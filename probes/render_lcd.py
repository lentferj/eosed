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

"""Reconstruct the E4XT LCD from a captured 50h display frame.

The 7->8 unpacking is settled (1920 bytes == 240x64/8). What is not settled is
how those bytes map to pixels, so this renders every plausible layout at once
and lets the eye pick -- the same "try them all, look, then claim" method the
capture itself used.
"""
import json
import struct
import sys
import zlib

W, H = 240, 64


def unpack_7to8(septets):
    out = bytearray()
    i = 0
    while i + 1 < len(septets):
        msb = septets[i]
        chunk = septets[i + 1:i + 8]
        i += 8
        for n, v in enumerate(chunk):
            out.append(v | (0x80 if msb >> n & 1 else 0))
    return bytes(out)


def row_major(data, msb_first=True):
    px = [[0] * W for _ in range(H)]
    for y in range(H):
        for xb in range(W // 8):
            byte = data[y * (W // 8) + xb]
            for b in range(8):
                bit = (byte >> (7 - b)) & 1 if msb_first else (byte >> b) & 1
                px[y][xb * 8 + b] = bit
    return px


def column_pages(data, lsb_top=True):
    """KS0108-style: 8 pages of H/8, each byte is 8 vertical pixels."""
    px = [[0] * W for _ in range(H)]
    for page in range(H // 8):
        for x in range(W):
            byte = data[page * W + x]
            for b in range(8):
                bit = (byte >> b) & 1 if lsb_top else (byte >> (7 - b)) & 1
                px[page * 8 + b][x] = bit
    return px


def halves_stacked(data):
    """Two 240x32 halves, top half first."""
    px = [[0] * W for _ in range(H)]
    half = len(data) // 2
    for which, base in enumerate((0, half)):
        for y in range(32):
            for xb in range(W // 8):
                byte = data[base + y * (W // 8) + xb]
                for b in range(8):
                    px[which * 32 + y][xb * 8 + b] = (byte >> (7 - b)) & 1
    return px


def write_png(path, rows_of_px, scale=2, gap=6):
    """Greyscale PNG, candidates stacked vertically with a grey separator."""
    width = W * scale
    strips = []
    for px in rows_of_px:
        for y in range(H):
            line = bytearray()
            for x in range(W):
                v = 0 if px[y][x] else 255          # ink black on white
                line.extend([v] * scale)
            for _ in range(scale):
                strips.append(bytes(line))
        for _ in range(gap):
            strips.append(bytes([160] * width))

    raw = b"".join(b"\x00" + s for s in strips)
    height = len(strips)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)
    return width, height


def main():
    src, dst = sys.argv[1], sys.argv[2]
    frames = [json.loads(l) for l in open(src)]
    big = max(frames, key=lambda f: f["length"])
    data = unpack_7to8(big["bytes"][16:-1])
    assert len(data) == W * H // 8, len(data)

    candidates = [
        row_major(data, msb_first=True),
        row_major(data, msb_first=False),
        column_pages(data, lsb_top=True),
        column_pages(data, lsb_top=False),
        halves_stacked(data),
    ]
    print(write_png(dst, candidates, scale=2))


if __name__ == "__main__":
    main()
