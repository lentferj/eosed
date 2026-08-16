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

"""The panel screen, live against a real E4XT.

**This transmits.** It opens a panel session (§28) and then polls for screen
updates; with the panel armed (``ctrl+t``) it also sends keypresses. Kept in
``probes/`` rather than wired into ``eosed`` proper because the receive half
lives here: the app's bridge owns the MIDI input for the *editor* protocol,
and having two readers on one port is exactly the kind of thing this project
has already been bitten by.

Refresh follows §33b, measured rather than assumed:

    52h  86 bytes,  70 ms   -> nothing changed, do not repaint
    52h  full frame         -> use it directly (the common case for a change)
    52h  mid-sized partial  -> escalate to 51h, since partials are undecoded
    51h  2212 bytes, 716 ms -> a full screen, on demand and on ctrl+r

Ports default to config.toml's cached send/recv pair, which on this rig are
two *different* interface ports (§26) -- the trap that makes `eoscli --port`
unusable here.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual.app import App                                   # noqa: E402

from eos import bridge as bridge_mod                          # noqa: E402
from eos import lcd                                           # noqa: E402
from eos import panel as pp                                   # noqa: E402
from eosed.panel import PanelScreen                           # noqa: E402


class PanelLink:
    """Owns the two MIDI ports and speaks the panel protocol over them."""

    def __init__(self, send_port: str, recv_port: str, device_id: int):
        import rtmidi

        self.device_id = device_id
        self.out = rtmidi.MidiOut()
        self.inp = rtmidi.MidiIn(queue_size_limit=16384)
        outs, ins = self.out.get_ports(), self.inp.get_ports()
        if send_port not in outs:
            raise SystemExit(f"no output port {send_port!r}")
        if recv_port not in ins:
            raise SystemExit(f"no input port {recv_port!r}")
        self.out.open_port(outs.index(send_port))
        self.inp.open_port(ins.index(recv_port))
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.out.send_message(pp.open_session(device_id))
        time.sleep(0.4)
        self.drain()

    def drain(self) -> None:
        while self.inp.get_message():
            pass

    def send(self, frame) -> None:
        self.out.send_message(list(frame))

    def _await_display(self, timeout: float):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            message = self.inp.get_message()
            if message is None:
                time.sleep(0.001)
                continue
            frame = message[0]
            if len(frame) > 6 and frame[5] == 0x50:
                return frame
        return None

    def _ask(self, frame, timeout):
        self.drain()
        self.out.send_message(frame)
        return self._await_display(timeout)

    def poll(self):
        """§33b's policy. Returns a bitmap to repaint with, or None."""
        reply = self._ask(pp.update_screen(self.device_id), 1.5)
        decision = lcd.classify_update(reply)
        if decision == lcd.RefreshDecision.IDLE:
            return None
        if decision == lcd.RefreshDecision.USE:
            return lcd.decode_display(reply)
        return self.full()

    def full(self):
        reply = self._ask(pp.request_screen(self.device_id), 3.0)
        return lcd.decode_display(reply) if reply else None

    def close(self) -> None:
        for port in (self.out, self.inp):
            try:
                port.close_port()
                port.delete()
            except Exception:
                pass


class LivePanel(App):
    CSS = "Screen { align: center middle; }"

    def __init__(self, link: PanelLink, allow_write: bool, mode: str = "quadrant"):
        super().__init__()
        self.link = link
        self.allow_write = allow_write
        self.mode = mode

    def on_mount(self) -> None:
        screen = PanelScreen(
            allow_write=self.allow_write, device_id=self.link.device_id,
            send=self.link.send, bitmap=self.link.full(), poll=self.link.poll)
        screen.render_mode = self.mode
        # Quit when the panel is dismissed. In eosed proper, escape returns to
        # the main view; here the panel *is* the application, so dismissing it
        # left a black window with nothing behind it and no way back -- which
        # looks exactly like a crash. Reported as "hitting ESC accidentally
        # made the screen go blank".
        self.push_screen(screen, lambda _result: self.exit())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Live front panel against an E4XT.")
    parser.add_argument("--device-id", type=int, required=True,
                        help="must match Device Inquiry; guessing 0 makes a live machine look dead")
    parser.add_argument("--send-port")
    parser.add_argument("--recv-port")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--mode", default="quadrant",
                        choices=("quadrant", "half", "braille"),
                        help="LCD render; half-block needs a 244-column terminal")
    parser.add_argument("--allow-write", action="store_true",
                        help="permit arming; without it ctrl+t refuses")
    args = parser.parse_args(argv)

    send, recv = args.send_port, args.recv_port
    if not (send and recv):
        cached = bridge_mod.load_last_ports(args.config)
        if not cached:
            raise SystemExit("no ports given and none cached; run `eoscli inquire` once")
        send, recv = send or cached[0], recv or cached[1]

    link = PanelLink(send, recv, args.device_id)
    try:
        LivePanel(link, args.allow_write, args.mode).run()
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
