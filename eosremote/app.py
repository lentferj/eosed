# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
#
# This file is part of eosremote. Original work. GPL-2.0-or-later.
#
# The general Textual-app shape (a title/status bar, modal arm-then-fire
# screens for destructive operations, --demo mode) follows the pattern
# established by the sibling k2kremote project, though none of its code is
# copied — this app has no LCD to mirror and no continuous refresh loop; it
# is a plain on-demand request/response editor.

"""eosremote — a Textual editor for the EOS remote editor protocol.

This is an EDITOR, not a screen mirror: it has no concept of the device's
own LCD and never presses front-panel buttons (that would need the
undocumented panel protocol — see docs/RESOLUTION_NOTES.md §3). It browses
presets, and reads/writes individual parameters by id via the documented
protocol in :mod:`eos.messages`.

Four panes, left to right: **Preset** (paged catalog browser) → **Voice**
(every voice of the selected preset) → **Parameters** (the selected voice's
params, or the preset's GLOBAL params if no voice is selected) →
**Samples** (which raw sample(s) the selection actually uses — the whole
preset's if no voice is selected, just that voice's otherwise). "Samples"
here is a *derived* view, not a browsable bank: this protocol has no
generic parameter access to a raw sample's own properties (loop points,
root key, sample rate — see docs/RESOLUTION_NOTES.md §10), only to a
voice's Sample Zone fields (``E4_GEN_SAMPLE`` and friends), which is what
this pane resolves down to a sample number + name.

All MIDI I/O runs in a background thread (Textual's ``@work(thread=True)``)
serialized by ``self._bridge_lock`` — :class:`eos.bridge.EosBridge` is not
thread-safe, and nothing here may issue two requests on the same connection
concurrently.

**Write actions (parameter edits, rename, the Master menu) are gated behind
``allow_write``**, which defaults to on for ``--demo`` and off for real
hardware unless ``--allow-write`` is passed — no write path has been
hardware-verified as thoroughly as the read paths yet (see TODO.md). The
Master menu's destructive operations (Delete Preset, Erase RAM Bank/Presets/
Samples) are never bound to a single keypress: they require an explicit
arm-then-fire confirmation in :class:`MasterScreen`.
"""

from __future__ import annotations

import argparse
import math
import threading
from typing import Callable, Dict, List, Optional, Tuple

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import DataTable, Footer, Header, Input, Static

from eos import bridge as bridge_mod
from eos import messages as m
from eos import params as p
from eosremote.demo import DemoBridge

# The preset page size is not a fixed constant: it's recomputed from how many
# rows the presets pane can actually show, so a taller terminal displays more
# presets per page instead of leaving blank space below a fixed-size list.
# Each unit is one sequential MIDI round-trip (eos.bridge.EosBridge.catalog_presets
# has no batched "give me every name" command), so the multiplier is a buffer
# against small resizes, not "fetch everything visible plus 50% margin of error";
# BROWSER_RESIZE_SETTLE debounces a resize drag so it doesn't re-fetch on every frame.
BROWSER_MIN_WINDOW = 16
BROWSER_FETCH_MULTIPLIER = 1.5
BROWSER_RESIZE_SETTLE = 0.4

# The full PRESET_SELECT wire range (spec'd 0-999), not the 0-127 default
# catalog_presets/catalog_samples use elsewhere in this codebase. That
# smaller default matches what a full sweep happened to cover on one test
# bank, not a proven capacity limit — live-confirmed on a different real
# bank to actually hold presets past 127 (up to at least 269). Silently
# under-scanning here would give a confidently *wrong* answer for exactly
# the question this feature exists to answer, which is worse than it just
# taking longer.
SAMPLE_USAGE_SCAN_RANGE = range(0, 1000)

# Live-tested: a full sweep of the above took ~4 minutes on a bank with
# real presets past 269. Default: bail out after this many *consecutive*
# no-voices presets (a strong "past the real data" signal, not a certainty
# — a bank with an unusually large deliberate gap could have real presets
# past the stop point that this would then miss). Overridable in
# config.toml (see eos.bridge.load_sample_usage_early_stop) to a specific
# number, or to "fullscan" to disable early-stop entirely.
SAMPLE_USAGE_EARLY_STOP_DEFAULT = 10

# Colors lifted from the E4XT Ultra's own front-panel logo/fascia: the black
# chassis, the red "4XT" badge, its cream outline/lettering, and the brushed
# aluminum control-panel band (reused here for $panel, same as the hardware's
# button row).
E4XT_THEME = Theme(
    name="e4xt",
    primary="#DCD5B4",
    secondary="#7C8591",
    accent="#C8102E",
    warning="#D9A441",
    error="#B0202B",
    success="#6B9B5E",
    foreground="#E7E2CC",
    background="#0A0A0B",
    surface="#18181A",
    panel="#6B7280",
    dark=True,
)

_PRESET_SELECT = p.lookup("PRESET_SELECT").id
_VOICE_SELECT = p.lookup("VOICE_SELECT").id
_LINK_SELECT = p.lookup("LINK_SELECT").id
_SAMPLE_ZONE_SELECT = p.lookup("SAMPLE_ZONE_SELECT").id
_GEN_SAMPLE = p.lookup("E4_GEN_SAMPLE").id


def _group_param_ids(group: str) -> List[int]:
    prefix = {"voice": "voice.", "global": "global", "link": "link"}[group]
    return sorted(pid for pid, param in p.PARAMETERS.items() if param.group.startswith(prefix))


_MULTISAMPLE_SENTINEL = 0x3FFF  # spec: voice-level E4_GEN_SAMPLE == this means multisample
_NO_SUCH_VOICE_MARKER = 0x3FFE  # empirically: this voice index does not exist on this preset
_MAX_ZONE_SCAN = 32  # safety cap only — see the docstring below
_MAX_VOICE_SCAN = 64  # safety cap only — preset_num_voices cannot be trusted at all, see below


class _BankState:
    """One catalog's browser bookmark: which page is showing, and the range
    + result of the last hardware fetch (reused when shrinking a resize or
    switching back to this bank, instead of re-scanning names already in
    hand)."""

    def __init__(self) -> None:
        self.window_start = 0
        self.cache_range: Optional[range] = None
        self.cache: Dict[int, str] = {}


