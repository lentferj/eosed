#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.
#
# eosed is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# eosed is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Read a highlighted numeric field off the E4XT's LCD, programmatically.

Written for the voice LFO Rate field, which is how the 128-row rate table in
`docs/data/e4xt_lfo_rate_table.json` was recovered (RESOLUTION_NOTES §103) --
but nothing here is specific to that parameter: it reads whichever numeric
field currently carries the cursor on a voice-edit page.

The field is rendered white-on-black (it carries the cursor), so glyph pixels
are the UNSET pixels inside the highlight block. Glyphs are variable width, so
they are segmented on empty columns and classified by exact bitmap match against
a template library. An unrecognised glyph is reported rather than guessed --
a wrong digit read silently is exactly the failure this whole session has been
about.
"""
import numpy as np, json, os
TEMPLATES = os.environ.get("EOSED_LCD_GLYPHS",
    os.path.join(os.path.dirname(__file__), "lcd_glyphs.json"))

def rate_field(a):
    """(glyph-bitmap, bounds) for the highlighted value field on a Voice LFO page."""
    a = np.asarray(a, dtype=int)
    cand = []
    for y in range(5, 26):
        runs = "".join("#" if v else "." for v in a[y]).split(".")
        if runs and max((len(s) for s in runs), default=0) > 25:
            cand.append(y)
    if not cand:
        return None, None
    y0, y1 = min(cand), max(cand)
    top = a[y0]
    xs = [x for x in range(len(top)) if top[x]]
    x0, x1 = min(xs), max(xs)
    return 1 - a[y0:y1 + 1, x0:x1 + 1], (y0, y1, x0, x1)

def segment(g):
    """glyph sub-bitmaps, split on fully-empty columns"""
    cols = g.any(axis=0)
    out, run = [], []
    for x, on in enumerate(cols):
        if on:
            run.append(x)
        elif run:
            out.append(g[:, run[0]:run[-1] + 1]); run = []
    if run:
        out.append(g[:, run[0]:run[-1] + 1])
    return [trim(s) for s in out]

def trim(s):
    rows = s.any(axis=1)
    if not rows.any():
        return s
    ys = np.where(rows)[0]
    return s[ys[0]:ys[-1] + 1]

def key(s):
    return f"{s.shape[0]}x{s.shape[1]}:" + "".join(str(v) for v in s.flatten())

def load():
    return json.load(open(TEMPLATES)) if os.path.exists(TEMPLATES) else {}

def save(lib):
    json.dump(lib, open(TEMPLATES, "w"), indent=0)

def read_rate(a, lib=None):
    """-> (text, unknown_keys). text is None if any glyph is unrecognised."""
    lib = load() if lib is None else lib
    g, _ = rate_field(a)
    if g is None:
        return None, ["NO FIELD"]
    chars, unknown = [], []
    for s in segment(g):
        k = key(s)
        if k in lib:
            chars.append(lib[k])
        else:
            chars.append("?"); unknown.append(k)
    return "".join(chars), unknown

def learn(a, text):
    """label the glyphs of a field whose value is known"""
    lib = load()
    g, _ = rate_field(a)
    segs = segment(g)
    if len(segs) != len(text):
        return False, f"{len(segs)} glyphs vs {len(text)} chars"
    for s, c in zip(segs, text):
        lib[key(s)] = c
    save(lib)
    return True, f"learned {len(segs)} glyphs"
