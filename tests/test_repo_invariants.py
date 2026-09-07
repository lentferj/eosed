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
"""Repo-wide invariants over every TRACKED Python file.

Added 2026-09-07 after a sibling project promoted a script out of a gitignored
directory and the act of tracking it surfaced two real defects that had been
sitting there unseen: text I/O with no explicit encoding, which works on a
UTF-8 locale and breaks elsewhere. **The ignore rule had been hiding a defect,
not merely a file.** These checks scan what is tracked, so the same class cannot
re-enter through a file nobody looks at.

Scope is deliberately the tracked set rather than the working tree: bench and
scratch files are not distributed and are not held to this.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked_python():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.split() if line]


def test_there_are_tracked_python_files():
    """Guard the guard: a broken listing would make every check below vacuous."""
    assert len(_tracked_python()) > 10


def test_every_tracked_python_file_has_an_spdx_header():
    missing = []
    for path in _tracked_python():
        head = path.read_text(encoding="utf-8")[:400]
        if "SPDX-License-Identifier: GPL-2.0-or-later" not in head:
            missing.append(str(path.relative_to(ROOT)))
    assert not missing, f"missing SPDX header: {missing}"


def _text_opens_without_encoding(tree):
    """`open(...)` calls in text mode with no encoding= argument."""
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "open"):
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        if "encoding" in kwargs:
            continue
        mode = ""
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value or ""
        if "b" in mode:
            continue
        bad.append(node.lineno)
    return bad


def test_no_tracked_text_io_without_an_explicit_encoding():
    """Locale-dependent text I/O: fine on a UTF-8 box, wrong on another."""
    offenders = {}
    for path in _tracked_python():
        src = path.read_text(encoding="utf-8")
        lines = _text_opens_without_encoding(ast.parse(src))
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert not offenders, f"open() in text mode without encoding=: {offenders}"
