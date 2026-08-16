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
from textual import work
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


#: Render modes for the LCD, cheapest-to-widest. k2kremote offers the same
#: three for the K2000's identically-sized screen; which one reads best
#: depends on how much terminal width you can spare.
RENDER_MODES = ("quadrant", "half", "braille")

#: Columns each mode needs for the display itself.
_MODE_WIDTH = {"quadrant": lcd_mod.WIDTH // 2,     # 120, 2x2 px per cell
               "half": lcd_mod.WIDTH,              # 240, 1x2 px per cell
               "braille": lcd_mod.WIDTH // 2}      # 120, 2x4 px per cell

_MODE_RENDER = {"quadrant": lambda bm: lcd_mod.to_quadrants(bm),
                "half": lambda bm: lcd_mod.to_halfblocks(bm),
                "braille": lambda bm: lcd_mod.to_braille(bm)}

#: The button layout needs this much; the display may need more.
MIN_PANEL_WIDTH = 124


def panel_width(mode: str = "quadrant") -> int:
    return max(MIN_PANEL_WIDTH, _MODE_WIDTH.get(mode, 120) + 4)


PANEL_WIDTH = panel_width()


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


def _row(cells: List[_Cell], active: Optional[int], indent: int = 2,
         width: int = PANEL_WIDTH) -> Tuple[str, str]:
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
    pad = max(0, width - used)
    return labels + " " * pad, hints + " " * pad


def visible_width(markup: str) -> int:
    """Printable width of a markup string, in terminal cells.

    Rich's own measurement, not a regex strip and ``len()``: this text mixes
    box-drawing, an em dash and ``\u2299``, and cell width is not character
    count for all of them. Every alignment bug in this file came from
    measuring it a cheaper way and being wrong by one to four columns.
    """
    return Text.from_markup(markup).cell_len


def _placed(items, active: Optional[int], indent: int,
            width: int = PANEL_WIDTH) -> Tuple[str, str]:
    """Two lines with each label centred on an explicit column.

    Used for the soft keys, which must line up with the boxes drawn along the
    bottom of the LCD rather than sit in an evenly-spaced row of their own.
    The labels above them change per page -- six narrow boxes on one screen,
    three wide ones on another -- but the keys are physically at sixths of the
    display, so the column is what stays true.
    """
    labels = [" "] * width
    hints = [" "] * width
    spans = []
    for column, label, hint, code in items:
        for text, buf in ((label, labels), (f"({hint})", hints)):
            start = indent + column - len(text) // 2
            start = max(0, min(start, width - len(text)))
            for offset, char in enumerate(text):
                buf[start + offset] = char
            if buf is labels:
                spans.append((start, len(text), code))

    def paint(buf, bold):
        out = ""
        index = 0
        while index < width:
            hit = next((s for s in spans if s[0] == index), None)
            if hit and active is not None and hit[2] == active:
                chunk = "".join(buf[index:index + hit[1]])
                out += f"[reverse b]{chunk}[/reverse b]"
                index += hit[1]
                continue
            out += buf[index]
            index += 1
        return out if bold else "[dim]" + out + "[/dim]"

    return paint(labels, True), paint(hints, False)


def _headings(*items, width: int = PANEL_WIDTH, indent: int = 3) -> str:
    """A dim caption line with each label centred on a column.

    Headings are placed the same way the keys are, because on the hardware
    they *label groups*: PRESET arcs over MANAGE/EDIT, PAGE over PREV/NEXT.
    Laying them out as free text drifts out of register with the buttons the
    moment a column moves.
    """
    buf = [" "] * width
    for column, text in items:
        start = max(0, min(indent + column - len(text) // 2, width - len(text)))
        for offset, char in enumerate(text):
            buf[start + offset] = char
    return "[dim]" + "".join(buf) + "[/dim]"


def _caption(text: str, width: int = PANEL_WIDTH) -> str:
    return "[dim]" + text.ljust(width)[:width] + "[/dim]"


def render_panel(active: Optional[int] = None, *, armed: bool = False,
                 status: str = "", bitmap=None, mode: str = "quadrant") -> str:
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
    total = panel_width(mode)

    def line(body: str = "", visible: Optional[int] = None) -> None:
        """One panel line, closed on both sides.

        ``visible`` is the printable width of *body*; it has to be passed in
        because Rich markup makes ``len()`` lie, and a rail drawn from a lying
        length is exactly how the first draft came out ragged.
        """
        width = visible_width(body) if visible is None else visible
        out.append("[dim]│[/dim]" + body + " " * max(0, total - width)
                   + "[dim]│[/dim]")

    out.append("[dim]╭─[/dim] [b]E4XT ULTRA[/b] [dim]"
               + "─" * (total - 13) + "╮[/dim]")

    # --- display + wheel -----------------------------------------------------
    # The LCD is rendered as braille (2x4 pixels per cell), which turns the
    # device's 240x64 screen into 120x16 characters -- no kitty graphics
    # protocol, no sixel, nothing but a font with U+2800..U+28FF. See §32.
    inner = _MODE_WIDTH.get(mode, lcd_mod.WIDTH // 2)
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
        # Quadrant blocks, not braille: same 120 columns but twice the
        # vertical resolution, and solid cells rather than dots, so the
        # device's 1px font strokes read as strokes. Braille turned the
        # screen into texture (§34).
        for row in _MODE_RENDER.get(mode, _MODE_RENDER["quadrant"])(bitmap):
            line("  [dim]│[/dim]" + row.ljust(inner) + "[dim]│[/dim]")
    line("  [dim]└" + "─" * inner + "┘[/dim]")

    # --- soft keys, aligned under the display's own soft-menu boxes ----------
    columns = lcd_mod.soft_key_columns(inner)
    for text in _placed(
            [(columns[n], f"F{n + 1}", f"f{n + 1}", KEYMAP[f"f{n + 1}"])
             for n in range(6)],
            active, indent=3, width=total):
        line(text)
    line()
    line("  " + state + "     [dim]wheel ([ ]) ([{ }] ×10)[/dim]")
    line()

    # --- buttons, laid out against the hardware photograph -------------------
    # Columns, not evenly-spaced rows. The panel groups things the way the
    # metal does: MASTER and DISK/BROWSE alone at the left, PRESET's
    # MANAGE/EDIT pair above SAMPLE's, AUDITION beside them, and then -- all
    # on the *lower* row -- the three assignables, EXIT, the PAGE pair, and
    # ENTER. An earlier version put the assignables and EXIT on the top row
    # and ENTER on a third, which reads fine in isolation and matches nothing
    # on the device.
    #
    # The headings matter as much as the keys: "PRESET" belongs over
    # MANAGE/EDIT rather than over MASTER, and "PAGE" spans PREV/NEXT only --
    # on the hardware it is a printed arc over exactly those two.
    # Columns are expressed against the narrow layout and then scaled to the
    # panel's actual width, so the buttons spread with the display instead of
    # huddling on the left in half-block mode. On the hardware the keys span
    # the whole width of the unit; a fixed 124-column cluster under a
    # 244-column display is a text-grid artefact, not the panel.
    def sx(column: int) -> int:
        return round(column * (total - 4) / MIN_PANEL_WIDTH)

    C_MODE, C_MANAGE, C_EDIT, C_AUDITION = sx(7), sx(19), sx(29), sx(40)
    C_A1, C_A2, C_A3 = sx(50), sx(62), sx(74)
    C_EXIT, C_PREV, C_NEXT, C_ENTER = sx(84), sx(92), sx(100), sx(108)
    C_LEFT, C_MID, C_RIGHT = sx(112), sx(116), sx(120)

    def placed(items):
        for text in _placed(items, active, indent=3, width=total):
            line(text)

    line(_caption("", total).replace("[dim][/dim]", "") if False else
         _headings([(C_MANAGE + C_EDIT) // 2, "PRESET"],
                   [(C_A1 + C_A3) // 2, "ASSIGNABLE KEYS"],
                   [(C_PREV + C_NEXT) // 2, "PAGE"],
                   [C_MID, "CURSOR"], width=total, indent=3))
    placed([
        (C_MODE, "MASTER", "q", KEYMAP["q"]),
        (C_MANAGE, "MANAGE", "w", KEYMAP["w"]),
        (C_EDIT, "EDIT", "e", KEYMAP["e"]),
        (C_AUDITION, "AUDITION", "r", KEYMAP["r"]),
        (C_MID, "▲", "↑", KEYMAP["up"]),
    ])
    line(_headings([(C_MANAGE + C_EDIT) // 2, "SAMPLE"],
                   [(C_A1 + C_A3) // 2, "HOLD SET/SHIFT"],
                   width=total, indent=3))
    placed([
        (C_MODE, "DISK/BR", "a", KEYMAP["a"]),
        (C_MANAGE, "MANAGE", "s", KEYMAP["s"]),
        (C_EDIT, "EDIT", "d", KEYMAP["d"]),
        (C_A1, "1", "f", KEYMAP["f"]),
        (C_A2, "2", "g", KEYMAP["g"]),
        (C_A3, "3", "h", KEYMAP["h"]),
        (C_EXIT, "EXIT", "j", KEYMAP["j"]),
        (C_PREV, "PREV", "k", KEYMAP["k"]),
        (C_NEXT, "NEXT", "l", KEYMAP["l"]),
        (C_ENTER, "ENTER", ";", KEYMAP[";"]),
        (C_LEFT, "◀", "←", KEYMAP["left"]),
        (C_RIGHT, "▶", "→", KEYMAP["right"]),
    ])
    # The assignables carry printed sub-labels on the metal; the cursor
    # diamond's bottom key sits on this line too.
    line(_headings([C_A1, "SEQUENCER"], [C_A2, "NEW SAMPLE"], [C_A3, "RAM/ROM"],
                   width=total, indent=3))
    placed([(C_MID, "▼", "↓", KEYMAP["down"])])
    line()

    # --- numeric keypad + DEC/INC, far right as on the hardware --------------
    # On the metal these sit to the *right* of the cursor diamond, not under
    # the mode buttons. Putting them bottom-left was the last thing in this
    # layout that came from the convenience of a text grid rather than from
    # the photograph.
    K1, K2, K3 = sx(96), sx(106), sx(116)
    # DEC/INC live above the keypad on the metal, not beside the PAGE keys --
    # they were borrowing PREV/NEXT's columns, which put them under the wrong
    # heading entirely.
    line(_headings([K2, "DEC / INC"], width=total, indent=3))
    for text in _placed([(K1 + 4, "DEC", "-", KEYMAP["-"]),
                         (K3 - 4, "INC", "=", KEYMAP["="])],
                        active, indent=3, width=total):
        line(text)
    for row in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"),
                ("+/-", "0", ".")):
        keys = {"+/-": ",", ".": "."}
        items = [(col, label, keys.get(label, label), KEYMAP[keys.get(label, label)])
                 for col, label in zip((K1, K2, K3), row)]
        for text in _placed(items, active, indent=3, width=total):
            line(text)

    out.append("[dim]╰" + "─" * total + "╯[/dim]")
    if status:
        out.append("")
        out.append(status)
    return "\n".join(out)


class PanelScreen(ModalScreen):
    """The front-panel surface. ``escape`` closes, ``ctrl+t`` arms."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("ctrl+t", "toggle_arm", "Arm/disarm sending"),
        Binding("ctrl+r", "force_refresh", "Force a full screen"),
        Binding("ctrl+g", "cycle_render", "Cycle LCD render"),
    ]

    #: Poll interval for the cheap 52h update request. 70ms per poll (§33b),
    #: so twice a second is about 14% of the MIDI link -- responsive without
    #: queueing the user's keypresses behind screen traffic.
    POLL_SECONDS = 0.5

    def __init__(self, *, allow_write: bool, device_id: int, send=None,
                 bitmap=None, poll=None):
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
        # poll() -> bitmap | None, implementing §33b's policy. Owned by the
        # caller because it needs the MIDI input port, which this screen
        # deliberately does not.
        self._poll = poll
        self._polling = False
        self.render_mode = "quadrant"

    def compose(self) -> ComposeResult:
        yield Static(render_panel(), id="panel")

    def on_mount(self) -> None:
        self._refresh("panel open — sending disabled")
        if self._poll is not None:
            self.set_interval(self.POLL_SECONDS, self._tick)

    def _tick(self) -> None:
        # One poll in flight at a time. A 52h round trip is ~70ms but an
        # escalation to 51h is ~716ms (§33b), and overlapping requests would
        # interleave two conversations on one wire.
        if self._polling or self._poll is None:
            return
        self._polling = True
        self._poll_worker()

    @work(thread=True)
    def _poll_worker(self) -> None:
        try:
            bitmap = self._poll()
        except Exception as exc:                      # a dead port must not kill the UI
            self.app.call_from_thread(self._poll_failed, str(exc))
            return
        self.app.call_from_thread(self._poll_done, bitmap)

    def _poll_done(self, bitmap) -> None:
        self._polling = False
        if bitmap is not None:
            self.bitmap = bitmap
            self._refresh()

    def _poll_failed(self, message: str) -> None:
        self._polling = False
        self._refresh(f"screen poll failed: {message}")

    def action_cycle_render(self) -> None:
        """`ctrl+g` -- quadrant -> half-block -> braille.

        Not a cosmetic choice. Quadrant (120 cols) reads best in the space the
        panel already needs; half-block (240 cols) keeps horizontal pixels 1:1
        and is the most faithful if the terminal is wide enough; braille is
        the same width as quadrant but 2x4 per cell, which merges this
        device's 1-pixel strokes -- kept because it is the compact option and
        some fonts render it better than blocks.
        """
        index = RENDER_MODES.index(self.render_mode)
        self.render_mode = RENDER_MODES[(index + 1) % len(RENDER_MODES)]
        need = panel_width(self.render_mode)
        note = "" if need <= self.size.width else f" — needs {need} columns, you have {self.size.width}"
        self._refresh(f"LCD render: {self.render_mode}{note}")

    def action_force_refresh(self) -> None:
        """`ctrl+r` -- ask for a full screen regardless of what the delta says.

        Every automatic refresh scheme eventually disagrees with reality; this
        is the way to say "just ask again" without restarting anything.
        """
        if self._poll is None:
            self._refresh("no device connected — nothing to refresh")
            return
        self._refresh("forcing a full screen ...")
        self._tick()

    def _refresh(self, status: str = "") -> None:
        if status:
            self.last_status = status
        self.query_one("#panel", Static).update(
            render_panel(self.last_key, armed=self.armed, status=self.last_status,
                         bitmap=self.bitmap, mode=self.render_mode))

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

        # Derived from BINDINGS rather than listed literally. The literal
        # version silently swallowed ctrl+r the moment it was added: this
        # handler consumes every key by design, so any new binding is dead on
        # arrival unless it is also named here, and nothing fails loudly when
        # it is not. Deriving the set means adding a Binding is enough.
        if key in {binding.key for binding in self.BINDINGS}:
            return

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
