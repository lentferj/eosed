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

"""Open a panel/remote session, then listen while a human works the panel.

**This TRANSMITS.** It is the first thing in this project that sends on the
undocumented protocol, which is why it is a separate tool and not a flag on
``panel_capture.py`` -- that harness's "never sends a byte" property is worth
keeping absolutely, so it can always be pointed at hardware without thought.

WHAT IT SENDS, EXHAUSTIVELY

    F0 18 7F <devID> 7A 10 F7        once, at startup

That is it. One frame, the session-open message captured verbatim in §28 from
a real handshake on this exact firmware -- not §3's published variant, and not
a shape-corrected guess. §3's rule is that no byte sequence goes out that is
not backed by a capture recorded in RESOLUTION_NOTES; this one is, and nothing
else is, so nothing else is sent. In particular it does **not** send the close
message: §28a notes the only published version of that has its manufacturer id
transposed, and we have never captured one.

WHY IT EXISTS

§27 established that the E4XT stays silent until remote communication is
opened -- pressing front-panel keys on a cold machine emits nothing. Once a
session is open the device echoes panel activity as `40 <key> 00 <01|00>`
(§26). So opening the session ourselves is the difference between needing a
browser running someone else's tool in the loop and needing nothing at all.

With this, the whole remaining capture plan is a person pressing keys:
the key-code table, then the navigation to the disk pages, then the load.

PORTS

Defaults come from ``config.toml``'s cached ``send_port``/``recv_port``, which
is the pair autodetect proved. Do not assume they are the same port -- on the
author's rig the E4XT is sent to on one interface port and heard on another
(§26), which is exactly the trap that makes ``eoscli --port`` unusable there.

HOW TO RUN A SESSION

  1. Start it. It prints the frame it sent and then everything it hears.
  2. Press ONE key. Wait for the two lines (down, then up).
  3. Keep going, one key at a time, pausing a few seconds between them --
     the gaps segment the log when markers are impossible because both your
     hands are on the machine.
  4. Ctrl-C, or let --duration expire. Write down the order you pressed them
     in; that plus the timestamps is the key-code table.

IF NOTHING COMES BACK

The session did not open. That is a finding, not a failure -- record it. Most
likely causes, in order: wrong ``--device-id`` (it must match what Device
Inquiry reports, which is NOT necessarily 0); the mididings SysEx strip back
in the route (§5); or the open message being version-specific in a way §28's
single capture cannot show.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import panel_capture as pc                                    # noqa: E402
from eos import bridge as bridge_mod                          # noqa: E402


def open_frame(device_id: int) -> List[int]:
    """The §28 session-open message. The ONLY thing this tool transmits."""
    return [0xF0, 0x18, 0x7F, device_id, 0x7A, 0x10, 0xF7]


def resolve_ports(args) -> tuple:
    if args.send_port and args.recv_port:
        return args.send_port, args.recv_port
    cached = bridge_mod.load_last_ports(args.config)
    if not cached:
        raise SystemExit(
            "error: no --send-port/--recv-port given and no cached pair in "
            f"{args.config}. Run `eoscli inquire` once to populate it.")
    send, recv = cached
    return args.send_port or send, args.recv_port or recv


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open a panel session (§28) and log what the device echoes. "
                    "Sends exactly one frame, ever.")
    parser.add_argument("--device-id", type=int, default=None,
                        help="SysEx device id; must match Device Inquiry (not always 0)")
    parser.add_argument("--send-port")
    parser.add_argument("--recv-port")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("-o", "--output")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the frame that would be sent and exit")
    args = parser.parse_args(argv)

    if args.device_id is None:
        raise SystemExit("error: --device-id is required; run `eoscli inquire` to find it. "
                         "Guessing 0 is how a live machine looks dead (§26).")

    frame = open_frame(args.device_id)
    print("will send exactly one frame: " + pc.hexs(frame))
    if args.dry_run:
        return 0

    send_name, recv_name = resolve_ports(args)
    print(f"send: {send_name}\nrecv: {recv_name}")

    import rtmidi

    out = rtmidi.MidiOut()
    inp = rtmidi.MidiIn(queue_size_limit=8192)
    try:
        outs = out.get_ports()
        ins = inp.get_ports()
        if send_name not in outs:
            raise SystemExit(f"error: no output port {send_name!r}")
        if recv_name not in ins:
            raise SystemExit(f"error: no input port {recv_name!r}")
        out.open_port(outs.index(send_name))
        inp.open_port(ins.index(recv_name))
        inp.ignore_types(sysex=False, timing=True, active_sense=True)

        capture = pc.Capture()
        handle = open(args.output, "a", encoding="utf-8") if args.output else None
        started = time.monotonic()

        out.send_message(frame)
        print(f"{0.0:9.3f} --- SENT: {pc.hexs(frame)} ---")

        try:
            while time.monotonic() - started < args.duration:
                message = inp.get_message()
                if message is None:
                    time.sleep(0.002)
                    continue
                data, _delta = message
                event = capture.add_frame(data, port=recv_name,
                                          at=time.monotonic() - started)
                opcode = pc.panel_opcode(data)
                label = pc.PANEL_OPCODES.get(opcode, "") if opcode is not None else ""
                print(f"{event['at']:9.3f} {event['dialect']:<8} len={event['length']:<5} "
                      f"{event['hex'][:78]}  {label}")
                if handle:
                    handle.write(json.dumps(event) + "\n")
                    handle.flush()
        except KeyboardInterrupt:
            print()
        finally:
            if handle:
                handle.close()

        print(capture.report())
        if not capture.frames():
            print("\nnothing came back -- see 'IF NOTHING COMES BACK' in this file")
        return 0
    finally:
        for port in (out, inp):
            try:
                port.close_port()
                port.delete()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
