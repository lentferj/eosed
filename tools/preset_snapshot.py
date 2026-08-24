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
"""Capture and replay a preset's VOICE PARAMETERS, as a stand-in for restore.

    tools/preset_snapshot.py capture 22 pc22.json
    tools/preset_snapshot.py verify  22 pc22.json      # diff, writes nothing
    tools/preset_snapshot.py replay  22 pc22.json

WHY THIS EXISTS. The E4XT's RAM does not survive a power cycle -- it comes back
empty (docs/RESOLUTION_NOTES.md §48) -- and preset *restore* is not built in
either dump format (see TODO.md). So until 2026-08-24 every hand-built reference
preset on the bench was one power cycle away from gone, and reproducing a
session's worth of edits meant reading them out of a chat log.

WHAT IT IS NOT. **This is not the missing restore.** It replays the editor
protocol's per-voice parameter table and nothing else: no sample zones, no
links, no preset-level fields, no sample data, and no name. A preset whose
character lives in its zone layout will not come back from this. It reproduces
what a session of parameter edits did, which is the case that keeps arising.

WHY IT VERIFIES BEFORE IT TRUSTS. `verify` reads the device and diffs against
the file without writing anything, and `replay` re-reads every value after
writing it. A capture nobody has restored from is a backup nobody has restored
from; `verify` makes checking one free.

Parameters that the device declines to answer are omitted from the capture
rather than stored as a guess, and a replay reports what it could not set
instead of failing silently.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Dict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from eos import bridge as bridge_mod  # noqa: E402
from eos import params  # noqa: E402

PRESET_SELECT, VOICE_SELECT = 223, 225

#: The voice-scoped groups, in id order. Deliberately explicit rather than
#: "everything in eos.params": preset- and master-scoped ids must not be
#: replayed per voice, and cords past 11 read back as unallocated junk on this
#: firmware (§53), so they are excluded rather than captured and written back.
GROUPS = ("voice.general", "voice.tuning", "voice.mode", "voice.amp",
          "voice.amp.env", "voice.filter", "voice.filter.env", "voice.lfo",
          "voice.aux.env", "voice.cords")
MAX_CORD = 12


def voice_param_ids() -> list:
    ids = []
    for p in sorted(params.PARAMETERS.values(), key=lambda p: p.id):
        if p.group not in GROUPS:
            continue
        if p.group == "voice.cords" and (p.id - 129) // 3 >= MAX_CORD:
            continue
        ids.append(p.id)
    return ids


def _confirm(b, pid: int, want: int, tries: int = 5) -> bool:
    for _ in range(tries):
        b.set_parameter(pid, want)
        time.sleep(0.12)
        try:
            if b.get_parameter(pid, timeout=1.0) == want:
                return True
        except Exception:
            pass
        time.sleep(0.18)
    return False


def _select(b, preset: int, voice: int) -> None:
    if not _confirm(b, PRESET_SELECT, preset):
        raise RuntimeError(f"could not select preset {preset}")
    if not _confirm(b, VOICE_SELECT, voice):
        raise RuntimeError(f"could not select voice {voice}")


def read_voice(b, preset: int, voice: int, ids) -> Dict[int, int]:
    _select(b, preset, voice)
    out = {}
    for pid in ids:
        try:
            out[pid] = b.get_parameter(pid, timeout=1.0)
        except Exception:
            pass          # omitted, not guessed
    return out


def cmd_capture(args, b) -> None:
    ids = voice_param_ids()
    voices = {}
    for v in range(args.voices):
        row = read_voice(b, args.preset, v, ids)
        voices[str(v)] = {str(k): int(val) for k, val in row.items()}
        print(f"  voice {v}: {len(row)} of {len(ids)} parameters", flush=True)
    with open(args.file, "w") as fh:
        json.dump({"preset": args.preset, "voices": voices}, fh, indent=1)
    print(f"  -> {args.file}")


def cmd_verify(args, b) -> int:
    data = json.load(open(args.file))
    diffs = 0
    for vs, want in sorted(data["voices"].items(), key=lambda kv: int(kv[0])):
        got = read_voice(b, args.preset, int(vs), [int(k) for k in want])
        bad = [(int(k), int(v), got.get(int(k)))
               for k, v in want.items() if got.get(int(k)) != int(v)]
        diffs += len(bad)
        print(f"  voice {vs}: {len(want) - len(bad)}/{len(want)} match"
              + ("" if not bad else "   differs: " + ", ".join(
                  f"id {i}={g} (file {w})" for i, w, g in bad[:8])
                 + (" ..." if len(bad) > 8 else "")))
    print(f"\n  {'IDENTICAL' if not diffs else str(diffs) + ' DIFFERENCES'}")
    return 1 if diffs else 0


def cmd_replay(args, b) -> int:
    data = json.load(open(args.file))
    failed = []
    for vs, want in sorted(data["voices"].items(), key=lambda kv: int(kv[0])):
        v = int(vs)
        _select(b, args.preset, v)
        for k, val in sorted(want.items(), key=lambda kv: int(kv[0])):
            pid, target = int(k), int(val)
            if not _confirm(b, pid, target):
                failed.append((v, pid, target))
        print(f"  voice {v}: {len(want) - len([f for f in failed if f[0] == v])}"
              f"/{len(want)} written", flush=True)
    if failed:
        print("\n  COULD NOT SET:")
        for v, pid, target in failed:
            print(f"    voice {v} id {pid} -> {target}")
    print(f"\n  {'all values written and read back' if not failed else str(len(failed)) + ' FAILED'}")
    return 1 if failed else 0


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=bridge_mod.DEFAULT_CONFIG_PATH)
    ap.add_argument("--voices", type=int, default=6,
                    help="how many voices to cover (default: 6)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("capture", "read the device into a file"),
                           ("verify", "diff the device against a file, writing nothing"),
                           ("replay", "write a file back to the device")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("preset", type=int)
        s.add_argument("file")
    args = ap.parse_args(argv)

    b = bridge_mod.EosBridge.autodetect()
    try:
        rc = {"capture": cmd_capture, "verify": cmd_verify,
              "replay": cmd_replay}[args.cmd](args, b)
    finally:
        _confirm(b, VOICE_SELECT, 0)
        b.close()
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
