<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
-->

# Resolution Notes

*How* things got resolved: RE procedures, hardware probes, ready-to-apply
code. `TODO.md` tracks *what* is open; this file tracks *how* to close it.

## §1 — Editor protocol source document (resolved)

The full "Remote Preset Editing via MIDI SysEx" spec (Draft #30, EOS 4.00,
Brian Clark, E-mu Systems, 17 Feb 1999, 61 pages) is on the author's machine
at:

```
e-mu_eos_remote_sysex.pdf (not redistributed)
```

It is an E-mu internal document, text-extractable (not a scan). It documents
**only** the `55h`-designated editor/librarian protocol — see §3 below for why
that is a different thing from a front-panel mirror.

Frame: `F0 18 21 <devID> 55 <cmd> … F7`. `18h` = E-mu manufacturer id, `21h` =
E4 product id, `devID` 0–126 unique / 127 = broadcast, `55h` = "special editor
designator" byte, then `<cmd>` (see the command table transcribed into
`eos/messages.py`'s `Command` enum). Checksum = 1's-complement of the sum of
the data bytes; `7Fh` in the checksum position means "ignore checksum".

Device inquiry uses the **standard** MIDI Non-Realtime Universal SysEx, not
the `18h`/`21h`/`55h` frame: `F0 7E <devID> 06 01 F7`, response
`F0 7E <devID> 06 02 18h 01h 04h <dd dd> <ssss> F7` where `<dd dd>` is the
14-bit (LSB-first) family-member code:

| code | model |
|---|---|
| `00h,05h` | E4 |
| `01h,05h` | E64 |
| `02h,05h` | E4k |
| `03h,05h` | E64FX |
| `04h,05h` | E4XT |
| `05h,05h` | E4X |
| `06h,05h` | E6400 |
| `07h,05h` | E4XT Ultra |
| `08h,05h` | E6400 Ultra |

`<ssss>` is 4 ASCII chars, e.g. `"4.00"`.

## §2 — Parameter table (resolved, transcription only)

~270 parameter ids (14-bit, LSB-first; parameter *data* is also 14-bit,
signed or unsigned depending on the parameter, LSB-first) grouped GLOBAL (id
0–21), LINKS (23–35), VOICES general/tuning/amp-filter/lfo-aux/cords (37–182),
MASTER (183–250+), plus per-link filter flags (251+). Several parameters
(filter type/morph, glide rate, LFO rate) have non-linear displayed-value
conversions given as literal C functions/lookup tables in the spec — these are
transcribed verbatim into `eos/params.py` rather than re-derived, to avoid
introducing rounding bugs relative to what the real device's own front panel
shows.

`03h`/`04h` (Parameter Min/Max/Default Request/Response) let the *device*
report a parameter's live range — always prefer this at runtime over the
table's static min/max where the two might drift across EOS versions.

## §3 — Editor protocol ≠ panel/mirror protocol (key distinction, unresolved on our side)

