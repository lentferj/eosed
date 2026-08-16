# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# The display encoding decoded here is this project's own reverse engineering
# (docs/RESOLUTION_NOTES.md §26, §32). Nothing about the EOS screen has been
# published by E-mu or by any third party that this project has found -- the
# 2016 midimachines page that documents the session handshake explicitly
# covers no screen sequences. See LICENSE.
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

"""Decoding the E4XT's LCD out of a `50h` panel frame.

**The encoding is a plain bitstream, seven bits per byte, MSB first.** Not
MIDI's usual 7->8 byte packing -- that was this project's first reading (§26)
and it was wrong in a way that looked right: 2195 septets x 7/8 truncates to
exactly 1920 bytes, which is 240x64/8, so the arithmetic appeared to confirm
itself while the rendered image sheared progressively across the screen. The
bitstream reading needs no such coincidence: 2195 x 7 = 15365 bits for
15360 pixels, five bits of tail padding, and the picture comes out square.

Worth keeping as a caution: a decoding that produces the *right size* is not
thereby the right decoding, and the confirming arithmetic was the thing that
delayed noticing for a day.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

WIDTH = 240
HEIGHT = 64

#: Bytes 0-5 are the frame header (`F0 18 7F <a> <b> 50`); bytes 6-15 are a
#: sub-header constant across every frame seen; the bitstream follows.
_SUBHEADER = 10
_HEADER = 6

Bitmap = List[List[int]]


def decode_display(frame: Sequence[int]) -> Optional[Bitmap]:
    """A 64x240 bitmap of 0/1 from a `50h` frame, or None if it is not one.

    Returns rows top to bottom, each a list of ``WIDTH`` bits, 1 = lit.
    """
    if len(frame) < _HEADER + _SUBHEADER + 2:
        return None
    if list(frame[:3]) != [0xF0, 0x18, 0x7F] or frame[5] != 0x50:
        return None
    payload = frame[_HEADER + _SUBHEADER:-1]

    bits: List[int] = []
    needed = WIDTH * HEIGHT
    for value in payload:
        for shift in range(6, -1, -1):
            bits.append((value >> shift) & 1)
            if len(bits) >= needed:
                break
        if len(bits) >= needed:
            break
    if len(bits) < needed:
        return None
    return [bits[y * WIDTH:(y + 1) * WIDTH] for y in range(HEIGHT)]


def is_partial(frame: Sequence[int]) -> bool:
    """True for a `50h` frame too short to be a whole screen.

    Partial/region updates exist (§26 saw 86- and 112-byte frames alongside
    the 2212-byte full ones) and their region encoding is not yet known, so
    they cannot be composited onto a previous frame. Callers should keep
    showing the last full screen rather than rendering a fragment as if it
    were the whole display.
    """
    if len(frame) < 7 or frame[5] != 0x50:
        return False
    payload = len(frame) - _HEADER - _SUBHEADER - 1
    return payload * 7 < WIDTH * HEIGHT


#: Braille dot bit order within a 2x4 cell: (x, y) -> bit in U+2800.
_BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def to_braille(bitmap: Bitmap, *, invert: bool = False) -> List[str]:
    """The screen as Unicode braille -- 2x4 pixels per character.

    240x64 becomes 120x16 characters, which fits a pane without scrolling and
    needs nothing from the terminal but a font with U+2800..U+28FF. No kitty
    graphics protocol, no sixel, no image escape codes: braille is the cheap
    portable way to put real pixels in a text grid, and at this size the
    device's own font stays legible.
    """
    lines: List[str] = []
    for cy in range(0, HEIGHT, 4):
        row = []
        for cx in range(0, WIDTH, 2):
            dots = 0
            for dy in range(4):
                for dx in range(2):
                    y, x = cy + dy, cx + dx
                    if y >= HEIGHT or x >= WIDTH:
                        continue
                    lit = bitmap[y][x]
                    if invert:
                        lit = 1 - lit
                    if lit:
                        dots |= _BRAILLE_BITS[dy][dx]
            row.append(chr(0x2800 + dots))
        lines.append("".join(row))
    return lines


#: Half-block rendering: two vertical pixels per character cell, using the
#: upper-half block and reverse video. Wider than braille (240 columns) but
#: blockier and easier to read at a glance on a large terminal.
def to_halfblocks(bitmap: Bitmap) -> List[str]:
    lines: List[str] = []
    for cy in range(0, HEIGHT, 2):
        row = []
        for x in range(WIDTH):
            top = bitmap[cy][x]
            bottom = bitmap[cy + 1][x] if cy + 1 < HEIGHT else 0
            row.append(" ▄▀█"[(top << 1) | bottom])
        lines.append("".join(row))
    return lines


def to_ascii(bitmap: Bitmap) -> List[str]:
    """One character per pixel. For tests and diffs, not for a UI."""
    return ["".join("#" if bit else "." for bit in row) for row in bitmap]
