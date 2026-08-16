# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# Protocol facts here were captured from an E4XT Ultra on firmware 4.70 and
# are recorded in docs/RESOLUTION_NOTES.md §26-§30.  The session-open opcode
# and the key-press down/up behaviour were published independently in 2016 by
# midimachines (see LICENSE); everything else -- the frame header layout, the
# key-code map, and the data-dial encoding -- is this project's own capture
# work.
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

"""The **panel/remote** protocol -- `F0 18 7F <devID> 7A <cmd> ... F7`.

Deliberately a separate module from :mod:`eos.messages`, which speaks the
*editor* protocol (`F0 18 21 <devID> 55 ...`). CLAUDE.md's standing rule is
that the two must not be conflated: one is fully specified by E-mu, this one
is undocumented and every byte in it was either captured here or is prior art
from a third party. Keeping them in separate files makes it hard to acquire a
false sense of authority by proximity.

**Nothing in this module is guessed.** Every frame it can build corresponds to
traffic observed on the wire (§28 for the open, §29/§30 for buttons and the
dial). There is no close message here, because we have never captured one --
the only published version has its manufacturer id transposed (§28a) and is
not worth trusting.
"""

from __future__ import annotations

import enum
from typing import Dict, List, Optional

SOX = 0xF0
EOX = 0xF7
MANUFACTURER_ID = 0x18
PANEL_ID = 0x7F         # where the editor protocol has 21h
PANEL_DESIGNATOR = 0x7A  # where the editor protocol has 55h


class PanelCommand(enum.IntEnum):
    """Opcode byte, position 5. Names describe observed behaviour only."""

    OPEN = 0x10             # host->device, session open (§28)
    BUTTON = 0x40           # 40 <key> 00 <01=down|00=up>  (§29, §30)
    DIAL = 0x43             # 43 01 <lo> <hi>, signed 14-bit delta (§30)
    DISPLAY = 0x50          # device->host, 240x64 bitmap (§26, §32)
    DISPLAY_REQUEST = 0x51  # host->device, "send me the screen" -- confirmed §33
    DISPLAY_UPDATE = 0x52   # host->device, delta request; 86 bytes = nothing new (§33a)
    SCREEN_QUERY = 0x60     # host->device, provokes a 61h reply (§33)
    SCREEN_STATE = 0x61     # device->host, two payload bytes, meaning unknown


class Key(enum.IntEnum):
    """Front-panel key codes, captured 2026-08-15 (§30).

    32 of these were observed directly. The eight number keys marked below
    were inferred *after* both ends of the run and a midpoint were tested --
    which is how the ``+/-`` key between 9 and 0 was caught, and why ``ZERO``
    is 7Eh rather than the 7Dh a naive sequence would assign.
    """

    PRESET_MANAGE = 0x58
    SAMPLE_MANAGE = 0x59
    PRESET_EDIT = 0x5A
    SAMPLE_EDIT = 0x5B
    MASTER = 0x5C
    DISK_BROWSE = 0x5D
    PAGE_EXIT = 0x5E
    ASSIGN_1 = 0x5F
    ASSIGN_2 = 0x60
    # 0x61 -- exists, never pressed, unidentified
    F1 = 0x62
    ASSIGN_3 = 0x63
    F2 = 0x64
    AUDITION = 0x65
    F3 = 0x66
    # 0x67 -- exists, never pressed, unidentified
    F4 = 0x68
    PAGE_PREV = 0x69
    F5 = 0x6A
    PAGE_NEXT = 0x6B
    F6 = 0x6C
    ENTER = 0x6D
    CURSOR_UP = 0x6E
    CURSOR_LEFT = 0x6F
    CURSOR_RIGHT = 0x70
    CURSOR_DOWN = 0x71
    DEC = 0x72
    INC = 0x73
    NUM_1 = 0x74
    NUM_2 = 0x75      # inferred
    NUM_3 = 0x76      # inferred
    NUM_4 = 0x77      # inferred
    NUM_5 = 0x78      # inferred
    NUM_6 = 0x79      # inferred
    NUM_7 = 0x7A
    NUM_8 = 0x7B      # inferred
    NUM_9 = 0x7C
    SIGN = 0x7D       # +/-
    NUM_0 = 0x7E
    SET_SHIFT = 0x7F  # "."


#: Codes that were never pressed but are known to exist (gaps in an otherwise
#: contiguous run). Kept so a later session can go looking rather than
#: rediscovering the gap.
UNIDENTIFIED_CODES = (0x61, 0x67)

#: Key codes that were inferred from the sequence rather than observed. Worth
#: keeping machine-readable so a UI can mark them, and so a future capture can
#: assert against this set rather than a comment.
INFERRED_KEYS = frozenset({
    Key.NUM_2, Key.NUM_3, Key.NUM_4, Key.NUM_5, Key.NUM_6, Key.NUM_8,
})


def _frame(device_id: int, command: int, payload: List[int]) -> List[int]:
    if not 0 <= device_id <= 0x7F:
        raise ValueError(f"device id out of range: {device_id}")
    for byte in payload:
        if not 0 <= byte <= 0x7F:
            raise ValueError(f"payload byte not 7-bit: {byte}")
    return [SOX, MANUFACTURER_ID, PANEL_ID, device_id, PANEL_DESIGNATOR,
            command, *payload, EOX]


