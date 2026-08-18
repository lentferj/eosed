<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# Resolution Notes

*How* things got resolved: RE procedures, hardware probes, ready-to-apply
code. `TODO.md` tracks *what* is open; this file tracks *how* to close it.

## §1 — Editor protocol source document (resolved)

The full "Remote Preset Editing via MIDI SysEx" spec (Draft #30, EOS 4.00,
Brian Clark, E-mu Systems, 17 Feb 1999, 61 pages) is **not redistributed
with this project** — it is E-mu's document, not ours to ship. Anyone
reproducing this work needs their own copy; it circulates as
`e-mu_eos_remote_sysex.pdf`.

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

> **CORRECTION (2026-08-18).** This section, and several later ones, call the
> panel protocol "undocumented". That was true of what this project could find,
> and false as a statement about the world: E-mu documented it in 1996, in
> "Remote Control of the Emulator-IV Series via MIDI/SMDI" (the *Peptalk*
> document). It surfaced only after the RE here was complete. The independence
> of that work is unaffected — and its opcodes agree with E-mu's, including
> button `40h`, full display `50h` and display request `51h`, which is the
> strongest confirmation the panel work has had. Later uses of "undocumented"
> below are left as written: they record what was known at the time, and this
> note covers them.
>
> The word to have used was "no documentation found", not "none exists".

A **second, undocumented** SysEx dialect exists for that: `F0 18 7F 00 00
<cmd> … F7` (note: device id fixed at `00`/`7F`, not the `21h`-family frame).
Fragments published by third parties who reverse-engineered it from MIDI
traffic between Ray Bellis's browser tool (<https://emu.tools>)
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

**NOT WHAT HAPPENED (corrected 2026-08-18).** This method was proposed before hardware access and deliberately NOT taken. e-remote was never run, sniffed or consulted. The only external input was the published page's opcodes; everything else came from this project's own captures of the device echoing physical front-panel presses (docs/captures/, device-to-host frames only). The "exercise one control at a time and diff" half of the plan
was kept; the "let e-remote drive it" half was replaced by a human pressing the
buttons and naming each one.

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

## §6a — LFO rate display table: transcription gap (RESOLVED via mpc2emu's hardware calibration)

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
silently guess-correct it, `eos/params.py::cnv_lfo_rate()` raised
`NotImplementedError` with a pointer back here.

**Resolved 2026-08-01, by the second route and from the other direction.**
The sibling mpc2emu project needed the same mapping for its own converter and
calibrated it empirically off the E4XT's *own rate menu*, fitting a
log-quadratic (`models/common.py`, `lfo_rate_byte_to_hz`, GPL-2.0-or-later —
attributed in `LICENSE`):

    Hz = exp(-0.000300578·b² + 0.0808242·b - 2.52573)

Anchors: byte 0 = 0.08 Hz, 64 = 4.12 Hz, 127 = 18.01 Hz — all three
reproduced exactly by the fit, which is monotonic across 0..127 (its vertex
lies at byte ≈134, outside the range, so no two bytes map to one frequency).
Both checks are pinned by tests.

**Displayed with a leading `~`** (`~4.12Hz`), deliberately: this approximates
the front panel rather than reproducing the spec's table digit for digit, and
the notation says so at a glance. Every other conversion in `eos/params.py`
prints an exact spec-derived value and carries no tilde.

Worth noting how this closed: not by re-reading the PDF, but because a
sibling project measured the machine instead. The ambiguous page-wrap is
still ambiguous; it simply stopped mattering. This does not block anything else — the
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
the **EOS 4.0 Software Manual** (`e-mu_eos_4.0_manual.pdf`), a different
document from the SysEx spec of §1 and likewise not redistributed here. The
4.7 addendum (`e-mu_eos_4.7_addendum.pdf`) was checked for the FX B
algorithm question below and changes nothing there. The names come from
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

## §21 — Master/erase actions: ALL FOUR verified live (resolved)

The four destructive utilities were the last unverified commands in this
project: Preset Delete (`71h`), Erase RAM Bank (`74h`), Erase All RAM Presets
(`75h`), Erase All RAM Samples (`76h`). **All four are now confirmed live** — §21a-§21d below. Every one was fired
by hand from the TUI's arm-then-fire modal, never from a script, with
before/after state captured over SysEx from a separate session. The app reaches them only through a modal arm-then-fire screen, never
a single keypress, and `--allow-write`/`w` gates them on top of that.

### Established behaviour: EOS does not compact

**EOS never compacts a bank on delete.** Deleting one preset or one sample
leaves every other slot at the number it already had; the deleted slot simply
becomes empty. The reason is that slot numbers are load-bearing elsewhere —
MIDI Program Change and multimode setups address presets *by number*, so
compacting would silently re-point every sequencer track and multi entry that
referenced anything above the hole.

**This is established, on the author's direct experience of the machines** —
front-panel-visible behaviour seen over years of use, not an inference from
the specification. It is a different class of claim from the "Number Of X"
count fields (§11/§12), which were plausible readings of a document and wrong
on contact with hardware; here the hardware *is* the source.

The one part still genuinely open is narrower: whether a **remote** `71h`
delete behaves identically to a front-panel delete. There is no reason to
expect otherwise, and the numbering rationale above applies regardless of who
issues the delete — but "the remote path matches the panel path" is exactly
the kind of assumption this project has been bitten by before, and step 1
below checks it for free.

### Bank to test against

Small, and *structurally* varied rather than large. The verification needs:

* **≥3 presets**, so a middle one can be deleted and its neighbours shown
  intact — and so compaction would be visible if it happened.
* **presets and samples present at the same time**, which is the only way to
  separate `75h` from `76h` from `74h`: the discriminating evidence is what
  each one *spares*, not what it destroys.
* **distinguishable presets** — differing voice counts are ideal, since a
  read-back then proves identity rather than mere presence.
* **small sample payload.** Sample bytes add nothing to the proof and
  everything to the wait: the sequence needs 3-4 full bank reloads to re-arm,
  so single-digit MB turns a ~40-minute exercise into a few minutes.

Roughly 5-10 presets and 5-10 samples in under ~10 MB is ample. A gap in the
preset numbering is *not* needed: EOS does not compact (above), and deleting
a middle preset demonstrates it either way.

### Order, least destructive first

1. `71h` on a middle preset. Verify: that slot reads `"Empty Preset"` and
   walks to `-2` voices; **every other preset keeps its own number, name and
   voice count** (per the section above — this confirms the remote path
   matches the panel path, it is not an open question about the device);
   sample memory is unchanged.
2. Reload. `75h`. Verify: presets gone, **sample memory unchanged and sample
   names still readable** — the check that separates this from `74h`.
3. Reload. `76h`. Verify: samples gone, presets still present.
4. Reload. `74h`. Verify: both gone.

Each step needs its own reload; a half-erased bank cannot verify the next.
Snapshot `preset_memory()`/`sample_memory()` plus the preset and sample name
catalogs before each step, so verification is a diff rather than a judgement.

**Do not script this.** Per the project's own rule, a Master action is fired
by hand, from the TUI's arm-then-fire modal, with the bank known-reloadable —
which also exercises the real user path rather than just the wire command.


### §21a — Preset Delete (`71h`) confirmed live, 2026-07-31

The first Master action ever fired at real hardware. Driven **by hand** from
the TUI's arm-then-fire modal (`--allow-write`, select preset, `m`, `1` to
arm, `Enter` to fire) rather than from a script, per this section's own rule;
the author operated it, and the before/after state was captured over SysEx
from a separate session with the app closed, since only one session may hold
the MIDI port.

Bank: three presets and two samples in 3.5 MB — deliberately tiny, per the
sizing argument above.

| | before | after |
|---|---|---|
| P000 | `P_VCUT`, 12 voices | `P_VCUT`, 12 voices |
| P001 | `P_VGAIN`, 7 voices | **gone** |
| P002 | `P_VPAN`, 7 voices | `P_VPAN`, 7 voices — **same slot** |
| samples | S001, S002 | S001, S002 |
| preset RAM | 8 KB | **5 KB** |
| sample RAM | 3.49 MB | 3.49 MB |

**Findings:**

* Deletes exactly the selected preset, leaving the others untouched.
* **No compaction, confirmed for the remote path.** P002 kept its number and
  name. This was the one genuinely open question: the non-compacting
  behaviour was already established from front-panel use, but "a remote
  `71h` behaves like a panel delete" was an assumption. It does.
* Preset RAM actually drops (8 KB → 5 KB), so this frees storage rather than
  merely blanking a name.
* Samples and sample RAM are untouched, as expected for a preset-scoped
  delete.

**Why the bank's names mattered more than its structure:** P001 and P002 were
both 7-voice presets, so voice count alone could not have separated "did not
compact" from "compacted, and the survivor happens to look similar". The
distinct names are what made the result unambiguous — worth repeating when
testing the three Erase utilities.

This also exercised the full user path end to end, not just the wire command:
the `--allow-write` gate, the modal's arm-then-fire two-keypress requirement,
and the command itself.


### §21b — Erase All RAM Presets (`75h`) confirmed live, 2026-07-31

Fired by hand from the arm-then-fire modal (`m`, `3`, `Enter`), same method
as §21a, against the bank §21a left behind (P000 `P_VCUT` 12 voices, P002
`P_VPAN` 7 voices, S001/S002, 3.49 MB).

| | before | after |
|---|---|---|
| P000 | `P_VCUT`, 12 voices | **`Untitled Preset`, 1 voice** |
| P002 | `P_VPAN`, 7 voices | gone |
| S001 / S002 | present | **present, unchanged** |
| preset RAM | 5 KB | **0 KB** |
| sample RAM | 3.49 MB | **3.49 MB** |

**Confirms the intended split:** presets are destroyed, **samples and sample
RAM are untouched**. That is the whole distinction between `75h` and `74h`,
and it holds.

**The bank is not left empty — and that is a device invariant, not
something `75h` does.** After the erase, slot 0 holds a blank
`"Untitled Preset"` with one voice while preset RAM reads 0 KB. Per the
author: **P000 always exists on an EOS machine.** The device never holds
zero presets, so "erase all presets" necessarily bottoms out at that single
empty one rather than at nothing. `75h` is not re-initialising anything
special; it is removing everything it can and leaving the floor.

This was surprising from the outside, which is exactly why it was worth
firing rather than reasoning about — a client author reading only the
command name would predict an empty bank.

Consequences for anything scripting against this:

* **"No presets" and "one empty Untitled Preset" are the same state**, and
  a preset-name sweep can never come back completely empty on this hardware,
  since P000 always exists. Do not treat a `P000` reading
  `"Untitled Preset"` as evidence an erase failed.
* `preset_memory()` reading 0 KB used is the reliable signal that the erase
  took, not the absence of preset names.
* `"Untitled Preset"` and `"Empty Preset"` are **different states**, and the
  distinction is load-bearing. `"Empty Preset"` (§13) means the slot holds
  nothing — which is what `71h` leaves behind, and what every slot above the
  populated range reads. `"Untitled Preset"` means a real, empty preset
  occupies the slot: it has a voice, and it is what the user's own scratch
  presets read before anything was written to them.

Predicted but worth stating: this is why the test bank needed samples in it
at all. Without them, `75h` and `74h` would have produced identical
observations.


### §21c — Erase All RAM Samples (`76h`) confirmed live, 2026-07-31

Fired by hand from the arm-then-fire modal (`m`, `4`, `Enter`) against the
reloaded test bank.

| | before | after |
|---|---|---|
| S001 / S002 | `VNoise_C2` / `VTone_C2` | **gone**, both read `"Empty Sample"` |
| P000 / P001 / P002 | 12 / 7 / 7 voices | **unchanged, all three** |
| preset RAM | 8 KB | 8 KB |
| sample RAM | 3.49 MB | 3.00 MB |

Confirms the mirror of §21b: samples destroyed, **presets and preset RAM
untouched**. Two things fell out that were not predicted.

**Sample RAM has a ~3 MB floor: "3.00 MB used" IS empty.** The erase did not
take the figure to zero. Corroborated independently earlier in the same
session — the first survey of a bank containing no samples at all reported
exactly `free_10kb = 12800`, i.e. the same 3.00 MB used. So roughly 3 MB is
device overhead that is always accounted as used. **A client testing
`sample_memory()` used == 0 for "no samples" will never see it.** Test the
sample-name catalog instead, or compare against this floor.

**Voices are left DANGLING, not stripped.** After the erase, `P000`'s voices
still read `E4_GEN_SAMPLE = 1` — pointing at a sample that no longer exists,
while `get_sample_name(1)` returns `"Empty Sample"`. The presets keep their
full voice/zone structure referencing nothing.

This is the more consequential finding, and it has a direct bearing on this
project: **`eosed`'s Samples pane resolves voices to sample numbers and looks
up their names, so after a sample erase it will display references to samples
that are gone.** Nothing in the voice-level value distinguishes "sample 1"
from "sample 1 which has been erased" — the only way to know is to cross-check
the sample catalog. The same applies to `u` (reverse sample lookup) and to any
external tool walking voices.

Not treated as a bug in the device: leaving the reference intact is arguably
the right behaviour, and is consistent with the non-compacting rule (§21a) —
slot numbers stay stable, and reloading the samples would make the presets
whole again. But it means "this voice plays sample N" and "sample N exists"
are independent questions.


### §21d — Erase RAM Bank (`74h`) confirmed live, 2026-07-31

The last of the four. Fired by hand (`m`, `2`, `Enter`) against a freshly
reloaded test bank, so that both categories were present and it had something
of each to destroy — without that, `74h` cannot be told apart from `75h`.

