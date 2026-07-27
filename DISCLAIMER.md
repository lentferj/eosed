<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
-->

# Disclaimer

## Use at your own risk — back up first

eosremote talks to vintage hardware over MIDI System Exclusive. It is provided
**as is, with absolutely no warranty and no liability** for data loss,
**hardware damage**, corrupted media, or any other harm arising from its use.
**You assume all risk.**

The E4/EOS remote editor protocol includes several **one-shot, unconfirmed**
destructive operations with no device-side "are you sure": Preset Delete
(`71h`), Erase Current RAM Bank (`74h`), Erase All RAM Presets (`75h`), and
Erase All RAM Samples (`76h`). None of these are ever key-bound in this tool;
they are only reachable through a modal arm-then-fire screen — but a scripting
mistake in `eoscli` or a bug in the editor could still fire one.

**Before you use this software with real hardware, make complete, current
backups of everything on your E4/E4XT** — RAM presets, samples, links/voices,
Master/MIDI settings, and any attached SCSI/media — so you can restore after
an unintended change.

Remote edits made through this tool's editor protocol are written to a
**separate buffer** from what the device's own front-panel display shows; the
spec states the device screen does not reflect a remote edit until the preset
is touched from the front panel. Do not assume the hardware's LCD agrees with
what this tool shows.

## AI Assistance & Human Authorship

In the interest of transparency: eosremote was created by its **human author,
Jan Lentfer (<jan.lentfer@web.de>)**, working together with Anthropic's
**Claude**, an AI coding assistant, and closely follows the pattern established
by the author's sibling **k2kremote** and **mpc2emu** projects.

**The ideas and the direction are human.** The decision to target the EOS
editor protocol first (rather than reverse-engineer the undocumented panel/
mirror protocol), the project structure, and the safety behaviours (modal-only
destructive ops, synthetic-first testing, one-session hardware rule) came from
the human author.

**Claude assisted with the execution:** transcribing the parameter/command
tables from the manufacturer's SysEx specification, writing the protocol
codec, transport, and CLI/TUI code, and drafting the documentation and tests.

**Hardware verification is minimal so far.** Unlike k2kremote (verified
extensively on a real K2000R) and mpc2emu (verified against a real E4XT),
eosremote has, as of this writing, only had its read-only Device Inquiry
(`eoscli inquire`) exercised against a real E4XT Ultra — see
`docs/RESOLUTION_NOTES.md` §7. Every other command (`config`, `memory`,
`catalog`, `get`, `dump`, and anything that writes) is still verified only
against the specification's worked examples and synthetic tests, not real
hardware. See `TODO.md` for status.

## No Warranty

This software is provided **as is**, without warranty of any kind, express or
implied, including but not limited to the warranties of merchantability,
fitness for a particular purpose, and non-infringement.

In no event shall the authors or copyright holders be liable for any claim,
damages, or other liability — including data loss or hardware damage —
whether in an action of contract, tort, or otherwise, arising from, out of, or
in connection with the software or the use or other dealings in the software.

See the [`LICENSE`](LICENSE) file (GPL-2.0-or-later) for the full legal terms.

## Hardware Risk

Driving vintage instruments over MIDI SysEx carries inherent risk. Before and
while using eosremote with real hardware:

1. **Keep good, current backups** of all RAM presets and attached media on the
   E4/E4XT, so you can recover from an unintended change.
2. **Only one session drives the hardware at a time.** Do not run eosremote
   probes or the app against an E4/E4XT that another session (or the front
   panel) may be actively using.
3. **A SysEx-stripping MIDI route may sit between you and the device** (see
   `~/mididings_e4xt.py` on the author's machine) — `eoscli`'s autodetect
   connects directly to the underlying hardware ports and does not need this
   bypassed (confirmed live, `docs/RESOLUTION_NOTES.md` §7), but a manually
   specified `--port` pointing at a filtering intermediary would still be
   silently dropped; verify SysEx actually reaches the device before assuming
   a probe failed for protocol reasons.
4. **Test against a non-critical instrument / backed-up state first.**

The author accepts **no responsibility** for data loss, hardware damage, or
any other adverse effects resulting from the use of this software.

## Tested Environment

As of this writing, eosremote's protocol layer has been developed against the
manufacturer's specification and synthetic (fake-bridge) tests, plus one live
read-only probe (`eoscli inquire`, via autodetect) against a real E4XT Ultra
running EOS 4.70 (`docs/RESOLUTION_NOTES.md` §7). Every other command remains
**unverified against real hardware**. See `TODO.md`.

## Trademarks

E-mu, Emulator, EOS are trademarks of Creative Technology Ltd. All other
product names, trademarks, and registered trademarks mentioned in this
project are the property of their respective owners. Their use here is for
identification purposes only and does not imply endorsement. The author is
not affiliated with, endorsed by, or otherwise connected to Creative
Technology / E-mu Systems.