def _voice_sample_info(bridge, preset: int, voice: int) -> Optional[Tuple[int, List[int]]]:
    """Best-effort: (zone count, [raw sample number(s)]) for one voice, or
    ``None`` if this voice index doesn't exist on this preset at all.

    Deliberately does NOT use ``EosBridge.voice_num_szones`` — confirmed live
    (docs/RESOLUTION_NOTES.md §11) to disagree with the real zone count in a
    preset/voice-dependent way with no consistent formula, echoing the
    sibling mpc2emu project's independent finding that this device family's
    analogous on-disk "n_zones" field is equally unreliable/redundant. Nor
    ``EosBridge.preset_num_voices`` to decide how many voices to walk — the
    exact same failure mode was later found there too (docs/RESOLUTION_
    NOTES.md §12): its raw wire value is not off by a fixed constant either,
    just usually looked that way from too few data points.

    Instead: a voice's own (VOICE_SELECT-scoped) E4_GEN_SAMPLE reads one of
    three things, empirically consistent across every case tested — the
    spec's 3FFFh multisample sentinel; the device's own (undocumented but
    consistent) 3FFEh "no such voice" signal, returned as ``None`` for the
    caller to stop walking voice indices on; or, for an ordinary
    single-sample voice, the real sample number directly. Zones (for a
    multisample voice) are read one at a time (SAMPLE_ZONE_SELECT) starting
    at 0 until one reads E4_GEN_SAMPLE=0 — empirically the clean, consistent
    signature of "past the real zones" (as opposed to garbage) in every
    case tested — capped at _MAX_ZONE_SCAN as a safety bound, not a trusted
    count. Callers walk voice indices the same way, capped at
    _MAX_VOICE_SCAN, also not a trusted count.
    """
    bridge.set_parameter(_VOICE_SELECT, voice)
    voice_level_sample = bridge.get_parameter(_GEN_SAMPLE)
    if voice_level_sample == _NO_SUCH_VOICE_MARKER:
        return None
    if voice_level_sample != _MULTISAMPLE_SENTINEL:
        return 1, [voice_level_sample]
    numbers = []
    for zone in range(_MAX_ZONE_SCAN):
        bridge.set_parameter(_SAMPLE_ZONE_SELECT, zone)
        sample = bridge.get_parameter(_GEN_SAMPLE)
        if sample == 0:
            break
        numbers.append(sample)
    return len(numbers), numbers


# --- modal screens ----------------------------------------------------------