| | before | after |
|---|---|---|
| P000 / P001 / P002 | `P_VCUT` 12v, `P_VGAIN` 7v, `P_VPAN` 7v | **`Untitled Preset`, 1 voice** |
| preset RAM | 8 KB | **0 KB** |
| S001 / S002 | `VNoise_C2`, `VTone_C2` | **gone** |
| sample RAM | 3.49 MB | **3.00 MB** |

**`74h` is the union of `75h` and `76h`**, with nothing left over. It lands on
both floors established independently by the two earlier tests — the lone
`"Untitled Preset"` of §21b and the 3.00 MB sample-RAM floor of §21c — which
is a useful cross-confirmation of both, since they were measured in separate
runs against different starting states.

### Summary of the four

| command | | verified behaviour |
|---|---|---|
| `71h` | Preset Delete | Deletes the *selected* preset only. **Does not compact** — survivors keep their numbers and names. Frees preset RAM. Samples untouched. |
| `74h` | Erase RAM Bank | Presets **and** samples, in one action. Both floors. |
| `75h` | Erase All RAM Presets | Presets only; samples and sample RAM untouched. Bottoms out at the single `"Untitled Preset"` that always exists. |
| `76h` | Erase All RAM Samples | Samples only; presets and preset RAM untouched. **Leaves voices dangling** at erased sample numbers. |

Two device facts fell out that are not in the specification and that a client
author would not guess, both worth treating as load-bearing:

* **`preset_memory()` reaching 0 KB, not an empty name catalog, is the signal
  that presets are gone** — P000 always exists (§21b).
* **`sample_memory()` never reaches 0**; ~3.00 MB is device overhead, and that
  figure *is* empty (§21c).

## §22 — Cross-check against mpc2emu's independent RE (2026-08-01)

