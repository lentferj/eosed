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
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Load a bank from disk into RAM, over the panel protocol, verifiably.

WHY THIS IS A TOOL AND NOT A PARAGRAPH
======================================
The load path is described in RESOLUTION_NOTES 34 and 48 and has been walked
"dozens of times" (Jan, 2026-09-14) -- and re-derived from that prose every
time, hitting the same two traps on the way. A procedure that is reconstructed
from prose on each use is not recorded, it is remembered. This is the fix:
the sequence lives in code, the traps live in guards, and the result is checked
against the device rather than assumed.

THE TWO TRAPS, BOTH OF WHICH PRODUCE A PLAUSIBLE WRONG STATE
============================================================
1. **F4 on an already-open LOAD dialog is MERGE, not "close".** Section 48
   lists Merge as a button on that screen. Pressing F4 twice -- the natural
   thing to do when a previous run left the dialog open -- therefore performs
   a LOAD, silently, and then the screen returns to the main page looking
   exactly as though the dialog had been dismissed. This cost a session on
   2026-09-14: the bank arrived in RAM with nothing having asked for it.
   GUARD: never press F4 without first classifying the screen.

2. **There are THREE screens, not two.** A detector tuned on "main page" and
   "LOAD dialog" reads the *destroy-confirm* as whichever of the two its
   threshold happens to fall nearest, and on 2026-09-14 it read it as the main
   page and reported a load complete that had not started. GUARD: classify
   into MAIN / LOAD / CONFIRM explicitly, and treat anything else as UNKNOWN
   and stop.

MEASURED SCREEN SIGNATURES (E4XT Ultra, EOS 4.70, 240x64)
=========================================================
    screen          longest vertical run   longest horizontal run
    MAIN                    17                     35
    LOAD dialog             51                    221
    destroy-confirm         27                    148

THE CONFIRM IS NEVER ANSWERED AUTOMATICALLY
===========================================
"Destroys current RAM Bank... continue?" appears only when RAM is NOT empty,
so seeing it means this load would discard something a previous step put
there. `--destroy` is required to answer it, and without that flag the tool
CANCELS and says so. That is the RAM-only analogue of the arm-then-fire rule
the Erase utilities get: nothing here can touch a disk, but discarding a bank
someone is mid-measurement on is still a surprise worth refusing to cause.

VERIFICATION IS PART OF THE LOAD
================================
The panel says a load finished; only the preset names say what arrived. The
tool closes its panel ports, opens the editor protocol, and reads the catalog
back -- section 47/48's rule, which is the only thing that actually settles
where a bank landed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rtmidi                                             # noqa: E402
from eos import bridge as bridge_mod, lcd, panel as pp    # noqa: E402

CONFIG = str(Path(__file__).resolve().parent.parent / "config.toml")
DEV = 5
SETTLE = 0.45

MAIN, LOAD, CONFIRM, UNKNOWN = "MAIN", "LOAD", "CONFIRM", "UNKNOWN"


def _runs(bitmap):
    """(longest vertical run, longest horizontal run) of set pixels."""
    rows = [list(r) for r in bitmap]

    def longest(lines):
        best = 0
        for line in lines:
            run = 0
            for v in line:
                run = run + 1 if v else 0
                best = max(best, run)
        return best

    return longest(zip(*rows)), longest(rows)


def classify(bitmap):
    """MAIN / LOAD / CONFIRM / UNKNOWN from the screen's box geometry.

    Deliberately three-way plus an explicit UNKNOWN: a two-way classifier is
    what mis-read the confirm dialog as a finished load (see module docstring).
    """
    if bitmap is None:
        return UNKNOWN, (None, None)
    v, h = _runs(bitmap)
    if v >= 40 and h >= 180:
        return LOAD, (v, h)
    if 20 <= v < 40 and h >= 100:
        return CONFIRM, (v, h)
    if v < 20 and h < 100:
        return MAIN, (v, h)
    return UNKNOWN, (v, h)