class GotoScreen(ModalScreen[Optional[int]]):
    """Ask for an integer in [low, high]; dismiss(None) on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, low: int, high: int):
        super().__init__()
        self._title = title
        self._low = low
        self._high = high

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"{self._title}  [{self._low}-{self._high}]"),
            Input(placeholder=str(self._low), id="value"),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            value = int(event.value.strip())
        except ValueError:
            return
        if self._low <= value <= self._high:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditValueScreen(ModalScreen[Optional[int]]):
    """Show a parameter's current value + device range; ask for a new value."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, param: p.Parameter, current: int,
                minimum: int, maximum: int, default: Optional[int]):
        super().__init__()
        self.param = param
        self.current = current
        self.minimum = minimum
        self.maximum = maximum
        self.default = default

    def compose(self) -> ComposeResult:
        info = (f"{self.param.name} (id {self.param.id})\n"
               f"current {p.describe_value(self.param, self.current)}\n"
               f"range {self.minimum} .. {self.maximum}")
        if self.default is not None:
            info += f"   default {self.default}"
        if self.param.unit:
            info += f"   unit {self.param.unit}"
        yield Vertical(
            Static(info),
            Input(value=str(self.current), id="value"),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            value = int(event.value.strip())
        except ValueError:
            return
        if not (self.minimum <= value <= self.maximum):
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RenameScreen(ModalScreen[Optional[str]]):
    """Ask for a new (<=16 char) preset name."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_name: str):
        super().__init__()
        self.current_name = current_name

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Rename preset (current: {self.current_name!r})"),
            Input(value=self.current_name.strip(), id="value"),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MasterScreen(ModalScreen[Optional[str]]):
    """Arm-then-fire menu for the destructive Master utilities.

    Deliberately requires two keypresses (arm, then Enter to fire) rather
    than binding any single key to a destructive action — see
    DISCLAIMER.md / CLAUDE.md's hardware rules.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("enter", "fire", "Fire", show=False)]

    _ACTIONS = {
        "1": ("delete_preset", "Delete preset {preset}"),
        "2": ("erase_bank", "Erase current RAM bank"),
        "3": ("erase_all_presets", "Erase ALL RAM presets"),
        "4": ("erase_all_samples", "Erase ALL RAM samples"),
    }

    def __init__(self, preset: Optional[int]):
        super().__init__()
        self.preset = preset
        self.armed: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Vertical(Static(id="body"), id="dialog")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        lines = ["Master functions — press a number to ARM, Enter to FIRE, Escape to cancel.", ""]
        for key, (action, label) in self._ACTIONS.items():
            if action == "delete_preset" and self.preset is None:
                lines.append(f"  {key}) {label.format(preset='(none selected)')}  [unavailable]")
                continue
            marker = ">" if self.armed == action else " "
            lines.append(f"{marker} {key}) {label.format(preset=self.preset)}")
        if self.armed:
            lines.append("")
            lines.append(f"ARMED: {self.armed} — press Enter to FIRE.")
        self.query_one("#body", Static).update("\n".join(lines))

    def on_key(self, event) -> None:
        if event.key in self._ACTIONS:
            action, _ = self._ACTIONS[event.key]
            if action == "delete_preset" and self.preset is None:
                return
            self.armed = action
            self._refresh()

    def action_fire(self) -> None:
        if self.armed:
            self.dismiss(self.armed)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _FillWidthDataTable(DataTable):
    """A DataTable whose last column stretches to fill the widget's width.

    Textual sizes columns to their content only (``auto_width``). With short
    content — e.g. the presets table's "#"/"Name" columns — that leaves the
    row highlight pinned to a fixed width instead of tracking the pane as the
    terminal is resized, unlike the params table, whose longer parameter
    names happen to already reach the pane's edge at typical sizes.

    ``resize_callback``, if set, is invoked after every resize — used by the
    presets table to recompute how many presets it has room to show.
    """

    resize_callback: Optional[Callable[[], None]] = None

    def _stretch_last_column(self) -> None:
        columns = list(self.ordered_columns)
        if not columns:
            return
        *fixed_columns, last = columns
        padding = 2 * self.cell_padding
        fixed_width = sum(c.get_render_width(self) for c in fixed_columns)
        available = self.size.width - fixed_width - padding
        last.auto_width = False
        last.width = max(available, last.content_width)
        self._require_update_dimensions = True
        self.refresh()

    def on_resize(self, event) -> None:
        self._stretch_last_column()
        if self.resize_callback is not None:
            self.resize_callback()


# --- main app ----------------------------------------------------------------

class EosRemoteApp(App):
    CSS = """
    #dialog {
        width: 64; height: auto; border: round $accent; padding: 1 2;
        background: $surface; align: center middle;
    }
    #tables { height: 1fr; }
    #presets { width: 22%; height: 1fr; }
    #voices  { width: 13%; height: 1fr; }
    #params  { width: 40%; height: 1fr; }
    #samples { width: 25%; height: 1fr; }
    #status { height: 1; background: $panel; color: $text; padding: 0 1; }

    /* Compact view (see action_toggle_view): hide Voice/Samples, giving
       their space back to Preset/Parameters -- the original 2-pane layout. */
    #tables.compact #voices { display: none; }
    #tables.compact #samples { display: none; }
    #tables.compact #presets { width: 40%; }
    #tables.compact #params { width: 60%; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "show_presets_bank", "Presets"),
        Binding("s", "show_samples_bank", "Samples"),
        Binding("g", "goto", "Goto"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "edit_value", "Edit value", show=False),
        Binding("o", "rename", "Rename"),
        Binding("v", "browse_voices", "Voices"),
        Binding("l", "browse_links", "Links"),
        Binding("u", "find_sample_usage", "Find usage"),
        Binding("c", "clear_sample_usage_cache", "Clear usage cache"),
        Binding("e", "toggle_view", "Extended view"),
        Binding("escape", "back_to_preset", "Back to preset"),
        Binding("m", "master_menu", "Master"),
    ]

    def __init__(self, bridge, *, allow_write: bool, demo: bool,
                connect_kwargs: Optional[dict] = None):
        super().__init__()
        self.register_theme(E4XT_THEME)
        self.theme = "e4xt"
        self.bridge = bridge
        self.allow_write = allow_write
        self.demo = demo
        self._connect_kwargs = connect_kwargs or {}
        self._bridge_lock = threading.Lock()

        # Remembered across restarts in config.toml (see eos.bridge.load_
        # compact_view/save_compact_view) — but not for --demo, matching the
        # project's "demo touches no real local state" convention (also
        # avoids the exact test-pollution bug docs/RESOLUTION_NOTES.md §7
        # already caught once for the MIDI port cache in this same file).
        # Fresh install / no config yet -> defaults to the compact 2-pane
        # view.
        self._view_config_path = self._connect_kwargs.get("config_path", bridge_mod.DEFAULT_CONFIG_PATH)
        stored_view = None if self.demo else bridge_mod.load_compact_view(self._view_config_path)
        self.compact_view: bool = True if stored_view is None else stored_view

        self.current_preset: Optional[int] = None
        self.current_sample: Optional[int] = None
        self.current_voice: Optional[int] = None
        self.current_link: Optional[int] = None

        self.bank: str = "preset"  # "preset" or "sample" — which catalog the left pane shows
        self.browser_window = BROWSER_MIN_WINDOW
        self._resize_timer = None
        self._bank_states: Dict[str, _BankState] = {"preset": _BankState(), "sample": _BankState()}

        # What's currently shown in the Parameters pane, so a value edit can
        # refresh the same set without re-deriving "global vs. this voice".
        self._current_param_ids: List[int] = []
        self._current_param_label: str = "global"

        # Cached result of the last _load_preset_overview fetch (one preset
        # of "walk every voice/zone" work) — reused when navigating back
        # from a voice/link to the *same* preset instead of re-walking every
        # voice/zone over MIDI again for data that hasn't changed. Cleared
        # by anything that could actually invalidate it: a parameter write
        # (could change which sample a zone points at) or a Master action.
        self._preset_overview_cache: Optional[
            Tuple[int, int, Dict[int, int], List[int], Dict[int, int],
                 List[Tuple[int, str, str]]]] = None

        # Opt-in full-bank reverse lookup ("which presets use this sample")
        # — see action_find_sample_usage. Deliberately not automatic: a full
        # sweep is a per-voice/zone walk repeated across every preset, easily
        # a minute or more of sequential MIDI round-trips. A *complete* sweep
        # builds a reusable {sample: [(preset, name), ...]} index for every
        # sample it saw along the way, not just the one that triggered it —
        # every later lookup is then instant, no MIDI at all, until
        # something is actually written (same invalidation as the preset-
        # overview cache above). A cancelled/partial sweep's findings are
        # shown once but not persisted as this index — no way to tell "not
        # found" from "not scanned yet" for whatever it didn't reach.
        self._sample_scan_active = False
        self._cancel_sample_scan = False
        self._sample_usage_index: Dict[int, List[Tuple[int, str]]] = {}
        self._sample_usage_scanned_range: Optional[range] = None
        # None = "fullscan" (early-stop disabled); an int = that many
        # consecutive no-voices presets before bailing. Not read for --demo,
        # same "demo touches no real local state" reasoning as compact_view.
        configured_gap = None if self.demo else bridge_mod.load_sample_usage_early_stop(
            self._view_config_path)
        if configured_gap == "fullscan":
            self._sample_usage_early_stop_gap: Optional[int] = None
        elif isinstance(configured_gap, int):
            self._sample_usage_early_stop_gap = configured_gap
        else:
            self._sample_usage_early_stop_gap = SAMPLE_USAGE_EARLY_STOP_DEFAULT

        self.last_status: str = ""  # exposed for tests

    def _bank_state(self, bank: Optional[str] = None) -> _BankState:
        return self._bank_states[bank if bank is not None else self.bank]

    # -- layout ---------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Horizontal(
            _FillWidthDataTable(id="presets"),
            _FillWidthDataTable(id="voices"),
            _FillWidthDataTable(id="params"),
            _FillWidthDataTable(id="samples"),
            id="tables",
            classes="compact" if self.compact_view else "",
        )
        yield Static("", id="status")
        yield Footer()

    def action_toggle_view(self) -> None:
        self.compact_view = not self.compact_view
        tables = self.query_one("#tables")
        if self.compact_view:
            tables.add_class("compact")
        else:
            tables.remove_class("compact")
        if not self.demo:
            bridge_mod.save_compact_view(self.compact_view, self._view_config_path)
        self.set_status(f"view: {'compact' if self.compact_view else 'extended'}")

    def on_mount(self) -> None:
        self.title = "eosremote"
        presets_table = self.query_one("#presets", _FillWidthDataTable)
        presets_table.add_columns("#", "Name")
        presets_table.cursor_type = "row"
        presets_table.call_after_refresh(presets_table._stretch_last_column)
        presets_table.resize_callback = self._on_browser_resized

        voices_table = self.query_one("#voices", _FillWidthDataTable)
        voices_table.add_columns("Voice", "Zones")
        voices_table.cursor_type = "row"
        voices_table.call_after_refresh(voices_table._stretch_last_column)

        params_table = self.query_one("#params", _FillWidthDataTable)
        params_table.add_columns("Id", "Name", "Value", "Unit")
        params_table.cursor_type = "row"
        params_table.call_after_refresh(params_table._stretch_last_column)

        samples_table = self.query_one("#samples", _FillWidthDataTable)
        samples_table.add_columns("Sample", "Name", "Used by")
        samples_table.cursor_type = "row"
        samples_table.call_after_refresh(samples_table._stretch_last_column)

        # Deferred like the column stretch above: at this exact point in
        # on_mount, the pane hasn't had its first real layout pass yet, so
        # measuring it now would see a placeholder size, not the laid-out
        # one — nothing else re-triggers this before the first fetch.
        self.call_after_refresh(self._start_after_layout)

    def _start_after_layout(self) -> None:
        self.browser_window = self._desired_browser_window()
        if self.bridge is None:
            self.set_status("connecting ...")
            self._connect()
        else:
            self.set_status(f"connected: {self.bridge.description}"
                            if hasattr(self.bridge, "description") else "connected (demo)")
            self.load_bank_page("preset", 0)

    def on_unmount(self) -> None:
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception:
                pass

    def set_status(self, text: str) -> None:
        self.last_status = text  # exposed for tests, matching k2kremote's convention
        try:
            self.query_one("#status", Static).update(text)
        except Exception:
            pass

    # -- dynamic preset page size -------------------------------------------
    def _desired_browser_window(self) -> int:
        table = self.query_one("#presets", _FillWidthDataTable)
        capacity = max(1, table.size.height - 1)  # -1 for the header row
        return max(BROWSER_MIN_WINDOW, math.ceil(capacity * BROWSER_FETCH_MULTIPLIER))

    def _on_browser_resized(self) -> None:
        # Debounced: a window drag fires many resize events, and each preset
        # page load is a sequential per-preset MIDI round-trip — re-fetching
        # on every intermediate frame would hammer the device for nothing.
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(BROWSER_RESIZE_SETTLE, self._settle_browser_resize)

    def _settle_browser_resize(self) -> None:
        self._resize_timer = None
        new_window = self._desired_browser_window()
        if new_window == self.browser_window:
            return
        bank = self.bank
        state = self._bank_state(bank)
        start = state.window_start
        cache_range = state.cache_range
        shrinking_within_cache = (
            new_window < self.browser_window and cache_range is not None
            and cache_range.start == start and cache_range.stop >= start + new_window)
        self.browser_window = new_window
        if shrinking_within_cache:
            # Every name the smaller page needs is already in hand from the
            # last fetch — just show fewer of them, no need to re-hit the
            # device for a strict subset of what it already gave us.
            self._show_bank_page(bank, start, new_window, state.cache)
        elif self.bridge is not None:
            self.load_bank_page(bank, start)

    # -- connection -------------------------------------------------------
    @work(thread=True)
    def _connect(self) -> None:
        kwargs = self._connect_kwargs
        try:
            if kwargs.get("port"):
                bridge = bridge_mod.EosBridge.standard(
                    kwargs["port"], device_id=kwargs["device_id"], timeout=kwargs["timeout"])
            else:
                bridge = bridge_mod.EosBridge.autodetect(
                    device_id=kwargs["device_id"], timeout=kwargs["timeout"],
                    config_path=kwargs.get("config_path", bridge_mod.DEFAULT_CONFIG_PATH),
                    on_try=lambda name: self.call_from_thread(self.set_status, f"trying {name} ..."))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"connection failed: {exc}")
            return
        self.bridge = bridge
        self.call_from_thread(self.set_status, f"connected: {bridge.description}")
        self.call_from_thread(self.load_bank_page, "preset", 0)

    # -- bank browser (presets or samples) -----------------------------------
    @staticmethod
    def _catalog_fn(bridge, bank: str):
        return bridge.catalog_presets if bank == "preset" else bridge.catalog_samples

    @work(thread=True)
    def load_bank_page(self, bank: str, start: int, cursor: Optional[int] = None) -> None:
        if self.bridge is None:
            return
        # Captured once up front: self.browser_window may change concurrently
        # (a resize settling mid-fetch) — the fetch and the display of its
        # results must agree on the same window size.
        window = self.browser_window
        label = "presets" if bank == "preset" else "samples"
        self.call_from_thread(self.set_status, f"loading {label} {start}-{start + window - 1} ...")
        try:
            with self._bridge_lock:
                names = self._catalog_fn(self.bridge, bank)(range(start, start + window))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._show_bank_page, bank, start, window, names, None, cursor)

    def _show_bank_page(self, bank: str, start: int, window: int, names: Dict[int, str],
                        status: Optional[str] = None, cursor: Optional[int] = None) -> None:
        # ``status`` lets a caller that just performed an action (rename, a
        # Master fire) show its own confirmation instead of the generic
        # "presets/samples N-M" message this refresh would otherwise set —
        # without it, two independently-scheduled worker completions would
        # race to set the status bar and the confirmation could vanish
        # before it's ever seen.
        state = self._bank_state(bank)
        state.window_start = start
        state.cache_range = range(start, start + window)
        state.cache = names
        if bank != self.bank:
            # A background refresh for the bank the user has since switched
            # away from — its cache is now current, but don't touch what's
            # on screen (that belongs to the other bank).
            return
        table = self.query_one("#presets", _FillWidthDataTable)
        table.clear()
        for number in range(start, start + window):
            table.add_row(str(number), names.get(number, ""), key=str(number))
        table.call_after_refresh(table._stretch_last_column)
        # Rebuilding the table resets the cursor to row 0 (the window's
        # first item) — without this, "goto 125" would visibly land on
        # whatever item happens to be first in the 112-127 window instead
        # of highlighting 125 itself.
        if cursor is not None and start <= cursor < start + window:
            table.move_cursor(row=cursor - start)
        label = "presets" if bank == "preset" else "samples"
        self.set_status(status if status is not None else f"{label} {start}-{start + window - 1}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is None:
            return
        if event.data_table.id == "presets":
            if self.bank == "preset":
                self.select_preset(int(event.row_key.value))
            else:
                self.select_sample(int(event.row_key.value))
        elif event.data_table.id == "voices":
            self.select_voice(int(event.row_key.value))
        elif event.data_table.id == "params":
            self.action_edit_value()
        # "samples" (the derived used-by pane) is read-only — no action.

    def select_sample(self, sample: int) -> None:
        # Raw samples have no per-sample parameters in this protocol (see
        # docs/RESOLUTION_NOTES.md §10) — the closest thing, a voice's
        # Sample Zone fields, is reached via 'v' from a selected preset, not
        # from here. Still worth clearing whatever preset/voice detail was
        # previously shown and surfacing what little IS known about this
        # sample, rather than leaving stale data on screen with a message
        # that reads like a refused edit (selecting a sample isn't a
        # request to edit it). Also clears the Samples pane specifically —
        # a previous sample's "used by" scan result (see action_find_
        # sample_usage) would otherwise linger looking like it's about
        # *this* sample.
        self.current_sample = sample
        name = self._bank_state("sample").cache.get(sample, "")
        self._current_param_ids = []  # nothing here is a real, editable parameter
        self._current_param_label = f"sample {sample}"
        table = self.query_one("#params", _FillWidthDataTable)
        table.clear()
        table.add_row("—", "Sample number", str(sample), "", key="sample_number")
        table.add_row("—", "Name", name, "", key="sample_name")
        table.call_after_refresh(table._stretch_last_column)
        self.query_one("#samples", _FillWidthDataTable).clear()
        self.set_status(f"sample {sample} {name!r} — 'u' checks which presets use it")

    def _switch_bank(self, bank: str) -> None:
        if bank == self.bank:
            return
        self.bank = bank
        if bank == "sample":
            # The Voice/Parameters/Samples-used-by panes describe a
            # *preset*, which isn't in scope while browsing the raw Sample
            # bank — clear them immediately rather than leaving stale
            # preset/voice data on screen until a sample happens to be
            # selected.
            self.query_one("#voices", _FillWidthDataTable).clear()
            self.query_one("#params", _FillWidthDataTable).clear()
            self.query_one("#samples", _FillWidthDataTable).clear()
            self._current_param_ids = []
            self._current_param_label = "global"
        else:
            self._restore_preset_detail_panes()
        state = self._bank_state(bank)
        desired_range = range(state.window_start, state.window_start + self.browser_window)
        if state.cache_range == desired_range:
            self._show_bank_page(bank, state.window_start, self.browser_window, state.cache)
        elif self.bridge is not None:
            self.load_bank_page(bank, state.window_start)

    def _restore_preset_detail_panes(self) -> None:
        # Switching back to the Preset bank: current_preset/current_voice/
        # current_link were never cleared (only the panes were, when we
        # switched away), so this puts back whatever was last shown there —
        # the preset overview reuses its cache when possible, same as
        # action_back_to_preset.
        if self.current_preset is None:
            return
        if self.current_voice is not None:
            self._load_voice_detail(self.current_preset, self.current_voice)
        elif self.current_link is not None:
            self._load_link_detail(self.current_preset, self.current_link)
        else:
            self._show_or_reload_preset_overview()

    def _show_or_reload_preset_overview(self) -> None:
        cache = self._preset_overview_cache
        if cache is not None and cache[0] == self.current_preset:
            # Nothing about drilling into a voice/link (or switching Sample
            # bank and back) changes what the preset-level view would
            # recompute — reuse it instead of re-walking every voice/zone
            # over MIDI again.
            self._show_preset_overview(*cache)
        else:
            self._load_preset_overview(self.current_preset)

    def action_show_presets_bank(self) -> None:
        self._switch_bank("preset")

    def action_show_samples_bank(self) -> None:
        self._switch_bank("sample")

    def _current_item_name(self) -> str:
        table = self.query_one("#presets", DataTable)
        number = self.current_preset if self.bank == "preset" else self.current_sample
        try:
            row = table.get_row(str(number))
            return str(row[1])
        except Exception:
            return ""

    def action_goto(self) -> None:
        title = "Goto preset" if self.bank == "preset" else "Goto sample"
        self.push_screen(GotoScreen(title, 0, 999), self._on_goto_result)

    def _on_goto_result(self, number: Optional[int]) -> None:
        if number is None:
            return
        bank = self.bank
        state = self._bank_state(bank)
        window_start = (number // self.browser_window) * self.browser_window
        if window_start == state.window_start:
            # already showing the right window — just move the cursor,
            # no need to re-scan the same names again
            self.query_one("#presets", DataTable).move_cursor(row=number - window_start)
        else:
            self.load_bank_page(bank, window_start, cursor=number)
        if bank == "preset":
            self.select_preset(number)
        else:
            self.select_sample(number)

    def action_refresh(self) -> None:
        state = self._bank_state()
        self.load_bank_page(self.bank, state.window_start)
        if self.bank == "preset" and self.current_preset is not None:
            if self.current_voice is not None:
                self._load_voice_detail(self.current_preset, self.current_voice)
            elif self.current_link is not None:
                self._load_link_detail(self.current_preset, self.current_link)
            else:
                self._load_preset_overview(self.current_preset)

    # -- preset selection: voice list + global params + preset-wide samples --
    def select_preset(self, preset: int) -> None:
        self.current_preset = preset
        self.current_voice = None
        self.current_link = None
        self._load_preset_overview(preset)

    @work(thread=True)
    def _load_preset_overview(self, preset: int) -> None:
        self.call_from_thread(self.set_status, f"loading preset {preset} ...")
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                zone_counts: Dict[int, int] = {}
                by_voice: Dict[int, List[int]] = {}
                voice_count = 0
                for voice in range(_MAX_VOICE_SCAN):
                    info = _voice_sample_info(self.bridge, preset, voice)
                    if info is None:
                        break
                    zone_counts[voice] = info[0]
                    by_voice[voice] = info[1]
                    voice_count = voice + 1
                global_ids = _group_param_ids("global")
                global_values = self.bridge.get_parameters(global_ids)
                sample_rows = self._resolve_sample_rows(by_voice)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self._preset_overview_cache = (preset, voice_count, zone_counts,
                                       global_ids, global_values, sample_rows)
        self.call_from_thread(self._show_preset_overview, preset, voice_count, zone_counts,
                              global_ids, global_values, sample_rows)

    def _show_preset_overview(self, preset: int, voice_count: int, zone_counts: Dict[int, int],
                              ids: List[int], values: Dict[int, int],
                              sample_rows: List[Tuple[int, str, str]]) -> None:
        self._show_voices(voice_count, zone_counts)
        self._show_params(ids, values, "global")
        self._show_samples(sample_rows)
        self.set_status(f"preset {preset}: {voice_count} voice(s), {len(sample_rows)} sample(s) used")

    def _show_voices(self, voice_count: int, zone_counts: Dict[int, int]) -> None:
        table = self.query_one("#voices", _FillWidthDataTable)
        table.clear()
        for voice in range(voice_count):
            zones = zone_counts.get(voice, 1)
            zones_label = "single" if zones <= 1 else f"multi ({zones})"
            table.add_row(f"V{voice + 1}", zones_label, key=str(voice))
        table.call_after_refresh(table._stretch_last_column)

    def action_browse_voices(self) -> None:
        if self.current_preset is None:
            self.set_status("select a preset first")
            return
        self._start_browse_voices()

    @work(thread=True)
    def _start_browse_voices(self) -> None:
        # Reuse the already-known voice count from the current preset
        # overview when available, rather than re-walking voices just to
        # bound this modal's range (preset_num_voices cannot be trusted at
        # all — see _voice_sample_info's docstring / RESOLUTION_NOTES §12).
        cache = self._preset_overview_cache
        if cache is not None and cache[0] == self.current_preset:
            count = cache[1]
        else:
            try:
                with self._bridge_lock:
                    self.bridge.set_parameter(_PRESET_SELECT, self.current_preset)
                    count = 0
                    for voice in range(_MAX_VOICE_SCAN):
                        if _voice_sample_info(self.bridge, self.current_preset, voice) is None:
                            break
                        count += 1
            except Exception as exc:
                self.call_from_thread(self.set_status, f"error: {exc}")
                return
        if count <= 0:
            self.call_from_thread(self.set_status, "this preset has no voices")
            return
        self.call_from_thread(self._prompt_voice_index, count)

    def _prompt_voice_index(self, count: int) -> None:
        # The front panel numbers voices from 1 (V1..Vn) — confirmed on
        # hardware. Ask/display 1-based, store 0-based internally (that's
        # VOICE_SELECT's actual wire range).
        if count == 1:
            # Nothing to pick between — a prompt whose only valid answer is
            # "1" is just an extra keypress, not a real choice.
            self.select_voice(0)
            return

        def on_result(displayed: Optional[int]) -> None:
            if displayed is None:
                return
            self.select_voice(displayed - 1)
        self.push_screen(GotoScreen("Voice (as shown on the front panel, V1-Vn)", 1, count), on_result)

    # -- voice selection: voice params + that voice's samples ---------------
    def select_voice(self, voice: int) -> None:
        self.current_voice = voice
        self.current_link = None
        self._load_voice_detail(self.current_preset, voice)

    @work(thread=True)
    def _load_voice_detail(self, preset: int, voice: int) -> None:
        self.call_from_thread(self.set_status, f"loading voice V{voice + 1} ...")
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                info = _voice_sample_info(self.bridge, preset, voice)
                numbers = [] if info is None else info[1]
                # _voice_sample_info leaves SAMPLE_ZONE_SELECT pointed at the
                # last zone it read; re-selecting the voice resets that (spec:
                # zone selection "will get reset if you select a new Voice")
                # so the group read below is the voice's own scope, not one
                # zone's — otherwise voice-only fields (CTUNE, XPOSE, RT_*)
                # come back as the spec's -1/"not applicable" sentinel.
                self.bridge.set_parameter(_VOICE_SELECT, voice)
                voice_ids = _group_param_ids("voice")
                voice_values = self.bridge.get_parameters(voice_ids)
                sample_rows = self._resolve_sample_rows({voice: numbers})
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._show_voice_detail, voice, voice_ids, voice_values, sample_rows)

    def _show_voice_detail(self, voice: int, ids: List[int], values: Dict[int, int],
                           sample_rows: List[Tuple[int, str, str]]) -> None:
        self._show_params(ids, values, f"voice V{voice + 1}")
        self._show_samples(sample_rows)
        self.set_status(f"preset {self.current_preset}: voice V{voice + 1}, "
                        f"{len(sample_rows)} sample(s) used")

    def action_browse_links(self) -> None:
        if self.current_preset is None:
            self.set_status("select a preset first")
            return
        self._start_browse_links()

    @work(thread=True)
    def _start_browse_links(self) -> None:
        try:
            with self._bridge_lock:
                count = self.bridge.preset_num_links(self.current_preset)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        if count <= 0:
            self.call_from_thread(self.set_status, "this preset has no links")
            return
        self.call_from_thread(self._prompt_link_index, count)

    def _prompt_link_index(self, count: int) -> None:
        # Assumed 1-based to match the front panel's voice numbering
        # (V1..Vn, confirmed on hardware) — NOT independently confirmed for
        # links specifically. Correct this if the panel shows links as L0..
        if count == 1:
            self.select_link(0)
            return

        def on_result(displayed: Optional[int]) -> None:
            if displayed is None:
                return
            self.select_link(displayed - 1)
        self.push_screen(GotoScreen("Link (assumed 1-based like voices)", 1, count), on_result)

    # -- link selection: link params (no Samples-pane concept for links) ----
    def select_link(self, link: int) -> None:
        self.current_voice = None
        self.current_link = link
        self._load_link_detail(self.current_preset, link)

    @work(thread=True)
    def _load_link_detail(self, preset: int, link: int) -> None:
        self.call_from_thread(self.set_status, f"loading link L{link + 1} ...")
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                self.bridge.set_parameter(_LINK_SELECT, link)
                link_ids = _group_param_ids("link")
                link_values = self.bridge.get_parameters(link_ids)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._show_link_detail, link, link_ids, link_values)

    def _show_link_detail(self, link: int, ids: List[int], values: Dict[int, int]) -> None:
        self._show_params(ids, values, f"link L{link + 1}")

    def action_back_to_preset(self) -> None:
        if self._sample_scan_active:
            self._cancel_sample_scan = True
            self.set_status("cancelling sample usage scan ...")
            return
        if self.current_preset is None or (self.current_voice is None and self.current_link is None):
            return
        self.current_voice = None
        self.current_link = None
        self._show_or_reload_preset_overview()

    # -- samples pane: resolve raw sample numbers to names -------------------
    def _resolve_sample_rows(self, by_voice: Dict[int, List[int]]) -> List[Tuple[int, str, str]]:
        # Assumes self._bridge_lock is already held (called from within the
        # same worker/lock scope as the voice/param reads above).
        # A set, not a list: a voice with several zones that happen to share
        # one underlying sample (a very normal pattern -- different key
        # ranges reusing the same recording) must list that voice once, not
        # once per zone.
        users: Dict[int, set] = {}
        for voice, numbers in by_voice.items():
            for number in numbers:
                users.setdefault(number, set()).add(voice)
        rows = []
        for number in sorted(users):
            try:
                name = self.bridge.get_sample_name(number)
            except Exception:
                name = ""
            voices_label = ",".join(f"V{v + 1}" for v in sorted(users[number]))
            rows.append((number, name, voices_label))
        return rows

    def _show_samples(self, rows: List[Tuple[int, str, str]]) -> None:
        table = self.query_one("#samples", _FillWidthDataTable)
        table.clear()
        for number, name, voices_label in rows:
            table.add_row(str(number), name, voices_label, key=str(number))
        table.call_after_refresh(table._stretch_last_column)

    # -- reverse lookup: which presets use this sample (opt-in, expensive) --
    def action_find_sample_usage(self) -> None:
        if self.bank != "sample" or self.current_sample is None:
            self.set_status("select a sample first")
            return
        if self._sample_scan_active:
            self.set_status("a scan is already running ('escape' to cancel)")
            return
        if self._sample_usage_scanned_range == SAMPLE_USAGE_SCAN_RANGE:
            # A complete sweep already built the index — instant lookup,
            # no MIDI at all.
            matches = self._sample_usage_index.get(self.current_sample, [])
            self._show_sample_usage_results(self.current_sample, matches, note=" (cached)")
            return
        self._start_find_sample_usage(self.current_sample)

    def action_clear_sample_usage_cache(self) -> None:
        if self._sample_scan_active:
            self.set_status("a scan is running ('escape' to cancel first)")
            return
        if not self._sample_usage_index and self._sample_usage_scanned_range is None:
            self.set_status("no sample-usage cache to clear")
            return
        self._sample_usage_index = {}
        self._sample_usage_scanned_range = None
        self.set_status("sample-usage cache cleared — next 'u' re-scans")

    @work(thread=True)
    def _start_find_sample_usage(self, sample: int) -> None:
        self._sample_scan_active = True
        self._cancel_sample_scan = False
        last = SAMPLE_USAGE_SCAN_RANGE.stop - 1
        gap = self._sample_usage_early_stop_gap  # None = fullscan, no early stop
        # Every sample each preset uses is recorded, not just this one —
        # a complete (or early-stopped, see below) sweep becomes a reusable
        # index for any future lookup.
        index: Dict[int, List[Tuple[int, str]]] = {}
        consecutive_empty = 0
        stopped_early = False
        stopped_at = SAMPLE_USAGE_SCAN_RANGE.start
        try:
            with self._bridge_lock:
                for preset in SAMPLE_USAGE_SCAN_RANGE:
                    stopped_at = preset
                    if self._cancel_sample_scan:
                        break
                    self.call_from_thread(
                        self.set_status,
                        f"scanning for sample usage: preset {preset}/{last} "
                        f"(builds a reusable index — 'escape' to cancel) ...")
                    found_voices = False
                    try:
                        self.bridge.set_parameter(_PRESET_SELECT, preset)
                        used_samples = set()
                        for voice in range(_MAX_VOICE_SCAN):
                            info = _voice_sample_info(self.bridge, preset, voice)
                            if info is None:
                                break
                            found_voices = True
                            used_samples.update(info[1])
                        if used_samples:
                            name = self.bridge.get_preset_name(preset)
                            for used in used_samples:
                                index.setdefault(used, []).append((preset, name))
                    except Exception:
                        pass  # best-effort, same convention as catalog_presets -- counts as "empty" below
                    if found_voices:
                        consecutive_empty = 0
                    else:
                        consecutive_empty += 1
                        if gap is not None and consecutive_empty >= gap:
                            stopped_early = True
                            break
        finally:
            self._sample_scan_active = False
        cancelled = self._cancel_sample_scan
        if not cancelled:
            # Early-stopping is a deliberate, accepted tradeoff (see
            # SAMPLE_USAGE_EARLY_STOP_DEFAULT) -- unlike a user cancellation,
            # its result is still trusted as the cache for future lookups.
            self._sample_usage_index = index
            self._sample_usage_scanned_range = SAMPLE_USAGE_SCAN_RANGE
        if cancelled:
            note = f" (cancelled at preset {stopped_at}, partial)"
        elif stopped_early:
            note = f" (stopped at preset {stopped_at} after {gap} consecutive empty presets)"
        else:
            note = f" (full sweep to preset {stopped_at})"
        self.call_from_thread(
            self._show_sample_usage_results, sample, index.get(sample, []), note)

    def _show_sample_usage_results(self, sample: int, matches: List[Tuple[int, str]],
                                   note: str = "") -> None:
        table = self.query_one("#samples", _FillWidthDataTable)
        table.clear()
        for preset, name in matches:
            table.add_row(str(preset), name, "", key=str(preset))
        table.call_after_refresh(table._stretch_last_column)
        where = ", ".join(f"{preset} {name!r}" for preset, name in matches[:5])
        if len(matches) > 5:
            where += f", +{len(matches) - 5} more — see extended view ('e')"
        summary = f"sample {sample}: used by {len(matches)} preset(s){note}"
        self.set_status(f"{summary} — {where}" if matches else summary)

    # -- parameter table ------------------------------------------------
    def _show_params(self, ids: List[int], values: Dict[int, int], label: str) -> None:
        self._current_param_ids = ids
        self._current_param_label = label
        table = self.query_one("#params", _FillWidthDataTable)
        table.clear()
        for pid in ids:
            param = p.PARAMETERS[pid]
            value = values.get(pid)
            display = "" if value is None else p.describe_value(param, value)
            table.add_row(str(pid), param.name, display, param.unit or "", key=str(pid))
        table.call_after_refresh(table._stretch_last_column)
        self.set_status(f"preset {self.current_preset}: {label} parameters ({len(ids)})")

    # -- editing a parameter value ------------------------------------------
    def action_edit_value(self) -> None:
        if self.current_preset is None:
            return
        table = self.query_one("#params", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return
        try:
            param_id = int(row_key.value)
        except ValueError:
            return  # not a real parameter row (e.g. the sample-info display)
        self._start_edit(param_id)

    @work(thread=True)
    def _start_edit(self, param_id: int) -> None:
        param = p.PARAMETERS[param_id]
        try:
            with self._bridge_lock:
                current = self.bridge.get_parameter(param_id)
                rng = self.bridge.get_parameter_range(param_id)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._prompt_edit, param, current, rng)

    def _prompt_edit(self, param: p.Parameter, current: int, rng: m.ParameterRange) -> None:
        if not self.allow_write:
            self.set_status("writes disabled (pass --allow-write to enable)")
            return

        def on_result(new_value: Optional[int]) -> None:
            if new_value is None:
                return
            self._apply_edit(param.id, new_value)

        self.push_screen(
            EditValueScreen(param, current, rng.minimum, rng.maximum, rng.default), on_result)

    def _invalidate_write_sensitive_caches(self) -> None:
        # Any real write could change which sample a voice/zone points at
        # (or, for a Master action, far more) — neither the cached preset
        # overview nor the sample-usage index can be trusted as unchanged
        # after one.
        self._preset_overview_cache = None
        self._sample_usage_index = {}
        self._sample_usage_scanned_range = None

    @work(thread=True)
    def _apply_edit(self, param_id: int, value: int) -> None:
        ids = self._current_param_ids
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(param_id, value)
                values = self.bridge.get_parameters(ids)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self._invalidate_write_sensitive_caches()
        self.call_from_thread(self._show_params, ids, values, self._current_param_label)
        self.call_from_thread(self.set_status, f"set id {param_id} = {value}")

    # -- rename ---------------------------------------------------------
    def action_rename(self) -> None:
        number = self.current_preset if self.bank == "preset" else self.current_sample
        if number is None:
            kind = "preset" if self.bank == "preset" else "sample"
            self.set_status(f"select a {kind} first")
            return
        if not self.allow_write:
            self.set_status("writes disabled (pass --allow-write to enable)")
            return
        self.push_screen(RenameScreen(self._current_item_name()), self._on_rename_result)

    def _on_rename_result(self, name: Optional[str]) -> None:
        if name is None:
            return
        number = self.current_preset if self.bank == "preset" else self.current_sample
        self._apply_rename(self.bank, number, name)

    @work(thread=True)
    def _apply_rename(self, bank: str, number: int, name: str) -> None:
        state = self._bank_state(bank)
        start, window = state.window_start, self.browser_window
        try:
            with self._bridge_lock:
                if bank == "preset":
                    self.bridge.set_preset_name(number, name)
                else:
                    self.bridge.set_sample_name(number, name)
                names = self._catalog_fn(self.bridge, bank)(range(start, start + window))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        # A preset rename only touches the name, not voice/zone/sample data
        # — but the sample-usage index stores preset *names* too, and every
        # write invalidates caches uniformly on principle rather than
        # reasoning out which specific writes are "safe" to leave be.
        self._invalidate_write_sensitive_caches()
        kind = "preset" if bank == "preset" else "sample"
        # One combined UI update, not two racing ones — see _show_bank_page.
        self.call_from_thread(self._show_bank_page, bank, start, window, names,
                              f"renamed {kind} {number} to {name!r}")

    # -- master (destructive) menu ---------------------------------------
    def action_master_menu(self) -> None:
        self.push_screen(MasterScreen(self.current_preset), self._on_master_result)

    def _on_master_result(self, action: Optional[str]) -> None:
        if action is None:
            return
        if not self.allow_write:
            self.set_status("writes disabled (pass --allow-write to enable)")
            return
        self._fire_master_action(action)

    @work(thread=True)
    def _fire_master_action(self, action: str) -> None:
        bank = self.bank
        state = self._bank_state(bank)
        start, window = state.window_start, self.browser_window
        try:
            with self._bridge_lock:
                if action == "delete_preset":
                    self.bridge.delete_preset(self.current_preset)
                elif action == "erase_bank":
                    self.bridge.erase_ram_bank()
                elif action == "erase_all_presets":
                    self.bridge.erase_all_ram_presets()
                elif action == "erase_all_samples":
                    self.bridge.erase_all_ram_samples()
                names = self._catalog_fn(self.bridge, bank)(range(start, start + window))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self._invalidate_write_sensitive_caches()  # destructive — nothing cached can be trusted now
        # One combined UI update, not two racing ones — see _show_bank_page.
        self.call_from_thread(self._show_bank_page, bank, start, window, names, f"fired: {action}")


# --- CLI entry ---------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="eosremote", description="Textual editor for the EOS remote editor protocol.")
    parser.add_argument("--port", help="MIDI port name (default: autodetect via Device Inquiry)")
    parser.add_argument("--device-id", type=int, default=m.DEFAULT_DEVICE_ID)
    parser.add_argument("--timeout", type=float, default=bridge_mod.DEFAULT_TIMEOUT)
    parser.add_argument("--config", default=bridge_mod.DEFAULT_CONFIG_PATH, metavar="FILE",
                        help="port cache file: the last successful autodetect pair is tried "
                             "first on reconnect (default: config.toml; ignored if absent)")
    parser.add_argument("--demo", action="store_true",
                        help="use a canned in-memory device; never opens a MIDI port")
    parser.add_argument("--allow-write", action="store_true",
                        help="enable writes to real hardware (parameter edits, rename, the Master "
                             "menu's destructive operations); always on for --demo")
    args = parser.parse_args(argv)

    if args.demo:
        app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    else:
        app = EosRemoteApp(
            None, allow_write=args.allow_write, demo=False,
            connect_kwargs=dict(port=args.port, device_id=args.device_id, timeout=args.timeout,
                                config_path=args.config))
    app.run()


if __name__ == "__main__":
    main()
