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

"""Capture harness for the undocumented panel/remote protocol (§3).

**PASSIVE. THIS NEVER SENDS A SINGLE BYTE.**

That is not caution for its own sake. §3's rule is that no code may be written
against a byte sequence for this protocol that is not backed by a capture
recorded in `docs/RESOLUTION_NOTES.md`, and a prober that transmits is already
breaking it -- the only sequences we could send are the four published
fragments, none of which this project has verified. So this listens, and the
device is driven by something that already knows how: a browser running Ray
Bellis's e-remote (<https://emu.tools>) against the same E4XT. We sniff the
conversation between them. Nothing here talks to the sampler.

SCOPE (2026-08-14): this serves a **disk load trigger, not a screen mirror.**
Mirroring the LCD and injecting keypresses would be Ray Bellis's e-remote
rebuilt from its own traffic — allowed, since the protocol facts are E-mu's
and we read the wire rather than his code, but not what this project is for.
The browse half comes from the disk *image* (parsed off-device); this protocol
is only for selecting a bank and firing the load. See TODO and §26.

Consequence for how you use this: the key-code table is the critical path, and
capturing it needs **no e-remote at all** — the device echoes its own
front-panel presses (§3), so a human at the machine is the traffic source.

WHAT IT IS FOR

Selecting a disk, browsing it, and loading a bank -- from the desk rather than
the front panel -- is the use case that motivates the panel protocol at all
(TODO.md). None of it is reachable from the documented editor protocol: the
whole command table, 01h-7Ah, is RAM-scoped and has no disk surface. So the
the *load* has to come out of this protocol. The browse does not: it comes
from the disk image, which is written off-device here and is parseable
already.

That is a correction of what this file said when it was written. It argued
"screen first, buttons are worthless without it" — true for a mirror, and the
scope decision above rules a mirror out. With browsing moved off-device, the
**key-code table is the critical path** and the display is needed only to
confirm which page is showing before firing, which is a far smaller problem
than decoding one well enough to read a directory from.

WHAT IS ALREADY KNOWN (§3, third-party, unverified by us)

    F0 18 7F 00 00 7F 11 00 08 F7   init handshake
    F0 18 7F 00 00 10 F7            enable remote ("open" the sampler)
    F0 18 7F 00 00 7F 11 06 04 F7   emitted on a front-panel button press
    F0 18 7F 00 00 11 F7            close communication

Note the frame shape differs from the editor protocol: device id is fixed at
00/7F and there is no 55h designator byte. Every press emits **two** messages
(down and up) -- the device echoes panel activity, unlike the K2000.

Unknown, and what a session is for: the display-frame encoding (size, packing,
full-frame vs delta), the button-code table, and the wheel encoding.

BEFORE YOU RUN IT

  * `~/mididings_e4xt.py` strips all SYSTEM messages, SysEx included, on the
    E4XT's live route (§5). Bypass or change it first or this captures
    nothing and you will think the protocol is quiet.
  * Only one session drives the E4XT at a time (CLAUDE.md). This opens MIDI
    *input* ports only, but that is still a port -- do not run it while
    another session or probe is live.
  * A capture is worthless without knowing what you did. Use markers: type a
    short label and press Enter to stamp the log ("about to press F1"), then
    do the thing. `--markers-only` is the disciplined mode: nothing is logged
    until the first marker.

HOW TO RUN A SESSION

  1. Bypass the mididings SysEx strip. Confirm with `aseqdump` if unsure.
  2. Start e-remote in a browser and connect it to the E4XT.
  3. Start this on the same ports:  `python probes/panel_capture.py -o panel.jsonl`
  4. Exercise **one control at a time**, marker before each:
       a. one soft key, released cleanly
       b. one data-wheel click, one direction
       c. something that changes ONLY the LCD and nothing else
       d. then, and only then, navigate toward the disk pages
  5. Ctrl-C. Read the summary. Commit the .jsonl and the summary into
     `docs/captures/` and write what they showed into RESOLUTION_NOTES §3.

Diffing consecutive same-length frames is what exposes a delta-encoded screen:
if a frame repeats with two bytes changed after a cursor move, those two bytes
are the cursor. `--analyse FILE` re-runs the whole summary over a saved log,
so the thinking can happen after the hardware is back in its rack.

IF NOTHING ARRIVES

Do not conclude the protocol is dead. In order of likelihood: the mididings
strip is still in the path; you are listening on the wrong port (e-remote may
be talking to a different one -- run with no `--port` to listen to all of
them); rtmidi is dropping oversized SysEx (raise `--buffer`); or e-remote
never completed its handshake, in which case the device is not "open" and
genuinely is not sending. The last one is a finding, not a failure -- record
it either way, and it is exactly what §3 means when it says a capture must
back every claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --- frame classification (pure) --------------------------------------------
# Kept free of MIDI so the whole analysis half is testable synthetically, the
# same split the app uses for _dangling_sample_refs. A probe that mis-parses
# does not fail loudly -- it quietly wastes a hardware session, which is the
# one resource this project cannot re-run cheaply.

# Three bytes, not five. §3 recorded the panel frame as `F0 18 7F 00 00 …`
# with "device id fixed at 00/7F" -- and the first real capture (2026-08-14,
# E4XT Ultra, firmware 4.70) shows that is wrong: the frames are
# `F0 18 7F <devID> 7A …`, where <devID> is the machine's actual SysEx device
# id (05 here, matching what Device Inquiry reports) and 7Ah sits where §3
# expected 00. Matching on five bytes classified every real panel frame as
# generic "sysex" -- the harness watched the protocol it was built for go past
# and did not recognise it. See §26.
PANEL_PREFIX = (0xF0, 0x18, 0x7F)
EDITOR_PREFIX = (0xF0, 0x18, 0x21)
EDITOR_DESIGNATOR = 0x55

#: The four fragments §3 records, for recognition only -- never for sending.
KNOWN_FRAGMENTS: Dict[Tuple[int, ...], str] = {
    (0xF0, 0x18, 0x7F, 0x00, 0x00, 0x7F, 0x11, 0x00, 0x08, 0xF7): "init handshake",
    (0xF0, 0x18, 0x7F, 0x00, 0x00, 0x10, 0xF7): "enable remote",
    (0xF0, 0x18, 0x7F, 0x00, 0x00, 0x7F, 0x11, 0x06, 0x04, 0xF7): "button press (published example)",
    (0xF0, 0x18, 0x7F, 0x00, 0x00, 0x11, 0xF7): "close communication",
}


#: Panel opcodes seen in the 2026-08-14 capture (§26). Byte 5, after
#: `F0 18 7F <devID> 7A`. Labels marked "?" are named from position and
#: co-occurrence only -- one capture, no second machine, no version spread --
#: so treat them as handles for reading a log, not as protocol facts.
PANEL_OPCODES: Dict[int, str] = {
    0x40: "button down/up",       # 40 <key> 00 <01=down|00=up>, confirmed by 3 keys
    0x50: "display data",         # + 10-byte sub-header + 7-bit packed bitmap
    0x52: "display follows?",     # always immediately precedes a 50
    0x60: "screen request?",      # always immediately follows a button-down
    0x61: "screen ack?",          # 61 7F 7F
}


def panel_opcode(frame: Sequence[int]) -> Optional[int]:
    """The opcode byte of a panel frame, or None if this is not one.

    Position 5: `F0 18 7F <devID> 7A <opcode>`. Note this reads the *device
    id* at 3 rather than assuming a fixed value, which is what §3 got wrong.
    """
    if len(frame) < 6 or tuple(frame[:3]) != PANEL_PREFIX:
        return None
    return frame[5]


def classify(frame: Sequence[int]) -> str:
    """Which dialect a frame belongs to: panel, editor, sysex or non-sysex.

    The two dialects are told apart by prefix, not by guessing from content:
    panel is ``F0 18 7F 00 00``, editor is ``F0 18 21 <devID> 55``. Anything
    else that starts F0 is some other manufacturer's or E-mu's own other
    product family (§4 -- Proteus and Morpheus share the 18h id), and is
    reported as plain "sysex" rather than silently dropped, because a capture
    that hides traffic is worse than one that shows too much.
    """
    if not frame or frame[0] != 0xF0:
        return "non-sysex"
    if tuple(frame[:3]) == PANEL_PREFIX:
        return "panel"
    if tuple(frame[:3]) == EDITOR_PREFIX and len(frame) > 4 and frame[4] == EDITOR_DESIGNATOR:
        return "editor"
    return "sysex"


def describe_known(frame: Sequence[int]) -> Optional[str]:
    """The §3 label for an exactly-matching published fragment, else None."""
    return KNOWN_FRAGMENTS.get(tuple(frame))


def hexs(frame: Iterable[int]) -> str:
    return " ".join(f"{byte:02X}" for byte in frame)


def diff_positions(a: Sequence[int], b: Sequence[int]) -> List[int]:
    """Byte offsets where two equal-length frames differ.

    Returns [] for different lengths: a length change is not a diff, it is a
    different kind of message, and pretending otherwise produces noise exactly
    where the screen encoding would be.
    """
    if len(a) != len(b):
        return []
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


def summarise_diffs(frames: Sequence[Sequence[int]]) -> Dict[int, Dict[str, object]]:
    """Per frame-length: how many seen, and which offsets ever varied.

    Grouping by length is the crude but effective way in: a delta-encoded
    display frame repeats at one size, and the offsets that move between
    consecutive ones are the payload. Offsets that *never* move across a whole
    session are structure -- header, opcode, checksum -- and are just as
    informative.
    """
    by_length: Dict[int, List[Sequence[int]]] = {}
    for frame in frames:
        by_length.setdefault(len(frame), []).append(frame)

    summary: Dict[int, Dict[str, object]] = {}
    for length, group in sorted(by_length.items()):
        varying: Dict[int, int] = {}
        for previous, current in zip(group, group[1:]):
            for offset in diff_positions(previous, current):
                varying[offset] = varying.get(offset, 0) + 1
        constant = [i for i in range(length) if i not in varying]
        summary[length] = {
            "count": len(group),
            "varying": dict(sorted(varying.items())),
            "constant": constant,
        }
    return summary


@dataclass
class Capture:
    """An in-memory capture, so analysis works on live and saved logs alike."""

    events: List[dict] = field(default_factory=list)

    def add_frame(self, frame: Sequence[int], *, port: str, at: float) -> dict:
        event = {
            "kind": "frame",
            "at": round(at, 6),
            "port": port,
            "dialect": classify(frame),
            "length": len(frame),
            "hex": hexs(frame),
            "bytes": list(frame),
        }
        known = describe_known(frame)
        if known:
            event["known"] = known
        self.events.append(event)
        return event

    def add_marker(self, label: str, *, at: float) -> dict:
        event = {"kind": "marker", "at": round(at, 6), "label": label}
        self.events.append(event)
        return event

    def frames(self, dialect: Optional[str] = None) -> List[List[int]]:
        # .get, not [], and skip what has none: a session ended by Ctrl-C or a
        # crash can leave a half-written final line, and losing the whole
        # analysis of a hardware session to its last truncated frame would be
        # a poor trade.
        # Dialect is recomputed from the bytes, never read back from the
        # stored field -- for the same reason as the "known" label above, and
        # this one bit for real: the first live capture was logged by a build
        # whose classifier had §3's wrong 5-byte prefix, so every panel frame
        # was filed as generic "sysex". Re-analysing an old log with a fixed
        # classifier has to produce the fixed answer, or the fix is invisible
        # exactly where it matters. Fixing this for `known` and leaving it
        # here was the same mistake §24 caught: half a mechanism corrected.
        return [event["bytes"] for event in self.events
                if event["kind"] == "frame" and event.get("bytes")
                and (dialect is None or classify(event["bytes"]) == dialect)]

    def report(self) -> str:
        """The end-of-session summary, also what --analyse prints."""
        lines: List[str] = []
        frame_events = [e for e in self.events if e["kind"] == "frame"]
        markers = [e for e in self.events if e["kind"] == "marker"]
        lines.append(f"{len(frame_events)} frame(s), {len(markers)} marker(s)")

        by_dialect: Dict[str, int] = {}
        for event in frame_events:
            dialect = classify(event.get("bytes", ()))  # derived, not stored
            by_dialect[dialect] = by_dialect.get(dialect, 0) + 1
        for dialect, count in sorted(by_dialect.items()):
            lines.append(f"  {dialect:<10} {count}")

        # Recomputed from the bytes rather than read back from the stored
        # "known" field. A log this tool wrote carries that field, but one
        # that was hand-trimmed, merged from two sessions, or produced by an
        # older version may not -- and the failure was silent in exactly the
        # wrong direction: a capture containing the handshake reported "no
        # known fragments seen", which reads as the finding that §3's
        # published bytes are wrong. Derive it, do not trust it.
        seen_known = {label for e in frame_events
                      if (label := describe_known(e.get("bytes", ())))}
        if seen_known:
            lines.append("known §3 fragments seen: " + ", ".join(sorted(seen_known)))
        else:
            lines.append("known §3 fragments seen: none "
                         "(if e-remote was connected, the handshake is not what §3 records)")

        panel = self.frames("panel")
        if not panel:
            lines.append("no panel frames -- see 'IF NOTHING ARRIVES' in this file's docstring")
            return "\n".join(lines)

        by_opcode: Dict[int, int] = {}
        for frame in panel:
            opcode = panel_opcode(frame)
            if opcode is not None:
                by_opcode[opcode] = by_opcode.get(opcode, 0) + 1
        if by_opcode:
            lines.append("")
            lines.append("panel opcodes (byte 5):")
            for opcode, count in sorted(by_opcode.items()):
                label = PANEL_OPCODES.get(opcode, "unknown -- new, worth chasing")
                lines.append(f"  {opcode:#04x}  n={count:<5} {label}")

        lines.append("")
        lines.append("panel frames by length (offset:times-changed):")
        for length, stats in summarise_diffs(panel).items():
            varying = stats["varying"]
            assert isinstance(varying, dict)
            moved = ", ".join(f"{offset}:{count}" for offset, count in varying.items()) or "none"
            lines.append(f"  len {length:<5} n={stats['count']:<5} varying -> {moved}")
        lines.append("")
        lines.append("A length that repeats often with a few varying offsets is the")
        lines.append("candidate display frame. Correlate those offsets with the markers")
        lines.append("around them before claiming what they mean.")
        return "\n".join(lines)


def load_capture(path: str) -> Capture:
    capture = Capture()
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                capture.events.append(json.loads(line))
    return capture


# --- live capture (MIDI) -----------------------------------------------------

def _open_inputs(port_filter: Optional[str], buffer_size: int):
    """Open every matching MIDI input with SysEx reception enabled.

    rtmidi ignores SysEx by default, which is the single most common reason a
    sniffer appears to show a silent bus.
    """
    import rtmidi  # imported here so --analyse works on a host with no MIDI

    probe = rtmidi.MidiIn()
    try:
        names = probe.get_ports()
    finally:
        try:
            probe.delete()
        except Exception:
            pass

    opened = []
    for index, name in enumerate(names):
        if port_filter and port_filter.lower() not in name.lower():
            continue
        port = rtmidi.MidiIn(queue_size_limit=buffer_size)
        port.open_port(index)
        port.ignore_types(sysex=False, timing=True, active_sense=True)
        opened.append((name, port))
    return opened


def run_live(args: argparse.Namespace) -> int:
    import select

    try:
        inputs = _open_inputs(args.port, args.buffer)
    except Exception as exc:
        print(f"error: could not open MIDI inputs ({exc})", file=sys.stderr)
        return 2
    if not inputs:
        print("error: no MIDI input ports matched", file=sys.stderr)
        return 2

    print("PASSIVE capture -- this sends nothing.")
    print("listening on: " + ", ".join(name for name, _ in inputs))
    print("type a label + Enter to mark the log; Ctrl-C to stop")
    if args.markers_only:
        print("--markers-only: nothing is recorded until the first marker")

    capture = Capture()
    handle = open(args.output, "a", encoding="utf-8") if args.output else None
    started = time.monotonic()
    recording = not args.markers_only

    def emit(event: dict) -> None:
        if handle:
            handle.write(json.dumps(event) + "\n")
            handle.flush()  # a hardware session must survive a Ctrl-C or a crash

    try:
        while True:
            for name, port in inputs:
                while True:
                    message = port.get_message()
                    if message is None:
                        break
                    frame, _delta = message
                    if not recording:
                        continue
                    event = capture.add_frame(frame, port=name,
                                              at=time.monotonic() - started)
                    label = f"  [{event['known']}]" if "known" in event else ""
                    print(f"{event['at']:9.3f} {name[:18]:<18} {event['dialect']:<8} "
                          f"len={event['length']:<4} {event['hex'][:96]}{label}")
                    emit(event)

            if select.select([sys.stdin], [], [], 0.002)[0]:
                label = sys.stdin.readline().strip()
                if label:
                    recording = True
                    event = capture.add_marker(label, at=time.monotonic() - started)
                    print(f"{event['at']:9.3f} --- MARKER: {label} ---")
                    emit(event)
    except KeyboardInterrupt:
        print("\n")
    finally:
        for _name, port in inputs:
            try:
                port.close_port()
                port.delete()
            except Exception:
                pass
        if handle:
            handle.close()

    print(capture.report())
    if args.output:
        print(f"\nlog: {args.output}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Passive capture harness for the EOS panel/remote protocol (§3). "
                    "Never transmits.")
    parser.add_argument("-o", "--output", help="append JSONL events to this file")
    parser.add_argument("-p", "--port", help="only listen to inputs whose name contains this")
    parser.add_argument("--buffer", type=int, default=8192,
                        help="rtmidi queue size; raise it if long frames are truncated")
    parser.add_argument("--markers-only", action="store_true",
                        help="record nothing until the first marker is typed")
    parser.add_argument("--analyse", metavar="FILE",
                        help="re-run the summary over a saved log and exit (no MIDI)")
    args = parser.parse_args(argv)

    if args.analyse:
        print(load_capture(args.analyse).report())
        return 0
    return run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