class Panel:
    """Panel session. Sends only frames eos.panel builds, and never 7F 00."""

    def __init__(self, send_port: str, recv_port: str):
        self.out, self.inp = rtmidi.MidiOut(), rtmidi.MidiIn(queue_size_limit=16384)
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.out.open_port(self.out.get_ports().index(send_port))
        self.inp.open_port(self.inp.get_ports().index(recv_port))
        self._send(pp.open_session(DEV))
        time.sleep(0.35)
        self._drain()

    def _send(self, frame):
        f = list(frame)
        # The front-panel divert must never leave this process, whatever built
        # the frame. Asserted on the wire, not at the call sites.
        if len(f) >= 7 and f[4] == pp.PANEL_DESIGNATOR and f[5:7] == [0x7F, 0x00]:
            raise SystemExit("REFUSED: front-panel divert")
        self.out.send_message(f)
        time.sleep(0.05)

    def _drain(self):
        while self.inp.get_message():
            pass

    def key(self, k, settle=SETTLE):
        for frame in pp.press(DEV, k):
            self._send(frame)
        time.sleep(settle)
        self._drain()

    def screen(self, timeout=3.0):
        self._drain()
        self._send(pp.request_screen(DEV))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            msg = self.inp.get_message()
            if msg and len(msg[0]) > 500 and msg[0][5] == 0x50:
                return lcd.decode_display(msg[0])
            time.sleep(0.002)
        return None

    def state(self):
        return classify(self.screen())

    def close(self):
        for p in (self.out, self.inp):
            try:
                p.close_port(); p.delete()
            except Exception:
                pass


def _to_main(panel, verbose=True):
    """Leave the device on the main preset page, pressing only Cancel."""
    for _ in range(4):
        st, m = panel.state()
        if verbose:
            print(f"    screen: {st} {m}")
        if st == MAIN:
            return
        if st == UNKNOWN:
            raise SystemExit(f"  unrecognised screen {m}; refusing to press keys blind")
        panel.key(pp.Key.F1, settle=0.8)     # Cancel on both dialogs
    raise SystemExit("  could not reach the main preset page")


def load(panel, *, drive_steps=0, bank_steps=0, destroy=False, timeout=180.0):
    _to_main(panel)

    panel.key(pp.Key.F4, settle=0.8)         # F4 on MAIN opens the LOAD dialog
    st, m = panel.state()
    if st != LOAD:
        raise SystemExit(f"  F4 did not open the LOAD dialog (got {st} {m})")
    print("    LOAD dialog open")

    # Fields are Drive / Folder / Bank, top to bottom; INC/DEC step the value.
    # Changing Drive re-points Bank to that volume's B000 (section 48), so
    # Drive is stepped first and Bank after, never the reverse.
    for _ in range(abs(drive_steps)):
        panel.key(pp.Key.INC if drive_steps > 0 else pp.Key.DEC)
    if drive_steps:
        panel.key(pp.Key.CURSOR_DOWN); panel.key(pp.Key.CURSOR_DOWN)
    elif bank_steps:
        panel.key(pp.Key.CURSOR_DOWN); panel.key(pp.Key.CURSOR_DOWN)
    for _ in range(abs(bank_steps)):
        panel.key(pp.Key.INC if bank_steps > 0 else pp.Key.DEC)

    print("    firing Load (F6)")
    panel.key(pp.Key.F6, settle=1.0)

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        st, m = panel.state()
        if st == CONFIRM:
            if not destroy:
                print("    'Destroys current RAM Bank' -- RAM is NOT empty.")
                print("    CANCELLING: pass --destroy to answer this deliberately.")
                panel.key(pp.Key.F1, settle=0.8)
                return False
            print("    confirming (--destroy given)")
            panel.key(pp.Key.F6, settle=1.0)
            continue
        if st == MAIN:
            print(f"    back on the main page after {time.monotonic()-start:.1f}s")
            return True
        time.sleep(1.5)
    raise SystemExit("  timed out waiting for the load to finish")


def verify(limit=24):
    """Read the preset names back. The panel cannot answer this; only RAM can."""
    b = bridge_mod.EosBridge.autodetect(device_id=DEV, timeout=2.0, config_path=CONFIG)
    return b.catalog_presets(range(0, limit))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--drive-steps", type=int, default=0,
                    help="INC(+)/DEC(-) steps on the Drive field before loading")
    ap.add_argument("--bank-steps", type=int, default=0,
                    help="INC(+)/DEC(-) steps on the Bank field before loading")
    ap.add_argument("--destroy", action="store_true",
                    help="answer 'Destroys current RAM Bank' -- required when RAM is not empty")
    ap.add_argument("--state-only", action="store_true",
                    help="classify the current screen and exit, pressing nothing")
    args = ap.parse_args(argv)

    send, recv = bridge_mod.load_last_ports(CONFIG)
    panel = Panel(send, recv)
    try:
        if args.state_only:
            st, m = panel.state()
            print(f"  screen: {st}  (vrun,hrun)={m}")
            return 0
        ok = load(panel, drive_steps=args.drive_steps, bank_steps=args.bank_steps,
                  destroy=args.destroy)
    finally:
        panel.close()
        time.sleep(0.3)
    if not ok:
        return 2
    print("  verifying against RAM (the panel cannot answer this):")
    names = verify()
    for number in sorted(names):
        print(f"    {number:4d}  {names[number]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
