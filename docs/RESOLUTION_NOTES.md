<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
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

**Follow-up (2026-07-30): the transcription was incomplete, and the stated
reason for it was wrong.** `eos/params.py` carried a comment claiming the PDF
capture "stopped at id 258 (`E4_LINK_FILTER_CTRL_C`)" and that further ids in
that range were unavailable. Re-extracting the source PDF with `pdftotext
-layout` and diffing the result against `PARAMETERS` programmatically showed
13 spec'd ids simply missing, all of them plainly present in the document:

- **259-266** — `E4_LINK_FILTER_CTRL_D`..`_H`, `_SWITCH_1`, `_SWITCH_2`,
  `_THUMB` (all 0/1, "0 = filter off / 1 = filter on"). With these the LINK
  group is 29 parameters, matching the dump format's own "58 bytes per Link"
  figure exactly — previously it was 21 and silently disagreed with §6's byte
  arithmetic.
- **267-270** — `MASTER_WORD_CLOCK_IN` (0-4: Internal/BNC/AES/ADAT/future),
  `MASTER_WORD_CLOCK_PHASE_IN`/`_OUT` (0-511 = 0.00-359.30° in 512
  increments), `MASTER_OUTPUT_DITHER` (0/1). These sit inside the spec's own
  `/** ULTRA ONLY PARAMETERS **/` fence — **our unit is an E4XT Ultra**
  (member code `(7,5)`, §7), so they are expected to be live here.
- **271** — `MASTER_AUDITION_KEY` (0-127), outside the Ultra-only fence.

