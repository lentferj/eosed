<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
-->

# eosremote

A terminal tool for the E-mu **EOS** sampler family (E4, E4XT, E4XT Ultra,
E6400, …) driven over MIDI SysEx, from the same author as the sibling
**k2kremote** (Kurzweil K2000/K2000R) and **mpc2emu** projects.

> **Author:** Jan Lentfer &lt;jan.lentfer@web.de&gt;, with AI support
> (Anthropic Claude) — see [AI assistance](#ai-assistance--human-authorship).
> **Legal:** [DISCLAIMER.md](DISCLAIMER.md) · [LICENSE](LICENSE)

---

## ⚠️ Use at your own risk — back up first, hardware verification is minimal

eosremote is provided **as is, with absolutely no warranty and no liability**
for data loss or **hardware damage**. You assume all risk.

Unlike its siblings, **eosremote's protocol implementation is only lightly
verified against real E4/E4XT hardware**: `eoscli inquire` has been confirmed
live against a real E4XT Ultra (see `docs/RESOLUTION_NOTES.md` §7); every
other command is still verified only against the specification and synthetic
tests — see [TODO.md](TODO.md). It has been built from, and tested against
the worked examples in, the manufacturer's own
SysEx specification. Full terms: [DISCLAIMER.md](DISCLAIMER.md).

---

## Two protocols, one device — what this tool is (and isn't) yet

EOS exposes two separate SysEx dialects:

1. **The remote editor/librarian protocol** — fully documented by E-mu
   (`F0 18 21 <devID> 55 <cmd> … F7`). Parameter edit/request with live
   min/max/default query, preset dump/restore, preset & sample naming,
   memory/config queries, and voice/link/sample-zone utilities. **This is what
   eosremote currently implements** (`eos/` protocol package, `eoscli`).
2. **The undocumented panel/remote-control protocol** — what a browser tool
   like Ray Bellis's [e-remote](https://www.emu.tools/e-remote/) uses to mirror
   the device's own LCD and inject front-panel button presses (the same *kind*
   of thing k2kremote does for the K2000). E-mu never published this one;
   only fragments are known publicly. **eosremote does not implement this
   yet** — see `docs/RESOLUTION_NOTES.md` §3 for what's known and the plan to
   reverse-engineer the rest.

So today, eosremote is an **editor** (a command-line explorer plus a Textual
TUI), not a screen mirror.

## What it does today

`eoscli` (command-line explorer):
- `inquire` — standard MIDI device inquiry; identifies the model
  (E4/E4XT/E4XT Ultra/E6400/…) and EOS firmware revision.
- `config` / `memory` — installed options (voice count, FX/MIDI/Octopus/
  Digital-I-O cards), Preset and Sample RAM/ROM/Flash totals.
- `catalog` — preset and sample names.
- `get <param-id-or-name>` — read a single parameter's current value, with
  its device-reported min/max/default.
- `dump <preset> <file>` — full preset dump to a local file (OLD format:
  name, global parms, links, voices), using the spec's ACK/NAK/WAIT/EOF
  handshake.

`eosremote` (Textual TUI) — four panes, left to right:
- **Preset** — a paged, on-demand catalog scan (page size adapts to how tall
  the pane is).
- **Voice** — every voice of the selected preset, with a single/multisample
  hint.
- **Parameters** — the selected voice's parameters, or the preset's GLOBAL
  parameters if no voice is selected.
- **Samples** — a *derived* view, not a separate browsable bank: which raw
  sample(s) the selection actually plays (the whole preset's if no voice is
  selected, just that voice's otherwise), resolved from the voice's Sample
  Zone fields down to a sample number + name.
- Edits a parameter's value in place (device-fetched min/max/default shown),
  renames a preset, and a modal arm-then-fire Master screen for the
  destructive utilities (Delete Preset, Erase RAM Bank/Presets/Samples —
  never bound to a single keypress).
- **Writes (edit/rename/Master) are disabled by default against real
  hardware** — pass `--allow-write` to enable them; always on for `--demo`.
  No write path has been exercised against real hardware as thoroughly as
  the read paths yet — see [TODO.md](TODO.md).

`--demo` on both entry points: exercises the same code paths against a
canned in-memory device, no MIDI port opened, no hardware required.

Not yet implemented: NEW-format dump/restore, editing a raw sample's own
properties (loop points, root key, sample rate — this protocol has no
generic parameter access to those; see `docs/RESOLUTION_NOTES.md` §10), Link
browsing in this 4-pane layout, and anything touching the panel/mirror
protocol. See [TODO.md](TODO.md).

---

## AI assistance & human authorship

eosremote was built by its human author, **Jan Lentfer**, together with
Anthropic's **Claude**, following the pattern of the sibling k2kremote and
mpc2emu projects. The decision to build the documented editor protocol first
— rather than start from screen-mirroring, which would require reverse
engineering before a line of protocol code could be written — came from the
human author, as did the safety rules (destructive ops are never key-bound;
one MIDI session at a time). Claude assisted with transcribing the parameter
tables from the specification and writing the implementation, tests, and
docs. Full account in [DISCLAIMER.md](DISCLAIMER.md).

---

## Install & run

```sh
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/eoscli --demo inquire
.venv/bin/eosremote --demo
```

Real hardware use requires a MIDI interface connected to the E4/E4XT, and —
if you route through `mididings` or similar — a route that does **not** strip
SysEx (see `docs/RESOLUTION_NOTES.md` §5 for a gotcha the author hit on their
own setup).

Autodetect (the default when `--port` is omitted) tries every MIDI port,
which can take tens of seconds on a host with many ports. Once it succeeds,
the winning send/receive port pair is cached to `config.toml` (gitignored)
and tried first on the next connection, before falling back to a full sweep
if the cache is stale (ports renamed/gone) — pass `--config PATH` to use a
different cache file, or edit `eos/bridge.py`'s `DEFAULT_CONFIG_PATH`/pass
`config_path=None` to a script using `EosBridge.autodetect()` directly to
disable caching.

## Tests

```sh
.venv/bin/python -m pytest
```

All tests are synthetic (fake MIDI ports / fake device replies) — no hardware
is touched or required.

## License and Third-Party Sources

GPL-2.0-or-later. See [LICENSE](LICENSE) for the full text and the
third-party attribution table (the SysEx protocol facts transcribed from
E-mu's specification; the transport layer ported from k2kremote/mpc2emu).

## Trademarks

E-mu, Emulator, EOS are trademarks of Creative Technology Ltd. The author is
not affiliated with, endorsed by, or otherwise connected to Creative
Technology / E-mu Systems.
