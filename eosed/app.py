# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Mostly original work, GPL-2.0-or-later,
# except: the key-hint legend's fold-to-terminal-width helper (wrap_blocks)
# is ported from the sibling k2kremote project (k2kremote/app.py's
# wrap_blocks), same author, also GPL-2.0-or-later — see LICENSE.
#
# The general Textual-app shape (a title/status bar, modal arm-then-fire
# screens for destructive operations, --demo mode) follows the pattern
# established by k2kremote, though otherwise none of its code is copied —
# this app has no LCD to mirror and no continuous refresh loop; it is a
# plain on-demand request/response editor.

"""eosed — a Textual editor for the EOS remote editor protocol.

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
hardware-verified as thoroughly as the read paths yet (see TODO.md).
``allow_write`` is also toggleable at runtime with ``w`` (``action_
toggle_write_mode``), on top of whatever ``--allow-write`` started it at;
the header turns the E4XT badge's own red while armed, a persistent
reminder that's easy to miss in the status line alone. The Master menu's
destructive operations (Delete Preset, Erase RAM Bank/Presets/Samples) are
never bound to a single keypress regardless of write mode: they require an
explicit arm-then-fire confirmation in :class:`MasterScreen`.
"""

from __future__ import annotations

import argparse
import math
import threading
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Tuple

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import DataTable, Header, Input, Static

from eos import bridge as bridge_mod
from eos import messages as m
from eos import params as p
from eosed.demo import DemoBridge

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

# Infinite-scroll extension: the presets/samples pane only ever shows one
# fetched window at a time (0-999 is the full PRESET_SELECT wire range, far
# more than any one page), and 'g' (goto) was the only way to reach past it
# -- live-caught as a real gap since it's easy not to know 'g' exists.
# Approaching the bottom of the loaded rows (within this many, by keyboard
# or otherwise) fetches the next chunk in the background and appends it,
# rather than replacing the page -- ordinary DataTable scrolling then keeps
# working across the new rows with no further action needed.
BROWSER_EXTEND_THRESHOLD = 10
BROWSER_EXTEND_CHUNK = 50

# Block separator in the key-hint legend (see _KeyHints/wrap_blocks below).
_LEGEND_SEP = " · "


def wrap_blocks(blocks: List[str], width: int, sep: str = _LEGEND_SEP) -> str:
    """Pack ``blocks`` into lines no wider than ``width``, joined by ``sep``.

    Ported from the sibling k2kremote project (k2kremote/app.py's
    ``wrap_blocks``, same author, GPL-2.0-or-later — see LICENSE), which
    solved the identical problem for its own key-hint legend. Breaks
    happen only *between* blocks, never inside one, so a binding like
    "u Find usage" is never split mid-label; a block wider than ``width``
    on its own simply occupies its own line rather than being cut.
    """
    lines: List[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else current + sep + block
        if width and len(candidate) > width and current:
            lines.append(current)
            current = block
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)

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
    """Every parameter id in one pane's group, ascending.

    Memoized: the id set is derived from a table that never changes at
    runtime, but this was being recomputed (a full scan + sort of all ~267
    parameters) once per preset in _load_preset_overview and once per link
    in _load_link_detail. Callers treat the result as read-only; a copy is
    returned so a caller that mutates it can't corrupt the shared entry.
    """
    cached = _GROUP_PARAM_IDS.get(group)
    if cached is None:
        prefix = {"voice": "voice.", "global": "global", "link": "link"}[group]
        cached = sorted(pid for pid, param in p.PARAMETERS.items()
                        if param.group.startswith(prefix))
        _GROUP_PARAM_IDS[group] = cached
    return list(cached)


_GROUP_PARAM_IDS: Dict[str, List[int]] = {}

_VOICE_PARAM_IDS = _group_param_ids("voice")  # the 146-id group, same every voice/preset

# Confirmed live by directly probing the raw wire reply (see
# docs/RESOLUTION_NOTES.md §13): an unused sample slot's get_sample_name
# returns this exact placeholder, not a blank name and not an exception.
_EMPTY_SAMPLE_NAME = "Empty Sample"

# E4_GEN_SAMPLE is a SIGNED parameter (device-reported minimum -8), so these
# two are simply -1 and -2 -- the same bit patterns §11/§12 recorded as
# 3FFFh/3FFEh before the signedness was understood. `eos.bridge` sign-extends
# them from `eos.params`' table, so the values compared here are negative.
# Only these two of the eight possible negative values exist: verified across
# a full 287-preset bank, walking past every sentinel (RESOLUTION_NOTES §18a).
_MULTISAMPLE_SENTINEL = -1  # spec: voice-level E4_GEN_SAMPLE == this means multisample
_NO_SUCH_VOICE_MARKER = -2  # empirically: this voice index does not exist on this preset
# Both are safety bounds, not trusted counts (preset_num_voices/voice_num_
# szones cannot be trusted at all — §11/§12). They are set to the protocol's
# own ceiling: VOICE_SELECT and SAMPLE_ZONE_SELECT are both 0..255 in the
# spec AND in the device's own 03h/04h reply, and the EOS 4.0 manual states
# "Each preset can have up to 256 voices".
#
# They used to be 64 and 32, which were guesses, and both were too small for
# real content — live-caught on a commercial bank (RESOLUTION_NOTES §19):
# drum kits run to 94 voices ("drum kit"), and a multisample voice was
# found with 62 zones. The old caps silently truncated those presets: the
# Voice pane stopped at 64 and the Samples "used by" aggregation missed every
# sample that only voices 64+ referenced, with nothing on screen to say so.
#
# Raising them costs nothing for ordinary presets, since every walk stops at
# its own sentinel long before the cap; only genuinely deep presets pay, and
# for those the extra round trips are the whole point.
_MAX_ZONE_SCAN = 256
_MAX_VOICE_SCAN = 256


@dataclass(frozen=True)
class _Change:
    """One recorded write to the current preset, enough to replay it backwards.

    ``scope`` is the selection the edit was made under. This protocol is
    stateful -- a parameter id means "this voice's" or "this link's" field
    depending on what VOICE_SELECT/LINK_SELECT point at (see
    docs/RESOLUTION_NOTES.md §11) -- so an undo has to restore the same
    selection before writing the old value back, or it lands on whatever
    happens to be selected now. ``param_id`` is None for a preset rename,
    where ``old``/``new`` are the names.
    """

    param_id: Optional[int]
    old: object
    new: object
    voice: Optional[int]
    link: Optional[int]
    scope: str

    @property
    def label(self) -> str:
        if self.param_id is None:
            return "preset name"
        return p.PARAMETERS[self.param_id].name

    def describe(self, value: object) -> str:
        if self.param_id is None:
            return repr(value)
        return p.describe_value(p.PARAMETERS[self.param_id], int(value))