All 13 are now in the table, and `tests/test_params.py` pins both the full id
set (0-271 minus the spec's own gaps) and the 29-parameter LINK count so the
dump-format disagreement cannot silently reappear. **Not verified live** —
transcription only, same status as the rest of this section; the Ultra-only
four in particular should be confirmed with a `03h`/`04h` range request
before anything relies on them. The general lesson: a "capture stopped here"
note is a claim about the tooling, not about the document, and is worth
re-testing rather than inheriting.

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

After the fix, `eoscli dump 0 <file>` against preset 0 (a real
preset from the bank loaded this session) succeeded: 1096 bytes, matching
the previously-peeked header `byte_count` exactly. A copy is kept at
`docs/samples/e4xt_ultra_preset0_old_format.bin` for future
parsing work. Byte-level inspection:

- **Bytes 0-1:** preset number (u14) = `0`. This means the OLD long-form
  dump payload actually starts with `<NUMBER><NAME>...`, not just `<NAME>...`
  as this file's docstrings previously assumed (fixed) — the `<NAME>`-only
  grammar block quoted in §2 evidently describes the **NEW** format's
  payload, not OLD's.
- **Bytes 2-17:** the preset name, space-padded to 16 — matched the
  catalog exactly. (The saved fixture's name field has since been
  overwritten with `"Test Preset"`: the preset came from a commercial bank
  and its title is not ours to ship — see CLAUDE.md. Only those 16 bytes
  were changed; every offset and parameter value below is as captured.)
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
Both `eoscli` and `eosed` expose `--config PATH`. Note for anyone editing
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
the **EOS 4.0 Software Manual**, which lives one directory *above* the
SysEx spec of §1, not beside it:
`e-mu_eos_4.0_manual.pdf (not redistributed)`
(also in ``, along with `e-mu_eos_4.7_addendum.pdf` — checked
for the FX B algorithm question below and it changes nothing there),
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
looked like it scaled. Root causes, both in `eosed/app.py`:

- **`DataTable`'s own built-in default CSS is `height: auto; max-height:
  100%`** — Textual sizes each table to its *content* (row count), not to
  the pane. The presets pane always shows exactly one fixed page
  (`PRESET_WINDOW`, was a constant 16), so on any reasonably tall terminal
  it sits well under 100% and never grows. The params pane can have anywhere
  from ~22 rows (GLOBAL group) to 146 (a VOICE group's parameters) and often
  exceeds 100%, hitting the `max-height` ceiling — which *looks* like
  correct scaling but is really the same "size to content" behavior landing
  on a different, larger content size. Fixed with explicit
  `#presets { height: 1fr; } #params { height: 1fr; }` in `EosedApp.CSS`,
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
`EosedApp._desired_preset_window()` computes `ceil(1.5 × pane row
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
against preset 0 (the same preset captured in §7's saved dump
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
for API completeness. `eosed.app._voice_sample_info` instead uses the
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
issue): `eosed.app.EosedApp._load_voice_detail` read a voice's own
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

## §12 — `preset_num_voices`'s "-1" correction was also wrong (resolved, verified live)

§11's fix for `preset_num_voices` (subtract 1 from the raw wire value) was
confirmed against two dump-file cross-checks (preset 0 and preset 1, two
different bank states) and shipped. Live use of the sample-usage reverse
lookup (`u`) against the user's actual working bank (270 consecutive
presets, P000-P269) surfaced a scan that stopped early, apparently at a
genuine content gap around preset 81. Front-panel spot checks disproved
that outright:

- **P075**: front panel shows 1 voice, 2 samples, and it audibly
  plays sound on Audition. `preset_num_voices(75)` raw value is `1`; the
  `-1` correction gives `0` — "no voices", directly contradicting the
  front panel and the fact that it plays.
- **P080**: front panel shows 1 voice, 5 samples, also audible.
  Same raw value `1`, same false "no voices" after correction.

So the `-1` fix, despite passing both dump-file cross-checks that motivated
it, is **not a constant offset** — exactly the failure mode already found
for `voice_num_szones` in §11, just one level up (presets instead of
voices/zones). The two dump-file checks that "confirmed" it were preset 0
on two different occasions; neither is proof of a general formula, the same
lesson §11 already spent three paragraphs on and evidently still needed a
fourth demonstration to fully absorb.

**Two competing hypotheses, both checked before picking a fix:**

1. *Timing/race in the scan's rapid sequential `PRESET_SELECT` +
   `preset_num_voices` calls.* Ruled out with a targeted 4-variant probe
   across presets 65-100: with/without explicitly re-setting
   `PRESET_SELECT` immediately before the count read, with/without an
   added 150ms settle delay, each combination run twice. All four variants
   agreed exactly, preset by preset — not a timing bug.
2. *The count field itself is unreliable, like `voice_num_szones`.*
   Confirmed by probing voice 0's own voice-level `E4_GEN_SAMPLE` directly
   for presets 75 and 80 (bypassing `preset_num_voices` entirely): both
   read back real, non-sentinel sample ids at voice 0 — a genuine voice —
   while voices 1-3 all read back a consistent `16382` (`0x3FFE`), clearly
   distinct from the `16383` (`0x3FFF`) multisample sentinel already known
   from §11. `0x3FFE` behaves exactly like the "past the real zones"
   `E4_GEN_SAMPLE == 0` signal in §11's zone walk, but one level up: the
   device's own, consistent "this voice index does not exist" marker.

**Final fix, mirroring §11's zone-walk architecture exactly:** stopped
calling `preset_num_voices` for this purpose entirely.
`eos.bridge.EosBridge.preset_num_voices` now returns the plain raw wire
value (the `-1` removed), kept only for API completeness with a docstring
warning not to trust it as a count — same treatment as `voice_num_szones`.
`eosed.app._voice_sample_info` walks voice indices from 0, reading each
voice's own `E4_GEN_SAMPLE` first: `0x3FFE` means the voice doesn't exist
and the walk stops (returns `None`); otherwise the existing §11 logic
applies unchanged (non-`0x3FFF` ⇒ single-sample voice, sample id is the
value itself; `0x3FFF` ⇒ multisample, walk zones as before). Capped at
`_MAX_VOICE_SCAN = 64` as a safety bound, not a trusted count — same
pattern as `_MAX_ZONE_SCAN`. All three call sites that previously trusted
`preset_num_voices` (`_load_preset_overview`, `_start_browse_voices`, the
`u` reverse-lookup scan's per-preset voice walk) now use this walk
instead. `eosed.demo.DemoBridge` was updated to simulate the same
`0x3FFE` marker for any `VOICE_SELECT` other than 0, since every demo
preset has exactly one real voice — without this, the walk-based logic
would have made every demo preset appear to have `_MAX_VOICE_SCAN` voices
instead of 1.

> **Later (§18a): these are -2 and -1, not `0x3FFE`/`0x3FFF`.** The raw words
> recorded above are correct as observed; what was not known at the time is
> that `E4_GEN_SAMPLE` is a *signed* parameter, so those bit patterns are
> simply the two's-complement -2 and -1. The code now compares against the
> signed values, and `EosBridge` sign-extends them on the way in. Nothing
> about the findings in this section changes — only how the values are
> spelled.

This also explains the sample-usage scan's false early-stop: presets in
the 75-90 range that genuinely have voices were being reported as having
none, manufacturing a run of consecutive "empty" presets that never
actually existed on the device.

## §13 — An empty preset/sample slot answers with a real, named placeholder, not blank or an error (resolved, verified live)

The cache-all sweep's sample-name pass (see the `_run_full_sweep`
docstring in `eosed/app.py`) needed its own "is this slot empty"
signal, separate from `get_preset_name`'s (whose early-stop already comes
from the voice walk, not the name lookup — §12 above). Live use against
the user's real bank (270 presets, S000 upward) reported the sample-name
pass never stopping early at all, even though S195 was confirmed the
first genuinely empty sample slot with nothing populated afterward.

**Two guesses were tried and both failed live before the raw wire reply
was actually inspected:**

1. *Assumed the device pads an empty slot's name with plain ASCII
   spaces* — checked `fetched.strip()` for blankness. Still ran the full
   range live.
2. *Assumed some other non-ASCII filler* (NUL, `0xFF` "erased flash",
   or decode-replacement garbage from `eos.messages._unpad_name`, which
   masks each byte to 7 bits and decodes with `errors="replace"`) —
   checked for the absence of any letter/digit (`any(ch.isalnum() for ch
   in fetched)`), reasoning a real name always has one. Also still ran
   the full range live.

**Root cause, found by finally probing the actual raw SysEx reply**
directly (bypassing `catalog_samples`/the app entirely — a plain script
sending `SampleNameRequest` for samples 0, 1, 194–200, 250, 300, 500, 999
and printing both the raw frame bytes and the decoded name): an unused
sample slot's `SAMPLE_NAME` reply is a completely normal, well-formed
frame containing the literal, human-readable name **`"Empty Sample"`**
— not blank, not garbage, a real placeholder string the device itself
assigns. Confirmed identically for every unused slot probed, from sample
0 through sample 999. The equivalent probe against `PresetNameRequest`
found the exact same device-wide convention one level up: an unused
preset (270, 300, 500, 999 all probed) answers `"Empty Preset"`.

Both of the earlier guesses failed for the same reason: `"Empty
Sample".strip()` is non-blank, and it obviously contains plenty of
letters — neither heuristic had any way to distinguish a real name from
this specific, legitimate-looking placeholder, because neither guess was
checked against what the device actually sends before being written.

**Fix:** `eosed.app._EMPTY_SAMPLE_NAME = "Empty Sample"`; the
sample-name loop in `_run_full_sweep` now compares the fetched name
(case-folded, stripped) against this exact placeholder and treats a
match the same as blank/absent — counts toward the early-stop gap, and
is not cached into `_catalog_cache["sample"]` as if it were a real name.
`get_preset_name`'s own "Empty Preset" answer was left alone: that
early-stop signal already comes from the voice walk (§12), never from
name-lookup success, so it was never exposed to this failure mode, and
whether to also strip "Empty Preset" out of the *displayed* preset
catalog is a separate, purely cosmetic question not yet addressed (the
plain, pre-cache-all `catalog_presets`/`catalog_samples` bank browser
would show the same literal placeholder text for an unused slot, and
always has — not a regression introduced by cache-all).

**Verified live** with a direct, read-only run of the app's actual
`_run_full_sweep("structure")` against the real E4XT Ultra (headless,
via Textual's `run_test()` against the real bridge — no visible terminal
needed): the preset walk stopped at preset 62 after 10 consecutive empty
presets (a real, if unexpected, gap that far down — not a bug), and the
sample-name pass stopped at sample 204 — exactly 195 (the first
genuinely empty slot, per the user) plus the 10-consecutive-empty
default gap. Both numbers landing exactly where expected is strong
confirmation the fix is correct, not just plausible.

## §14 — Making the front-panel LCD actually redraw after a remote edit: Program Change, not the editor protocol (resolved, verified live)

Raised live: a remote rename (`o`) via the editor protocol worked (the
device's own data changed), but the front-panel LCD only showed the new
name after physically touching the preset from the front panel — exactly
what the specification says (`PRESET_SELECT`, id 223, is documented
"independent of the front panel's own selection"; a remote edit lands in
a buffer the LCD doesn't consult until the preset is touched physically).

**First checked: is there any SysEx command in the documented protocol
for "redraw the screen"?** Exhaustively — every command byte in
`eos.messages.Command` (58 defined values across the full 0x00–0x7F
range), the raw specification text itself (searched for "screen",
"panel", "LCD", "display", "refresh", "redraw" — the only hit is the
spec's own stated design goal, that the remote editor is meant to
provide an interface "superior to the standard E4 front panel display",
i.e. the remote side is *meant* to replace the LCD as the interface, not
drive it), and this project's own existing panel/mirror-protocol notes
(§3), which already record that a screen/LCD concept only exists in the
*undocumented* panel protocol, never reverse-engineered here. Conclusion:
no such command exists in the documented editor protocol, by design.

**The actual answer: a plain MIDI Program Change**, suggested by the
user — a completely ordinary MIDI channel voice message, not part of
this SysEx protocol at all, and exactly the same mechanism a keyboard
player uses to switch patches during a performance. Unlike
`PRESET_SELECT`, this *does* make the device select the preset for real
(for playback) and redraw its own LCD, since it's the same path the
front panel's own preset up/down buttons ultimately drive.

**Bank/program scheme, confirmed live (per the user's own explanation,
then verified against real hardware across multiple banks):** Bank
Select MSB is always 0; Bank Select LSB selects which block of 128
presets (0 → presets 0-127, 1 → 128-255, 2 → 256-383, …); Program Change
then picks within that 128-preset block. All three messages (Bank
Select MSB, Bank Select LSB, Program Change) must be sent every time —
the device does not treat a bank as "sticky" in a way that would let
Bank Select be skipped when the target bank hasn't changed from the
last command.

**First live attempt failed in a genuinely confusing way — not because
the bank/program math was wrong, but because of message timing.**
Commanding preset 52 (bank 0, program 52) landed on **P049** (off by
exactly −3, not the classic ±1 indexing mismatch); a *second* Program
Change immediately after, targeting preset 3, did **nothing at all** —
the display stayed on P049. Ruled out MultiMode as an explanation first
(`MIDIGLO_MIDI_MODE` read back live as `0` = omni, not `2` = multi, so
per-channel MultiMode preset mapping doesn't apply here) and confirmed
`MIDIGLO_RCV_PROGRAM_CHANGE` was on (`1`) and the channel read
(`MIDIGLO_BASIC_CHANNEL` = 4, i.e. channel 5) was being used correctly.
**Root cause: unlike SysEx (already throttled by `bridge.ThrottledOut`,
which explicitly documents that only `0xF0`-leading messages get a gap —
"ordinary MIDI... passes straight through"), the three plain channel
messages (Bank Select MSB, Bank Select LSB, Program Change) were being
sent back-to-back with zero delay at all.** The receiving MIDI
interface/driver apparently drops or misorders rapid, ungapped
consecutive channel messages — exactly the kind of USB-MIDI timing
quirk this project has run into before in a different form (see §7's
`ThrottledOut` motivation for SysEx). **Fix:** insert `SEND_GAP` (the
same 50ms already used to throttle SysEx) between each of the three
messages in `EosBridge.send_program_change`. **Verified live afterward
across three separate presets spanning two different banks** — 10 (bank
0), 52 (bank 0), and 300 (bank 2, program 44) — each one landing on the
*exact* commanded preset number with no discrepancy, confirming both the
bank/program math and the gap fix are correct, not just no-longer-broken
by coincidence.

**Not addressed by this feature:** there is still no way to *read back*
which preset the device currently considers active/selected — probed
directly (`PRESET_SELECT` before and after a Program Change) and
confirmed it stays completely unchanged regardless, consistent with the
spec's own "independent of the front panel" wording. Verifying that a
Program Change actually landed on the intended preset still requires
looking at the physical front panel; there is no SysEx-readable
equivalent, at least none found in the documented protocol.

## §15 — Live automation without Program Change silently edits the wrong (inactive) preset, and triggered a device crash (open, 2026-07-28)

**Context:** a sibling project (mpc2emu) tried to drive an amp-envelope
sustain-level calibration sweep against a real E4XT Ultra purely over this
repo's editor protocol: `set_parameters([(PRESET_SELECT, 1), (VOICE_SELECT,
0), ...])` then repeated `set_parameters([(DCY1_LVL, pct), ...])` before each
note, with plain `midi_out.send_message()` note-on/off in between. Every
parameter read back exactly as written (confirmed live via `get_parameter`),
yet the recorded audio never tracked the swept value — it matched Preset 0's
envelope (a ~29s decay) almost the whole time.

**Root cause: exactly §14's finding, hit blind because the calibration script
didn't know about it yet.** `PRESET_SELECT` only retargets which preset's
*data* the editor protocol edits — it is not "select for playback" and does
not change what a Note On actually triggers. The script edited Preset 1 the
whole time while Preset 0 kept right on playing. **Fix for any future live
automation: call `EosBridge.send_program_change(preset)` (not
`set_parameter(PRESET_SELECT, ...)`) before any note is expected to exercise
edits made to that preset** — this is the one documented mechanism that
actually activates a preset for playback (§14).

**Separately, and more seriously: the device crashed mid-session** (front
panel showed a fatal "Gen Trap error", needing a full power cycle to
recover). It happened during a small follow-up diagnostic — a
`set_parameters` call immediately followed by a `get_parameter` call on the
same id, sent moments after the calibration script's full run (9x
parameter-edit + note-on + note-off + parameter-edit + note-on... cycle, ~40
messages total including plain channel messages with **no throttling gap at
all** — `ThrottledOut` only paces `0xF0`-leading SysEx, and §14 already found
that *plain* channel messages need the same `SEND_GAP` treatment because the
USB-MIDI interface drops/misorders rapid ungapped ones). No repro attempt has
been made yet — this note exists so nobody retries the same traffic pattern
blind.

**Not yet root-caused. Blocked on:**
1. **A minimal, deliberately cautious repro** — one isolated
   `set_parameters`-then-`get_parameter` pair, run alone (not after a long
   burst of prior traffic), to check whether it's that specific pattern or
   cumulative untrottled traffic that's at fault.
2. If reproducible, bisect: is it specific to `voice.amp.env` ids, to
   editing-then-immediately-querying the same id, or to sending SysEx
   requests without the same gap §14 mandated for channel messages?
3. Until root-caused, treat rapid automated traffic against a real E4XT as
   genuinely capable of crashing it, not just misbehaving cosmetically —
   this raises the stakes on the "only one session, synthetic-first"
   CLAUDE.md rule beyond what was previously assumed (misordered display
   updates vs. a fatal trap are very different risk levels).

## §16 — OLD-format dump layout for `voice.*` ids is uniform and predictable: `dump_offset = 98 + (id − 53) × 2` (resolved, verified live)

**Resolves the "voice data whose exact byte layout is not yet fully
cross-checked" caveat in §6/§7**, at least for the ids covered here.
Found productively (not as a bug hunt) while a sibling project (mpc2emu)
used this repo to hunt down unknown `E4B` file-format bytes: `set_parameters`
a distinctive value onto a live voice, `dump_preset_old` before and after,
diff the two dumps.

**Every single one of ~35 parameter ids tested, spanning `voice.general`
(53) through `voice.lfo` (116) — crossing the `voice.tuning`/`.mode`/
`.amp`/`.filter`/`.lfo` group boundaries, and the structural boundary
between `vpar`-style scalars and the amp-envelope rate/level pairs at id
70 — landed at exactly `98 + (id − 53) × 2`.** Each parameter occupies 2
consecutive bytes regardless of its live-protocol value range (a `0-127`
scalar and `E4_VOICE_DELAY`'s `0-10000` both take exactly 2 bytes; unused
high bits are just `0`). No exceptions found across the whole tested span.

**Important caveat, not a contradiction:** this describes the *dump's own*
internal layout only. It does **not** mean dump-adjacent ids land at
correspondingly-adjacent offsets in the on-disk **file** format — mpc2emu's
own cross-check found the file groups the amp/filter envelopes' 6 rate/level
stage-pairs by *phase name* (Atk1, Atk2, Dcy1, Dcy2, Rls1, Rls2), while a
third envelope (Aux, ids 117-128, previously undocumented on the mpc2emu
side too) is packed in the *live protocol's own* `SEG0..SEG5` raw id order
instead (Atk1, Dcy1, Rls1, Atk2, Dcy2, Rls2) — two different envelopes in
the same file using two different internal orderings, neither matching this
dump's uniform id-ascending layout. Useful for testing whether a parameter
*exists* and reading its current value quickly; not a substitute for an
independent file-offset diff if the on-disk position is what's actually
needed (see mpc2emu's `docs/RESOLUTION_NOTES.md` §E4BPARAMHUNT for the full
methodology and findings on that side).

**Not yet checked:** whether the same uniform formula extends below id 53
or above id 128, and whether the NEW-format dump (`dump_preset_new`) has an
analogous uniform layout or something else entirely.

## §17 — Name-catalog scans are strictly serial; pipelining them is the big win (open, needs a live probe)

`EosBridge.catalog_presets`/`catalog_samples` and `eosed.app`'s cache-all
sample-name pass all share one shape: send one name request, **block for its
reply**, repeat. Every item therefore costs at least one full round trip plus
`SEND_GAP` (0.05s), so a 0-999 sweep has a **~50 second floor in throttle
alone**, before any device latency — which is most of why a full sweep is
"several minutes" and why the early-stop heuristic had to be invented.

**Why pipelining should work:** the reply frames are self-identifying. A
`PRESET_NAME` (`05h`) / `SAMPLE_NAME` (`09h`) response carries the preset/
sample number in its own payload, so replies do not need to be matched
positionally to requests — exactly the property `get_parameters` already
exploits to batch 64 parameter ids per request and sort the answers out by
id afterwards. Sending K name requests back-to-back and then collecting K
replies keyed by their embedded number would collapse K round trips into one
pipeline depth.

**Why it is NOT implemented yet:** nothing in the spec says the device
queues more than one outstanding request, and the failure mode if it does not
is silent and ugly — dropped replies read as "this preset has no name", which
is indistinguishable from an empty slot and would quietly corrupt exactly the
catalogs this is meant to speed up. That is a wire-behaviour question about
real hardware, and per CLAUDE.md it must be captured, not assumed.

**Probe to run (single session, hardware rule applies):**

1. With an `aseqdump`-style sniffer on the E4XT's route, send 4 `PresetName
   Request` frames back-to-back with **no** intervening read, for four
   presets with known, distinct names.
2. Count the replies. Four replies, each carrying the right number, means the
   device queues and pipelining is safe — record the maximum depth that still
   returns everything (retry with 8, 16, 32).
3. Fewer than four replies, or replies with wrong/duplicated numbers, means
   it does not queue: keep the serial loop and close this out as "won't fix",
   noting the tested depth.
4. Repeat for `SampleNameRequest` (`0Ah`) separately — do not assume the two
   behave alike, the same lesson §11/§12 already taught for the "Number Of X"
   family.

**If step 2 succeeds**, the change is contained: give `catalog_presets`/
`catalog_samples` a `pipeline_depth` parameter defaulting to 1 (today's exact
behaviour), send that many requests before collecting, and match each reply
via `PresetName.decode(...).preset`. Skipped numbers still fall out as
"absent" the same way they do now. Keep the default at 1 until the probe says
otherwise.

**Related, deliberately left alone:** `_run_full_sweep` holds `_bridge_lock`
for the entire multi-minute walk, so every other worker blocks behind it.
That looks like a responsiveness bug but is load-bearing — this protocol is
*stateful* (`PRESET_SELECT`/`VOICE_SELECT`/`SAMPLE_ZONE_SELECT` are device-
side selections, see §11), so letting another request interleave mid-sweep
would silently re-point the selection under the walk and produce wrong data,
which is far worse than an unresponsive pane. Any change here needs a
selection save/restore around each released segment, not just finer locking.

## §18 — First full write test: signedness was handled inconsistently on both halves of a parameter (resolved, verified live)

**The occasion.** 2026-07-31, the first session in which anything was
*written* to the real E4XT Ultra (rev 4.70). Ten scratch presets (P000-P009,
all "Untitled Preset", each exactly one voice with no sample assigned) were
created on the front panel for the purpose. Method: 100ms between every SysEx
send (double the usual `SEND_GAP`, per the standing §15 crash caution), write
every preset-scoped parameter, read it back, then switch away and return and
read it again — the second pass being the one that actually tests
`PRESET_SELECT` scoping rather than an echo of an unchanged selection.

Scoped out deliberately, and still untested live: the Master/erase utilities
(`71h`/`74h`/`75h`/`76h` — one-shot destroyers, never appropriate for
unattended automation), the 70 `master.*` parameters (device-global: basic
channel, tuning, SCSI id — not preset state), and `E4_GEN_SAMPLE` (id 38),
which re-points a voice at a sample and is the field the structure walk reads
its own sentinels from, so writing it would move the ground under the test.

**Result: the transport is sound.** 167 parameters × 10 presets × 2 passes =
3340 comparisons, plus 20 renames, all exact. No dropped replies, no NAKs, no
device crash of the §15 kind. Values written to one preset survive an
arbitrary number of selections elsewhere and read back intact.

**The bug, found before the first write.** A parameter's value and its own
min/max/default were decoded by *different rules*:

* `ParameterEdit.decode` (command 01h, which the device reuses for value
  replies) decoded values with `decode_u14` — never sign-extended.
* `ParameterRange.decode` (04h) sign-extended all three fields with
  `decode_s14` — unconditionally.

So the two halves of the same parameter contradicted each other. Read-only
reconnaissance showed `E4_PRESET_CTRL_A` sitting at **16383** against its own
device-reported range of **[-1, 127] default -1** — 16383 being exactly
`-1 & 0x3FFF`. Proven by the first write performed in this project's history:
writing -12 and -24 to `E4_PRESET_TRANSPOSE` read back as 16372 and 16360,
i.e. `value & 0x3FFF` exactly. **The write path and the device were both
already correct**; only the read side was missing the sign extension.

And the unconditional sign-extension on the range side was the same mistake
mirrored: it corrupts any *unsigned* parameter whose range runs past 8191.
`E4_VOICE_DELAY` (id 61, genuinely 0..10000) reported a maximum of **-6384**
(`10000 - 16384`). That one is not cosmetic — it collapses the parameter's
usable span to nothing, which is exactly how it slipped through the first
write pass: the harness picked values inside `[0, -6384]` and "wrote" 0 every
time. Probed in isolation afterwards, id 61 round-trips every value up to and
including 10000 perfectly.

**Why it cannot be fixed in `eos.messages`.** The wire carries no signedness
flag anywhere — not in the value reply, not in the min/max/default reply.
That layer genuinely cannot know. So both decoders now return **raw 14-bit
words**, and `eos.bridge._signed_value` applies signedness from `eos.params`'
table (a negative `minimum`), for values *and* ranges alike. One source of
truth for both halves, so they cannot drift apart again. An id absent from
the table, or any word without bit 13 set, passes through untouched.

At the time this landed, `E4_GEN_SAMPLE`'s transcribed minimum of 0 meant its
undocumented `3FFEh`/`3FFFh` sentinels (§11, §12) passed through unchanged.
That is no longer so: §18a below establishes that the parameter really is
signed and those sentinels really are **-1 and -2**, and converts the whole
chain to say so.

`encode_s14` refused values past 8191 and so could not express id 61's real
maximum at all; `encode_14` accepts either domain and emits the bit pattern
both would.

**Verified live after the fix:** the whole matrix re-written and re-read with
exact signed comparison and no masking anywhere — 1670/1670, of which 376
comparisons were on negative values, every one of which would have read back
`+16384` before.

### §18a — Transcribed ranges vs. what rev 4.70 actually reports

With hardware in hand, all 267 parameters' ranges were audited against the
device (03h/04h is read-only, so this was safe for `master.*` too). **30
differ** from the spec transcription. They are not all the same kind of thing
and must not be treated alike:

**Genuine transcription errors — corrected in `eos/params.py`:** the six
`E4_VOICE_FENV_SEG*_TGTLVL` and six `E4_VOICE_AENV_SEG*_TGTLVL` entries are
**-100..100**, not the 0..100 transcribed. Confirmed twice over: the device
reports it, and negative values written to them round-trip exactly. The
corresponding *amp* envelope levels (`E4_VOICE_VENV_SEG*_TGTLVL`) really are
0..100 — a volume cannot go negative, and the device agrees — which is what
makes this a transcription slip rather than a version difference. These 12
were the only entries changed.

**Almost certainly firmware/model differences — deliberately NOT changed,**
since the device is already authoritative at runtime (`get_parameter_range`)
and the table documents the 4.00 spec: `E4_PRESET_FX_B_ALGORITHM` 0..27 →
0..32, `E4_LINK_PRESET` 0..999 → 0..1999, `E4_VOICE_SUBMIX` -1..3 → 0..7
(an Ultra has 8 submix outputs), `E4_VOICE_FTYPE` 0..255 → 0..20,
`E4_VOICE_LFO_SHAPE`/`LFO2_SHAPE` 0..7 → 0..15, `MIDIGLO_BASIC_CHANNEL`
0..15 → 0..31, `MIDIGLO_VEL_CURVE` 0..13 → 0..23, `MULTIMODE_CHANNEL` 1..16
→ 1..32, `MULTIMODE_PRESET` -1..999 → -1..1999, `MULTIMODE_SUBMIX` -1..3 →
-1..7, `MASTER_FX_A_ALGORITHM`/`FX_B_ALGORITHM` min 0 → 1,
`MASTER_OUTPUT_FORMAT` 0..2 → 1..2, `MASTER_WORD_CLOCK_IN` 0..4 → 0..3,
`LINK_SELECT` 0..255 → 0..254. Anything reading these off the table for
display (e.g. the `*_NAMES` label tables in `eos/params.py`) is working from
the smaller 4.00 set and will have gaps on this firmware — `describe_value`
already returns `None` for an unknown index rather than exploding.

**`E4_GEN_SAMPLE`'s minimum of -8 — resolved, verified live.** The reported
minimum is -8, not the transcribed 0, which raised the question of whether
there are eight negative special values of which §11/§12 had only ever seen
two (`3FFFh`/`3FFEh`).

Deliberately *not* settled by inference. The -8 on its own is precisely the
shape of evidence that has already been wrong three times in this file (§11
`voice_num_szones`, §12 `preset_num_voices`, and `preset_num_links`): a
plausible signal from a related field, extrapolated without independent
confirmation. Two things argued against reading semantics into it — the
on-disk format's `sample_idx` is an *unsigned* BE u16 (mpc2emu's
`docs/E4B_FORMAT.md` §5.3), so negative sample numbers are not a data domain
there at all; and the reported minimum is **invariant**, identical across
voice-past-the-end, zone-past-the-end, empty preset, P999 and link-selected
contexts, which is what a static field declaration looks like.

**The probe that settled it.** Every existing walk in this repo *stops* at the
first sentinel, so none of them was ever in a position to observe a third
value. A dedicated sweep of a full loaded bank deliberately walked **past**
them: 287 populated presets, voices 0-7 of each regardless of sentinels, plus
zones 0-33 of 40 multisample voices. **3956 reads, 173 distinct values, and
in the whole -16..-1 window only two: -2 (1781×) and -1 (574×).** No -3, no
-8, nothing between.

So the parameter is genuinely signed, only two negative values exist, and
they are exactly -1 (multisample) and -2 (no such voice). Converted
accordingly, in one atomic change: `eos/params.py`'s minimum to -8,
`eosed/app.py`'s `_MULTISAMPLE_SENTINEL`/`_NO_SUCH_VOICE_MARKER` to -1/-2,
`eosed/demo.py`'s fake marker, and the test fakes, which have to answer in
the same domain the real bridge now returns.

**Why converting was worth the risk at all**, given it changes nothing
functionally: before it, sentinel handling was correct *only because the
table was wrong*. `_signed_value` reads the table's minimum to decide whether
to sign-extend, so the transcribed 0 was load-bearing — and anyone correcting
that 0 (an entirely reasonable thing to do) silently broke voice detection.
The trap is now gone rather than merely guarded.

**Regression check, live:** `eosed.app._voice_sample_info` was run against 55
real presets (40 of them containing multisample voices) immediately before
and immediately after the change, and the two captures are **byte-identical**
— 152 voices, 429 zones, same structure both times. Tests alone would not
have caught a sentinel-domain mismatch against real hardware, since
`DemoBridge` and the test fakes bypass `_signed_value` entirely.

## §19 — The voice/zone walk caps were guesses, and both were too small for real content (resolved, verified live)

Found while re-testing §18a against a **full commercial bank** (128MB of
samples, 990 populated presets, P000-P989) rather than the sparse
user-built bank the earlier work used.

`_MAX_VOICE_SCAN = 64` and `_MAX_ZONE_SCAN = 32` were introduced (§11/§12)
as "safety bounds, not trusted counts" — correct in principle, but the
*numbers* were picked to be comfortably larger than anything then observed,
which is a guess dressed as a bound. Real content overruns both:

| preset | name | voices |
|---|---|---|
| P111 | drum kit | **94** |
| P113 | drum kit | 87 |
| P005 | drum kit | 81 |
| P112 | drum kit | 76 |

and the deepest multisample voice found (P041 V0, P040 V0/V1) has **62
zones**, nearly double the 32 cap. 120 presets on this bank have 8+ voices.

**Why this was invisible.** Truncation produces no error and no warning: the
walk simply stops, and voices past the cap look exactly like voices that do
not exist. The Voice pane showed 64 rows for a 94-voice kit, and — worse,
because it is silent and wrong rather than merely incomplete — the Samples
"used by" aggregation omitted every sample referenced *only* by voices 64+.
The same applies to the `u` reverse-lookup sweep, which would report "this
sample is used by no preset" for a sample that only a deep kit's later
voices play.

**The bound to use is the protocol's own, not a bigger guess.**
`VOICE_SELECT` and `SAMPLE_ZONE_SELECT` are both 0..255 in the spec table
*and* in the device's own 03h/04h reply (checked live), and the EOS 4.0
Software Manual states it outright in its preset overview: **"Each preset can
have up to 256 voices."** Both caps are now 256. Raising them costs nothing
for ordinary presets — every walk stops at its own sentinel long before the
cap — and the presets that do pay are exactly the ones that were being
silently truncated.

**Verified live** through `eosed.app._voice_sample_info` itself: P005/P111/
P112/P113 now walk to 81/94/76/87 voices and 82/79/55/60 distinct samples,
about 5s each at a 25ms send gap.

**Perf note, now with real numbers instead of the speculation TODO.md
carried:** a deep kit costs ~5s to walk at 25ms and roughly 20s at 100ms,
since every voice is a sequential `VOICE_SELECT` + read round trip.

**That is not, however, a case for applying §17's pipelining here — the
voice walk is a strictly harder problem, and conflating the two would be a
mistake.** The two share a shape (send, block for reply, repeat) but not the
property that makes pipelining *sound*. A `PresetName`/`SampleName` reply
carries its own preset/sample number, so K requests can be fired off and
their replies matched by content, order irrelevant. A parameter reply
carries only `(param_id, value)` — no selection context — so a pipelined
voice walk would send `VOICE_SELECT=0; REQ(38); VOICE_SELECT=1; REQ(38); …`
and receive N replies that all read "parameter 38 = X", distinguishable
*only by arrival order*. That needs reply ordering to be guaranteed (never
probed), on top of `VOICE_SELECT` being device-side state that any
interleaved request would re-point — the same hazard §17's own closing
paragraph raises against releasing `_bridge_lock` mid-sweep. Getting it
wrong produces silently wrong structure data, which is exactly the outcome
§17 refuses to risk for names.

If this walk is to be sped up, the honest options are a shorter send gap
(§19a) or fetching less, not pipelining it on the strength of a resemblance.

### §19a — 25ms send gap, tested

`SEND_GAP` has been 0.05 with the module docstring admitting it was
"conservative; NOT reverse-engineered for EOS". Tried 0.025 against the real
device, A/B against the known-good 0.1, separating the two risk profiles:

* **reads are self-pacing** — we block for each reply, so the gap only adds
  latency. 40 presets: 20.4s at 100ms vs **8.4s at 25ms**, zero errors, and
  the two runs returned byte-identical data.
* **writes are not** — `set_parameters` fires frames back to back with only
  the gap between them and no reply to throttle against, so this is where a
  short gap would overrun the device's input buffer, losing edits silently.
  3 bursts x 145 voice parameters, read back each time: **zero lost or wrong
  at either gap**, and the original values restored cleanly afterwards.

Then sustained: the full 990-preset walk above ran ~500s of continuous
traffic at 25ms with no errors and no §15-style crash. So 25ms is safe for
this device on this interface, for both short and sustained load. Not
changed as the default in `eos/bridge.py` — §15's crash is still not
root-caused, and there is no reason to spend the safety margin globally when
the callers that care can pass `gap=`.

## §19b — Read and write send gaps are now separate, because they protect against different things (resolved)

Pushing the single `SEND_GAP` down (§19a) showed diminishing returns and,
more usefully, showed *why*: the gap is doing two unrelated jobs, and only
one of them still matters.

**Measured, 25ms → 10ms → 5ms, on a full commercial bank:**

| gap | 40-preset read | 6 × 145-param write bursts | data | lost writes |
|---|---|---|---|---|
| 25ms | 8.4s | 5.8s | reference | 0 |
| 10ms | 6.2s | 5.6s | identical | 0 |
| 5ms | 5.8s | 5.5s | identical | 0 |

Cutting the gap 5× bought 31% on reads and essentially nothing on writes.
The floor is not our pacing: MIDI is 31250 baud ≈ 0.32ms/byte, so a batched
42-edit frame (~180 bytes) occupies **~58ms of wire** no matter what, and
what remains is device round-trip latency.

**The asymmetry, which runs opposite to intuition.** The useful axis is not
read-vs-write but *"is this send followed by a blocking wait for its reply?"*

* A **request** is. The round trip already separates it from the next send,
  so its gap is nearly redundant — which is exactly why 5ms was harmless.
* A **write** is not. `set_parameters` emits up to 42 edits per frame and
  several frames back to back with only the gap between them and nothing to
  pace against. That gap is the sole protection against an overrun input
  buffer, and its failure mode is **silent**: a lost edit raises nothing and
  is found only by reading back.

So the conservative gap belongs on writes, and reads — the overwhelming bulk
of traffic in every sweep this app does — can be cut. `ThrottledOut` now
takes `write_gap` alongside `gap`, applied as time owed *after* a send (how
long the device gets to digest what it was handed), so a write's larger gap
delays whatever follows it. `EosBridge._send(..., write=True)` marks the
eight fire-and-forget sends: parameter edit(s), preset/sample naming, and the
four destructive utilities. Dump ACK/NAK deliberately stay on the read gap —
the device is streaming and pacing us there.

**Verified live:** identical 40-preset read workload plus 4 write bursts, at
a uniform 50ms vs a 5ms/50ms split — reads **12.4s → 9.4s** (24% faster),
writes unchanged at 4.1s, zero lost edits either way.

**Defaults deliberately unchanged.** `write_gap` defaults to `gap`, so
nothing moves unless a caller asks. §15's crash is still not root-caused, and
the sub-25ms figures have only ~20s of traffic behind them each, against
~500s for 25ms — "not disproven", not validated. The split adds the
*capability* to spend the margin where it is provably safe (reads) while
keeping it where the failure would be silent (writes); adopting a lower
default is a separate decision needing a sustained soak first.

## §20 — How long a cache-all sweep actually takes, and why preset count is the wrong predictor (resolved, measured live)

Measured by calling `eosed.app.EosedApp._run_full_sweep` itself — unbound,
against a shim supplying only the attributes it touches — rather than
reimplementing the walk, so the figures describe the real feature rather than
a lookalike loop. (A reimplementation would silently drop things like the
sample-name memo or the early-stop heuristic and report a number no user
would ever experience.)

**Bank:** a full commercial bank on an E4XT Ultra rev 4.70 — 990 populated
presets (P000-P989), 128 MB of samples with ~260 KB free, 2013 KB of used
preset RAM, and **6198 voices**. Default 50 ms send gap throughout.

| depth | elapsed | per KB used | per 50 presets |
|---|---|---|---|
| `names` | 150 s | 0.075 | ~8 s |
| `structure` | 1371 s (23 min) | 0.68 | ~69 s |
| `full` | **6241 s (1 h 44 min)** | 3.10 | ~310 s |

`full` is 4.5× `structure`: it adds one batched 146-parameter fetch per
*voice*, and there are 6198 of them.

**Preset count is the wrong predictor.** `structure` and `full` scale with
*voices*, not presets — 990 one-voice pads are an order of magnitude cheaper
than 990 drum kits at the same count, and nothing about the preset number
distinguishes them. But voice count is not knowable up front: the walk that
would establish it *is* the expensive thing being predicted.

**Used preset RAM is a usable proxy**, and costs one `preset_memory()` query
before the sweep starts. Across the banks measured it tracks voice count
closely — this bank runs ~3.1 voices per KB of used preset RAM (2013 KB /
6198 voices), and an almost-empty scratch bank reported 3 KB for 10 voices.
So `eosed.app` estimates sweep time as `used_kb × seconds_per_kb` and prompts
only when that exceeds a minute. The constants above are that calibration.

**Caveats worth keeping attached to these numbers:**

* They are **Ultra** numbers. Non-Ultra E4 models have slower CPUs, and
  device response time already dominates our send pacing — §19a showed
  cutting the gap from 25 ms to 5 ms bought only ~30%, because a batched
  frame's wire time (~58 ms) plus device latency is the floor.
* The harness calls `set_status`/`call_from_thread` directly instead of
  repainting a TUI, so the real `a` key is marginally slower. Noise at this
  scale — UI repaints against 6198 batched MIDI fetches.

### §20a — a self-inflicted estimation error worth recording

Before the `full` run finished, its remaining time was estimated from the
§19 sweep's histogram, giving **~4130 voices** and a predicted 75-95 minutes.
The real answer was **6198 voices and 104 minutes** — the voice count was 33%
low, and the time estimate correspondingly so.

The cause: that histogram came from a sweep whose own `MAX_VOICE` cap was 32,
so every drum kit of 76-94 voices contributed exactly 32. The estimate was
built on data truncated by **the very cap §19 had just been written about**,
in the same session. The lesson is not "estimate better" but that derived
data inherits the limits of the walk that produced it, and a bound that was
adequate for the original question (finding negative sentinel values) is not
automatically adequate for a later one (counting voices). Worth checking what
a dataset's collection cap was before computing totals from it.
