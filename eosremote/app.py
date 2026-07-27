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
_SAMPLE_ZONE_SELECT = p.lookup("SAMPLE_ZONE_SELECT").id
_GEN_SAMPLE = p.lookup("E4_GEN_SAMPLE").id


def _group_param_ids(group: str) -> List[int]:
    prefix = {"voice": "voice.", "global": "global"}[group]
    return sorted(pid for pid, param in p.PARAMETERS.items() if param.group.startswith(prefix))


def _voice_sample_info(bridge, preset: int, voice: int) -> Tuple[int, List[int]]:
    """Best-effort: (zone count, [raw sample number(s)]) for one voice.

    ``voice_num_szones`` is a standalone request (no SELECT context needed).
    Reading which sample(s) a voice actually plays does need VOICE_SELECT
    (and, for a multisample voice, SAMPLE_ZONE_SELECT per zone) set first —
    a single-sample voice's own E4_GEN_SAMPLE is the answer directly; a
    multisample voice's top-level E4_GEN_SAMPLE instead reads the spec's
    3FFFh sentinel, and the real numbers live one zone at a time.
    """
    zones = bridge.voice_num_szones(preset, voice)
    bridge.set_parameter(_VOICE_SELECT, voice)
    if zones <= 1:
        return zones, [bridge.get_parameter(_GEN_SAMPLE)]
    numbers = []
    for zone in range(zones):
        bridge.set_parameter(_SAMPLE_ZONE_SELECT, zone)
        numbers.append(bridge.get_parameter(_GEN_SAMPLE))
    return zones, numbers


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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("g", "goto_preset", "Goto preset"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "edit_value", "Edit value", show=False),
        Binding("o", "rename_preset", "Rename"),
        Binding("escape", "back_to_preset", "Back to preset", show=False),
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

        self.current_preset: Optional[int] = None
        self.current_voice: Optional[int] = None

        self.preset_window_start = 0
        self.browser_window = BROWSER_MIN_WINDOW
        self._resize_timer = None
        # The range and result of the last hardware catalog_presets() fetch
        # — shrinking the window afterward re-displays a subset of names
        # already in hand instead of re-asking the device for them.
        self._preset_cache_range: Optional[range] = None
        self._preset_cache: Dict[int, str] = {}

        # What's currently shown in the Parameters pane, so a value edit can
        # refresh the same set without re-deriving "global vs. this voice".
        self._current_param_ids: List[int] = []
        self._current_param_label: str = "global"

        self.last_status: str = ""  # exposed for tests

    # -- layout ---------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Horizontal(
            _FillWidthDataTable(id="presets"),
            _FillWidthDataTable(id="voices"),
            _FillWidthDataTable(id="params"),
            _FillWidthDataTable(id="samples"),
            id="tables",
        )
        yield Static("", id="status")
        yield Footer()

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
            self.load_presets(0)

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
        start = self.preset_window_start
        cache_range = self._preset_cache_range
        shrinking_within_cache = (
            new_window < self.browser_window and cache_range is not None
            and cache_range.start == start and cache_range.stop >= start + new_window)
        self.browser_window = new_window
        if shrinking_within_cache:
            # Every name the smaller page needs is already in hand from the
            # last fetch — just show fewer of them, no need to re-hit the
            # device for a strict subset of what it already gave us.
            self._show_presets(start, new_window, self._preset_cache)
        elif self.bridge is not None:
            self.load_presets(start)

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
        self.call_from_thread(self.load_presets, 0)

    # -- preset browser -----------------------------------------------------
    @work(thread=True)
    def load_presets(self, start: int, cursor_preset: Optional[int] = None) -> None:
        if self.bridge is None:
            return
        # Captured once up front: self.browser_window may change concurrently
        # (a resize settling mid-fetch) — the fetch and the display of its
        # results must agree on the same window size.
        window = self.browser_window
        self.call_from_thread(self.set_status, f"loading presets {start}-{start + window - 1} ...")
        try:
            with self._bridge_lock:
                names = self.bridge.catalog_presets(range(start, start + window))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._show_presets, start, window, names, None, cursor_preset)

    def _show_presets(self, start: int, window: int, names: Dict[int, str],
                      status: Optional[str] = None, cursor_preset: Optional[int] = None) -> None:
        # ``status`` lets a caller that just performed an action (rename, a
        # Master fire) show its own confirmation instead of the generic
        # "presets N-M" message this refresh would otherwise set — without
        # it, two independently-scheduled worker completions would race to
        # set the status bar and the confirmation could vanish before it's
        # ever seen.
        self.preset_window_start = start
        self._preset_cache_range = range(start, start + window)
        self._preset_cache = names
        table = self.query_one("#presets", _FillWidthDataTable)
        table.clear()
        for number in range(start, start + window):
            table.add_row(str(number), names.get(number, ""), key=str(number))
        table.call_after_refresh(table._stretch_last_column)
        # Rebuilding the table resets the cursor to row 0 (the window's
        # first preset) — without this, "goto 125" would visibly land on
        # whatever preset happens to be first in the 112-127 window instead
        # of highlighting 125 itself.
        if cursor_preset is not None and start <= cursor_preset < start + window:
            table.move_cursor(row=cursor_preset - start)
        self.set_status(status if status is not None else f"presets {start}-{start + window - 1}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is None:
            return
        if event.data_table.id == "presets":
            self.select_preset(int(event.row_key.value))
        elif event.data_table.id == "voices":
            self.select_voice(int(event.row_key.value))
        elif event.data_table.id == "params":
            self.action_edit_value()
        # "samples" is read-only/informational — no action on select.

    def _current_preset_name(self) -> str:
        table = self.query_one("#presets", DataTable)
        try:
            row = table.get_row(str(self.current_preset))
            return str(row[1])
        except Exception:
            return ""

    def action_goto_preset(self) -> None:
        self.push_screen(GotoScreen("Goto preset", 0, 999), self._on_goto_result)

    def _on_goto_result(self, preset: Optional[int]) -> None:
        if preset is None:
            return
        window_start = (preset // self.browser_window) * self.browser_window
        if window_start == self.preset_window_start:
            # already showing the right window — just move the cursor,
            # no need to re-scan the same preset names again
            self.query_one("#presets", DataTable).move_cursor(row=preset - window_start)
        else:
            self.load_presets(window_start, cursor_preset=preset)
        self.select_preset(preset)

    def action_refresh(self) -> None:
        self.load_presets(self.preset_window_start)
        if self.current_preset is not None:
            if self.current_voice is not None:
                self._load_voice_detail(self.current_preset, self.current_voice)
            else:
                self._load_preset_overview(self.current_preset)

    # -- preset selection: voice list + global params + preset-wide samples --
    def select_preset(self, preset: int) -> None:
        self.current_preset = preset
        self.current_voice = None
        self._load_preset_overview(preset)

    @work(thread=True)
    def _load_preset_overview(self, preset: int) -> None:
        self.call_from_thread(self.set_status, f"loading preset {preset} ...")
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                voice_count = self.bridge.preset_num_voices(preset)
                zone_counts: Dict[int, int] = {}
                by_voice: Dict[int, List[int]] = {}
                for voice in range(voice_count):
                    zones, numbers = _voice_sample_info(self.bridge, preset, voice)
                    zone_counts[voice] = zones
                    by_voice[voice] = numbers
                global_ids = _group_param_ids("global")
                global_values = self.bridge.get_parameters(global_ids)
                sample_rows = self._resolve_sample_rows(by_voice)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
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

    # -- voice selection: voice params + that voice's samples ---------------
    def select_voice(self, voice: int) -> None:
        self.current_voice = voice
        self._load_voice_detail(self.current_preset, voice)

    @work(thread=True)
    def _load_voice_detail(self, preset: int, voice: int) -> None:
        self.call_from_thread(self.set_status, f"loading voice V{voice + 1} ...")
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                _zones, numbers = _voice_sample_info(self.bridge, preset, voice)
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

    def action_back_to_preset(self) -> None:
        if self.current_preset is None or self.current_voice is None:
            return
        self.current_voice = None
        self._load_preset_overview(self.current_preset)

    # -- samples pane: resolve raw sample numbers to names -------------------
    def _resolve_sample_rows(self, by_voice: Dict[int, List[int]]) -> List[Tuple[int, str, str]]:
        # Assumes self._bridge_lock is already held (called from within the
        # same worker/lock scope as the voice/param reads above).
        users: Dict[int, List[int]] = {}
        for voice, numbers in by_voice.items():
            for number in numbers:
                users.setdefault(number, []).append(voice)
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
        self._start_edit(int(row_key.value))

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
        self.call_from_thread(self._show_params, ids, values, self._current_param_label)
        self.call_from_thread(self.set_status, f"set id {param_id} = {value}")

    # -- rename ---------------------------------------------------------
    def action_rename_preset(self) -> None:
        if self.current_preset is None:
            self.set_status("select a preset first")
            return
        if not self.allow_write:
            self.set_status("writes disabled (pass --allow-write to enable)")
            return
        self.push_screen(RenameScreen(self._current_preset_name()), self._on_rename_result)

    def _on_rename_result(self, name: Optional[str]) -> None:
        if name is None:
            return
        self._apply_rename(self.current_preset, name)

    @work(thread=True)
    def _apply_rename(self, preset: int, name: str) -> None:
        start = self.preset_window_start
        window = self.browser_window
        try:
            with self._bridge_lock:
                self.bridge.set_preset_name(preset, name)
                names = self.bridge.catalog_presets(range(start, start + window))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        # One combined UI update, not two racing ones — see _show_presets.
        self.call_from_thread(self._show_presets, start, window, names,
                              f"renamed preset {preset} to {name!r}")

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
        start = self.preset_window_start
        window = self.browser_window
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
                names = self.bridge.catalog_presets(range(start, start + window))
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        # One combined UI update, not two racing ones — see _show_presets.
        self.call_from_thread(self._show_presets, start, window, names, f"fired: {action}")


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