The PDF above documents **only** parameter/preset editing. It contains no
front-panel button injection, no cursor/data-wheel control, and no LCD/screen
readback — the intro explicitly frames the goal as a *replacement* GUI ("a
large, colorful, graphical interface, superior to the standard E4 front panel
display"), not a mirror of the existing one.

A **second, undocumented** SysEx dialect exists for that: `F0 18 7F 00 00
<cmd> … F7` (note: device id fixed at `00`/`7F`, not the `21h`-family frame).
Fragments published by third parties who reverse-engineered it from MIDI
traffic between Ray Bellis's browser tool (<https://www.emu.tools/e-remote/>)
and real hardware
(<https://midimachines.wordpress.com/2016/04/30/arduino-midi-and-sampler-ultra-series/>):

```
F0 18 7F 00 00 7F 11 00 08 F7   init handshake
F0 18 7F 00 00 10 F7            enable remote communication ("open" the sampler)
F0 18 7F 00 00 7F 11 06 04 F7   emitted on a front-panel button press
F0 18 7F 00 00 11 F7            close communication
```

Each physical panel press emits **two** messages (down + up) — the device
echoes panel activity, unlike the K2000 (see k2kremote `TODO.md`: "physical-
panel PANEL echo needs a human press"). The display-frame encoding (size,
packing, full-frame vs. delta) is **not known** and is not in the above
fragments. Do not write code against a byte sequence for this protocol that
is not backed by a capture recorded in this file.

**RE method, once hardware access is available (see TODO.md item "panel
protocol RE"):** run Ray Bellis's e-remote in a browser against the E4XT with
an ALSA MIDI thru/sniffer in the path (`aseqdump`, or a small rtmidi logger in
`probes/`), exercise one control at a time — a single soft button, then the
data wheel one click, then something that changes the LCD — and diff
consecutive captures. This is the same method that produced
`../mpc2emu/docs/k2000r_midi_comms.md` for the K2000R. **Do not** decompile or
copy Ray Bellis's client-side code; observe the wire traffic only.

## §4 — Related but distinct E-mu protocols (do not conflate)

Checked against local `edisyn` (Java patch editors, GPL-licensed, used here
only as a reference for wire-protocol facts, no code copied):

- **Proteus 2000 family** (`edisyn/synth/emuproteus2000/EmuProteus2000.java`):
  frame `F0 18 0F <devID> 55 <cmd> … F7` — same manufacturer id and same `55h`
  "special editor designator" convention as EOS, but **product id `0Fh`** (not
  `21h`) and a completely different, separately-versioned command set,
  addressed by `<SIMM-or-user-memory, number>` tuples rather than EOS's
  preset/voice/zone selectors. edisyn's own source comments describe this
  spec as significantly incomplete relative to what the hardware needs.
- **Morpheus** (`edisyn/synth/emumorpheus/EmuMorpheus.java`): frame
  `F0 18 0C <devID> <cmd> … F7` — product id `0Ch`, and no `55h` designator
  byte at all; command follows the device id directly.

None of `eos/messages.py`'s `Command`/`ParamId` tables apply to either device.
A Proteus/Morpheus tool would need its own protocol package under this
project's transport/Textual scaffolding, built the same way this project was
built relative to k2kremote — reusing the *idiom*, not the bytes.

## §5 — mididings SysEx strip on the E4XT route (open, blocks live work)

`~/mididings_e4xt.py` (outside this repo) currently creates an ALSA client
that filters MIDI channels 5–8 and **strips all SYSTEM messages, including
SysEx**, on the current E4XT route. Any live probe or session must either
route around this script or have it changed first — otherwise a "no reply"
result is a false negative about the protocol, not a real one.

## §6a — LFO rate display table: transcription gap (open, cosmetic only)

`eos/params.py`'s glide-rate, master-tuning-offset, and chorus-ITD display
tables were transcribed from the spec PDF and cross-validated: they reproduce
the spec's own worked boundary values exactly (`cnv_morph_freq(0)` → 83Hz,
matching the stated "83Hz to 9824Hz" EQ range; `cnv_glide_rate(127)` →
32.738sec/oct, matching the spec's own reference table tail). Each source
table has an unambiguous, page-clean layout (16 rows of 8, or one value per
line), so these are trusted.

The **LFO rate** (`E4_VOICE_LFO_RATE`/`LFO2_RATE`, ids 105/110) display
table's source (`lfounits1[]`/`lfounits2[]`) wraps across a page boundary in
the PDF in a way that produced 129 transcribed entries against an expected
128 — i.e. one value is duplicated or misplaced by the page-break reflow, and
which one is not determinable from the extracted text alone. Rather than
silently guess-correct it, `eos/params.py::cnv_lfo_rate()` raises
`NotImplementedError` with a pointer back here. **To resolve:** re-open the
source PDF directly (not through a text-extraction pass) at the LFO rate
section and re-transcribe `lfounits1[]`/`lfounits2[]` by hand, or capture the
128 raw parameter values against real hardware and reverse the display
strings shown on its front panel. This does not block anything else — the
raw 0-127 parameter value is unaffected and fully controllable.

## §6 — Preset dump field order cross-check (open)

`../mpc2emu/docs/E4B_FORMAT.md` documents the on-disk E4B bank/preset/voice/
zone/sample byte layout, reverse-engineered independently against the E4XT's
file format. The remote editor protocol's preset-dump field order (Global
Parms → Links → Voices → per-voice Sample Zones, per §"Dump Data Formats" of
the spec) is structurally similar but not proven identical — once a live dump
is captured, diff its field order against E4B_FORMAT.md's preset structure and
record any mismatch here.

## §7 — First live contact: Device Inquiry against the real E4XT Ultra (resolved)

Ran `eoscli inquire` (real, `EosBridge.autodetect()`, no `--port`) against
Jan's E4XT Ultra with it powered on, single session. Result:

```
device id      : 5
family code    : (1, 4)
member code    : (7, 5)
model          : E4XT Ultra
firmware       : 4.70
```

This is the **first verified live exchange** with real EOS hardware over the
protocol this repo implements — everything before this note was spec-derived
and synthetic-tested only.

**Findings:**

- **The device answers the standard MIDI Device Inquiry correctly and per
  spec.** Family code `(1,4)` and member code `(7,5)` = "E4XT Ultra" decode
  exactly per the table in §1. `eos/messages.py::parse_device_inquiry_reply`
  needed no changes.
- **SysEx device id is 5 on this unit, not the library default of 0.**
  `EosBridge.autodetect()` already captures `reply.device_id` into the
  returned bridge (see `EosBridge._connect`), so this is handled automatically
  for anyone using autodetect; a manual `EosBridge.standard(...)` call would
  need `device_id=5` explicitly for this specific unit.
- **`~/mididings_e4xt.py`'s SysEx-stripping did not need to be touched.**
  ALSA topology (`aconnect -l`) showed mididings_e4xt sits between two
  specific hardware ports — `U6MIDI Pro:U6MIDI Pro MIDI 1` (36:0, the E4XT's
  MIDI OUT arriving into the host, shared/merged with the K2000R's and
  TG77's return traffic on the same physical input) and `ESI M4U eX:ESI M4U
  eX MIDI 4` (56:3, dedicated to the E4XT's MIDI IN) — and `autodetect()`
  connects directly to those same two hardware ports in parallel with
  mididings, never through `mididings_e4xt`'s own ALSA ports. The success was
  found trying output port `ESI M4U eX:ESI M4U eX MIDI 4 56:3` (the 19th port
  tried). Because the shared input carries other synths' replies too,
  `autodetect()`'s reliance on payload content (manufacturer id byte) rather
  than port identity to recognise a reply is what made this safe — worth
  keeping in mind before ever "simplifying" that check.
- **Not yet touched live:** `catalog`, `get`, `dump`, and anything that
  writes. See TODO.md for the remaining verification order.

**Follow-up (same session): `config` and `memory` verified live.**

```
$ eoscli config                          $ eoscli memory
RAM            : 128 MB                  Preset memory  : 4485 / 4485 kB free
128 voices     : True                    Sample memory  : 128 MB total, ~128000 kB free
FX card        : True
MIDI card      : True
Octopus card   : False
Digital I/O    : True
ROM            : 0 MB
Flash          : 0 MB
Preset Flash   : True
ADAT I/O       : True
```

Both `ConfigurationResponse` and `ExtendedConfigurationResponse` decoded
without errors on the first live attempt — no byte-offset fixes needed.
Internally consistent: RAM (128MB) matches Sample memory's reported 128MB
total; `Preset Flash: True` (an options1 bit — a flash-upgrade *card* being
installed) alongside `ROM: 0 MB` / `Flash: 0 MB` (the separate Sample
ROM/Sample Flash *capacity* fields) is not a contradiction — this unit has
the preset-flash upgrade board but no additional sample ROM/flash SIMMs
beyond its 128MB of sample RAM. Preset memory shows 0 bytes in use (4485/4485
free) while ~3MB of sample RAM is in use, which is normal — EOS can hold
loaded samples with no preset yet referencing them.

Not independently cross-checked against the front panel's own System/Info
page in this session — worth doing once convenient, but the self-consistency
above is a good sign.

**Follow-up (same session): `catalog` verified live, full 0-127 sweep.**

All 128 slots answered — no timeouts, no CANCELs, across the whole sweep
(useful in itself: the connection holds up over a multi-minute operation,
which matters for the upcoming `dump` test). Slot 0 = "Untitled Preset",
slots 1-127 = "Empty Preset" — this bank is currently unprogrammed, matching
`memory`'s report of 0 preset bytes in use.

**Correction to §1's assumption about nonexistent presets:** the spec states
*"If a non-existant Preset is requested, the response is a CANCEL message"*
under the **Preset Dump Request** (`0Eh`) section specifically. In practice,
**Preset Name Request (`06h`) does not behave this way** — every slot from
0-127 answered with a real `PresetName` reply (a placeholder name like "Empty
Preset"), never a `CANCEL`. So on this unit, all 1000 preset slots appear to
always have *some* name, and "free preset memory" tracks unallocated byte
capacity, not slot existence. `EosBridge.catalog_presets()`'s
`TimeoutError`/`ValueError`-swallowing fallback is still worth keeping (for
other EOS models/firmware, or ids beyond however many slots a given unit
actually exposes), but do not expect a `CANCEL` from a name request on
hardware like this.

**Follow-up (same session, after a real bank was loaded): `dump` (OLD
format) verified live — bug found and fixed.**

First attempt (`eoscli dump 0 ...`) timed out waiting for the first data
packet after receiving the header. **Root cause:** the spec calls the OLD
dump header "the first packet" (`00h = Packet Number (first packet)`), and it
turns out the device treats it exactly like any other packet in the
ACK/NAK/WAIT handshake — it will not send any data packets until that packet
number is ACKed. `eos.bridge.EosBridge.dump_preset_old`/`dump_preset_new`
didn't ACK the header at all; fixed by sending `Ack(packet_number=header.
packet_number)` (OLD) / `NewAck(packet_number=0)` (NEW, extrapolated —
**not yet independently confirmed live for the NEW format**, since
`NewDumpHeader` carries no packet-number field of its own to begin with)
immediately after decoding the header, before entering the data-receiving
loop. All dump-engine tests in `tests/test_bridge.py` updated to expect this
extra ACK.

After the fix, `eoscli dump 0 <file>` against preset 0 ("Test Preset", a real
preset from the bank loaded this session) succeeded: 1096 bytes, matching
the previously-peeked header `byte_count` exactly. A copy is kept at
`docs/samples/e4xt_ultra_preset0_old_format.bin` for future
parsing work. Byte-level inspection:

- **Bytes 0-1:** preset number (u14) = `0`. This means the OLD long-form
  dump payload actually starts with `<NUMBER><NAME>...`, not just `<NAME>...`
  as this file's docstrings previously assumed (fixed) — the `<NAME>`-only
  grammar block quoted in §2 evidently describes the **NEW** format's
  payload, not OLD's.
- **Bytes 2-17:** name = `"Test Preset"` (space-padded to 16) — matches the
  catalog exactly.
- **Bytes 18-61:** 22 signed 14-bit words, decoding to fully in-range,
  plausible values in exactly `eos.params`'s GLOBAL id order (0-21):
  `FX_A_ALGORITHM=18` (range 0-44 ✓), `FX_A_PARM_0=40` (0-90 ✓),
  `FX_A_PARM_1=64`, `FX_A_AMT_0=7`, `FX_B_ALGORITHM=24` (0-27 ✓),
  `FX_B_PARM_1=3`, `FX_B_PARM_2=50`, `FX_B_AMT_0=28`, rest 0. **This
  confirms the GLOBAL parameter table's id-to-field mapping is correct**,
  independent of the spec text alone.
- **Bytes 62-63:** link count = `1`.
- **Bytes 64+:** the single link's first word (`E4_LINK_PRESET`) decodes to
  `104` — a plausible cross-reference to another preset, consistent with
  what a "Link" is for.
- **Beyond that:** attempting to walk the rest assuming "29 words/58 bytes
  per link" (§2's figure, which — per the finding above — may itself belong
  to the NEW format's grammar, not OLD's) lands on an implausible
  `num_voices` reading with 972 bytes unaccounted for. **The link/voice byte
  layout for the OLD format is not yet correctly parsed** — this is
  genuinely open, not guessed at further here. Next step: use the saved
  sample above, plus `eoscli dump --new-format` on the same preset once that
  path is live-verified (its header explicitly states per-section parameter
  counts, which would settle this without guessing), or cross-check against
  `../mpc2emu/docs/E4B_FORMAT.md`'s independently RE'd voice/link structure.

**Follow-up (same session): autodetect port cache, addressing the ~19-36s
scan time noted above.** `eos.bridge.load_last_ports`/`save_last_ports` cache
the successful (send_port, recv_port) pair to `config.toml` (CWD-relative,
gitignored — same convention as k2kremote's `BridgeConfig`); `autodetect()`
tries that pair first via a single-port probe (`_try_port_pair`) before
falling back to the full sweep if it's absent, stale, or doesn't answer.
Both `eoscli` and `eosremote` expose `--config PATH`. Note for anyone editing
tests: this writes to the **real filesystem** by default — every synthetic
test that calls `EosBridge.autodetect()` with a fake `rtmidi` must pass
`config_path=None` (or an isolated `tmp_path`-based path for tests that
specifically exercise the cache), or it will read/clobber whatever is
actually sitting in the repo's own `config.toml`. This was caught the hard
way: an early version of the cache tests overwrote this repo's real
`config.toml` with fake test port names — no real data was lost (the cache
feature didn't exist before that same session), but it was a genuine bug in
test isolation, not just a hypothetical risk.

## §8 — FX algorithm/parameter name tables (from the EOS 4.0 manual; unconfirmed on hardware)

`eos/params.py` now has `FX_A_ALGORITHM_NAMES` (44 entries), `FX_B_ALGORITHM_NAMES`
(32 entries), `FX_A_PARM_NAMES`, `FX_B_PARM_NAMES`, and `FX_AMT_BUS_NAMES`, plus
a general `describe_value(param, value)` helper (used by both `eoscli get`
and the TUI) that shows `"value (Name)"` when a mapping is known. Source:
the **EOS 4.0 Software Manual** (`(a local copy, path removed)`),
chapter 2 "Master Effects A/B" (pp. 97-98) and chapter 8 "Preset Effects A/B"
(pp. 283-287) — the two independently cross-checked and match exactly.

**Important limitation, not papered over:** neither manual page prints a
numeric id column — only effect *names*, in a 3-column table. The id-to-name
mapping assumes id == row-major reading order (standard convention for this
kind of selector list), which is **not independently confirmed** against
real hardware or any explicitly numbered source. Expanding the printed
ranges ("Room 1-3", "Hall 1 & 2", etc.) in that order happens to yield
exactly 44 names for FX A (ids 0-43) and 32 for FX B (ids 0-31).

Two discrepancies surfaced and are deliberately left visible rather than
"corrected" by guessing:
- FX A: the SysEx spec's own `max=44` implies id 44 is valid, but only 44
  names exist (0-43) — id 44's name is unknown.
- FX B: the SysEx spec's `max=27` (28 valid ids) is smaller than this newer
  manual's 32 named B effects — ids 28-31 are manual-only and may not exist
  on hardware running the spec's original firmware revision.

The `FX_A_PARM_0/1` ("Decay Time"/"HF Damping") and `FX_B_PARM_0/1/2`
("Feedback"/"LFO Rate"/"Delay Time") labels come from the manual's
processor-level description ("Reverb effects have two adjustable
parameters..."), not a per-algorithm breakdown — cross-checking the "Delay"
A-effect's own dedicated description shows it uses "Delay Time" and
"Feedback" for the same two slots instead, so these labels are the
**typical case per processor, not a guarantee for every one of the 44/32
algorithms** (the same caveat as the filter-type overlay in §2). `FX_A_PARM_2`
is not named anywhere in the manual and is left unmapped. `FX_*_AMT_0-3`,
by contrast, are confidently mapped (Main/Sub 1/Sub 2/Sub 3) — those are
fixed submix-bus sends, not algorithm-dependent.

**To verify:** set `FX_A_ALGORITHM`/`FX_B_ALGORITHM` to a handful of these
ids live (e.g. via `eoscli` — writes are gated behind `--allow-write`/
`allow_write`, so this is a deliberate, opt-in step, not automatic) and
compare against what the front panel actually displays for that preset.
Not yet done this session.

## §9 — Filter type names + envelope segment labels (from the manual)

`eos/params.py::FILTER_TYPE_NAMES` (21 entries, `E4_VOICE_FTYPE`). Source:
EOS 4.0 Software Manual, chapter 8 "Filter Parameters" (pp. 342-345): "21
filter types are currently implemented", followed by a **single-column**
list (one full paragraph per type — not a multi-column table like the FX
effects in §8), in this exact order: 2-Pole/4-Pole/6-Pole Lowpass, 2nd/4th
Order Highpass, 2nd/4th Order Bandpass, Contrary Bandpass, Swept EQ
1/2→1/3→1-octave, Phaser 1/2, Bat Phaser, Flanger Lite, Vocal Ah-Ay-Ee,
Vocal Oo-Ah, Dual EQ Morph, 2EQ + Lowpass Morph, 2EQ Morph + Expression,
Peak/Shelf Morph.

Same "id == list position" assumption as the FX tables, but meaningfully
**higher confidence** here: (a) no multi-column reading-order ambiguity,
(b) the count matches the manual's own stated total exactly (21), and (c)
the last three names independently corroborate the filter-type-dependent
parameter-overlay section headers already transcribed from the SysEx spec
itself in §2 ("2EQ+Lowpass Morph", "2EQMorph+Exprssn", "Peak/Shelf Morph")
— two independent sources agreeing, not one source read twice. Still not
independently hardware-confirmed; same verification suggestion as §8
applies (set `E4_VOICE_FTYPE` live, compare to the front panel).

Envelope segment ids (`E4_VOICE_VENV/FENV/AENV_SEG{0-5}_{RATE,TGTLVL}`, 36
parameters total) already carried a clean role label ("Atk1 Rate", "Dcy2
Level", etc.) in their `notes` field since these were first transcribed —
`describe_value()` now shows it in brackets, restricted to exactly the three
envelope groups (`voice.amp.env`/`voice.filter.env`/`voice.aux.env`) so that
other parameters' longer caveat-sentence `notes` (e.g.
`E4_VOICE_FILT_GEN_PARM3`'s "filter-type dependent; see notes above") don't
get displayed as if they were a value name.

## §10 — Editor TUI: presets/params panes not resizing together (resolved, verified live)

Reported live (real E4XT Ultra session, `--demo` off): the presets pane
looked frozen at a fixed size across terminal resizes while the params pane
looked like it scaled. Root causes, both in `eosremote/app.py`:

- **`DataTable`'s own built-in default CSS is `height: auto; max-height:
  100%`** — Textual sizes each table to its *content* (row count), not to
  the pane. The presets pane always shows exactly one fixed page
  (`PRESET_WINDOW`, was a constant 16), so on any reasonably tall terminal
  it sits well under 100% and never grows. The params pane can have anywhere
  from ~22 rows (GLOBAL group) to 146 (a VOICE group's parameters) and often
  exceeds 100%, hitting the `max-height` ceiling — which *looks* like
  correct scaling but is really the same "size to content" behavior landing
  on a different, larger content size. Fixed with explicit
  `#presets { height: 1fr; } #params { height: 1fr; }` in `EosRemoteApp.CSS`,
  overriding the widget default so both panes always fill the space the
  `Horizontal` container gives them.
- **`DataTable` columns are `auto_width` by default** — sized to cell
  content, not to the table's own box width, so short content (the presets
  table's "#"/"Name" columns) left the row cursor highlight pinned to a
  fixed width with dead space to its right, while the params table's longer
  parameter names happened to already reach the pane's edge at typical
  sizes. Fixed with `_FillWidthDataTable(DataTable)`, a small subclass whose
  `_stretch_last_column()` (called after every column/row mutation and on
  every `on_resize`) sets the last column's width explicitly to whatever
  space remains in the box, instead of leaving it on `auto_width`.

A third, separate issue surfaced once the above two were fixed: the presets
pane's *page size* itself was a fixed constant (`PRESET_WINDOW = 16`,
independent of terminal height), while the params pane just lists however
many parameters the current group has — so a tall terminal revealed more of
whatever content params happened to have, but never more *presets* per page,
which read as "still not really adapting". This is also the fetch batch
size for `EosBridge.catalog_presets()` — a live MIDI round-trip **per
preset**, sequential, no batching in the protocol — so naively re-sizing the
page to exactly fill the pane on every resize event would spam the device
with a fresh multi-preset scan on every frame of a window drag.

Resolved by making the page size dynamic but deliberately damped:
`EosRemoteApp._desired_preset_window()` computes `ceil(1.5 × pane row
capacity)`, floored at `PRESET_MIN_WINDOW = 16` (`app.py`'s replacement for
the old constant). Resize events feed a debounce timer
(`PRESET_RESIZE_SETTLE = 0.4s`) via `_on_presets_resized`/
`_settle_preset_resize`, so only the size after a resize *settles* triggers
a re-fetch, not every intermediate event. Shrinking is cheaper still: the
last fetch's `{preset: name}` result and the `range` it covered are cached
(`self._preset_cache`/`_preset_cache_range`); shrinking within that already-
fetched range just redisplays fewer of the cached rows with no new hardware
call, since a smaller page is always a strict subset of a larger one already
in hand. Growing beyond the cached range still fetches, same as before.

**Verified live** against the real E4XT Ultra (autodetected ports, same
session pattern as §7): resizing the terminal now visibly changes how many
presets are fetched/shown, debounced growth triggered exactly one
`catalog_presets()` call, and shrinking back down triggered zero.

## §11 — "Number Of X" commands (0x16-0x1D) are not plain counts (resolved, verified live)

First live use of `preset_num_voices`/`preset_num_links`/`preset_num_szones`/
`voice_num_szones` (the `extended_view` branch's Voice/Samples panes),
against preset 0 ("Test Preset", the same preset captured in §7's saved dump
at `docs/samples/e4xt_ultra_preset0_old_format.bin`). Reported
live: a preset the front panel shows as 2 voices (V1 single-sample, V2
multisample with 2 zones/samples) rendered in the TUI as **3 voices**, with
the 2nd and 3rd showing empty/garbage sample data.

**Root cause, confirmed two independent ways:**

1. **Cross-checked against the saved dump file**, bypassing the live command
   entirely: the OLD-format dump's own `<Voices>` section starts with a
   plain, direct voice-count word (`{<NUMBER>,<NAME>,<Global Parms>,<Links>,
   <Voices>}`, dump grammar, no off-by-one language anywhere in that part of
   the spec). Manually decoding that file (name+globals = 62 bytes, link
   count = 1 at offset 62-63, one 26-byte OLD-format link, so the voice
   count word sits at offset 90-91) gives **2** — not 3.
2. **A live, read-only probe** (`preset_num_voices` called 3x in a row: always
   3, ruling out a one-off glitch) walked all three voice indices `0..2`
   the live command claimed existed:
   - voice 0: `voice_num_szones` → 0, voice-level `E4_GEN_SAMPLE` = 1 (a real
     sample id) — a genuine single-sample voice.
   - voice 1: `voice_num_szones` → 1, voice-level `E4_GEN_SAMPLE` = 16383
     (the spec's multisample sentinel — **contradicts** "1 zone = not
     multisample" if 1 were the literal zone count) — with a settled
     300ms-per-step per-zone read, zones 0 and 1 both resolved to *different,
     real, non-garbage* sample data.
   - voice 2: `voice_num_szones` → 16, but every one of those 16 "zones"
     read back an identical, unchanging `E4_GEN_SAMPLE=0`/`KEY_LOW=16`/etc.
     regardless of which zone was selected — the signature of a voice index
     that doesn't actually exist on the device.

Both independent findings agree the device's real voice count is 2 while
`preset_num_voices`'s raw wire value is 3; separately, `voice_num_szones`'s
raw wire value for the confirmed 2-zone multisample voice was 1, not 2.

**These two commands disagree in *direction*, and a first attempt at the fix
got it backwards** — worth recording so the mistake isn't repeated. Reading
"raw values are off by one either way" and pattern-matching too quickly, the
first fix applied `+1` to *all four* siblings. That's right for
`voice_num_szones` (0→1 real for a single-zone voice, 1→2 real for the
confirmed multisample one) but wrong for the "Preset Num Of X" trio: applying
`+1` to `preset_num_voices`'s raw `3` produced `4`, moving *away* from the
dump file's ground truth of `2`, which is what the live re-test after the
first fix actually showed (preset 0 rendered as 4 voices, not 2). The
arithmetic, done properly against the same two data points: raw `3`, real
`2` ⇒ real = raw **− 1**, not raw + 1. `eos.bridge.EosBridge.preset_num_voices`
subtracts 1 from the raw wire value. Confirmed live specifically, on two
different presets (0 and 1), both cross-checked against their own dump
files.

**A third round of the same mistake, worth recording just as plainly:**
the fix above still extrapolated the `-1` correction to `preset_num_links`
and `preset_num_szones` too, reasoning "same command family, same wire
shape, same naming pattern" — exactly the reasoning already shown wrong
once for `voice_num_szones` above. Live-testing the TUI's restored Link
browsing (`l`) against preset 0 — independently known, from its own saved
dump file, to have exactly 1 real link — silently reported "no links".
Probing `preset_num_links(0)` directly found the raw wire value is `1`:
already the plain, direct count, needing **no correction at all** — not
`+1` like its `preset_num_voices` sibling, not any other offset. **Lesson,
now demonstrated three separate times in this one section** (`voice_num_
szones` being fundamentally unreliable rather than off by a constant;
`preset_num_voices` needing `-1` where a first guess said `+1`; now
`preset_num_links` needing nothing where a first guess said `-1`): sharing
a command family, byte range, or name is *no evidence at all* about how a
"Number Of X" command actually behaves — each one needs its own
independent live check, every time, no matter how similar it looks to a
sibling already confirmed. `preset_num_szones` (the one remaining sibling)
is not called anywhere in this codebase and remains completely unverified
— `eos.bridge.EosBridge.preset_num_szones` now applies no correction
either, deliberately, rather than guessing a third formula with zero
evidence behind it.

At the same time, the first fix also applied `+1` to `voice_num_szones` (a
different family, "Voice Num Of X"), based on it matching exactly one
data point (preset 0's multisample voice: raw `1` → real `2`). **That did
not hold up on a second preset.** Re-testing against preset 1 ("Brazz
Intense", front panel: 2 voices, both multisample, sharing samples S005/
S006/S007) surfaced a direct, unambiguous contradiction: voice 0's
`voice_num_szones` raw value was `0` (⇒ "single" under the `+1` fix), yet
that same voice's own voice-level `E4_GEN_SAMPLE` read the spec's `16383`
multisample sentinel — a single-zone voice cannot legitimately show that
value. Walking zones 0-7 anyway (ignoring the count field) found 3 real,
distinct samples (`5`, `7`, `6` — exactly S005/S007/S006) before zone 3
cleanly read `0`. So this voice's real zone count is 3, needing "+3" over
its raw `0` — while preset 0's voice 1 needed only "+1" over its raw `1`.
**No single additive constant reconciles both** — `voice_num_szones` isn't
off by a fixed offset at all, it's simply not a trustworthy count, in a
preset/voice-dependent way with no formula. (The sibling mpc2emu project
independently reached the identical conclusion about this device family's
analogous on-disk `n_zones` field: "Redundant/display-only... can only be
trusted from [a structural derivation], not the count field" — see
`../mpc2emu/docs/E4B_FORMAT.md` §4.1/4.5. Different format, same lesson.)

**Final fix:** stopped calling `voice_num_szones` for this purpose
entirely. `eos.bridge.EosBridge.voice_num_szones` now returns the plain raw
wire value with a docstring warning not to trust it as a count, kept only
for API completeness. `eosremote.app._voice_sample_info` instead uses the
spec-documented, reliable signal: read the voice-level `E4_GEN_SAMPLE`
first — if it's not the `0x3FFF` sentinel, the voice is single-sample and
that value *is* the real sample number, no zone walk needed; if it *is*
the sentinel, walk zones from 0 (`SAMPLE_ZONE_SELECT`) until one reads
`E4_GEN_SAMPLE == 0`, which was the clean, consistent signature of "past
the real zones" in every case tested (never garbage), capped at
`_MAX_ZONE_SCAN = 32` as a safety bound rather than a trusted count.
Verified live against both presets: preset 0 now shows 2 voices (V1
single/real sample, V2 multi(2)/2 real samples); preset 1 shows 2 voices,
both correctly multi, with the 3 real distinct samples resolved and named
for each.

**Separate, also-real bug found and fixed alongside this** (not a wire/count
issue): `eosremote.app.EosRemoteApp._load_voice_detail` read a voice's own
general parameter group for display *after* walking that voice's sample
zones — but zone-walking leaves `SAMPLE_ZONE_SELECT` pointed at the last
zone it visited, and the spec only resets zone selection on a fresh
Voice/Preset selection, not automatically. The trailing parameter read was
therefore happening in "zone" scope, not "voice" scope, which is exactly
why voice-only fields (`E4_GEN_CTUNE`/`XPOSE`/`RT_LOW`/`RT_LOWFADE`/
`RT_HIGH`/`RT_HIGHFADE`) came back as the spec's `-1`/"not applicable"
sentinel (`16383`, 14-bit two's complement) in the same screenshot that
surfaced the count bug above. Fixed by re-selecting the voice (which resets
zone selection per spec) between the zone walk and the voice-level
parameter read.

**What zone-select rate does *not* explain, ruled out live:** `set_parameter`
is fire-and-forget (no ack), so a first hypothesis was that the existing
50ms `SEND_GAP` (see module docstring, itself an unverified guess) might be
too tight for the device to apply a `SAMPLE_ZONE_SELECT` edit before the
very next parameter read landed, causing stale/repeated reads. A read-only
probe with the gap widened to 300ms per step got the exact same (correct,
per-zone-distinct) results as the default 50ms gap — the "all zones read
identical data" symptom in the original bug report was fully explained by
the count-off-by-one (reading a voice index that doesn't exist) rather than
a timing race. `SEND_GAP` itself remains unverified for anything beyond
this specific call pattern.