class HistoryScreen(ModalScreen[None]):
    """Read-only list of this preset's changes, newest last (see action_history)."""

    BINDINGS = [Binding("escape", "close", "Close"), Binding("h", "close", "Close", show=False)]

    def __init__(self, preset: Optional[int], changes: List[_Change]):
        super().__init__()
        self._preset = preset
        self._changes = changes

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Changes to preset {self._preset} — {len(self._changes)} "
                   f"({'z' if self._changes else 'escape'} "
                   f"{'undoes the last one, ' if self._changes else ''}escape closes)",
                   id="history_title"),
            _FillWidthDataTable(id="history"),
            id="dialog", classes="wide",
        )

    def on_mount(self) -> None:
        table = self.query_one("#history", _FillWidthDataTable)
        # Scope gets its own column rather than a "[V1]" suffix on the
        # parameter name: it is the selection the edit was made under, and
        # the same parameter id edited under two different voices is two
        # genuinely different fields (see _Change's docstring). Reading that
        # off a suffix means re-parsing it by eye on every row.
        table.add_columns("#", "Scope", "Parameter", "Old", "New")
        table.cursor_type = "row"
        for number, change in enumerate(self._changes, start=1):
            table.add_row(str(number), change.scope, change.label,
                          change.describe(change.old), change.describe(change.new),
                          key=str(number))
        if not self._changes:
            table.add_row("—", "", "no changes yet", "", "")
        table.call_after_refresh(table._stretch_last_column)
        table.focus()

    def action_close(self) -> None:
        self.dismiss(None)


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
    """Show a parameter's current value + device range; ask for a new value.

    Inside this dialog the arrow keys *are* free (there is no row cursor to
    steal them from, unlike the Parameters pane behind it), so up/down step
    the value by 1 and page up/down by 10 — for a parameter whose useful
    range is a handful of steps, that beats retyping the number.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "step(1)", "＋1", show=False),
        Binding("down", "step(-1)", "−1", show=False),
        Binding("pageup", "step(10)", "＋10", show=False),
        Binding("pagedown", "step(-10)", "−10", show=False),
    ]

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

    def action_step(self, delta: int) -> None:
        field = self.query_one("#value", Input)
        try:
            base = int(field.value.strip())
        except ValueError:
            base = self.current  # mid-edit garbage: step from the real value
        value = max(self.minimum, min(self.maximum, base + delta))
        field.value = str(value)
        # Keep the caret at the end, so typing after stepping appends rather
        # than landing wherever the previous text left it.
        field.cursor_position = len(field.value)

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


class ConfirmSweepScreen(ModalScreen[bool]):
    """Yes/no before a cache-all sweep that is going to take a long time.

    Not a generic confirm: it exists because a full-depth sweep of a large
    bank runs for the better part of an hour with nothing but a status line
    to say it has not hung, and there is no way to know that from the key
    legend. `escape` cancels a running sweep, but only if you knew to expect
    one that long in the first place.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("n", "cancel", "No", show=False),
                Binding("y", "confirm", "Yes", show=False)]

    def __init__(self, depth: str, estimate: str, detail: str):
        super().__init__()
        self.depth = depth
        self.estimate = estimate
        self.detail = detail

    def compose(self) -> ComposeResult:
        yield Vertical(Static(id="body"), id="dialog")

    def on_mount(self) -> None:
        self.query_one("#body", Static).update(
            f"Cache all data (depth: {self.depth})\n\n"
            f"This bank looks like roughly {self.estimate}.\n"
            f"{self.detail}\n\n"
            "The app stays usable, but every other MIDI action waits behind\n"
            "the sweep. 'escape' cancels it at any point (nothing is kept).\n\n"
            "Start it?   y) yes    n/escape) no")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# Rough cost model for a cache-all sweep, calibrated against a real E4XT
# Ultra rev 4.70 at the default 50ms send gap (docs/RESOLUTION_NOTES.md §20).
#
# Preset COUNT is the wrong predictor: "structure"/"full" scale with how many
# VOICES a bank holds, and a 990-preset bank of one-voice pads is an order of
# magnitude cheaper than one of 94-voice drum kits at the same count. Used
# preset RAM is a decent proxy for voice count (~0.5 KB per voice on the banks
# measured) and, unlike voice count, is available up front from a single
# `preset_memory()` query -- which matters, since the walk that would tell us
# the real number *is* the expensive thing we are trying to predict.
_SWEEP_SECONDS_PER_KB = {      # seconds of sweep per KB of used preset RAM
    "names": 0.075,            # 150s / 2013 KB
    "structure": 0.68,         # 1371s / 2013 KB
    "full": 3.10,              # 6241s / 2013 KB  (1h 44m on that bank)
}
# Below this, do not bother asking -- a small bank sweeps in seconds.
_SWEEP_CONFIRM_SECONDS = 60


def _estimate_sweep_seconds(depth: str, used_kb: Optional[int]) -> Optional[float]:
    """Very rough seconds for a cache-all sweep, or None if unknown."""
    if used_kb is None or used_kb <= 0:
        return None
    per_kb = _SWEEP_SECONDS_PER_KB.get(depth)
    return None if per_kb is None else used_kb * per_kb


def _humanize_seconds(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)} seconds"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.0f} minutes"
    return f"{minutes / 60.0:.1f} hours"


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


class _BankBrowserTable(_FillWidthDataTable):
    """The #presets/#samples bank browser specifically -- ``DataTable``
    itself already binds PageUp/PageDown to scroll the cursor within
    whatever rows are currently loaded (``page_up``/``page_down``, both
    ``show=False``); redefining the same keys here overrides that just for
    this table; overriding on the shared ``_FillWidthDataTable`` instead
    would have also stolen PageUp/PageDown from the 146-row Parameters
    table, where DataTable's own paging is exactly what's needed."""

    BINDINGS = [
        Binding("pageup", "prev_bank_page", "Prev page", show=False),
        Binding("pagedown", "next_bank_page", "Next page", show=False),
    ]

    def action_prev_bank_page(self) -> None:
        self.app.action_prev_page()

    def action_next_bank_page(self) -> None:
        self.app.action_next_page()


class _KeyHints(Static):
    """The persistent, multi-line key-binding legend at the bottom of the
    screen.

    Replaces Textual's built-in ``Footer``: that widget is hardcoded to a
    single, horizontally-scrolling line (see ``textual.widgets._footer``'s
    ``Footer``/``FooterKey`` ``DEFAULT_CSS``, ``height: 1``) rather than
    wrapping, so bindings started getting clipped/scrolled off once this
    app's binding count grew past what one line comfortably holds. This
    folds itself to the terminal's actual width instead (via wrap_blocks),
    onto as many lines as that width actually needs — 1 on a wide terminal,
    more on a narrow one — rather than a fixed line count.

    ``Footer`` also colored its key/description halves distinctly (its own
    ``footer-key--key``/``footer-key--description`` component classes) —
    losing that when it was dropped made the legend look flat next to the
    rest of the E4XT-themed app. Each block is re-split back into its key
    and description (recovered from the folded plain text — every binding
    here is a single space-free token, so splitting on the first space is
    unambiguous) and re-styled: the key in the theme's accent red, the
    description in its muted secondary tone.
    """

    DEFAULT_CSS = "_KeyHints { height: auto; }"

    def __init__(self, blocks: List[str], *, id: Optional[str] = None):
        super().__init__(id=id)
        self._blocks = blocks

    def on_mount(self) -> None:
        self._render_hints()

    def on_resize(self, event) -> None:
        self._render_hints()

    def _render_hints(self) -> None:
        folded = wrap_blocks(self._blocks, self.size.width)
        text = Text(no_wrap=True)
        for line_num, line in enumerate(folded.split("\n")):
            if line_num:
                text.append("\n")
            for block_num, block in enumerate(line.split(_LEGEND_SEP)):
                if block_num:
                    text.append(_LEGEND_SEP, style="dim")
                key, _, description = block.partition(" ")
                text.append(key, style=f"bold {E4XT_THEME.accent}")
                text.append(" " + description, style=E4XT_THEME.secondary)
        self.update(text)


# --- main app ----------------------------------------------------------------

