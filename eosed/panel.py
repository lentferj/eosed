# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.

"""A front-panel control surface, laid out like the E4XT's own.

**Bindings are positional, not mnemonic.** The panel's two button rows map
onto the keyboard's two home rows in left-to-right order, so ``q w e r`` is
MASTER / PRESET MANAGE / PRESET EDIT / AUDITION and ``a s d f g h j k l ;``
continues along the row beneath it. Muscle memory then transfers from the
hardware rather than from the initials of the labels -- "M for Master" reads
well in a table and is useless once your hands are moving.

The two places where mnemonic and positional agree, the panel gets both for
free: F1-F6 are the keyboard's F1-F6 (top row on both), and the cursor
diamond is the arrow cluster (right-hand side on both).

**It is an exclusive mode.** While this screen is up it consumes every
keystroke, mapped or not, so the layout is free to reuse keys the main view
already binds -- ``s`` is SAMPLE MANAGE here and the samples pane there, and
neither has to know about the other. ``escape`` leaves; ``ctrl+t`` arms.
Nothing else escapes to the app.

**Sending is gated.** Opening this screen never transmits. Arming is a
deliberate, separate act (``ctrl+t``) and requires write mode to be on
already, so reaching the hardware takes two independent decisions -- the same
shape as ``--allow-write`` plus the Master arm-then-fire modal. The reason is
specific rather than reflexive: this protocol is undocumented, its menus
contain one-shot erase functions, and a stray keystroke in a TUI is a much
cheaper accident than a stray keystroke on a rack unit you are standing in
front of.

**The LCD.** The screen area renders a real decoded display when it has one,
as braille (2x4 pixels per cell, so 240x64 becomes 120x16 characters and no
terminal graphics protocol is involved). The decoding is this project's own
(§32) -- nothing about the EOS screen was ever published by anyone.

That is a change of position from 2026-08-14, when this area was blank on
purpose. The objection then was to rebuilding e-remote's graphical panel from
its own traffic; what is drawn here comes from a bitstream this project
decoded itself, and is what makes "confirm the device is on the page this
sequence assumes" possible before firing a load.

**There is still no live feed.** Requesting a screen on demand has never been
confirmed against hardware (§30, §31), so the pane shows a decoded frame only
when one is handed to it. The placeholder says which half is missing rather
than implying the whole feature is unbuilt.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static

from eos import lcd as lcd_mod
from eos import panel as panel_proto
from eos.panel import Key

#: keyboard key -> panel key code. The single source of truth: the layout art
#: below reads its hints from here, so a binding cannot drift from what the
#: panel draws. (Same reasoning as the README key-table guard in tests.)
KEYMAP: Dict[str, int] = {
    # upper button row, left to right along QWERTY
    "q": Key.MASTER,
    "w": Key.PRESET_MANAGE,
    "e": Key.PRESET_EDIT,
    "r": Key.AUDITION,
    # lower button row, left to right along ASDF
    "a": Key.DISK_BROWSE,
    "s": Key.SAMPLE_MANAGE,
    "d": Key.SAMPLE_EDIT,
    "f": Key.ASSIGN_1,
    "g": Key.ASSIGN_2,
    "h": Key.ASSIGN_3,
    "j": Key.PAGE_EXIT,
    "k": Key.PAGE_PREV,
    "l": Key.PAGE_NEXT,
    ";": Key.ENTER,
    # soft keys: top row on the panel, top row on the keyboard
    "f1": Key.F1, "f2": Key.F2, "f3": Key.F3,
    "f4": Key.F4, "f5": Key.F5, "f6": Key.F6,
    # cursor diamond: right-hand cluster on both
    "up": Key.CURSOR_UP,
    "down": Key.CURSOR_DOWN,
    "left": Key.CURSOR_LEFT,
    "right": Key.CURSOR_RIGHT,
    # numeric keypad
    "0": Key.NUM_0, "1": Key.NUM_1, "2": Key.NUM_2, "3": Key.NUM_3,
    "4": Key.NUM_4, "5": Key.NUM_5, "6": Key.NUM_6, "7": Key.NUM_7,
    "8": Key.NUM_8, "9": Key.NUM_9,
    # ',' sits left of '.' on the keyboard exactly as '+/-' sits left of '.'
    # on the panel's bottom keypad row.
    ",": Key.SIGN,
    ".": Key.SET_SHIFT,
    # DEC/INC are a pair above the keypad; '-' and '=' are a pair top-right.
    "-": Key.DEC,
    "=": Key.INC,
}

#: Data-wheel steps. Not buttons -- these send 43h deltas (§30). The shifted
#: pair sends 10 at once, which is what the device itself does when a human
#: spins fast, rather than ten frames in a row.
WHEEL: Dict[str, int] = {
    "[": -1,
    "]": +1,
    "{": -10,
    "}": +10,
}


PANEL_WIDTH = 124


class _Cell:
    """One drawn control: a label, its keyboard hint, and its panel code."""

    __slots__ = ("label", "hint", "code", "width")

    def __init__(self, label: str, hint: str, code: Optional[int], width: int = 9):
        self.label = label
        self.hint = hint
        self.code = code
        self.width = width


def _cell(label: str, key: str, width: int = 9) -> _Cell:
    return _Cell(label, key, KEYMAP.get(key), width)


def _gap(width: int = 9) -> _Cell:
    return _Cell("", "", None, width)


def _row(cells: List[_Cell], active: Optional[int], indent: int = 2) -> Tuple[str, str]:
    """Two markup lines (labels, key hints) for one row of controls.

    Width is tracked explicitly rather than measured off the result: Rich
    markup makes ``len()`` lie, and a border drawn from a lying length is how
    the first version of this ended up ragged.
    """
    labels = " " * indent
    hints = " " * indent
    used = indent
    for cell in cells:
        used += cell.width
        if cell.code is None and not cell.label:
            labels += " " * cell.width
            hints += " " * cell.width
            continue
        label = cell.label.center(cell.width - 1)
        hint = f"({cell.hint})".center(cell.width - 1)
        if active is not None and cell.code == active:
            labels += f"[reverse b]{label}[/reverse b] "
            hints += f"[reverse]{hint}[/reverse] "
        else:
            labels += f"[b]{label}[/b] "
            hints += f"[dim]{hint}[/dim] "
    pad = max(0, PANEL_WIDTH - used)
    return labels + " " * pad, hints + " " * pad


def visible_width(markup: str) -> int:
    """Printable width of a markup string, in terminal cells.

    Rich's own measurement, not a regex strip and ``len()``: this text mixes
    box-drawing, an em dash and ``\u2299``, and cell width is not character
    count for all of them. Every alignment bug in this file came from
    measuring it a cheaper way and being wrong by one to four columns.
    """
    return Text.from_markup(markup).cell_len


def _caption(text: str) -> str:
    return "[dim]" + text.ljust(PANEL_WIDTH)[:PANEL_WIDTH] + "[/dim]"


def render_panel(active: Optional[int] = None, *, armed: bool = False,
                 status: str = "", bitmap=None) -> str:
    """The panel as Rich markup. Pure -- no widgets, so it is testable.

    ``active`` is the key code to highlight (the one just pressed). It matters
    most when no ``bitmap`` is available: without it, a keypress that went
    nowhere and one that reached the device look identical.

    ``bitmap`` is a decoded 64x240 screen from :func:`eos.lcd.decode_display`,
    drawn as braille in the display area. Omitted, the area explains that the
    live feed is unconfirmed rather than pretending the screen is unbuilt.

    Laid out to match the hardware photograph -- display across the top with
    the wheel to its right, soft keys in a row beneath it, mode buttons at the
    far left in two rows (PRESET above SAMPLE), assignables and the PAGE group
    centre-right, cursor diamond and numeric keypad on the right.
    """
    out: List[str] = []

    def line(body: str = "", visible: Optional[int] = None) -> None:
        """One panel line, closed on both sides.

        ``visible`` is the printable width of *body*; it has to be passed in
        because Rich markup makes ``len()`` lie, and a rail drawn from a lying
        length is exactly how the first draft came out ragged.
        """
        width = visible_width(body) if visible is None else visible
        out.append("[dim]│[/dim]" + body + " " * max(0, PANEL_WIDTH - width)
                   + "[dim]│[/dim]")

    out.append("[dim]╭─[/dim] [b]E4XT ULTRA[/b] [dim]"
               + "─" * (PANEL_WIDTH - 13) + "╮[/dim]")

    # --- display + wheel -----------------------------------------------------
    # The LCD is rendered as braille (2x4 pixels per cell), which turns the
    # device's 240x64 screen into 120x16 characters -- no kitty graphics
    # protocol, no sixel, nothing but a font with U+2800..U+28FF. See §32.
    inner = lcd_mod.WIDTH // 2                      # 120 braille columns
    state = ("[b red] ARMED — keys reach the device [/b red]" if armed
             else "[dim] disarmed (ctrl+t to arm) [/dim]")
    line("  [dim]┌" + "─" * inner + "┐[/dim]")
    if bitmap is None:
        # Not a scope decision any more -- the decoder works (§32). What is
        # missing is the live feed: requesting a screen on demand has never
        # been confirmed against hardware, so there is nothing to show yet.
        for text in (" no screen received — the decoder works (§32), the live"
                     " feed does not yet",
                     " requesting a screen on demand is still unconfirmed"
                     " against hardware"):
            line("  [dim]│[/dim][dim]" + text.ljust(inner) + "[/dim][dim]│[/dim]")
    else:
        for braille in lcd_mod.to_braille(bitmap):
            line("  [dim]│[/dim]" + braille.ljust(inner) + "[dim]│[/dim]")
    line("  [dim]└" + "─" * inner + "┘[/dim]")
    line()
    line("  " + state + "     [dim]wheel ([ ]) ([{ }] ×10)[/dim]")
    line()

    # --- soft keys -----------------------------------------------------------
    line(_caption("      - - - - - - - - - -  soft keys  - - - - - - - - - -"))
    soft = [_gap(4)] + [_cell(f"F{n}", f"f{n}", 7) for n in range(1, 7)]
    for text in _row(soft, active):
        line(text)
    line()

    # --- mode buttons, assignables, page group, cursor -----------------------
    line(_caption("   PRESET                      ASSIGNABLE        PAGE          CURSOR"))
    upper = [
        _cell("MASTER", "q", 10),
        _cell("MANAGE", "w", 9),
        _cell("EDIT", "e", 8),
        _cell("AUDITION", "r", 10),
        _gap(3),
        _cell("1", "f", 5), _cell("2", "g", 5), _cell("3", "h", 5),
        _gap(2),
        _cell("EXIT", "j", 7),
        _gap(8),
        _cell("▲", "up", 8),
    ]
    for text in _row(upper, active):
        line(text)
    line()

    line(_caption("   SAMPLE"))
    lower = [
        _cell("DISK/BR", "a", 10),
        _cell("MANAGE", "s", 9),
        _cell("EDIT", "d", 8),
        _gap(7),
        _gap(3),
        _gap(5), _gap(5), _gap(5),
        _gap(2),
        _cell("PREV", "k", 7), _cell("NEXT", "l", 7),
        _cell("◀", "left", 8), _cell("▶", "right", 8),
    ]
    for text in _row(lower, active):
        line(text)

    tail = [
        _gap(10), _gap(9), _gap(8), _gap(10), _gap(3),
        _gap(5), _gap(5), _gap(5), _gap(2),
        _cell("ENTER", ";", 7),
        _gap(8),
        _cell("▼", "down", 8),
    ]
    line()
    for text in _row(tail, active):
        line(text)
    line()

    # --- numeric keypad + DEC/INC --------------------------------------------
    line(_caption("   keypad                                        DEC / INC"))
    pad_rows = [
        [("1", "1"), ("2", "2"), ("3", "3")],
        [("4", "4"), ("5", "5"), ("6", "6")],
        [("7", "7"), ("8", "8"), ("9", "9")],
        [("+/-", ","), ("0", "0"), (".", ".")],
    ]
    for index, keys in enumerate(pad_rows):
        cells = [_gap(3)] + [_cell(label, key, 7) for label, key in keys]
        if index == 0:
            cells += [_gap(16), _cell("DEC", "-", 7), _cell("INC", "=", 7)]
        for text in _row(cells, active):
            line(text)

    out.append("[dim]╰" + "─" * (PANEL_WIDTH) + "╯[/dim]")
    if status:
        out.append("")
        out.append(status)
    return "\n".join(out)


class PanelScreen(ModalScreen):
    """The front-panel surface. ``escape`` closes, ``ctrl+t`` arms."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("ctrl+t", "toggle_arm", "Arm/disarm sending"),
    ]

    def __init__(self, *, allow_write: bool, device_id: int, send=None,
                 bitmap=None):
        super().__init__()
        self.allow_write = allow_write
        self.device_id = device_id
        self._send = send
        self.armed = False
        self.last_key: Optional[int] = None
        self.last_status = ""
        self.bitmap = None
        self.sent_frames: List[List[int]] = []   # exposed for tests
        self.bitmap = bitmap

    def compose(self) -> ComposeResult:
        yield Static(render_panel(), id="panel")

    def on_mount(self) -> None:
        self._refresh("panel open — sending disabled")

    def _refresh(self, status: str = "") -> None:
        if status:
            self.last_status = status
        self.query_one("#panel", Static).update(
            render_panel(self.last_key, armed=self.armed, status=self.last_status,
                         bitmap=self.bitmap))

    def action_close(self) -> None:
        self.dismiss(None)

    def action_toggle_arm(self) -> None:
        if not self.armed and not self.allow_write:
            self._refresh("cannot arm: write mode is off (press 'w' in the main view first)")
            return
        self.armed = not self.armed
        if not self.armed:
            self._refresh("disarmed — keys are not sent")
        elif self._send is None:
            # --demo, or a session with no bridge. Saying "keys now reach the
            # E4XT" here would be a lie of exactly the kind this project keeps
            # finding in its own docs -- true of the armed state in general,
            # false of this particular run.
            self._refresh("armed, but there is no device connected — nothing will be sent")
        else:
            self._refresh("ARMED — keys now reach the E4XT")

    # -- input ---------------------------------------------------------------
    # on_key rather than BINDINGS for the panel keys themselves: the map is
    # keyed by the characters a person actually types (";", ",", "[") and
    # going through Textual's binding names for those invites a silent
    # mismatch between the art and the handler. One dict, one lookup.

    def on_key(self, event) -> None:
        key = event.key
        char = getattr(event, "character", None)

        if key in ("escape", "ctrl+t"):
            return                       # leave these to BINDINGS

        # Exclusive by design: every other key is consumed here, mapped or
        # not. This screen is a *mode*, and a mode that lets unrecognised keys
        # fall through is not one -- 'z' would undo, 'm' would open the Master
        # menu, 'C' would start a full cache sweep, all from inside a panel
        # that looks like it is talking to the sampler. Consuming everything
        # is also what frees the layout to bind whatever the hardware needs
        # without checking it against the main view's keys.
        event.stop()

        code = KEYMAP.get(key)
        if code is None and char is not None:
            code = KEYMAP.get(char)
        if code is not None:
            self._press(code)
            return

        delta = WHEEL.get(key)
        if delta is None and char is not None:
            delta = WHEEL.get(char)
        if delta is not None:
            self._wheel(delta)
            return

        self._refresh(f"{key!r} is not a panel key — escape to leave")

    def _press(self, code: int) -> None:
        self.last_key = code
        label = panel_proto.KEY_LABELS.get(code, f"{code:#04x}")
        if not self.armed:
            self._refresh(f"{label} ({code:#04x}) — not sent, panel is disarmed")
            return
        frames = panel_proto.press(self.device_id, code)
        self._transmit(frames)
        self._refresh(f"{label} ({code:#04x}) sent")

    def _wheel(self, delta: int) -> None:
        self.last_key = None
        if not self.armed:
            self._refresh(f"wheel {delta:+d} — not sent, panel is disarmed")
            return
        self._transmit([panel_proto.dial(self.device_id, delta)])
        self._refresh(f"wheel {delta:+d} sent")

    def _transmit(self, frames: List[List[int]]) -> None:
        self.sent_frames.extend(frames)
        if self._send is None:
            return
        for frame in frames:
            self._send(frame)