The sibling mpc2emu project reverse-engineered the same machine from the
opposite side — differential saves and byte-hunting of the on-disk E4B format,
with no access to E-mu's protocol specification. It has now cross-referenced
this project's transcribed parameter table against its own findings
(`../mpc2emu/docs/E4B_FORMAT.md`, "Cross-reference: the EOS editor-protocol
parameter spec"). Three outcomes, in increasing order of interest.

**Corroboration.** Names, ranges and units line up with fields mpc2emu had
RE'd anonymously — `E4_VOICE_NON_TRANSPOSE` ↔ its `vpar[38]`,
`E4_VOICE_CHORUS_AMOUNT` (0-100%) ↔ `vpar[42]`, and the six-stage envelope
segment naming (`Atk1/Dcy1/Rls1/Atk2/Dcy2/Rls2`) confirms the rate/level
pairing and ordering it had inferred from byte layout alone. Note the id
spaces are *different*: a SysEx parameter id is not a `vpar[]` offset. The
semantics agree; the numbering does not.

**Something flowed back to us: §6a is now closed** — mpc2emu's measured LFO
rate calibration replaced the untranscribable display table. See §6a.

**And one real disagreement, which is theirs to resolve but ours to know
about.** `eos/params.py::fil_freq()` is a port of the specification's own C
for the filter cutoff byte → Hz conversion. mpc2emu measured the *acoustic*
−3 dB corner of the 4-pole lowpass on noise and got a materially different
answer — up to **3× apart** mid-range.

Probably not a contradiction: the two describe different quantities. The
spec's function yields the **displayed / design** frequency, which is what the
front panel shows; mpc2emu measured where the filter actually turns over, and
a 4-pole cascade's −3 dB point sits well below its design frequency. The
disagreement runs in exactly that direction.

**For this project that is fine, and no change is warranted.** eosed's job is
to show the user what the device shows, so the design frequency is the correct
quantity and `fil_freq` should stay as the spec defines it. The question mpc2emu
raises — whether a *converter* should target the design frequency or the
measured corner, since source formats (SF2/EXS24/SFZ/GIG) specify a design
frequency — is a question about conversion fidelity, not about this display.

Recorded because it would be easy to mistake for a bug here later: if someone
measures the E4XT's filter and finds `fil_freq` "wrong", this is why, and the
answer is that they measured a different thing.

---

## §24 — The blanket `except` was not how §23 hid; it is a second bug, and it destroys files (resolved, 2026-08-13)

**§23 is wrong about this, and the correction matters.** That entry treats
the encoding as *the* bug and the blanket `except Exception: return {}` as
merely the reason it was silent. The commit message went further and called
the masking secondary. It is not secondary and it is not a symptom: it is an
independent defect with a worse failure mode than the one it hid, and fixing
the encoding left it live.

**The mechanism.** Saving is read-modify-write, deliberately — the module
comment says so, "not a blind overwrite, so unrelated keys survive each
other's saves". That invariant holds only while a failed read is
distinguishable from an empty one. It is not:

```python
try:
    return tomllib.loads(text)
except Exception:
    return {}                 # "no settings" and "I could not read this"
```

So a parse failure turns the next save into a blind overwrite of a file the
app never understood. Reproduced with a hand-typed bracket — no encoding
involved, on a UTF-8 Linux box:

```
before:  cache_depth = "full"
         send_pc_on_preset_select = false
         this line is [broken

after one unrelated save (the view preference):
         # eosed local config — gitignored, safe to delete.
         compact_view = true
```

Both hand-edited settings gone, silently. **The cp1252 em dash was one cause
among many.** A stray bracket, a file truncated by a crash, a half-written
config from a killed process, or the next encoding surprise all reach the
same place.

### Why the framing mattered, not just the code

§23 read as history — a bug found and fixed. Anyone reading it would conclude
the config path was now sound. The sentence describing the masking sat there
as an explanation of a past failure while describing a present one, which is
the specific way documentation goes wrong in this project: not by being
false, but by describing a live mechanism in the past tense.

### The fix, and the part most likely to have been got wrong

`_read_config(path)` now returns `(settings, status)` with status
`ok` / `missing` / `unreadable`. `_read_config_dict` stays as a thin wrapper
for the ten readers that cannot act on a failure. Both savers go through
`_update_config`, which **refuses to write when the existing file did not
parse** and prints one line to stderr saying so.

**`missing` and `unreadable` must stay distinct.** Conflating them is the
original defect, and the obvious over-correction — refuse to write whenever
the read produced nothing — would stop a first run ever creating a config,
swapping one silent failure for another. There is a test for exactly that,
because it is the mistake this fix invites.

A preference that fails to persist is a nuisance. A file quietly emptied is
not recoverable by a user who has no reason to suspect it happened, which is
why the refusal is loud and the write is the thing that gives way.

### What it shares with §23, and what it does not

§23's lesson was that a correct test running only where the bug cannot
reproduce proves nothing. This one is different: **the failing configuration
was reachable on the author's own machine the whole time.** It needed no
matrix, no second platform, and no hardware — one malformed file and one
save. It survived because the code had been read as "the encoding was the
problem" and nobody wrote the four-line reproduction.

The existing test `test_read_config_dict_invalid_toml_returns_empty` pinned
the returning-empty behaviour, so it was deliberate rather than overlooked.
Pinning a behaviour is not the same as establishing that it is right.

## §23 — The config file was silently unreadable on Windows, and the CI matrix is what found it (resolved, 2026-08-13)

**The bug.** `eos/bridge.py`'s `_write_config_dict` opened `config.toml` in
text mode with no `encoding=`:

```python
with open(path, "w") as handle:          # <- locale codec, whatever that is
```

Python then uses the *locale* codec, which is UTF-8 on this project's Linux
box and **cp1252 on Windows**. The file's first line is our own header
comment, and it contains an em dash:

```
# eosed local config — gitignored, safe to delete.
```

cp1252 encodes that em dash as the single byte `0x97`. TOML is UTF-8 **by
specification**, and `tomllib` enforces it, so the read side —

```python
with open(path, "rb") as handle:
    return tomllib.load(handle)
```

— raised `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97`. The
blanket `except Exception: return {}` around it then converted that refusal
into an empty dict, which is *indistinguishable from "no config file"*. So
nothing failed loudly; the settings simply were not there.

> **Corrected by §24.** This entry treats that blanket `except` as the reason
> the encoding bug was silent. It is a second bug in its own right, and the
> worse of the two: because saving is read-modify-write, any parse failure —
> a hand-typed bracket, a truncated file, an encoding surprise — makes the
> next save overwrite a file the app never read. Fixing the encoding did not
> touch it. Read §24 before concluding from this entry that the config path
> is sound.

Reproduce it on any platform:

```python
with open(p, "w", encoding="cp1252") as h:      # what Windows did implicitly
    h.write("# eosed local config — gitignored, safe to delete.\n"
            'send_port = "Out Port"\n')
tomllib.load(open(p, "rb"))                     # UnicodeDecodeError, byte 0x97
```

**What it cost a Windows user.** Three things, all silent:

1. The last-known-good port cache never persisted, so **every** launch paid a
   full autodetect sweep — tens of seconds on a host with many ports, and the
   precise cost the cache exists to avoid.
2. The compact/extended view preference never survived a restart.
3. **Hand-edited keys were destroyed.** `save_*` round-trips through
   `_read_config_dict` before writing, so a read that returned `{}` meant the
   next save wrote *only* the key it was saving. A user's `cache_depth`,
   `sample_usage_early_stop` or `send_pc_on_preset_select` vanished the first
   time the app saved anything — with the file on disk looking perfectly
   plausible to them.

**The fix** (commit `a45d590`) names the encoding on write, and makes the read
side tolerant so the damage is repairable rather than permanent:

- write with `encoding="utf-8"` — both ends now agree with the TOML spec;
- on read, decode UTF-8 and **fall back to cp1252** on `UnicodeDecodeError`,
  so a file already written by a broken build still yields its hand-edited
  keys, and the next write rewrites it as UTF-8. Self-healing, no manual
  cleanup, no migration note for users.

**How it was found, which is the transferable part.** Not by reading the code
— it had been read many times — but by adding `macos-latest` and
`windows-latest` to the CI matrix (commit `0a444dd`). Nine tests that assert
this exact save/load round trip had been **passing on Linux for the life of
the project** while the code was broken on another platform. They were not
bad tests; they were correct tests running only where the bug does not
reproduce.

Note the shape: this is the same failure as `test_ports_lists_something`
(§ Housekeeping in `TODO.md`) and the same as §21c's stale-cache false
negative. A test that never executes the failing configuration and a protocol
assumption that was never fired at hardware are the same defect wearing
different clothes, and this project has now produced three of them.

**The regression test had to avoid inheriting the bug.** The obvious test —
write a config, assert the bytes on disk are valid UTF-8 — **passes on Linux
with the bug still present**, because a UTF-8 locale produces a correct file.
Writing that test would have re-created the exact vacuity it was meant to
close. So `test_config_is_written_as_utf8_regardless_of_the_locale_codec`
monkeypatches `builtins.open` and asserts the call *names* its encoding, which
is checkable on any host regardless of locale. Verified to fail with the fix
reverted, on Linux.

**What the cross-platform matrix does and does not prove.** CI now runs the
full synthetic suite on Linux (3.11/3.12/3.13), macOS and Windows (3.11/3.13),
plus a smoke test of both console scripts. That covers install, entry points,
demo mode and every test. It proves **nothing** about talking to an E4XT from
macOS or Windows: hosted runners have no MIDI hardware. On both, `eoscli
ports` enumerated cleanly and returned empty lists — worth noting, because it
means CoreMIDI and WinMM construct fine even headless, and the
`MidiUnavailable` path (§ the `ports` fix) is in practice a Linux-container
condition rather than a general one.

**Two platform facts worth keeping, neither exercised here:**

- `python-rtmidi` 1.5.8 publishes wheels for CPython 3.8–3.12 only. On 3.13+
  pip builds from source **on every platform** — our own 3.13 Linux job
  installs `python_rtmidi-1.5.8-cp313-cp313-linux_x86_64.whl`, a locally built
  wheel, not a manylinux one. That is why the README now recommends 3.11/3.12
  rather than "3.11+".
- WinMM grants a MIDI port to one application at a time, unlike ALSA, which
  does not enforce exclusive access at all. On Windows the OS therefore
  enforces this project's one-session-at-a-time rule; on Linux nothing does,
  which is why `DISCLAIMER.md` has to say it in words.

---

## §25 — EOS has no disk surface at all, and what that costs the remote-load idea (resolved as a negative result, 2026-08-14)

Recorded because a negative result that is not written down gets re-derived,
and this one took a full command-table audit plus a manual search.

**The question.** Banks are staged onto HD images and mounted with a SCSI
emulator; the last manual step is walking to the E4XT to load one. Can a
disk be chosen, browsed, and loaded remotely — the way `s3ked` does it on the
Akai S3000?

**Answer: not over the documented protocol, and not by s3ked's method.**

**1. The editor protocol has no disk commands.** Full sweep of `Command` in
`eos/messages.py` (`01h`–`7Ah`): parameter edit/request/min-max-default, preset
and sample names, preset dump, memory/config/extended-config queries, the
"number of X" family, voice/zone/link utilities, sample erase and defrag,
preset copy/delete, multimode map, the three RAM erasers, and the NEW-dump
ACK/NAK. **Every one is RAM-scoped.** There is no drive selection, no volume
list, no directory read, no load, no save, no mount. This is not a gap in
eosed's coverage — it is absent from E-mu's specification.

**2. The manual agrees.** The EOS 4.0 manual documents no SysEx disk control.
The only documented hands-off load is **Auto Bank Load** (Master → Bank →
Auto, F2/F3): one designated bank, loaded at power-up, chosen at the panel.
Useful for a fixed rig — and if the auto-load pointer is left on one slot, the
*contents* of that slot can be changed remotely by rewriting the disk image,
making a power cycle a crude remote trigger. It is not browsing, and it was
not what was wanted.

**3. s3ked's technique does not port, for a structural reason.** On the
S3000, s3ked fires a load by writing the LOAD page's type-of-load register
(its §75/§93: writing 1 acts, 0 and 2–7 store and do nothing). That is only
half the feature, and the other half is *documented on the Akai*:
`RVOLLIST`/`VOLLIST` (`35h`/`36h`) return volume-list items and
`RHDDIR`/`HDDIR` (`37h`/`38h`) return harddisk directory entries. So on the
Akai the browse is a supported query and only the trigger needed reverse
engineering. **On EOS there is nothing to aim at**: both halves must come out
of the undocumented panel protocol (`F0 18 7F 00 00 …`, §3).

**4. What that implies about the order of work.** The display frame is the
blocker, not a refinement. Browsing a disk you cannot see is not browsing, and
button injection without screen readback means walking blind through menus
that also hold the erase utilities — on a machine whose destructive operations
are one-shot with no device-side confirmation. **Screen first, then
navigation, then the trigger.** The buttons look like the easy start and are
the wrong start.

**5. Harness.** `probes/panel_capture.py` is built and tested, and is
**passive by construction** — it never transmits. §3 forbids writing code
against byte sequences this project has not captured, and the only panel
sequences available are third-party fragments we have never verified, so a
prober that sent them would be breaking the rule it exists to serve. Instead
it listens while a human drives the device from its own front panel (an earlier
draft of this paragraph said it sniffs e-remote; that was the plan, not what was
done — see §3's correction):
timestamps frames, classifies panel vs editor vs other-E-mu (§4), takes typed
markers so the log records what the operator did, and diffs consecutive
same-length frames so the offsets that move stand out. `--analyse FILE`
reproduces the summary offline.

Two defects were found by *running* it against a synthetic log rather than by
reading it, both fixed and pinned by tests: the summary trusted a stored
`known` field instead of deriving the label from the bytes, so a capture that
did contain §3's handshake reported "no known fragments seen" — which reads as
the finding that the published bytes are wrong, the most expensive possible
wrong answer; and a truncated final line (what a Ctrl-C'd session leaves) took
the whole analysis down with a `KeyError`. Same lesson as §24: run the thing,
do not reason about it.

**6. Cheapest next step, which may close the item without any of the above.**
Point e-remote at the E4XT. It already mirrors the panel over this protocol.
If it works, the actual problem — the desk is several meters from the rack —
is solved with no protocol work, and eosed only needs a native pane if one is
wanted for its own sake. If it does not work, that is a finding worth having
before booking a capture session, and it is also §3's designated traffic
source, so either outcome moves the RE forward.

---

## §26 — Panel protocol captured live: §3's published frame shape is WRONG, and the display is a 240×64 bitmap (2026-08-14, E4XT Ultra fw 4.70)

First real capture of the panel/remote protocol. It corrects §3 on the most
basic fact — the frame header — and answers the question §3 listed as the
blocker, the display-frame encoding.

**Setup.** Chrome's WebMIDI exposes only `Midi Through` on this host, so
e-remote could not reach the interface directly. Bridged with:

    aconnect 14:0 56:3     # Midi Through -> E4XT MIDI IN
    aconnect 56:2 14:0     # E4XT MIDI OUT -> Midi Through

Note the **asymmetry**, which cost a diagnosis: this rig sends on
`ESI M4U eX MIDI 4` (56:3) and receives on `MIDI 3` (56:2) — different ports,
as `config.toml`'s cached `send_port`/`recv_port` pair records. Bridging 56:3
in both directions looks right and silently cannot work: replies arrive on
56:2 and never reach the bridge. This is also why `eoscli --port` can never
work on this rig — it uses one name for both directions — and why autodetect
caches a *pair*.

`--port` also defaults to device id 0 while this machine is id 5, so a forced
`--port` inquiry gets no reply and looks exactly like dead hardware. Two
independent reasons for the same symptom; neither was a fault.

### The frame header is not what §3 says

    §3 (third-party, unverified):   F0 18 7F 00 00 <cmd> … F7
    observed live:                  F0 18 7F 05 7A <cmd> … F7
                                             ^^ ^^
                                             |  designator 7Ah
                                             device id (5 = this machine's,
                                             as reported by Device Inquiry)

§3 states "device id fixed at `00`/`7F`". **It is a real device-id field**,
carrying the same id the editor protocol uses, and `7Ah` sits where §3 shows
`00`. None of §3's four published fragments appeared in the capture.

That is not necessarily a contradiction of the sources — they may be a
different firmware, a different EOS machine, or a different phase of the
handshake — but it *is* a demonstration of why §3's rule exists: the harness
was built matching §3's five-byte prefix and therefore classified **every real
panel frame as generic "sysex"**. It watched the protocol it was written for
go past and did not recognise it. Fixed by matching the three-byte
`F0 18 7F` and reading the device id as a field.

### Opcodes observed (byte 5)

| op | n | what |
|---|---|---|
| `40h` | 6 | **button down/up** — `40 <key> 00 <01=down\|00=up>` |
| `50h` | 3 | **display data** — 10-byte sub-header then a packed bitmap |
| `52h` | 3 | always immediately precedes a `50h` |
| `60h` | 3 | always immediately follows a button-down |
| `61h` | 3 | `61 7F 7F` |

The button layout was confirmed independently by the harness's own
length-diffing rather than by eye: across the six 10-byte frames, only offsets
6 and 8 ever varied — the key code and the down/up flag. Three distinct key
codes were seen (`68h`, `73h`, `6Eh`) for three deliberate presses.

`52h`/`60h`/`61h` are named from position and co-occurrence only, on one
capture, one machine, one firmware. Handles for reading a log, not facts.

### The display frame — solved

`50h` payload: a constant 10-byte sub-header (`01 01 00 00 00 00 70 01 40 00`
on every frame seen), then the screen as **standard MIDI 7→8 packed data**
(one MSB byte carrying the high bits of the following seven).

    full frame:  2195 septets  ->  1920 bytes  ==  240 × 64 / 8

**Exactly** the E4XT's 240×64 monochrome LCD, with nothing left over. Two
shorter `50h` frames (86 and 112 bytes total) followed screen changes, so
partial/delta updates exist as well — their region encoding is not yet known
and is the obvious next question.

Pixel *layout* within those 1920 bytes is still unsolved: a naive row-major
30-bytes-per-row render produces recognisable text-like structure but skewed,
so it is some other order (column-major pages, or interleaved halves — a
240×64 panel is commonly driven as two 120-wide or two 32-high halves).

### Pixel layout: row-major, 30 bytes per row, MSB = leftmost

Settled by rendering candidates and looking, rather than by argument. Strides
29, 31 and 32 shear progressively; **30 is horizontal**, which is also the
arithmetic answer (240 / 8). Within a byte, MSB-first and LSB-first are nearly
indistinguishable at this resolution and both read; the bit order inside the
7→8 MSB byte likewise. A row/half interlace was tried and is clearly wrong.

What comes out is unmistakably an EOS screen: three lines of text, one row in
inverse video (the selection), and soft-key labels along the bottom edge.
Glyphs are legible as glyphs but not yet crisp, so something small remains —
most likely a bit-order detail, or the captured frame being mid-update.

`probes/render_lcd.py` does the reconstruction and can emit the candidate
grid; it writes PNG with nothing but `zlib` and `struct`, so it adds no
dependency.

### The capture in this repo

`docs/captures/panel_e4xt_fw470_2026-08-14.jsonl`, complete — all 18 frames
including the three `50h` display frames with their pixel payloads.

It was first committed **with the pixel data stripped**, because an LCD bitmap
is a screenshot and CLAUDE.md bans committing commercial preset names in any
form, screenshots explicitly included. At that point the layout was not yet
decodable, so the content could not be verified as clean, and "probably fine"
is not the standard that rule sets. The author then confirmed nothing
commercial was on the screen, and the full capture replaced it.

Recorded because the order matters: the check came before the commit, not
after, and the answer that unblocked it came from the one person who could
actually see the machine. Re-capturing with a known pattern on screen is
still the fastest way to finish the pixel layout.

### Next — reordered by the 2026-08-14 scope decision (see TODO)

**SUPERSEDED 2026-08-16: the mirror was built (front-panel mode, `k`).** The
reasoning below stood at the time and is kept for the record. Two things
changed it. First, the mirror was built from this project's own captures of the
device echoing physical presses — not from e-remote's traffic, which was never
captured. Second, and the actual driver: The reason it was reversed is not that the objection stopped mattering. eosed exists to support mpc2emu, and the measurements mpc2emu needs -- stepping a parameter across its range, then reading back both what the machine SAYS it is and what comes out of the audio outputs -- cannot be automated without driving the panel and reading the screen. The mirror is measurement apparatus first; that it also happens to be useful at the desk is a by-product. The original text
follows.

The project will **not** build a screen mirror: that is Ray Bellis's e-remote
rebuilt from its own traffic, and while the protocol facts are E-mu's and §3
has always confined us to the wire rather than his code, cloning his tool is
not what this is for. The target is the s3ked shape — browse from the disk
*image* (already written off-device here, and parseable by mpc2emu/`emu3fs`),
and use this protocol only to select a bank and fire the load.

That inverts the ordering this section was originally written with. Decoding
the display to *browse* is off the table; confirming a known layout before
firing a destructive-adjacent action is still wanted, and is a much smaller
problem.

1. **Key-code table** — now the critical path. Press each panel key once in a
   recorded order with `probes/panel_capture.py` listening. Note this needs
   **no e-remote at all**: §3 records that the device echoes its own
   front-panel activity, so a human at the machine generates the traffic.
2. **Does it echo cold?** Determine whether the device emits panel activity
   unprompted or whether something must first open remote communication. If
   cold, the dependency on any third-party tool is zero.
3. **Navigation sequence to the disk pages**, deterministic and recorded.
4. **Enough display decoding to confirm state** — which page is showing,
   which item is selected — not enough to browse from. The pixel layout is
   already row-major/30-bytes-per-row; a re-capture with a known pattern on
   screen (a name field of `W`s vs blank) would finish the bit-order detail
   in one press if it turns out to matter.
5. `52h`/`60h`/`61h` by exercising them in isolation.

Direction is **not** recoverable from this capture: Midi Through carries both
ways on one port, so host→device and device→host are indistinguishable in the
log. Next session should capture the two directions on separate ports, or log
e-remote's output client separately.

---

## §27 — The device does NOT echo panel activity cold (2026-08-14, controlled test)

§26 planned the key-code capture around §3's statement that the E4XT echoes
its own front-panel presses, concluding the RE needed no third-party tool at
all. **Tested, and that conclusion was wrong.**

**Method.** Passive capture on `ESI M4U eX MIDI 3` (56:2, the device's MIDI
OUT) started *before* a power cycle, deliberately: e-remote had been connected
earlier the same day, and testing without a restart risks reading leftover
remote-mode state as an inherent property. Nothing transmitted at any point.
After boot the author pressed **F4 twice** (LOAD, then Merge).

**Result.** Eight messages, all at the power-on instant, none SysEx:

    80 00 40   ×8      (Note Off, ch 1) — boot chatter

The two F4 presses produced **nothing at all**.

This is a controlled negative rather than a silent one: the boot messages
prove the port, the cabling and the capture path all work, on the same run
that recorded no panel echo. Had the log simply been empty, "wrong port"
would have been the likelier explanation.

**Conclusion.** §3's echo claim is **conditional**: the device echoes panel
activity only once remote communication has been opened, not inherently. The
`F0 18 7F …` traffic in §26 was flowing because e-remote had opened the
session first.

**No front-panel escape hatch.** The EOS 4.0 manual documents no setting to
enable remote/panel communication. Its only mention of the capability is a
marketing line ("Emulators can be operated by remote control using an external
computer") and a pointer to E-mu's web site for the SysEx specification —
which is the *editor* protocol, already implemented here.

**So an "open" message is required, and we do not have it.** §3 publishes
`F0 18 7F 00 00 10 F7` for it, but §26 proved §3's frame *header* wrong, so
its opcode semantics cannot be trusted either. The shape-corrected guess would
be `F0 18 7F 05 7A 10 F7` — **do not send it on that reasoning alone.** An
unverified opcode in an undocumented protocol on a machine whose documented
protocol contains one-shot erase commands is precisely what §3's
capture-before-code rule exists to prevent, and the header being wrong is
direct evidence that this document's bytes do not describe this firmware.

**Options, in order of preference:**

1. **Ask Ray Bellis.** He published fragments of this RE voluntarily. The
   enable sequence is one question.
2. **One bounded capture of e-remote's *connect*.** Distinct from
   reimplementing his tool (ruled out, see TODO): observing a device's
   handshake once, on the wire, to learn a fact about E-mu's protocol. After
   that the browser is never needed again — everything else can be captured
   from the front panel, since echo works once the session is open.

**NEITHER OPTION WAS USED (§28).** The open message was constructed from the
published `10h` opcode with the header re-derived against this firmware, and it
worked first time. e-remote was never run.
3. **Probing opcodes blind** — rejected. Not worth it for a convenience
   feature on hardware this hard to replace.

---

## §28 — The session-open handshake, captured (2026-08-14). §3's opcodes were right; only its header was wrong

§27 established that the device is silent until remote communication is
opened, and that we did not have the message to open it. Captured now, on a
freshly power-cycled machine with nothing else having spoken to it, so this is
a complete cold open rather than a fragment of an existing session.

    t+0.000  F0 18 7F 05 7A 10 F7             host->device   OPEN
    t+0.006  F0 18 7F 7A 05 7F 11 00 08 F7    device->host   reply
    t+0.012  F0 18 7F 05 7A 60 F7             host->device
    t+0.018  F0 18 7F 05 7A 61 7F 7E F7
    t+0.028  F0 18 7F 05 7A 51 F7             host->device
    t+0.743  F0 18 7F 05 7A 50 <2205 septets> device->host   full 240x64 screen

**The open message is `F0 18 7F <devID> 7A 10 F7`** — `05` here being this
machine's SysEx device id, the same one Device Inquiry reports.

**§3 was half right, and the half it got right is the useful half.** Its
opcode `10h` for "enable remote communication" is correct, and the device's
reply carries `7F 11 00 08` — byte-for-byte §3's published "init handshake"
tail. What §3 got wrong was only the header: it records positions 3 and 4 as
`00 00` where this firmware uses `<devID> 7A`. Most likely its source machine
sat at device id 0 and the designator was mis-transcribed. The fragments are
genuine; their framing is not.

That is worth stating plainly because §26 rejected §3 wholesale on the
strength of the header mismatch, and that was an over-correction. The right
reading is narrower: **§3's opcode semantics are usable, its frame layout is
not.**

### A byte-order oddity, not yet a direction bit

The device's init reply is `F0 18 7F **7A 05** …` while everything else in the
capture — including the display frames the device itself sends — is
`F0 18 7F **05 7A** …`. So the swap is *not* a general host/device marker; it
appears only on this one reply. Recorded as an observation, not a rule.
Direction still cannot be recovered from a Midi Through capture (§26), because
that port carries both ways on one wire.

### Screen request opcodes differ by context

    §26 (after a button press):   60, 61 7F **7F**, **52**, then 50
    §28 (on session open):        60, 61 7F **7E**, **51**, then 50

`51h` vs `52h` and the final byte of `61h` both vary. The obvious hypothesis is
full-screen vs partial/region refresh, with `61 <a> <b>` carrying a region or
cursor coordinate — untested, one capture each, so treat it as a question to
design a probe around rather than a finding.

### What this unblocks

eosed can now open a session itself, without any third-party tool, using a
sequence this project captured rather than guessed — which is exactly what
§3's capture-before-code rule asks for. Once open, §27's result inverts: the
device *does* echo front-panel activity, so the key-code table and the whole
disk-load navigation can be recorded with a human at the panel and nothing
else in the loop.

The next step is therefore the first time this project **transmits** on the
undocumented protocol. That deserves its own small tool rather than being
bolted into the passive harness, whose never-sends property is worth keeping
intact.

### §28a — Provenance: the handshake was already public; the display format was not

Checked after the capture, because "did we take something that wasn't ours"
is a fair question and the answer turned out to matter.

**The handshake is prior public knowledge, published 2016.** The same
midimachines page §3 already cites publishes it outright:

| published there (2016) | captured here (fw 4.70) |
|---|---|
| `F0 18 7F 00 00 10 F7` — "enable communication" | `F0 18 7F 05 7A 10 F7` |
| `F0 18 7F 00 00 7F 11 00 08 F7` — sampler's answer | `F0 18 7F 7A 05 7F 11 00 08 F7` |
| `F0 18 7F 00 00 7F 11 06 04 F7` — key press, two per press (down/up) | `40 <key> 00 <01\|00>` |
| `F0 7F 18 00 00 11 F7` — close on losing foreground | not yet captured |

Same opcodes, different framing — which is the §28 reading confirmed from a
second direction. Note the published close message reads `F0 **7F 18**  …`,
manufacturer id and the 7Fh byte transposed relative to every other line on
that page; almost certainly a transcription slip, and worth capturing before
anyone writes code against it.

**The display format is not published there or anywhere else located.** That
page documents no screen sequences at all, and E-mu's specification covers
only the editor protocol. §26's decoding — 240×64 monochrome, MIDI 7→8
packing, row-major at 30 bytes per row — appears to be original to this
project.

**Why this settles the fairness question.** The session handshake is
third-party prior art about a manufacturer's protocol, not something taken
from e-remote itself; e-remote served as a traffic source for exactly one
capture of the *device's* behaviour, and none of its code was touched (§3's
standing rule). The one thing that would have been discourteous — rebuilding
its screen mirror — is ruled out on its own merits (TODO, 2026-08-14).

Attribution added to `LICENSE` alongside the E-mu specification and the
k2kremote/mpc2emu ports: midimachines for the opcodes, e-remote named as the
traffic source, and the display decoding claimed as original.

---

## §29 — eosed opened a panel session itself, and the first key codes (2026-08-14)

**The dependency is now zero.** `probes/panel_open.py` sent §28's captured
open message and the E4XT answered with the expected handshake:

    sent   F0 18 7F 05 7A 10 F7
    got    F0 18 7F 7A 05 7F 11 00 08 F7      (t+0.01s)

No browser, no third-party tool, no guessed bytes — a sequence this project
captured, replayed by this project. §27's finding (the device is silent until
a session is opened) is therefore not a blocker but a step, and everything
after it comes from a person at the front panel.

`panel_open.py` is deliberately separate from `panel_capture.py`: it is the
only thing here that transmits, and it transmits **exactly one frame, ever**.
The harness keeps its never-sends property intact so it can be pointed at
hardware without thought.

### Key codes, confirmed against a narrated press order

41 frames. The author pressed the soft keys in order, Preset Manage once, and
**Master twice between each soft key** to back out of whatever the previous one
opened — which is why `5Ch` appears in pairs throughout and is what made the
mapping unambiguous without markers.

| code | key | evidence |
|---|---|---|
| `58h` | Preset Manage | one press, narrated |
| `5Ch` | Master | 14 presses, always in pairs between soft keys |
| `62h` | F1 | press order |
| `64h` | F2 | press order |
| `66h` | F3 | press order |
| `68h` | F4 | press order — **and** independently in the §26 e-remote capture |
| `6Ah` | F5 | press order, then **confirmed in isolation** |
| `6Ch` | F6 | press order, then **confirmed in isolation** |

**The soft-key row is complete: EOS has six soft keys, F1–F6, and there are
six codes — `62h` to `6Ch`, stepping by 2.**

This entry first predicted `6Eh` = F7 and `70h` = F8 from the +2 step. **Both
are wrong: the machine has no F7 or F8 keys.** The step was real and the
extrapolation past the end of the physical hardware was not — a pattern
correctly observed and then run off the edge of the device it describes.
Corrected within the hour by the author, who owns one.

`6Eh` therefore is *not* F7. It appears in the §26 capture and remains
unidentified; whatever button it is, it is not a soft key. `70h` has never
been observed at all and was pure extrapolation.

F5 and F6 were then re-pressed **alone**, with nothing before, between or
after, precisely to separate confirmation from inference:

    t+211.99  40 6A 00 01   F5 down
    t+212.21  40 6A 00 00   F5 up
    t+215.41  40 6C 00 01   F6 down
    t+215.57  40 6C 00 00   F6 up

Clean, isolated, and matching the press-order reading exactly. That is the
standard the other four rows should eventually be held to as well; they rest
on a narrated sequence, which is weaker.

Codes are **physical**, labels are **contextual**: `62h` is that button
whatever the current page makes it do. This is what makes a deterministic
navigation sequence possible, and also why "press F3" is meaningless in this
protocol without knowing which page is showing — the reason a state-confirming
read of the display is still wanted even though browsing moved off-device.

Not all codes are even: the §26 capture contains `73h`, so the low bit is not
simply unused.

Frame shape, unchanged from §26 and consistent across all 40 press frames:

    F0 18 7F 7A 05 40 <keycode> 00 <01=down|00=up> F7

Note this is the `7A 05` byte order, not `05 7A`. Captured on the device's own
output port with only the open message ever sent the other way, so for
**buttons and the dial** the reading is solid: device→host is `7A <devID>`,
host→device is `<devID> 7A`, and both forms of `40h` have now been seen
(browser clicks in §26 carried `05 7A`, physical presses here carry `7A 05`).

**Corrected 2026-08-15 — this originally claimed direction was settled for the
whole protocol, and it is not.** The claim was drawn from a capture that
contains no `50h` display frames whatsoever. Every display frame this project
has ever recorded came from a Midi Through capture, where both directions
share one wire, and every one carries `05 7A` — the *host* marker. Read
literally that says the host sent the screen, which cannot be right.

So one of these is true and we do not yet know which:

* the byte pair is not a direction marker at all, and means something else
  that merely correlates with direction for `40h`/`43h`; or
* `50h` genuinely travels with the other pattern, for a reason not yet
  understood; or
* something in the Midi Through path reordered or re-originated those frames.

**The deciding experiment is cheap and has never been run:** listen on the
device's own output port (56:2 here, *not* the send port) while requesting a
screen, and see whether a `50h` arrives at all and with which byte order. One
capture settles it. Until then, do not build a display decoder that assumes
the answer.

One duplicated UP frame at t+92.01 (identical timestamp, identical bytes).
Not explained; not obviously harmful; noted so a later session that sees
doubled events has a precedent rather than a mystery.

Capture: `docs/captures/panel_keycodes_e4xt_fw470_2026-08-14.jsonl`. No display
frames in it, so nothing to scrub — the screen was never requested.

---

## §30 — Full front-panel key map, and the data dial is a different opcode (2026-08-15)

Captured with `probes/panel_open.py` holding a session open while the author
sat at the machine and named each button as it was pressed. No markers were
possible (both hands on the panel), so the narration *is* the marker track —
one message per key, matched to the frame that arrived between messages.

### Buttons — opcode `40h`

    F0 18 7F 7A 05 40 <keycode> 00 <01=down|00=up> F7

**32 codes observed directly.** Eight more are inferred and labelled as such.

| code | key | | code | key |
|---|---|---|---|---|
| `58` | Preset Manage | | `6C` | F6 |
| `59` | Sample Manage | | `6D` | Enter |
| `5A` | Preset Edit | | `6E` | Cursor Up |
| `5B` | Sample Edit | | `6F` | Cursor Left |
| `5C` | Master | | `70` | Cursor Right |
| `5D` | Disk/Browse | | `71` | Cursor Down |
| `5E` | Page Exit | | `72` | DEC |
| `5F` | Assignable 1 | | `73` | INC |
| `60` | Assignable 2 | | `74` | 1 |
| `61` | **unknown** — never pressed | | `75`–`79` | 2–6 *(inferred)* |
| `62` | F1 | | `7A` | 7 |
| `63` | Assignable 3 | | `7B` | 8 *(inferred)* |
| `64` | F2 | | `7C` | 9 |
| `65` | Audition | | `7D` | +/− |
| `66` | F3 | | `7E` | 0 |
| `67` | **unknown** — never pressed | | `7F` | . (set/shift) |
| `68` | F4 | | | |
| `69` | Page Prev | | | |
| `6A` | F5 | | | |
| `6B` | Page Next | | | |

Codes run `58h`–`7Fh` and **stop exactly at `7Fh`**, the top of the 7-bit
range. Nothing below `58h` was ever emitted, so either the panel has no other
keys or they live in an unexplored part of the space.

Two methodological notes worth keeping:

* **The number keys were not all pressed.** 1, 7, 9, 0, +/− and . were, and
  the ends were tested deliberately — testing a sequence at its *boundary* is
  what catches a break. It did: `0` is `7Eh`, not the `7Dh` a naive run would
  predict, because `+/−` sits between 9 and 0. Only after both ends and a
  midpoint landed were 2–6 and 8 inferred.
* That discipline exists because of §29's mistake, where a real +2 step was
  extrapolated into two keys the machine does not have.

### Data dial — opcode `43h`, not a button at all

    F0 18 7F 7A 05 43 01 <lo> <hi> F7

One frame per movement, **no down/up pair**. The payload is a signed delta,
**14-bit two's complement, least-significant septet first**:

| observed | value |
|---|---|
| `01 00` | +1 |
| `02 00` | +2 |
| `03 00` | +3 |
| `7F 7F` | −1 |
| `7E 7F` | −2 |
| `7D 7F` | −3 |

**It coalesces.** Spinning fast does not raise the frame rate — the minimum
observed gap is 32 ms, about 30 frames/sec — it raises the magnitude. So a
client must treat the field as an accumulating delta and never as "one click
per message", and a *driver* presumably may send >1 to move several steps in
one frame. Untested in that direction.

The `01` at position 6 is presumed an encoder or axis id; the E4XT has one
dial, so nothing distinguishes it yet.

### What this unblocks

Navigation is now expressible: every key needed to walk to the disk pages and
select an item has a code — Disk/Browse, the cursor cluster, Page Prev/Next,
Enter, Page Exit to back out, and the dial for fast list movement. Combined
with §28's session open, a deterministic sequence can be *written*; what is
still missing is confirmation that the machine is on the page the sequence
assumes, which is the narrow use the display frame (§26) is still wanted for.

Capture: `docs/captures/panel_keymap_e4xt_fw470_2026-08-15.jsonl`. No display
frames were requested, so there is nothing to scrub.

---

## §31 — A text LCD readout without e-remote: feasible, and what it actually needs (planned, 2026-08-15)

The question: can eosed show the E4XT's screen as *text*, the way k2kremote
shows the K2000's, using only this project's own reverse engineering?

**Yes in principle, and the dependency is already zero** — but it is a
different and larger job than k2kremote's, for one reason that is worth being
precise about.

### Why this is not the same job as k2kremote's

k2kremote reads the K2000's screen as **characters**: that protocol carries
text, so rendering it as text is transcription. EOS carries the screen as a
**bitmap** — 240×64 monochrome, 7→8 packed, row-major at 30 bytes per row
(§26). There is no character data anywhere in the frame. A text readout
therefore requires recognising glyphs from pixels.

That sounds worse than it is. The device has one fixed ROM font, so this is
not OCR in the hard sense: every glyph is a fixed bitmap at a fixed cell size,
so recognition is an exact dictionary lookup on a cell's bit pattern, not a
classifier. Build the dictionary once and it is deterministic forever.

### What we already have, all of it ours

* Opening a session — `F0 18 7F <devID> 7A 10 F7`, captured (§28) and
  implemented in `eos/panel.py`. No browser needed.
* The screen's encoding — packing, dimensions and row order (§26).
* A renderer that reconstructs the bitmap (`probes/render_lcd.py`).
* The ability to *drive* the panel, so a known string can be put on screen
  deliberately (§30 key map) — which is exactly what a font table needs.

### What is missing, in order

1. **Confirm which opcode requests a screen, and from where it arrives.**
   `51h` and `52h` both precede a `50h` (§28, §26), and `60h`/`61h` are in the
   same conversation, but all of that was observed on Midi Through with the
   host and device sharing a wire. This also blocks the direction question
   §30 now flags as unresolved. One capture on the device's *output* port
   while we send a request settles both.
2. **A font table.** Drive the panel to a screen whose text is known exactly —
   a preset name field we set ourselves — capture the bitmap, and cut it into
   character cells. The cell grid falls out of the geometry: 240 px wide with
   a typical 6 px advance is 40 columns, 64 px tall with an 8 px line is 8
   rows, which matches the four-to-five text lines EOS screens actually show
   with room for the inverse-video bars. Confirm rather than assume.
3. **A cell→character dictionary**, built by rendering known strings and
   recording each cell's bit pattern. Unknown patterns render as `?` and are
   a signal to capture more, never a guess.
4. **Inverse video.** EOS marks the selection by inverting a run of cells, so
   a cell and its inverse are the same glyph in different states. Detect it
   as a property of the cell, not as two separate glyphs, or the dictionary
   doubles for no benefit.

### Why this does not reopen the scope decision

The 2026-08-14 decision was **no screen mirror**, because rebuilding
e-remote's graphical panel from its own traffic is poor form. A text readout
derived from our own decoding is a different artefact: it is the k2kremote
idiom, it is what a TUI can actually use, and — the deciding point — it is
built from a font table this project derives by driving the machine itself.
Nothing in it is taken from anyone else's tool.

It is also the thing that makes the disk-load feature safe rather than blind:
"confirm the machine is on the page this sequence assumes" needs perhaps two
lines of text, not a picture.

**Do not start at step 2.** The font work is the fun part and the useless one
if step 1 comes back saying we cannot request a screen on demand.

---

## §32 — The display encoding was wrong in §26, and the right one reads cleanly (2026-08-15)

§26 decoded the `50h` payload as **MIDI 7→8 byte packing** (one MSB byte
carrying the high bits of the next seven) and reported the result as settled
because the arithmetic landed exactly:

    2195 septets × 7/8  ->  1920 bytes  ==  240 × 64 / 8

**That was a coincidence, and it is the reason the error survived a day.**
The rendered picture sheared progressively across the screen — text lines
drifting a row every twenty-odd columns — and that was misread as a *layout*
problem (row-major vs column pages, stride 29/30/31/32, interlaced halves)
because the size arithmetic seemed to rule out a *packing* problem.

The actual encoding is simpler: **a plain bitstream, seven bits per byte,
most-significant bit first.**

    2195 septets × 7 = 15365 bits, for 15360 pixels, 5 bits of tail padding

No packing, no MSB byte, no groups. Decoded that way the screen comes out
square, and the capture from 2026-08-14 reads:

    ┌────────────────────────────────────────────┐
    │ Drive : D1 ZuluscsiCDROM                   │
    │ Folder: F000 Default Folder                │
    │ Bank  : B000 <bank name>       [inverse]   │
    └────────────────────────────────────────────┘
      [Cancel]          [Merge]          [Load]

with **LOAD** set vertically down the left edge. That is the disk-load page —
the exact screen this whole line of work exists to reach.

**The lesson, which is the transferable part:** a decoding that produces the
*right size* is not thereby the right decoding. Size is one constraint and a
weak one; geometry is the strong one. `tests/test_lcd.py` now asserts on
geometry instead — the dialog's own horizontal rules must come out as long
unbroken runs, which a sheared decode cannot satisfy and a wrongly-sized one
never gets the chance to.

### Rendering it in a terminal, cheaply

No kitty graphics protocol, sixel or image escape needed:

* **half-blocks** (`▀▄█`, two vertical pixels per cell) → 240×32 characters,
  horizontal pixels 1:1, and the device's 1-pixel font strokes stay separate.
  The legible choice, at the cost of needing a wide terminal.
* **braille** (U+2800, 2×4 pixels per cell) → 120×16 characters, correct
  aspect and compact, but the thin strokes merge into neighbouring dots and
  it reads as texture more than type.

Both are in `eos/lcd.py`. Half-blocks is the one to default to.

### What this does *not* settle

Direction (§30's correction) is still open: every `50h` we hold came from a
Midi Through capture. Requesting a screen on demand is still unconfirmed, and
remains the next hardware step before any of this becomes a live pane.

---

## §33 — Screens can be requested on demand, and the byte pair is NOT a direction marker (2026-08-15, live)

The experiment §30-corrected and §31 both said had never been run. Captured on
the device's **own output port** (`56:2`), with this project's own sends going
the other way on `56:3` and nothing else on the wire -- so unlike every
previous display capture there is no Midi Through ambiguity about who sent
what.

Sent the session open (§28), then one candidate opcode at a time:

| sent | device replied |
|---|---|
| `51h` | **2212-byte `50h` — a full screen** |
| `52h` | 2212-byte `50h` — a full screen |
| `60h` | `61h 77 7E` — a short reply, payload differs from the `7F 7E` seen in §28 |
| `61h` | nothing |

**`51h` requests a screen.** Repeatable, immediate, no preconditions beyond an
open session.

**`52h` is the delta request — see §33a.** This section originally said the
two were indistinguishable, which was true of the experiment and not of the
device: the two requests were sent back to back with nothing changing in
between, so a full response and a "nothing new" response would look the same.
Prompted to re-run it with a real screen change in the middle, they separate
immediately.

`61h` produced nothing when sent, consistent with it being a device->host
reply rather than a request. `60h` appears to *ask* for whatever `61h` carries.

**Measured 2026-08-18 — the two payload bytes track the SELECTED MODE, and the
cursor-position guess was wrong.** Walking the mode buttons and querying `60h`
after each:

    mode            byte6  bits      bit cleared
    Preset Manage    0x3E  0111110       0
    Sample Manage    0x3D  0111101       1
    Preset Edit      0x7B  1111011       2
    Master           0x6F  1101111       4

**Active low: each mode clears its own bit in byte 6.** Reproducible — Sample
Manage returned `3d 7e` on both visits, Preset Manage `3e 7f` on both. Bit 3 is
presumably Sample Edit, not exercised separately. What the bits ultimately
drive is not established here; that they index the mode selection is.

### The byte pair is opcode-correlated, not directional

The display frame arrived on the device's own output port carrying `05 7A` —
the pattern §30 originally called "host->device". It cannot be: nothing but
this project was transmitting, and we did not send a 2212-byte screen.

So the correction in §30 was right to withdraw the claim, and this settles
what is actually true:

    7A 05   handshake reply (7Fh), button echo (40h), data dial (43h)
    05 7A   display data (50h), the 61h reply

**Both sets contain device->host traffic.** The pair varies with the *message*,
not with the direction of travel. §26's original confusion is fully explained
by this, and any parser must accept either ordering per opcode rather than
inferring direction from it -- which `eos.panel.parse_button` already does,
for the weaker reason that it had seen both.

### The whole loop, demonstrated

Open session -> send `40h` PAGE_EXIT (down, up) -> send `51h` -> decode the
`50h` reply. The screen changed, confirming that eosed can **drive the panel
and read the result back**, entirely through this project's own captures and
with no third-party tool in the loop at any point.

That is the last structural unknown for the disk-load feature. What remains is
sequencing, not protocol: walk to the disk pages by key, request a screen to
confirm the page, then fire. The state-confirmation step §31 wanted is now
buildable.

### Still open

* Whether `51h` and `52h` differ, and what `61h`'s two payload bytes mean.
* The short `50h` frames (86 and 112 bytes) from §26 -- presumably partial or
  region updates, still not decodable, and `eos.lcd.is_partial` refuses them
  rather than rendering a fragment as a whole screen.


### §33a — `51h` is full, `52h` is delta, and nothing is ever pushed (2026-08-15)

Re-run of §33's request test with a screen change deliberately placed between
the requests, because the first run could not have told a full response from
an empty delta:

    51h on a quiet screen              -> 2212 bytes (full)
    52h on a quiet screen              -> 2212 bytes
    52h again, still quiet             ->   86 bytes
    [CURSOR DOWN pressed]              -> no unsolicited frame at all
    52h right after the change         ->   86 bytes
    52h again                          ->   86 bytes
    51h after the change               -> 2212 bytes (full)

**`51h` always returns a full screen** -- three for three, regardless of what
came before it. That is the one to build on: a client that wants to know what
is on the display asks with `51h` and decodes the answer, with no dependence
on device-side state it cannot see.

**`52h` is an update request.** It falls to 86 bytes once there is nothing new
to send.

> **CORRECTED 2026-08-18.** The line above reading `52h right after the change
> -> 86 bytes` is unsound: the "change" was a CURSOR DOWN that was never checked,
> and re-running it today with the screen hashed before and after shows
> `CURSOR_RIGHT` on that kind of page alters **zero pixels**. The screen almost
> certainly never moved, so 86 bytes was the correct "nothing new" answer to a
> question nobody had changed the answer to.
>
> Re-measured with the change verified — a page toggle altering 3206 pixels:
>
>     52h, first call after a 51h        -> 2212 (full)
>     52h again, nothing changed         ->   86
>     52h after a VERIFIED 3206 px change-> 2212 (full)
>
> **So `52h` returns a FULL screen whenever anything has changed, and 86 bytes
> when nothing has.** It is a conditional full transfer, not a delta, and it
> keeps its own "what have I sent" state independent of `51h` — the first `52h`
> after a `51h` returns full.
>
> Consequence: **the 86-byte frame is a no-change reply, not a partial update.**
> The inference below, that 86 and 112 identify partial region updates, does not
> follow for 86. The 112-byte frame has not been reproduced in any of these
> tests and remains unexplained. `eos.lcd.is_partial` still refuses both, which
> is right either way.

Their region encoding is still unknown, and
`eos.lcd.is_partial` continues to refuse them rather than render a fragment as
a whole screen.

**The device never pushes.** Pressing a key produced *no* unsolicited `50h`.
§26's capture shows display frames following button presses, but there is a
`52h` immediately before every one of them -- e-remote was polling, and the
frames were replies. Any client must ask; the screen is not sent to it. That
also means a live pane needs a poll loop with a chosen interval, and the cost
of a full `51h` (2212 bytes at MIDI speed, ~0.7 s in §28's capture) is what
sets how fast that can reasonably run.

Worth recording how this was found: the first experiment was run, reported,
and *believed*, and it was the reader asking "would two different requests
really give the same reply -- did you change menus in between?" that exposed
it. The result was not wrong so much as uninformative, which is harder to
notice than a wrong one, because the data looked clean.

### §33b — What the refresh strategy should be, measured (2026-08-15)

Round-trip cost, request to complete frame, measured twice each:

    51h full     2212 bytes    716 ms
    52h delta      86 bytes     70 ms

716 ms is most of a second of MIDI wire time, on the same link that carries
keypresses -- so continuously polling for full screens is out. It would also
delay every button the user pressed behind an in-flight screen transfer.

**`52h` is a usable change detector**, which is what makes a cheap poll
possible. Provoking a real change and asking:

    after MASTER (page switch)   52h -> 2212 bytes,  screen ink 2863 -> 2631
    after PAGE NEXT              52h ->   86 bytes,  ink unchanged
    after CURSOR DOWN            52h ->   86 bytes,  ink unchanged

86 bytes means nothing changed. And when something did change, `52h` returned
a **full, decodable frame** rather than an undecodable fragment -- so in the
common case the cheap request also delivers the answer, and no follow-up full
request is needed at all.

(PAGE NEXT and CURSOR DOWN did not alter this particular page, which is why
they read as no-change. That is the device being honest, not the detector
failing: the ink total confirms the screen really was identical.)

**The design that follows:**

1. **Poll `52h`**, not `51h`. At 70 ms a poll, twice a second is ~14% of the
   link and feels immediate.
2. **86 bytes -> do nothing.** No decode, no repaint, no cost.
3. **A frame large enough to decode -> use it directly.** This is the common
   case for real changes and costs one request, not two.
4. **Anything in between (the 112-byte case from §26) -> escalate to `51h`.**
   Partial-region frames are still undecodable, so buy a full screen rather
   than render a fragment.
5. **Pause polling while sending keys**, so a burst of presses is not queued
   behind a screen transfer.
6. **Keep a manual force-refresh**, because every automatic scheme eventually
   disagrees with reality and the user needs a way to say "just ask again".

This answers all three options together: full at the start *and* on demand,
delta as the poll, and a refresh key -- not as alternatives but as the roles
each request is actually suited to.

The cost of being wrong here is asymmetric and worth stating: polling too
hard makes the panel sluggish in a way that looks like the protocol being
slow, while polling too gently just means the screen lags a beat behind.

### §33c — Why the partial frames are still undecoded, honestly (2026-08-15)

Earlier sections said the region encoding of the short `50h` frames was
"unknown", which implied it had been examined and resisted. It had not been
examined. Corrected here, with what looking actually found.

**The sub-header is a rectangle, and it is the same in every frame.** Read as
14-bit LSB-first pairs, `01 01 00 00 00 00 70 01 40 00` is:

    [129] [x=0] [y=0] [w=240] [h=64]

240 and 64 are exactly the screen dimensions, which is unlikely to be
coincidence. But the 2212-, 112- and 86-byte frames all carry **identical**
sub-headers, so whatever distinguishes a partial from a full screen is not
there.

**The short payloads are not raw bitmaps.** 69 septets is 483 bits against the
15360 a screen needs, so they are encoded or compressed. Both are dominated by
runs of `7F`, and the 112-byte frame visibly repeats a
`58 44 56 11 15 44 25 3?` group three times -- the shape of run-length coding,
or of repeated identical scanlines.

**What blocked going further was provoking one.** A delta can only be read
against known ground truth: capture a full screen, change something small,
capture the delta, capture the full screen again, and diff. Six keys were
tried (cursor left/right, INC, DEC, page prev/next) and **every one changed
exactly zero pixels**, returning an 86-byte reply each time. The device was
sitting on a page where none of them do anything.

That failure is worth keeping for two reasons. It is a clean six-for-six
validation that **86 bytes means no change** -- confirmed against pixel-level
diffs of the full screens either side, not inferred from size alone. And it
shows the real obstacle is not the encoding but reaching a screen where a
*small* change is possible: everything that did change (a page switch) came
back as a full 2212-byte frame instead.

**Next attempt should navigate to an edit page first** -- somewhere with a
value field and a cursor -- and change one character. A blinking cursor, if
EOS has one, would produce a small delta continuously and hand over as many
samples as anyone could want.

Until then `eos.lcd.is_partial` refuses these frames and `classify_update`
escalates them to a full `51h`, which is correct behaviour under uncertainty
and costs one extra request in a case that appears to be rare.

### §36 — The numeric keys do work; two things that make them look like they do not (2026-08-16)

Reported as "the number keys do not work for selecting a preset -- typing
012 ENTER jumps to P012 on the hardware". They do work, and finding that out
turned up a real concurrency defect next door.

**The keys and codes are correct.** Driving `0 1 2 ENTER` at the device
produces exactly `7Eh 74h 75h 6Dh`, the display changes as the digits are
typed, and ENTER commits it -- verified by reading the screen back either
side. Note this incidentally exercises `75h` (digit 2), one of the codes §30
marked *inferred* rather than observed, and it behaves.

**First trap: the page.** Numeric entry only does anything where the machine
itself accepts it. On Preset Manage, typing digits changes the display
immediately. On the Master/Memory page it does nothing at all -- exactly as
pressing those keys on the front panel would. A first attempt at reproducing
this "failed" purely because the device was left on a page with no numeric
field, which looks identical to a broken key map.

**Second trap, and the real bug: two threads, one wire.** In the app the
screen poll runs in a worker thread and sends under `_bridge_lock`, while a
keypress went straight to `midi_out.send_message()` from the UI thread with
no lock at all. `ThrottledOut` imports no threading and guards nothing.

So a keypress could be emitted in the middle of a poll's screen transfer.
That is not a rare window: the poll fires every 500ms and a full `51h` takes
716ms (§33b), so the port is busy for a large fraction of wall time, and
interleaving two SysEx streams on one ALSA port is a good way to lose one.

Fixed by routing panel sends through the same lock. Worth noting the shape:
the lock was added for the *poll* when it was written, and the send path --
older, and correct while it was the only writer -- was not revisited when a
second writer appeared. Nothing failed loudly; it just intermittently did
nothing.

**What is still true and worth telling a user:** the panel drives the
device's own UI. Typing a preset number there moves the *machine*, not
eosed's preset browser, and on a page with no numeric field it does nothing
-- both exactly as the hardware behaves.

## §34 — Remote disk browse and load, live; and a pitch experiment that had to be thrown away (2026-08-17, E4XT Ultra)

§25 concluded that "EOS has no disk surface at all". That is still true of the
**editor** protocol and should stay on the record as such. It is not true of
the device: driven over the **panel** protocol, with the display decoded per
§32, the whole disk subsystem is readable and drivable from the desk. This is
the thing the project was started for — choose a disk, browse it, load from
it, without walking to the rack.

### What the disk pages actually offer

`DISK_BROWSE` (`5Dh`) toggles between the DISK page and the browse page. On
the DISK page the soft keys are:

| key | function |
|---|---|
| F1 | `Utils▲` |
| F2 | `Browse▲` — submenu: Drives / Folders / Banks / Presets / Samples / More▲ |
| F3 | `View` — toggles icon grid ↔ list |
| F4 | `Load...` |
| F5 | `Save...` (greyed on read-only media) |
| F6 | `Info...` |

The rig showed D0 (a writable FAT hard drive), D1/D3/D4/D5/D7 (CD-ROM images),
D8 (a real Quantum Fireball) and D9 (floppy).

`Info...` on a **bank** gives slot number, type and total size. `Info...` on a
**sample** gives index, type and channel, length in samples, duration, `Srate`,
loop points and size.

### A bank's sample rates are readable without loading it

Browse -> Samples is scoped to **the bank under the cursor**, not the whole
drive — numeric entry clamps at the bank's last sample, which is also how you
discover its sample count. Combined with the sample `Info` popup, that means
a bank's entire rate profile can be surveyed straight off the disk before
spending the minutes a Load costs. Two 100 MB-class banks were surveyed and
skipped this way in the time one of them would have taken to load.

Automating it is worth the small effort: open Info, grab, dismiss, step, and
stack only the changing rectangle of the screen into one image. Twenty popups
read in one glance rather than twenty screenshots.

Two traps found the hard way, both of which produce *plausible wrong output*
rather than an error:

- **Dialog parity.** A popup left open by a previous run inverts every
  subsequent open/dismiss: each "open" dismisses, the cursor never moves
  because the modal eats it, and you get N identical shots of the page
  underneath. Probe for the dialog before starting rather than assuming a
  clean screen.
- **Detecting the dialog on the wrong row.** Sampling one row inside the
  popup border finds its white interior and reports "closed" for an open
  dialog. Look for the border's long unbroken black run.

### Load *does* confirm — except when there is nothing to destroy

An earlier note in this session claimed `Load...` fires immediately with no
confirmation. **That was wrong**, and it was wrong in the unsafe direction, so
it is corrected here rather than quietly amended. Load raises:

```
?  Destroys current RAM bank... continue?
   Cancel (F1)        Merge (F4)        Load (F6)
```

The first observed load skipped the dialog because RAM was **empty** — there
was nothing to destroy. With a bank resident, the dialog always appears.
`Merge` is a genuine third option: it adds to the RAM bank rather than
replacing it.

### An editor-protocol parameter write does not reach the sounding preset

The spec says a remote edit goes to a buffer the front panel does not reflect
until the preset is touched. Demonstrated rather than quoted: setting
`E4_PRESET_VOLUME` to -18 dB read back as -18 dB and did not move the audio by
a single sample. The consequence for any live experiment is sharp — a layered
voice **cannot** be muted from here to isolate another one.

### Two small live facts

- `MASTER_AUDITION_KEY` (id 271) is in the spec's parameter table; this E4XT
  never answers a read of it. Both `eoscli get 271` and a bridge read time out.
- The device's `MIDIGLO_BASIC_CHANNEL` is **4** (MIDI channel 5) on this rig.
  An earlier "the device makes no sound" scan tried channels 1, 2, 3, 4 and 16
  and was wrong for two independent reasons at once: RAM was empty *and* the
  channel was never tried.

### The pitch experiment, and why it was thrown away

The goal was to establish whether EOS honours a sample's stored rate on
playback — a question the sibling mpc2emu project's E4B writer rests on. Bank
B02 on D0 is the right vehicle: 6.0 MB, with samples at ~31524/31969/32103/
32144 Hz alongside ~44001/44053/44100 Hz. P000 V0 plays sample 1 (31524 Hz) at
root MIDI 50; P011 V0 is a single-voice, single-zone preset playing sample 44
(44100 Hz) at root MIDI 60. Uncompensated, the low-rate sample would sound 581
cents out — unmistakable.

The measurements came back 0.6 cents apart, which reads as a clean pass.

**It was an artefact.** The two spectra shared harmonic amplitude ratios to
three decimal places, which two different instruments do not do. Playing the
*same* note on both presets produced recordings identical to the last digit:
**Program Change never changed the preset**. One preset had been measured at
two keys, which tracks the interval exactly and says nothing whatever about
rate compensation.

The lesson is cheap to state and was nearly expensive: **verify that the
preset actually changed before trusting any measurement that depends on it.**
An A/B where A and B are secretly the same thing does not fail loudly; it
returns a beautiful number.

Note also the limit that survives even a perfect run of this experiment: in
machine-written material the stored rate at `[54-57]` and the pitch offset at
`[58-59]` **agree**, so the device's own files cannot separate which of the two
it reads. Only a file where they disagree can.

### Device left in a wedged state — for the record

By the end the E4XT would sound notes normally and on pitch, while ignoring
Program Change and neither answering nor acting on SysEx. Device Inquiry timed
out with the MIDI interface otherwise completely silent, so bus contention was
ruled out by test, as was a stale port binding (ports here resolve by full
name, which fails loudly rather than silently, and the same binding had worked
for hours).

The theory at the time was a **modal dialog** left open on the front panel:
the display was unreadable by then — the screen is fetched over the same SysEx
path that had gone quiet — and numeric jumps were being sent to pages inferred
rather than verified. EOS modals block preset changes, so one cause covered all
three symptoms.

**That theory is contradicted by the only direct observation of the machine.**
Jan looked at it the following morning before powering it down: it was sitting
on Preset Manage or Sample Manage, an ordinary page, with nothing strange on
screen and no dialog. A modal would have been visible.

So the cause is **unknown and no longer recoverable** — the power cycle took
the evidence with it. What the symptoms actually describe is a device whose
voice engine kept running while its MIDI/SysEx handling stopped: notes were
still parsed and sounded, while Program Change and SysEx were neither answered
nor acted upon. That is a partial firmware wedge rather than a busy machine,
and it has a family resemblance to the fatal "Gen Trap" fault recorded in
TODO.md under unattended automation — same conditions (hours of unattended
driving, sustained SysEx traffic with 2212-byte screen replies polled
continuously), milder outcome.

Recorded as unexplained rather than closed. If it recurs, the thing to capture
*before* power-cycling is the front panel's own state and whether the device
still answers a Device Inquiry after a MIDI reset — neither was available this
time.

No blind keypresses were sent to clear it, and none should be. The Utils menus
carry Erase RAM Bank/Presets/Samples with no second confirmation, and
dismissing an unknown modal blind is precisely how one of those gets
confirmed. Nothing on disk was written — no Save, no Erase, no Delete — and
the loaded bank came off read-only media.

**Operational rule this earns:** once the display stops answering, panel
driving stops too. The panel protocol is only safe while you can see what you
are pressing.

## §35 — Which field EOS actually reads for playback pitch: `[58-59]`, settled by a mirror pair (2026-08-17, live)

The question §34 could not answer, and neither could PITCHCHK as built: a
sample header carries BOTH a stored rate at `[54-57]` and a pitch offset at
`[58-59]`, and in every machine-written file — and in a correctly written one
— the two AGREE. Agreement is exactly what makes a file useless for
attribution. To find out which field the machine obeys, the two have to
contradict each other.

### The instrument

Two banks built by editing six bytes of a known-good file (mpc2emu's
PITCHCHK.E4B), so the PCM is byte-identical throughout — a C4 tone whose
samples were laid down at 27500 Hz. Only the metadata differs:

| bank | `[54-57]` rate | `[58-59]` offset | what each field claims |
|---|---|---|---|
| PITCH_A | 27500 | 0 | rate says compensate, offset says don't |
| PITCH_B | 44100 | -523 | rate says don't, offset says compensate |

Mirror images, so exactly one must come out 817.5 cents sharp
(44100/27500 = 1.6036). Which one names the field. Being a within-file
equality test, the capture chain's own tuning drops out.

### Result

Chain calibrated first against CD3-PITCHCAL (three sine tones whose correct
answer is known by construction): **-0.8, -0.8, -0.6 cents** at 440/220/110 Hz.
Pure sines also validate the *estimator* — harmonic-rich material had been
making autocorrelation lock an octave low.

| played | expected if rate authoritative | expected if offset authoritative | measured |
|---|---|---|---|
| PITCH_A P001 @ MIDI 72 | 523.25 Hz | 839.1 Hz | **838.84 Hz (+817.1 cents)** |
| PITCH_B P001 @ MIDI 72 | 839.1 Hz | 523.25 Hz | **523.25 Hz (-0.0 cents)** |

Both 44100 Hz controls read -0.9 and -0.7 cents, matching the calibration.

**`[58-59]` is authoritative for playback pitch.** Both banks followed the
offset and ignored the stored rate, in opposite directions, to within half a
cent of prediction.

### `[54-57]` is not ignored — it drives the DISPLAY

Same PCM, same frame count, different rate field, read off Sample Manage:

- PITCH_A S002: `2.00secs, left, 27500Hz`
- PITCH_B S002: `1.24secs, left, 44100Hz`

55001 frames / 27500 = 2.00 s; / 44100 = 1.247 s. So the machine reads both
fields and uses them for different things: `[54-57]` for the reported rate and
duration, `[58-59]` for what you actually hear. "Informational" was the right
word for pitch purposes and the wrong word for the field generally.

### Two traps this run walked into, both worth keeping

**Program Change is page-dependent.** It is honoured on the main preset page
and IGNORED on Preset Manage / Sample Manage. Two measurements taken while it
was being ignored came back identical to each other — the §34 failure exactly,
reproduced within a day of writing it up. The fix that holds regardless: step
presets with the panel's own INC key and verify on the LCD, since selection
and proof-of-selection then come from the same place.

**A voice's zone is not its root key.** PITCHCHK's two presets are both rooted
at MIDI 60 but their zones are C3-C3 and **C4-C4** — so the second preset is
silent at MIDI 60 and only sounds at MIDI 72. That silence read as "the preset
makes no sound", which nearly became a finding about rejected metadata. It was
a key range. Read `E4_GEN_KEY_LOW`/`KEY_HIGH`, not just `E4_GEN_ORIG_KEY`,
before concluding anything from silence.

Incidentally the zone split is what makes the pair self-verifying: the control
only answers at 60 and the test only at 72, so sound at both proves the preset
changed without needing the display at all.

## §36 — The filter-type table confirmed, the E4B byte that feeds it is a grouped code, and a walk that pressed Load (2026-08-18, live)

Section B11 of `HW_CHECKLIST.md` is closed, the route to the page that closes
it is not the one the manual implies, and the program written to map that
route pressed something it should not have. All three are worth recording.

### B11: `id == list position` is now OBSERVED, 16 of 16

`eos/params.py`'s `FILTER_TYPE_NAMES` carried the caveat "still an assumption,
not a hardware-confirmed fact: id == list position". Confirmed against the
machine's own display, using the sibling project's 98-preset anchor bank:

| byte | runtime | our table (manual prose) | machine display | |
|---|---|---|---|---|
| 0x00 | 1 | 4-Pole Lowpass | `4 Pole Low-pass` | exact |
| 0x02 | 2 | 6-Pole Lowpass | `6 Pole Low-pass` | exact |
| 0x08 | 3 | 2nd Order Highpass | `2nd Order High-pass` | exact |
| 0x09 | 4 | 4th Order Highpass | `4th Order High-pass` | exact |
| 0x10 | 5 | 2nd Order Bandpass | `2nd Order Band-pass` | exact |
| 0x11 | 6 | 4th Order Bandpass | `4th Order Band-pass` | exact |
| 0x12 | 7 | Contrary Bandpass | `Contrary Band-pass` | exact |
| 0x20 | 8 | Swept EQ, 1-octave | `Swept EQ 1 octave` | exact |
| 0x21 | 9 | Swept EQ, 2->1-octave | `Swept EQ 2->1 oct` | **abbrev** |
| 0x22 | 10 | Swept EQ, 3->1-octave | `Swept EQ 3->1 oct` | **abbrev** |
| 0x40 | 11 | Phaser 1 | `Phaser 1` | exact |
| 0x41 | 12 | Phaser 2 | `Phaser 2` | exact |
| 0x42 | 13 | Bat Phaser | `Bat-Phaser` | exact |
| 0x48 | 14 | Flanger Lite | `Flanger Lite` | exact |
| 0x50 | 15 | Vocal Ah-Ay-Ee | `Vocal Ah-Ay-Ee` | exact |
| 0x51 | 16 | Vocal Oo-Ah | `Vocal Oo-Ah` | exact |

14 exact, 2 abbreviated, **0 disagreements**, reproduced independently by the
sibling project's own joiner after three bugs were fixed in it.

**A literal string comparison would have reported 16 mismatches on a table
that is entirely correct.** The machine hyphenates where the manual does not
(`Low-pass`, `High-pass`, `Band-pass`, `Bat-Phaser`), drops the comma in
`Swept EQ, 1-octave`, and truncates the two long Swept EQ names at about 17
characters. This was predicted before any capture, from the manual disagreeing
with *itself*: its prose says `2EQ Morph + Expression` while its two screen
illustrations show `+ Exp` and `+Exp`.

Runtime 17-20 (the morphing filters) are not reachable from bytes 0x00-0x5F and
remain unconfirmed. Runtime 0 stays ambiguous: `2-Pole Lowpass` is both the
table's id 0 and the documented rendering of a *rejected* byte, so `0x01`
reading back 0 cannot be told from a rejection.

### The E4B `vpar[58]` byte is a grouped code, not a filter index

Reading `E4_VOICE_FTYPE` (id 82) for all 98 presets and joining to the bank's
expectation table: **80 of 98 bytes map to runtime 0.** The 18 that do not
group by high nibble — `0x0x` lowpass, `0x08`/`0x09` highpass, `0x1x`
bandpass, `0x2x` swept EQ, `0x4x` phaser/flanger, `0x5x` vocal.

So the on-disk byte selects a *family* in the high nibble and a member in the
low nibble. Any writer treating it as a sequential filter number emits either a
valid-looking byte selecting a filter from an unrelated family, or an invalid
one that silently becomes 2-Pole Lowpass. Reported to the sibling project; its
writer turned out to emit only valid codes, so this is a coverage gap there
(seven reachable filters it can never produce) rather than a live defect.

### The route to the Filter page, and three panel behaviours

The EOS 4.0 manual says to select the voice(s) then "press the Amp/Filt
function key (F3)" and "use the Previous and Next Page buttons to locate the
Filter screen". Both true, and both underspecified:

```
PRESET_EDIT              -> Voices-Main      (F3 here is "[ Global", NOT Amp/Filt)
EditVce (F6)             -> Amplifier        (Amp/Filt already selected; F3 never needed)
PAGE_PREV x4             -> rewinds to the clamp
PAGE_NEXT x2             -> Filter
```

- **`EditVce` returns to the group's LAST-VIEWED page**, so "two pages forward
  from the landing page" is correct exactly once and drifts thereafter. The
  first sixteen captures all landed on `Filter Envelope`.
- **Paging CLAMPS at both ends rather than wrapping**, which is what makes the
  rewind reliable — `PAGE_PREV` past the start is a no-op.
- **`PRESET_MANAGE` TOGGLES between two pages** rather than being a
  destination. Measured: `b1e70b -> 2419a7 -> b1e70b -> 2419a7 -> b1e70b`.
- **Paging does nothing outside an editor.** Zero page changes in 118 edges
  across three navigation-only walks. This was first blamed on empty RAM; a
  walk of a fully loaded machine reproduced it exactly. The real cause was the
  instrument: a navigation-only program cannot enter an editor, because entry
  is a soft key, and paging only applies inside.

### A walk pressed Load, and why the whitelist did not stop it

An exhaustive walk with a labelled soft-key whitelist reached the DISK subtree
it was designed to exclude, opened the "Destroys current RAM bank... continue?"
dialog, and confirmed a load. Nothing on media was written; RAM was empty and
gained one preset and 1.59 MB of samples.

**Root cause: the queue stored a KEY NAME after validating a LABEL.** The
press was justified by a page the walk had since left, and soft-key meaning is
page dependent — F4 is Load on the disk pages and Place on Sample Manage. The
hazard the whitelist existed to prevent was reintroduced by the queue that
carried its decisions. Compounding it, the modal back-out pressed `PAGE_EXIT`,
which does **not** dismiss that dialog (`Cancel` on F1 does), so the walk went
on pressing into a modal that swallows keys.

The replacement is not a better check. `probes`-style traversal was split into
two programs, and the recon pass has **no soft-key constant in it at all** —
the capability is absent rather than guarded, so no rule has to be obeyed
correctly for it to be safe. It re-derives what is pressable from the screen in
front of it, so no intention outlives the screen that produced it, and it
aborts rather than guessing a modal dismissal.

Key codes make the boundary worth stating precisely: no movement or mode key
shares a code with a soft key, but `CURSOR_UP` (0x6E) is one bit from F3, F5
and F6, and `PAGE_NEXT`/`PAGE_PREV` are one bit from F5/F4. There is no
checksum in `40 <key> 00 <01|00>`, so a corrupted byte cannot be rejected. No
guard was added for this: a read-back detects an event it cannot prevent. What
bounds it is that recon never visits the disk subtree, so a bit flip reaches
`Name`/`New`/`Copy`/`Place` rather than `Load`/`Save`/`Erase`.

### Three controls in one session that measured the wrong thing

1. A walk control returning via `PRESET_MANAGE` **passed by coincidence** — it
   compared a page reached by a key that toggles, so it tested press parity,
   not machine state. Its replacement then "failed" on the same parity.
2. A band-sensitivity control reported all bands clean; the perturbation had
   never landed, because RAM was empty and there was no neighbouring preset to
   select. A null from an apparatus that moved nothing.
3. A page-identity check reported "8 distinct, good" across sixteen captures
   **all on the wrong page** — its crop included a per-voice field, so its
   distinctness came from the preset rather than the page.

The images caught all three. None of the checks did.

The generalisation worth keeping: **assert sameness where sameness is
expected, rather than difference where difference is uninformative.**
Difference has many causes; sameness has few. The corrected check requires the
page title to be IDENTICAL across all sixteen captures and lets the name band
carry the measurement.

### Incidental

The `Amp Envelope` and `Filter Envelope` pages label their columns
`seg | rate | level%`. The machine's own word for that field is **rate**. That
is its claim, not a measurement of behaviour, and it bears on the sibling
project's open question of whether the stored envelope byte is a rate or a
duration — a label and a behaviour are different claims.

`Sample Edit` carries four unenumerated submenus (`Tools1^`..`Tools4^`), a
plausible home for parameters no converter models. Not entered.

### Second SysEx hang, and the card-pull procedure it earned (2026-08-18)

The device stopped answering **both** protocols again — `eoscli memory` and
`catalog` timing out, `51h` returning no screen — discovered while confirming
the session was idle. Second occurrence; §34 records the first, cause
unestablished both times, **power cycle the known fix both times.**

What is known this time and was not last time:

- **No script of this project was running**, no RtMidi client was subscribed
  to the ports, and a passive listen showed the bus silent. So it is not
  contention and not something mid-request.
- The last operation before it was a 16-preset display sweep that **completed
  normally and reported its own control clean**.
- Played notes produced no audio, but that is **not** offered as evidence the
  machine was dead: Program Change is page-dependent, the page was unknown, and
  the output level had been turned down by hand earlier. A datum that supports
  the alarming reading is still worthless if it has an innocent explanation
  that was not ruled out.

Still unexplained. If it happens a third time, the thing to capture *before*
power-cycling is **what the front panel shows and whether it responds to its
own buttons** — that separates "MIDI subsystem wedged" from "machine hung",
and neither occurrence has that datum.

**Procedure adopted: power the E4XT down before pulling the ZuluSCSI card.**
Right on a live SCSI bus regardless, and doubly so when the device is in an
unknown state. The reasoning generalises past this machine: *nobody can assert
the bus is idle, only that they personally are not driving it.* An idle-check
is a statement about the checker, not about the world — the same gap as a
transport control standing in for a measurement control.

On 2026-08-18 the card was pulled with the machine powered on, before this was
written. Recorded as a hot pull rather than assumed harmless, so that a later
fault is not mistaken for a first occurrence of something new.

**One candidate, stated so the next occurrence can eliminate it.** The EOS
manual's default SCSI table assigns **id 6 to the Emulator itself**. On
2026-08-18 an ISO (`CD6-ENVSPAN.iso`) was mounted on id 6 from 09:14 until
12:42 — an image sitting at the host's own bus address, across the second
hang. ZuluSCSI reported no conflict and mounted it happily, because *its*
numbering is unique on the SD card; the collision is one layer down, on the
real bus.

This is **not** a claim of cause. The hangs are MIDI and this is SCSI, and the
first occurrence (2026-08-17) predates that file existing, so it cannot be the
whole story. It is recorded because it is the only candidate anyone has
produced, and because it is cheap to falsify: **the file is now removed, so a
third hang eliminates it, and no further hangs make it suggestive.** Note which
happened rather than filing the next one as "the same unexplained thing".

Worth noting how it was found, too: the host's drive list read
`D0 D1 D2 D3 D4 D5 D7 D8` — no D6 — while the ZuluSCSI log showed a clean
`Opening /CD6-ENVSPAN.iso for id:6`. A lower layer reporting success was
briefly used to dismiss a higher layer's observation. The host's view was the
one that mattered, because the host is the thing that has to see the bus.

### The morphing filters, and a file byte that crashes the machine (2026-08-18)

A second anchor bank swept `vpar[58]` = `0x60`-`0xFF` (162 presets), to reach
the four morphing filters that `0x00`-`0x5F` could not.

    file byte  runtime  display
    0x60         17     "Dual EQ Morph"       exact
    0x61         18     "2EQ+Lowpass Morp"    TRUNCATED
    0x62         19     "2EQMorph+Exprssn"    TRUNCATED
    0x68         20     "Peak/Shelf Morph"    exact
    0x63          0     "2 Pole Low-pass"     (a rejected byte, as control)
    0x7F         21     ""                    NO NAME -- see below

So **runtime 17-20 are confirmed against the display**, and with §36's sixteen
that is 20 of the 21 documented types observed rather than inferred. The
family pattern holds: `0x60`/`0x68` are family boundaries exactly as `0x40`,
`0x48`, `0x50` were.

**155 of 162 bytes read runtime 0.** The deliberate control — capturing the
display for a byte *known* to be rejected — confirms rejected bytes render as
`2 Pole Low-pass`. That control was nearly skipped as uninformative and is the
only reason the next paragraph is interpretable.

#### `0x7F` produces an out-of-range filter type and a FATAL Gen Trap

**Invalid bytes are NOT uniformly clamped.** Most map to runtime 0 and render
harmlessly. `0x7F` does not: it passes through as **runtime 21**, one past the
end of the 21 implemented types (ids 0-20). The machine has no name for it,
renders an **empty** field, and shortly after took a fatal firmware fault:

```
FATAL ERROR: Gen Trap error
PC:107FFA50  Eaddr:107FFA50  SR:007F
A0:00000008  A1:00000000  A2:0006A4CE
D0:00000018  D1:00000001  D2:0000007F
```

**`D2` holds `0x7F`** — the byte itself is in the register dump. `D0` is
`0x18` (24). Recovered by power cycle; the machine came back clean, RAM empty,
firmware 4.70 as before.

**This is a hazard for anything that writes or forwards E4B voice parameters:
a file carrying `0x7F` in `vpar[58]` can crash an E4XT.** The sibling
mpc2emu writer never emits it, so nothing shipped is affected, but a corrupt or
third-party file could. A reader guard is cheap; the crash is not.

This is the **second** Gen Trap this project has recorded — TODO.md carries one
from unattended amp-envelope automation that was never root-caused. That one
has no trigger and no dump. **This one has both.**

#### Truncation is at 16 characters and removes spaces

`2EQ Morph + Expression` renders as `2EQMorph+Exprssn`. The machine does not
merely cut the string — it drops the spaces the manual's prose has, then
truncates. So a joiner comparing prose to display **must strip separators
before comparing, not merely test for a prefix**: `2EQ Morph + Expression`
does not have `2EQMorph+Exprssn` as a prefix under any whitespace-preserving
comparison. Predicted from the manual disagreeing with itself (`+ Exp` in one
illustration, `+Exp` in another); the machine is harsher than either.

#### What remains open

Byte `0x01` reads runtime 0 and renders `2 Pole Low-pass`, which is also what
a *rejected* byte renders. The display cannot separate "legitimately 2-Pole"
from "clamped". The lowpass family wanting three members, with `0x00` -> 4-Pole
and `0x02` -> 6-Pole leaving 2-Pole and `0x01` both unaccounted, makes `0x01`
the natural candidate — but that is an inference and this experiment cannot
confirm it. It needs a byte known to be 2-Pole by construction.

## §37 — The EOS envelope byte is a RATE, and the decay is linear in dB (2026-08-18, live)

The sibling mpc2emu project's E4B writer converts envelope times to a byte and
had no hardware evidence for which quantity the byte represents. A purpose-built
bank settles it: four presets sharing one decay byte, differing only in sustain
level, so that

- **DURATION** predicts LO and HI reach sustain in the SAME time;
- **RATE** predicts LO takes LONGER, having further to fall.

Two controls first, and both had to pass before the comparison meant anything:

| preset | decay | sustain | measured (two runs) |
|---|---|---|---|
| `SPAN LO`  | 2.0 s | 20% | 0.540, 0.540 s |
| `SPAN HI`  | 2.0 s | 80% | 0.140, 0.130 s |
| `SPAN CTL` | 2.0 s | 20% (duplicate of LO) | 0.550, 0.560 s |
| `SPAN REF` | 4.0 s | 20% (different byte) | 1.070, 1.050 s |

- **Method control** — `CTL` must equal `LO`: 15 ms apart. Pass.
- **Measurement control** — `REF` must differ from `LO`: 1.96x. Pass. This is
  the one that matters: without it a null is indistinguishable from an
  apparatus that cannot observe a change at all.

**Result: LO/HI = 4.00x. The byte is a RATE.**

### The law falls out, and only because no ratio was predicted

The sustain level is a dB law, so the experiment was deliberately designed as
"equal or not equal" rather than against a predicted number — a linear guess
would have been a figure invented from an assumption, and a measurement
disagreeing with it would have read as a finding.

    LO: sustain/peak 0.177 -> linear span 0.823, dB span 15.0 dB
    HI: sustain/peak 0.655 -> linear span 0.345, dB span  3.7 dB

    linear span ratio  LO/HI = 2.38     <- what a linear guess gives
    dB     span ratio  LO/HI = 4.09
    measured time      LO/HI = 4.00

**The decay is linear in dB**: time taken is the dB distance divided by a
constant rate. A "roughly 4x" prediction from linear percentages would have
been right for the wrong reason and nobody would have looked again.

Fitted rates: byte 72 gives 27.9/27.2/26.8 dB/s across LO/HI/CTL — consistent —
and byte 84 gives 14.2 dB/s. So **+12 on the byte halves the rate**, one data
point but the first anyone has on that axis.

The machine's own envelope pages label the column `rate` (§36). Label and
behaviour agree; a disagreement would have been more interesting, and there
isn't one.

### What this does NOT license

The obvious repair to the writer is a span-aware conversion, and it must wait.
Computing the span needs the achieved sustain level, and the sibling project's
model predicts 0.208 and 0.821 where the machine gives **0.177 and 0.655** — a
span ratio of 8.0x against the measured 4.00x. A conversion built on that would
be wrong by a factor of two **and would look principled**, which is worse than
the present error looking arbitrary. The fix waits on a sustain-LEVEL sweep.

The two sustain/peak figures were recorded only as a sanity check that the
right quantity was being measured. They turned out to be the numbers that
stopped a confident wrong fix.

## §38 — Stereo, single-cycle and filter-envelope depth, measured (2026-08-18, live)

Three A/B pairs, each with its predicted direction written down before any
capture, on adjacent keys of one bank.

### Stereo — confirmed

    ST MONO   L/R correlation = +1.0000
    ST WIDE   L/R correlation = -0.1954

Identical channels against independent ones. E4B stereo had been reverse
engineered from a corpus of 473 files and 20,383 samples and **never heard**.
Closed.

### Single-cycle oscillators — confirmed, after a null the apparatus invented

Level as a fraction of peak, per second, over a **10 second** hold:

    SC OFF  0.000 0.000 0.877 0.869 0.861 0.874 0.001 0.000 0.000 0.000
    SC ON   0.000 0.000 0.833 0.836 0.838 0.838 0.836 0.836 0.834 0.836

`SC OFF` ends with the sample at ~6 s; `SC ON` sustains to the end of the
capture, pitch steady at 110.1 Hz across six sample points — no warble.

**The first attempt used a 4 s hold and reported both at sustain = 0.78, i.e.
indistinguishable.** That would have been filed as "no difference". It was an
artefact: the source does not run out until ~6 s, so a 4 s window cannot
separate "sustains indefinitely" from "has not finished yet", and nothing in
the capture flags the window as too short. **For a sustain test the hold must
exceed the source length.**

This pair is also the only one not protected by a ratio, so the capture clock
mattered: 109.8/110.1 Hz against a nominal 110.0 Hz is the rig validating
itself to 0.2%.

### Filter-envelope depth — and a ruler that clamped

Centroid excursion, three runs each:

    FE OLD (depth 0.776)   213  212  211    mean 212   spread 2 Hz
    FE NEW (depth 0.663)   246  246  247    mean 246   spread 1 Hz

34 Hz against a 1-2 Hz noise floor, so the pair is distinguishable and the
"indistinguishable is itself the result" branch does not apply. The shallower
preset showed the LARGER excursion, which reads as the correction being
backwards.

**It is not. The metric was clamped.** The trajectories peak at 707.5 and
709.5 Hz — 2 Hz apart across two different envelope depths, which the parameter
cannot do. With the ceiling pinned, excursion inverts with depth, because a
deeper envelope raises the resting floor while the peak cannot move.

Measured on the same captures, floor taken from the settled sustain phase:

| preset | depth | peak | floor |
|---|---|---|---|
| `FE OLD` | 0.776 | 707.5 Hz (spread 1.2) | **617.1 Hz** (spread 1.9) |
| `FE NEW` | 0.663 | 709.5 Hz (spread 0.6) | **554.3 Hz** (spread 2.5) |

Peaks differ by 2 Hz, floors by 62.8 Hz, and **the floors order exactly as
depth predicts** — the deeper envelope rests higher. The correction is correct;
the excursion metric could not see it.

**The floor is the usable ruler**: 63 Hz of movement per 0.113 of depth against
~2 Hz of noise, roughly 30:1, and unclamped.

The general form, which has now bitten twice in one session: *a ruler that
saturates against its source is measuring the source.* Excursion was measured
because excursion was what the metric produced, not because it was the right
quantity — and the tell was sitting in the data as two peaks agreeing to 1 Hz,
recorded and walked past as incidental.

## §39 — The sustain-level law, and a rate confirmed on a second dataset (2026-08-18, live)

§37 established that the envelope byte is a rate. Writing the converter needs
the other axis too: what the sustain LEVEL byte actually achieves. A bank of 18
presets sweeps the **raw byte, 64-127**, deliberately not the sibling project's
model value — that model is the thing in question, and putting it in the
measurement loop would fit a law to its own assumption.

Controls are byte 127 at both ends, where full sustain must put the plateau AT
the peak:

    CTL-A 127  sustain/peak 0.9437
    CTL-B 127  sustain/peak 0.9351    agree to 0.009, both near 1.0    PASS

### Two ends of the range are not usable, and the reasons are measurements

- **Bytes 64-72 sit at the noise floor.** Plateaus of 16, 31 and 63 counts,
  against a silent capture measuring 8-9. Those are ratios of noise to signal.
- **Bytes 120-127 saturate against the ceiling**, because a plateau cannot
  exceed the attack peak it is divided by. This is the same clamping that
  inverted the filter-envelope excursion in §38, arriving in a different
  experiment within the hour.

Fitted over bytes 80-116 only — above the floor, below the ceiling, 10 points:

    dB below peak = 0.547 x byte - 66.14      R^2 = 0.980

That is **0.547 dB per byte, one doubling every 11.0 bytes.** Residuals run
-1.6 to +1.2 dB, so two significant figures is as much as it will carry.

### The exclusions validate themselves against a second measurement

The captures also carry decay TIMES, and the rate byte is 72 throughout — the
byte §37 measured at 27.9 dB/s. So each preset's decay should reproduce
`span / 27.9` using its own measured span. Across the 11 usable points:

    mean measured/predicted = 0.951   sd 0.048   -> implied 26.5 dB/s

**Two experiments, two banks, two different sources, one rate byte, 5% apart.**
The rate law of §37 is confirmed on independent data.

And the excluded points fail here in exactly the direction their exclusion
predicted, having been chosen from the LEVEL data before any timing analysis
existed:

    bytes 64, 68, 72   ratio 0.607, 0.682, 0.753   floor: runs SHORT
    byte 120           ratio 1.624                 ceiling: runs LONG

The floor cases must run short — the envelope decays into noise, so the plateau
reads too high, the span too small and the predicted time too long — and the
trend is monotonic, climbing out at byte 76 exactly where contamination should
stop mattering. **A boundary justified by two independent kinds of evidence
rather than fitted to make the answer tidy.**

### The 5% is unexplained, and a wrong explanation is recorded as wrong

The gap between 26.5 and 27.9 dB/s was first attributed here to the decay-time
estimator firing early: it crosses a threshold 5% of the linear distance above
the plateau, which necessarily fires before the plateau is reached.

**That mechanism does not fit the data.** For a 30 dB span the threshold sits
21.9 dB below the peak, predicting a ratio of 0.730 where 0.853 was measured;
it predicts three to five times more bias than observed, and far more
span-dependence than the residuals carry (span-vs-ratio correlation -0.45 over
11 points).

So the direction was right and the magnitude wrong. **The 5% is unexplained,
not explained** — which is a stronger reason not to quote 26.5 as a competing
figure than the one originally offered. Two independent measurements agreeing
to 5% is the result; attributing the remainder is not possible from these
captures and does not change anything downstream.

### What is still open: the anchor

`sustain/peak` divides by the attack peak, which is **source-dependent**. The
two banks disagree at nominally the same setting — byte 107 measured 0.177 in
§37's bank, byte 108 measures 0.4565 here, and bytes one apart cannot differ by
2.6x. Crest factor accounts for 1.377 of the 2.579 discrepancy; **1.87x, or
5.4 dB, is unaccounted for by either project.**

So the *shape* of the level law is solid and the *absolute anchoring* is not:
a relative law measured within one bank, needing a per-source offset before it
can calibrate anything. `env_seconds_to_rate(seconds, span_db)` stays unwritten
until that resolves — sixteen points and an R^2 of 0.980 make it tempting, and
a confidently wrong number replacing a confidently wrong number would be worse
than the present error looking arbitrary.

---

## §40 — A panel sub-command that takes the front panel away (2026-08-18, live)

**Recorded as a hazard, without the bytes.** One sub-command of the panel
protocol diverts the front panel to the remote: while it is in effect the
E4XT stops acting on its own buttons entirely. A counterpart message hands
control back.

Measured on the machine, in two single runs with an operator watching the
front panel:

    session open alone      -> key echo arrives, panel still live
    + the sub-command       -> key echo still arrives, panel dead
    + the counterpart       -> panel live again

The second run is the one that matters and it is why this is written down.
The panel gives **no indication whatsoever** that it has been diverted — no
message, no changed screen, no LED. Someone standing at the sampler sees a
machine that has stopped responding. Every probe in this project had been
sending the divert message on its way *out*, believing it to be the restore,
and left the panel locked out until the counterpart was sent by hand.

**Rules that follow, and are in force:**

- eosed never sends it. It is not reachable from the TUI or `eoscli`.
- It is never key-bound, and never sent speculatively — same standing as the
  Erase utilities (§21).
- Any code that ever does send it must send the counterpart on **every** exit
  path, including on exception. A `finally` is the minimum, and a `finally`
  that sends the wrong one of the pair is worse than none, which is exactly
  the mistake made here.

**Why the bytes are not in this file.** The sub-command was identified from a
document held privately by the third party who wrote it, shared with this
project for testing and not for publication. Publishing the opcode would
publish their unreleased work. It is recorded locally, outside version
control, and will be documented here if and when they publish.

The hazard itself is stated in the README rather than kept quiet, because the
people most likely to trip it are not eosed's users: anyone sweeping a
sub-command range while writing their own client will find it eventually, and
the failure presents as dead hardware rather than as a message they sent.