class EosedApp(App):
    CSS = """
    #dialog {
        width: 64; height: auto; border: round $accent; padding: 1 2;
        background: $surface; align: center middle;
    }
    /* The history overlay is a 4-column table (#, parameter, old, new) and
       a parameter name plus its scope alone runs to ~26 chars, so the
       64-wide dialog the single-field prompts use would truncate it.
       Capped at 90% so it still fits a narrow terminal. */
    #dialog.wide { width: 84; max-width: 90%; }
    #history { height: auto; max-height: 20; }
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

    /* Write mode armed (see action_toggle_write_mode): the top bar turns
       the E4XT badge's own red instead of its default grey, as a
       persistent, glanceable reminder that edits/rename/Master are live. */
    Header.-write-armed { background: $accent; color: $foreground; }
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
        Binding("c", "cache_structure", "Cache structure"),
        Binding("C", "cache_everything", "Cache everything"),
        Binding("x", "clear_sample_usage_cache", "Clear usage cache"),
        Binding("e", "toggle_view", "Extended view"),
        Binding("escape", "back_to_preset", "Back to preset"),
        Binding("m", "master_menu", "Master"),
        Binding("w", "toggle_write_mode", "Write mode"),
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
        Binding("h", "history", "History"),
        # Arrow keys can't be used here -- they move the row cursor in every
        # pane, which is the one navigation the app can't give up. "=" is
        # accepted alongside "+" so nudging up doesn't need the shift key.
        Binding("plus,equals_sign", "nudge_up", "Value +1"),
        Binding("minus", "nudge_down", "Value -1"),
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
        # Guards the infinite-scroll background extend below (one in-flight
        # fetch per bank at a time) -- set on the UI thread the moment a
        # fetch is dispatched, cleared once its result is applied.
        self._extending: Dict[str, bool] = {"preset": False, "sample": False}

        # What's currently shown in the Parameters pane, so a value edit can
        # refresh the same set without re-deriving "global vs. this voice".
        self._current_param_ids: List[int] = []
        self._current_param_label: str = "global"

        # Cached result of the last _load_preset_overview fetch per preset
        # (one preset of "walk every voice/zone" work), keyed by preset
        # number — reused when navigating back to a preset (from a voice/
        # link, or from the Sample bank) instead of re-walking its voices/
        # zones over MIDI again for data that hasn't changed. A "structure"-
        # depth cache-all entry (see below) stores None for global_values
        # (index 3 of the tuple) — _show_or_reload_preset_overview fetches
        # just those on first access rather than treating the entry as
        # absent. Cleared by anything that could actually invalidate it: a
        # parameter write (could change which sample a zone points at) or a
        # Master action.
        self._preset_overviews: Dict[int, Tuple[
            int, Dict[int, int], List[int], Optional[Dict[int, int]],
            List[Tuple[int, str, str]]]] = {}

        # Each voice's own 146-param group, keyed by (preset, voice) --
        # (sample numbers, param values) -- filled in only by a "full"-
        # depth cache-all sweep (see _run_full_sweep), since fetching this
        # for every voice of every preset is itself the single most
        # expensive addition to that sweep. Live-caught: even after a
        # "full" sweep, browsing into a voice ('v') still re-fetched this
        # group fresh every time -- selecting a *preset* had gotten fast,
        # but a voice's own params hadn't, which didn't match what "cache
        # ALL data" implies. _load_voice_detail consults this first.
        self._voice_details: Dict[Tuple[int, int], Tuple[List[int], Dict[int, int]]] = {}

        # Full preset/sample name catalogs, keyed by bank ("preset"/
        # "sample") — filled in by a cache-all sweep (see _run_full_sweep
        # below); consulted by load_bank_page before it hits the device for
        # a page it already has in hand. Sparse (only numbers with a real
        # name), so a bare "is this number in the dict" can't tell "no name
        # here" from "not scanned yet" — _catalog_scanned_upto tracks how
        # far each bank has actually been swept (exclusive upper bound) so
        # load_bank_page knows whether a requested window is fully covered.
        self._catalog_cache: Dict[str, Dict[int, str]] = {"preset": {}, "sample": {}}
        self._catalog_scanned_upto: Dict[str, int] = {"preset": 0, "sample": 0}

        # Opt-in full-bank sweep, shared by two entry points: 'u' (find-
        # sample-usage) always sweeps at "structure" depth for one specific
        # sample; 'a' (cache-all, action_cache_all) sweeps at the configured
        # depth and keeps everything for every preset/sample. Deliberately
        # not automatic by default: a full sweep is a per-voice/zone walk
        # repeated across every preset, easily a minute or more of
        # sequential MIDI round-trips — see _run_full_sweep. A *complete*
        # sweep (or one that stops via the early-stop heuristic, as opposed
        # to a user cancellation) builds a reusable {sample: [(preset,
        # name), ...]} index for every sample it saw along the way, not
        # just the one that triggered it — every later lookup is then
        # instant, no MIDI at all, until something is actually written
        # (same invalidation as the preset-overview cache above). A
        # cancelled/partial sweep's findings are shown once (for 'u') but
        # never promoted into these caches — no way to tell "not found"
        # from "not scanned yet" for whatever it didn't reach.
        self._scan_active = False
        self._cancel_scan = False
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

        # Cache-all ('a' key): how deep a sweep goes, and whether one runs
        # unattended right after startup's first bank page loads. Both
        # user-edited in config.toml (eos.bridge.load_cache_depth/
        # load_cache_all_on_startup), never read for --demo, same reasoning
        # as compact_view/sample_usage_early_stop above.
        self._cache_all_on_startup: bool = (
            False if self.demo else bool(bridge_mod.load_cache_all_on_startup(self._view_config_path)))
        # "structure" instead, and ON by default: it buys the everyday wins
        # (instant preset selection, bank paging, `u`) for 23 min on a large
        # bank where a "full" sweep costs 1h 44m (RESOLUTION_NOTES §20).
        # cache_all_on_startup wins if both are set — it is the explicit
        # request for the deeper sweep.
        configured_structure = (
            None if self.demo
            else bridge_mod.load_cache_structure_on_startup(self._view_config_path))
        self._cache_structure_on_startup: bool = (
            False if self.demo else
            (True if configured_structure is None else configured_structure))
        configured_depth = None if self.demo else bridge_mod.load_cache_depth(self._view_config_path)
        self._cache_depth: str = configured_depth or "full"

        # Send a plain MIDI Program Change whenever a preset is selected
        # (see eos.bridge.EosBridge.send_program_change and
        # docs/RESOLUTION_NOTES.md §14) -- unlike PRESET_SELECT (the editor
        # protocol's own selector), this is what actually makes the device
        # select the preset and redraw its own front-panel LCD, the same as
        # touching it physically would. No key binding -- happens
        # automatically on select_preset. Defaults to on (unlike
        # cache_all_on_startup): cheap, and there's no real downside for a
        # session actually being played on the hardware. Config-only, same
        # "demo touches no real local state" reasoning as the other
        # settings above, but the *feature* itself still defaults on in
        # --demo too (DemoBridge.send_program_change is a no-op either way).
        configured_send_pc = (
            None if self.demo else bridge_mod.load_send_pc_on_preset_select(self._view_config_path))
        self._send_pc_on_preset_select: bool = True if configured_send_pc is None else configured_send_pc

        # Undo log for whichever preset is currently selected, oldest first.
        # Deliberately in-memory only, and cleared the moment a different
        # preset is selected: a remote edit is not persistent anyway -- it
        # lives in the device's RAM until the bank is saved to disk *on the
        # hardware*, so reloading the bank or power-cycling is the real
        # "undo everything" and nothing here needs to survive a restart to
        # be safe. Not a cache, so _invalidate_write_sensitive_caches must
        # never touch it.
        self._changes: List[_Change] = []
        # See _take_pending_status: a confirmation that must survive the
        # pane refresh its own action kicks off.
        self._pending_status: Optional[str] = None
        # Device-reported min/max/default per parameter id. Fetched lazily and
        # kept for the session: authoritative over the static table, but it
        # does not change under us, and re-asking on every nudge would triple
        # that key's round trips. Cleared with the write-sensitive caches
        # anyway, so a Master action cannot leave a stale range behind.
        self._param_ranges: Dict[int, m.ParameterRange] = {}

        self.last_status: str = ""  # exposed for tests

    def _bank_state(self, bank: Optional[str] = None) -> _BankState:
        return self._bank_states[bank if bank is not None else self.bank]

    # -- layout ---------------------------------------------------------
    def _legend_blocks(self) -> List[str]:
        # BINDINGS is the single source of truth for both key dispatch and
        # the legend text — unlike k2kremote's separate LEGEND_BLOCKS table,
        # there is no second list to keep in sync by hand. `show=False`
        # entries (e.g. "enter") are hidden the same way Footer hid them.
        return [f"{binding.key} {binding.description}" for binding in self.BINDINGS if binding.show]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Horizontal(
            _BankBrowserTable(id="presets"),
            _FillWidthDataTable(id="voices"),
            _FillWidthDataTable(id="params"),
            _FillWidthDataTable(id="samples"),
            id="tables",
            classes="compact" if self.compact_view else "",
        )
        yield Static("", id="status")
        yield _KeyHints(self._legend_blocks(), id="keyhints")

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

    def action_toggle_write_mode(self) -> None:
        # A runtime arm/disarm switch on top of --allow-write, not a
        # replacement for it: --allow-write (always on for --demo) just
        # sets the *starting* state; this key can arm or disarm either way,
        # every session starting back at whatever --allow-write said. Never
        # persisted, unlike compact_view -- a write-armed reminder is only
        # useful live, not worth carrying into the next launch.
        self.allow_write = not self.allow_write
        self._update_write_mode_indicator()
        self.set_status("write mode ON — edit/rename/Master enabled" if self.allow_write
                        else "write mode OFF — read-only")

    def _update_write_mode_indicator(self) -> None:
        # The E4XT badge's own red (see E4XT_THEME.accent) instead of the
        # header's default grey — a persistent, glanceable reminder that
        # writes are live, not just a one-off status line easy to miss.
        self.query_one(Header).set_class(self.allow_write, "-write-armed")

    def on_mount(self) -> None:
        self.title = "eosed"
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

        # Reflect the constructor's initial allow_write (--allow-write, or
        # always-on for --demo) immediately — the header shouldn't start
        # grey if writes are already armed at launch.
        self._update_write_mode_indicator()

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
            self._maybe_cache_all_on_startup()

    def _maybe_cache_all_on_startup(self) -> None:
        # No prompt on either path, deliberately: cache_all_on_startup is an
        # explicit opt-in, and cache_structure_on_startup is the default —
        # asking on every launch would make the default an annoyance rather
        # than a convenience. Both still announce the estimate, so a long
        # sweep on a big bank is never a silent surprise, and `escape`
        # cancels either at any point.
        if self._cache_all_on_startup:
            self._confirm_then_cache_all(self._cache_depth, prompt=False)
        elif self._cache_structure_on_startup:
            self._confirm_then_cache_all("structure", prompt=False)

    def on_unmount(self) -> None:
        # The very first layout pass fires a resize, which arms the
        # BROWSER_RESIZE_SETTLE debounce below — so a short-lived app (any
        # test, or a quick quit) routinely shuts down with one still pending.
        # Left armed, it fires against a screen whose widgets are already
        # gone; _settle_browser_resize guards that too, but cancelling here
        # means the callback simply never runs rather than running and
        # bailing (and, more importantly, never dispatches a load_bank_page
        # worker at a point where there is nothing left to display it).
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
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
        try:
            new_window = self._desired_browser_window()
        except NoMatches:
            # Torn down between the resize that armed this timer and the
            # timer firing (on_unmount cancels it, but the callback can
            # already be queued by then) — there is no pane left to size.
            return
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
        self.call_from_thread(self._maybe_cache_all_on_startup)

    # -- bank browser (presets or samples) -----------------------------------
    @staticmethod
    def _catalog_fn(bridge, bank: str):
        return bridge.catalog_presets if bank == "preset" else bridge.catalog_samples

    def _catalog_cache_covers(self, bank: str, wanted: range) -> bool:
        return wanted.stop <= self._catalog_scanned_upto.get(bank, 0)

    @work(thread=True)
    def load_bank_page(self, bank: str, start: int, cursor: Optional[int] = None,
                       force: bool = False) -> None:
        if self.bridge is None:
            return
        # Captured once up front: self.browser_window may change concurrently
        # (a resize settling mid-fetch) — the fetch and the display of its
        # results must agree on the same window size.
        window = self.browser_window
        label = "presets" if bank == "preset" else "samples"
        wanted = range(start, start + window)
        if not force and self._catalog_cache_covers(bank, wanted):
            # A cache-all sweep already scanned this whole window — no need
            # to hit the device for names already in hand.
            cache = self._catalog_cache[bank]
            names = {number: cache[number] for number in wanted if number in cache}
            self.call_from_thread(self._show_bank_page, bank, start, window, names, None, cursor)
            return
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

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "presets":
            return
        self._maybe_extend_bank_page(event.cursor_row, event.data_table.row_count)

    def _maybe_extend_bank_page(self, cursor_row: int, row_count: int) -> None:
        if self.bridge is None:
            return
        bank = self.bank
        state = self._bank_state(bank)
        if self._extending.get(bank) or state.cache_range is None:
            return
        if state.cache_range.stop >= SAMPLE_USAGE_SCAN_RANGE.stop:
            return  # already fetched to the end of the wire range
        if cursor_row < row_count - BROWSER_EXTEND_THRESHOLD:
            return
        self._extending[bank] = True
        self._extend_bank_page(bank)

    @work(thread=True)
    def _extend_bank_page(self, bank: str) -> None:
        state = self._bank_state(bank)
        # Re-read on this thread rather than trusting the check
        # _maybe_extend_bank_page did on the UI thread: a page load
        # completing in between resets cache_range (to a fresh window, or to
        # None), and _extending only guards against a second *extend*, not
        # against that.
        cache_range = state.cache_range
        if cache_range is None:
            self._extending[bank] = False
            return
        extend_range = range(cache_range.stop,
                             min(cache_range.stop + BROWSER_EXTEND_CHUNK,
                                SAMPLE_USAGE_SCAN_RANGE.stop))
        try:
            cache = self._catalog_cache[bank]
            if extend_range.stop <= self._catalog_scanned_upto.get(bank, 0):
                # A cache-all sweep already covers this range -- no MIDI at all.
                names = {number: cache[number] for number in extend_range if number in cache}
            else:
                with self._bridge_lock:
                    names = self._catalog_fn(self.bridge, bank)(extend_range)
        except Exception as exc:
            self._extending[bank] = False
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._append_bank_rows, bank, extend_range, names)

    def _append_bank_rows(self, bank: str, extend_range: range, names: Dict[int, str]) -> None:
        state = self._bank_state(bank)
        self._extending[bank] = False
        if state.cache_range is None or state.cache_range.stop != extend_range.start:
            # A page load landed while this extend was in flight, so these
            # rows no longer continue what's on screen. Dropping them is
            # right: appending would leave a gap or a duplicate run.
            return
        state.cache.update(names)
        state.cache_range = range(state.cache_range.start, extend_range.stop)
        if bank != self.bank:
            return  # switched banks while this was loading -- cache is still updated for later
        table = self.query_one("#presets", _FillWidthDataTable)
        for number in extend_range:
            table.add_row(str(number), names.get(number, ""), key=str(number))
        table.call_after_refresh(table._stretch_last_column)

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
        cached = self._preset_overviews.get(self.current_preset)
        if cached is not None and cached[3] is not None:
            # Nothing about drilling into a voice/link (or switching Sample
            # bank and back) changes what the preset-level view would
            # recompute — reuse it instead of re-walking every voice/zone
            # over MIDI again.
            self._show_preset_overview(self.current_preset, *cached)
        elif cached is not None:
            # A "structure"-depth cache-all sweep walked this preset's
            # voices/zones/samples but deliberately skipped its GLOBAL
            # values (that's the whole point of that depth level) — fetch
            # just those instead of redoing everything else over MIDI.
            self._load_preset_globals_only(self.current_preset, cached)
        else:
            self._load_preset_overview(self.current_preset)

    @work(thread=True)
    def _load_preset_globals_only(self, preset: int, cached: Tuple) -> None:
        voice_count, zone_counts, global_ids, _, sample_rows = cached
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                global_values = self.bridge.get_parameters(global_ids)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        # Upgrade the cached entry in place — global values fetched once are
        # then reused the same way a "full"-depth sweep's would be.
        self._preset_overviews[preset] = (voice_count, zone_counts, global_ids,
                                          global_values, sample_rows)
        self.call_from_thread(self._show_preset_overview, preset, voice_count, zone_counts,
                              global_ids, global_values, sample_rows)

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

    def action_next_page(self) -> None:
        self._step_page(1)

    def action_prev_page(self) -> None:
        self._step_page(-1)

    def _step_page(self, direction: int) -> None:
        # A full jump, unlike the infinite-scroll extend above -- replaces
        # the page rather than growing it, the same as 'g' (goto) already
        # does, just without needing to know or type an exact number.
        if self.bridge is None:
            return
        state = self._bank_state()
        last_start = max(0, SAMPLE_USAGE_SCAN_RANGE.stop - self.browser_window)
        new_start = max(0, min(state.window_start + direction * self.browser_window, last_start))
        if new_start == state.window_start:
            self.set_status("already at the first page" if direction < 0 else "already at the last page")
            return
        self.load_bank_page(self.bank, new_start)

    def action_refresh(self) -> None:
        state = self._bank_state()
        self.load_bank_page(self.bank, state.window_start, force=True)
        if self.bank == "preset" and self.current_preset is not None:
            if self.current_voice is not None:
                self._load_voice_detail(self.current_preset, self.current_voice)
            elif self.current_link is not None:
                self._load_link_detail(self.current_preset, self.current_link)
            else:
                self._load_preset_overview(self.current_preset)

    # -- preset selection: voice list + global params + preset-wide samples --
    def select_preset(self, preset: int) -> None:
        # The undo log is per-preset and in-memory only, so switching preset
        # discards it -- there is no way to undo an edit to preset 3 while
        # preset 7 is selected, since every write goes to whatever
        # PRESET_SELECT currently points at. Re-selecting the *same* preset
        # (a plain re-click, or coming back from a voice/link) keeps it:
        # nothing was actually left.
        if preset != self.current_preset:
            self._clear_changes()
        self.current_preset = preset
        self.current_voice = None
        self.current_link = None
        # Reuses _preset_overviews the same way returning from a voice/link
        # or the Sample bank already did (_show_or_reload_preset_overview)
        # — a cache-all sweep (see action_cache_all) has generally already
        # walked every preset, and a plain re-select shouldn't re-walk one
        # over MIDI again just because it came from a fresh click/goto/enter
        # rather than an "escape" back. An explicit 'r' still forces a real
        # refetch regardless (action_refresh calls _load_preset_overview
        # directly, bypassing this).
        self._show_or_reload_preset_overview()
        if self._send_pc_on_preset_select and self.bridge is not None:
            self._send_program_change_for_preset(preset)

    @work(thread=True)
    def _send_program_change_for_preset(self, preset: int) -> None:
        try:
            with self._bridge_lock:
                self.bridge.send_program_change(preset)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"program change error: {exc}")

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
        self._preset_overviews[preset] = (voice_count, zone_counts, global_ids,
                                          global_values, sample_rows)
        self.call_from_thread(self._show_preset_overview, preset, voice_count, zone_counts,
                              global_ids, global_values, sample_rows)

    def _show_preset_overview(self, preset: int, voice_count: int, zone_counts: Dict[int, int],
                              ids: List[int], values: Dict[int, int],
                              sample_rows: List[Tuple[int, str, str]]) -> None:
        self._show_voices(voice_count, zone_counts)
        self._show_params(ids, values, "global")
        self._show_samples(sample_rows)
        self.set_status(self._take_pending_status()
                        or f"preset {preset}: {voice_count} voice(s), "
                           f"{len(sample_rows)} sample(s) used")

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
        cached = self._preset_overviews.get(self.current_preset)
        if cached is not None:
            count = cached[0]
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
        cached = self._voice_details.get((preset, voice))
        if cached is not None:
            numbers, voice_values = cached
            with self._bridge_lock:
                # Only touches the bridge if this voice's samples reference
                # a name not already in _catalog_cache["sample"] -- normally
                # a no-op after a "full" sweep, but _resolve_sample_rows can
                # still fall back to a live get_sample_name, which needs the
                # same lock as any other MIDI call.
                sample_rows = self._resolve_sample_rows({voice: numbers})
            self.call_from_thread(self._show_voice_detail, voice, _VOICE_PARAM_IDS, voice_values,
                                  sample_rows)
            return
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
                voice_values = self.bridge.get_parameters(_VOICE_PARAM_IDS)
                sample_rows = self._resolve_sample_rows({voice: numbers})
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self.call_from_thread(self._show_voice_detail, voice, _VOICE_PARAM_IDS, voice_values,
                              sample_rows)

    def _show_voice_detail(self, voice: int, ids: List[int], values: Dict[int, int],
                           sample_rows: List[Tuple[int, str, str]]) -> None:
        self._show_params(ids, values, f"voice V{voice + 1}")
        self._show_samples(sample_rows)
        self.set_status(self._take_pending_status()
                        or f"preset {self.current_preset}: voice V{voice + 1}, "
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
        # _show_params set its own status; re-assert a pending confirmation
        # over it, same reason as the preset/voice views above.
        pending = self._take_pending_status()
        if pending is not None:
            self.set_status(pending)

    def action_back_to_preset(self) -> None:
        if self._scan_active:
            self._cancel_scan = True
            self.set_status("cancelling scan ...")
            return
        if self.current_preset is None or (self.current_voice is None and self.current_link is None):
            return
        self.current_voice = None
        self.current_link = None
        self._show_or_reload_preset_overview()

    # -- samples pane: resolve raw sample numbers to names -------------------
    def _resolve_sample_rows(self, by_voice: Dict[int, List[int]],
                             memo: Optional[Dict[int, str]] = None) -> List[Tuple[int, str, str]]:
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
        sample_cache = self._catalog_cache["sample"]
        for number in sorted(users):
            if number in sample_cache:
                name = sample_cache[number]  # already known from a cache-all sweep — no MIDI
            elif memo is not None and number in memo:
                name = memo[number]  # already resolved earlier in this same sweep — no MIDI
            else:
                try:
                    name = self.bridge.get_sample_name(number)
                except Exception:
                    name = ""
                if memo is not None:
                    memo[number] = name
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
        if self._scan_active:
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
        if self._scan_active:
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
        # 'u' always sweeps at "structure" depth: it needs the voice/zone
        # walk (to build the sample-usage index) but has no use for GLOBAL
        # parameter values — same shared sweep 'a' (action_cache_all) uses.
        result = self._run_full_sweep("structure")
        matches = result["sample_index"].get(sample, [])
        if result["cancelled"]:
            note = f" (cancelled at preset {result['stopped_at']}, partial)"
        else:
            self._promote_sweep_result(result)
            note = self._sweep_note(result)
        self.call_from_thread(self._show_sample_usage_results, sample, matches, note)

    def _show_sample_usage_results(self, sample: int, matches: List[Tuple[int, str]],
                                   note: str = "") -> None:
        samples_table = self.query_one("#samples", _FillWidthDataTable)
        samples_table.clear()
        for preset, name in matches:
            samples_table.add_row(str(preset), name, "", key=str(preset))
        samples_table.call_after_refresh(samples_table._stretch_last_column)

        # #samples is hidden in compact view (see the "compact" CSS class)
        # — mirror the same results into #params, which is visible in
        # *both* view modes, the same way select_sample already borrows it
        # for read-only sample info instead of leaving compact-view users
        # with nothing but the status bar's own 5-item truncation.
        self._current_param_ids = []  # nothing here is a real, editable parameter
        self._current_param_label = f"sample {sample} usage"
        params_table = self.query_one("#params", _FillWidthDataTable)
        params_table.clear()
        for preset, name in matches:
            params_table.add_row("—", f"preset {preset}", name, "", key=f"usage_{preset}")
        params_table.call_after_refresh(params_table._stretch_last_column)

        where = ", ".join(f"{preset} {name!r}" for preset, name in matches[:5])
        if len(matches) > 5:
            where += f", +{len(matches) - 5} more — see the Parameters pane"
        summary = f"sample {sample}: used by {len(matches)} preset(s){note}"
        self.set_status(f"{summary} — {where}" if matches else summary)

    # -- cache-all: one full-bank sweep filling every cache at once ---------
    def action_cache_structure(self) -> None:
        """`c` — the everyday sweep: names + voice/zone/sample structure.

        Explicitly "structure" rather than the configured `cache_depth`, so
        the two keys mean fixed, predictable amounts of work. On a large bank
        this is ~23 min against ~1h 44m for `C` (RESOLUTION_NOTES §20).
        """
        self._cache_at_depth("structure")

    def action_cache_everything(self) -> None:
        """`C` — everything `c` fetches, plus each preset's GLOBAL values and
        every voice's own parameter group. Much slower; only worth it if you
        will actually open many voices."""
        self._cache_at_depth("full")

    def _cache_at_depth(self, depth: str) -> None:
        if self._scan_active:
            self.set_status("a scan is already running ('escape' to cancel)")
            return
        self._confirm_then_cache_all(depth)

    @work(thread=True)
    def _confirm_then_cache_all(self, depth: str, *, prompt: bool = True) -> None:
        """Ask first if this bank looks big enough to be worth warning about.

        The size query is one round trip and needs the bridge, so it runs on
        this worker thread like every other MIDI call; the modal itself is
        pushed back onto the UI thread. A bank we cannot size (or a small
        one) starts immediately, exactly as before -- the prompt is there to
        prevent a surprise, not to add a keystroke to every sweep.

        ``prompt=False`` (the startup path) still computes and announces the
        estimate but never blocks: that sweep was asked for in config.toml.
        """
        estimate = None
        used_kb = None
        try:
            with self._bridge_lock:
                memory = self.bridge.preset_memory()
            used_kb = max(0, memory.total_kb - memory.free_kb)
            estimate = _estimate_sweep_seconds(depth, used_kb)
        except Exception:
            pass  # sizing is a courtesy; never block the sweep on it

        if estimate is None or estimate < _SWEEP_CONFIRM_SECONDS:
            self._start_cache_all(depth)
            return

        if not prompt:
            self.call_from_thread(
                self.set_status,
                f"cache all ({depth}) on startup: roughly "
                f"{_humanize_seconds(estimate)} on this bank — 'escape' cancels")
            self._start_cache_all(depth)
            return

        detail = (f"{used_kb} KB of preset RAM in use; the sweep reads every "
                  f"preset,\nand at this depth every voice inside it.")
        # The depth comes from which key was pressed ('c' vs 'C'), not from
        # self._cache_depth, so it has to travel with the callback.
        self.call_from_thread(
            self.push_screen,
            ConfirmSweepScreen(depth, _humanize_seconds(estimate), detail),
            lambda go, depth=depth: self._on_sweep_confirmed(go, depth))

    def _on_sweep_confirmed(self, go: Optional[bool], depth: str) -> None:
        if go:
            self._start_cache_all(depth)
        else:
            self.set_status(f"cache ({depth}) cancelled")

    @work(thread=True)
    def _start_cache_all(self, depth: str) -> None:
        result = self._run_full_sweep(depth)
        if result["cancelled"]:
            self.call_from_thread(
                self.set_status,
                f"cache-all cancelled at preset {result['stopped_at']}, nothing cached")
            return
        self._promote_sweep_result(result)
        note = self._sweep_note(result)
        self.call_from_thread(
            self.set_status,
            f"cache all ({depth}): {len(result['preset_names'])} preset name(s), "
            f"{len(result['sample_names'])} sample name(s){note}")

    def _sweep_note(self, result: dict) -> str:
        if result["stopped_early"]:
            note = (f" (stopped at preset {result['stopped_at']} after "
                    f"{result['gap']} consecutive empty presets)")
        else:
            note = f" (full sweep to preset {result['stopped_at']})"
        if result["sample_stopped_early"]:
            note += (f"; sample names stopped at {result['sample_stopped_at']} "
                     f"after {result['gap']} consecutive unnamed samples")
        return note

    def _promote_sweep_result(self, result: dict) -> None:
        # A fresh sweep's findings are authoritative on their own (complete,
        # or early-stopped by the accepted heuristic) — replace wholesale
        # rather than merging into whatever was cached before, so a stale
        # duplicate row from an earlier partial run can't linger.
        self._catalog_cache["preset"] = result["preset_names"]
        self._catalog_cache["sample"] = result["sample_names"]
        self._catalog_scanned_upto["preset"] = result["stopped_at"] + 1
        self._catalog_scanned_upto["sample"] = result["sample_stopped_at"] + 1
        if result["depth"] in ("structure", "full"):
            self._preset_overviews = result["overviews"]
            self._sample_usage_index = result["sample_index"]
            self._sample_usage_scanned_range = SAMPLE_USAGE_SCAN_RANGE
        if result["depth"] == "full":
            self._voice_details = result["voice_details"]

    def _run_full_sweep(self, depth: str) -> dict:
        """One preset-range walk shared by 'u' (always "structure") and 'a'
        (the configured depth). Fills in as much as ``depth`` calls for and
        returns it all in a dict for the caller to decide what to do with
        (promote to the real caches, or, for 'u', just report one sample's
        matches) — a cancelled sweep's findings must never be promoted (no
        way to tell "not found" from "not reached" for whatever it didn't
        get to), so the decision has to stay with the caller.

        "names": preset_names + sample_names only (no voice/zone walk at
        all, so early-stop has no signal to work from — always a complete,
        uninterrupted sweep, for both catalogs). "structure": adds the same
        per-voice/zone walk _load_preset_overview does for one preset,
        repeated across the range — zone_counts/by_voice resolved into both
        a preset-keyed overview cache and a sample-keyed usage index —
        honoring the configured early-stop gap for the preset walk *and*,
        separately, for the sample-name pass that follows it (bailing after
        the same number of consecutive nameless samples — a name lookup
        failing is just as valid an "empty" signal for a sample as no
        voices is for a preset; a sample-name pass that always ran the full
        0-999 range regardless of the preset walk having already bailed out
        looked inconsistent in practice). "full" additionally fetches each
        preset's GLOBAL parameter values (one batched get_parameters call
        per preset, not one per parameter) *and* every voice's own 146-id
        parameter group (_voice_details, keyed by (preset, voice)) — by far
        the most expensive addition, since it's one batched call per voice,
        not per preset; live-caught as worth it anyway, since selecting a
        preset having gotten instant while browsing into any of its voices
        ('v') still re-fetched fresh every time did not match what "cache
        ALL data" was supposed to mean.
        """
        self._scan_active = True
        self._cancel_scan = False
        last = SAMPLE_USAGE_SCAN_RANGE.stop - 1
        walk_voices = depth in ("structure", "full")
        gap = self._sample_usage_early_stop_gap if walk_voices else None
        # Needed whenever an overview tuple gets built at all (so a later
        # "structure"-depth upgrade to full, see _load_preset_globals_only,
        # knows *which* ids to fetch) — not gated to depth == "full" itself,
        # which only decides whether global_values gets fetched right now.
        global_ids = _group_param_ids("global") if walk_voices else None

        preset_names: Dict[int, str] = {}
        overviews: Dict[int, Tuple] = {}
        # Sample names resolved during this sweep, shared across every preset
        # it visits. Without it _resolve_sample_rows consulted only
        # _catalog_cache["sample"], which this sweep does not populate until
        # _promote_sweep_result runs at the very end — so a bank where many
        # presets reuse the same samples re-asked the device for the same
        # handful of names once per preset, for the whole walk.
        sample_name_memo: Dict[int, str] = {}
        sample_index: Dict[int, List[Tuple[int, str]]] = {}
        voice_details: Dict[Tuple[int, int], Tuple[List[int], Dict[int, int]]] = {}
        consecutive_empty = 0
        stopped_early = False
        stopped_at = SAMPLE_USAGE_SCAN_RANGE.start
        # Bound up front, not inside the loop body: an exception escaping the
        # walk (the PRESET_SELECT write below is outside the per-preset try)
        # used to leave these unbound, so the `return` at the end raised
        # UnboundLocalError and buried whatever the real failure was.
        cancelled = False
        sample_names: Dict[int, str] = {}
        sample_stopped_early = False
        sample_stopped_at = SAMPLE_USAGE_SCAN_RANGE.start
        try:
            with self._bridge_lock:
                for preset in SAMPLE_USAGE_SCAN_RANGE:
                    stopped_at = preset
                    if self._cancel_scan:
                        break
                    self.call_from_thread(
                        self.set_status,
                        f"caching preset {preset}/{last} ({depth} — "
                        f"'escape' to cancel) ...")
                    try:
                        self.bridge.set_parameter(_PRESET_SELECT, preset)
                    except Exception as exc:
                        # Was outside any try: a transport failure here (a
                        # dropped port, say) aborted the whole sweep with a
                        # bare traceback in a worker thread and no status
                        # line, since neither caller wraps this method.
                        self.call_from_thread(self.set_status, f"scan aborted at preset {preset}: {exc}")
                        cancelled = True
                        break
                    # Name lookup and the voice walk are independent signals
                    # (see docs/RESOLUTION_NOTES.md §12) — kept in separate
                    # try blocks so a name-lookup failure (a real possibility
                    # for a preset the device holds no name for) can't
                    # preempt the voice walk, which is what the early-stop
                    # heuristic below actually depends on. The original
                    # single-sample 'u' lookup got this right by fetching
                    # the name lazily, only once voices were found; cache-
                    # all needs every preset's name unconditionally, so the
                    # two steps are decoupled here instead.
                    name: Optional[str] = None
                    try:
                        name = self.bridge.get_preset_name(preset)
                        preset_names[preset] = name
                    except Exception:
                        pass  # no name here -- matches catalog_presets' "skip it" convention
                    found_voices = False
                    if walk_voices:
                        try:
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
                                if depth == "full":
                                    # Re-select the voice first -- the zone
                                    # walk inside _voice_sample_info may have
                                    # left SAMPLE_ZONE_SELECT pointed at its
                                    # last zone, and voice-only fields read
                                    # back the spec's -1/"not applicable"
                                    # sentinel otherwise (same fix already
                                    # in _load_voice_detail).
                                    self.bridge.set_parameter(_VOICE_SELECT, voice)
                                    voice_details[(preset, voice)] = (
                                        info[1], self.bridge.get_parameters(_VOICE_PARAM_IDS))
                            found_voices = voice_count > 0
                            global_values = (self.bridge.get_parameters(global_ids)
                                             if depth == "full" else None)
                            sample_rows = self._resolve_sample_rows(by_voice, sample_name_memo)
                            overviews[preset] = (voice_count, zone_counts, global_ids,
                                                 global_values, sample_rows)
                            if found_voices:
                                used_samples = {s for numbers in by_voice.values() for s in numbers}
                                for used in used_samples:
                                    sample_index.setdefault(used, []).append((preset, name or ""))
                        except Exception:
                            pass  # best-effort, same convention as catalog_presets -- counts as "empty" below
                    if walk_voices:
                        if found_voices:
                            consecutive_empty = 0
                        else:
                            consecutive_empty += 1
                            if gap is not None and consecutive_empty >= gap:
                                stopped_early = True
                                break

                cancelled = self._cancel_scan
                if not cancelled:
                    # A per-sample loop (not catalog_samples, which has no
                    # early-stop hook of its own) so this honors the same
                    # gap the preset walk above does -- "does this sample
                    # have a name at all" is exactly as valid a per-item
                    # signal as "did this preset have voices", and a
                    # sample-name pass that always ran the full 0-999 range
                    # regardless of the preset walk having already bailed
                    # out early looked inconsistent in practice.
                    #
                    # Live-caught, three times now, before the actual root
                    # cause was found by directly probing the raw wire
                    # reply (see docs/RESOLUTION_NOTES.md §13): an empty
                    # sample slot doesn't raise, isn't blank, and isn't
                    # non-ASCII padding garbage -- the device replies with
                    # a real, legitimate-looking, *named* placeholder:
                    # literally "Empty Sample" (confirmed for every unused
                    # slot probed, 0 through 999). The equivalent
                    # get_preset_name also returns "Empty Preset" for an
                    # unused preset, the same device-wide convention --
                    # harmless there since that early-stop signal already
                    # comes from the voice walk, not the name lookup, but
                    # it means this exact placeholder string is a reliable,
                    # precise "nothing here" signal, not a guess about byte
                    # padding.
                    consecutive_empty_samples = 0
                    for sample in SAMPLE_USAGE_SCAN_RANGE:
                        sample_stopped_at = sample
                        if self._cancel_scan:
                            cancelled = True
                            break
                        self.call_from_thread(
                            self.set_status, f"caching sample names: {sample}/{last} ...")
                        try:
                            fetched = self.bridge.get_sample_name(sample)
                        except Exception:
                            fetched = ""
                        if fetched.strip() and fetched.strip().casefold() != _EMPTY_SAMPLE_NAME.casefold():
                            sample_names[sample] = fetched
                            consecutive_empty_samples = 0
                        else:
                            consecutive_empty_samples += 1
                            if gap is not None and consecutive_empty_samples >= gap:
                                sample_stopped_early = True
                                break
        finally:
            self._scan_active = False
        return {
            "depth": depth, "cancelled": cancelled, "stopped_early": stopped_early,
            "stopped_at": stopped_at, "gap": gap, "preset_names": preset_names,
            "sample_names": sample_names, "overviews": overviews, "sample_index": sample_index,
            "sample_stopped_early": sample_stopped_early, "sample_stopped_at": sample_stopped_at,
            "voice_details": voice_details,
        }

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

    # -- nudge the highlighted parameter by one step -------------------------
    def action_nudge_up(self) -> None:
        self._start_nudge(+1)

    def action_nudge_down(self) -> None:
        self._start_nudge(-1)

    def _start_nudge(self, delta: int) -> None:
        param_id = self._selected_param_id()
        if param_id is None:
            return
        if not self.allow_write:
            self.set_status("writes disabled -- press 'w' to arm write mode")
            return
        self._nudge(param_id, delta)

    def _selected_param_id(self) -> Optional[int]:
        """The parameter id under the Parameters pane's cursor, if it is one.

        Rows in that pane are not always parameters -- select_sample and the
        sample-usage results borrow it for read-only display, keyed by
        something that isn't an id.
        """
        try:
            table = self.query_one("#params", DataTable)
        except NoMatches:
            return None
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        try:
            return int(row_key.value)
        except ValueError:
            return None

    @work(thread=True)
    def _nudge(self, param_id: int, delta: int) -> None:
        param = p.PARAMETERS[param_id]
        ids = self._current_param_ids
        try:
            with self._bridge_lock:
                current = self.bridge.get_parameter(param_id)
                # The device's own 03h/04h range is authoritative over the
                # static table (this module's standing rule), but it does not
                # change under us -- so it is fetched once per parameter and
                # kept, otherwise every single nudge would cost three round
                # trips instead of two.
                rng = self._param_ranges.get(param_id)
                if rng is None:
                    rng = self.bridge.get_parameter_range(param_id)
                    self._param_ranges[param_id] = rng
                target = max(rng.minimum, min(rng.maximum, current + delta))
                if target == current:
                    edge = "maximum" if delta > 0 else "minimum"
                    self.call_from_thread(
                        self.set_status,
                        f"{param.name} already at its {edge} ({current})")
                    return
                self.bridge.set_parameter(param_id, target)
                values = self.bridge.get_parameters(ids)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self._invalidate_write_sensitive_caches()
        self.call_from_thread(self._record_nudge, param_id, current, target)
        self.call_from_thread(self._show_params, ids, values, self._current_param_label)
        self.call_from_thread(
            self.set_status,
            f"{param.name} = {p.describe_value(param, target)} (was {current})")

    def _record_nudge(self, param_id: int, old: int, new: int) -> None:
        # Consecutive nudges of the same parameter in the same scope collapse
        # into one undo entry: holding '+' for ten steps is one edit as far
        # as the user is concerned, and ten separate entries would make both
        # the history and 'z' close to useless for it. The entry keeps its
        # ORIGINAL `old`, so undoing it returns to where the run started.
        voice, link, scope = self._current_scope()
        if self._changes:
            last = self._changes[-1]
            if (last.param_id == param_id and last.voice == voice
                    and last.link == link and last.new == old):
                self._changes[-1] = replace(last, new=new)
                self._update_change_indicator()
                return
        self._record_change(param_id, old, new)

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
            self.set_status("writes disabled -- press 'w' to arm write mode")
            return

        def on_result(new_value: Optional[int]) -> None:
            if new_value is None:
                return
            if new_value == current:
                # Not a change; recording it would pad the undo log with
                # no-ops the user never actually made.
                self.set_status(f"{param.name} already {current} — unchanged")
                return
            self._apply_edit(param.id, new_value, current)

        self.push_screen(
            EditValueScreen(param, current, rng.minimum, rng.maximum, rng.default), on_result)

    # -- undo log -------------------------------------------------------------
    def _current_scope(self) -> Tuple[Optional[int], Optional[int], str]:
        """(voice, link, label) for the selection an edit is about to be made under."""
        if self.current_voice is not None:
            return self.current_voice, None, f"V{self.current_voice + 1}"
        if self.current_link is not None:
            return None, self.current_link, f"L{self.current_link + 1}"
        return None, None, "global"

    def _record_change(self, param_id: Optional[int], old: object, new: object) -> None:
        voice, link, scope = self._current_scope()
        self._changes.append(_Change(param_id, old, new, voice, link, scope))
        self._update_change_indicator()

    def _clear_changes(self) -> None:
        self._changes = []
        self._update_change_indicator()

    def _update_change_indicator(self) -> None:
        # The header subtitle, not the status line: the status line is
        # transient (every load/scan overwrites it) and a pending-changes
        # count is exactly the sort of thing that must not scroll away.
        count = len(self._changes)
        if self.current_preset is None:
            self.sub_title = ""
        elif count:
            self.sub_title = f"preset {self.current_preset} · Δ{count}"
        else:
            self.sub_title = f"preset {self.current_preset}"

    def action_history(self) -> None:
        self.push_screen(HistoryScreen(self.current_preset, list(self._changes)))

    def action_undo(self) -> None:
        self._start_undo(1)

    def action_undo_all(self) -> None:
        self._start_undo(len(self._changes))

    def _start_undo(self, count: int) -> None:
        if not self._changes:
            self.set_status("nothing to undo")
            return
        if not self.allow_write:
            # An undo is itself a write, so it is gated exactly like one.
            self.set_status("writes disabled -- press 'w' to arm write mode")
            return
        self._undo_changes(min(count, len(self._changes)))

    @work(thread=True)
    def _undo_changes(self, count: int) -> None:
        preset = self.current_preset
        reverted: List[_Change] = []
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(_PRESET_SELECT, preset)
                for _ in range(count):
                    if not self._changes:
                        break
                    change = self._changes[-1]
                    # Restore the selection this edit was made under before
                    # writing -- see _Change's docstring.
                    if change.voice is not None:
                        self.bridge.set_parameter(_VOICE_SELECT, change.voice)
                    elif change.link is not None:
                        self.bridge.set_parameter(_LINK_SELECT, change.link)
                    if change.param_id is None:
                        self.bridge.set_preset_name(preset, str(change.old))
                    else:
                        self.bridge.set_parameter(change.param_id, int(change.old))
                    # Popped only after the write succeeded, so a failure
                    # part-way leaves the log describing what is still applied.
                    self._changes.pop()
                    reverted.append(change)
        except Exception as exc:
            self.call_from_thread(self._finish_undo, reverted, f"undo failed: {exc}")
            return
        self.call_from_thread(self._finish_undo, reverted, None)

    def _finish_undo(self, reverted: List[_Change], error: Optional[str]) -> None:
        self._invalidate_write_sensitive_caches()
        self._update_change_indicator()
        if error is not None:
            message = error
        elif len(reverted) == 1:
            change = reverted[0]
            scope = f" [{change.scope}]" if change.scope != "global" else ""
            message = (f"reverted {change.label}{scope} from "
                       f"{change.describe(change.new)} to {change.describe(change.old)}"
                       f" — Δ{len(self._changes)} left")
        elif reverted:
            message = (f"reverted {len(reverted)} change(s) on preset "
                       f"{self.current_preset} — back to as loaded")
        else:
            message = "nothing to undo"
        # Shown now *and* armed for the refresh below. Re-reading the pane is
        # a worker, and its completion sets its own "preset N: ..." status --
        # which would silently swallow the confirmation of what was just
        # reverted, the same race _show_bank_page's `status` parameter exists
        # to avoid. Setting both covers either ordering.
        self.set_status(message)
        self._pending_status = message
        # Re-read whatever pane is showing so it reflects the reverted values
        # rather than the ones the user just undid.
        self._reload_current_view()

    def _take_pending_status(self) -> Optional[str]:
        """One-shot status set by an action whose confirmation must outlive
        the pane refresh it triggers (see _finish_undo)."""
        status, self._pending_status = self._pending_status, None
        return status

    def _reload_current_view(self) -> None:
        if self.current_preset is None:
            return
        if self.current_voice is not None:
            self._load_voice_detail(self.current_preset, self.current_voice)
        elif self.current_link is not None:
            self._load_link_detail(self.current_preset, self.current_link)
        else:
            self._load_preset_overview(self.current_preset)

    def _invalidate_write_sensitive_caches(self) -> None:
        # Any real write could change which sample a voice/zone points at,
        # a preset/sample's name, or (for a Master action) far more —
        # nothing cache-all filled in can be trusted as unchanged after one,
        # cleared uniformly rather than reasoning out which specific caches
        # a given write could not possibly have touched.
        self._preset_overviews = {}
        self._sample_usage_index = {}
        self._sample_usage_scanned_range = None
        self._catalog_cache = {"preset": {}, "sample": {}}
        self._catalog_scanned_upto = {"preset": 0, "sample": 0}
        self._voice_details = {}
        self._param_ranges = {}

    @work(thread=True)
    def _apply_edit(self, param_id: int, value: int, old_value: Optional[int] = None) -> None:
        ids = self._current_param_ids
        try:
            with self._bridge_lock:
                self.bridge.set_parameter(param_id, value)
                values = self.bridge.get_parameters(ids)
        except Exception as exc:
            self.call_from_thread(self.set_status, f"error: {exc}")
            return
        self._invalidate_write_sensitive_caches()
        if old_value is not None:
            # Recorded on the UI thread so the header counter and the log
            # stay consistent with each other.
            self.call_from_thread(self._record_change, param_id, old_value, value)
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
            self.set_status("writes disabled -- press 'w' to arm write mode")
            return
        self.push_screen(RenameScreen(self._current_item_name()), self._on_rename_result)

    def _on_rename_result(self, name: Optional[str]) -> None:
        if name is None:
            return
        number = self.current_preset if self.bank == "preset" else self.current_sample
        previous = self._current_item_name()
        if name == previous:
            self.set_status("name unchanged")
            return
        # Only a *preset* rename joins the undo log: the log is scoped to the
        # selected preset, and a sample's name is not part of it (a sample is
        # shared by every preset that plays it).
        if self.bank == "preset" and number == self.current_preset:
            self._record_change(None, previous, name)
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
            self.set_status("writes disabled -- press 'w' to arm write mode")
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
        prog="eosed", description="Textual editor for the EOS remote editor protocol.")
    parser.add_argument("--port", help="MIDI port name (default: autodetect via Device Inquiry)")
    parser.add_argument("--device-id", type=int, default=m.DEFAULT_DEVICE_ID)
    parser.add_argument("--timeout", type=float, default=bridge_mod.DEFAULT_TIMEOUT)
    parser.add_argument("--config", default=bridge_mod.DEFAULT_CONFIG_PATH, metavar="FILE",
                        help="local settings file: caches the last successful autodetect port "
                             "pair, and holds the view/cache-sweep/program-change "
                             "preferences (default: config.toml; ignored if absent)")
    parser.add_argument("--demo", action="store_true",
                        help="use a canned in-memory device; never opens a MIDI port")
    parser.add_argument("--allow-write", action="store_true",
                        help="enable writes to real hardware (parameter edits, rename, the Master "
                             "menu's destructive operations); always on for --demo")
    args = parser.parse_args(argv)

    if args.demo:
        app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    else:
        app = EosedApp(
            None, allow_write=args.allow_write, demo=False,
            connect_kwargs=dict(port=args.port, device_id=args.device_id, timeout=args.timeout,
                                config_path=args.config))
    app.run()


if __name__ == "__main__":
    main()
