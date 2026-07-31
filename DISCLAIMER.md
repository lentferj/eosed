<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# Disclaimer

## AI Assistance & Human Authorship

In the interest of transparency: eosed was created by its **human
author, Jan Lentfer (<jan.lentfer@web.de>)**, working together with
Anthropic's **Claude**, an AI coding assistant, and closely follows the
pattern established by the author's sibling **k2kremote** and **mpc2emu**
projects.

**The ideas and the direction are human.** The decision to target the
documented editor/librarian protocol first — rather than start by
reverse-engineering the undocumented panel/mirror protocol, which would
need live hardware captures before a line of protocol code could be
written — the project structure, and every safety behaviour (destructive
Master operations are never key-bound, only reachable through a modal
arm-then-fire screen; synthetic-first testing via `--demo`; the
one-session-at-a-time hardware rule) came from the human author, arrived
at through real, iterative use against real hardware — not a spec
written up front.

**Claude assisted with the execution:**
- transcribing the parameter/command tables from the manufacturer's own
  SysEx specification into `eos/messages.py` / `eos/params.py`;
- writing and refactoring the protocol codec, transport, CLI, and
  Textual TUI code;
- drafting and maintaining the documentation and test suite.

**The live-hardware verification and every design correction rest on the
human author's own iterative use against a real E-mu E4XT Ultra** — the
part no AI can do on its own:
- running each `eoscli` command (`inquire`, `config`, `memory`, `catalog`,
  `dump`) against the real instrument and confirming the replies matched
  what the front panel itself reports;
- driving the full Textual TUI live — preset/voice/link/sample browsing,
  the bank switch, the reverse sample-usage lookup, and the "cache all"
  sweep — across sessions, catching real bugs the synthetic test suite
  could not have (see below);
- catching **at least three "Number Of X" fields that read as plain
  counts in the specification but are not reliable on real hardware**
  (`voice_num_szones`, then `preset_num_voices`, independently) purely by
  noticing the TUI's counts disagreed with what the front panel showed
  for known presets — see `docs/RESOLUTION_NOTES.md` §11/§12 for the
  full, occasionally embarrassing account of how many times "same
  command family, must behave the same way" turned out to be wrong;
- catching a live-only bug in the sample-name early-stop heuristic
  **twice** in a row — a first fix (checking for a blank name) still
  didn't stop early against the real device; every synthetic
  `FakeBridge` in the test suite happened to raise cleanly for a missing
  sample, which is exactly why neither the bug nor the first fix's
  shortcoming showed up until tested live;
- specifying every UX behavior after actually navigating the TUI on a
  real terminal against real hardware — the compact/extended view split,
  the "which pane shows what" decisions, the cache-all key and its
  three depth levels, all came from spotting something that looked or
  behaved wrong live, not from planning it upfront.

In short, the AI accelerated the coding and the protocol-table
transcription, but the ideas, the hardware verification, and the
correctness of the result are the product of the human author's own,
repeated, real-hardware use.

## Undocumented and Partially-Documented Protocol

EOS exposes **two separate SysEx dialects**, and eosed's relationship
to each is very different:

1. **The remote editor/librarian protocol** (`F0 18 21 <devID> 55 <cmd> …
   F7`) is fully documented by E-mu Systems in a public specification —
   see [LICENSE](LICENSE) for the exact document and how its facts are
   used. This is what eosed implements today.
2. **The undocumented panel/remote-control protocol** (`F0 18 7F 00 00 …
   F7`) — used by tools that mirror the device's own LCD and inject
   front-panel button presses — was never published by E-mu. Only
   fragments are known publicly. **eosed does not implement this
   protocol.** Where `docs/RESOLUTION_NOTES.md` records anything about
   it, that is preliminary reverse-engineering notes, not a verified
   implementation.

Even within the documented protocol, **several "Number Of X" query
commands do not behave as their names or the specification's wording
suggest** — confirmed only by cross-checking against real hardware and
saved dump files, not derivable from the specification text alone. See
`docs/RESOLUTION_NOTES.md` §11/§12 for the specifics; eosed's own
code no longer trusts these fields and instead walks live device state
directly, but any other implementation working from the same
specification should not assume those fields are plain counts either.