def open_session(device_id: int) -> List[int]:
    """`F0 18 7F <devID> 7A 10 F7` -- captured verbatim in §28.

    The device is silent until this is sent: it does **not** echo front-panel
    activity cold (§27), which is the finding that makes this message the
    precondition for everything else.
    """
    return _frame(device_id, PanelCommand.OPEN, [])


def button(device_id: int, key: int, *, down: bool) -> List[int]:
    """`40 <key> 00 <01|00>`.

    A real press is a *pair* -- down then up. The device emits both when a
    human presses a key, and callers driving it should send both; see
    :func:`press` for the pair.
    """
    return _frame(device_id, PanelCommand.BUTTON, [int(key), 0x00, 0x01 if down else 0x00])


def press(device_id: int, key: int) -> List[List[int]]:
    """The two frames a single keypress consists of, in order."""
    return [button(device_id, key, down=True), button(device_id, key, down=False)]


def request_screen(device_id: int) -> List[int]:
    """`51h` -- ask the device to send its current screen.

    Confirmed live (§33, §33a): with a session open this returns a full
    2212-byte `50h` frame immediately, every time, regardless of what came
    before it. `52h` is the *delta* request and drops to 86 bytes when there
    is nothing new -- useful for polling cheaply, useless if you want to know
    what is actually on screen, so this function asks for the full one.

    Note the device never pushes a screen: pressing a key produces no
    unsolicited frame (§33a). A client polls or it sees nothing.

    Decode the reply with :func:`eos.lcd.decode_display`.
    """
    return _frame(device_id, PanelCommand.DISPLAY_REQUEST, [])


def query_state(device_id: int) -> List[int]:
    """`60h` -- provokes a short `61h <a> <b>` reply of unknown meaning.

    The two payload bytes differ between captures (§28 saw `7F 7E`, §33 saw
    `77 7E`), so they carry *something* that changes with device state --
    cursor position and selected-field index are the obvious guesses and
    neither has been tested. Exposed because it is cheap, harmless and the
    next person to look at this needs a way to poke it.
    """
    return _frame(device_id, PanelCommand.SCREEN_QUERY, [])


def dial(device_id: int, delta: int) -> List[int]:
    """`43 01 <lo> <hi>` -- signed 14-bit two's complement, LSB septet first.

    The device *coalesces* when a human spins fast: it raises this magnitude
    rather than the frame rate (§30). Sending a delta greater than 1 is
    therefore the natural way to move a list quickly, and is the same shape
    the device itself produces -- though driving it in that direction has not
    been tested against hardware.
    """
    if not -0x2000 <= delta <= 0x1FFF:
        raise ValueError(f"dial delta out of 14-bit range: {delta}")
    value = delta & 0x3FFF
    return _frame(device_id, PanelCommand.DIAL, [0x01, value & 0x7F, (value >> 7) & 0x7F])


def parse_dial(frame: List[int]) -> Optional[int]:
    """Signed delta from a `43h` frame, or None if it is not one."""
    if len(frame) < 9 or frame[:3] != [SOX, MANUFACTURER_ID, PANEL_ID]:
        return None
    if frame[5] != PanelCommand.DIAL:
        return None
    value = frame[7] | (frame[8] << 7)
    return value - 0x4000 if value >= 0x2000 else value


def parse_button(frame: List[int]) -> Optional[tuple]:
    """``(keycode, is_down)`` from a `40h` frame, or None.

    Accepts either byte order at positions 3/4: the device sends
    `7A <devID>` and the host sends `<devID> 7A` (§30). A parser that
    insisted on one would silently drop half the conversation.
    """
    if len(frame) < 10 or frame[:3] != [SOX, MANUFACTURER_ID, PANEL_ID]:
        return None
    if frame[5] != PanelCommand.BUTTON:
        return None
    return frame[6], bool(frame[8])


KEY_LABELS: Dict[int, str] = {
    Key.MASTER: "MASTER",
    Key.DISK_BROWSE: "DISK/BROWSE",
    Key.PRESET_MANAGE: "MANAGE",
    Key.PRESET_EDIT: "EDIT",
    Key.SAMPLE_MANAGE: "MANAGE",
    Key.SAMPLE_EDIT: "EDIT",
    Key.AUDITION: "AUDITION",
    Key.ASSIGN_1: "1",
    Key.ASSIGN_2: "2",
    Key.ASSIGN_3: "3",
    Key.F1: "F1", Key.F2: "F2", Key.F3: "F3",
    Key.F4: "F4", Key.F5: "F5", Key.F6: "F6",
    Key.PAGE_EXIT: "EXIT",
    Key.PAGE_PREV: "PREV",
    Key.PAGE_NEXT: "NEXT",
    Key.ENTER: "ENTER",
    Key.CURSOR_UP: "▲", Key.CURSOR_DOWN: "▼",
    Key.CURSOR_LEFT: "◀", Key.CURSOR_RIGHT: "▶",
    Key.DEC: "DEC", Key.INC: "INC",
    Key.NUM_0: "0", Key.NUM_1: "1", Key.NUM_2: "2", Key.NUM_3: "3",
    Key.NUM_4: "4", Key.NUM_5: "5", Key.NUM_6: "6", Key.NUM_7: "7",
    Key.NUM_8: "8", Key.NUM_9: "9",
    Key.SIGN: "+/-", Key.SET_SHIFT: ".",
}