The author of eosed is not affiliated with, endorsed by, or otherwise
connected to **E-mu Systems / Creative Technology Ltd.**

## No Warranty

This software is provided **as is**, without warranty of any kind,
express or implied, including but not limited to the warranties of
merchantability, fitness for a particular purpose, and
non-infringement.

In no event shall the authors or copyright holders be liable for any
claim, damages, or other liability — including data loss or hardware
damage — whether in an action of contract, tort, or otherwise, arising
from, out of, or in connection with the software or the use or other
dealings in the software.

See the [`LICENSE`](LICENSE) file (GPL-2.0-or-later) for the full legal
terms.

## Hardware Risk

eosed talks to vintage hardware over MIDI System Exclusive. Driving
vintage instruments this way carries inherent risk, above and beyond the
No Warranty terms above.

The E4/EOS remote editor protocol includes several **one-shot,
unconfirmed** destructive operations with no device-side "are you
sure": Preset Delete (`71h`), Erase Current RAM Bank (`74h`), Erase All
RAM Presets (`75h`), and Erase All RAM Samples (`76h`). None of these are
ever key-bound in this tool; they are only reachable through a modal
arm-then-fire screen in the TUI — but a scripting mistake using `eoscli`
directly, or a bug in the editor, could still fire one. Write mode
(edit/rename/Master) is off by default; `--allow-write` starts a session
already armed, and `w` arms or disarms it at any point during the
session — the header bar turns the E4XT badge's own red while armed, as
a persistent reminder alongside the status line.

Remote edits made through this protocol are written to a **separate
buffer** from what the device's own front-panel display shows; the
specification states the device screen does not reflect a remote edit
until the preset is touched from the front panel. **Do not assume the
hardware's LCD agrees with what this tool shows.**

Before and while using eosed with real hardware:

1. **Keep good, current backups** of all RAM presets, samples, and
   attached media on the E4/E4XT, so you can recover from an unintended
   change.
2. **Only one session drives the hardware at a time.** Do not run
   eosed (or `eoscli`) against an E4/E4XT that another session, a
   probe script, or the front panel may be actively using — ALSA MIDI on
   Linux does **not** enforce exclusive port access, so nothing at the
   OS level will stop or warn about a real conflict; this is a discipline
   the user must maintain themselves.
3. **A SysEx-stripping MIDI route may sit between you and the device**
   — confirm SysEx actually reaches the device before assuming a probe
   failed for protocol reasons, especially if you route MIDI through
   software like `mididings`.
4. **Test against a non-critical instrument / backed-up state first**,
   especially before ever passing `--allow-write`.

The author accepts **no responsibility** for data loss, hardware damage,
or any other adverse effects resulting from the use of this software.

## Tested Environment

As of this writing, eosed's protocol and TUI have been developed
against the manufacturer's specification, an extensive synthetic
(`--demo`/fake-bridge) test suite, **and repeated live sessions against a
real E-mu E4XT Ultra** running EOS firmware. Live-confirmed so far:
`eoscli inquire`, `config`, `memory`, `catalog`, and `dump` (OLD format);
the full Textual TUI's **read paths** — preset/voice/link browsing, the
Preset/Sample bank switch, the reverse sample-usage lookup, and the
cache-all sweep, including the count-field corrections in
`docs/RESOLUTION_NOTES.md` §11/§12 that live use itself surfaced.

**Write paths are partly verified.** Parameter edits and renames have
been exercised against a real E4XT Ultra — every preset-scoped parameter
written across ten scratch presets, read back, and re-read after
selecting away and returning (3340 comparisons and 20 renames, all
exact; `docs/RESOLUTION_NOTES.md` §18). **Every Master action remains
unverified against real hardware**, as does writing `E4_GEN_SAMPLE`. See
[TODO.md](TODO.md) for exact status and what's still open, including the
NEW-format dump path and the undocumented panel protocol above.

## Trademarks

E-mu, Emulator, EOS are trademarks of Creative Technology Ltd. All other
product names, trademarks, and registered trademarks mentioned in this
project are the property of their respective owners. Their use here is
for identification purposes only and does not imply endorsement. The
author is not affiliated with, endorsed by, or otherwise connected to
Creative Technology / E-mu Systems.
