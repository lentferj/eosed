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

### The spec's own layout, transcribed 2026-08-25

Recorded because a sibling project is about to hand-edit a dump body, and the
alternative was inferring this from a hexdump. **All parameters are 2-byte
words**; the OLD dump body is:

    {<NUMBER>, <NAME>, <Global Parms>, <Links>, <Voices>}

    <NUMBER>       one word, preset number 0-999
    <NAME>         16 ASCII characters
    <Global Parms> ids 0-5 first (TRANSPOSE, VOLUME, CTRL_A..D), then effects
                   A and B. "If the effects A or B Algorithm is 0, then the
                   effects parameters are the values of Master Effects A or B."
    <Links>        first word = number of links; then 13 words per link, in
                   link-number order. No links -> no link data at all.
    <Voices>       first word = number of voices, then per voice:

        voice parameters      146 words   General(20) Tuning(11) Amp/Filt(37)
                                          Lfo/Aux(24) Cords(54)
        number of sample zones  1 word
        zone blocks            13 words each, ONLY if the count is > 1

**The group number is the FIRST of those 146 words, not an extra one.** The
spec says "The first word is the Group number associated with the Voice. What
follows are the Voice Parameters", which reads as a separate word — and this
section said so until the arithmetic was checked against a real dump. It is
`E4_GEN_GROUP_NUM`, the first of the General(20). The spec's own sum settles it
where its prose does not: *"There are 146 total base parameters per Voice. This
number along with the number of Samples word = 147 words, or 294 Bytes."* 147,
not 148.

**Verified against two live dumps** (2026-08-25):

| | predicted | actual |
|---|---|---|
| 1-voice, 8-zone preset | 66 + 292 + 2 + 8×26 = **568** | **568** |
| 6-voice, 1-zone-each preset | walk all six voices | consumes **1830 of 1830** |

A one-word error here is not cosmetic: it shifts **every** field of **every**
voice by one word, and the resulting values are all plausible.

**"66 Bytes of Preset so far if no Links"** — the spec's own checkpoint, which
is worth keeping as an arithmetic check on any parser: 2 (number) + 16 (name) +
44 (22 global words) + 2 (link count) + 2 (voice count) = 66.

**The multisample marker is `3FFFh` in `E4_GEN_SAMPLE`.** *"If the Sample
Number is 3FFFh, then it is a multisample voice."* That is the same value the
editor protocol returns as **−1** on parameter id 38 — the two are one fact
seen through a u14 and an s14 reading of the same field, which is worth stating
because they look like different sentinels.

**A zone count of 1 means the voice is not multisample and NO zone blocks
follow** — the next word begins the next voice. Only a count greater than 1
produces zone data. A parser that always reads zone blocks will walk off the
end of every ordinary preset.

**The 13-word zone block** is `E4_GEN_SAMPLE` plus the 12 fields ids 39, 40,
42, 44, 45-48, 49-52 — exactly `eos/params.py`'s `SAMPLE_ZONE_PARAM_IDS`,
which was transcribed independently and agrees.

*This is what the spec says, not what the machine was observed to do.* The
field order below is still the open item; this transcription narrows what has
to be checked rather than closing it.

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
`eos.messages.Command` (57 defined values across the full 0x00–0x7F
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

> **The second sentence is WITHDRAWN; see §49.** The `E4_PRESET_VOLUME`
> observation above stands and is reproducible. The generalisation from it does
> not: `E4_GEN_VOLUME` (id 39), the per-*voice* level, reaches the audio
> immediately, and muting one voice to isolate another works. Test any given
> parameter rather than inferring its scope from either note.

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

**SUPERSEDED 2026-08-22 — DO NOT USE. The byte labels behind this fit were
wrong (the bank's sweep is non-uniform and was indexed as if uniform). The
corrected law is 0.754 dB/byte at R^2 0.9999; see §45.**

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

---

## §41 — A guard that passed thirty silent captures (2026-08-21, live)

**Ninety reference captures for mpc2emu, and the interesting result is a
failure in the measuring apparatus, not in the device.**

The task: one note per preset across a ten-preset bass bank already resident in
RAM, three takes each, at MIDI 69, then 57, then 81. Rig constants (MIDI port,
basic channel 5, capture ports, the persistent JACK client) come from
mpc2emu's `tests/re_banks/hw_measure.py`, which documents this bench.

### The guard that was built, and worked

The known hazard here is §34's: **a Program Change the E4XT ignores leaves
whatever was already selected**, and it is ignored anywhere but the main preset
page. Ten identical recordings filed under ten preset numbers look exactly like
data, which is how the 2026-08-17 pitch experiment produced a result off two
recordings of the same preset.

So selection was never assumed. Before every take the LCD was read back over the
panel protocol and hashed, with two conditions checked afterwards rather than
trusted:

    hash CONSTANT across a preset's three takes  -> selection did not move
    ten hashes DISTINCT                          -> ten different presets

Both held on every pass. A pre-flight also confirmed PC was landing before any
audio was recorded: three presets gave three distinct screens, and returning to
the first reproduced its hash exactly.

### The guard that did not exist

The MIDI 81 pass reported:

    no clipping; peaks -70.3 .. -65.2 dBFS
    RESULT: usable

for thirty captures in which **nothing sounded at all**. The level check asked
whether the audio was too loud. It never asked whether there was any, and
silence does not clip.

Two independent confirmations, once the peaks looked suspicious:

    audio   note window sits +0.3 dB (median) above the same file's OWN
            pre-roll; the MIDI 69 set lifts +60 dB
    device  asked over the editor protocol rather than inferred: all ten
            presets are a single voice spanning A-1..G4 (MIDI 21..79)

Note 81 is two semitones above the top of the mapped range on every preset. The
device was behaving correctly and the selection guard was correct throughout:
the right preset was selected, and it properly sent nothing.

**What actually caught it was luck.** The A440 set existed to compare against,
and 50 dB is hard to miss. A standalone run at 81 would have shipped thirty
silent files marked `usable`, and any spectrum computed from them would have
been of the room.

### The fix

Each take now measures its lift over **its own pre-roll silence**, and anything
under 6 dB voids the run:

    real note here   +48 .. +64 dB
    dropped note      +0.0 .. +1.0 dB

This needs no absolute reference and no assumption about level or gain, which is
what makes it portable to any capture on this bench. The two already-delivered
manifests were backfilled with the field so the recipient could verify the
claim instead of taking it on trust.

### The general shape, worth keeping

Every measurement failure this project and its siblings have hit this week is
the same one: **a check that validates the measurement's internal consistency
while never testing whether it points at the specimen.**

    §34   two recordings, 0.6 cents apart, of the same preset
    §36   a walk whose whitelist validated a label but queued a key name
    §33a  a delta claim resting on a keypress that changed zero pixels
    §41   a level guard that confirmed the silence was not clipping

The countermeasure is not a better threshold. It is that every guard must be
able to answer *"what would this look like if the thing under test were absent
entirely?"* — and a peak meter answers that question with a comfortable number.

### A fifth door into the same failure, and an ambiguity it leaves in §41's own result

The sibling project hit this class again the same week, from a direction none of
the four above covers. A cutoff-calibration bank of eleven presets, one per
cutoff position, captured with a *verified* noise source, came back identical to
3-4 significant figures on both RMS and centroid. Nothing was wrong with the
source, the capture path or the analysis: their writer gates the whole filter
block on `filter_type` being truthy, 0 in that enumeration means **Off**, and
the generator had never set the field. The filter was not in the signal chain at
all. It was caught by walking to the machine and reading the algorithm off the
panel -- `PITCH NONE AMP` -- not by any amount of scrutiny of the numbers.

**A verified instrument pointed at an inert parameter measures exactly as
cleanly as one pointed at a live one.** Verifying the source harder cannot
detect it; only asking whether the thing being swept is actually in the path can.

This project's perturbation check already does that for the *cord* -- run 1's
pre-flight confirmed depth 0 vs 100 moved the centroid 127 Hz before any contour
was believed. It does **not** do it per segment, and that leaves §41's own
headline observation ambiguous:

    "three of six segments are inert on a held note"

An inert segment is exactly what a release stage looks like during a held note.
It is also exactly what a segment that is not in the signal path looks like. The
knock-out experiment cannot tell those apart, so the finding constrains less than
its wording suggests. Re-read it as *"SEG0, SEG4 and SEG5 produced no audible
effect during a held note, for reasons not established"* until the rate -> time
calibration makes the traversal readable.

### The other half: the material, not the machine

Note 81 is unmapped on the AKAI conversion too (keygroups span 24..79), so
nothing sounds there on either machine and there was no comparison to lose. That
also rules out the one reading that would have mattered — a conversion that
widened the range would have sounded where the E4XT is silent, and looked like
the E4XT missing top end. The leg was re-run at 79, the top mapped key, and
labelled +10 semitones rather than described as an octave.

Any absolute reading at 79 measures the edge of the sample's span; the paired
difference stays clean because both machines transpose at the same key, but a
per-preset oddity appearing only there should be blamed on the boundary before
the conversion.

---

## §42 — `sustain/peak` is NOT source-dependent, and that makes §39's gap worse (2026-08-22, live)

§39 closed with the sustain-level law's *shape* solid and its *absolute
anchoring* unexplained: ENVSPAN's byte 107 measured `sustain/peak` 0.177 while
SUSLEVEL's byte 108 measured 0.4565, and bytes one apart cannot differ by 2.58x.
Crest factor was offered as accounting for 1.377 of it, leaving 1.87x / 5.4 dB
with no candidate. The leading suspect was the metric itself: `sustain/peak`
divides by the attack peak, which is source-dependent.

**It is not.** The suspect is eliminated.

### The design: everything but the source held constant

One bank, twelve presets, one key each (36-47), one pass, one capture path. The
same five level bytes (84/92/100/108/116) rendered on **two sources**: a pure
220 Hz sine (crest 1.414) and an 11-harmonic tone (crest 1.948). Laid out
**interleaved** SIN/HRM rather than blocked -- with a blocked layout, any drift
in the capture path across the run lands entirely in the quantity being
measured. Three takes of each of the twelve.

Windows were taken from the data, not assumed: an exploratory 10 s capture put
the attack peak at 0.55 s and a flat plateau from 2.0 s to 6.4 s holding to
+-0.3 counts, so sustain is the median over 3.0-6.0 s.

### Controls, and a threshold derived rather than picked

Byte 127 on the sine at both ends of the run -- full sustain must put the
plateau at the peak:

    CTL-A (preset 0)   ratio 1.0002
    CTL-B (preset 11)  ratio 0.9999     differ by 0.03%

Take-to-take spread within a preset is **2.14% median, 4.02% worst**, measured in
this same run. That is the bar any difference has to clear, and it is derived
from the takes rather than hard-coded -- a fixed threshold here would have been
meaningless, since the quantity's own repeatability is what sets the floor.

### The result

    byte    SIN ratio   HRM ratio    HRM - SIN
     84      0.02712     0.02751       +0.13 dB
     92      0.05538     0.05463       -0.12 dB
    100      0.11097     0.11017       -0.06 dB
    108      0.22429     0.22195       -0.09 dB
    116      0.44167     0.44651       +0.09 dB

**Mean offset -0.01 dB. Spread 0.25 dB. Trend across bytes 84->116: -0.01 dB.**

Not a constant offset, not a growing one: **zero**, to well inside the run's own
repeatability. The two sources' attack peaks differ by a factor of ~2.1 (2628 vs
1247 counts, 6.5 dB) and their ratios agree to a quarter of a dB. That is a
positive demonstration of source-independence, not merely a failure to find one.

### What this costs, and it is more than it looks

The obvious reading is "the metric is fine". The expensive reading is the right
one: **crest factor is a property of the source, and the source has no effect on
this quantity at all.** So the crest-factor term that was said to account for
1.377 of the 2.579 accounts for nothing either.

The gap did not shrink from 2.58x to 1.87x. **The whole 2.58x is unexplained**,
and one of the two candidate mechanisms has been removed rather than confirmed.
What remains must be a difference between the two *banks* -- different envelope
settings, different presets, a different measurement window, or an error in one
of the two original measurements -- and nothing in this experiment can say
which. `env_seconds_to_rate(seconds, span_db)` stays unwritten, and the reason
is now narrower and better founded than "some of it is unexplained".

The disc is spent: it answered its question, and the answer eliminated the
answer everyone expected.

---

## §43 — The filter envelope's rate byte, in seconds (2026-08-22, live)

§41 failed three times partly because nobody knew what a rate byte meant in
seconds, so a dip at 5.6 s could not be mapped to a stage. That is now measured.

    log2(seconds) = 0.08184 x byte - 3.9893        R^2 = 0.9998
    -> the byte is a TIME constant: higher is SLOWER,
       doubling every 12.2 bytes

    byte  24   measured 0.24 s   fit 0.25 s
    byte  40   measured 0.62 s   fit 0.61 s
    byte  56   measured 1.54 s   fit 1.51 s
    byte  72   measured 3.74 s   fit 3.74 s
    byte  88   measured 9.14 s   fit 9.27 s

### THE TRAVERSE DISTANCE IS PART OF THE RESULT — do not quote the law without it

**These times are for ONE FULL SEGMENT TRAVERSAL to target 100.** The prefactor
scales with how far the segment travels; the slope does not. For
`t = A x e^(K x b)`, a segment covering distance `d` of the full span takes
`(d/full) x A x e^(K x b)` — so `0.08184` per byte is distance-independent
evidence and `-3.9893` is not.

Quoted without that, the constant reads as a disagreement with any measurement
taken over a shorter traverse. mpc2emu's own `ENV_RATE_A` runs 0.52x this one
across the whole range (0.51 / 0.53 / 0.56 at bytes 24 / 56 / 88) because theirs
was fitted on **Decay-1**, a segment travelling peak->sustain rather than a full
span. Near-constant ratio, slope untouched: that is the signature of a distance
difference, not of a conflict, and neither number needs changing.

The start value here was not independently established — what is measured is the
transition to target 100, observed as a full-range corner excursion (floor ~470
Hz to plateau ~11.6 kHz). Anyone fitting a shorter stage should expect a smaller
prefactor by roughly the distance ratio.

### This law is measured on a RISE. The release is assumed. (added 2026-08-24)

Every point above is a transition **upward, to target 100**. **Whether a release
segment obeys the same law was never measured**, and nothing here entitles anyone
to assume it does — the amplitude envelope's segments were only shown to share
one scale (§63, §69) by measuring them.

Recorded because a decision now rests on it. The sibling project found its filter
release path computing a span in **dB**, from a law that maps an *amplitude
sustain byte* to dB below peak, for an envelope §56 says the machine runs on a
**cutoff byte** scale — a span in the wrong unit, with a comment asserting the
unit as a fact. It nevertheless lands **within 2 rate bytes** of this law across
30 combinations of filter sustain and release time, worst case 1.19× in time,
because that unit error and the 0.52× distance difference above very nearly
cancel. The near-constant offset is the tell: **shape right, anchor off.**

They chose not to correct it, and the reason is this section's gap:
**correcting a 1.19× error against an assumed reference is how a 1.19× error
becomes a 1.4× one.** Closing that would take a filter-inert subject with a
filter cord deliberately added, measuring a downward traversal — and it is not
worth the bench time while the amplitude error it would have masked was 1.8×.

*A law measured in one direction is a law measured in one direction.*

### The design sidesteps the ordering question rather than waiting on it

Set **all six segments to the same target (100) and the same rate R**. The
envelope then has exactly one transition to make — from its start value up to
100, during whichever segment runs first — and every later segment is already at
its target, so nothing else moves. That times one segment's traversal without
knowing which segment it is. §41's ordering question stays open and does not
block this; the dependency runs the other way.

### Two measurement traps, both avoided by measuring at the end

- **The corner's low end is invisible.** The contour sits flat near 470 Hz for
  the first ~0.9 s at byte 64 and only then climbs: down there the corner is
  below most of the source's energy and the centroid barely moves while the
  envelope is already travelling. A t10 would have folded that floor into the
  law. The *completion* instant has no such problem, so traversal time is
  note-on to 95% of the total excursion.
- **The source cannot contribute a rise.** This is measured on the stationary
  noise (§42's sibling artefact, verified on capture at 9.0-9.7% centroid spread
  at 5 ms), not on a bass sample whose own onset was common-mode with the
  envelope and destroyed the first attempt.

### Bytes 104 and 120 did not finish, and that is a check rather than a gap

Both were excluded for showing no traversal inside a 12 s note. The fit
*predicts* that: byte 104 is 23 s and byte 120 is 57 s. Two points excluded on a
measurement criterion, then independently accounted for by the law fitted to the
other five.

### It matches the amp envelope

§37 measured the **amp** envelope decay halving every ~12.3 bytes. This is
**12.2 bytes** per doubling on the **filter** envelope, from an unrelated
experiment on a different source with a different observable. The two envelopes
share a rate law, which was assumed by nobody and is now evidence rather than
convenience.

**What this unblocks:** §41's traversal-order experiment becomes readable —
stage boundaries can now be predicted in seconds and a dip located against them
instead of being reported as an unexplained time.

---

## §44 — The filter envelope's traversal order, settled (2026-08-22, live)

**SEG0 -> SEG1 -> SEG2 -> SEG3 while the note is held, hold at SEG3's target
until note-off, then SEG4 -> SEG5 on release.** Sequential in id order, not
interleaved. `eos/params.py`'s stage names were wrong and are corrected.

    id 93/94    SEG0   Atk1
    id 95/96    SEG1   Atk2
    id 97/98    SEG2   Dcy1
    id 99/100   SEG3   Dcy2  <- THE SUSTAIN LEVEL
    id 101/102  SEG4   Rls1
    id 103/104  SEG5   Rls2

### Why §41's design could not have answered this

§41 held all six segments at one level and dropped one to zero. **A segment
already at its target travels zero distance, and zero distance takes zero time**
— so every at-target stage completed instantly and the dip landed at the same
instant regardless of which segment carried it. That is exactly what it saw:
SEG1, SEG2 and SEG3 all dipping at ~5.6 s. The data were fine; the experiment
could not distinguish the orders it was posed against.

### The design the rate law made possible

Give every segment a full distance to travel (alternating 100/0) **and a
distinct rate**, so each stage has a distinct *duration* (§43):

    SEG0 rate 24 -> 0.25 s    SEG3 rate 48 -> 0.96 s
    SEG1 rate 32 -> 0.39 s    SEG4 rate 56 -> 1.51 s
    SEG2 rate 40 -> 0.61 s    SEG5 rate 64 -> 2.38 s

Then the sequence of leg durations names the order. Observed, with levels
100/0/100/0/100/0: a rise of ~0.22 s, a fall of ~0.32 s, a rise, a fall of
~0.72 s, **then a flat hold for the rest of the note** — four legs, in id order,
and SEG4/SEG5 never ran.

Measured legs run consistently *shorter* than predicted, which is §43's floor
effect: the corner's low end is below the source's energy, so the start of each
leg is invisible and every leg is clipped at its quiet end. It biases durations
one way and does not reorder them.

### The control: invert every level, and the hold follows SEG3

With levels 0/100/0/100/0/100 the predictions inverted, and so did the machine:

    SEG0 target 0, starting at 0 -> no movement at all, as predicted
    then rise, fall, rise
    then a flat hold at ~11500 Hz -- BRIGHT

**The sustain was dark when SEG3's target was 0 and bright when it was 100.**
Flipping the input flipped the output, which is what the ascending/descending
staircase in §41 failed to do and is why that result was withdrawn.

### What this explains retroactively

- **mpc2emu's "sustain" reads id 100**, which under the old labelling was
  "Atk2 Level" and looked like an odd choice. Under the measured mapping id 100
  is Dcy2's target — the sustain. Their field was right and our label was wrong.
- **§41's "three of six inert on a held note"** now has its reason: SEG4 and
  SEG5 are release stages, and SEG0 was inert in that particular experiment
  because it started and ended at the same level. The observation was correct
  and its cause is no longer unestablished.

Not verified for the voice and aux envelopes (ids 67-80, 117-128). The same
ordering is likely and is not measured; their notes are left alone.

---

## §45 — There was never a 2.58x. The banks agree; the byte labels did not (2026-08-22, live)

**ENVSPAN and SUSLEVEL, measured in one session through one capture path, agree
on the same byte to 0.69%.**

    ENVSPAN  'SPAN LO S20'  sustain byte 107  ->  0.2045   (-13.78 dB)
    SUSLEVEL 'SUS 107'      sustain byte 107  ->  0.2031   (-13.84 dB)

Against a within-preset take-to-take spread of 2-3%, that is agreement, not
discrepancy. §39's "bytes one apart cannot differ by 2.58x" was reporting a
defect in the analysis, not in the machine.

### Where the 2.58x came from

**The bank has no byte-108 preset.** Its sweep is deliberately non-uniform:

    64  72  80  88  96  100  104  107  110  113  116  118  120  122  124  127

The value 0.4565 that §39 attributed to "byte 108" sits at **byte 116**, which
measures 0.4495 today. A preset index was converted to a byte as though the
steps were uniform, so every point above the spacing change carried a wrong
label — and comparing one of those mislabelled points against ENVSPAN's
correctly-labelled 107 produced a ratio that no physical law could explain.

This is the second time this exact bank has been mis-indexed on the assumption
of uniform spacing; the first was caught before publication, this one was not.

### The corrected law

Refitted from today's sixteen presets, sustain/peak as amplitude, `20log10`:

    dB below peak = 0.7539 x byte - 94.21      R^2 = 0.9999   (bytes 64-122, n=14)
    dB below peak = 0.7518 x byte - 94.03      R^2 = 0.9995   (bytes 80-116, n=9)

**0.754 dB per byte, one doubling every ~8.0 bytes.**

§39 published **0.547 dB/byte, R^2 0.980** over 80-116. That slope is 38% low
and its scatter was the mislabelling, not the hardware: on correct labels the
same range fits at R^2 0.9995. **§39's law should not be used.**

Bytes 124 and 127 flatten (only 0.88 dB between 124 and full scale) — the
ceiling clamp §39 correctly identified, and the reason the fit stops at 122.
The three byte-127 controls read 0.9997, 1.0004 and 1.0003.

### What this does and does not overturn

- **§42 stands entirely.** `sustain/peak` is source-independent; that was
  measured directly and does not depend on any byte label.
- **§42's framing was wrong.** It said eliminating the source left "the whole
  2.58x unexplained". The 2.58x did not exist, so there was nothing left to
  explain. §42 removed a candidate mechanism for an artefact.
- **§37's rate work is untouched** — different quantity, different experiment.

### The shape of it

Three measurements today were rigorous about the instrument and pointed at the
wrong thing (§41's design, the ISO container, §43's prefactor without its span).
This is the fourth and the cheapest: **the instrument was fine, the specimen was
fine, and the axis was mislabelled.** A wrong x-value is not detectable by any
amount of care about y — the machine faithfully reported what byte 107 does,
twice, and the number was filed under 108.

### Corroborated independently, and the low end checked rather than trusted

mpc2emu refitted the same quantity on their own hardware — different session,
different bank, narrowband analysis against the test tone's own frequency rather
than broadband RMS — and expressed it per percent rather than per byte:

    §39 (superseded)    0.547  dB/byte
    here               0.754  dB/byte    R^2 0.9999
    mpc2emu            0.795  dB/byte    (1.010 dB/% x 127/100), R^2 0.996

In the working range the two agree closely: at byte 107 they predict -13.65 dB
against -13.78 / -13.84 measured here on two different banks. Slopes 5.5% apart,
**both ~45% away from §39**. Two projects, different methods, different
observables, landing together and jointly disagreeing with the old value — which
is a stronger claim than either refit could make alone. A single refit replaces
one number with another; two independent ones say the *quantity* is real.

**Their caveat about the bottom of the range is correct, and quantifiable from
this run's own captures.** Sustain level against the silent pre-roll of the same
file:

    SUS 064   6.3 counts   floor 1.79   SNR 10.9 dB
    SUS 072  12.5 counts   floor 1.79   SNR 16.9 dB
    SUS 080  25.1 counts   floor 1.79   SNR 22.9 dB
    SUS 088  50.6 counts   floor 1.79   SNR 29.0 dB

At byte 64 the floor is close enough to inflate the reading, so those points are
the weakest in the set. **Refitting without them barely moves the answer:**

    bytes  64-122   0.7539 dB/byte   R^2 0.99985
    bytes  80-122   0.7550 dB/byte   R^2 0.99966
    bytes  88-122   0.7556 dB/byte   R^2 0.99944

0.2% across the three, and all three predict byte 107 identically. So the
published fit is not being driven by its noisiest points — checked rather than
asserted. The caveat still applies to *extrapolation* below byte 80, where the
two projects' fits diverge to 1.88 dB apart at byte 64 and neither has good
evidence.

---

## §46 — `FEnv+ -> FilFreq` depth: a product, to first order, with real compression (2026-08-22, live)

> **SUPERSEDED IN ITS UNIT BY §56, and the difference is the whole point.**
> This section states the depth in **octaves**. §56 measured 57 points on a
> stationary subject with every corner divided by a wide-open reference and
> found the cord adds a fixed number of **cutoff BYTES** — `delta_byte =
> 0.02506 × level% × amount`, residual 2.1 bytes across five base cutoffs —
> **not octaves and not Hz**. Because the corner is exponential in the byte, an
> octave-based conversion needs a different amount from every different base
> and a byte-based one does not. **Cite §56 for the depth law.** This section
> is kept for its method and for the compression it reports, part of which was
> itself withdrawn (three points on a descending stretch).

**The shift is a product of envelope level and cord amount**, as the AKAI's is
(s3ked §148) — so mpc2emu's conversion is structurally right and needs a
constant, not a redesign. But the product holds only to first order, and the
deviation is systematic rather than noise.

    octaves ~= 5e-4 x level% x amount        (amount 0-100, level 0-100)

At full level and full amount that is ~5 octaves, which on this base cutoff is
already past where the corner leaves the measurable band.

### Method

Stationary noise (§42's artefact), filter 4-pole lowpass, base cutoff `FMORPH`
40, all six envelope segments held at a constant level with rate 0 so the
envelope is a plateau rather than a traversal, and the cord amount stepped.

**The corner is a real frequency, not a proxy.** Each capture's power spectrum is
divided by a REFERENCE capture taken with the filter wide open, which removes
the source's own spectrum, the sampler's reconstruction roll-off and the capture
chain in one step — §42 already showed that roll-off is real (8000-14000 Hz on
file becomes 6700-11900 Hz at the output). The corner is then the highest
frequency still within 3 dB of the passband of that ratio.

**Trap 1 checked before anything else** (s3ked lost nine runs and a disc to it):
amount 0 vs 100 moved the corner 6.68 octaves, so the envelope had distance to
travel and the depth was actually under test. A null there would have meant an
inert envelope, not an inert depth.

**Traverse distance is stated, per §43's lesson:** the envelope sits at a
constant level L for the whole note. Every octave figure is per that L.

### The data

    level  25   0.01488 oct per amount unit   R^2 0.9940
    level  50   0.02445                       R^2 0.9900
    level 100   0.04335                       R^2 0.9922  (amounts <= 60 only)

Base corner with amount 0 was 222.7 / 234.4 / 234.4 Hz across the three levels —
independent of envelope level, as it must be if the cord is the only path from
envelope to filter. That is an internal check the design provides for free.

### WITHDRAWN 2026-08-22, same day: the compression was n=3

**A 12-level grid (132 captures) does not reproduce the monotonic drift below,
and the exponent comes out at a pure product.**

    log-log fit across 12 levels:   k ~ level^0.974      (1.000 = pure product)

    k/level x 1e4, levels 8 -> 100:
      6.03  5.71  6.12  5.68  5.37  5.01  4.69  4.81  5.29  6.19  6.22  5.89

That is **not monotonic**. It dips near level 58 and rises at both ends, total
spread 1.33x. The three levels sampled below (25, 50, 100) happened to land on a
descending stretch of what is scatter, and I read a trend off three points and
called it compression.

Fitted through the origin over the well-conditioned region (shifts <= 3 octaves,
n=106):

    octaves = 5.14e-4 x level x amount      median residual 0.074 oct (7.4%)

Over all in-band points (n=117) it is 5.45e-4 with a median residual of 5.0%.

**The remaining scatter tracks fit quality, not level.** Per-level R^2 falls from
0.999 in the middle of the range to 0.94 at levels 83-100, exactly where the
corner approaches the top of the measurable band and the curve bends — so the
apparent rise in k at the high end is most likely the band edge, not the machine.

**What stands:** it is a product, so the sibling project's conversion structure
is right and the sustain does cancel. **What does not:** the level-dependent
constant, the 37% figure, and the claim that a converter must model compression
below the clamp. A single constant is defensible, with ~5-8% residual.

Also checked, and it is not the apparatus in the way suspected: no capture in
the set clips. The wide-open reference — the loudest capture, and the denominator
every corner is measured against — peaks at **-12.75 dBFS with zero samples at
full scale**, and crest factor holds 3.9-4.5 across all levels with no downward
trend. A level-dependent overload would have shown as falling crest at the loud
end and does not.

### Where it stops being a product

    k / level     5.95      4.89      4.34   x 1e-4      (levels 25, 50, 100)
    spread 32%, and MONOTONIC in level -- not scatter

    ratio at matched amount    L100/L50    L50/L25
      amount 20                   2.20        2.65
      amount 40                   1.97        2.06     <- clean product
      amount 60                   1.74        1.89

At amount 40 both ratios sit within measurement error of exactly 2. Away from
there they drift the same way in both pairs: **the larger the total shift, the
less than proportional it becomes.** That is compression as the corner climbs,
and it is why the level-100 slope is fitted over amounts <= 60 — above that the
corner reached the top of the measurable band (24 kHz, the analysis Nyquist).

**For a converter this matters more than the constant.** A product law
extrapolated past roughly three octaves of shift overshoots, and the E4XT clamps
rather than continuing. Where it saturates is part of the answer, not an
artefact to design around.

### What it settles for the sibling project

mpc2emu writes `SUSTN2` and `depth` from independent source fields and maps the
E4B amount as `amount x 50`. Since the E4XT is a product in the same sense the
AKAI is, that structure is sound and only the constant is in question — the
one-line fix rather than the redesign. The compression above ~3 octaves applies
to both machines' models and is the part most likely to be missing from either.

---

## §47 — Banks merge, and a page that ignores Program Change survives a handover (2026-08-22/23, live)

Two findings from staging a four-bank comparison for the sibling project, one
about the device and one about how a correct machine can still be unusable.

### `Merge` exists, appends in load order, and renumbers nothing

Pressing `Load...` on a bank while RAM is occupied raises a confirmation not seen
when RAM is empty:

    "Destroys current RAM bank... continue?"     Cancel (F1) | Merge (F4) | Load (F6)

**`Merge` adds the bank to what is already resident instead of replacing it.**
Four banks were merged this way and all four stayed available at once:

    bank 1  -> presets  0-9    (10)
    bank 2  -> presets 10-21   (12)
    bank 3  -> presets 22-27   ( 6)
    bank 4  -> presets 28-33   ( 6)

Each bank starts where the previous ended, in load order. **Nothing was
renumbered and nothing was overwritten**, verified by reading all 34 preset names
back off the device after the last merge rather than inferring from bank sizes.
Sample memory tracked it: 128.0 MB free before, 120.7 MB after.

That matters for measurement work: an A/B between banks becomes a Program
Change rather than a two-minute reload, so a comparison can be driven from one
capture path without a load between the two things being compared.

### The page trap survives a handover, and that is the new part

§34 and §36 already record that the E4XT honours Program Change only on its own
main preset page. What tonight added is what happens when a *different operator*
inherits the machine.

The four merges left the device on the disk browser's BANK page. The banks were
resident, the machine was healthy, notes sounded, and Bank Select CCs were
received and had an effect — but **every Program Change was silently dropped**,
so three unrelated presets (a synth bass, a pad, an electric bass) measured
byte-identical. Nothing on screen said why, because nothing was wrong.

    on the browser page              back on the preset page
      PC   0   f598e64e1c              PC   0   04195783fc
      PC  22   f598e64e1c              PC  22   da5b543563
      PC  28   f598e64e1c              PC  28   1b2b242623
      1 distinct screen                3 distinct

**The guard is three seconds and belongs in the handover, not only in the run.**
Send a Program Change, read the screen back, confirm the selection moved. This
project has had that check since §41 and applies it to every capture it takes —
and it was still not applied when declaring the machine ready for someone else,
which cost the sibling project a measurement round and a debugging round.

A machine can be correct, loaded, and answering, and still be incapable of the
measurement about to be taken on it. "Ready" is a claim about the *page*, not
only about the contents of RAM.

## §48 — A load path that cannot fall into the page trap, and what a power cycle leaves behind (2026-08-23, live)

Staging the same four-bank comparison a second time, this time from cold. Both
findings below are about *routes and state*, not about the protocol.

### `Load...` is on the main preset page, and it comes back by itself

§34 reached the disk subsystem through `DISK_BROWSE` (`5Dh`), which is what left
the machine on the browser's BANK page and produced §47's handover failure.
There is a second route, and it is strictly better for anything scripted.

**`F4` on the main preset page opens a compact LOAD dialog** — three fields and
three soft keys, no browser involved:

    +--------------------------------------------------+
    | L |  Drive : D2 <volume>                          |
    | O |  Folder: F000 <folder>                        |
    | A |  Bank  : B001 <bank>                          |
    | D |                                               |
    +--------------------------------------------------+
      Cancel (F1)            Merge (F4)          Load (F6)

- Cursor up/down moves between the three fields; `INC`/`DEC` steps the value.
- Changing **Drive** re-points **Bank** to that volume's `B000` automatically,
  so a wrong-volume load takes a deliberate mistake rather than an oversight.
- `Merge` is offered here as a *button*, not as the confirmation dialog of §47.
  Both exist; they are different screens.
- **On completion the device returns to the main preset page on its own.** That
  is the whole value of this path: the operator never stands on a page that
  ignores Program Change, so §47's trap cannot arise. The screen hash after each
  of four consecutive loads was the preset page's, every time.

Drive and Bank persist between openings of the dialog, so merging N banks off one
volume is `F4`, `INC`, `F4` per bank after the first.

### RAM does not survive a power cycle — and the machine says so honestly

The E4XT was powered down with four banks resident and 120.7 MB free. It came
back with **nothing**: `Untitled Bank`, `P000 Untitled Preset`, 128.0 MB free.

Worth recording as a *negative* alongside a sibling machine's behaviour: the
K2000 in the same rack comes back holding program headers whose sample RAM has
emptied, so a glance at its display suggests a loaded instrument that cannot
sound. The E4XT has no such intermediate state. Empty is empty, and it is
visible on the first screen.

### The empty-RAM placeholder is a real off-by-one hazard

That placeholder `P000` is the reason bank 1 went in with **Load** rather than
**Merge** here. Merging into empty RAM risks appending *after* the placeholder
and shifting every subsequent bank's base by one — which would not fail, it
would silently renumber a comparison whose whole point is that PC number N means
source N. Load destroys nothing when there is nothing resident, and reproduces
the documented layout.

Either way the check is the same one §47 already demands, and it is the only
thing that actually settles it: **read the preset names back off the device and
confirm where each bank starts.** Four banks of 10/12/6/6 landed at 0-9, 10-21,
22-27, 28-33 with 34+ still empty, and the preset-page screen hashes for two
spot-checked slots matched 2026-08-22's recorded values byte for byte.

### A merged bank keeps the first-loaded bank's name, over all of it

The title line at the top of the preset page shows **`MXORIGE4`** — the name of
the bank loaded *first* — above all 34 presets, including the 24 that came from
the three banks merged in after it. There is no per-preset indication of which
bank a preset arrived from.

So in a merged bank the title line is not an attribution. Anyone reading a
result off the screen mid-session would attribute every preset to the first
bank, and be wrong for 71% of them. **The PC number is the only thing that
identifies the source**, which is why the range table above is the artefact that
matters. This is the more expensive of the two findings here: the load path is a
convenience, this one silently mislabels data.

### One more guard worth the fifteen seconds

Preset names prove the *headers* arrived; they do not prove the samples did. One
note per bank at C4, measured as lift over each capture's own pre-roll (§41),
gave +57.3 / +51.9 / +40.6 / +50.3 dB. A listening audit started on a bank whose
samples failed to load returns silence, and silence looks like a result.

## §49 — Voice edits DO reach the audio, and the Voices page shows them (2026-08-23, live)

Both of these correct limitations this project had recorded as facts. They came
out of a live parameter fix on a six-voice, two-layer octave-stacked electric
piano (PC 22 of the comparison bank) whose octave layers had arrived from a
converter mistuned to +98 cents instead of +12 semitones.

### §34's "a layered voice cannot be muted from here" is wrong

§34 established — correctly, and it stays on the record — that writing
`E4_PRESET_VOLUME` (id 1) read back perfectly and **did not move the audio by a
single sample**. From that it concluded that a layered voice cannot be muted
over the editor protocol to isolate another one.

That generalised one parameter to a class it does not belong to.
**`E4_GEN_VOLUME` (id 39), the per-voice level, reaches the audio immediately.**
Setting one voice of a two-voice layer to −96 and capturing, then the other,
separated the layers cleanly:

    voice A alone   -46.83 dBFS
    voice B alone   -40.99 dBFS

So **remote layer soloing works**, and any measurement on a multi-voice preset
can isolate the voice it is actually about. This matters more than it sounds:
it is the difference between measuring a voice and measuring a mix. Restore the
muted voice and read the restore back — the mute is a measurement tool, not a
state anyone should be left holding.

The distinction to carry forward is *preset*-scope versus *voice*-scope
parameters, not "editor writes reach the audio" versus "they do not". Where a
given parameter falls has to be tested, not assumed from either §34 or this.

### The Voices page reflects a remote edit live

CLAUDE.md and the spec both say a parameter edit does not appear on the
device's own LCD until the preset is touched from the front panel, and a TUI
must therefore track its own state model. On the **Preset Edit → Voices-Main**
page that is not what happens: the volume/ctune/ftune columns update **as the
writes land**, with no front-panel interaction at all. Photographed before and
after — the same page, the same six rows, the values changed.

This does not overturn the general rule, and the general rule is still the safe
assumption for a UI. It does mean the machine's own display can be used as an
independent check on what a remote write actually did, on at least one page. An
operator standing at the rack sees the edit.

### Sanity checks that belong to any live edit like this

- **Read the before-state first.** A relayed diagnosis is a claim about the
  device, and the device is right there. If the voices do not look the way the
  report says, the edit is aimed at the wrong thing.
- **Read every value back afterwards**, and report the read-back rather than
  what was sent.
- **A/B the audio**, because §34's case is exactly a write that read back
  correctly and changed nothing audible.
- **Watch for a confounded bin.** The octave layer here lands on the unison
  layer's own second harmonic, so that frequency says nothing about the octave
  layer's level. Isolating the voices was the only way to get a real number —
  the mixed reading would have been a plausible wrong answer, §45's shape
  exactly.

## §50 — The amp envelope's stage order, settled off the machine's own display (2026-08-23, live)

§44 measured the FENV traversal order and said in terms that VENV and AENV were
**not** verified, keeping the spec's interleaved labels for both. VENV is now
settled, and the answer is the boring one: **it uses the same order as FENV.**

    SEG0 = Atk1    SEG1 = Atk2    SEG2 = Dcy1
    SEG3 = Dcy2    SEG4 = Rls1    SEG5 = Rls2

So SEG3's target level is the sustain for the amplitude envelope too, and the
old labels had "Atk2" sitting on it. `eos/params.py` ids 70-81 corrected.

### How, and why it did not need another audio measurement

§44 cost a day of captures because the question was *what does the hardware do*.
This one is *what does the hardware call them*, and the machine will simply say:
**Preset Edit → Voices → `EditVce` → the Amp/Filt page group draws both
envelopes**, six labelled rate/level pairs and a plot of the resulting shape.

The mapping was NOT read off the page's two-column layout — that layout is
ambiguous about whether the columns run down or interleave. Each displayed pair
was matched to the value read back over SysEx for a specific segment id, on a
preset where the pairs are distinct enough to make the matching unique
(`Atk2` = 0/100 could only be SEG1; `Dcy2` = 0/96 could only be SEG3). Both
envelopes were checked independently and agree.

**AENV (ids 117-128) is still unverified** and keeps the old labels. One visit
to the Lfo/Aux page group settles it the same way.

### The graphical envelope page is a cross-check worth remembering

The page plots the envelope, not just its numbers. For comparing this machine
against another manufacturer's — which is what prompted the trip — a picture
sidesteps having to agree on units first, and it caught something the numbers
had already implied but did not make obvious: a decay stage with a **high** rate
byte (87, and higher is slower here) that travels only from level 100 to level
96. The slowest stage in the envelope is also completely inaudible. Read as
numbers that looks like a long decay; drawn, it is a flat line.

That is worth stating as a general caution, because it is the same trap as
§41's: **a rate byte is a time constant, and the elapsed time depends on the
distance the segment has to travel.** Neither number means anything alone.

### Panel navigation, for the next person

    PRESET_EDIT (5Ah)        -> Voices-Main, one row per voice
    CURSOR_UP / CURSOR_DOWN  -> choose the voice row (rows scroll past 4)
    F6                       -> EditVce, entering that voice's editor
    PAGE_PREV / PAGE_NEXT    -> within the Amp/Filt group:
                                Amp Envelope | Filter | Filter Envelope
    PAGE_EXIT (5Eh)          -> back to Voices-Main; twice to the preset page

The voice editor **remembers the last page visited**, so stepping voice to voice
lands on the same page each time and the per-voice cost is one exit, one cursor
move and one `F6`.

And the rule from §47 applies to this trip too: the preset editor is not the
main preset page, so **Program Change is ignored while you are in there.** Exit
all the way back before handing the machine over, and confirm by hash.

## §51 — Filter type ids confirmed; and a slope change that was inaudible for a reason (2026-08-23, live)

### `FILTER_TYPE_NAMES` position mapping, confirmed

`eos/params.py` transcribed the 21 filter-type names from the manual and carried
an explicit caveat that **id == list position was an assumption**, with the check
that would settle it written into the comment. Done:

    id 0  ->  panel reads "2 Pole Low-pass"
    id 1  ->  panel reads "4 Pole Low-pass"
    id 3  ->  behaves as a highpass: fundamental -15.6 dB, 3-6 kHz +12.6 dB

Three of twenty-one, but at both ends of the low run and across a type-family
boundary, so what is confirmed is the *positional* mapping rather than three
individual names. The rest stay transcription and the same one-line check
settles any of them.

> **Superseded by §36, five days earlier than this paragraph reads.** §36
> confirmed **16 of 16** against the machine's own display — 14 exact, 2
> abbreviated, 0 disagreements — so "three of twenty-one" understates what is
> known. Only runtime 17–20, the morphing filters, remain unconfirmed, and
> runtime 0 stays ambiguous because `2-Pole Lowpass` is both the table's id 0
> and the documented rendering of a *rejected* byte.

**Spot-checked again 2026-08-25 on third-party authored content.** A bank loaded
read-only from the machine's own disc: `E4_VOICE_FTYPE` (**parameter id 82**)
reads **value 1** on a voice the sibling project decodes as a 4-pole lowpass, and
the panel prints `Filter  4 Pole Low-pass` for that same voice. Its cutoff page
printed `Frequency: 20000Hz` at cutoff byte 255 — **the panel's nominal figure,
not the corner**: §52 measured the printed cutoff as 2.0–2.1× off the real corner
at the dark end, and it must not be lifted as a top-end calibration anchor. It is
recorded here only as the display accompanying the filter name. One more row
agreeing with §36's table, on content neither project authored.

**It was reported to the sibling as a disagreement first, and that framing was
half wrong.** Reporting the raw mismatch was right; calling the two numberings
"the same scale offset" was not, and **§36 already had the answer.** The E4B
`vpar[58]` byte is a **grouped code** — family in the high nibble, member in the
low — not an index into anything: `0x00`→1, `0x02`→2, `0x08`→3, `0x10`→5,
`0x40`→11. There is no scale relating a stored byte to a runtime id, and §36
warns specifically that treating it as a sequential filter number yields a
plausible byte from an unrelated family or one that silently degrades to 2-Pole
Lowpass.

So the correct statement of the case is: **eosed runtime id 1, E4B stored byte
`0x00`, both displayed by the machine as `4 Pole Low-pass`** — three names for
one filter, related by §36's table and by nothing simpler.

*A disagreement about a number is not a disagreement about the thing until both
sides state which encoding they are quoting* — and a report that omits a mapping
its own project has already measured is reporting less than it knows.

### A real defect that was completely inaudible, and the reason matters

A sibling project's AKAI reader never assigns a filter type, so every converted
voice landed on the 4-pole (24 dB/oct) where the source machine's filter is
2-pole (12 dB/oct). Genuine, documented mismatch. Setting all six voices of a
converted preset from 4-pole to 2-pole and measuring:

    body (300-1300 ms)   -0.8 to +0.8 dB in every octave band, every note
    onset (0-150 ms)     scatter, no pattern

against a prediction that the difference should grow ~12 dB per octave above the
corner — tens of dB by 6 kHz on a 65 Hz corner. Measured about one.

**The null was not accepted without a control.** §34 is a case on this exact
device of a write that read back perfectly and never reached the audio, so
"nothing changed" has two very different explanations. Setting a 2nd-order
highpass instead moved the fundamental -15.6 dB and 3-6 kHz +12.6 dB: filter type
writes do reach the sounding voice, and the null is real.

**Why it is null:** the preset's filter envelope amount was saturated, sweeping
the corner far above the sample's content for most of the note. When the corner
is above everything present, 12 dB/oct and 24 dB/oct below it sound identical.

The generalisable part is the ordering, and it is a trap worth naming: **two real
defects where the first masks the second will, if fixed in the wrong order, make
the wrong fix look like the one that worked.** Here the slope fix is inaudible
until the envelope amount stops holding the filter open — so fixing the amount
first, then the slope, is the only order in which either result means anything.

### Also, in passing: the panel is the arbiter of the cutoff law

The converted unison layer was predicted from the sibling's law to sit at 138 Hz.
The device's Fc/Morph byte is 4 and its own Filter page reads **65 Hz** — a factor
of about 2.1. Worth recording next to §50's open ~1.9x between two candidate
envelope-rate laws: two different conversion laws, both out by about two, both at
the dark/fast end of their range. That may be one shared bug rather than two, and
is a cheaper thing to look for than either discrepancy alone.

## §52 — The filter, measured: id 84 is Q, the panel's Hz is not the corner, and both resonances clamp at 112 (2026-08-23, live)

A calibration run on a white-noise preset — flat, non-decaying, played at its
root key so nothing is resampled — with every capture divided by a wide-open
reference so the sampler's own output roll-off comes out of the answer (§41).

### `E4_VOICE_FKEY_XFORM` (id 84) is the resonance control

The spec's name for id 84 is "meaning varies by filter type", and nothing in
this project or the sibling's file layout named it. Ids 85-92, the ones labelled
"filter-type dependent", move the panel's `Q` field **not at all**. Id 84 does,
and the panel prints it 1:1 — set 46, panel reads 46, over the whole 0..127.

So on the lowpass types **id 84 is Q**. Identified the same way §51 settled the
filter-type ids: set it, look at the machine, put it back.

### The panel's printed cutoff is NOT the corner, and is wrong at the dark end

| Fc byte | panel prints | measured −3 dB | slope |
|---|---|---|---|
| 0 | 57 Hz | 118 Hz | −12.7 |
| 4 | 65 Hz | 129 Hz | −12.9 |
| 15 | 87 Hz | 182 Hz | −12.8 |
| 32 | 135 Hz | 237 Hz | −12.7 |
| 64 | 294 Hz | 398 Hz | −12.6 |
| 100 | 669 Hz | 689 Hz | −12.3 |

The panel is out by **2.0-2.1x at the bottom**, converging to agreement by byte
100. Look at what it prints down there: 57, 59, 61, 63, 65, 67, 69 — **linear,
2 Hz per byte** — while the real corner is exponential throughout. The display
is wrong, not the filter.

This is a trap with an innocent appearance: anyone calibrating a conversion law
by reading the machine's own screen inherits a factor of two at the dark end and
nothing at the bright end, which is far harder to spot than a constant error.
**Measure the corner; do not read it off the panel.** It also cost this project
a wrong claim to a sibling — a converter law was reported as "2.1x too dark" on
the strength of a panel reading, and was in fact correct to 7%.

**The slope column is the trust boundary.** It holds −12.7/−12.8 through byte 64
and degrades to −7.7 by byte 220 — that is the fit running out of spectrum above
the corner, not the filter changing. Points above byte ~120 are not usable.

> **AMENDED 2026-08-24 — that last sentence was too broad and a sibling project
> was entitled to lean on it harder than the data deserved.** The boundary is
> correct for the **slope** and wrong for the **corner**. §60 re-measured the
> region directly: interpolating this table across the gap gives 931 / 1145 /
> 1950 Hz at bytes 119 / 135 / 179 against a measured 918 / 1092 / 2003 — 1.4%,
> 4.9% and 2.6%. **The corner column is usable across the whole range;** only
> the slope column stops at byte ~120.

12 dB/oct confirmed for the 2-pole; the 4-pole measured −20 to −24 dB/oct, and
its corner sits 10-20% below the 2-pole's for the same byte.

### Resonance: one calibration covers both filter types, and both clamp at 112

Peak height above the passband, corner parked at ~1300 Hz:

    byte     0    16    32    48    64    80    96   108   112   127
    2-pole +0.1  +1.4  +3.8  +6.1  +9.2 +11.9 +14.4 +15.5 +17.8 +17.8
    4-pole +0.1              +18.3       +28.7 +31.1 +35.5 +35.5

**The 4-pole's peak in dB is exactly twice the 2-pole's at the same byte** —
ratio 2.00, 2.00, 2.00, 1.99, 1.99 at every point measured. That is what
cascading two identical sections does, and it means one measured curve times
`poles/2` covers the family. No per-type calibration matrix is needed.

**Both types clamp at byte 112.** Everything from 112 to 127 measures the same
filter, flat within noise, while the panel goes on printing the number set. A
writer that clamps its own output to 127 is silently writing 112, and fifteen
steps of range do not exist.

**No self-oscillation anywhere**, including a +35 dB peak at the top of the
4-pole. Checked rather than assumed: a filter ringing on its own puts energy in
the capture *before* the note is sent, so every point recorded its pre-roll
level. All sat at −85 to −86 dBFS.

Converting through the 2-pole relation `|H|peak/|H|0 = Q/sqrt(1 - 1/(4Q^2))`,
**the 2-pole tops out at Q ≈ 7.8**. Anything asking for more gets the ceiling,
and two different requested values above it become the same filter.

### And the §47 trap again, in this project's own run

The resonance A/B on a second preset captured six files of silence: the panel
was still parked in the noise preset's filter editor from this calibration,
Program Change is ignored there, so every note went to the wrong preset and
landed outside its zones. The parameter writes were unaffected — they address
the edit context, not the sounding preset, and read back correctly — but the
audio was of something else entirely.

Two hours after writing §47 up, and `lift_db` caught it where a peak/clip guard
would not have. **Assert the selection on the device's own screen before
recording, not after.** The re-run does exactly that and refuses to proceed on a
hash mismatch.

## §53 — Modulation cords SUM: depth beyond one cord is reachable (2026-08-23, live)

A cord's amount tops out at ±100. That is not the ceiling on how much a
destination can be modulated: **two cords with the same source and destination
add, and their sum is indistinguishable from a single cord of the summed
amount.**

Measured on the single-voice noise preset, 2-pole, Q 0, base cutoff at Fc byte 0
(~118 Hz measured), each capture divided by a wide-open reference:

| cord 0 | cord 1 | corner | octaves over base |
|---|---|---|---|
| 0 | 0 | 111.6 Hz | −0.08 |
| 37 | 0 | 613.6 Hz | +2.38 |
| 0 | 37 | 613.6 Hz | +2.38 |
| 37 | 37 | 2186.5 Hz | +4.21 |
| **74** | **0** | **2186.5 Hz** | **+4.21** |
| 37 | 74 | >19 kHz | saturated |

`37 + 37` and `74 + 0` land on the same frequency to the resolution of the
measurement. The slot used does not matter and the destination does not pick a
single winner.

So a driver that needs more depth than one cord provides should **allocate a
second cord** rather than clamping. Nothing about this is specific to
`FEnv → FilFreq`; it is a property of the modulation summing.

### The trap that made this take three attempts

The first two attempts measured a filter that was **already fully open**, and
therefore could not distinguish "the cords sum" from "the second cord is
ignored". A voice with a 2.1 kHz base cutoff reaches past the machine's own
11.9 kHz output roll-off (§41) at a depth of only 37 units, so 37, 100 and 137
all sound identical — and reporting that as "they do not sum" would have been a
false negative with a clean-looking table behind it.

**A saturated instrument cannot report a difference.** The question only became
answerable by moving it to a low base cutoff where the sum still lands inside
the audio band. Same family as §51's null and §45's mislabelled axis: the
measurement was fine, the operating point was wrong.

(The first attempt had a second fault on top: the test note sounded two voices,
and the untested one was 6 dB louder and swept its own filter wide open at the
same instant. An in-preset "control" is only a control if the thing being
measured is audible over it.)

### A consequence worth stating separately

Reaching further does not mean hearing further. On a voice whose corner is
already past the output roll-off at the smaller depth, the extra octaves land
entirely outside the audio band and change nothing audible. Depth headroom is
worth having for correctness; it is not automatically worth having for tone.

### §46's depth constant does not survive contact with this base, and the replacement is not known either

§46 fitted `octaves ≈ 5.14e-4 × level% × amount` on the **4-pole** from a
different base cutoff. Against the 2-pole from Fc byte 0:

| amount | §46 predicts | measured | oct per unit |
|---|---|---|---|
| 37 | 1.90 oct | **2.38 oct** (614 Hz) | 0.0643 |
| 74 | 3.80 oct | **4.21 oct** (2187 Hz) | 0.0569 |
| 100 | 5.14 oct | **>7.38 oct** (>19.6 kHz) | — |

The first two points alone would say "about 20% more, and slightly compressive".
They also extrapolate to 5.69 octaves at amount 100 — about 6 kHz — and the
machine delivers **more than 19 kHz**. So the relation is superlinear near the
top, or something else changes above ~74, and two clean points plus a lower
bound cannot distinguish those.

**Use none of the three numbers.** Not §46's 5.14, not the 0.057 oct/unit these
points suggest, and not 7.38 except as a lower bound. A real depth law needs its
own run at a base low enough that amount 100 still lands inside the audio band —
and byte 0 *is* the bottom of the cutoff range, so that run needs a different
approach rather than more points.

The practical consequence is the useful part: **one cord at full depth already
clears the audio band from a ~120 Hz base.** Any voice sitting that dark is
saturated at a single cord, and no amount of extra depth is audible on it.

## §54 — A saturated instrument cannot report a difference (2026-08-23)

Not a new measurement. A rule, promoted out of §51 and §53 because it caused
**four** null results in one evening, in four different guises, and each time the
null looked like a clean answer:

1. **Filter slope.** 4-pole to 2-pole moved the audio ~1 dB where the argument
   predicted tens. The filter envelope held the corner above the sample's
   content, so both slopes passed everything (§51).
2. **Filter envelope decay.** Halving the decay time changed nothing, for the
   same reason: after the corner is up, how fast it got there is invisible.
3. **A second modulation cord, on a bright voice.** From a 2.1 kHz base, depth
   37 already clears the machine's 11.9 kHz output roll-off, so 37, 100 and 137
   are one sound (§53).
4. **The same cord test on the dark voices**, chosen precisely because 129 Hz
   looked unsaturated. It is not: one cord at full depth reaches past 19 kHz
   from that base, which the noise table already said and nobody applied.

The shape is always the same. **A control that is already at its limit produces
a flat, confident, meaningless null** — and a flat null is much easier to
believe than a noisy signal, which is what makes it dangerous.

### What to do about it

- **Before running an A/B, ask what the control's range is at this operating
  point.** Not its range in principle: at the base cutoff, envelope depth and
  filter type actually in use.
- **Prove the control has authority before trusting a null.** §51's highpass
  probe is the pattern: ask the parameter for something that *cannot* sound the
  same, and confirm it does. A null without that step cannot distinguish "no
  effect" from "no effect reached the audio".
- **Move the operating point rather than adding points.** §53's question only
  became answerable at a base cutoff low enough that the answer landed inside
  the audio band. More repetitions at a saturated point buy nothing.
- **When the prediction and the measurement disagree, check whether the
  measurement had room to agree.** Three of the four above were predicted by
  numbers already in this file.

Related: §41 (a guard that passed thirty captures of silence), §45 (a
mislabelled axis producing a clean-looking law), §51, §53.

## §55 — The assign group is note allocation, not a mute group (2026-08-23, live)

Asked because a sibling project traced a percussive artefact on an AKAI S3000XL
to its **keygroup mute group**: one note starts two keygroups and the second
silences the first, leaving a ~10 ms burst of the first layer. The question was
whether EOS can express that.

**It cannot.**

### The field exists, and it is not what its name suggests

`E4_VOICE_ASSIGN_GROUP` (id 66, range 0-23) is the only candidate: values 0-14
are Poly variants, **15-23 are Mono A..I**, nine independent groups. The sibling
project's own E4B format notes map it to `vpar[27]` and call it a "choke group".

Measured on a two-layer preset whose voices 0 and 1 both sound at one note:

    both voices set to Mono A, single note   ->  +0.13 dB
    10 ms envelope                           ->  no step anywhere

Both layers keep sounding. There is no choke.

### The control that makes that null mean something

A null about a group setting is worthless until the group is shown to have
authority (§54). Measured on the noise preset — one voice, flat, no decay of its
own — with two overlapping notes 600 ms apart:

| assign group | note 1 alone | both held | rise |
|---|---|---|---|
| Poly All | −46.2 dB | −43.2 dB | **+2.99 dB** |
| Mono A | −45.7 dB | −46.4 dB | **−0.68 dB** |

+3 dB is two incoherent sources summing, exactly as it should be. Mono A gives
no rise at all: the second note steals the first. **The group works perfectly —
it is voice allocation across NOTES.** Two voices under one note are not in
competition with each other, so a Mono group does not separate them.

### Solo Mode, and the two combined — also null, also controlled

`E4_VOICE_SOLO` (id 65: Off / Multiple Trigger / Melody last-low-high / Synth
last-low-high / Fingered Glide) was tested the same way, alone and stacked on
Mono A. Single note, both voices, median level against the untouched baseline:

| setting | 50 ms – 1.0 s | first 100 ms |
|---|---|---|
| Multiple Trigger | +0.50 dB | −0.42 dB |
| Multiple Trigger + Mono A | +0.57 dB | −0.06 dB |
| Synth (last) + Mono A | +0.54 dB | +0.33 dB |

The ~+0.5 dB is common to cases sharing no setting, so it is capture variation.
Both layers keep sounding in all three.

And both solo modes carry their own control, on the noise preset, two
overlapping notes:

    Solo Off          rise when the 2nd note joins   +3.07 dB
    Multiple Trigger  rise                           -0.52 dB   steals
    Synth (last)      rise                           +0.09 dB   steals

They do exactly what the manual says — stop a second NOTE sounding — and have no
opinion about two voices allocated by one note-on.

Nothing else in the parameter table is a candidate. `GROUP_SELECT` (id 227) is
an editing selector, not a routing field.

### The manual says why, and it matches

EOS 4.0 p340, Assign Group: *"assign a certain number of output CHANNELS to each
voice… Voices will ROTATE WITHIN THEIR ASSIGNED BIN of channels… Mono A-I: Nine
monophonic channels. Any voices assigned to the same letter interrupt each
other"*, with the example of *"an open high hat… cancelled by a closed high
hat"* — two different keys. p338, Solo Mode: *"prevents more than one NOTE from
sounding at once"*.

**Both mechanisms key off a new note-on contending for something.** One note-on
that starts two voices creates no contention at either level, so neither fires.
That is precisely why "any voices assigned to the same letter interrupt each
other" reads as though it should apply here, and does not — and why the
widely-given advice to pair Solo Mode with Assign Group is correct for the
hi-hat case and irrelevant to this one.

### How firmly this is closed

Three legs: the assign group measured with a control, both solo modes measured
with controls both alone and combined, and the manual describing both purely in
terms of notes. What is **not** claimed is that nothing in EOS can do it — two
fields were tested and two manual sections read, which is not an exhaustive
search of the format.

### Why it is worth writing down

A converter targeting E4B will find a field called a choke group, set it, and
produce a preset that measures correct and sounds wrong — the same shape as the
four saturation nulls in §54, arrived at from the opposite direction. **The
capability is real, the name is apt for what it does, and it does not do this.**

The wider lesson is about where an evening goes: every filter parameter tried
against that artefact measured correct and sounded insufficient, because the
mechanism being modelled was not the mechanism producing the sound. Before
tuning parameters to chase a difference, establish what produces it. A
capability question answered early would have retired a filter type test, a
filter envelope decay test, two cord-depth tests and a resonance calibration as
irrelevant to the symptom — all of which produced good measurements of the wrong
thing.

## §56 — The FEnv→FilFreq depth law: linear in cutoff BYTES, not octaves (2026-08-24, live)

57 points on the noise preset, 2-pole, Q 0, envelope parked at level 100 so the
cord amount is the only variable, every corner divided by a wide-open reference
taken at that same base.

### The law

    delta_byte = 0.02506 × level_percent × amount

41 unsaturated points across five base cutoffs, residual RMS **2.1 bytes**. At
level 100 that is `delta_byte = 2.506 × amount`; fitted with a free intercept it
comes out `2.5318 × amount − 1.53`, so the origin sits where it should.

**The cord adds a fixed number of cutoff BYTES.** Not octaves, not Hz.

### The base-dependence question, answered

| base byte | slope | points |
|---|---|---|
| 0 | 2.5101 byte/unit | 19 |
| 12 | 2.5179 | 7 |
| 32 | 2.5094 | 6 |
| 64 | 2.4536 | 5 |
| 100 | 2.4486 | 4 |

**It does not depend on the base.** Five bases agree to about 2.5%, and the two
low ones have the fewest points and the highest corners, where inverting
byte↔Hz is least reliable.

In *octaves* the same data looks strongly base-dependent — 0.0917 oct/unit from
byte 0 against 0.0542 from byte 100, a factor of 1.7 — and every bit of that is
an artefact of the byte→Hz curve not being a pure exponential. Picking the wrong
unit turned a constant into a function of the base.

### Level and amount really are a product

Four envelope levels at amount 60, base byte 0, converted back to bytes:

    level  25 -> byte  38.9      level  75 -> byte 109.1
    level  50 -> byte  74.7      level 100 -> byte 147.8

1.4754 byte per level-unit through the origin, i.e. 2.459 byte per amount-unit
at level 100 — matching the amount sweep's 2.506 to 2%.

### Saturation is the cutoff range, not the cord

Every saturated point predicts `base_byte + 2.506 × amount ≥ 250.3`; every
unsaturated one predicts `≤ 238.1`. No overlap. The cord is not clamping —
the cutoff byte is running out of range at 255.

**One cord at full depth is worth 250.6 bytes of a 0..255 range**, so it spans
essentially the whole cutoff range from any base, and overflow to a second cord
(§53) does not arise for this destination. It remains real for others.

### Why this matters beyond the number

A sibling converter shipped `octaves = 5.14e-4 × level% × amount` — the right
*form*, a clean product, in the wrong *unit*. Three voices of one preset needed
cord amounts of 32, 15 and 39 to put their corners in the same place, which
looked like evidence that the law was base-dependent and unpredictable. Through
this law those three land on bytes 215, 217 and 217: one constant, three bases.

Those three amounts were chosen earlier the same night by direct measurement,
with no law involved. That they collapse onto one byte offset is the strongest
check available here — the calibration reproduces what independent measurement
already picked.

**The inverse, which is the thing to put in code:**

    amount = clamp(round((target_byte − base_byte) / 2.506), 0, 100)

with `target_byte` from §52's cutoff calibration — *not* from the panel's
printed Hz, which is wrong at the dark end.

### A limitation of the method, recorded because it was asked for

The two-independent-readings discipline of §52 could not be applied here. The
panel's Filter page shows the **static Fc parameter**, not the modulated corner,
so it prints the same value at every cord amount. It is a real second reading
for each base and was recorded that way, but nothing on the machine displays the
quantity this section calibrates.

### Independently refitted, and what the disagreement showed

The sibling project refitted the same 57 raw points from scratch — doing the
Hz→byte inversion themselves in log-Hz rather than reusing the converted
numbers — and got **2.480 against 2.506, agreeing to 1.0%**. Per-base slopes
2.334 / 2.554 / 2.519 / 2.384 / 2.441: base-independence confirmed by both fits.

The interesting part is where the two fits *disagreed*. Their residual RMS was
**23.7 bytes against 2.1**, because they extrapolated the byte↔Hz curve above
byte 100 — past the trust boundary §52 draws from the measured slope column.
Inside the boundary the fits agree; outside it, the same data turns to noise.
That is the boundary earning its keep, and it is a better argument for stating
one than any amount of prose about it.

### The AKAI end, for the record

Measured in parallel by a third project on the same kind of source: the AKAI's
depth is linear at 0.002612 octaves per `SUSTN2 × depth`, and **its corner has a
hard ceiling at 7.86 kHz** (eight points, two bases, 1.6% spread).

That closes the account of the whole evening. The converter's old constant asked
for a corner past 19 kHz; the source machine parks at 7.86 kHz. Every filter
parameter tried against the symptom measured correct and sounded insufficient
because the corner was already above everything the material contained — §54's
saturation rule, arrived at from the other end and confirmed on the source
machine rather than on this one.

## §57 — The amplitude envelope's audible floor: rate 0 closes before any sound leaves (2026-08-24, live)

A decay-to-silence at the fastest rate the envelope offers produces **nothing at
all**, not a very short burst. Measured on an isolated voice with `Dcy1` level 0
and the rate swept, against the capture's own −84 dBFS noise floor:

| Dcy1 rate | burst | peak |
|---|---|---|
| 0 | **silent** | −73.7 dBFS |
| 1 | **silent** | −74.2 |
| 2 | 0.0 ms | −65.1 |
| 3 | **13.4 ms** | −50.8 |
| 5 | 16.6 ms | −41.9 |
| 8 | 17.0 ms | −37.0 |

**Rate 3 is the first usable rung.** Rates 0 and 1 close the envelope before any
audio leaves the voice; rate 2 is 15 dB below rate 3 and 0 ms long, so it is not
a near miss.

**The peak climbs with the rate, not only the duration.** A slower decay lets
more of the attack transient out before the envelope reaches zero, so choosing
too fast a rate loses the burst's amplitude as well as its length. That is why
the gap between rate 2 and rate 3 is a cliff rather than a slope.

Reproducible: an independent run at rate 3 measured 13.7 ms at −50.7 dBFS
against 13.4 ms at −50.8 dBFS.

### Why it matters, and the shape of the mistake

A converter asked to render a ~10 ms cut computes a decay faster than the rate
byte can express and clamps to the fastest available — rate 0 — which is the
correct instinct and the wrong result, because the fastest available rate is
*before any sound*. The layer disappears entirely: 24 dB of missing content
presented as a fix.

**The nearest EXPRESSIBLE value is a better approximation than the nearest
representable one.** Clamping should stop at the audible floor, not at the
numeric one. The sibling project now floors this at rate 3, gated on "a decay
was asked for AND the sustain is zero" — a rate 0 into a real sustain is a
legitimate instant jump and must stay one.

### And a withdrawal, because it is the same lesson twice

The first pass at this reported "a 4.3 ms burst at −73.9 dBFS". That was the
peak of the noise floor across a 3.5 s file, with the onset detector locking on
to sample zero because there was no onset to find. It was caught by printing the
level in fixed windows instead of trusting the summary number — the same
correction that separates §41's thirty silent captures from a real measurement,
and the same one that withdrew four findings on 2026-08-22. **A summary
statistic computed over a file with nothing in it still returns a number.**

## §58 — LFO→Pitch depth is linear and waveform-independent; and an estimator that lied (2026-08-24, live)

Sixteen captures on a sustained ~330 Hz partial, cord amount swept from 1.57% to
25.2% of full scale, each shape measured over the same amounts in one session.
Depth read from the instantaneous frequency of the isolated partial (bandpass →
analytic signal → unwrapped phase → derivative).

### The LFO waveform does not change the peak excursion

One-sided cents, derived from the **modulation fundamental** with each shape's
own Fourier factor applied (`4/π` for a square, `8/π²` for a triangle):

| amount | % of scale | triangle | square | ratio |
|---|---|---|---|---|
| −2 | 1.57 | 30.1 | 30.4 | 0.993 |
| −4 | 3.15 | 53.2 | 53.2 | 1.000 |
| −6 | 4.72 | 87.5 | 88.0 | 0.995 |
| −8 | 6.30 | 110.5 | 111.0 | 0.996 |
| −12 | 9.45 | 168.0 | 164.4 | 1.022 |

Mean 1.001. A calibration taken with one waveform transfers to another.

**Two waveforms whose harmonic content differs completely, agreeing to 1% on the
derived peak, is also the strongest available validation of the estimator** —
and it is what exposed the one below.

### The response is linear well below any previous calibration

Eight triangle points over 1.57–25.2% fit `cents = 16.362 × pct + 7.38`,
residual RMS 8.2 cents, with no curvature. A sibling's constant fitted over
25–100% and extrapolated down predicts values whose ratio to these runs 0.891 to
1.086, mean **1.006**. The extrapolation was justified; it simply had not been
checked.

The one real caveat is the intercept. A fit with a free constant term gives
+9.00 cents at zero cord, which cannot be true, and that intercept is the entire
disagreement at the bottom: at 1.57% it overshoots by 11%. Above ~3% it stops
mattering.

### The estimator that lied, and why it looked like the safe one

This section's first result was "the depth is 19% more than predicted". It was
not. That figure came from a **2nd/98th-percentile range of the instantaneous
frequency**, chosen precisely because it "assumes nothing about the waveform".

It assumes something worse: that the tracker's excursions belong to the signal.
It collects the phase-tracker's overshoot at the triangle's corners and the
sample's own pitch wobble adding at the extremes. At one amount it reported
180–189 cents peak-to-peak where the fundamental-derived figure is 175.

**A shape-agnostic estimator is not automatically an unbiased one.** The
percentile range makes no assumption about the modulation and a large one about
the measurement chain. The fundamental-amplitude estimator makes an explicit
assumption about shape — which is testable, and was tested, by two shapes
agreeing to 1%.

The general form, and it is not §54's: there, a null was empty because the
*control* was saturated. Here a positive result was inflated because the
*instrument* was reporting its own artefacts. Both look like clean numbers.
**Prefer the estimator whose assumption you can test over the one whose
assumption is hidden.**

### Data limits

The square becomes untrackable above amount −12: at −32 it reports 7.92 Hz,
double the true rate, because the pitch steps carry the partial out of the
±70 Hz analysis band. Those points are recorded and flagged, and must not be
fitted. The triangle tracks cleanly across the whole sweep.

## §59 — A vibrato-depth instrument that cannot make an octave error (2026-08-24)

Built because both projects' phase-tracking estimators fail the same way: they
must decide which partial to follow, and when the deviation grows the partial
walks out of the analysis band and the tracker reports the artefact instead of
failing. §58 records this project's version (7.92 Hz reported for a 3.73 Hz
modulation); a sibling's sweep produced 649, 577, 558, 547, 543, 524, 570, 305,
516 cents with the tracked fundamental collapsing and sticking.

`~/temp/e4xt_ref/sideband.py`. Reads a WAV, returns a result or a refusal.

### The estimator

Frequency modulation puts sidebands around each harmonic at multiples of the
modulation rate. **The power-weighted variance of the spectrum about the carrier
is the mean square frequency deviation**, for *any* periodic modulating
waveform — so the RMS deviation needs no assumption about shape at all. Only the
conversion to a *peak* needs one (√2 sine, √3 triangle), and both are reported
alongside the RMS.

Inverting the first sideband ratio `J₁(β)/J₀(β)` was rejected: it is
non-monotonic and diverges near `J₀`'s zeros at β = 2.405 and 5.52, and a ±88
cent vibrato at 3.73 Hz on a 330 Hz carrier sits at β = 4.5, between them.

No fundamental is ever estimated, so an octave error has nowhere to enter.

### Two bugs that had to be fixed before it was exact

- **The moment must be taken in cents, not Hz.** Modulation is exponential in
  frequency — ±88 cents on 330 Hz is +16.9 Hz up and −16.1 Hz down — so a
  linear-frequency moment overweights the up-excursion and read 3.5% high. In
  log-frequency the bias disappears entirely.
- **A pure tone does not give zero variance.** The analysis window has a width
  of its own, and at small depths that width *is* the answer: 5 cents read +38%.
  The bias is now computed by pushing an unmodulated tone through the identical
  pipeline and subtracted, rather than assumed.

Amplitude modulation is divided out first — a decaying note is AM, and its
sidebands land in the same place.

### Measured accuracy

| condition | error |
|---|---|
| 5–150 cents, sine and triangle | ±0.0% |
| square (RMS) | −1.5% at 25, −0.9% at 88 |
| noise down to 6 dB SNR | +1.3% |
| 0 dB SNR | +4.9% |
| amplitude decay to 0.7 s | ±0.0% |
| decay 0.35 s | +2.5% |

### What it refuses, and the ceiling that is structural

It returns a refusal with a reason for: carrier-to-noise under 12 dB; sideband
energy reaching the edge of the integration band; a modulation rate under 2.5
FFT bins in a sub-window; and a required band that would reach the neighbouring
harmonic.

That last one is a **hard ceiling of about 200 cents RMS on any harmonic-rich
source**, and playing a different note does not move it — sidebands spread as
3×deviation while the neighbouring harmonic sits one carrier away, and the
deviation scales with the carrier:

    carrier  150 Hz -> ~171 cents      carrier  660 Hz -> ~217 cents
    carrier  330 Hz -> ~204 cents      carrier 1000 Hz -> ~222 cents

A measurement needing more than that has to be restructured, not retried.

### Peak-picking cannot find the carrier

At large modulation index the spectrum has a **dip at the centre** — `J₀` passes
through zero — and the tallest component is a sideband. On real captures that
dragged the carrier estimate from 330 Hz to 444 Hz. The carrier is now the
cluster's power centroid, iterated, which does not care which component is
tallest.

### The two estimators disagree by 8% on real signal, and both are right

Cross-checked against §58's captures: sideband/phase-fundamental = **1.085**
(triangle, 5 points, spread 1.083–1.088) and **1.074** (square, 4 points).
**Both estimators are exact to ±0.0% on synthetics**, so this is a property of
the signal, not of either method — and the extra was traced to the modulation's
own harmonics rather than to drift.

They measure different things. The moment counts all spectral spread in the
band; the phase-fundamental counts only the component at the modulation rate.
**For calibrating a depth field the fundamental-only estimator is more
selective; for "how far does the pitch actually move" the moment is right.**
Pick per question, and do not average them.

## §60 — The cutoff table re-measured where it is used, and a trust boundary that was too broad (2026-08-24, live)

§52 swept the cutoff range and told the reader to trust bytes 0–100. Real
converted programs put their cutoffs at bytes 119–179 — entirely inside the
region that warning covered — and two tables disagreed there by 26–39%. Two
extrapolations disagreeing is not evidence about either, so the region was
measured directly.

Noise preset, 2-pole, Q 0, cord zeroed, every capture divided by a wide-open
reference. **−3 dB crossing**, model-free:

| byte | measured | §52 | byte | measured | §52 |
|---|---|---|---|---|---|
| 4 | 128.8 Hz | 129 | 128 | 1001.4 Hz | — |
| 64 | 397.4 | 398 | 135 | 1092.0 | — |
| 80 | 515.4 | 516 | 145 | 1298.6 | 1300 |
| 100 | 687.9 | 689 | 160 | 1589.6 | — |
| 110 | 772.2 | — | 179 | 2002.7 | — |
| 119 | 918.3 | — | 195 | 2523.3 | 2526 |

**§52 reproduces to better than 0.3% at every byte where it had a point.**

### The correction to §52's own wording

§52's "points above byte ~120 are not usable" was aimed at the **slope** column,
which genuinely degrades from −12.7 to −7.7 dB/oct as the roll-off runs out of
spectrum. It was written as though it covered the whole row. It does not:
interpolating §52's **corner** column across the gap gives 931 / 1145 / 1950 Hz
where the direct measurement gives 918 / 1092 / 2003 — 1.4%, 4.9%, 2.6%.

The boundary was correctly placed for the quantity it was derived from and
wrongly generalised to its neighbour. §52 now carries that amendment inline,
because a sibling project reasonably declined to trust the table on the strength
of the original sentence, and a warning that is too broad costs as much as one
that is too narrow.

### Two estimators, disagreeing informatively

A 2-pole model `|H|² = A/(1 + (f/f_c)⁴)` was fitted to every point as a second
opinion. Its `f_c` runs **below** the −3 dB crossing at low bytes (92 vs 129 at
byte 4) and **above** it at high bytes (2518 vs 2003 at byte 179), crossing over
around bytes 135–145 where the fit residual is also smallest — 0.07–0.27 dB
there against 1.3 dB at both ends.

A true Butterworth 2-pole has its −3 dB point exactly at `f_c`, so the
divergence says the response is not that shape at the extremes; over-damped at
the bottom is the obvious guess given `Q` reads 0. **The −3 dB crossing is
reported as the answer because it is model-free and it is what "cutoff" means.**
The fitted column is kept because a residual that rises at both ends and
collapses in the middle is a statement about the filter, not noise.

## §61 — Resonance moves the corner, by up to an octave (2026-08-24, live)

The cutoff calibration of §52/§60 was taken at **Q 0**. Applying it to voices
running at Q 102–112 put their filters 1.49–1.61× above target — near-constant
across three different base cutoffs, so systematic.

Measured on the noise preset: fix the cutoff byte, sweep Q, watch both the
resonant peak and the −3 dB crossing.

**−3 dB crossing, as a multiple of the same byte at Q 0:**

| byte | Q 41 | Q 64 | Q 102 | Q 112 |
|---|---|---|---|---|
| 119 | 1.37 | 1.50 | 1.63 | 1.68 |
| 135 | 1.59 | 1.78 | 1.94 | 2.00 |
| 179 | 1.94 | 2.24 | 2.59 | 2.75 |

At byte 135 the corner goes from 1092 Hz at Q 0 to 2184 Hz at Q 112 — **a full
octave from the resonance control alone.**

### It is not "two features of two curves"

The obvious alternative explanation was that a resonant peak and an over-damped
−3 dB crossing are simply different features and nothing is moving. Both were
measured, and **both move together**, so the response really is shifting rather
than changing shape around a fixed corner.

### The shift is not a single factor

It grows with Q *and* with the cutoff byte: 1.68× at byte 119 against 2.75× at
byte 179, both at Q 112. So it cannot be corrected with a constant. A conversion
that wants a corner frequency needs a Q-aware surface, or the targeting has to
be done by measurement at the voice's actual Q.

### The consequence for anything driving this filter

**Cutoff and resonance are not independent controls on this machine.** A driver
that sets a corner from a Q-0 calibration and then applies resonance will miss
by up to an octave, and will miss more the brighter the voice. Two parameters
calibrated separately and correct separately can still be wrong together.

It also retired an A/B before it ran: a set of cord amounts aimed by measurement
at Q 0, and a set computed by a law, were being compared on a preset that had
since had resonance applied to every voice. Both were valid for a machine state
that no longer existed. **A calibration carries the conditions it was taken
under, and changing any of them invalidates it silently.**

### §61a — Aiming at the real Q closes the gap, and exposes a floor

Following §61, all six voices of the test preset were re-aimed by measurement at
their **actual** Q rather than from a Q-0 table. Verified afterwards:

| voice | Q | amount | target | measured | ratio |
|---|---|---|---|---|---|
| v1 | 112 | 25 | 5161 Hz | 4974 Hz | 0.964 |
| v3 | 112 | 14 | 7414 Hz | 7453 Hz | 1.005 |
| v5 | 102 | 29 | 4153 Hz | 4183 Hz | 1.007 |

**No residual.** The 1.49–1.61× miss was entirely the Q shift; nothing else was
hiding underneath it. Worth noting how far the three candidate answers diverge —
measured-at-real-Q **25/14/29**, the law's 34/21/37, and an earlier
measured-at-Q-0 32/15/39 — when only one set was obtained under the conditions
the preset actually runs at.

**And there is a floor.** On the low-cutoff voices (byte 4, Q 41) the target of
207 Hz is unreachable: at cord amount **zero** the peak already sits at 523 Hz,
2.5× above target, lifted there by the resonance alone. Reducing the modulation
cannot help, because the floor is the resonance rather than the modulation.

A curve-fit will happily extrapolate to amount 0 and report it as the answer —
which is both unreachable as a solution and worse musically, since it removes
the modulation entirely. What is still reproducible is the **sweep size**:

    source asks   138 → 207 Hz  = 0.59 octaves
    machine gives 523 → 739 Hz  = 0.50 octaves at amount 8

so the amount was chosen to match the sweep and the offset reported, rather than
picking a number that hits neither.

**This is a constraint on any conversion, not a tuning problem.** Where a
source's resonance maps to a Q whose lift exceeds the source's own cutoff
target, the target cannot be reached on this machine at any modulation depth.
What to do then — match the sweep, clamp to the floor, or sacrifice the
resonance — is a policy question rather than an arithmetic one.

### A restore path that was not complete

The first attempt aborted mid-reference: the voice under test carries a
mute-group cut (§57) that makes it a 13.7 ms burst, far too short to read a
filter off, and the script had no provision for it. Its `finally` restored the
cutoff and the muted partner's volume but **not the cord amount**, leaving that
voice at zero.

Caught by reading the machine back rather than trusting the cleanup. The rerun
opens the amplitude envelope for the measurement and puts it back, and restores
the cord on every path. **A `finally` block is only as good as the list of
things it was written to remember**, and the one thing the run had changed most
recently was the one it forgot.

## §62 — The first step of a field is where the law breaks (2026-08-24, live)

A modulation depth was wanted at 7.35 cents RMS. The cord amount field is
0..127, so one unit ought to be far finer than that. Measured, with the
modulation rate pinned and the selective estimator (§59):

| amount | rms cents | minus floor | per unit | vs linear |
|---|---|---|---|---|
| 0 | 2.25 | — | — | floor |
| −1 | 3.85 | 3.12 | 3.12 | **0.40** |
| −2 | 16.12 | 15.96 | 7.98 | 1.02 |
| −3 | 22.36 | 22.25 | 7.42 | 0.95 |
| −4 | 28.50 | 28.41 | 7.10 | 0.91 |
| −6 | 46.94 | 46.89 | 7.81 | 1.00 |

**From amount 2 upward the field is linear at ~7.6 cents RMS per unit. The first
step is not: amount 1 delivers 40% of a unit**, and the jump from 1 to 2 is five
times where it should be two.

So the target was unreachable — it falls between amount 1 (undershoot 2.4×) and
amount 2 (overshoot 2.2×), with no byte in between. **The quantisation, not the
law, was the limit**, and a field with 127 steps still could not resolve a depth
well inside its range.

### The pattern this completes

Four instances in one day, all the same shape — a field linear across its
working range and not linear at its very bottom rung:

- **§57**: envelope decay rates 0 and 1 both produce silence; rate 3 is the
  first usable value, and rate 2 is 15 dB below it.
- **§60**: the cutoff curve is not log-linear between bytes 4 and 64; reading it
  as though it were puts a target 35% out.
- **§58**: an LFO depth law fitted from 25% upward carries a +9.00 cent
  intercept at zero, which cannot be real and is the entire disagreement below
  3%.
- **§62**: this.

**A law fitted over a field's middle should not be trusted at its first step.**
On this machine the first step has been wrong every time anyone has looked, and
it is exactly where a converter lands whenever a source asks for "a little".

Practical consequence for anything driving the E4XT: if a computed value rounds
to 1, measure what 1 actually does before shipping it. It may be delivering
under half of what the arithmetic says.

## §63 — Envelope rate is a SPEED, and the amplitude span is ~90 dB (2026-08-24, live)

Two questions that a sibling project could not separate from its own code, both
answerable without assuming any constant.

### The rate byte sets dB per second, not a segment duration

Noise preset, envelope parked so it jumps straight to a sustain level and holds,
release the only thing moving:

| sustain | rate 60 | rate 69 | rate 87 |
|---|---|---|---|
| 70 | 47.6 dB/s | 27.8 | 10.4 |
| 100 | 45.5 dB/s | 28.6 | 9.9 |

**The dB/s is the same at every sustain level.** The time to fall a fixed number
of dB does not depend on where the fall starts; only the total release time
scales, because the distance does. (Raw times differ by a constant ~0.12 s
latency between the two sustains, which cancels in the slope.)

So the rate law is **span-independent**, and arithmetic that divides a span to
obtain a rate has the wrong shape regardless of which constant it divides by.

> **Do not over-generalise that sentence** (added 2026-08-24). It is about
> obtaining the *rate law* by dividing a span, and about the **release** stage
> in particular, whose endpoint is silence — a level neither machine measures,
> and which both sides of a conversion invent from their own parameter scales.
> A **decay** stage is different: it runs from peak to the sustain level, an
> endpoint both machines agree on and can be metered. Converting a decay *time*
> into a rate legitimately needs that span, and a span-aware decay conversion is
> correct. **The span is wrong only where the endpoint is invented.** The
> sibling project's measurements make the split visible: its decay conversion
> agrees with the source machine to 1–7% while its release conversion is out by
> 1.6–4×, and the only structural difference between the two is which endpoint
> is real.

    dB/s = 1382 × exp(−0.0565 × rate)        halving every 12.3 bytes

The 12.3-byte halving matches §43's filter-envelope rate law (12.2 bytes) to
within measurement: **the two envelopes share one rate scale.**

**Provenance, recorded because a sibling is about to hardcode this** (added
2026-08-24, §67): the law rests on **three rate bytes — 60, 69 and 87 — at two
sustain levels**, six measurements, on the noise preset described above, with
roughly 50 dB and 73 dB of travel above the output floor. **Fitted window
[60, 87]**, so bytes in the high 70s and low 80s interpolate rather than
extrapolate.

**And the subject was not stationary during a release** (added 2026-08-24). The
noise bank this law was measured on has **loop-in-release CLEAR** on both of its
samples — read off the disc image, `options` bit 3 not set. So at note-off the
voice leaves the loop and plays out whatever data follows it, exactly as §64
describes. **This is not a claim that the law is contaminated:** the releases
measured here are short enough that they almost certainly stayed inside the
remaining data, and the estimator only needed the −10 dB and −20 dB crossings.
But it puts a ceiling on the subject. **A fall at byte 100 takes about 9 s and
would not have survived it** — precisely the region a later sweep was designed
to reach. The replacement calibration bank, built with the flag asserted, turned
out to be necessary for a reason nobody had identified when it was commissioned.

*A calibration subject can carry the defect the calibration exists to exclude.*
Check the subject's own flags before trusting a measurement made on it.

Three distinct bytes is thin for an exponent, and the reason to trust the slope
anyway is not the point count but §43: a different envelope, a different
subject and a different run put the halving at 12.2 bytes against this 12.27.

**The prefactor holds up.** Against four fresh measurements taken later the same
day on real sampled material rather than noise (§67), fitted with the window
kept 15 dB clear of the noise floor:

| byte | §63 predicts | measured | error |
|---|---|---|---|
| 69 | 28.04 | 28.35 / 28.24 | +1.1% / +0.7% |
| 80 | 15.02 | 15.52 / 14.99 | +3.3% / −0.2% |

**Within 1–3% at both.** The exponent implied by those pairs is 0.05615 per byte
against this law's 0.0565 — 0.6% apart. Inverting for 15.224 dB/s gives 79.8
from the law and 80.04 from the measurements.

> **This table replaces an earlier one that said the opposite** — that the
> prefactor ran 5–10% fast at byte 80, and that the byte for 15.224 dB/s was
> 78–79. Those numbers came from fits whose window ran down to 6 dB above the
> noise floor. **Near the floor a log-domain fall flattens**, because the
> measured RMS is signal plus floor rather than signal alone; those points sit
> above the true line and lever the fitted slope down. The slowest release
> spends longest there and took the most damage, which is why byte 80 looked
> biased and byte 69 did not. The residual-by-thirds output diagnosed it: at
> floor+6 all four fits show the same +,−,+ curvature, and at floor+15 it
> vanishes and the residuals halve. **Keep the fit window at least 15 dB clear
> of the floor.**

One methodological difference accounts for some of that and should be stated:
§63's dB/s is a **two-point crossing measure** — 10 dB divided by the interval
between the −10 and −20 dB crossings — where §67's are least-squares fits over a
fixed window. The crossing measure is the more fragile of the two, being
sensitive to the exact crossing samples and to curvature near the top of the
fall.

### The amplitude span, measured rather than inferred

Every segment parked at one level, steady output against level 100:

| level | dB below 100 | level | dB below 100 |
|---|---|---|---|
| 100 | 0.00 | 30 | −61.36 |
| 80 | −13.02 | 20 | −69.41 |
| 60 | −32.52 | 12 | −72.60 |
| 40 | −51.47 | ≤6 | floor (−73.5) |

0.964 dB per level unit through the linear region, extrapolating to **−90 dB at
level 0** — a lower bound, since levels at or below 6 sit on the output floor.

A sibling's inferred `ENV_FULL_SPAN_DB = 97.82` is close; a "~55 dB" figure
taken from an old calibration's comment is not. **The inconsistency between the
two was real and resolved in favour of the inferred constant** — the comment
described that calibration's own conditions, not the field's range.

### Why the arithmetic still mattered less than expected

The hypothesis under test was that releases were coming out roughly three times
too fast. With the measured law, the test preset's octave layer — sustain level
68, about 47 dB of audible travel — releases in **1.68 s at rate 69** against a
desired 1.979 s. That is **18% fast, not 3× fast.**

An 18% error is worth fixing and is not what a listener describes as "quite a
bit longer". Shipping a 3× correction on the strength of the inconsistency would
have overshot badly in the opposite direction.

**A contradiction between two numbers in one codebase tells you something is
wrong; it does not tell you which of them.** Both halves here disagreed with
each other, and the measurement supported the one that had been labelled
"inferred, not measured" over the one written down from a live calibration.

## §64 — "Loop in release" is a separate flag, and without it a release cannot exist (2026-08-24, live)

A voice whose amplitude release rate had no audible effect at all: the note
stopped within 20 ms of note-off at rate 69 and at rate 80, where §63's
calibration says those are 28.1 and 15.1 dB/s. The same parameter id behaves
exactly as calibrated on a different preset, so the rate law was never in doubt.

Read off the machine — **Sample Edit → Tools1 → LpType**:

    Sample Loop Parameters
      Loop type        : on
      Loop in release  : off

**The loop is enabled and does not run through the release.** At note-off the
voice leaves the loop, plays out whatever sample data lies past the loop end —
a few tens of milliseconds — and stops. No envelope setting can reach past that.

### What was eliminated first, and why the order mattered

Each of these was measured before the flag was found, and each is worth keeping
because each is a plausible answer that happens to be wrong:

- **the filter envelope closing** — cord to zero, and the filter release
  slowed: no change
- **the sample running out** — holds of 1.0, 2.0, 3.0 and 4.5 s all stopped
  0.01–0.07 s after note-off, so it tracks note-off and not absolute time. This
  also proves the loop itself works: a 1.19 s sample still sounding at 4.5 s is
  looping.
- **the envelope never reaching its sustain segment** — held 8 s and 12 s, and
  separately set the decay rate to 0 so the sustain is reached at once: no
  change
- **an unusual full-depth footswitch→key-sustain cord** — zeroed: no change

### A withdrawn number, from the same session

One run reported the note persisting 7.84 s with that cord at +100 against
1.92 s at zero — a spectacular result, and false. The metric counted anything
more than 6 dB above a floor estimated from the file's own lead-in, and on a
quiet capture the noise wanders across that line indefinitely. Printing the
envelope killed it: four runs alternating the cord between 100 and 0 all show
−54 dBFS just before note-off and the floor 0.1 s later.

**Look at the shape, not the summary** — §41 for silence, §58 for an inflated
depth, and here for an invented sustain.

### Why this had never surfaced

A release is only audible on a sample that is still sounding when the key is
released, which means a looped one. Any converter that writes the loop points
and the loop-type flag but not *loop in release* produces samples that loop
perfectly while held and have no release at all — and nothing about that is
visible in a parameter read-back, a file dump, or a held note. It takes someone
listening for a release, on a looped sample, with a reason to expect one.

### Where the flag lives, and a contrast that was not one

The obvious next question was which sample header bit carries it. The obvious
answer — compare a preset whose releases *do* work — turned out to be a trap
worth recording.

**A working release is not evidence of the flag.** The preset whose releases
measured cleanly at every rate byte (§63) uses samples that are **12 seconds
long**, held for 1.5 s. Their option bits are `0x0031`, byte-for-byte identical
to the samples with no release at all. They kept sounding through the release
because ten seconds of data remained, not because anything was set. The
"contrast" was a difference in sample length wearing a flag's clothes.

That also confirms the mechanism from the other side: with loop-in-release off,
the voice leaves the loop at note-off and plays out whatever remains. Where the
loop sits near the end of the data — 52483 frames with the loop at
51646..51982 — nothing remains, and the note stops in 20 ms.

**A survey of the option word across 125 banks found five values, not two:**

| value | count | |
|---|---|---|
| `0x0031` | 1219 | looped |
| `0x0020` | 240 | unlooped |
| **`0x0039`** | 38 | |
| **`0x0079`** | 6 | |
| **`0x0078`** | 1 | |

```
0x0031 = 0b0011_0001
0x0039 = 0b0011_1001
                ^ bit 3 (0x08)
```

**Every file carrying bit 3 is dated 2002-09-21** — original-era banks. The
other 121 files, spanning 2002 to 2026 and including everything the sibling
toolchain has produced, carry only `0x0031` and `0x0020`.

**Not yet a verified meaning.** Bit 3 is present in exactly the files old enough
to have been made by the manufacturer's own tools and absent everywhere else,
which is consistent with loop-in-release and equally consistent with any other
flag those tools set. One convention travels with it: every bit-3 sample has
**6 frames past the loop end** where every `0x0031` sample has **0**, and file
evidence alone cannot separate the two.

The decisive test is audible rather than structural — set the flag from the
panel and measure whether the release appears at its calibrated rate — because
the RAM sample header cannot be read back without writing the bank to disk.

### Confirmed audibly: A/B/A on the flag itself

The flag was toggled on the sounding sample from the panel, measured, and set
back. Level after note-off:

    flag OFF   -54  ->  -83 (floor) within 0.1 s        instant
    flag ON    -54  -57  -63  -71  -77  -83             over 2.5 s
               3.4  3.6  4.0  4.5  5.0  6.0 s
    flag OFF   -54  ->  -83 within 0.1 s                instant again

With it on, four captures give **13.96 / 14.06 / 14.14 / 14.20 dB/s**, residual
0.5–0.7 dB over ~160 points each — a straight line. Mean 14.09 dB/s, i.e.
**2.84 s for a 40 dB fall**, against §63's prediction of 15.1 dB/s and 2.65 s
for that rate byte: **7%**.

So one measurement confirms three things at once — that loop-in-release is the
mechanism, that §63's rate law describes the release, and that a release
matched by *rate* rather than by *time* lands on the source machine's own figure
(the AKAI measures 15.2 dB/s and 2.64 s for the corresponding setting).

It also finally disposes of a suspect: all four flag-on captures alternated the
full-depth footswitch→key-sustain cord between +100 and 0, and the curves are
indistinguishable (13.96/14.14 against 14.06/14.20). The 7.84 s "sustain"
withdrawn above was entirely the metric.

**Still not established: that bit 3 is where the flag is stored.** The audible
test cannot see the header, and the header cannot be read back from RAM without
writing the bank to disk. Bit 3 remains a correlation with an era — strengthened
by nothing, and weakened as a lone clue by the sibling's check that "6 frames
past the loop end" appears in 815 samples against 45 carrying bit 3, so the two
do not travel together after all.

### Bit 3 confirmed, and a hot SD swap that propagates

**A bank written by the converter with bit 3 set sustains through its release,
with nobody touching a dialog.** Isolated voice, `Rls1` rate 69, three runs:

    27.17 dB/s   residual 0.57 dB over 86 points
    27.33 dB/s   residual 0.53 dB over 85 points
    16.05 dB/s   residual **4.07** -- discarded on its own residual, seven times
                 the others, with an envelope shape identical to them

**27.25 dB/s against §63's 28.0 predicted for that rate byte — 2.7%**, in the
same direction as the by-hand test's 7% at a different rate. So bit 3 of the E4B
sample header's `options` word is where "loop in release" is stored. That was
the last inference in this chain and it is now a measurement.

The third run is worth keeping as an example of the discipline paying for
itself: a fit reporting 16 dB/s where two neighbours report 27 would have been
a puzzle, and its residual said "do not use me" without anyone having to
adjudicate.

**A hot SD swap under a running ZuluSCSI propagates.** The card was changed
underneath a powered sampler and the disk browser showed the new image on the
next `Drives → drive → Banks` navigation — five banks where the same navigation
had shown four an hour earlier with the old image in place. **No restart, no
stale directory.** That is worth recording because the opposite was the
reasonable expectation: SCSI is not designed for it, and the fallback plan was a
power cycle costing a hand-built reference preset.

Both halves of that were tested against the same navigation on the same day, one
with the old image and one with the new, which is what makes it a result rather
than an absence of trouble.

### §62 amended — the first-step anomaly is a SIGN asymmetry

§62 measured that field on the **negative side only** and concluded that amount
1 delivers 40% of a linear unit, and that a target of 7.35 cents RMS was
unreachable between −1 and −2. That is true of negative amounts and not of the
field.

Same cord slot, same voices, magnitudes swept both ways:

| amount | rms cents | per unit | | amount | rms cents | per unit |
|---|---|---|---|---|---|---|
| +1 | 8.48 | 8.48 | | −1 | 3.78 | 3.78 |
| +2 | 20.84 | 10.42 | | −2 | 16.17 | 8.09 |

**Positive delivers more than the negative of the same magnitude — 2.24× at
|1|, 1.29× at |2|**, converging as the magnitude grows. Reproducible: +1
measured 8.48 twice with a −1 and a ±2 in between.

So the unreachable target was reachable all along on the other side of zero:
`+1` gives 8.48 against a 7.35 target, **15% over**, where `−1` gives 3.78,
49% under.

The practical consequence is for anyone who negates a cord for phase reasons —
a common thing to do when two machines' LFOs start in opposite directions.
**The negation is not free at small amplitudes**: it costs more than half the
modulation at ±1. A magnitude derived on the positive side cannot be carried
across the sign unchanged.

No explanation is offered here. Two's-complement rounding in the amount
encoding is the obvious guess and it has not been tested.

**And the methodological point, which is the reason this is written as an
amendment rather than a new section:** §62's sweep was −1, −2, −3, −4, −6. Every
point shared a sign, so the sign could not appear as a variable, and the
conclusion generalised from a half-explored axis without saying so. *A sweep
that never crosses zero has not measured a signed field.*

## §65 — The E4XT does not scale envelope rates with key; the release is missing per KEYGROUP (2026-08-24, live)

Jan's A/B verdict on the converted preset was that the lower octaves are near
perfect, and that further up the release is too short and the attack click too
weak — "on lower notes less noticeable, on the higher notes quite noticeable".
Two symptoms varying together with pitch invited one mechanism: that the E4XT
scales envelope rates with key while the source machine does not. The sibling
project had already measured the source as key-independent (0.21% spread across
four octaves), so this side was the remaining suspect.

**Measured within a keygroup, which is the whole design of the test.** Comparing
note 26 against note 88 across the preset changes the sample, the cutoff and the
envelope at once. Each of the three key ranges was swept internally, so within a
row the sample and every parameter are fixed and only the pitch moves. The
partner voice of each pair was muted so the sustaining layer was alone, and the
result is reported in dB/s, never in seconds — an error that varies with pitch
hides inside a time.

Before launching: the preset's only `Key+` source routes to `FilFreq` at amount
0, and no cord targets an envelope rate, so anything found would have been
architectural rather than something the writer asked for.

| voice | note | dB/s | residual | points |
|---|---|---|---|---|
| low kg | 26 | 25.59 | 1.48 | 85 |
| low kg | 40 | 26.75 | 0.79 | 86 |
| low kg | 52 | 27.09 | 0.56 | 87 |

**25.59 → 27.09 dB/s over 26 semitones: 1.059×, +0.23% per semitone.** Two
octaves of pitch buy 6% of rate, and the point with the worst residual is the
one holding up the low end. **The key-scaling hypothesis is dead**, on this
machine as on the other one.

### What the failed rows were actually saying

The mid and high keygroups produced *no fall to fit* — 0 and 1 points inside a
window that wants a straight stretch between 2 dB below note-off and 5 dB above
the floor. A fit that declines to run is a result if you look at what it
declined to fit:

| | at off | +20 ms | +100 ms | +300 ms |
|---|---|---|---|---|
| low kg, note 40 | −52 | −55 | −58 | −63 |
| mid kg, note 66 | −45 | −47 | −61 | −84 |
| high kg, note 84 | −39 | −39 | −40 | −84 |

Full level right up to note-off, so the loop is running during the hold. Then
gone inside ~100 ms. **Those keygroups do not release, they stop.**

### Two checks, one run

**The envelopes are identical.** Read back from all six voices: Atk1 0/100,
Atk2 0/100, Dcy1 99/68, Dcy2 0/68, Rls1 69/0, Rls2 0/0, FEnv Rls1 70, filter
cord 31 — the same six numbers on the low, mid and high voices alike. So this is
not a parameter that got written differently in one keygroup.

**And the release rate has no purchase.** Slowing Rls1 from 69 to 110 — §63's
law says that is 28 dB/s down to about 6, a 4.6× longer fall:

| keygroup | Rls1 69 | Rls1 110 |
|---|---|---|
| high | 180 ms to floor | 220 ms to floor |
| low (control) | 850 ms to floor | never reaches it: −54 at note-off, still −59 after 1.5 s |

The control is what makes the null mean anything. The identical edit on the low
keygroup turns an 850 ms fall into one that has travelled 5 dB in a second and a
half; on the high keygroup it moves nothing. **The amplitude release is
unreachable on the mid and high keygroups** — something is ending the note
before the envelope can, exactly as in the earlier case where the filter
envelope was closing first.

Here it is not the filter: the filter release and its cord are identical across
the keygroups too. Sound at full level through the hold and gone within ~100 ms
of note-off is the signature of **loop-in-release not being in effect** —
playback leaves the loop at note-off, plays whatever follows it, and stops. The
sibling project measured those post-loop tails at 100, 110 and 12400 frames,
i.e. about 2 ms, 2 ms and 280 ms.

### What this costs the earlier conclusion

§64 established bit 3 of the E4B `options` word by measuring the converted
bank's release at 27.25 dB/s against 28.0 predicted. That measurement was taken
on **one voice of the low keygroup**, and the conclusion — that the flag was now
set — was generalised to all sixteen samples from it. The flag is real and the
bit is right; what was never checked is whether the writer set it *everywhere*.
Two thirds of this preset says it did not, or that something else about those
samples defeats it.

**A confirmation taken on one member of a set confirms that member.** The low
keygroup was the natural place to measure because it was the one with an audible
release — which is to say the sample was chosen *because* it already worked, and
that is the selection that hid the defect for a day.

The next step belongs to the writer, not to the machine: check bit 3 of the
`options` word on the mid- and high-keygroup samples of the converted bank
against the low-keygroup ones. If it is set on all of them, the flag is not
sufficient and the loop points themselves are the next place to look.

## §66 — The machine was playing an older copy of the samples, and it took two of them with the same name to see it (2026-08-24, live)

§65 ended by asking the sibling project to check bit 3 of the `options` word on
the mid- and high-keygroup samples of the converted bank. It did: **the bit is
set on all sixteen samples in the file.** So the flag was not the thing that was
missing, and the next place to look was the machine.

**Read off the panel** — `Sample Edit` → `Tools1` (F2) → `LpType` (F2):

| sample | used by | length | Loop type | Loop in release |
|---|---|---|---|---|
| S021 | voice 3 / voice 5's neighbours | 1.19 s | on | **off** |
| S026 | voice 4 (high keygroup) | 0.86 s | on | **off** |
| S054 | voice 1 (low keygroup) | 1.19 s | on | **on** |

**S021 and S054 carry the same name and the same length.** They are two copies
of one sample sitting in RAM at once, and only one has the flag.

> **Amended, same day (§67).** This section called S021–S026 "an older copy of
> the converted bank". They are not: they are the **reference bank's own
> samples**, loaded long before the merge, and the two banks share all sixteen
> sample names. The reference preset's own map — `v0 24, v1 21, v2 25, v3 22,
> v4 26, v5 23` — points into exactly that range, which is what settles it. The
> mechanism below is unchanged and the conclusion is unchanged; what was wrong
> was whose samples they were.

And the preset's voices are split across them. Voice→sample, read three times
per voice with the voice reselected each round because the whole reading turns
on one surprising number:

    v0 24   v1 54   v2 25   v3 22   v4 26   v5 23

**Five voices point into the old copy. One points at the new one — and it is
the only voice that releases.** That is the entire result of §65 restated with
its cause attached: the mid and high keygroups do not fail to release because
of anything the converter wrote, but because the machine is not playing what
the converter wrote. The file on the card is correct.

### Why this is proof and not another correlation

Two samples with **the same name and the same length** read differently in the
same dialog, minutes apart, on the same page. That is the parity check the
dialog needed: it tracks the selected sample rather than showing one global
value, which could not be told from a single reading, and it is the reason to
believe both the `off`s and the `on`.

It also settles the two questions §65 left open, in the opposite direction from
the one it feared:

- **The panel field is real and honoured.** A sample with the flag on releases
  under envelope control — slowing its release rate from 69 to 110 stretched an
  850 ms fall past 1.5 s (§65). A sample with it off stops within ~100 ms and
  the rate does nothing.
- **Bit 3 stands.** §64's identification was never in trouble. The converter set
  it on all sixteen and the copy the machine loaded from that file reads `on`.

**And §65's self-criticism was right about the fact and wrong about the
reason.** "I measured the sample that already worked" was true — but what made
it work was not that it was a luckier member of the same set. It was a
different copy of the file, loaded at a different time. The tail lengths that
looked like the mechanism (12 ms where a release exists, 2 ms where it does
not) are a correlation with which copy is which, and they never could have been
the mechanism: 12 ms of data past the loop cannot produce an 850 ms fall, still
less one that stretches past 1.5 s when the envelope is slowed. *A quantity
three orders of magnitude too small to explain the effect is not the cause of
it, however cleanly it splits the table.*

### What this costs the listening test

Jan's A/B verdict — lower octaves near perfect, release too short and the
attack click too weak higher up — was taken on a preset **five voices of which
were stale**. The one keygroup he called near perfect is the one voice playing
the current sample. The verdict is sound as a description of what came out of
the speakers and cannot be used to grade the converter, because the converter's
output was only a sixth of what was sounding.

The fix is not in the converter. It is to clear RAM and load the bank once,
into a machine with no older copy of it resident, and re-run the audit.

### Panel notes, recorded because each cost a round trip

- `Sample Edit` opens on the last sample touched. `PAGE_NEXT` / `PAGE_PREV`
  step one sample at a time and the header shows the neighbours, which makes
  the walk self-checking. **Typing a sample number on the keypad and pressing
  ENTER does not select it** — the page returned to the sample it started on.
- The `LpType` dialog takes `Cancel` on F1 and `OK` on F6. Cancel is the one to
  use: OK accepts, and accepting unchanged values is a write nobody asked for.
  One OK was pressed on the first sample's dialog with nothing altered.
- A modal warning about an unrelated sample in RAM re-appears on almost every
  page transition inside the sample editor and **swallows the keypress that
  provoked it**, so a step that looks like it did nothing has usually done
  nothing. Photographing every keypress is what made that legible.

## §67 — Merge rebinds a preset's samples by name to whatever is already resident (2026-08-24, live)

RAM erased and the converted bank loaded **alone** into an empty machine. Both
halves matter: it is the only arrangement in which its samples cannot be matched
against anything, and §66 showed that with the reference bank resident they are.

| | v0 | v1 | v2 | v3 | v4 | v5 |
|---|---|---|---|---|---|---|
| merged over the reference bank | 24 | **54** | 25 | 22 | 26 | 23 |
| loaded alone into empty RAM | 4 | 1 | 5 | 2 | 6 | 3 |

**Five voices were bound at exactly +20 — the reference bank's copies of the
same-named samples — and one was bound to a freshly loaded copy.** Loaded alone
the map is 1..6, six distinct consecutive ids, stable over three reads.

So the merge resolves a preset's sample references **by name against samples
already in RAM**, and loads a sample only when nothing resident matches. The
sibling project has since shown the two banks' sixteen samples are identical in
name, in size and in PCM, differing in exactly one bit of the `options` word, so
name matching had every reason to succeed — which it did, on fifteen of sixteen.

**Why the sixteenth loaded anyway is unexplained.** It is the first entry in the
file. It is not a content or size discriminator, since every one of the sixteen
differs from its resident twin in the same single bit. A first-entry special
case is as plausible as anything else and nothing here tests it. Recorded as
open rather than guessed at.

**One candidate is dead, cheaply.** Before the erase the panel read sample RAM
**7 MB used of 128 MB, 5%**. The merge did not rebind because it ran out of
room; it had 121 MB free and rebound anyway.

### The defect is closed, and it was never the converter's

Release rate on the cleanly loaded preset, all three keygroups, partner voice
muted, fitted over one absolute window — +0.10 s to +1.00 s after note-off — that
the printed shapes show is inside the straight part of every capture:

| keygroup | notes | dB/s |
|---|---|---|
| low | 26 / 40 / 52 | 27.51 / 27.19 / 27.24 |
| mid | 62 / 66 / 70 | 28.16 / 27.94 / 27.74 |
| high | 76 / 84 / 96 | 28.64 / 34.73 / 34.08 |

**§63's law predicts 28.1 dB/s for the release rate byte these voices carry.**
Seven of the nine land within 3% of it. The mid and high keygroups — the two
that in §65 produced *no fall to fit at all*, gone inside 100 ms — now fall for
about a second and a half, exactly like the low one.

The two fastest readings, at the top of the top keygroup, come with residuals of
2.14 and 1.28 against 0.2–0.5 elsewhere, and their printed shapes have a visible
knee that one straight line cannot represent. **They are not evidence of key
scaling** — §65 measured that question properly and found +0.23%/semitone — and
they are not quoted as a rate here.

### What this means for the converter, and for every future merge

Nothing in the converted bank was wrong. The file was correct when §64 measured
it and it is correct now. **A preset can be loaded, read back parameter by
parameter, dumped, and audited by ear, and still be playing another bank's
samples** — the sample *numbers* in the preset are the only place it shows, and
nobody reads those because they are not a setting anyone chose.

Two defects in one day whose common property is that they are invisible to every
check in use: a sample flag that no parameter read-back reports, and a sample
binding that no dump shows. Both were found only by measuring the audio and
disbelieving the result.

The practical consequence for anyone writing banks: **give samples names that
cannot collide with a bank the user might already have loaded.** A revised bank
merged over its own earlier version, or over the reference it was derived from,
will otherwise bind silently to the older samples every time.

And for anyone auditing by ear: **a listening test run over a merge is not a
test of the file.** The verdict that started this chain — near perfect low,
release too short high — described the machine accurately and graded a preset
five sixths of which was another bank's audio.

### Two small things worth having

- **The panel prints `0mb` for empty sample RAM where the SysEx query still
  reports §21c's ~3 MB floor.** Two different numbers for the same state. The
  panel's is the intuitive one; a client must still use the floor.
- Loading a bank into empty RAM makes it **P000 upward**, and the machine lands
  on `P000` by itself with the bank's name in the title bar. No page trap and
  no dialog to dismiss — unlike the merge path of §48.

### §67 extended — with the release working, a calibration error is visible underneath it

How long each version sounds after note-off, same rig, same gain, same hold, at
the six notes the listening test used — time from note-off to within 6 dB of the
noise floor:

| note | reference preset | conversion, merged | conversion, clean |
|---|---|---|---|
| 26 | 0.05 s | 0.78 s | 0.84 s |
| 40 | 0.03 s | 0.87 s | 0.88 s |
| 52 | 0.02 s | 0.90 s | 0.90 s |
| 64 | 0.03 s | **0.02 s** | 1.14 s |
| 72 | 0.19 s | **0.19 s** | 1.30 s |
| 84 | 0.20 s | **0.09 s** | 1.17 s |

The middle column is the audit Jan was given: it tracks the *reference* preset
wherever the merge rebound it, and departs from it only in the low keygroup —
the one voice bound to the bank's own sample. Column three is the same file with
nothing else resident.

**And the reference preset itself barely releases at all** — 0.02–0.20 s at
every note. Its samples are the ones §66 read as `Loop in release: off`. That is
not a defect in it; it is simply not the thing the conversion is trying to
match.

### The rate byte is about 1.8× too fast

The source machine was measured elsewhere at **15.224 dB/s**, essentially
key-independent. The clean conversion measures 27–28, which is §63's prediction
for the release rate byte the voices carry. Inverting §63 for 15.224 gives byte
79.8, so byte 80 was predicted and then tested rather than asserted:

| keygroup | rate 69 | rate 80 | predicted at 80 |
|---|---|---|---|
| low | 27.36 dB/s | **13.44** | 15.05 |
| mid | 27.97 dB/s | **14.24** | 15.05 |
| high | 34.75 (resid 2.16) | 26.78 (resid 2.35) | — |

Solving each keygroup's own two points for the byte that lands on 15.224 gives
**80.0**. So the converter's release mapping should be producing about **80
where it produces 69**, and the audible consequence is a release 1.8× too fast
— which is exactly the half of Jan's verdict that survived the merge being
fixed.

> **Corrected the same evening.** This first read 78.1 and 78.9, from fits whose
> window ran to 6 dB above the noise floor; see §63's amendment for why that
> biases the slow end and how the residual thirds diagnosed it. Re-fitted 15 dB
> clear of the floor the two pairs give 28.35/28.24 at byte 69 and 15.52/14.99
> at byte 80, and the target byte is **80**. §63's own inversion gives 79.8, so
> the two routes agree to a fifth of a byte.

Two cautions on that number. The per-byte constant implied by these two points
was originally 0.061–0.065 against §63's 0.0565 — a disagreement that turned out
to be the floor artefact above, and which corrects to 0.05615, within 0.6% of
§63. Two points still do not re-derive a law, and §63's is the one to
trust for anything else.
either rate** — residuals of 2.16 and 2.35 against 0.22–1.26 elsewhere, with a
visible knee in the printed shape. It is consistent, it is not the key scaling
§65 ruled out, and it is unexplained. Left open rather than averaged away.

Rate 69 was restored on all three voices and read back. The fix belongs in the
file, not in RAM.

### §63 extended — a free point at byte 99, twelve bytes outside the fit

Byte 99 is the **decay** rate the converted bank's sustaining voices carry, and
it can be read off captures taken for something else entirely: the fall while the
note is still held, before any release. On the mid keygroup, three notes:

| note | dB/s |
|---|---|
| 62 | 5.39 |
| 66 | 5.36 |
| 70 | 5.34 |

**0.9% spread across three notes** — the cleanest decay reading in the set.

| | dB/s at byte 99 |
|---|---|
| measured | **5.36** |
| §63's law | 5.14 (4% low) |
| the sibling's constant | 6.1 (14% high) |

Two things follow. **§63 predicts a byte twelve outside its fitted window
[60, 87] to within 4%**, which is the first evidence that the slow end is
reachable by extrapolation — the end a planned sweep exists to measure. One
point is not a range and this one rides on a decay segment rather than a
release, so it does not retire the sweep; it lowers the risk that the law falls
apart there.

And **the decay and release segments share the rate scale.** §63 already argued
the filter and amplitude envelopes share one (12.2 against 12.3 bytes per
halving); this is a third context on the same scale.

**But the held level is only the envelope on a stationary source.** Total decay
travelled at note-off, with byte-identical envelopes on all six voices:

    14.7  17.1  24.6  27.2  28.2  32.1  34.2  35.8  39.9  dB

**14.7 to 39.9 dB from the same bytes.** The sample's own contour dominates
everywhere except the mid keygroup, whose notes sit within a few semitones of
its root. Anything measured off a held level on musical material is measuring
two things at once.

### A null that was underpowered, not negative

An earlier pass looked for the sample's loop period showing through the held
level, found lags that did not track pitch, and reported "not the loop". **The
analysis used 5 ms envelope windows and the loops are 7.6 and 15.3 ms at root —
3 to 13 ms at the notes played.** A 5 ms window cannot resolve a period under
10 ms, so the test could not have detected what it was looking for.

Redone at 0.5 ms on the held portion, low keygroup:

| note | semitones from root | loop period | best lag | ρ | ratio |
|---|---|---|---|---|---|
| 26 | −22 | 27.08 ms | 13.50 ms | 0.96 | 0.50 |
| 40 | −8 | 12.06 ms | 6.00 ms | 0.98 | 0.50 |
| 52 | +4 | 6.03 ms | 3.00 ms | 0.99 | 0.50 |

**Exactly half the loop period at all three notes across 26 semitones.** The
loop is showing through at its second harmonic and it tracks pitch precisely.
The null is withdrawn.

*Check the resolution of a measurement against the size of the thing being
looked for before reporting its absence.* A null from an instrument that cannot
see the effect is not evidence, and it reads exactly like one that is.

### The high keygroup's curvature is NOT the floor artefact

Worth separating, since one correction could easily be taken to dissolve the
other. Re-fitted 15 dB clear of the floor, rate 69, residual mean by thirds of
the fall:

| capture | dB/s | residual | thirds |
|---|---|---|---|
| low, +4 from root | 28.20 | 0.27 | +0.01 −0.01 −0.00 |
| mid, +10 | 28.00 | 0.18 | +0.04 −0.03 −0.01 |
| high, +4 | 29.13 | 0.92 | +0.40 −0.87 +0.46 |
| high, +12 | **36.07** | **1.78** | **−0.80 +1.79 −0.96** |
| high, +24 | 39.62 | 0.22 | −0.09 +0.16 −0.06 |

The floor artefact produced **+,−,+** on every capture it touched, and moving the
window removed it. The high keygroup at +12 shows **−,+,−** — the opposite sign
pattern, larger, and it survives the window change. Different sign, different
cause. The three shapes of §67's extension are still unexplained.

## §68 — Four defects with one shape, and three withdrawals with another (2026-08-24)

Written down because both patterns recurred inside a single evening, and neither
is about this machine specifically.

### The defects: everything upstream reported success

| what was wrong | what said it was fine |
|---|---|
| a sample flag set in the file and not honoured by the machine | the file, and every parameter read-back |
| a preset's samples resolved to a different bank's identically-named copies | the file, the parameter dump, and a listening test |
| a rate constant wrong by 13–19% for months | a 5% discrepancy in a note, written off as not worth chasing |
| a preset number written to one field of a file and read from another | the writer, and a full test suite |

**None of them were detectable without going to the machine and measuring.**
Each lives in the gap between what was written and what the machine did with it,
and a test that compares a writer to its own expectations cannot see into that
gap — it compares the project to itself.

The listening test is the sharpest case: it *did* reach the machine, and it
still could not see the second defect, because what it heard was another bank's
audio wearing the right envelopes and it had no reason to suspect the binding.
**Reaching the hardware is necessary and not sufficient; the measurement has to
be of a quantity the defect can move.**

### The identification corollary

A preset name is a label. **A preset number is also a label, and so is a stated
preset count** — anything the machine does not have to act on can drift without
anything upstream noticing. Two of the four above are exactly that.

So: **identify by a field the machine demonstrably acts on.** A root key it
transposes by. A rate byte it slews at. A sample number a voice actually plays.
Where a run depends on having the right subject in front of it, read that field
back and refuse if it disagrees, rather than trusting the label that named it.

### The withdrawals: a method whose limits were never checked

Three findings were withdrawn the same evening, all correct-looking at the time:

- a null from an autocorrelation on 5 ms windows, looking for a 3–13 ms period
- a 5–10% bias from fits whose window ran down to 6 dB above the noise floor
- a "contradiction with the machine" resting on a constant already under suspicion

**One shape: a method whose resolution, range or reference was never checked
against the size of the thing being measured.** All three produced results that
looked entirely reasonable from the inside — a clean null, a plausible bias, a
confident prediction. Nothing in any of the three would have raised a hand.

What caught two of the three was a specific question from someone reading the
raw numbers — *print the residuals by thirds*, *here are the actual loop
lengths* — which is the practical argument for reporting shapes and tables
rather than summaries. **A summary gives a reader nothing to ask about**, and an
R² would have looked fine on every one of those fits.

### The one to keep

*A result that looks fine from the inside is not evidence that the method could
have seen the alternative.* Ask what the measurement would have shown if the
opposite were true, and check the instrument can show it — before reporting
either an effect or its absence.

### A detector needs TWO negative controls, not one (added 2026-08-25)

A sibling's dead-note audit over 9433 converted programs reported **70 with keys
that go silent**, and it was a false-positive rate rather than a finding: it used
an absolute threshold — "no voice decaying slower than 0.25 s" — and one flagged
program has a source envelope that genuinely decays in 0.17 s. **0.17 s against
the 0.084 s of the artefact it was hunting is a factor of two, which is not a
discriminator.**

The fix was to apply the same test to **both sides** and report only the
difference: flag a key only where the conversion goes silent and the source does
not. That gave **0 of 9433 with the fix in, and 108 programs losing up to 59
keys each with it reverted.**

**The control had to be run twice.** The loose version *passed* its
fix-reverted control — it did report the known-bad programs — and was still
wrong, because it also reported 70 good ones. So:

> **A detector that reports zero is indistinguishable from one that cannot see.
> A detector that reports seventy is indistinguishable from one that cannot tell
> the difference.**

Both failures need a control, they are different controls, and **only the second
one looks like a result while it is happening.** A zero invites suspicion; a
large number invites a bug report. Run the negative control on the detector's
*positives* as well as on its zero.

## §69 — The rate law measured properly: 1% from byte 60 to 100, and flat in key (2026-08-24, live)

A purpose-built calibration bank — flat looped white noise, zones root-matched
so nothing is resampled, **loop-in-release asserted at the byte** (§63's own
subject does not have it), two independent noise draws at two sustain levels,
and two presets differing **only in root key**.

Everything below is on that subject, fitted 15 dB clear of the noise floor with
residual thirds printed, over falls of 38–57 dB.

### The premise: the byte is a SPEED

| preset | sustain byte | level at note-off | dB/s |
|---|---|---|---|
| draw A | 100 | −10.8 | 27.96 |
| draw A | 76 | −27.8 | 28.31 |
| draw B | 100 | −10.8 | 27.97 |
| draw B | 76 | −27.8 | 28.33 |

**17 dB apart at note-off, the same dB/s to 1.3%**, reproduced on two
independent draws. §63 argued this from two sustain levels on a subject that no
longer exists; it now holds on one that can be rebuilt from its own description.

### The mechanism: rate does not depend on key, or on distance from root

One sample, one envelope, one voice; only the root key differs between the two
presets, so a note played in both is the same audio at a different distance from
its root.

| note | root 72 | root 96 |
|---|---|---|
| 72 | +0 → **27.98** | −24 → **27.95** |
| 84 | +12 → **28.00** | −12 → **28.03** |
| 96 | +24 → **27.99** | +0 → **28.00** |

**Six captures, 27.95 to 28.03, spread 0.3%, across root distances −24 to +24.**
The same distance reached from either preset agrees to 0.05 dB/s, which is a
free internal control the design provides.

**So the machine does not scale envelope rates with key, and does not scale them
with distance from root either.** §65 reached the first half over a narrow range;
this settles both over four octaves.

**And it moves the unexplained curvature off the machine.** The musical material
showed an apparent release rate climbing from 28 to 39.6 dB/s toward the top of a
keygroup. On a stationary source at the same pitches the rate does not move at
all. **That climb is the sample's own contour showing through a fit that assumes
the envelope is the only thing moving** — not an envelope property, and not
anything a converter can correct by changing a rate byte.

### The law, measured across the range it is used in

| byte | measured | §63 predicts | ratio |
|---|---|---|---|
| 60 | 46.48 | 46.59 | 1.00 |
| 72 | 23.70 | 23.65 | 1.00 |
| 88 | 9.67 | 9.58 | 1.01 |
| 100 | 4.84 | 4.86 | 1.00 |

**Within 1% at every byte, including byte 100 — twelve outside §63's fitted
window of [60, 87].** Residuals 0.41–0.43 with thirds inside ±0.12.

`dB/s = 1382 × exp(−0.0565 × rate)` stands **as written**, now over a measured
60–100 rather than a fitted 60–87 with extrapolation beyond. A seven-point refit
proposed by the sibling project should not be adopted: it was pulled by a pair of
floor-contaminated points from this bench, and at byte 72 it predicts 23.88
against the 23.70 measured here.

### Two things the run settled on the way past

**A merge places presets by NEITHER field in the file.** The bank was written
with its preset bodies at ordinals 0–5 and its table-of-contents entries at
10–15 — the two disagree inside one file, which is a writer bug. Merged over a
resident six-preset bank they landed at **P006–P011**: appended, as §48
describes. Neither number placed anything, and the resident preset at `P000` was
never at risk.

**A new disc image on an already-enumerated SCSI id appears without a restart.**
The bank was written to a card volume the machine had enumerated hours earlier
with different contents, and the new bank was visible on the next browse. This is
the second instance, after §64's hot SD swap.

### The run that had to be thrown away, and what it looked like from inside

The first attempt was started with the LCD still in the disk browser after the
merge. **§47: a Program Change is honoured only on the main preset page.** So the
editor protocol's preset-select moved the *edit* target while the *sounding*
preset never changed — **fourteen captures of one preset, labelled as six**, with
every parameter write landing on presets that were not making the sound.

It did not look like a failure. Preset names read back correctly, roots read back
correctly, the pair-identification checks all passed, and every capture produced
a clean fit with small residuals. **The tell was in the data**: the skeleton swept
the rate byte from 60 to 100 and returned **28.4 dB/s at every one of them** — a
control that changes nothing is either a broken control or a broken run.

It was caught by someone listening, who said *what you are playing right now is
not noise* before the numbers had been read at all.

**So the identification discipline of §68 was necessary and not sufficient.** The
run verified everything about *which preset it was addressing* and nothing about
*which preset was sounding*, and those are different questions on a machine where
one bus carries edits and another carries notes. `select_verified` now reads the
LCD back after every Program Change and refuses if two presets share a screen.

*Verify the thing that produces the measurement, not the thing you addressed.*

## §70 — The top keygroup's scatter was the FILTER, and musical material cannot measure the rate law (2026-08-24, live)

The pitch sweep on musical material came back non-monotonic and wide — **18.34
dB/s at +8 semitones from root, 50.51 at +16, 36.07 at +12** — with *low*
residuals, so each was a straight fall with a wildly different slope. §69 had
just shown the machine's rate does not move at all across −24..+24 on a
stationary source, so it had to be the material.

These voices carry a filter-envelope release with a large `FEnv → FilFreq` cord,
which the calibration bank deliberately does not. The cutoff is **fixed** while
transposition slides the sample's spectrum across it, so how much energy the
closing filter removes depends on pitch — and not monotonically, because it
depends on where that sample's energy happens to sit relative to a fixed corner.

Same discriminator as §64's: take the cord to zero and re-measure.

| semitones from root | cord 31 (as found) | cord 0 |
|---|---|---|
| +4 | 27.74 | **28.18** |
| +8 | **19.05** | **28.22** |
| +12 | **39.46** | **28.13** |
| +16 | **49.38** | 25.23 *(18 points, note-off only 20 dB over the floor)* |
| +24 | 39.77 | no fall to fit |

**Zero the filter cord and a 19-to-49 dB/s scatter collapses to 28.1 ± 0.05**,
matching the noise bank and §63's prediction of 28.02. Residuals fall from
0.23–1.49 to 0.13–0.19.

**So the "release rate" measured on musical material is the amplitude envelope
and the filter closing together**, and the filter's share depends on pitch. It
is not an envelope property, not key scaling (§69 excluded that on a clean
subject), and not something a converter fixes by changing a rate byte.

### Which means musical material cannot measure the law

The same four-byte skeleton run on both subjects:

| byte | noise bank | musical (mid keygroup) | §63 predicts |
|---|---|---|---|
| 60 | 46.48 | 46.72 | 46.59 |
| 72 | 23.70 | 23.84 | 23.65 |
| 88 | 9.67 | **8.97** | 9.58 |
| 100 | 4.84 | **4.51** | 4.86 |

**The two subjects agree to 1% at the fast bytes and diverge by 6–7% at the slow
ones**, and the musical thirds turn curved exactly where they diverge (−0.19
+0.36 −0.17 at byte 100 against ±0.05 on noise). The filter release runs at its
own fixed rate, so on a *slow* amplitude fall it finishes early and stops
contributing partway down — bending the curve and dragging the fitted slope.

**The purpose-built subject was necessary and this is the measurement that shows
it.** Not for the reason it was commissioned — the loop-in-release flag — but
because a preset with any filter modulation at all cannot measure an amplitude
envelope. §63's original noise preset was right to have the cord zeroed, and
that detail was the load-bearing one.

### And a caution for anyone matching a release by ear

A listener hears the amplitude envelope and the filter together. **Calibrating
the amplitude rate byte to a target dB/s is necessary and not sufficient for
matching what someone hears** — the filter envelope has to be converted
faithfully too, and on a bright transposed sample its contribution can be larger
than the amplitude envelope's. The two machines' filter sections must agree
before an amplitude calibration is audible as a match.

## §71 — The recalibrated conversion, measured against the machine it copies (2026-08-24, live)

The first bank either project has converted with a release rate taken from a
hardware measurement rather than from a constant. Loaded alone — **Load, not
Merge**, so the two conversions were never resident together and their shared
sample names could not come into play at all.

**Identified by what the machine reports**, not by which bank was loaded: the
release rate byte read back **80 on all three sustaining voices**, where the
same voices read 69 earlier the same day.

### The envelope, partner muted, at notes within ±11 semitones of a root

| keygroup | semitones from root | dB/s | residual |
|---|---|---|---|
| low | −8 | **15.30** | 0.44 |
| mid | +6 | **14.59** | 0.20 |
| top | +4 | 10.12 | **2.57** |

**Against the source machine's 15.224 dB/s: +0.5% and −4.2%.** Against the same
notes on the previous conversion — 27.17 and 28.21 — the new bank is 1.78× and
1.93× slower. **The error against the source was 87% before and is 0.5–4% now.**

### Time from note-off to the noise floor, whole preset

| note | reference preset | old conversion | recalibrated | ratio |
|---|---|---|---|---|
| 26 | 0.05 s | 0.84 s | 1.37 s | 1.63× |
| 40 | 0.03 s | 0.88 s | 1.31 s | 1.49× |
| 52 | 0.02 s | 0.90 s | 1.56 s | 1.73× |
| 64 | 0.03 s | 1.14 s | 1.84 s | 1.61× |
| 72 | 0.19 s | **1.30 s** | **2.64 s** | **2.03×** |
| 84 | 0.20 s | 1.17 s | 1.36 s | **1.16×** |

Same rig, same gain, same notes and hold as the pre-erase captures, so the two
older columns are recorded audio rather than a second resident bank.

**Keep the first column.** The preset in it releases in **0.02–0.20 s** at every
note while the faithful conversion takes **1.3–2.6 s** — two orders of magnitude
apart. **It is not ground truth for a release and using it as one would condemn
a correct conversion.**

> **Corrected 2026-08-25: it is not a library original either.** This section,
> §66 and §67 all call it "the reference preset" and §71 called it hand-built
> from a library. **It is an EARLIER CONVERSION of the same source program**,
> produced by the same sibling writer. Three things settle it: the E-MU library
> material for this row is the ten-preset synth-bass set at PC 0–9, whose
> names were read off the machine and share nothing with this preset's;
> the voice counts 6 / 8 / 7 across the group match three separate builds of the
> conversion and nothing in the library; and the preset names are that writer's
> truncation of the source program names.
>
> **Which makes the two orders of magnitude a better result, not a worse one.**
> All three columns are conversions of one program at three stages — before the
> loop-in-release flag (§64), after it, and after the rate calibration (§71).
> The first column is not a different instrument that happens to release
> quickly; it is **this** instrument with the flag missing.
>
> And it dissolves a coincidence §66 recorded without explaining: that "the
> reference bank" and the conversion share all sixteen sample names. Of course
> they do — **both came out of the same writer.**
>
> *Which bank on the card each preset came from is still open*: the load
> boundaries observed here are PC 0–9, 10–21, 22–33, 34–39 for the four banks in
> their documented order, which puts the group at 34–39 in the FOURTH bank, not
> the third. That is a question for whoever holds the files.

### The two numbers that are not rates, both predicted before the run

- **The top keygroup's residual of 2.57** against 0.20–0.44 elsewhere. §70: the
  filter release runs at its own fixed rate, so on a *slower* amplitude fall it
  finishes early and bends the curve. Same signature as the 6–7% divergence at
  slow bytes in the both-subjects skeleton. **Predicting that a number would be
  uninterpretable, and finding it uninterpretable, is a result.**
- **Note 84 moving only 1.16×** where everything else moved 1.49–2.03×. It is
  +12 from the top keygroup's root, i.e. outside the window where the envelope
  dominates. Every note inside ±11 of a root moved by half to double; the one
  note outside it barely moved.

Neither is a defect in the conversion, and both would have looked like one to
anyone reading the table without §70.

### What is left

The mid keygroup's −4.2% is the largest remaining discrepancy and it is smaller
than the filter's own contribution at those pitches. **Nothing about it should be
chased until the filter envelope's release direction has been measured**
(TODO.md) — §43's law is fitted on rises only, and correcting a few percent
against an assumed reference is how a few percent becomes a lot.

## §72 — Three constants checked, and the clipping trap that nearly ate the first one (2026-08-25, live)

Three checks on constants a sibling project shipped with nothing behind them,
all on the calibration bank's noise preset at a root-matched key, envelope parked
to jump to full and hold, filter cord zeroed. Every parameter saved first and
restored on every path — 19 of 19 read back identical.

### The trap: a wide-open filter is the loudest thing the voice makes

The first pass **clipped**, and clipped exactly where the answer was being read:

    cutoff byte   251  252  253  254  255
    samples at full scale    1    4   14   57  172

and every attack capture clipped as well. **A clipped measurement and a
saturated filter are indistinguishable from the shape of the answer alone** —
both make the top bytes look identical, which is what the table under test
predicted. Caught by Jan before it produced a number.

The control that separates them is **two source levels**: if the saturation
point stays at the same byte it is the filter, if it moves it is the output
stage. Everything below was repeated 12 dB down, all peaks −2.4 to −12.7 dBFS,
zero clipped samples, with the absolute peak printed beside every result.

**The source's own headroom is not the output's.** This bank is authored at −6
dBFS deliberately; that says nothing about what a wide-open filter plus the
preset's and the output pair's gain do downstream.

### 1. The cutoff does NOT saturate — 252–255 are not identical

8–16 kHz band energy, bytes 248 → 255, at −12 dB:

    108.94  109.40  109.84  110.26  110.65  111.03  111.39  111.73

**Monotonic, 0.35–0.46 dB per byte, still climbing at 255.** Maximum spectral
deviation from byte 255: **2.68 dB at 252**, 1.98 at 253, **1.00 at 254**.

**And the level control says it is the filter and not the output stage**: the
clipped run gave 2.76 / 1.79 / 1.01 for the same three bytes. The pattern did
not move with level, because there is no saturation point to move. Positive
control passed — byte 200 differs from 255 by 45.8 dB.

Writing 255 for a fully-open filter remains correct; **treating 252 as
equivalent to 255 discards about 2.7 dB**, and a sibling reports 742 voices at
fully-open across one disc, so it is the commonest setting there is.

### 2. Resonance is flat from byte 88 to 110 and steps at 112

Peak height against a Q=0 reference at the same cutoff:

| byte | 88 | 92 | 96 | 100 | 104 | 108 | 110 | 112 | 116 |
|---|---|---|---|---|---|---|---|---|---|
| dB | 20.56 | 20.25 | 20.67 | 20.72 | 21.03 | 21.05 | 21.05 | **23.66** | 23.70 |

**0.8 dB across 22 bytes, then 2.62 dB between 110 and 112, then nothing.**
§52's "clamps at 112" is that step and the flat above it.

The question asked was whether a table entry at 108 is a typo for 104. **The
measurement says the distinction is not audible in that region**, because the
machine has no gradient there to interpolate across — a mis-placed anchor
between 96 and 110 lands on a plateau either way. The step at 112 is what
matters. (The absolute dB here is a spectral peak height and not the same
observable as a resonance figure in a spec table; the *shape* is the result.)

### 3. Rate byte 0 is instant, and it agrees with §57 from the other side

The first estimator measured note-on-command to steady, carrying an unknown
fixed latency, and returned **rate 1 faster than rate 0** — impossible, and the
tell that it was unreliable at the end being tested. Replaced with an
offset-free measure: time between two points **on the rising edge**, steady−20
dB to steady−3 dB, at 0.5 ms resolution.

| rate | 0 | 1 | 2 | 3 | 5 | 8 | 16 | 24 |
|---|---|---|---|---|---|---|---|---|
| ms | **0.5** | **0.5** | 16.0 | 22.5 | 15.0 | 22.5 | 41.5 | 84.0 |

**Rates 0 and 1 complete inside one 0.5 ms window.** So the rate law's ~31 ms
floor at byte 0 is not a floor and the byte is genuinely instant.

**And it puts the boundary where §57 put it, from the opposite direction.** §57
measured *decays*: rates 0 and 1 silent, rate 2 a 0.0 ms burst, rate 3 the first
usable rung. This measures *attacks* and finds rates 0 and 1 instant with rate 2
the first that takes measurable time. Two directions, two runs, one boundary.

## §73 — The last unexplained shape was the instrument beating against itself (2026-08-25)

The top keygroup's knee — residuals of 2.16 and 2.35 against 0.22–1.26
elsewhere, consistent across rate bytes, surviving §65's key-scaling exclusion
and the floor-contamination correction of §63 — has an answer, and it needed no
bench time. A sibling project measuring a different machine found periodic
structure in its own release residuals and suggested the same test here.

Residual spectra, 0.5–20 Hz, cubic detrend, on the release of all nine
clean-load captures:

| capture | peak-to-mean | top three (Hz / magnitude) |
|---|---|---|
| low, +4 | 2.5× | 4.83/10.8 3.86/10.0 19.32/6.6 |
| mid, +6 | 5.1× | 4.83/10.7 3.86/7.4 5.80/4.1 |
| top, +4 | 4.0× | 4.83/11.5 3.86/8.8 1.93/7.0 |
| **top, +12** | 5.6× | **1.93/43.8 2.90/34.7 0.97/27.5** |
| top, +24 | 2.1× | 3.86/6.4 2.90/6.4 13.53/4.6 |

**The one capture with the knee is the only one whose release is dominated by a
low-frequency series, and its magnitudes are four times anything else** —
0.97 / 1.93 / 2.90 Hz, a fundamental and its harmonics, which is what several
detuned oscillators produce. The instrument is a layered electric-piano type
whose layers are deliberately detuned. It beats.

**Two controls make it a result rather than a coincidence.**

**The clean captures are not quiet — they carry 3.86 Hz**, and this preset's
LFO1 runs at **3.78 Hz** (read from the file by the sibling). So the estimator
detects real few-Hz modulation everywhere, at the frequency the file predicts.
That rules out "everything beats, this one louder" *and* validates the
instrument in the same measurement.

**And the noise bank shows nothing**: peak-to-mean 2.1–2.5× with magnitudes 7–11,
against 4.9–12.2× and magnitudes to 127 on musical material. Noise has no beat
frequency and the measurement says so.

### What it costs and what it is worth

**A second independent reason for a stationary calibration subject**, after
loop-in-release: every rate measured on musical material carries this and the
noise bank cannot. It also gives the both-subjects skeleton divergence at slow
bytes (§70) a candidate that is not the filter release — **both stay open**, since
that divergence grew toward the slow end, which fits a filter finishing early
and does not obviously fit beating.

Three things were blamed for the top keygroup across one evening — key scaling
(§65, excluded), the filter (§70, real but not this), and the sample's contour —
and the residual structure inside the fits was none of them. *A fit's residual
is data. If it has a shape, something made it.*

## §74 — The preset send path works, and the first attempt failed on a bug in the READ path (2026-08-25, live)

First host-initiated preset dump this project has ever made. Verified the way a
transport should be: **dump a preset, send it to an empty slot, dump that slot,
compare byte for byte.**

    source P018, a single-voice organ preset, 438 bytes
    retargeted to P100 -- only the first two bytes differ, checked
    P100 before: 'Empty Preset'
    send returned in 0.5 s
    P100 after:  the same name, 1 voice
    read back:   438 bytes, IDENTICAL

**A byte-identical return does not depend on the inferred half of the handshake
being semantically right.** The spec states that a preset may be dumped *to* the
E4 but not who acknowledges what on a host-initiated transfer; that half mirrors
the receive direction. If the bytes come back, the transport worked whatever the
negotiation is doing — which is why this was chosen over a functional test.

**And the inference was right:** the device ACKs the header and each data
packet, exactly as it expects to be ACKed when sending.

### The first attempt failed, and not where anyone was looking

    ValueError: unexpected 0x7b while waiting on the dump header

`0x7B` is EOF. The device had not answered the header at all — **it was the
trailing EOF of the preceding dump, still sitting in the input queue.**

`dump_preset_old` loops `while len(data) < header.byte_count`. When the data
completes exactly on the count, the loop exits **without reading the EOF the
spec says the sender "must" send at the end of a transfer.** Nothing in a dump
notices: the caller gets correct bytes, every test passes, and the frame simply
waits. **The next exchange then reads it as the answer to its own first
question.**

Fixed in the read path, where the bug is: both dump paths now consume the
trailing EOF, and anything that is *not* an EOF is pushed back rather than
swallowed, because dropping a real reply would be worse than the bug. The send
path additionally drains with a **settling** window rather than an instantaneous
one — a frame the device sent microseconds ago has not arrived yet and is not
drained by a loop that returns immediately.

**This is the same shape as §68's four defects, in our own code:** a read path
that was correct in everything it returned and wrong in what it left behind,
invisible until something downstream asked the next question. It survived a
verified live dump (§7) and 489 passing tests because **nothing had ever spoken
to the device immediately after a dump.**

*A function that leaves the shared resource dirty is not correct, however
correct its return value.*

## §75 — A four-voice preset with a multisample voice, built entirely by dump send (2026-08-25, live)

The first real use of the send path (§74), and the result is a capability rather
than a number: **a sibling project's hand-edited preset body was transferred to
the machine in one operation, and the machine holds exactly what was sent.**

The edit restructured a six-voice preset into four, collapsing three
single-zone voices into **one multisample voice carrying three key zones**, and
changed four cutoff bytes and four modulation-cord amounts.

    P100 before: 'Empty Preset'
    sent 1320 bytes, retargeted from preset 0 to 100
    P100 after:  the sent name, 4 voices, 6 sample zones
    read back:   1320 bytes, differing in exactly ONE byte -- offset 0, the
                 retarget itself. 1319 of 1320 identical.

Structure as the machine holds it, and `preset_num_szones` agrees independently
at 6 = 3+1+1+1, so this is not a parser reading its own assumptions back:

    voice 0: E4_GEN_SAMPLE -1 (multisample)  zone count 3  zone samples 4,5,6
    voice 1: 1    voice 2: 2    voice 3: 3   zone count 1 each

**No `NEW_VOICE`, no `NEW_SAMPLE_ZONE`, no `COMBINE`** — none of the `20h`/`30h`
family, which has still never been sent to this machine. And the reason that
matters is not the commands saved: **the alternative's failure mode was a
half-built preset**, a state neither project could have described, produced by
commands never exercised. **A single transfer has no intermediate state to be
wrong in.**

### The renumbering, and why it ran even though it changed nothing

Sample references in a dump are **numbers**, and a bank's numbering depends on
what else is resident (§67). So the sibling supplied its zones keyed by sample
*name* and never sent a number, and the numbers were resolved here against RAM
at the moment of use.

It resolved to a no-op — the body descended from a dump of the resident bank, so
its numbers were already RAM numbers, provable without names at all. **It was
run anyway**, at the sibling's insistence, so that the path carrying the *next*
body — which will not descend from a resident dump — is one that has been
proven rather than reasoned about.

### The name match that had to be exact, and nearly was

The names first supplied did not match what the machine reports:

    supplied        machine reports
    <base>          '<base>_C2'
    <base>1         '<base>1_C3'      ... and four more

**The supplied name is a prefix of all six.** One file carries two names per sample — a
plain one in its table of contents and a display name with the root note
appended for the machine — and the projects were reading different fields. A
resolver falling back to "starts with" or "closest" would have **bound every
zone to the same sample and reported success.**

The resolver refused, because it requires exactly one exact match. That rule was
written for a different hazard — a sibling had seen two single-byte corruptions
in resident RAM in thirty hours, and a fuzzy-matched corrupt name binds a zone
to the wrong sample silently — and it covered this one for free.

**It must also refuse on ambiguity, not only on absence.** Display names are
built by truncating the base to make room for the root suffix, so two samples
with different names can collide into one display name while their table-of-
contents names still differ. **Machine-reported sample names are not guaranteed
unique.**

### And §47 collected another one

A check of "does a bare program change reach preset 100" was run with the panel
still in the disk browser after a merge. **All four program changes were
silently ignored** — PC 0 and PC 100 returned the same screen, indistinguishable
from each other. Walked back to the preset page, the same test passes and is
repeatable.

*The trap is not that the page matters. It is that a dropped Program Change
produces a plausible measurement of the preset that was already selected.*

## §76 — The General(20) block is ids 37–56 in id order, pinned two ways (2026-08-25, live)

A hand edit made at the front panel, dumped and diffed against the body that was
sent, resolved the voice-parameter block's first group outright.

**The diff was five words**, one of them the preset number:

    voice 0 word 2     0 -> +10      voice 2 word 2    -6 ->  -8
    voice 1 word 2   -16 -> -18      voice 3 word 2   -16 -> -18

Four voices, one index, values in dB — **word 2 is `E4_GEN_VOLUME`, id 39.** And
the whole block follows:

| word | id | | word | id | | word | id |
|---|---|---|---|---|---|---|---|
| 0 | 37 GROUP_NUM | | 4 | 41 CTUNE | | 8 | 45 KEY_LOW |
| 1 | 38 SAMPLE | | 5 | 42 FTUNE | | 9 | 46 KEY_LOWFADE |
| 2 | 39 VOLUME | | 6 | 43 XPOSE | | 10 | 47 KEY_HIGH |
| 3 | 40 PAN | | 7 | 44 ORIG_KEY | | 11 | 48 KEY_HIGHFADE |

words 12–15 are ids 49–52 (`VEL_*`), words 16–19 ids 53–56 (`RT_*`).

**Pinned twice, independently.** A sibling project located words 1, 7, 8 and 10
by *column matching* — searching the block for the one index whose values across
all voices matched a vector predicted from its own converter output, and
refusing on anything but a unique hit. Those four land exactly on their
id-order positions, and that method never used the ordering. **Neither
derivation is a transcription of the spec**, which gives only the group sizes.

It also settles a mapping that was deliberately left open: a voice word holding
`12` looked like a transpose and is **`E4_GEN_CTUNE`** (id 41, coarse tune,
*Voice only*) — which is why it has no counterpart in a zone block. The zone
block's 13 fields are the General(20) **minus the six *Voice only* ids** (37,
41, 43, 53–56), exactly `SAMPLE_ZONE_PARAM_IDS`.

### A saturated field is not a measurement

The edit was made by ear to correct a level imbalance no measurement had
explained. **Voice 0 sits at `+10` — the field's maximum** — and the other three
were then moved *down* by 2 dB each.

**That is what running out of range looks like.** The balance shift actually
wanted is **at least 12 dB of attack against sustain, and 12 is a lower bound**;
the listener raised one layer until it stopped rising and continued in the only
direction left.

*A control at its end stop records where the range ended, not where the person
wanted to be.* Fitting a correction to `+10/−2/−2/−2` would encode the ceiling
as if it were a choice. The way to recover the unclamped figure is to move all
four proportionally — 0 and −12 — and ask whether that is still right or whether
more is wanted, which is another listen rather than another build.

## §77 — The voice parameter block is `word = id − 37`, and column matching is retired (2026-08-25, live)

Every field offset either project had found by searching for a predicted column
lands on one formula. The spec's group sizes are the reason:

    General(20)   ids  37- 56   ->  words   0- 19
    Tuning(11)    ids  57- 67   ->  words  20- 30
    Amp/Filt(37)  ids  68-104   ->  words  31- 67
    Lfo/Aux(24)   ids 105-128   ->  words  68- 91
    Cords(54)     ids 129-182   ->  words  92-145

Contiguous, in id order, 146 words — **so the word index of any voice parameter
is `id − 37`.**

**Tested against the machine rather than asserted.** Fourteen fields read out of
a live dump at `id − 37` and independently over the editor protocol from the same
voice of the same preset: 14 of 14 exact, spanning all five groups.

| id | word | | id | word | | id | word |
|---|---|---|---|---|---|---|---|
| 38 SAMPLE | 1 | | 70 VENV_SEG0_RATE | 33 | | 83 FMORPH | 46 |
| 39 VOLUME | 2 | | 74 VENV_SEG2_RATE | 37 | | 146 CORD5_AMT | 109 |
| 44 ORIG_KEY | 7 | | 78 VENV_SEG4_RATE | 41 | | 149 CORD6_AMT | 112 |
| 45 KEY_LOW | 8 | | 47 KEY_HIGH | 10 | | … | |

**This retires column matching for this format.** That method — searching the
block for the one index whose values across all voices match a predicted vector,
refusing on anything but a unique hit — found words 1, 7, 8, 10, 46, 109 and 112
correctly and was the right tool when the layout was unknown. It cost a
predicted vector per field and could only find fields that happened to vary
between voices. **The rule costs nothing and covers all 146**, including every
field that is identical across every voice and therefore invisible to a column
search.

Worth keeping the sequence, though: the rule was *derived* only after the
matched offsets existed to check it against. **Four independently matched
offsets agreeing with a formula is what made the formula credible** — proposing
it first would have been a guess with a plausible shape, which is the thing that
has cost this bench the most time.

### It also confirmed a defect and two decay times on the way past

The dump was taken so a sibling could locate the amplitude envelope for a
preset whose four voices carry two distinct envelopes in a 2-2 pattern. With the
rule, no search was needed and the structure reads straight out:

    v  keys      Dcy1 rate
    0  24- 38      86
    1  39- 52       3     <- choked
    2  45- 76       3     <- choked
    3  72-127      86

**Note 48 falls inside voices 1 and 2 and nothing else, and both are choked** —
so that note has no sustaining voice at all, which is the click-then-silence the
sibling measured at −85 dBFS against a source that rings for seconds.

And §63's rate law reproduces their two decay figures from the bytes on the
machine, over the ~98 dB span:

    rate 86 -> 10.7 dB/s -> 9.12 s      converter says 9.123 s
    rate  3 -> 1167 dB/s -> 0.084 s     converter says 0.084 s

Two chains — a converter's own arithmetic, and a rate law measured on white
noise here — meeting to three figures.

### The defect's shape, which is not about mute groups

The sibling's mute-group model replaced the losing voice's envelope across its
**whole key range**. A choke can only bite where the two keygroups **overlap**;
elsewhere the partner is not sounding and nothing chokes. Their code contained
an overlap test, it was correct, and it decided *whether* to cut rather than
*where*.

*Pointing at the line that implements a check is not checking that the check
does what its name says.* Finding the code is evidence about the code's
existence and nothing more — the same family as a test whose subject sits
outside the range where the effect exists, which will pass for whatever reason
happens to be available (§72).

### Confirmed by ear and by meter, with a control nobody planned

The corrected preset was sent back over the path built earlier the same day
(§74/§75) and measured against two other arms. Note 48, RMS in successive
windows:

| | | | | | |
|---|---|---|---|---|---|
| source machine | −25.9 | −24.0 | −25.0 | −24.0 | −27.0 |
| original conversion | −44.4 | **−85.9** | −85.8 | −86.0 | −86.1 |
| split, envelopes untouched | −44.9 | **−86.0** | −85.7 | −86.3 | −86.3 |
| scoped fix | −11.7 | **−8.7** | −11.1 | −13.3 | −22.7 |

**The middle arm is the control and it matches the original within 0.5 dB.** The
voice split on its own changes nothing audible; scoping the envelope is what
fixed it.

**That control existed only because of a mistake.** The sibling's first body
wrote the decay rate to word 39 — `Dcy2`, which the source leaves at zero — so
the split happened and the envelopes did not. It was caught here by reading the
body at `id − 37` and finding 33 dead notes where the author's own check
reported none, and the discarded build then turned out to be exactly the arm
that rules out "the split did it". **Nobody would have built it deliberately.**

*The author's verify passed because it read back the word it had just written.*
A check that reads the field it wrote proves the write happened and nothing
else — the same error as pointing at the line that implements a check, one
remove further in.

**And the discriminator that made the disagreement actionable**, rather than two
parties contradicting each other: the same code, on the same field, had
reproduced the author's description of the *unmodified* preset exactly minutes
earlier. **A reading that agrees on one artefact and disagrees on the next is
more likely to have found a real difference than to have broken in between.**
The general fix is to pin an offset against a value both sides have
independently observed — here `[86, 3, 3, 86]` — *before* writing anything,
which turns an offset from an assumption into a measurement.

## §78 — A one-second window averages a moving transient, and a static filter model is looking in the wrong place (2026-08-27, live)

Measured while running a cord sweep for mpc2emu on the AKAI key-follow question
(their §AKAIKEYFOLLOWHW). The conversion-side conclusion belongs in their tree;
what is recorded here is the measurement lesson, which is ours and applies to
every filter number this project has produced.

The subject was one voice of a four-voice conversion — the voice covering keys
72–127 — with a single parameter swept: the Key→FilterFreq cord amount, at
0/−10/−20/−29/−40/−46 percent. Six preset bodies, each differing from the
zero arm in **exactly one word** (verified by byte-diff before sending), all six
captured in one process at one gain.

### The window is not neutral when the filter is moving

Every metric this rig uses reads a **1-second window from onset + 0.05 s**:
`spectral_ab`'s third-octave profile, the level error, `octave_check`. An
average over that window is only safe if the thing being averaged holds still.

It does not hold still when the voice carries a filter envelope. Resolving the
same window into 50 ms steps, on the band that carries essentially all of the
top note's energy:

    t/ms      0     -10    -20    -29    -40    -46
      50    0.0     1.0    4.4   11.8   -5.0  -10.5
     500   -4.9    -3.3    1.9    0.9  -13.5  -19.1
    1150   -7.7    -4.1    2.3  -12.5  -22.8  -27.2

At −29 that band swings **24 dB inside a single note** (+11.8 at 50 ms to −12.5
at 1150 ms), against 8 dB at cord 0. The one-second number is an average across
that swing, and where the swing sits moves with the parameter being swept. So a
sweep of a filter parameter partly measures *how much of a moving transient
happened to fall inside the window* — which reads back as a mysterious
non-monotonicity in the parameter.

**Any law fitted to a windowed level or a windowed spectrum, on a voice with a
filter envelope, carries this.** That includes §43's filter-envelope law and
§63's rate law; §63 is safe because it fits a slope within the window rather
than a single average, but the distinction was never stated and is stated here.

### The static corner is not where the filter is

The static model put the corner at 427–673 Hz across the sweep. The ratio
spectrum against the zero arm — each arm's fine spectrum divided by the zero
arm's, which cancels the source, the other voices and the rig, and cannot have
its peak moved by a gain offset — puts the moving transition at **2–4 kHz**.

The gap is the filter envelope, at 50% on this voice: the corner during the note
sits far above its base value, and the swept parameter only sets where the
excursion *starts*. A model of base cutoff plus resonance predicts none of this
and cannot be corrected into predicting it, because the term that decides
whether the resonance ever crosses a given partial is the envelope amount.

### Two things that made the result readable

- **A ratio against a controlled zero arm, not an absolute spectrum.** The five
  swept arms differ from the zero arm in one word, so everything else divides
  out exactly. This is what let a 2–4 kHz transition be asserted against a
  427–673 Hz prediction: the alternative — reading a corner off an absolute
  spectrum — would have been reading it off the source's own harmonic
  structure.
- **Checking where the energy actually is before trusting a peak.** The first
  pass masked bands at −60 dB of peak and reported a boost peak walking from
  7184 Hz down to 1068 Hz, which looked like a beautifully clean moving
  resonance. It was noise: the top note's energy is concentrated in ONE
  1/12-octave band about 80 dB above every other band, and the "peak" was
  wandering around in the floor. At a −40 dB mask the effect is real but sits
  somewhere else entirely. **A monotonic-looking result across five points is
  not evidence of anything if the bands it moves through hold no signal.**

### Also confirmed here

- RAM does not survive a power cycle (already recorded), but **the sample
  numbering after a fresh load of the same bank does**: the reloaded preset 0
  dump was byte-identical to the dump taken from the previous load, so bodies
  holding sample numbers from an earlier session remained correct without a
  name-resolver pass. Checked rather than assumed, and it is a check worth
  repeating rather than a rule worth trusting.
- The `F4` compact LOAD dialog (§ above) drove a bank load with the LCD read at
  every step and the machine back on its main preset page afterwards. Six
  Program Changes across the sweep, six distinct screen hashes — §47's trap
  cannot be ruled out by intent, only by a check that distinguishes the arms,
  and identical preset names mean the hash of the preset page is that check.

### §78 corrected — the moving transient was the finding, not the flaw

§78 above says the one-second window averages a transient whose position moves
with the swept parameter, and treats that as a reason to distrust the windowed
numbers. The observation is right and the conclusion drawn from it was wrong.

**When the thing being averaged is moving, the movement is a result. Measure
it.** What the window was averaging away was how long the note lasts, and note
duration is a property of the instrument, not an artefact of the analysis. The
correct response was a second metric, not less confidence in the first.

This was caught by a listener, not by a number. Told that one arm sounded
shorter and that the shorter one matched the source, a decay measurement was
built — dB per second between two FIXED times inside the held note, so that
unlike a peak-anchored fall time it cannot be moved by where the peak lands
(on one arm the peak lands on note-off, which made a fall-time metric rank it
best when the raw envelope shows it never decays at all). On that measure the
swept parameter has a clear optimum, and it is NOT at the value the spectral
metric prefers:

    parameter        third-octave distance      decay error
       0                    4.72                 +2.9 dB/s
     -20%                   7.96                 -1.1 dB/s

So the two metrics disagree, both are sound, and the earlier conclusion that
one end was simply optimal held only because a whole axis was unmeasured.

Two things worth keeping from how it went wrong:

- **The data was already in hand.** A band-envelope table taken for a different
  purpose showed one arm collapsing 24 dB inside a single note against another's
  8 dB. That is the entire finding, and it was read as evidence about the
  measurement rather than about the instrument.
- **A single-axis "optimum" needs the axis named.** Stating it without the
  qualifier is what made a partial result read as a settled one.

Also recorded because it will confound the listening test that follows: the
arms differ in LEVEL as well as in decay, by about 17 dB at the top note, and a
quieter note stops being audible sooner. It reads as shorter whatever its decay
rate is, so a preference between two arms is not evidence about decay until
they are level-matched.

## §79 — A layer that is nominally in range and contributes nothing, caught by a positive control (2026-08-28, live)

A sibling session proposed that one voice of a four-voice conversion was masking
another and so damping a filter effect we were trying to measure. Testing it
needed a preset with that voice removed — easy — and then a way to know the
removal had actually happened, which is the part worth recording.

**The measurement and its control in one table.** Level of the note, the full
preset minus the same preset with only the top-of-keyboard voice kept:

    note      36      43      48      55      65      80      96
    dB     +47.0   +47.4   +46.8   +46.8   +52.3   -0.05   -0.05

The two right-hand columns are the result: at the notes under test the removed
voices change the level by five hundredths of a dB, so they were contributing
nothing and could not have been masking anything. The five left-hand columns are
the control that makes that readable — below key 72 the removed voices are 47–52
dB of real signal, which proves the edit removed what it claimed to.

Without those five columns, "no difference at notes 80 and 96" has two
explanations that look identical: the voices are inaudible there, or the build
did not drop them. **A null needs a column where the same manipulation produces
a large effect, in the same file, from the same run.** Here it came free,
because the voice being kept has a limited key range and the sweep already
spanned it — which is worth designing for rather than noticing afterwards.

The same 2x2 (stacked/solo at two parameter values) put the release rate within
0.4 dB/s across every cell, on two notes and two bands, so the difference under
investigation belongs to the remaining voice alone.

### Two of my own conclusions this retracted

- I had warned that comparisons against the source were contaminated by the
  extra layer. At these notes they are not; the layer is silent and the earlier
  numbers stand. The caution was reasonable and it was wrong, and it was cheaper
  to test than to keep carrying.
- I had proposed that a two-day-old reference capture was stale across a power
  cycle. An independent measurement on the live source came back at 15.1 dB/s
  against that file's 15.2/15.2/15.8, so the reference was sound. **A reference
  is not stale because it is old; it is stale if it disagrees with the thing it
  represents, which is a question with an answer.**

Both were hypotheses raised to explain a disagreement, and both dissolved under
a measurement that took minutes. Worth the habit: when a disagreement invites
several explanations, the cheap discriminating measurement beats ranking them by
plausibility.

### §79 addendum — the state that nobody verified was the source machine's

The disagreement that produced the measurements above was a listening test:
the source was reported to sustain longer than our conversion, while four
independent metrics said our conversion was the shorter one. It was resolved
by the listener discovering he had been auditioning **the wrong program on the
source machine.**

The asymmetry is what is worth recording. Over the same hours this session:

- verified our own device state by dumping all eight slots and comparing them
  byte for byte against the files sent;
- verified the two-day-old reference capture against an independent live
  measurement on the source, agreeing to 0.7 dB/s;
- verified every Program Change had landed by requiring distinct screen hashes;
- verified a null result with a positive control in the same table.

**Nobody verified what was loaded on the machine being compared against.** It
was the one piece of state in the chain with no check on it, and it was the one
that was wrong. Four correct measurements were then spent explaining a
difference that did not exist — the level-matching confound, the monitoring
chain sitting downstream of the capture tap, the stacked-layer contamination.
Every one of those was a reasonable hypothesis and none of them was the answer.

The rule this suggests is narrow and cheap: **when a comparison spans two
machines, the far machine's state needs the same verification as the near
one's.** "Which program is resident, confirmed by reading it back" costs
seconds and is not harder to do on the other end of the bench.

The investigation was still worth running. It produced §79's control, the
retraction of two of my own hypotheses, and an isolated finding — the converted
voice's release is roughly 1.6-1.8x too fast against a source figure measured
independently — which is real, is unrelated to the false alarm, and would not
have been found without chasing it. Ruling out a contradiction is not the same
as wasting the effort on it.

## §80 — A median is only readable if the values agree, and two baseline numbers were not (2026-08-29, live)

Re-running the conversion matrix against a freshly built bank meant comparing
twelve patches against numbers recorded a week earlier. Two of those baseline
numbers turned out to mean nothing, and the thing that exposed both was a
column the harness does not compute: **the spread of the per-note values the
median was taken over.**

The pitch feature is a median of `cents_err` across the notes played. The
summariser already refuses to report an octave unless a majority of notes
tracked AND all agree — a good rule, written after a median of two disagreeing
octaves invented a fault. But `cents` has no equivalent guard: once the octave
test passes, the median is taken and reported however far apart the values are.

    slot   old cents   new cents   old spread   new spread
      A       1.5         1.4         46.1        49.7
      B      41.2        21.5          0.7        51.0

Slot A sat in the report's "everything else — within 3.4 cents" tier on a
number whose four notes disagreed by 46 cents. Slot B's baseline was tight and
trustworthy; its fresh measurement is not, and reading the pair as "improved
from 16.4 to −3.3" would have been reporting a change in the tracker's failure
mode as a change in the conversion.

**The values behind a summary statistic are evidence about whether the summary
should be believed, and they are already in the file.** Nothing had to be
re-measured to find this — the per-note features were sitting in both JSON
files the whole time. Printing the spread alongside the median costs one line
and converts a confident wrong number into a visible refusal.

### What the spread is diagnosing

Both bad cases are the same shape: values clustered at two points about 50
cents apart. That is a source sitting near a semitone boundary, with the
tracker rounding to whichever side each note lands on — so the "error" is an
artefact of where the boundary falls, and the median lands in the empty middle
where no note actually was. A bimodal set has no meaningful median, and a
spread of ~50 cents is its signature.

### The check that did work

The octave question on slot B was answerable, and not by the tracker's own
octave field. The SOURCE recording was put through the identical feature
extractor: it reads an octave above the written note on every note, so the
conversion now reading an octave above written **agrees with it**, and what
looked like a new fault is the old one fixed. Confirmed independently by the
ratio of the two f0 estimates, 0.967–1.029 across four notes — same octave, no
octave field involved.

**Measure the reference the same way as the subject, with the same code, before
concluding the subject is wrong.** The written pitch is not the reference here;
the source recording is.

### Unrelated, found in the same pass and worth keeping

Two presets in the untouched reference bank peak at −0.8 and −0.7 dBFS. Nothing
clipped, because this pass plays one velocity — but the reference is what every
conversion is scored against, and a reference that clips at a higher velocity
would push every comparison against it in the same direction while looking like
a conversion error. Recorded now rather than after a louder pass finds it.

### §80 extended — on one route it is nine of twelve, and five of them answered

The two cases above were found while comparing one route. Checking the next
route's baseline *before* measuring against it — the point of the exercise —
gave a much worse picture. Per-note spread behind each baseline tuning number,
twelve patches, one route:

    spread ≤ 2 cents ....... 3 patches   usable
    spread 115-487 cents ... 9 patches   of which:
        4 the tracker DECLINED and reported nothing   (honest)
        5 the tracker ANSWERED, and the answer was reported to one decimal

487 cents is four semitones of disagreement between notes of the same patch.
Two of the five answering patches were quoted at +0.2 and +0.5 cents and filed
in the report's "everything else — within 3.4 cents" tier, on values whose
notes disagreed by 314.

**The four that declined are the system working.** The summariser's octave
guard caught those. The five that answered passed the octave test — unanimous
octave across notes — and then had a median taken over cents values spanning
three semitones, because there is no equivalent guard on cents. **Passing a
guard on one field is not evidence about another field.**

This material is organs and twelve-strings, where several partials compete, so
it is the case the original report's "tuning could not be measured" tier was
written for. The tier exists. These patches did not land in it, because landing
there requires the tracker to refuse, and it did not refuse — it produced a
number. **A tier for "unmeasurable" only protects the cases the instrument is
honest about.**

Consequence, recorded because it changes what a comparison can claim rather
than just how confident it is: on that route, nine of twelve patches have **no
tuning baseline at all**, so "did it improve" is unanswerable there by this
method and no delta should be printed for them. One patch carries a real
+44.2 cent error at 1.6 cents of spread, and that one is worth acting on. The
envelope measures are unaffected throughout — a sustain ratio is not a pitch
estimate — which is why the same comparison still says something useful about
nine tenths of what these conversions do.

The check is now in `cmp_route.py` alongside the captures rather than in a
person's memory: every median prints its spread, and a spread over 10 cents
refuses to produce a difference instead of producing a wrong one.

## §81 — Re-capturing unchanged material is how you learn what a metric's numbers are worth (2026-08-29/30, live)

A conversion metric was reporting differences of 0.07 to 0.23. Nobody had ever
asked what the metric does when **nothing changes at all**. Re-capturing six
unchanged presets answered it, and the answer rewrote part of the result.

    preset   capture 1   capture 2    shift
      A        0.058       0.060      +0.003
      B        0.051       0.022      -0.029
      C        0.134       0.077      -0.058
      D        0.092       0.055      -0.037
      E        0.085       0.068      -0.017
      F        0.093       0.073      -0.020

Same presets, same rig, same notes, same schedule. **Up to 0.058 of movement on
material that did not change**, five of six in the same direction. So a reported
difference of 0.069 is not a finding; it is inside the instrument's own scatter.

### What it cost, and what survived

Of ten conversions compared that evening, eight had been reported as improved.
The two smallest improvements were withdrawn on those grounds, and **that
withdrawal was itself wrong** — corrected below. Recomputed against the noise
floor, with each row taken from its own correct note set, the improvements are
0.069, 0.101, 0.108, 0.133, 0.142, 0.169, 0.195, 0.208 and the two regressions
are 0.191 and 0.227. **All ten exceed the 0.058 scatter**, one of them (0.069)
only just. Two further patches are percussive with zero sustain on both sides
and carry no information either way. So the tally is eight closer, two further,
two with nothing to say.

**Where the bad withdrawal came from, because the mechanism matters more than
the number.** One of the two figures, 0.090, was read off an earlier table that
mixed two different note sets — a table already corrected an hour before, for
that exact fault. Its real value is 0.133. **A superseded number was used to
withdraw a valid finding**, so a correct principle (measure the noise floor,
refuse what falls inside it) produced a wrong result because the input to it
came from a retracted source.

Applying a newly-learned rule is itself an operation that can be done wrong,
and it feels like diligence while it happens, which is what makes it hard to
catch. The guard against it is unglamorous: **recompute from the raw features
when applying a new threshold, rather than from any table you have already
written** — including your own, and especially one you have already corrected.

### The cause is the same fragility twice in one evening

The metric is `env[s_i] / peak` where `s_i = ipk + 0.8 * (hold_n - ipk)` — **the
sampling position is anchored to where the envelope peak lands.** On a patch
with a flat-ish envelope a small change in `ipk` moves `s_i` a long way, and the
ratio jumps without anything about the sound having changed.

That is the same defect as the peak-anchored fall time in §78's correction,
where one arm's peak landed on note-off and the fall-time metric ranked it best
while its raw envelope showed it never decayed at all. **A statistic anchored to
an extremum of the data is only as stable as the extremum**, and on held notes
with slow attacks the extremum is not stable at all. Two fixed times, or an
anchor at note-on, do not have this problem.

### The hypothesis this killed, which is why the control mattered

The obvious explanation was analogue compression: the first captures ran within
0.2 dB of full scale, the second set 9 dB lower, so the hot ones should have
been squashed and the cool ones untouched. **The data refuses it.** The shift is
not monotonic in level — the two hottest captures move LEAST among those that
move, the largest shift is a mid-level patch, and the coolest patch does not
move at all. A plausible mechanism that predicts a gradient, tested against six
points, was wrong.

### The general rule

**Before trusting a difference, measure the metric against no difference.** It
costs one extra capture pass over material already on hand, it needs no
hardware change, and it converts "this improved by 0.07" from a result into a
question. Nothing else in this project's history establishes the noise floor of
any of its metrics, which means every threshold used so far has been assumed.

### §81 addendum — a tool that refuses must be tested on what it should refuse

`cmp_route.py` was written for §80: print every median with its spread and
refuse to produce a difference when the spread is too wide. It was validated by
re-running a route whose answers were already known and confirming they came
back identical. That is a real check and it is the wrong one — it only exercises
the path where the tool *accepts*.

A sibling session asked whether a patch with an untracked note could produce a
confident wrong answer. Two bugs, both in the refusal path, neither reachable by
the validation that had been run:

- The delta was computed as `a and b and (b - a) or 0`. **When either median was
  `None` the chain collapsed to `0`, printing `old -> old`** — a patch whose new
  capture could not be tracked at all read as UNCHANGED, formatted identically
  to a real measurement.
- `spread()` dropped `None` entries and returned the spread of the survivors, so
  two notes out of four that happened to agree passed the width test and printed
  a two-note claim looking exactly like a four-note one.

Fixed by replacing the `and/or` with ordered explicit refusals and by returning
`(spread, n_tracked, n_notes)` so the count is printed alongside. The sibling
re-ran their own route against the fix: every previous verdict unchanged, and
several rows they had read as ordinary refusals turned out to rest on 2 of 4
notes — thin evidence that had been invisible.

**The general form: a guard is a branch, and an untested branch is an
assumption.** Validating a refusing tool on data it accepts tests everything
except the reason it exists. Feed it the shapes it is supposed to reject —
a missing value, one sample, all samples missing, a value that is exactly zero.

### And the same silent-no-op, twice in one session

The first attempt at the above fix used a string replacement whose pattern did
not match, with no assertion. It wrote the file unchanged and reported success,
and the verification printed evidence of the failure that was read past. The
same shape had already cost a commit message earlier in this project's history,
describing corrections it did not contain.

**Every scripted edit gets an assertion that the pattern matched**, and the
verification afterwards gets read rather than glanced at. It is two extra lines
and it converts a silent wrong result into a loud failure, which is the trade
this whole section keeps arriving at.

### §80 second corollary — agreement is necessary, not sufficient

§80 says a median is only readable if the values behind it agree, and gives the
spread as the test. That rule caught two bad baselines and it is incomplete in a
way that cost a claim on the same evening it was written.

Six bass-family conversions were reported as a clean tuning null: deltas of 0.0
to 0.9 cents, per-note spread about 5 cents, tight enough to pass §80's test
comfortably. A sibling session then established on native ground truth — the
source machine playing its own material, verified by spectrum — that the pitch
tracker reads bass **two octaves flat**. Checking the same thing in the local
captures:

    note   expected f0     tracked f0     error
     46      116.5 Hz      not tracked
     59      246.9 Hz        62.2 Hz     -2387 cents
     64      329.6 Hz        82.8 Hz     -2392 cents
     71      493.9 Hz       124.0 Hz     -2393 cents
     86     1174.7 Hz       295.2 Hz     -2391 cents

A ratio of 0.251 on every note it tracks, and the lowest note not tracked at
all. The sibling measured −2390 cents on a different machine and a different
route; this is −2387 to −2393 on ours. Same constant, so it is the instrument.

**Four notes agreeing tightly about the wrong partial are exactly as tight as
four agreeing about the right one.** The spread test cannot tell them apart,
because it only compares the values to each other and never to anything
external. So it is a test for *precision* and it was being read as a test for
*correctness*.

What the spread test still does: it catches a tracker that is unstable. What it
cannot do: catch a tracker that is confidently and consistently wrong. The
second failure mode needs an external reference — the source recording through
the same extractor, or the written pitch, or a spectrum — and §80's own worked
example used exactly that to settle an octave question, without noticing that
the technique was answering a different question than the spread was.

Practical form: **when a whole class of material reads the same unusual value,
suspect the instrument before the material.** Six unrelated presets all reading
exactly two octaves flat is not six patches with the same defect.

The claims that survived this were the ones involving no pitch estimate at all
— the envelope ratios. That is the second time in two days that the
pitch-independent measures were the ones left standing.

## §82 — A refusal message that named the wrong quantity cost three sessions hours (2026-08-31)

The vibrato tool refuses when the integration band it needs would be too wide
for the carrier. Its message read:

    the band needed (X Hz) would reach the neighbouring harmonic at Y Hz

**Y was the carrier frequency, not any harmonic's.** The message named a
quantity it was not printing. Three sessions — this one included — spent hours
on a harmonic-collision theory: ruling out the calibration table, layer
contamination, a tuning clamp, the filter envelope, an analysis-window artefact
that produced a false positive and had to be retracted, and finally a
loop-boundary click that turned out mathematically incapable of producing a
separate spectral line. All of it chasing a collision the message had invented.

**The real limit is arithmetic and has nothing to do with harmonics.** The first
band tried is `14 * mod` and the guard is `0.40 * carrier`, so it refuses
whenever

    mod >= carrier / 35

which for a 92 Hz carrier is any modulation above 2.6 Hz. Ordinary vibrato is
4-7 Hz, so that note was unmeasurable at any depth or rate anyone would use —
and the same voice an octave higher measures cleanly, which is exactly the
pattern that looked so mysterious.

### Why it survived so long

The refusal was **correct**. It refused when it should refuse, every time, and
returned no number. The whole file exists to avoid "a plausible number from an
instrument that could not see", and on that count it worked perfectly. Only the
*explanation* was wrong — and an explanation is not covered by the tests that
cover a return value.

**A diagnostic message is an interface, and a wrong one is worse than none.**
"Cannot measure" would have sent people to the tool's limits in minutes. Naming
a specific physical cause sent them to the instrument for hours, because it
sounded like the tool had already done the diagnosis.

### Fixed

The message now names the carrier, the limit, the ratio and the remedy, and the
docstring carries the ceiling as a table so nobody has to read the guard to find
it. Two further hazards are documented alongside, both found while answering the
question rather than by testing:

- `carrier_lo` defaults to 150 Hz, so a lower carrier is not in the search band
  at all and the tool locks onto a HARMONIC and reports it as the carrier.
- The 0.40 factor assumes the measured carrier is the fundamental. If it ever
  locks onto the second harmonic the true spacing is half what the guard
  assumes, and 0.40 becomes too permissive — **that failure is silent**, unlike
  the one that caused all the trouble.

The loud wrong explanation cost hours. The quiet wrong one is still there.

## §83 — The velocity→volume law, and a field that was never dropped but silently constant (2026-09-01, live)

mpc2emu's cross-format field-coverage audit reported `velocity_to_volume_db`
as a gap on the E4B side: "the E4XT has no law and neither reads nor writes
it". The first half is now measured. The second half was wrong, and wrong in
the direction that hides a defect rather than the one that invents one.

### The premise: not dropped, but written as a constant

Cord slot 0 of every voice of all 22 presets resident in the machine:

    P000–P009  original E4B    Vel< → AmpVol  24
    P010–P015  S3000 → E4B     Vel< → AmpVol  24   (every voice)
    P016–P021  S1000 → E4B     Vel< → AmpVol  24   (every voice)

and mpc2emu's `_MOD_TMPL` opens `0x0C, 0x40, 0x1E, 0x00` — source `0x0C`
(Vel<), destination `0x40` (AmpVol), amount byte `0x1E` = 30, which is
30/127 = **23.62 %** and is exactly what the editor protocol reports as 24.
Template and hardware agree to the byte.

So the E4B writer emits a velocity→volume cord on every voice for which
`needs_mod` is true, always the same one, inherited from the factory template
and never chosen. A source program whose velocity→volume is genuinely neutral
arrives carrying a swing it never asked for. **A field that is written as a
constant is worse than a field that is dropped**, because a dropped field is
silent and audibly absent, while a constant one is audible, plausible, and
attributed to the source.

It is also inconsistent rather than merely constant: `needs_mod` gates whether
the template is written at all, so a voice with no filter envelope, no
key-track, no velocity→filter and no LFO receives no mod table and therefore
no velocity→volume cord. The velocity response of a converted program then
depends on whether some unrelated cord happened to be non-zero. That is a
code-path reading and on this sample it never fired — all twelve converted
presets here carry the table — so it is recorded as latent, not observed.

### The law

Measured on a single-voice, single-zone preset (P008, the flattest sustain of
the ten single-voice presets at a body-ratio of 1.001), note 48, nine
velocities from 1 to 127, cord amount swept over 0 / 24 / 50 / 100:

| set amount | stored byte | true % | dB per velocity unit | swing v1→v127 | r² |
|---|---|---|---|---|---|
| 0   | 0   | 0.00   | 0.00011 | 0.01 dB  | — |
| 24  | 30  | 23.62  | 0.17754 | 22.37 dB | 0.999715 |
| 50  | 64  | 50.39  | 0.37901 | 47.76 dB | 0.999997 |
| 100 | 127 | 100.00 | 0.75108 | 94.64 dB | 0.999968 |

Per 1 % of cord amount that is **0.9470, 0.9477 and 0.9464 dB** — three
independent amounts agreeing to ±0.07 %. So:

    swing_dB(v1 → v127)  =  0.9470 × amount_percent          (94.7 dB at 100 %)
    attenuation_dB(v)    =  0.9470 × amount_percent × (127 − v) / 126

Linear in velocity and linear in the setting, which is two of the four
questions this family of measurements always asks. The third — **is 0 genuinely
neutral** — is answered by the control row: at amount 0 the level moves 0.01 dB
across the whole velocity range, so this cord is the only velocity→volume path
in the voice and zero really is zero.

The shipping default of 23.62 % is therefore a **22.4 dB** velocity→volume
swing, imposed on every voice the writer produces.

### The pivots, and the one that is not where its name says

The three velocity sources are named as a unipolar / bipolar / inverted triad
(`Vel+` 0x0A, `Vel~` 0x0B, `Vel<` 0x0C) and only `Vel+` had ever been measured.
Each was run at amount +10 and −10 against an amount-0 control, and the pivot
read off as the velocity whose level does not move:

| source | pivot from +10 | pivot from −10 | pivot |
|---|---|---|---|
| `Vel+` | −2.90 | −0.36 | **velocity 0** |
| `Vel~` | 89.92 | 88.88 | **velocity 89.4** |
| `Vel<` | 128.92 | 127.25 | **velocity 127** |

`Vel+` and `Vel<` are where the naming predicts. **`Vel~` is not.** It does not
pivot mid-scale at 64; it pivots at 89.4, and its total span at a given amount
is the same ~9.5 dB as the unipolar sources rather than twice it — so it is not
`2 × Vel+ − 1` either. No mechanism is offered here for why 89.4; the number is
reported because it is measured and because building on the inferred 64 would
be building on nothing.

**The two signs are the check that this is real.** A ceiling compressing the
gain half would move the +10 crossing later and the −10 crossing earlier, so
the two would diverge. They agree to one velocity unit on all three sources.

### The consequence for the writer

**No E4XT velocity source pivots at velocity 64**, so the AKAI's convention —
a swing rotating about 64, measured by s3ked as `swing_dB = 1.19557 × V_LOUD`
— cannot be carried by choosing a source. It has to be *constructed*:

    Vel+ at amount A                gives  swing S = 0.9470 × A, pivoting at v0
    plus a static volume trim of     −S/2  dB      moves the pivot to v64

The K2000's convention (neutral at 127, attenuating downward) needs no
construction at all — that is `Vel<`, which is also what the factory template
already uses. A unipolar source that scales from silence is `Vel+` directly.

Two hazards in that construction, both real rather than theoretical:

- **The static trim does not go in as dB** — see below. It must be converted
  through the volume curve, not written as a dB number.
- **A large swing runs out of trim.** A 43 dB AKAI swing needs −21.5 dB of
  static trim, and mpc2emu's own `E4XT_VOL_MEASURED_FLOOR_DB` is −22.90 dB.
  The trim required by the loudest real source values sits at the edge of the
  calibrated range, which is exactly the "nominal vs realised" problem their
  model docstring already anticipated, arriving from the other direction.

### `E4_GEN_VOLUME` is labelled dB and is not dB

Written as a positive control — a field specified in dB should move the capture
by the dB it is given — and it did not. Asking for −12 delivered **−8.86 dB**,
with 0.03 dB of spread across nine velocities, so the edit path is live and
repeatable and the *label* is what is wrong.

This independently confirms a law mpc2emu had already measured from the file
format: their `e4xt_byte_to_volume_db` predicts −9.172 dB for byte −12 against
the −8.858 dB measured here — **0.31 dB apart, from two entirely different
paths** (editor SysEx on a resident third-party preset, versus their
calibration against written banks). Their note that writing the dB value
straight in "delivered only half to three-quarters of the requested
attenuation" is confirmed at a new point.

The velocity→volume numbers above are unaffected: they are measured in dB from
the captures, not read off a field's label.

### Headroom, and why the sweep never needed the trim it was designed around

The plan was to pull the static volume down before sweeping, because a
ceiling-clipped point manufactures a compressive knee — the exact artefact a
"nominal vs realised" story predicts, so the one most likely to be believed.
It turned out to be unnecessary for the main sweep and the reason is worth
keeping: **`Vel<` only ever attenuates below velocity 127**, so the sweep runs
*downward* from the untouched baseline and never approaches the ceiling at all.

Baseline at velocity 127, nothing edited, all ten single-voice presets: peaks
−4.67 to −6.58 dBFS, **zero clipped samples**, note body 70–74 dB above each
file's own pre-roll. Every capture in the whole run was checked for clipping
as `max(abs(sample)) >= 32767` on raw frames — never on `peak_db`, which is a
5 ms moving average of |signal| and structurally cannot see a short clip
(§81). None clipped.

The trim was needed only for the pivot sweep, where a bipolar source adds gain
at one end whichever sign is used, and there it doubled as the positive control
that produced the dB-label finding above.

**Where the measurement actually ran out was the bottom, not the top.** At
amount 100 the three lowest velocities fall below the bench noise floor
(−88 dBFS): the nominal swing is 94.7 dB and the bench can only witness about
75 dB of it. Those points are reported as unmeasurable here, not as silence —
the machine may well be producing them.

### Two analysis faults, both of the same family

Neither corrupted a capture; both would have produced confident numbers.

1. **The note onset was computed from the schedule and the schedule was not the
   file layout.** The first analysis put the note at the `PRE` offset when it
   actually begins at arm + settle + PRE = 1.30 s, which placed the "head"
   window in the pre-roll silence and returned sustain ratios in the
   *thousands*. Visible only because the number was absurd; a smaller error
   would have passed.

2. **The fix then failed the other way.** Anchoring on the first detected onset
   presumes the first note sounds — and the first notes are the quiet ones. At
   cord amount 100 the three lowest velocities were below the detection line,
   the anchor latched onto note 4, and every window slid by exactly three notes
   (8.7 s = 3 × 2.9 s), reporting nine confident and wrong levels.

The anchor is now a **grid search**: score a whole comb of windows against the
envelope and take the offset that maximises in-window energy. The loud notes
are always present, so the comb locks on even when several notes are silent,
and it reports the anchor it found (0.78–0.79 s on every capture in this run,
across two separate processes) so a drift is visible rather than absorbed.

The general lesson is the one §78 and §81 already paid for from other
directions: **an assumed layout does not fail loudly.** A detector that can be
defeated by the very effect being measured is worse than no detector, because
it fails exactly when the experiment is working.

### §83 addendum — `Vel+` anchors at velocity 0 on the FILTER destination too (2026-09-01, live)

The pivots above were measured on `AmpVol`. mpc2emu's gap-2 floor scheme rests
on the same property holding for `FilFreq` — write the floor corner into
`vpar[60]` and the span into the cord, because `Vel+` adds from the base so
`corner(0) = base`. `FilFreq` is a different destination with its own
base-dependent conversion (§56), so it was measured rather than assumed.

**The observable is the spectral centroid of the note body, not the level.**
Opening a filter raises loudness as well as brightness, so a level measurement
cannot separate "the corner moved" from "the voice got louder", and the corner
is the whole question.

P000 voice 0, cord slot 4 (`Vel+` → `FilFreq`, which is the slot the writer
uses), base Fc byte 40 ≈ 205 Hz, amount +20 ≈ a 2653-cent sweep:

    velocity                        1     16     32     48     64     80     96    112    127
    Fc wide open, no cord        1333   1239   1186   1137   1110   1088   1078   1068   1063
    Fc 40, no cord               1122   1020    952    897    865    837    820    808    799
    Fc 40, Vel+ -> FilFreq 20    1126   1073   1066   1062   1070   1072   1072   1067   1063
    difference                      3     53    114    165    206    235    253    259    264   Hz

**At velocity 1 the cord moves the centroid by 3 Hz out of a 264 Hz sweep —
1.2 %.** Fitting the low-velocity end (where the response is still linear) puts
the zero crossing at velocity +0.5, +0.2 or −0.8 depending on whether three,
four or five points are used: within one velocity unit of zero on every
reading. `Vel+` anchors at velocity 0 on `FilFreq`, and the floor scheme's
premise holds.

**Two things not to misread in that table.**

- **The flattening at high velocity is the centroid saturating, not the cord.**
  Hz gained per velocity unit falls monotonically from 3.33 to 0.33 as the
  corner rises past the voice's content: once the filter is above everything
  the sample contains, opening it further changes nothing measurable. That is a
  property of the observable, not a nonlinearity in the cord.
- **The centroid falls with velocity even with no cord at all** (1122 → 799).
  That is the factory `Vel<`→`AmpVol` cord still doing its 22.4 dB: at velocity
  1 the note is ~22 dB down, so broadband noise makes up more of the spectrum
  and lifts the centroid. It cancels in the difference column, which is why the
  difference is what the conclusion is read from — but it does mean velocity 1
  is the noisiest point in the table, so a *small* non-zero effect there could
  be masked. A pivot at velocity −10 would show ~21 Hz at v1; 3 Hz was measured.

### The control that refused first, and why that was the run working

The first attempt used P008 — the voice §83's level work was done on — and
stopped itself: closing the filter from byte 255 to 140 moved the centroid by
41 Hz, so the filter was barely in circuit and a null would have meant nothing.
Screening all ten single-voice presets showed why: they are dark, centroids
149–430 Hz with 0.8–3.2 % of energy above 2 kHz, and byte 140 is ~895 Hz —
above essentially all of their content. P000 is the brightest, and byte 40
(205 Hz) sits inside its content rather than above it.

**The control then failed a second way, which is the more useful one.** It
captured the "wide open" reference at whatever Fc the preset happened to carry
and called it open — and P000 ships with **Fc 0**, fully closed. So the control
compared closed against less-closed, and returned a *negative* separation that
the `sep < 200` guard read as "blind" and aborted on. Two faults in one line: a
control that assumed a state instead of setting it, and a threshold applied to
a signed value. The control now sets Fc 255 explicitly and tests `abs(sep)`,
and it separates by 243 Hz.

This is the third time in one day that the measurement was sound and the layer
summarising it was not (§83's two anchor faults being the others). The common
shape is a derived quantity that cannot fail loudly: an assumed offset, an
assumed onset, an assumed starting state. What broke all three was printing the
intermediate — the anchor it found, the state it set, the separation it got —
so the summary can be disbelieved.

## §84 — Assumed state does not fail loudly, and three sessions found that out separately (2026-09-01)

Four faults in one evening's work, none of which corrupted a measurement and
all of which produced confident numbers on top of sound data:

1. **An assumed offset.** The note onset was computed from the capture
   schedule; the schedule was not the file layout (§83).
2. **An assumed onset.** The fix anchored on the first *detected* note, which
   presumes the first note sounds — and the first notes are the quiet ones, so
   at full cord amount the anchor slid by exactly three notes (§83).
3. **An assumed starting state.** A control captured its "wide open" reference
   at whatever cutoff the preset happened to carry, on a preset that ships
   fully closed (§83 addendum).
4. **A one-sided test on a two-sided claim.** That same control compared a
   *signed* separation against a threshold that meant a magnitude.

Faults 3 and 4 sat in one line and **cancelled into a stop rather than into a
plausible number**. That was luck. Had the sign fallen the other way the run
would have returned a confident null on a control that had never established
anything — and a null was the expected result, so nothing would have looked
wrong. A guard that fires for the wrong reason is not a guard.

**The common shape is not "derived summaries fail".** The inputs were sound in
every case; what failed was a quantity the code *assumed* and never displayed —
an offset, an onset, a starting condition, a sign convention. Such a quantity
has no failure mode that looks like a failure: it produces a number in the
right units, in a plausible range, with no error.

**The fix is the same in all four: print the intermediate the derivation
assumes, so it can be disbelieved.** The anchor search now reports the offset
it found (0.76–0.79 s across every capture in two separate runs, which is what
makes it checkable); the filter control now reports the cutoff it *set* rather
than the one it hoped for, and its separation in magnitude.

Two sibling projects reached the same rule from different directions the same
evening — relayed via mpc2emu, not verified here: s3ked arrived at "always
report the residuals", after a bad fit *looking* bad was what caught a
ceiling-limited run; and mpc2emu had it as "derived summaries fail while their
inputs are sound", which is the same observation one level up. Three
independent arrivals at *make the assumption observable* is worth more than any
of the constants measured that evening, all of which are replaceable by a
better measurement and none of which would have been trustworthy without it.

**Concrete rules this leaves behind**, all cheap:

- A control **sets** the state it is named after. It never reads the state a
  preset happens to be in and calls it the reference.
- A threshold on a deviation is applied to `abs(deviation)` unless the claim
  really is one-sided. "The ratio should be 1.0" is falsified by 1.4 exactly as
  much as by 0.6.
- Anything derived from a schedule, a layout or a starting condition is
  **printed alongside the result**, not just used.
- A guard that stops a run must say *which* condition stopped it, so that a
  stop for the wrong reason is distinguishable from a stop for the right one.

The measurement rig in `~/temp/e4xt_ref` was swept for the second rule the same
evening. One further instance was found and fixed: a byte-127 control asserting
that a plateau should sit AT the peak tested only `ratio < 0.80`, so a control
reading high — equally strong evidence that the metric was broken — would have
passed silently.

## §85 — `Vel~` pivots at velocity ~89, and the manual says 63 (2026-09-01, live)

§83 measured the three velocity sources' pivots on `AmpVol` and found `Vel+`
at velocity 0, `Vel<` at 127, and `Vel~` at **89.4** — the last against an
inferred midpoint of 64, with no mechanism offered.

Jan then produced the **EOS 4.0 manual's polarity figure (p.351)**, relayed via
mpc2emu, which maps each source's 0..127 control onto its applied range:

    +   0..127  ->    0 .. +127     zero at control   0
    ~   0..127  ->  -63 ..  +64     zero at control  63
    <   0..127  -> -127 ..    0     zero at control 127

The figure is **exact on two of the three sources** and it also *corroborates*
the one thing §83 could not explain: all three ranges are 127 units wide, which
is why `Vel~`'s span came out equal to the unipolar sources' rather than double
it. So the document agrees with everything measured except one number, and
mpc2emu's reading was that the measurement was the likelier of the two to be
wrong — 63 being the structurally sensible value, and the manual having earned
credit on the other two rows.

**It is not wrong. Twelve measurements now put it at 87–94.**

### What was varied, and why those things

Re-running the same measurement would have reproduced a systematic error
faithfully. So the re-check varied the two things that can produce "endpoints
right, midpoint displaced" without the source being unusual.

**Cord amount.** A pivot is a property of the source and cannot depend on the
amount. A *fixed insertion loss* when the cord is active would look identical
at one amount and separate immediately at another — halve the amount and the
apparent displacement doubles.

**Headroom.** If the gain half of a bipolar source were clipping against a
ceiling, the crossing would move as the voice is attenuated.

    vol  amount   crossing   dB/vel      r²      dB@v1    dB@v127    span
    -20      +5      88.86   +0.03904  0.99163    -3.19     +1.57     4.76
    -20      -5      91.07   -0.03575  0.99272    +3.15     -1.39     4.53
    -20     +10      88.77   +0.07799  0.99610    -6.93     +2.89     9.82
    -20     -10      90.11   -0.07633  0.99813    +6.86     -2.85     9.70
    -20     +25      90.64   +0.18900  0.99868   -16.60     +7.23    23.83
    -20     -25      89.62   -0.18666  0.99967   +16.32     -6.94    23.26
    -40     +10      87.39   +0.07783  0.99864    -6.69     +3.17     9.87
    -40     -10      93.95   -0.07367  0.99615    +6.64     -2.40     9.04

Nothing clipped in any capture. **Invariant to a 5× change in amount and to a
further ~15 dB of headroom.** A fixed insertion loss would have put the ±5
crossing near velocity 117; it is at 88.86. The spans scale 1:2:5 exactly with
the amount, and 23.83 dB at a true 25.20 % is 0.9456 dB/%, matching §83's
0.9470 from `Vel<` — so `Vel~` carries the same constant, as the figure says.

The original §83 data also rules out a *sign-independent* offset on its own,
which should have been checked at the time: a constant loss of the same sign at
both amounts would have put the −10 crossing at velocity 36, not 88.9. The
displacement tracks the amount in both magnitude and sign, which is what a
pivot is.

### It belongs to the source, not to `AmpVol`

The last route to an artefact was for the displacement to be a property of the
amplifier rather than the source. Measured again on **`FilFreq`** — a different
destination, a different preset (P000, not P008) and a different observable
(spectral centroid, not level), sharing nothing with the first measurement but
the source itself:

    velocity                  1     16     32     48     64     80     96    112    127
    Fc 40, no cord         1120   1020    952    897    862    836    820    806    797
    Fc 40, Vel~ +8         1010    924    873    839    827    822    830    842    859
    Fc 40, Vel~ -8         1234   1116   1035    959    903    852    811    775    740

    Vel~ +8 difference:    -110    -95    -79    -59    -35    -14    +10    +36    +62
    Vel~ -8 difference:    +115    +97    +83    +62    +40    +16    -10    -31    -57

Crossings **87.1 / 87.9** and **89.6 / 90.1** (whole range, and the six points
nearest the crossing). The control separated 242 Hz between wide open and
Fc 40, so the filter was demonstrably in circuit.

**Twelve measurements, two destinations, two presets, two observables, three
headroom settings, three amount magnitudes: 87.1 to 94.0, mean ≈ 89.6.** The
prediction was 63.

### What is ruled out, and what is not

- **A curved velocity map is ruled out.** It would be the natural explanation —
  endpoints are fixed under any monotonic curve and only the interior can move,
  which is exactly this signature. But `Vel<`'s attenuation is linear in MIDI
  velocity at r² 0.9997 over nine points and 0.99997 over a 95 dB range (§83).
  A map with no curvature cannot displace a midpoint by 26 units. (This was
  mpc2emu's argument; it holds up independently here.)
- **A mis-set source is ruled out** — the source id is read back from the device
  before every capture and asserted.
- **A global velocity curve is ruled out** — `MIDIGLO_VEL_CURVE` (id 216) reads
  0, linear, and was read in both runs.
- **NOT ruled out: a firmware difference.** The figure is from the **EOS 4.0**
  manual; this machine runs **EOS 4.70**. A source's zero point moving between
  revisions is the one explanation consistent with everything here, and it is
  not testable on a single machine. Anyone with EOS hardware on a different
  revision can settle it in one capture.

No mechanism is offered for 89.6. It is 0.70 of full scale, which is recorded
only so that a 0.70 later found in a scaling table has something to match
against — **that ratio is numerology until something else supports it**, and it
is not evidence for anything on its own.

### Practical effect: none today, which is why it was worth doing carefully

Nothing depends on this. The factory template and every voice in the resident
bank route `Vel<`, mpc2emu reports no local E4B routing `Vel~` into `AmpVol`,
and the writer does not emit it. The value of settling it is that **a source
named for the middle that does not sit in the middle is exactly the kind of
thing that gets assumed once and never re-checked** — and the assumption would
have been made from a document that is correct about everything else on the
page.

### §85 addendum — the pooled number, and the two things worth carrying forward

**Pooled across all twelve measurements:** mean **89.66**, sd 1.79, range
87.1–94.0, 95 % CI of the mean ±1.01. The two destinations agree within the
scatter — `AmpVol` 89.92 over ten measurements, `FilFreq` 88.35 over two, 1.6
velocity units apart. The manual's 63 is **26.7 units away, about 51 standard
errors**. This is not a close call and no further measurement will make it one;
what would settle it is EOS hardware on a different firmware revision, which is
the test recorded above.

**One law, three pivots — the useful shape for a writer.** The span result was
a by-product of a run aimed at the pivot, and it is the part a converter
actually needs: `Vel~` gives 0.9456 dB per 1 % of cord amount against `Vel<`'s
0.9470, so **the dB-per-percent constant is shared across sources**. A writer
therefore needs *one* law plus a per-source pivot, not three laws. Combined with
§83's velocity-linearity, the whole family is:

    attenuation_dB(v) = 0.7510 x amount_percent/100 x (v - pivot)
                                       [dB per velocity unit -- see the
                                        correction below on /126 vs /127]

    pivot:  Vel+ = 0     Vel~ = 89.7 (measured; manual says 63)     Vel< = 127

**Measure the response curve before choosing an operating point for a bipolar
probe.** Two `FilFreq` controls refused in a row because the base cutoff was
chosen from the byte→Hz table — byte 80 ≈ 396 Hz "sits inside the content" —
and moved the centroid by 2 Hz. The voice's *measured* sensitivity is
**+10.6 Hz per byte over bytes 20–60, flattening above 80 and then reversing**
(428 Hz at Fc 0, peaking 1036 Hz at Fc 80, back to 737 Hz at Fc 255). Both
bases sat in the dead region.

The general rule this leaves: **a bipolar source needs an operating point with
room in both directions, which is a strictly stronger requirement than "the
manipulation does something"** — the usual control only establishes the latter.
Deriving the operating point from a nominal conversion table instead of from
the response actually measured on the voice in front of you is the same
substitution as §84's assumed state, one level up: a plausible number standing
in for an observed one.

### §85 correction — two normalisations of one law, and which quantity each is

§83 stated the law as `0.9470 × amount_percent × (127 − v) / 126` and §85's
addendum restated it as `… × (v − pivot) / 127`. Those differ by 0.79 %, and
mpc2emu caught it. Neither is a typo: **they are two different quantities and
the mistake was writing them as though they were the same one.**

Their suggested resolution was the right one — refit rather than redivide —
because a denominator picked to reconcile two numbers is exactly the kind of
plausible-standing-in-for-observed substitution §84 is about. So all seventeen
slope measurements taken tonight were pooled, across three sources, five cord
amounts and three headroom settings, each divided by its own *true* amount
(stored byte / 127) rather than the value asked for:

    dB per velocity unit at 100 % cord amount
        mean 0.75097   sd 0.02288   95 % CI ±0.01088   n = 17

**That is the primitive, and it has no denominator to argue about.** It is what
a straight-line fit to level against velocity actually returns. The two swings
are both derived from it, and both are correct about different things:

    over v1..v127   (126 steps)  =  94.62 dB     what a player can reach
    over v0..v127   (127 units)  =  95.37 dB     the machine's applied range

The manual's polarity figure defines each source over the control range 0..127,
so **127 is right about the machine**. But MIDI has no note-on at velocity 0 —
it is a note-off — so **126 is right about anything playable**, and it is also
the interval the constant was fitted over. `velocity_to_volume_db` is defined as
a v1..v127 swing, so mpc2emu's `/126` is correct for that field.

This is the same nominal-versus-realised distinction s3ked raised about swing
clipping against a machine's ceiling, arriving from a different direction: the
nominal span is 127 units, the realisable one is 126 steps, and the gap is
0.75 dB. Inaudible, inside the residuals, and worth pinning down anyway —
**two normalisations that diverge silently are how a predicted number and a
measured one come to disagree months later with nobody able to say why.**

The rule this leaves: **state a measured law in the units it was measured in.**
Per velocity unit is what the fit returns; a "full swing" is a derived summary
and cannot be quoted without saying across what. Both §83's and §85's
statements are individually defensible and neither said which.

### §84 addendum — gates that can be satisfied by the wrong subject

§84 is about assumed state: a quantity the code never displays, which has no
failure mode that looks like a failure. A second class turned up the same day
and is worth separating from it, because the repair is different.

**A gate can be fully satisfied by the wrong subject.** mpc2emu's K2000 captures
(2026-09-02) used a bank-select convention that landed on program 318 — *a real
program on another bank*. That capture sounds, has a plausible envelope, passes
a level check, passes an SNR check, and passes a "did the manipulation do
something" control — because the manipulation genuinely did something, to the
wrong program. Every internal gate is satisfied. Silence at least announces
itself; this does not.

Their `_PersistentRecorder` bug is the same class: a cached client kept the
first instrument's inputs while MIDI port, channel and program change all
followed a switch correctly, so an "MPC capture" was really the K2000's inputs —
clean, analysable, entirely wrong.

**The distinction, which is mpc2emu's and is worth more than either bug: some
gates can only be satisfied by the right subject, and some cannot.** A signal
check, a level check, an SNR check and a liveness control are all satisfiable by
the wrong subject. So is a connection readback — it proves a path exists, not
what is on the far end of it.

**What does discriminate is a manipulation that shows up in the signal.** A
−12 dB parameter edit moving the capture 8.86 dB with 0.03 dB of spread across
nine velocities, or three cord amounts returning the same dB-per-percent
constant to ±0.07 %, is proof that the recording is *of the machine that was
edited* — because a recording of a different machine cannot track edits made to
this one. That is what verifies the 09-01 captures here, and it costs nothing
whenever a run already sweeps a parameter, which most of these do.

A connection readback is still worth having as the cheap early failure: it stops
a run before it wastes captures rather than after. But it belongs *below*
verify-by-effect, not in place of it.

**The structural point, and the reason this is written down rather than left in
a session:** every fault across three sessions on 2026-09-01/02 was visible in
data somebody already held, and each needed a comparison nobody had made — a
second statistic, a prior measurement, a manual, another reader. None was
hidden. And nobody was going to make that comparison unprompted against their
own work. That is an argument for building the comparison into the method, not
for being more careful.

## §86 — Committed is not durable: the rig that produced §83–§85 is not in any repo (2026-09-02)

mpc2emu made this point about their own tree and it lands harder here. Every
measurement in §83, §85 and §86 was taken by scripts in `~/temp/e4xt_ref/`,
which is **untracked, in the directory that gets periodically cleaned, with a
standing instruction to prefer deleting anything older than a week.** The prose
above is durable; the thing that produced it is on a deletion path.

Most of that is correctly scratch — 166 MB of captures, one-shot probes. Two
pieces are not, because they are fixes for faults documented above and would
otherwise be re-derived by re-hitting the same faults. CLAUDE.md puts
"ready-to-apply code" in this file, so they go here.

### The comb anchor (fixes both faults in §83)

Anchoring a multi-note capture on the first *detected* onset presumes the first
note sounds. When the quiet notes come first — any velocity ladder — a
sufficiently strong effect silences them and the anchor latches onto note 4,
sliding every window by an exact multiple of the note period and reporting a
full set of confident, wrong levels. Scoring a whole comb of windows against
the envelope locks on from the loud notes, which are always present:

```python
win  = max(1, int(0.005 * sr))                 # 5 ms envelope grid
m    = len(mono) // win
env  = np.abs(mono[: m * win].reshape(m, win)).mean(axis=1)
step = int(round(period * sr / win))           # period = pre + hold + gap
span = int(round((hold - body_lead - body_tail) * sr / win))
best, first = None, None
for off in range(int(0.20 * sr / win), int(2.50 * sr / win)):
    idx = [off + k * step for k in range(n_notes)]
    if idx[-1] + span >= len(env):
        break
    score = sum(float(env[i:i + span].sum()) for i in idx)
    if best is None or score > best:
        best, first = score, off * win         # first = sample index of note 0
```

**Report `first`.** It came out 0.76–0.79 s on every capture across five
separate processes on 2026-09-01, and printing it is what makes the anchor
checkable rather than assumed — §84's rule applied to the one quantity this
function invents.

### The reference bank's filter response (why two controls refused)

A filter operating point cannot be derived from the nominal byte→Hz table. On
P000 voice 0 at note 48, spectral centroid against `E4_VOICE_FMORPH` (id 83,
the file format's `vpar[60]`):

    Fc byte     0    20    40    60    80   100   120   160   255
    centroid  428   563   775   994  1036   970   882   823   737   Hz

**Sensitive over bytes 20–60 at +10.6 Hz/byte, flat by 80, and reversing above
it.** Byte 80 is ~396 Hz by the nominal table and looks like it sits inside the
content; it moves the centroid by 2 Hz. Two controls refused on operating
points chosen that way before the curve was measured.

All ten single-voice presets in this bank are dark — centroids 149–430 Hz with
0.8–3.2 % of energy above 2 kHz — so this is a property of the material, not of
one preset, and any filter probe on this bank needs a base in the 20–60 region.
A **bipolar** source needs room in both directions, which is strictly stronger
than "the filter does something" and is what the usual control fails to check.

### The general point

"Committed" and "durable" are not the same, and neither is "written down" and
"in the repo". The test is not whether a file exists but whether it survives
a cleanup nobody consults you about — and both projects spent an evening
treating a scratch directory as though it were storage.

## §87 — Two harness disciplines that exist only in untracked files (2026-09-02)

Applying §86's test to the rest of the rig leaves almost everything correctly
scratch, and two things that are not scratch at all. Both are **hardware**
properties rather than measurement ones, and losing them does not cost a
re-derivation — it costs a note ringing on an instrument somebody else plays,
or a preset left silently modified on their machine.

Neither is recorded here. CLAUDE.md carries the one specific instance (the
panel-divert opcode must send its counterpart on every exit path, including on
exception) but not the general practice, and CLAUDE.md is untracked by design.

### A script that sounds a note guarantees the note-off

On every exit path, not just the happy one. `try/finally` around the note is
not enough on its own: the paths that actually occur are **SIGTERM** — a
capture given too short a timeout and killed mid-run, which happened twice in
one day on 2026-08-30 — and SIGINT from an operator. A note-on whose process
dies leaves the voice sounding until someone finds the instrument, and the
instrument is shared.

    import atexit, signal
    atexit.register(all_notes_off)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(1))   # -> runs atexit handlers

`sys.exit` from the handler is what matters: the default SIGTERM disposition
terminates without running `atexit`, so registering the cleanup is not enough
unless the signal is also converted into a normal exit.

### A script that edits a parameter restores it, and reads the restore back

Every live measurement here works by editing RAM parameters on a machine whose
resident bank is somebody's working state. The restore belongs in the same
`atexit` handler as the note-off, and it must **print the value it read back**
rather than the value it wrote — §84's rule applied to the one quantity the
handler is responsible for. On 2026-09-01 roughly twenty parameter edits across
two presets were made and restored this way, and the read-backs are what makes
"restored" a fact rather than an intention.

    @atexit.register
    def restore():
        try:
            select(preset, voice)                    # re-select: it may have moved
            for pid, val in ORIGINALS.items():
                set_parameter(pid, val & 0x3FFF)
            print("restored: " + ", ".join(
                f"{pid}={get_parameter(pid)}" for pid in ORIGINALS))
        except Exception as e:
            print(f"*** RESTORE FAILED: {e} -- reload the bank from media ***")

**Re-select inside the handler.** `PRESET_SELECT`/`VOICE_SELECT` are device
state and the edit target may not be where the handler assumes — writing the
original values to the wrong voice is worse than not restoring, because it
corrupts a second voice while reporting success.

**The failure path is recoverable and should say so.** These edits are RAM-only,
so a failed restore costs a bank reload from media, not data. That is the whole
reason RAM work is delegable at all, and a handler that names the recovery turns
a scary message into an instruction.

### §87 addendum — verify the world, and the pattern that matches its own shell

Two additions, one from mpc2emu and one hit twice here without being written
down — which is the worse of the two states, since a fault that has been solved
and not recorded gets re-solved by re-hitting it.

**"The handler ran" is a claim about the code; "the instrument is silent" is a
claim about the world.** (mpc2emu, 2026-09-02.) After killing a held tone they
captured a second of audio and read −93 dBFS. The whole point of the exit-path
discipline above is a physical outcome, and the only check that speaks to it is
a measurement of the physical outcome. An `atexit` handler that provably ran
still tells you nothing about whether the note-off reached the instrument —
the MIDI port may have been closed first, the message may have been swallowed
by a filtering route, the machine may have been mid-load. One capture settles
it, and every rig here already has a recorder open.

**A process pattern matches the shell that contains it.** `pkill -f 'foo.py
--flag'` run from a shell whose own command line contains that string kills the
shell. Encountered here on 2026-08-31: exit 144, and a compound command stopped
halfway — including an edit that silently did not happen and was found only
later, which is the part that makes this a data-integrity fault and not just an
annoyance.

**The `[f]oo` bracket trick does not fix this**, and believing it does is how
the second encounter happened. It stops `grep` from matching *its own* entry in
the process table; it does nothing about the enclosing shell, whose command
line contains the pattern as literal text. On 2026-09-01 a check for "is another
session driving the hardware?" returned two matches, both of them this session's
own wrapper shells. Harmless in that direction — a false positive says *busy*
when the machine is free, which is the conservative failure — but it is the same
self-match whose other direction takes out the shell mid-operation.

The rule is not a better pattern. **Resolve to real PIDs, inspect them, and act
on the PID:**

    ps -eo pid,args | awk '$1 != PID && /pattern/ {print $1}' PID=$$

and kill those, having looked at them. A pattern is a claim about a string; a
PID is a claim about a process, and only one of those is what you meant.

### §84 addendum, second part — the class is about addressing, not about measurement

The wrong-subject failure has now turned up three times in one day, in three
domains that share no code and no concepts:

| where | the address | the wrong subject it resolved to |
|---|---|---|
| MIDI program select | bank-select convention | a **real program on another bank** — sounds, measures, passes every gate |
| JACK port connection | a cached recorder's ports | a **different instrument's inputs** — clean, analysable audio of the wrong machine |
| process matching (§87) | `pkill -f <pattern>` | **the shell issuing the command**, whose command line contains the pattern |

Two of those are mpc2emu's and the third is recorded here. The point mpc2emu
drew from the third is the one worth keeping: **this is not a measurement fault
at all.** Every instance is an *addressing* fault — a name, a pattern or a
cached handle that resolves to something other than what was meant, after which
every check downstream is satisfied by the substitute. Measurement is simply
where it becomes visible, because measurement is where a wrong subject still
produces a plausible number.

Which gives the general form: **a pattern is a claim about a string; a PID is a
claim about a process** — and the same asymmetry holds for a program number
against a dumped program, a port name against a verified signal path, a preset
selector against a read-back. In each pair the cheap side is satisfiable by the
wrong subject and the expensive side is not.

The repair is always the same shape and it is never a better pattern: **resolve
the address to the thing itself, then verify the thing.** Kill by PID after
inspecting it. Dump the program back. Track an edit through the signal. It costs
one extra step and it is the only step that can fail for the right reason.

### §83 addendum — the volume law above zero, and a static offset that leaves a swing alone (2026-09-02/04, live)

Two results that fell out of getting a test bank out of the noise floor, both
measured rather than reasoned, and both extending the "`E4_GEN_VOLUME` is
labelled dB and is not dB" finding above.

**1. The law holds through POSITIVE settings, and the 1:1 branch is wrong.**
mpc2emu's `e4xt_byte_to_volume_db` fits a quadratic `0.76732b + 0.000246b²` for
`b < 0` and returns `b` unchanged for `b >= 0` — a 1:1 positive branch that was
assumed alongside the fitted attenuation rather than measured with it. Moving
one voice from −4 to +7, an 11-unit step:

    the 1:1 positive branch predicts     10.07 dB
    the negative quadratic, extended      8.45 dB
    MEASURED                              8.53 dB

**The single quadratic holds across zero, to 0.08 dB.** The 1:1 branch is
1.5 dB optimistic at +7 and diverges further up. This is the same shape as the
−12 asked / −8.86 delivered result above, in the half of the range that had no
measurement in it — and the reason it went unnoticed is that a plausible
identity function in the untested half of a fitted curve looks like part of the
fit.

**The device's own ceiling is +10** (`get_parameter_range`, not the transcribed
table), so the usable span above a typical setting is small: a voice sitting at
−7 can gain at most 15.4 dB realised, which was not enough to lift one test
preset out of the noise at all.

**2. A static level offset does not change a velocity swing — now measured
where it was previously only inferred.** §85's evidence for this covered static
levels of 0, −12, −20 and −40 dB, **all at or below zero.** Lifting a preset
into measurable range required going *positive*, where an amplifier near unity
could compress the top of the swing and flatten the very quantity being
measured. Captured at two static settings 11 dB apart:

    static -4   swing 14.94 dB over 3 clear cells   r² 0.99997
    static +7   swing 15.27 dB over 5 clear cells   r² 0.99917

**0.32 dB apart.** The offset is neutral, and the +7 case is a five-point fit
across the full v1..v127 span rather than an extrapolation from the top of the
range — so the dB-linearity of the response is measured over the whole span,
not assumed from its loud end.

**Why the control was worth its capture.** Without it the 15.27 dB number rests
on "a static offset should not matter", which is exactly the kind of
should-not-matter that §84 is about: it would not have errored, it would have
returned a well-formed swing that was quietly about a saturating amplifier. Two
settings cost one extra capture and turn the assumption into a measurement.

**Floor-limiting is the mirror of clipping, and it compresses rather than
knees.** The same bank measured before the lift gave 3.37 dB where the file
held 14.9, because the quiet cells were at the noise floor and a swing measured
from a floored bottom is bounded by the top cell's height above the floor. **A
ceiling manufactures a fake knee; a floor manufactures fake compression.** Both
produce a clean, analysable, entirely wrong number.

**And the survival test must compare like with like.** A cell whose PEAK clears
an RMS noise floor by 10 dB can be pure noise: measured on these captures,
broadband noise peaks run **15–16 dB above their own RMS**, so a peak-vs-RMS
threshold at +10 dB admits noise on the noise alone. One preset presented five
cells that each looked 15–18 dB "above the floor" and every one was noise
(early-window RMS SNR −0.5 to +0.4 dB). Compare RMS against RMS, and print the
noise crest so the gap between the two criteria is visible rather than assumed.

### §87 addendum, second part — I recorded the pattern-matches-its-own-shell rule and then walked into it (2026-09-05)

The addendum above states the trap and gives the fix: a process pattern matches
the shell that contains it, the `[f]oo` bracket trick does not help because it
protects `grep` from its own process-table entry and not from the enclosing
shell, and the remedy is to resolve to real PIDs and act on those. It was
written a few hours before this.

Then a wait-loop for a 26-minute unattended capture was written as:

    until ! pgrep -f matrix_mpc.py >/dev/null; do sleep 15; done

`pgrep -f` matched the waiter's own command line, so the condition was never
true, and the loop ran until it was killed — exit 144. Checked afterwards:
`ps -eo pid,args | grep -c "[m]atrix_mpc.py"` returns **2** while zero capture
processes exist. Both matches are shell wrappers carrying the pattern as text.

**Nothing was lost, and the reason is worth more than the fault.** A second
waiter on the same run tested a different condition — whether the results file
had reached 61 entries — and that one fired correctly, because a row count is
not a process pattern and cannot match the thing asking about it. The run
completed, all 61 captures and four derived files are intact.

**Two things this adds to the rule as previously stated.**

1. **Writing a rule down does not install it.** The failure here was not
   ignorance of the trap; the trap was documented, by me, with the fix, in this
   file. What actually prevents it is not knowing better but never typing the
   shape at all — which argues for the habit (`ps` + explicit PID) rather than
   for the knowledge.
2. **The self-match makes a kill OVER-BROAD, not merely self-destructive.**
   The addendum framed the danger as `pkill` taking out the shell issuing it.
   Worse is available: `pkill -f matrix_mpc.py` here would have matched the
   shell *and* the real capture process, so a "clean up my stray watcher"
   gesture would have killed a 26-minute unattended hardware run at the same
   time. The harmless direction announces itself with a hung loop; that one
   would not have.

**Prefer a condition that cannot refer to the asker.** A file's contents, a row
count, an exit status — none of these can match the process testing them. A
process-name pattern always can.

## §88 — A summary loses its qualifier when it crosses a session boundary (2026-09-05)

The costliest fault of this exercise was not a wrong number. It was a **true**
statement that stopped being true when it travelled.

Four keys of a converted drum kit were reported as **silent**. They were not
silent — they peak 57–61 dB above the noise floor and read 42–46 dB of SNR in
an attack window. They vanish only in an *early* window opening at 100 ms,
because the samples behind them are 55–80 ms long and have finished before that
window starts. What was measured, and true, was "silent in the window I scored".
What was sent was "silent".

**The receiving session then found a mechanism that fitted the summary.** Sorting
the kit's sixteen samples by duration produced perfect separation — everything
under 80 ms silent, everything from 234 ms up sounding, nothing in the gap —
which reads as proof of a minimum-length limit in either the machine or the
converter. **The gap contained 100 ms.** The boundary was the analysis window's
opening time. A writer investigation followed, for a defect that does not exist.

### Both halves, because it took two mistakes

- **Mine:** a claim shipped without the condition under which it held. "Silent"
  is not a property of a sound; it is a property of a sound *and a window*.
- **Theirs, self-reported:** their own scorer had already run over the same
  captures on **peak**, which is immune to the window, and returned all sixteen
  keys measurable at 50–64 dB SNR with zero dropped notes — computed and printed
  *before* the finding was filed. The failure was not believing a peer; it was
  **believing a peer's summary over one's own measurement of the same data
  without noticing the two disagreed.**

The fix is the same shape on both sides and it is already in use elsewhere in
this project: `slot_map.json` ships beside the captures carrying how the mapping
was established and what it contradicted. **A silence claim must likewise carry
the window it was silent in.** A summary that cannot be checked at the far end is
the thing that turns one session's artefact into another session's bug hunt.

### A clean pattern is not evidence of a cause

Sixteen samples sorting by duration with an empty gap is the shape that feels
like proof, and it made the wrong conclusion *more* believable rather than less.
The pattern was real. Its cause was in the observer. **Perfect separation
constrains the boundary; it says nothing about which side of the apparatus the
boundary lives on.**

### Why several windows had to be emitted, in its strongest form

k2kremote and mpc2emu asked for four windows plus peak instead of one, so the
window could be chosen after the fact rather than baked into hundreds of
captures. That argument understated the case.

**The attack window is the only one in which these keys sound, and nobody would
choose it as the single window for a drum kit.** Had one window been emitted —
as it was before that request — the artefact would have been *undiscoverable*
without a recapture, and the writer hunt would have run until something
unrelated contradicted it. Emitting several windows did not merely permit a
better choice later; **it is the only reason the artefact was visible at all.**

That generalises past windows: **when an analysis parameter is a free choice,
emitting several values of it is not a convenience, it is the difference between
a wrong answer that can be caught and one that cannot.**

### Postscript: report a probe as refuted, not as inconclusive

The follow-up experiment — walking `E4_VOICE_START_OFFSET` up a sample that does
sound, to find a playback-duration floor — failed, and the honest description is
not "inconclusive". A 234 ms sample is clearly audible at offset 0 while a
622 ms sample is inaudible at offset 32; if that parameter were a fraction of
sample length, 466 ms would remain, nearly twice a duration that demonstrably
sounds. **That is a refutation of the assumed units**, and filing it as "the
probe was inconclusive" would have left the assumption standing for the next
person to build on.

## §89 — A check built on a signal featureless after its onset cannot detect a late anchor (2026-09-05, live)

A measurement procedure for amplitude-attack curves proposed this sanity check:
*measure the instant-attack preset; it must come out instant; if it does not,
the time anchor is wrong and every other curve is shifted with it.* It sounds
sufficient and it is blind in one direction.

**Measured, by deliberately moving the anchor on a real instant-attack capture
and asking the check's own question at each offset — first 100 ms bin relative
to that note's asymptote:**

    anchor error    bin1    bin2    bin3    the check says
      -0.30 s      -39.2   -38.6   -38.7   caught
      -0.10 s      -38.7     0.0    -0.1   caught
       0.00          0.0    -0.1    -0.4   instant
      +0.10         -0.1    -0.4    -1.0   instant
      +0.30         -1.0    -1.3    -1.8   instant
      +0.60         -2.0    -2.3    -2.7   instant
      +1.00         -3.5    -4.1    -4.3   caught

**An early anchor is caught at 0.10 s. A late anchor passes to about 0.6 s.**
That is structural rather than incidental: after an instant onset the signal is
flat, so starting the window late simply lands on more of the same. The check
can only see the direction that exposes the pre-onset silence.

**Late is the direction that damages the measurement**, and it damages it worst
where the check is least able to see it. A late anchor skips the first Δ of
every ramp, so every attack is measured *faster* than it is — the window opens
partway up the ramp. The error scales against each subject's own attack time:
0.3 s is 1.7 % of an 18-second attack and **essentially all of a 0.3-second
one.** So the fast subjects are corrupted most, and the instant subject —
the one being used as the validator — shows nothing at all.

### What to check instead

- **Validate on a moderate KNOWN attack, not on the instant one.** An attack of
  the same order as the tolerable error is sensitive to it, and a known nominal
  value gives a prediction that can fail. An instant attack is shape-insensitive
  to a late anchor by construction and can only ever catch the early direction.
- **Use both edges.** A note-off is a sharp falling edge and an independent time
  reference owing nothing to the attack: `last_energy − first_energy` must equal
  the commanded hold. Measured here as **14.00 s against a commanded 14.0** on
  the reference capture. Two edges constrain the anchor; one does not.
- **Carry the reference in every capture, not once per set.** The rig offset
  here is stable at 1.200 s and still carries **40 ms of scatter across 52
  captures**; one reference capture does not validate the others. Where only one
  preset sounds at a time this forces a bank design change — an anchor zone on
  a key no subject uses — rather than a procedure change.
- **Bin finer than the error you intend to catch.** At 250 ms bins a 100 ms late
  anchor is invisible even on a fast subject.

### The general form

**A validator must be sensitive to the failure it is validating against.** An
instant attack is the most obvious thing to test an anchor with and one of the
worst, because the property it demonstrates — flatness after onset — is exactly
the property that hides a late anchor. §84's rule was that a gate can be
satisfied by the wrong subject; this is the sibling: **a gate can be satisfied
by the right subject in a state that carries no information about the thing
being gated.**

Worth pairing with the other half, from the same afternoon: on a slow-attack
sound the audio's first energy is **not** the note-on. Onset detection on the
subject gave 4.36 s and 5.62 s for notes commanded at 1.70 s, because it finds
where the ramp crosses the threshold. So "take the anchor from the audio rather
than the schedule" needs the qualifier **"from a fast-attack reference in the
same capture geometry"** — the schedule can lie, and so can the subject's own
onset.

## §90 — A clamp boundary cannot be located by reading the clamped value (2026-09-05)

Three of the day's faults were plausible numbers that measured the wrong thing.
This one is different and worth naming separately: **a correct measurement, read
wrong off its own output.**

A pitch-ceiling sweep reported a sample capping one semitone early. The cause,
relayed from k2kremote: the **last tracking key's partials equal the frozen
value**, because the frozen value *is* that key's rate and everything above
clamps to it. Reading the boundary out of the value column therefore puts it one
row early — the first clamped row and the last unclamped row are numerically
identical.

**That is general and it has nothing to do with pitch.** Wherever a quantity
saturates, the last unclamped sample and the first clamped one carry the same
value by construction. So:

> A clamp boundary is invisible in the clamped quantity. It is only visible in
> the RELATIONSHIP the clamp destroys — the ratio, the slope, the increment —
> which is flat on one side and not on the other.

Re-derived from the ratios rather than the column, all four points fitted a
96 kHz ceiling with no residual: no offset, no second framing, nothing left
over. The discrepancy that prompted a mapping hypothesis did not exist.

**This is directly relevant to work in this file.** Several findings here turn on
detecting saturation — `e4xt_cord_saturates` re-saturating a cord at the end of
the cutoff byte (§56), floor-limited velocity cells compressing a swing (§83
addendum), converter clipping manufacturing a knee (§81). In every one of those
the boundary was found by watching a *slope* go flat, not by reading a level,
and §90 is the reason that was the right instrument rather than a stylistic
choice.

**The cost of the underlying bug, for scale.** The same investigation found one
function serving two callers with different needs — writing a stored authoring
field, and deciding how far a zone may extend. The authoring convention was
correct for the first and wrong for the second. Split: **78 zones that were
dropped entirely now place, and 519 more stop being clipped**, across 69 banks.
And a dropped zone was never silence — hole-filling put a neighbour across those
keys, so they sounded **the wrong sample**, which is the wrong-subject class of
§84 arriving as an audible defect rather than a measurement one.

## §91 — A warning can be correct, specific, and about the wrong thing (2026-09-06, live)

A converted bank measured 20 dB below its neighbour bank. Two explanations were
proposed and **both were refuted by measurement**, and the more persuasive one
was persuasive because it named the right presets for the wrong reason.

### The measurement that settles the constant

mpc2emu's `e4xt_byte_to_volume_db` is a quadratic fitted only to byte −30, with
`E4XT_VOL_MEASURED_FLOOR_DB = -22.90` marking where the fit ends; below that it
extrapolates. A writer feature deliberately writes bytes past that point, so
the question was whether the extrapolation holds. **Swept on hardware, every
voice of one preset set together, one capture per byte:**

    byte    measured Δ    curve says    error
     -10        -7.33        -7.65      +0.32
     -20       -14.78       -15.25      +0.46
     -30       -22.58       -22.80      +0.22
     -39       -29.64       -29.55      -0.09
     -43       -32.23       -32.54      +0.31
     -50       -37.46       -37.75      +0.29
     -60       -45.00       -45.15      +0.15

**The extrapolation is good to byte −60 at ±0.46 dB. `-22.9` is a conservative
label for where the fit was taken, not a boundary where it stops working.**
That is worth having independently of the investigation that prompted it.

**And the mechanism under suspicion works.** A voice-level trim of −29.6 dB plus
a velocity cord of +29.4 dB, measured on one preset against *itself* — trim in
versus trim out, no cross-preset comparison — lands at **−0.33 dB** against a
predicted −0.2, while carrying the full 24.5 dB velocity ramp it exists to
produce.

### The warning that named the right presets for the wrong reason

The converter's own build log had flagged, by name, the exact three presets that
measured low: *"the velocity-pivot trim puts N levels below the measured volume
floor, written by extrapolation."* It named the worst one, and that was the
preset independently measured worst. Every part of it was true.

**It was not the cause.** The extrapolation is accurate there, and the cord
cancels the trim to a third of a dB. The warning correlates with the symptom
because the trim is written for sources with a large velocity swing, and those
sources are plucked instruments — which is also what measures low in a fixed
window, for reasons of envelope and spectral content that have nothing to do
with the trim. **The warning and the symptom share a cause without either being
the other.**

**That made it more convincing, not less.** A diagnostic that names the right
subjects reads as confirmation. The general form:

> A warning can be correct, specific, and about the wrong thing — and naming
> the right subjects is exactly what makes it persuasive. Correlation between a
> diagnostic and a symptom is not evidence of mechanism, however precisely the
> diagnostic is worded.

Separating them needed a measurement neither the log nor the file could supply:
the constant the warning was about, checked against the machine.

### Two instrument faults, caught by physical implausibility

The first calibration attempt returned a "volume law" that moved 4 dB across 39
bytes, went **non-monotonic**, then fell off a cliff. Both faults were mine:

1. **The preset has two voices and only one was attenuated.** The other held the
   level, so the parameter appeared nearly inert.
2. **A blocking parameter read-back sat inside a timed note loop**, so each
   note's spacing grew by one MIDI round trip and the later notes — the deepest
   bytes — were progressively mis-windowed by a comb assuming a fixed period.

Neither was caught by a guard. What caught them was that **a volume control
cannot be non-monotonic**: the result was not merely surprising, it was
impossible, and impossibility is the cheapest error detector available. The fix
for the second was to stop assuming the schedule and capture one note per
arm — the same lesson as §89 arriving from the writing side rather than the
reading side.

## §92 — A trim written twice and restored once, and how to find a byte the editor protocol cannot reach (2026-09-06, live)

A converted bank rendered its plucked presets ~37 dB below its organ presets.
Every named parameter on both sides was checked and cleared over several hours.
**The cause was the velocity-pivot trim being written to two places and
cancelled in one:** the voice-level volume *and* every zone volume carry it,
while the velocity cord restores a single copy. Net **−29.50 dB**, measured.

### The measurement

Four bytes changed on the resident preset, nothing else:

    A  as dumped          v1 -82.81   v64 -70.92   v127 -56.55
    B  voice copy zeroed  v1 -56.31   v64 -41.54   v127 -27.04

    v127 change   +29.50 dB
    velocity ramp  26.26 dB -> 29.27 dB   preserved (and fuller: A's v1 was floored)

Dump → edit → `send_preset_old` → read back (exactly the four bytes differ) →
measure → re-send the original dump, **verified byte-identical**. RAM only.

### Locating a field the editor protocol cannot address

`E4_GEN_VOLUME` (id 39) is `SAMPLE_ZONE` scope: with a zone selected it writes
that zone, and there is no voice-scope route to it. Setting
`SAMPLE_ZONE_SELECT` past the last zone is a no-op — checked, 0.02 dB. So the
voice copy is unreachable from the parameter interface, and every attempt to
"remove the trim" through id 39 removed only half of it. **That is why three
separate ablations reported the trim as cancelling correctly: they were all
zeroing the copy that the cord already cancels.**

**The method that found it uses the scope limitation as the instrument:**

1. Dump the preset.
2. Zero everything the editor route *can* reach — every zone volume.
3. Dump again and diff: the changed byte pairs are the reachable fields.
4. Search the dump for any remaining field decoding to the same value.
   **What is left is what the editor cannot reach.**

Here that gave zone fields at 362/388/414/440 and 760/786/812/838, and two
further pairs decoding to −39 at **70 and 468** — where `468 − 70 = 398` is
exactly the voice-block stride (`760 − 362`). The structural check confirms the
identification without appealing to any writer's own array indexing, which is
the thing that could not be trusted: the peer's byte diff had named the field
from the emitting code and had picked the wrong voice out of several matching
candidates on the first attempt.

### The lesson the whole investigation converges on

Across a day of this: an extrapolation theory, a misread A/C comparison, two
wrong-subject measurements, and — mine — **a three-point model that fitted the
data to 0.10 dB and was not evidence for anything.** Two rival models, one with
the second trim copy and one without, fitted all three points equally well,
because they differed only in a quantity no measurement constrained. It was
written up as confirmation of the peer's hypothesis before that was noticed,
which is the failure mode §88 names as hardest to catch: a result that confirms
what the recipient already believes.

> **Every arithmetic argument in this investigation was underdetermined or
> wrong. Every ablation was decisive.** Change one thing, watch the level move.

That settled the trim cancellation, the filter, the amp envelope, the sample
swap, and finally this. **A model that fits is not evidence while a rival fits
equally well — and the way to tell them apart is never a better fit.**

### Live edit versus build path

A byte edit on a resident preset proves what the *machine* does; it proves
nothing about the code that writes the file. The fix (make the voice-level
write conditional on the voice being multi-zone — a single-zone voice has no
zone byte and must keep the trim) still needs capturing from a bank built by
the shipping path, because a writer change can miss in ways a hand-zeroed byte
never would.

### §92 addendum — the fixed build, and what the defect does to tables already taken

The row was rebuilt through the shipping writer. Diffed here independently of
the peer's report, and agreeing with it: same size (1027938 bytes), **nine
bytes differ**, every one a voice-level volume going to zero — six reading
signed −43 and three −39.

Two things that diff settles, and one it does not.

**The file and the wire disagree about width.** Nine bytes in the bank file
correspond to the *four* bytes edited on the resident preset: the E4B stores
the voice volume as one signed byte, the SysEx dump as a two-byte pair. An
offset learned on one side does not transfer to the other, and neither does a
count. This is the same trap as the voice-stride check in §92 — the only safe
transfer between the two representations is structural.

**The conditional and unconditional fixes coincide here, and the conditional is
still the right one.** All nine trimmed voices in this bank are multi-zone, so
both forms emit the same nine zeroes. A single-zone voice has no zone byte to
carry the trim and must keep it, which no bank in this column happens to
exercise — a fix can be indistinguishable from a wrong fix on the material at
hand and still be the one to ship.

**What it does not settle is any absolute level already recorded.** The whole
E4B column was built by the defective writer, so for every trimmed preset in
it, the captured levels are ~29 dB low. Those numbers are not wrong as
measurements — they are a correct record of what that build produced — but
**they cannot be read as conversion fidelity, which is what a confidence table
is for.** The distinction is the same one §84 keeps making: the measurement was
sound and the subject was not what the table claimed it was. A table inherits
the defects of the artefact it measured, and nothing in the table shows it.

**And a fix confirmed on the hardware still cannot be captured.** The E4XT
reads its banks from an ISO on a card in the drive emulator; there is no host
path to that medium while it is in the machine. So the RAM-only route that made
the diagnosis possible — dump, edit four bytes, send back — does not extend to
verifying the build, because what needs verifying is precisely the part that
arrives by disk. **The diagnosis and the regression test have different reach,
and the narrower one is the one that closes the loop.**

### §92 addendum 2 — choose the capture that can fail in two directions

The obvious row to re-capture first is the one with the largest effect: the KRZ
row, where every trimmed voice rises ~29.5 dB uniformly. **It is the wrong
choice**, and the reason generalises past this bug.

That row's trimmed voices are all multi-zone, so the correct fix (drop the
voice-level copy only where a zone copy exists to carry the trim) and a wrong
one (drop it unconditionally) emit **identical bytes**. Capturing it can show
that the fix did something. It cannot show that it did the right thing, because
on that material there is nothing it could have got wrong.

The S3000 row can. Of its 36 trimmed voices, 30 are single-zone — no zone byte
exists, so `vpar[54]` is the only place the trim can live and removing it would
make those voices ~29 dB too **loud**. The conditional keeps them. Verified in
the built files here, diffing pre against post independently of the peer's
report:

    row        bytes changed   trimmed voices     all changes to zero
    KR-E4            9              9                     yes
    S3-E4            6             36                     yes
    S1-E4            6              6                     yes
    MPC-E4          12             12                     yes

**Six of thirty-six.** The writer is selective in exactly the place selectivity
is required, and every edit removes rather than adds. (The 30/6 zone split is
the peer's classification from the source; what is checked here is that the
output changed 6 and not 36, which is the observable that would differ between
the two candidate fixes.)

So the capture to run first is the one where **a wrong fix and a missing fix
fail in opposite directions** — 30 voices unchanged and 6 risen. A uniform rise
across a row is a weaker result than a split one, however much larger it is.
The habit worth keeping: when choosing what to measure after a fix, do not pick
the subject with the biggest expected effect. **Pick the subject where the
plausible wrong answers are on opposite sides of the right one**, and prefer
material that exercises the branch the fix added — otherwise the test passes
for every version of the fix, including the ones that are wrong.

This is the third time in one investigation that the material at hand could not
tell two hypotheses apart (see §92's model-fit example, and the conditional
form's invisibility on the KRZ row). Each time the fix was the same: find or
build a subject on which they disagree.

## §93 — A control can reproduce the confound it was borrowed to break (2026-09-06)

A sibling project measuring a KRZ→AKAI conversion found the row dark and
sloping — 17.29 dB fall from key 36 to key 84 where a different source row on
the same machine is flat to 0.84 dB — and had a candidate cause in its writer:
a filter-envelope depth written as 0 whenever the source's filter sustain is 0.
**Perfectly confounded**: the six programs getting depth 0 are exactly the six
string/pad programs, and the six getting depth 33 are exactly the six organs.
Same split by depth, by instrument family, and by sample set.

The proposed way out is the right instinct — **take the same source material
through a different target**, where the suspect code path does not exist. That
is what this project's KRZ→E4B row is. The question asked was: are the strings
already darker than the organs on the E4XT?

**They are, by 36.08 dB, and the answer is worthless.**

    E4XT, KRZ source, loudest cell (v127, full window), mean of 6 programs
                    k36     k48     k60     k72     k84     36->84
    corded six   -58.15  -59.43  -61.18  -62.08  -63.31     5.16
    flat six     -23.18  -22.75  -23.30  -27.67  -26.86     3.68

The E4B writer that built this row is the one from §92, which applied the
velocity-pivot trim twice and restored one copy — worth ~30 dB, and landing on
exactly the corded programs. **So the borrowed control splits four ways: dark =
strings = depth-0 over there = trimmed by the writer over here.** A control is
only a control if the suspect split does not exist in it, and *whether it exists
is a fact about the control's own build*, which the borrower cannot see and the
lender may not have looked for.

Reported as such rather than sent. Had the 36 dB gone across as an answer it
would have read as strong confirmation that the darkness is inherited from the
source material, and **it would have stopped a correct fix in another project on
the strength of a defect in this one.** The near-miss is the point: the number
was real, the measurement sound, the reasoning that requested it sound, and the
conclusion would have been backwards.

### What survived, and why that part was safe

The trim is a **static per-voice offset**, so it cannot tilt a key slope. The
slope therefore transfers even though the level does not:

    all 12 programs   slope mean 4.42 dB   sd 1.34   range 3.40 .. 7.16
    worst v127 cell sits 16.9 dB over its floor -- nothing floor-compressed

So the source material slopes ~4 dB on a target with no filter-depth path, and
~13 dB of the other project's 17.29 is not inherited from its source. **The
useful answer came from the statistic the defect could not reach**, not from the
one that was asked for.

Generalising, because this keeps recurring: **when a measurement set is known to
be contaminated, do not discard it and do not correct it — ask which statistics
the contamination cannot touch.** A static offset destroys absolute level across
subjects and leaves slopes, ratios within a subject, and shapes intact. Say
which class a number belongs to when handing it over, and hand over the class,
not just the number.

### Two smaller cautions from the same exchange

**Do not join two projects' tables on slot index.** Bank slot N is not source
position N; on the MPC row the asserted order turned out scrambled (§ slot map).
Here the two groups were separated from the data instead — the organs show a
velocity ramp of 0.02 dB, having no velocity cord at all, the strings 18–27 dB —
which identifies group membership without either project's slot map or any
preset name.

**An estimate offered as a repair must be labelled as an estimate.** Adding the
trim back through the volume law (byte −39 → 30.30 dB, −43 → 33.45, measured
removal 29.50 on one preset) puts the two groups within a few dB of each other
rather than 36 apart — but the trim byte differs per voice and no mapping from
preset to byte was made, so that is an order-of-magnitude statement. §92's
addendum already says this column cannot be repaired by subtracting a constant;
a correction offered across a project boundary is exactly where that caveat gets
dropped.

### §93 addendum — the group mean hid a split group, and the qualifier was lost in one hop

The slope figures above were sent as "the two groups slope within 1.5 dB of each
other." They came back from the other project, one message later, as *removing*
the instrument-family explanation for the slope. **That is one hop, and it is
the §88 distance in the §88 direction** — a bound arriving as a null.

The mean was hiding a bimodal group:

    corded/string six   3.56  3.72  3.75  |  5.98  6.81  7.16
    flat/organ six      3.40  3.41  3.43  3.44  4.20  4.21
    means 5.16 vs 3.68 (diff 1.48), sd 1.53 vs 0.37, ranges overlapping

Three of the six string programs slope 6.0–7.2 dB against the organs' 3.4–4.2 —
**close to double, on a target with no filter-depth path at all.** So string
material genuinely can slope ~3.5 dB more than organ material here. The mean
difference of 1.48 dB is arithmetically correct and describes no program in the
set.

The finding survives, at reduced strength: 3.5 dB is not 17.29, so the family
explanation stays bounded rather than restored. But anything downstream assuming
equal slopes across the two groups is now wrong, and per-program scatter between
the two projects' tables is genuine rather than noise.

**Two habits this argues for.** Report a group difference with its spread, or
report the members — a mean over six is one number where six numbers cost the
same message. **And when handing a null across a project boundary, hand a bound
instead**: "within 1.5 dB" invites "no difference" in a way "3.4–7.2, bimodal"
does not. The correction was cheap here because it went out before the number
reached a write-up; §88's version cost a peer an investigation into a defect
that did not exist.

## §94 — The corrected file was one filename away (2026-09-06)

A shape was reported to two sibling projects — "the organs sit flat across three
octaves, then step 4.37 dB at k60→k72, then nothing" — and one of them called it
the strongest single argument in their investigation. **It does not exist.**

    organs, as reported (free-anchor analysis)
      k36 -23.18  k48 -22.75  k60 -23.30  k72 -27.67  k84 -26.86
    organs, corrected (refit analysis, same captures)
      k36 -21.60  k48 -22.75  k60 -23.30  k72 -25.92  k84 -26.83
      steps +1.14 +0.55 +2.62 +0.91 -- monotonic, no step, no flat region
    organs, measured directly at whole-tone resolution
      k58 -23.23 ... k74 -25.81   2.58 dB spread over eight steps,
      largest single step 0.90 dB. No knee anywhere.

**The comb anchor mis-locked by ~0.4 s on 15 of 60 captures**, including every
organ k36 and every organ k72, sliding the 0.02–1.15 s window past the note-off
into the release and reading the level ~2 dB low. The refit pass had already
detected all fifteen and corrected them. Its output was in the same directory,
under a filename differing by one word, and each of the fifteen records carries
the verdict string `free fit was WRONG`. **The uncorrected file was the one read.**

### Why none of the existing safeguards fired

The anchors themselves were the tell and were visible in the file that was read:
every mis-locked capture anchored at 1.61–1.69 s where its own siblings sat at
1.26–1.42, and — the part that matters — **the fifteen bad ones are exactly the
ones carrying a finite `anchor_margin` where all forty-five good ones carry
`inf`.** §87's addendum already records that `anchor_margin` does not detect
"locked hard onto the wrong offset"; what it turns out to do here is mark the
mis-locks by the *shape* of its own value rather than its magnitude, which no
threshold would have caught and no one was reading.

The result also had a non-monotonic dip — k72 lower than k84 — of exactly the
kind that caught the first volume calibration ("a volume control cannot be
non-monotonic", §83). Applied to a key sweep it was not recognised, because
nothing says a key response must be monotonic. **A sanity rule attached to one
quantity does not transfer to another on its own.**

### What actually caught it

Not review. The table had been quoted, questioned, corrected once already for a
different reason, and had survived all of it. **A new capture at finer
resolution disagreed with it in the first thirty seconds** — 2.02 dB across a
span where the table said 4.37, on the same presets, the same bank and the same
machine.

That is the fourth time in one day: every arithmetic argument underdetermined or
wrong, every change-one-thing-and-look decisive (§92). Here the rule had already
been written down and was not applied to the one step that is invisible from
inside the analysis — **which file the numbers came from.**

### The habit

**When an analysis chain produces a corrected artefact, the uncorrected one must
not remain readable under a similar name.** Either the corrected output
overwrites the input, or the input is renamed to say so. A directory holding
`X_windows.json` and `X_refit.json`, where the second exists precisely because
the first is known wrong on 25% of its rows, is a trap with a one-word margin —
and the failure is silent, because both files are well-formed, complete, and
carry the same schema.

**And when reporting a derived number across a project boundary, name the file
it came from.** The class of the statistic was given, the caveats were given, the
contamination was declared — and the number was still wrong, because provenance
within one's own tree was the thing never stated.

### §94 addendum — the trap was in all six sets, and two scripts had it hardcoded

The file pair that produced the wrong shape exists in **every** capture set, and
the free anchor is wrong on a substantial minority of rows in four of the six:

    set        captures   corrected by the refit pass
    krE4             60     15   (25.0%)   <- every organ k36 and k72
    matrix           61     11   (18.0%)
    matrix5          66     12   (18.2%)
    matrix6          66     11   (16.7%)
    s3E4             30      1   ( 3.3%)
    s1E4             30      0   ( 0.0%)

**A 0% set is what makes the trap survivable.** `s1E4` gives identical answers
from either file, so reading the wrong one there teaches nothing and confirms
the habit. The habit then fails on `krE4`, where a quarter of the rows move.

`column_summary.py` takes its path as an argument and was always called with the
refit file, so the E4B column's absolute tables are clean. **`matrix_summary.py`
and `matrix_summary5.py` had the uncorrected path hardcoded** — a default that
cannot be corrected at the call site, and that no reader of the output can see.

**The fix, applied:** all six superseded files renamed to
`*_windows_FREEANCHOR_SUPERSEDED.json`; every `*_refit.py` repointed to the new
input name; the two summaries repointed to the *corrected* file rather than to a
merely-renamed one; and `~/temp/e4xt_ref/ANALYSIS_FILES.md` added, stating which
file to read, the correction rate per set, and why the names are shaped that way.
A rename is a weak fix in general — but it is the right one here, because the
failure was that two well-formed files with the same schema were
indistinguishable at the point of reading.

### What the recomputation then found, and did not settle

Re-deriving the MATRIX5→MATRIX6 comparison from the corrected files leaves the
per-program result standing, marginally: max delta 1.07 dB where it had been
reported as "nothing over 1 dB". Per cell, nine of 66 exceed 1 dB and four are
on the drum probe, one of them by **31.47 dB**.

That single number is either the sibling project's sparse-layer fix repointing a
layer — which is exactly what it would look like — **or a wrong-subject
comparison**, because it assumes the two banks share a slot order. The MATRIX5
map was verified on the machine; MATRIX6's was assumed to inherit it. It is not
resolvable from this side and has been put back to the project that built both
banks.

**Which is the same fault twice in one afternoon, in two different disguises:**
reading the wrong file, and joining on an unverified index. Both are addressing
faults (§84), both produced well-formed numbers, and neither was visible in the
output. The rule that catches them is the same one: **name the provenance of a
number when you state it** — which file, which slot map, verified how.

## §95 — A window edge inside a short sound turns anchor jitter into level (2026-09-06)

Comparing two builds of the same bank, one drum cell differed by **31.47 dB**.
The sibling project checked its side thoroughly and found nothing: zone
assignments identical, 16 zones, same key and velocity ranges, same samples,
sample RMS identical to 0.00 dB. They handed it back as measurement. It was.

The v127 note at that key, in 20 ms steps from its own start:

    build A   -84.7 -82.1 -35.0 -38.5 -55.1 -76.2 -83.7 -84.3 ...   hit at 40-100 ms
    build B   -85.2 -85.5 -85.1 -84.6 -34.6 -39.3 -55.7 -81.2 ...   hit at 80-140 ms

**The same hit at the same amplitude, 40 ms apart** — and the two captures'
anchors are 40 ms apart, so the offset is entirely in where the anchor landed.
The `early` window opens at 100 ms. It catches the tail of B's hit and nothing
whatever of A's, which has already reached the floor. Two identical sounds, 31 dB
apart.

    window     cells over 1 dB (of 66)   of which drum
    early              9                     4
    full               6                     0
    attack             4                     1
    peak               4                     0

The same cell reads **+0.02 dB in `full`** and −1.29 in `attack`.

### The general statement, because this is the third disguise

Anchor jitter on this bench is ±50 ms (sd 0.050–0.056 across both sets, and the
rig offset's own sd is 40–42 ms — §83). These samples last ~80 ms. **When the
sound is shorter than a few times the anchor jitter, any window edge near its end
converts anchor noise into level differences without bound**, because the two
measurements are comparing a decaying signal against a noise floor on opposite
sides of the boundary.

The same class has now appeared three times, and looked different every time:

1. **"Silent" drum keys** — withdrawn. Keys sounding at 42–46 dB SNR were
   reported dead because the window opened after the sample ended (§84 addendum).
2. **The comb anchor scored over the whole hold** — failed on percussive
   material, scattering anchors 0.38–1.22 s, fixed by scoring the attack window.
3. **This** — not a missing signal but a manufactured difference, 31 dB between
   two recordings of the same unchanged sound.

**A window is not a neutral choice of statistic. It is an assumption about the
sound's duration**, and on this bench that assumption is violated by every drum
sample in the corpus. `early` (0.10–0.40 s) is unusable for percussive material;
`full` and `attack` are robust and agreed here to 0.02 and 1.29 dB.

### What the corrected comparison then showed

With the artefact removed, the build-to-build null holds except in two places.
One was **predicted**: the sibling's sparse-layer fix repoints the zone covering
that key on one program, and that program's cell is the largest non-drum move in
every window (−4.78 dB full, +2.87 peak) — arrived at from audio, with no
knowledge of which programs the fix had touched. **The other is unexplained**:
a program not on the fix's list moves in four cells, up to +6.04 dB in the attack
window, and has been handed back to the project that built both banks.

**A confirmed prediction and an unexplained residual came out of the same
recomputation.** The confirmation is worth little on its own — it was one cell
out of 66 and could have been chance — but it was made before either side knew
the other's answer, which is the only thing that made it evidence at all.

### §95 addendum — the harness measures level, and a whole program was playing one note

The unexplained program from §95 was diagnosed by the sibling project as a
single byte — a Non-Transpose flag flipping 0→1, so the program plays its root
pitch at every key instead of tracking the keyboard. Confirmed here from the
audio, independently of their file analysis:

    P010, fundamental of the v127 note (harmonic product spectrum, 50-550 ms)
              expected     build A      build B
      k36       65.4      65.2         262.6      two octaves sharp
      k48      130.8     131.1         262.6      one octave sharp
      k60      261.6     262.6         262.6      the root, correct in both
      k72      523.3     525.9         262.6      one octave flat
      k84     1046.5    1050.3         262.6      two octaves flat

Build A tracks to within 0.5% at every key; build B is pinned at the root to
0.0% across four octaves.

**The number that flagged it was +6.04 dB in the attack window at one key, and
under 3.2 dB everywhere else** — it would have passed a 1 dB screen at three of
the five keys. A program playing a single pitch across the whole keyboard is a
total conversion failure, and the level statistic barely registered it.

**Level and pitch are independent failure modes, and this entire analysis chain
measures only the first.** Four windows, peak, SNR, floor, swing, slope — every
statistic in it is an amplitude. A conversion can put the right loudness on the
wrong note, at every key, and no amount of care with windows or anchors will
show it. That is a gap in the harness, not in the bank; the anchor work of
§86–§95 made the amplitude measurements trustworthy and did nothing whatever
about this.

**Reporting the change, not the state.** The same f0 estimator across all ten
pitched programs gives nonsense on the quiet ones — a program at −84 dBFS
returns a harmonic-product-spectrum of its noise floor, and another returns a
flat spread with a full octave of constant error because the estimator locked to
the second harmonic. None of those absolutes are usable. **The build-to-build
difference is, because the same estimator meets the same material on both sides
and its failure modes cancel.** On that basis exactly one program acquires the
fixed-pitch signature, and one other changes in the direction of better tracking
— which is the program whose zone was independently known to have been repointed.

The habit: **when an estimator is unreliable but consistent, a difference can be
sound where neither of its terms is.** State which one is being offered.

### §95 addendum 2 — a confirmation withdrawn, an estimator's failure signature named

The confirmation reported above — that the repointed-zone prediction was borne
out by the largest non-drum move in every window, arrived at from audio without
knowledge of which programs the fix touched — **has been withdrawn.**

The sibling project then established that a *second* variable changed between
the two builds: the two generations read different copies of the same audio, one
carrying a `smpl` chunk and one not. The layer fix and the source switch **both**
predict a change at that key, and metadata-only differences are demonstrably
capable of large effects — a missing `smpl` chunk is precisely what pinned P010's
pitch. So "it is only metadata" is not available as grounds to dismiss it.

The measurement stands; the attribution does not. **Second underdetermined
confirmation offered in one day** (§92 records the first), and both times the
number was real and the causal claim was borrowed from whoever needed it.

The spectra do show a genuine change at that key:

    build A  top peaks   260.0 Hz (0.0 dB)   50.5 (-4.4)   74.7 (-5.9)
    build B  top peaks  2055.5 Hz (0.0 dB)  2030.3 (-0.7)  537.6 (-2.4)
    expected for that key: 65.4 Hz -- neither build produces it

### The f0 estimator's two failure modes, both now identified

**A constant at 93.8 Hz whenever the note is weak.** It appears at every key of
the program sitting at −84 dBFS, at three keys of another at −60, and at exactly
the one key of a healthy program that is quiet (−61 and −66 dB). It is a stable
feature of the noise floor, not a pitch. Every nonsense row in the sweep is made
of it.

**Subharmonic locking.** One program read two octaves flat at one key in *both*
builds — which would have been a fault present in both generations, and was
nearly reported as one. The raw spectrum shows the expected 520.8 Hz fundamental
present at −2.5 dB, with the estimator having latched onto a 128.5 Hz peak at
−2.8 dB. A harmonic product spectrum errs downward; **an octave-up reading is
therefore worth more than an octave-down one**, and the fixed-pitch result that
started this — a constant reading two octaves *sharp* at the bottom key — is in
the direction the estimator does not fail.

**Always confirm an HPS result against the raw spectrum before reporting it.**

### An unplanned control worth keeping

At the key where nothing changed, the top six spectral peaks are **identical
between the two builds to the last decimal** — 2101.3, 2076.0, 520.8, 128.5,
145.4, 537.6 Hz, same relative levels — across two separate captures made on
separate days. That is a stronger statement about the repeatability of this
capture chain than any amplitude work in §83–§95 has produced, and it arrived as
a by-product of checking something else.

## §96 — The fix measured, and two things the prediction got wrong (2026-09-06, live)

The double-trim fix (§92) was captured on hardware: the discriminating row
before and after, 30 captures each, same grid, same session, both builds
resident on separate disc ids so nothing had to be compared across a card swap.

**Build identity was established from the wire, not from ids or names.** Both
discs carry the same four bank names and both loads leave an **identical screen
hash** — same bank name, same first preset name — so the LCD could not have
distinguished them. Dumping all six presets from each and diffing gave 12 bytes
= six two-byte pairs going to zero, decoding as **−16 ×2, −20 ×3, −29 ×1**:
exactly the value distribution the sibling project reported from the file, six
bytes there against twelve on the wire (§92 addendum's width asymmetry). One
preset was byte-identical between builds and served as the null control.

    preset  trim   predicted rise   largest observed   delta   keys risen
    P000    -16        12.34             1.64         -10.70      1/5
    P001    -20        15.44            14.90          -0.55      3/5
    P002    -29        22.46             0.02         -22.44      0/5
    P003    none        0.00             0.06          +0.06      0/5
    P004    -16        12.34            12.20          -0.14      5/5
    P005    -20        15.44            14.84          -0.61      4/5

Predictions from the E4XT volume law (§83) applied to each preset's **own** trim
byte. Where the affected voice sounds, agreement is 0.14–0.61 dB.

**Both directions of the falsifier pass.** The most negative change anywhere is
−0.05 dB across all 30 cells, so nothing lost a trim it needed; the
byte-identical control moved 0.06 dB; velocity swing is preserved within 0.12 dB
on five presets and 0.69 on the sixth.

### The prediction was wrong twice, and both were reasoning errors

**1. The magnitude was imported from another row.** TODO.md recorded "6 risen
~29 dB". That is the *other* row's trim size (−39/−43). This row's trims are
−16/−20/−29, predicting 12.3/15.4/22.5 dB. The structure was right and the
number was borrowed — the same class as reading a group mean over a bimodal
group, and the fourth borrowed quantity to go wrong in a day.

**2. "A static per-voice offset cannot bend a curve" is false as stated.** It is
true only if the voice spans the whole measured range. Two presets here change
their key-response shape — flat at the bottom, up 14.8 dB at the top — because
the trimmed voice covers only part of the keyboard. **The shape falsifier was
wrong; the fix was not.** A per-voice quantity is uniform in the key dimension
only across that voice's own span, which is exactly the thing a five-key grid
cannot see.

### What the measurement cannot answer, and why

The falsifier asked for "30 voices unchanged". **This measures keys, not
voices.** A trimmed voice that sounds at none of the five sampled keys is
indistinguishable from one that was correctly left alone — P002's contributes
0.02 dB, and P000's appears only at one key as +1.64, consistent with a raised
voice summing with unraised ones rather than sounding alone. 19 of 30 cells are
unchanged to within 0.06 dB, and under an unconditional fix the single-zone
voices would have risen too, so the evidence favours the conditional without
closing it. **Closing it needs the voice key ranges** — a file-side question,
answerable against captures already taken.

### §G0 is now bounded by a number

Leaving the pre-fix disc mounted made the morning's captures of the *same bank*
a free control on the session boundary itself:

    same 30 cells, MATRIX6 this morning vs MATRIX6 tonight
    mean -0.009 dB    sd 0.034    max |diff| 0.12 dB    cells over 1 dB: 0

Across a card removal, two re-seats, a bank reload and eight hours, **the same
bank measures the same to within 0.12 dB.** The "same session gain or it is not
a comparison" rule was a caution with no measurement behind it; it now has one,
and the answer is that cross-session comparison on this bench is sound at the
0.1 dB level. That *strengthens* the earlier cross-session work rather than
retiring it — and it cost nothing but leaving a disc where it was.

## §97 — Correlation cannot tell stereo from silence (2026-09-06)

Asked whether the rig was recording in mono, this project answered with an L/R
**correlation** test:

    bank A   corr median +1.0000   "mono-like" 6/6
    bank B   corr median +0.0142   "mono-like" 0/12   <- reported as PROOF of true stereo

and reported that bank B being decorrelated proved neither the rig nor the
instrument summed to mono. **It proved the opposite of what was claimed.** Bank
B's right channel was at **−83.5 dBFS with a peak of 20 LSB** — silence.
Correlation against a noise floor is near zero, so the test could not
distinguish a stereo pair from a live channel beside a dead one.

**The precondition was never checked: is there signal in both channels at all?**
The question asked was "do the two channels differ", which correlation answers
correctly, and the answer to that question was then used for "are both channels
live", which it cannot answer. Same shape as the SNR rule in §87 — a
peak-against-RMS threshold answers a question, just not the one being asked.

### What the level check then showed, and why the first diagnosis was also wrong

The sibling project found the dead channel and concluded the input was broken,
asking for a re-patch. Per-set R levels with timestamps say otherwise:

    13:13  MPC row     R -55.7 dBFS  peak  4752   live
    13:57  KRZ row     R -83.5       peak    20   DEAD
    14:35  S3000 row   R -40.3       peak 29763   live
    14:50  S1000 row   R -49.8       peak  3109   live
    17:41  S3000 row   R -29.1       peak 32766   live
    18:01  KRZ row     R -85.1       peak    16   DEAD

**A broken input cannot be alive at 13:13, dead at 13:57 and alive at 14:35.**
The dead channel follows the *bank*: the KRZ-converted row plays to the left
output only. The instrument and the rig are fine, and the operator who twice
reported seeing only the left channel light on the converter was right both
times — that is the correct behaviour for that bank.

**Two wrong diagnoses in ten minutes, from two directions.** One tested
correlation and never checked level; the other checked level and never checked
whether it varied by subject. **Neither error is about the measurement — both
are about which variable was held fixed while the other moved**, and the
timestamps that settled it were already on disk.

### Consequences

- **The captures are valid.** They faithfully record an instrument outputting to
  one channel; nothing needs re-taking.
- **The analysis convention is what is wrong.** Averaging a live channel with a
  dead one is **−6.02 dB**, not the −3 dB convention recorded for decorrelated
  material — so every absolute level for that row is 6 dB low. Re-derivable from
  the left channel alone, with no bench time.
- **A standing open item is partly explained.** The KRZ→E4B row was recorded as
  ~20 dB down with the cause open; **6 dB of that is this**, and whatever routes
  the row to one output is now the first thing to check for the rest.
- **Pre/post comparisons are untouched** — same path in both arms — so §96
  stands as measured.

**The rule: check that a signal exists before characterising its shape.** Level
first, then correlation, then spectrum. Every stage of this harness that reads
a waveform now has a documented failure caused by skipping straight to the
interesting statistic.

### §97 addendum — the correction is not a constant, and the swings on that row are floors

The obvious repair for a row measured as a mono sum of one live and one dead
channel is to add 6.021 dB. **That is wrong on 170 of 540 cells.**

Averaging a live channel with *silence* is exactly −6.021 dB. Averaging it with
a *noise floor* is not, and the error grows as the signal approaches that floor:

    L-only minus mono-sum, by velocity
      v127   mean +6.006   sd 0.035   min +5.824
      v112   mean +5.992   sd 0.065
      v 64   mean +5.643   sd 0.636   min +3.030
      v 16   mean +4.508   sd 1.719   min +0.611
      v  1   mean +4.001   sd 2.087   min +0.777

At the loud end a constant would have been fine, which is exactly how such a
correction gets adopted: **it is validated on the cells where it does not
matter.** The right repair is to re-derive from the surviving channel — an
L-only copy of the analysis, not arithmetic on its output.

**Nothing relative moved**, as a uniform offset should not:

    organ slope k36->k84   5.23 -> 5.23
    string slope           5.44 -> 5.48
    organ-string gap      36.70 -> 36.72 dB

So §93's argument and every shape statement stand; only absolute dBFS for that
row moves, by +6.0 dB at the loud end.

### The limitation the re-derivation exposed

The velocity swings quoted for this row are **floor-limited lower bounds under
both conventions.** Re-derived from L the corded presets gain 3.2–4.8 dB of
swing — and their v1 cells still sit at **0.8–4.9 dB SNR**, so the quiet end is
in the noise either way:

    preset   swing mono   swing L-only   v1 SNR (L-only)
    P000        23.52        26.72            4.9
    P001        17.98        22.82            1.9
    P011        22.28        26.87            1.3

**Any swing from this row is a "≥", not a value.** The untrimmed presets are
unaffected — v1 at 64–70 dB SNR, swing 0.01 dB, a real null. This does not touch
the §83 velocity law, which was measured on dedicated calibration material with
headroom.

**And the two faults compound.** The hard-left pan discards half the signal path
before the converter, so the quiet end of every ramp on this row lands 6 dB
closer to the noise floor. Fixing the pan does not merely re-centre the row — it
buys back 6 dB of usable dynamic range exactly where this row's measurements are
worst. A routing bug and a measurement limitation that look independent were the
same 6 dB seen from two ends.

### §96 addendum — the build path proves itself, 0.08 dB from the hand edit

The KRZ row captured before and after, 60 captures each, both builds resident,
analysed from the left channel alone (§97):

    v127, mean over five keys, MATRIX6 -> MATRIX7
      P000  +29.58     P003  +0.21
      P001  +32.54     P004  +0.05
      P002  +29.61     P005  +0.03
      P009  +32.62     P006  +0.18
      P010  +32.64     P007  +0.20
      P011  +32.61     P008  +0.21
    most negative change anywhere: -0.03 dB
    within-preset spread: P000 rises 29.52-29.63 across all five keys

Six trimmed presets rise, six untrimmed do not, nothing falls, and the rise is
uniform across the keyboard — these voices span the full key range, which is why
the shape caveat that applied to the S3000 row (§96) does not apply here.

**§92 measured +29.50 dB by zeroing four bytes on the resident preset. The
shipping writer gives +29.58 dB. The distinction drawn that morning — "a live
edit proves the machine's behaviour, it does not prove the build path" — is now
closed at 0.08 dB.**

### A small systematic in the volume law

    byte -39   predicted 30.30   observed 29.59   delta -0.71   (2 presets)
    byte -43   predicted 33.45   observed 32.60   delta -0.85   (4 presets)

The law of §83 **over-predicts by 0.7–0.85 dB at both byte values, in the same
direction**, where §83 records it as verified to byte −60 at ±0.46 dB. Two
clusters is not a refit and this is logged as an observation, not a correction —
but it is consistent, and it says the removal of one trim copy is slightly
smaller than the law's figure for that byte.

### Swing tracks the trim 1:1, not 2:1

Post-fix velocity swings are **29.22 and 29.25** for the two −39 presets and
**32.05–32.10** for the four −43 presets: **swing ≈ the trim byte's own dB value
to within about a dB**, across six presets. If the trim is constructed as
−swing/2 to move the velocity pivot, that relation should be 2:1 and it is 1:1.
Either the construction is −swing, or the measured swing is not the quantity
being halved. A file-side question, recorded here because the correlation is
tight enough to be structural rather than coincidental.

### The floor problem, quantified

Pre-fix v1 SNR on the trimmed presets was **1.0–4.3 dB** — in the noise. Post-fix
it is **24.5–36.2 dB**. So the pre-fix swings were floors and the post-fix ones
are measurements, and most of the apparent swing increase is the floor lifting
rather than the ramp changing. This is the §97 addendum's prediction confirmed:
the trim and the hard-left pan together pushed the quiet end of every ramp into
the noise, and removing one of them recovers it.

### Cross-session control, second bank

    KR row, this morning vs tonight, L-only, n=60
    mean -0.107 dB   sd 0.234   max |diff| 0.69   cells over 1 dB: 0

Wider than the S3000 row's 0.12 dB, as expected for a row sitting 6 dB closer to
the floor. **Across both banks: 90 cells, nothing over 1 dB**, spanning a card
removal, two re-seats and 4.5 hours.

## §98 — Amp Pan is cord destination 65, and the control is what proved it (2026-09-06, live)

`CORD_DESTINATIONS` in `eos/params.py` carries `65: "AmpPan"`, transcribed from
E-mu's SysEx spec, between `64: AmpVol` and `66: AmpXfd`. **Transcription is not
measurement** (§94, §97), and a sibling project needed the id to decide whether
the E4XT can carry a dynamic panner at all. Measured:

    static source, DC (160), with AmpVol as a positive control
      baseline                    L -32.46  R -32.04   R-L  +0.42
      CONTROL DC -> AmpVol +100   L -19.11  R -18.70   R-L  +0.42   level +13.35
      CONTROL DC -> AmpVol -100   L -85.65  R -86.40   R-L  -0.75   level -53.2
      TEST    DC -> id 65  +100   L -85.30  R -24.81   R-L +60.49   hard right
      TEST    DC -> id 65  -100   L -24.85  R -86.48   R-L -61.63   hard left

**122 dB of balance swing with level roughly preserved**, against a control that
moves level by 66 dB and leaves balance at +0.42 dB throughout. The two
destinations do the two different things they should.

    time-varying source, Lfo1~ (96) -> 65, amount 100, one 4 s note
      R-L in 50 ms steps: -56.7 -31.0 +3.8 +57.5 +50.7 +1.5 -38.2 -56.7 ...
      range -56.7..+57.5 dB, 22 sign changes -> ~3.06 Hz

**Dynamic panning works.** (The swing narrows from ±57 to ±22 dB across the
note: the amplitude envelope decaying so the quiet half of each cycle nears the
floor, not the LFO decaying.) RAM only; cord 17 restored to `{0,0,0}` and
verified by readback.

### The result is real because of the control, and only because of it

**The first two runs both failed, both from addressing errors, and both read
back perfectly.**

1. **`PRESET_SELECT` (223) chooses the preset for EDITING and does not change
   what the MIDI channel plays.** Preset 3 was being edited while preset 0
   sounded. The spec says this in as many words; it still took a dead control to
   notice. Fixed by sending the Program Change alongside the editor selection.
2. **Voice 0 is not the voice that sounds at that key — voice 2 is.** Found by
   putting the control cord on each voice in turn and watching which one moved:
   voice 2 at −53.33 dB, every other voice within ±0.17. Voices 5–7 refuse the
   write, which is also how the preset's voice count was learned.

**Every parameter read back exactly as written in all three runs.** Readback
confirms a value was stored; it says nothing about whether the thing storing it
is the thing being heard. **Without the positive control the report would have
been "destination 65 does nothing" — the inverse of the truth, and it would have
killed a feature on another project's roadmap.**

The rule this earns: **an RE probe for "does X do anything" must include a
control that is already known to do something, driven through the same path.**
A null result from an unproven path is not evidence about X; it is evidence
about the path. Two of the three runs here produced exactly that null.

### §98 addendum — the envelope frame rate is a measurement choice, not a detail

The pan probe above sampled stereo balance in **50 ms frames** and resolved a
~3 Hz LFO cleanly — 22 sign changes over 3.6 s, a smooth sweep. That worked
because 3 Hz is well inside the frame rate's reach, and for no other reason.

**50 ms frames sample at 20 Hz, so the Nyquist limit is 10 Hz.** A sibling
project measuring MPC material found a pan LFO at **11.47 Hz**, which is *above*
that limit: sampled at 20 Hz it aliases to ~8.5 Hz, and depending on the phase
relationship it can also read as a slow wander or as **almost no swing at all**.
Their capture used 10 ms frames (100 Hz, Nyquist 50 Hz) and measured 3.65 dB of
swing where a 50 ms grid could plausibly have reported a null.

**A null from an under-sampled envelope looks exactly like a null from a
destination that does nothing** — which is the same failure §98 already records
for an unproven signal path, arriving by a different route. Two of the three
things that can produce "no modulation here" are properties of the measurement.

**The rule: choose the envelope frame from the modulation rate you are looking
for, and state the rate you can resolve.** For anything faster than a few Hz,
10 ms. The pan result above stands because 3 Hz against a 10 Hz limit has margin
to spare, not because 50 ms is a reasonable default — it is not one.

## §99 — A 20 ms lead-in trim clipped a slap transient, and it looked like session drift (2026-09-06)

The third cross-session control looked worse than the first two: 29 of 30 cells
agreeing to **0.07 dB**, and one cell — a slap-bass preset at one key and one
velocity — differing by **2.50 dB**. Anchors matched to 5 ms, SNR was ~41 dB in
both, every other velocity at that key matched to 0.08 dB.

**A repeat-trigger test killed the obvious explanation.** Ten identical notes in
one capture gave a full-window level constant to **0.01 dB**, so the machine is
not varying per note — no round-robin, no random crossfade. The instrument was
reproducible; the measurement was not.

**The cause is the `full` window's 0.02 s lead-in trim.**

    the v127 note, same preset/key/velocity, two sessions
                    0-0.02 s          0.02-1.15 s        0-1.20 s
      morning    rms -84.80 pk    8   -44.69 pk 2413    -44.95
      tonight    rms -31.78 pk 2412   -47.19 pk  820    -45.37

**In one capture the attack transient sits inside the first 20 ms; in the other
it sits just after.** A 5 ms difference in anchor moved a slap-bass transient
across the window's opening edge. The transient carries most of the note's
energy — peak 2413 against 820 for the body — so excluding it costs 1.8 dB.

Removing the lead-in trim across the whole set:

    window            n    mean     sd     max |diff|   cells over 1 dB
    0.02-1.15 s      30   -0.077   0.450      2.50            1
    0.00-1.15 s      30   -0.012   0.076      0.42            0

**The cross-session bound then holds on all three banks with nothing over 1 dB**,
and this row tightens from 2.50 dB to 0.42.

### The same class as §95, at the other end of the note

§95 recorded a window edge falling inside a percussive sound's **decay**, where
±50 ms of anchor jitter manufactured 31 dB. This is a window edge at the
**onset**, where 5 ms of anchor difference costs 1.8 dB. The lead-in trim exists
to skip the note-on edge; on percussive material the first 20 ms *is* the sound.

**A window is an assumption about where the energy is, at both ends.** Neither
edge is safe by default, and the trim that protects one signal type damages
another.

### What it does and does not change

The trim result for this row is unaffected in substance: **+12.06 dB with the
lead trim, +12.00 dB without**, against 12.34 predicted. What the trim inflates
is the *scatter* — per-cell sd 0.47 against 0.12, and one cell reading +14.57
where the corrected figure is +12.50. **A comparison between two arms measured
the same way survives it; a bound on reproducibility does not.**

## §100 — The context-dependent byte, read uniformly (2026-09-06)

Three independent instances turned up in one day, across two projects, in three
different file formats. All three are the same bug:

**A byte whose meaning depends on context, read as though it always means the
same thing.**

1. **`vpar[54]`, the E4B voice-level volume (§92).** The field is real, but the
   velocity-pivot trim written into it is *only* correct where a zone-level copy
   also exists to be cancelled. Written unconditionally, it left every affected
   preset ~29 dB low. The conditional fix restores it.
2. **A zone byte's high nibble in the KRZ reader** (sibling project's
   §KRZPANNIBBLE). It carries a PANNER wire's pan, not the zone's, and only in
   four of the algorithms; read uniformly it made **all 58 zones of a bank parse
   as pan −1.0**, and the converted bank played hard left — which is what
   silenced one capture channel for half of today (§97).
3. **A segment byte in the K2000 F3 block** (sibling project) that is a block
   *type*, and therefore changes what every following byte means.

### Why all three survived review

**The uniform read produced plausible values, not obvious nonsense.** Pan −1.0
is a legal pan. A volume trim is a legal trim. A block parses. Nothing threw,
nothing was out of range, and no assertion could have fired — the output was
well-formed and wrong, which is the same property that made §94's uncorrected
file and §97's dead channel survive.

**And two of the three were only caught from the far end of a long chain**: the
pan bug surfaced as a dead capture channel that looked like broken hardware, and
the volume bug as a 37 dB level discrepancy chased for hours. Neither was found
by reading the writer.

### The tell that would have caught the second one, and generalises

**A field that is uniform across an entire corpus is suspicious in proportion to
how expressive it is meant to be.** All 58 zones reading exactly −1.0 is not what
real material looks like — the sibling's own corpus notes record 68% of layers
carrying varied non-zero pans. **A parser that returns a constant for a field
that should vary has usually found a different field.**

That check costs one histogram per field and needs no hardware. It would not
have caught the first instance, where the value legitimately varies; for that
one the tell was structural — the same value appearing at both a voice-level and
a zone-level offset, which §92 found by elimination.

### The layout fact that came out of the third check

Diffing a pre-pan against a post-pan build of the same bank located the E4B zone
**pan** fields at **+2 bytes from the zone volume fields** — volumes at
362/388/414/440 and 760/786/812/838 in that preset, pan at each +2, all eight
moving `(96,127) → (0,0)`, i.e. −32 (full left) → 0 (centre), with the voice-level
trim fields at 70 and 468 unchanged on both sides.

**Derived from a diff, not from a spec**, and it establishes where the bytes are
rather than their full range — worth stating that way wherever it is recorded.

## §101 — A null is a finding only after every rival explanation is excluded (2026-09-07)

The last cell of the E4XT column came back stationary: a pan-modulation program
reading **R−L = +0.42 dB at every key and both mod-wheel positions**, swing
0.01–0.04 dB. +0.42 dB is the rig's own constant interface trim, which every
unmodulated program on this chain reads.

**That zero is a finding, and three hours earlier the identical table would have
meant nothing.** Four explanations produce the same number, and each had to be
excluded separately:

    the chain sums, so no pan could ever appear
        excluded by a control: the same bank pre-fix reads -59.48 dB and
        post-fix +0.41 dB on the same rig twenty minutes apart
    the envelope under-sampled the modulation
        excluded by 10 ms frames -- 100 Hz sampling, Nyquist 50 Hz, against a
        source LFO at 11.46 Hz that a 50 ms grid aliases to ~8.5 Hz or to zero
    the balance was measured in silence
        excluded by a level gate keeping only frames within 20 dB of the peak
    the pan path does not work on this target at all
        excluded by three programs on another bank panning correctly the same night

**Only after all four does a flat trace mean "this program does not pan."**

### And the cause came from a parameter read, not the capture

Reading the cords before designing the capture — the habit that paid off on a
zero-depth cord earlier the same night — gave the reason rather than the
symptom. The voice carries eight cords and **none of them targets AmpPan**;
its LFO is routed to *Pitch*. So this is not a depth-zero case and not a routing
failure: **the cord was never written.**

That is a third distinct way for a modulation to be absent, alongside the two a
sibling project's framing offered (modulation not arriving; block not reaching
the outputs) and the zero-depth case found earlier. **Four now, and only one of
them is visible from audio alone.**

### The habit

**Before reporting a null, list the ways the measurement could produce one
without the subject being null, and close each.** Here that was four, three of
which were closed by work done for other reasons — the control, the frame rate,
the level gate. Had the row been captured first and reasoned about afterwards,
the same numbers would have supported "the E4XT cannot pan", which is false and
was disproved on the same evening.

**A null costs more to establish than a positive result, and is worth less if
the cost is not paid.**

### §95 addendum 3 — the fixed-pitch flag proved causally, and a signature that has a twin

The Non-Transpose regression (§95 addendum) survives a rebuild of the affected
bank: the two builds' spectra are identical to the decimal — 262.6, 525.5,
788.1, 1051.0 Hz at every key across four octaves. Then, on the machine:

    voice 0: E4_VOICE_NON_TRANSPOSE (id 57) = 1, keys 0-127
    voices 1-3: = 0, keys 0-62

    as found        k36  262.6   k60  262.6   k84  262.6      fixed
    set 57 = 0      k36   65.2   k60  262.6   k84 1050.3      tracks to 0.4%
    restored to {0:1, 1:0, 2:0, 3:0}, verified by readback

**One parameter on one voice, flipped and restored, turns the whole program from
fixed-pitch to tracking.** That is the cause demonstrated rather than inferred,
and it also confirms id 57 on hardware — until now a transcription from the spec,
which §98 is the standing reminder not to trust.

**Only that one preset is affected.** Measured fundamental per key, where a
perfect tracker over k36–k84 gives a ratio of 16:

    P010    262.6  262.6  262.6  262.6  262.6    ratio  1.00   FIXED
    P007    130.7  261.8  524.4 1050.7 2102.8    ratio 16.08   tracks
    P004     49.1   65.6  130.7  261.5  522.9    ratio 10.66   tracks
    P008     65.2   65.6  130.7  262.2  523.7    ratio  8.03   tracks

Sub-16 ratios are the harmonic-product estimator locking to different harmonics
at different keys, not pitch faults — every one rises with the key.

### The signature has a twin, and only the level check separates them

One preset reads **93.8 Hz at every key, ratio 1.00 — the identical signature to
the genuine fault — at −86 dBFS.** That is the estimator's noise-floor constant
(§95 addendum 2), not a fixed-pitch program.

**So "constant frequency across keys" is necessary and not sufficient for
fixed-pitch; it needs the level beside it.** Exactly the shape of §100's
never-fails-cleanly reads, and of the sibling project's listing rule that needed
name-byte validation rather than listing comparison. **A diagnostic signature is
only as good as the null it can be told apart from**, and here the null produces
the signature exactly.

## §102 — A units boundary nobody wrote down, and an agreeable number echoed back (2026-09-07)

Three cord amounts read off the machine disagreed with a sibling project's
predictions by roughly a quarter, in the same direction:

    predicted   measured
        92          72
       -12          -9
        67          53

Reported raw, with the pattern stated ("static exact, wheel-gated ~0.77 of
prediction") and **explicitly without a theory**. The explanation turned out to be
a units boundary: **the E4B file stores cord amounts as ±127; the editor SysEx
parameter interface expresses them as ±100.**

    file  92 * 100/127 =  72.44 -> 72   MATCH
    file -12 * 100/127 =  -9.45 ->  -9   MATCH
    file  67 * 100/127 =  52.76 ->  53   MATCH

Exact on all three. The apparent spread between 0.75 and 0.79 was integer
rounding at small magnitudes — **a constant ratio disguised as scatter by the
rounding of small numbers**, which is worth remembering as its own trap.

**Consequence for any cross-project comparison:** a reader validating file bytes
against machine readings without the conversion is wrong by 27% on *every* cord,
uniformly — which looks like a systematic calibration error rather than a unit
mistake. Both oracle files now state the unit explicitly rather than implying it,
alongside the sign convention (preserved, meaning unmeasured) and the voice-index
caveat.

### The part that is mine

The peer had misquoted one of my measurements back to me — reporting that I read
92 where I had read 72 — and built the "prediction meets measurement" anchor on
it. **I repeated that 92 back to them as confirmation.** My own capture had
printed `AMOUNT 72` twenty minutes earlier, in my own output, in this session.

**I took an agreeable number from a peer and passed it on without checking it
against my own record** — and it was the number carrying the argument. That is
the same failure as §92's non-discriminating model fit and §93's borrowed
control, in its cheapest possible form: not a subtle inference, just failing to
re-read what I had already measured.

**The rule: a number that comes back from a peer with your name on it is still a
number to check.** Corroboration that arrives already agreeing is the kind most
worth verifying, and verifying it here cost one grep of my own log.

### What went right

The pattern was reported before it was explained, as a pattern with no theory
attached. Had it been reconciled — "close enough, probably rounding" — the units
boundary would have stayed undiscovered and every future file-to-machine
comparison would have carried a silent 27% error. **Reporting an unexplained
regularity raw is what made it explainable by someone with the other half.**

## §103 — The LFO rate map reproduces the panel, and the panel is not the rate (2026-09-07)

A converted program whose source LFO runs at 11.46 Hz was measured panning at
**8.85 Hz** — clean, identical at both mod-wheel positions, 285 frames at 10 ms
giving 0.35 Hz resolution. Its rate byte is **95**, and `cnv_lfo_rate(95)` returns
**~11.47 Hz**, which is why the writer chose that byte.

**The byte is correct according to the map. The map is wrong about the machine.**

Sweeping the rate byte in RAM and measuring the resulting modulation directly:

    byte    cnv_lfo_rate   measured    ratio
      40        1.25         1.98      0.63
      60        3.46         3.74      0.93
      75        6.33         5.49      1.15
      85        8.78         7.02      1.25
      95       11.47         8.85      1.30
     105       14.11        11.14      1.27
     115       16.34        14.04      1.16

**Not a constant offset — the shape is wrong**, crossing unity near byte 62 and
reaching 1.30 at 95. The measured points fit
`exp(-0.000074821·b² + 0.0373635·b − 0.679590)` to within 2.6%, and above byte 85
they are a *pure* exponential, `exp(0.023096·b − 0.0142)`, residuals ±0.004 Hz.
**For 11.46 Hz the byte is 105, not 95.**

### Why this was invisible for months

§6a records that `cnv_lfo_rate` came from a sibling project's empirical
calibration **off the E4XT's own rate menu**. It reproduces the panel display by
construction, and it was validated the same way. **Nobody had measured the rate
the machine actually modulates at** — the calibration and its check were the same
measurement, so agreement was guaranteed and meant nothing.

That is the §92 pattern in a different dress: a model that fits, where the thing
it was fitted to is not the thing anyone cares about.

**What remains ambiguous, and the check that settles it:** either the panel
display is not the modulation rate, or the menu calibration was misread. **Both
produce this table.** Distinguishing them needs a panel reading at a known byte,
which has not been done — recorded here as ambiguous rather than attributed.

### Scope

The map is used for every LFO rate the converter chooses, on every target and
every destination — pitch and filter LFOs as much as pan. **A pan LFO is simply
the first one whose rate was ever measured**, because the AmpPan work of §98–§102
made the modulation directly visible in the stereo image. The others were
converted through the same map and have never been checked.

### Not adopted

Seven points, one preset, one voice, one key. The rate should not depend on any
of those and that has not been shown; the balance frequency is assumed equal to
the LFO frequency, which the clean exponential supports and does not prove.
**`params.py` is unchanged** — this is a calibration to check, not to adopt, and
replacing one unverified constant with another would be the same mistake at a
different value.

### §103 addendum — the panel is honest, and the ambiguity is resolved against us

§103 left it open whether the display was not the modulation rate, or the
calibration off that display was wrong. **Both produced the table; the panel
reading separates them.** Read off the LFO 1 page against the audio:

    byte    panel   measured   cnv_lfo_rate   map error
      40     1.98     1.98         1.25        -36.9%
      60     3.74     3.74         3.46         -7.5%
      95     8.85     8.85        11.47        +29.6%
     105    11.14    11.14        14.11        +26.7%
     115    14.04    14.04        16.34        +16.4%

**The panel equals the measurement to two decimal places at every byte**,
including byte 40 where the error runs the other way — deliberately chosen as the
hardest discriminator. So the display is truthful and **the defect is entirely
this project's fit.**

The residual pattern says why: agreement is best next to the 2026-06-10 anchors
(bytes 0, 64, 127) and worst in the middle of the gaps. **A log-quadratic through
three points is exact at those three by construction and unconstrained between
them** — the shape was never tested where it was used, and the constant's own
comment said it was "refineable with intermediate readouts". None were ever
taken.

### Two caveats discharged by measurement rather than by argument

§103 listed three. The panel agreeing with the audio to three significant figures
**proves the balance frequency equals the LFO frequency 1:1**, which had been an
assumption; and it holds across five bytes, not one, which largely answers the
"seven points from one sweep" worry. **The surviving caveat is one preset, one
voice.**

### The right repair is a table, not a better curve

§6a's original problem was that the spec's display table was untranscribable —
129 entries recovered where 128 were expected — and a fitted curve was adopted
instead. **The panel is a readable oracle at every byte, and the audio
measurement is now proven equal to it**, so the true table can be recovered
empirically rather than approximated. Fitting a better curve to a lookup table
would repeat the original error at higher precision.

`params.py` is deliberately unchanged. Five dual-verified points prove the fit
wrong; they do not license a replacement.

**Incidental, from the same screen:** the Cords page displays amounts as
**percent** (`+49%`, `+6%`), which is §102's ±100 interface unit stated by the
machine itself — a units boundary that was visible on the front panel the whole
time.

### §103 addendum 2 — the table confirmed in the shipping path, and the last caveat discharged

Two GRATER builds were placed on one disc, differing by **one byte**: the rate
chosen by the old fitted map and the rate chosen from the measured table.

    build A   byte  95   table  8.85   measured  8.85 Hz   (CC1 = 0 and 127)
    build B   byte 106   table 11.44   measured 11.44 Hz   (CC1 = 0 and 127)

Exact at both mod-wheel positions, 750 frames each, 0.27 Hz resolution. **The
pan swing is unchanged across the pair** — 27.05 → 26.74 dB at CC1 = 0, 66.19 →
65.21 at 127 — so only the rate moved, which makes the comparison one-variable in
fact rather than by assertion. One disc, no cross-card drift.

**This is the first rate this project ever chose that has been verified as the
rate the machine produces.**

The source asked for 11.50 Hz and got 11.44, because the grid cannot express
11.50. That reads as an honest quantisation **only because the writer now reports
the rate it achieved**; under the old behaviour the same 0.06 Hz would have sat
invisibly on top of a 2.6 Hz error.

### The caveat that stood since the sweep is discharged

The table was recovered from one preset, one voice. Four spot bytes on a
different bank, a different preset, a different voice, and a **different LFO
shape** (triangle against the sweep's sine):

    byte  30   table  1.37   panel  1.37     byte 100   table 10.07   panel 10.07
    byte  70   table  4.88   panel  4.88     byte 120   table 15.56   panel 15.56

plus byte 64 read incidentally at 4.12 — the June anchor. **The mapping is a
global property of the LFO**, not per-voice and not shape-dependent. Four points
rather than a second sweep, on the reasoning that if it were per-voice, four
would show it as clearly as 128.

### The reader's refusal fired in the wild, first time out

The initial spot-check run returned `??.??????..?.???.???.??` and reported
MISMATCH on all four bytes. The page remembers its cursor field, and an earlier
mis-navigation had left the cursor on **Delay** — so the reader read that field,
met glyphs it had no template for, and **reported `?` rather than inventing
digits.**

That is exactly the property it was built for, and the failure it prevented is a
specific one: returning four plausible numbers from the wrong field, which would
have disagreed with the table and read as *the caveat failing* rather than as a
navigation fault. **A guess would have been indistinguishable from a finding.**

## §104 — A quiet outlier with no parameter to blame, and two wrong banks (2026-09-07)

A converted program read **−61 dB against peers at −33** on the E4XT, reproduced
to 0.3 dB, with its source material measured **+3.2 dB above the bank median** in
the built file and **+4.6 dB** in the original WAVs. Three sessions spent a day
looking for the attenuator. **There is no attenuator.**

    prog   hold   peak      ramp at 1 / 2 / 4 / 6 / 8 s
      0     2.0  -60.85    -79.4  -65.6    -      -      -
      0     8.0  -37.47    -79.2  -64.4  -53.0  -41.6  -45.6
      3     2.0  -35.50    -57.7  -70.3    -      -      -     <- control
      3     8.0  -35.44    -58.2  -60.2  -60.8  -61.4  -69.5

**The program has a 5.46 s envelope attack and the harness holds notes for
2.0 s.** It was scored a fifth of the way up its own ramp. Lengthening the hold
to 8 s raises it **+23.4 dB** from one constant; the control — a peer with a
0.000 s attack — moves **0.06 dB** across the same change, which is what rules
out the longer window inflating the peak and leaves no alternative standing.

**The mechanism accounts for ~23 of the 25 dB gap, not all of it.** The residual
2 dB is unestablished; the ramp reading −41.6 at 6 s and −45.6 at 8 s means the
true peak lands between samples, which would plausibly cover it, but that is a
hypothesis and is recorded as one.

**Why it was so expensive: a truncated attack has no parameter signature.** Every
volume, trim, cord, filter and envelope field reads normal, because every one of
them *is* normal. The measurement's precondition — that the note had time to
sound — is not a field anyone thinks to check. **Before explaining a quiet
outlier with a parameter, check the note had time to sound.**

Campaign-wide the exposure is one preset in 37 across six banks: one at 273% of
the hold and a hard floor of exactly 0.000 s everywhere else. **No population
near the boundary**, so the threshold question that seemed important is moot
here — but the shape recurs wherever a probe is shorter than the thing probed.

### Run-to-run reproducibility, measured for the first time

A mis-tagged capture turned into the figure no rig here had. Two independent runs
of the same bank, ~45 minutes apart:

    44 cells   mean -0.002 dB   sd 0.010   max |diff| 0.05 dB   cells over 0.5 dB: 0

**Hundredths of a dB.** Every confidence number produced here had assumed
run-to-run variance was small; it is now bounded rather than assumed. And it
settles more than it was asked: **a 38 dB discrepancy cannot be capture noise on
this bench**, so the "one flaky capture" hypothesis that consumed part of the day
was never plausible. **Had this figure existed at the time it would have redirected
the search to a wrong subject faster than the subject check did.**

### Two wrong banks, and the lesson that is not "add a check"

Bank index 2 addressed one bank on one disc and a different bank on its
successor. It was loaded by index twice, and both times a confirmation
screenshot was captured — **deliberately, as the guard** — and **not read**.

The first error produced a confident retraction of a correct measurement; the
second was catching the first. A peer amended their notes on the strength of it.

**The check existed and was performed. It was not read, because the answer was
already known.** No further safeguard addresses that: the safeguard was present
and the failure was in consuming it. What the day actually shows is narrower and
harder — **verification lapses exactly when the work gets interesting**, which is
when its result is most likely to be acted on.

### The question that would have caught it

The disagreement pattern was three independent contradictions at once. Both
sessions read that as strong evidence of a real divergence. The useful question
was not *"is this disagreement too strong to be real?"* — a judgement about
plausibility, which can be got wrong twice — but **"were these two sides measured
from the same object?"**, which has an answer. It would also have been cheaper
than either check that eventually found it.

## §105 — The envelope attack ladder, and a quantity with two meanings (2026-09-07)

The E4XT displays envelope rates as **bytes**, not times — unlike the LFO rate,
whose panel readout gave §103's table directly. So the byte → time law had to be
measured from audio. Eight points, `E4_VOICE_VENV_SEG0_RATE` (id 70), one preset
with steady material, per-point hold and window:

    byte   t_peak    10-90%
      20     0.18      0.10
      36     0.48      0.32
      48     1.02      0.84
      72     3.60      2.50
      79     5.70      3.60
      87     8.85      5.25
      96    15.10      8.80
     102    21.30     12.60

Data in `docs/data/e4xt_attack_rate_ladder.json`. **Higher byte is slower and
strongly non-linear** — 72→79 costs 2 s, 96→102 costs 6.

**Cross-checked against a program rather than only itself:** a preset whose panel
showed Atk1 rate 89 measured t_peak ~10.1 s, and byte 89 on a *different preset
with different material* gave 9.10 s. The timing follows the byte across
programs, which a material artefact could not.

### "Attack time" means two things and they differ by 1.6x

    t_peak    time from note-on to the envelope's peak -- the full 0 -> 100 traversal
    10-90%    the conventional rise, 0.619 +- 0.041 of t_peak on this machine

A sibling project's converter emitted bytes intended to produce given attack
times. Against **t_peak** its bytes ran **1.838x long, sd 0.050 across two
decades**; against **10-90%** only **1.14x**. **The ladder cannot choose between
those** — it is a question about what the source's field denotes, not about the
machine, and it was settled from the source side (the source law's own measured
10-90%/full ratio is 0.704, not 1.0, so it denotes the full traversal).

**Recording that as a finding rather than a footnote**: a measurement can be
complete, precise and still not answer the question, when the question turns on a
definition. The right move was to report both numbers and name the ambiguity, not
to pick the one that made a cleaner story.

### Two limits stated rather than smoothed away

**The law is not to be read below ~2 s without a re-take.** The three sub-second
points drift — `10-90%/intended` runs 1.00, 1.28, 1.68 there against 1.05–1.25
above — because at byte 48 a 30 ms window is ~3.5% of the rise and quantisation
becomes a real fraction of the result. Excluding them tightens every statistic,
which is the evidence that they are the weak ones, not a reason to hide them.

**The machine's own shape ratio is 0.619, not the 0.704 that had been borrowed
from a different machine.** That borrowed constant was doing real work in
someone's arithmetic, and different machines have different ramp shapes.

### The generalisable part

**The analysis window must scale with the value being measured.** A fixed window
cannot measure a ladder spanning 0.1 s to 12 s: too coarse at the bottom, and at
the top a fixed *hold* truncates the answer — which is §104's error appearing for
the third time in a day, at a third scale. Window ≈ 5% of the expected value,
hold ≈ 6x, both derived per point rather than chosen once.

### §105 addendum — a corrected bank on hardware, and a prediction that was not one

A sibling project used §105's ladder in the inverse direction, to choose the byte
that should produce a wanted attack time, and the rebuilt bank was played here.

**CORRECTED 2026-09-07 after review.** This addendum first claimed the ladder
"predicted a hardware result" that "neither half could have predicted alone."
**That was wrong and it flattered both projects.** The byte was chosen *from*
this ladder, so the ladder agreeing with the outcome is a consistency check on
one law, not a composition of two independent halves. What is corrected below is
the claim, not the measurements.

**The readback, and what it does and does not establish.** The rebuilt bank's
Atk1 rate read **91** off the machine. That confirms the byte the writer intended
reached the media and the instrument — a real check, and it can fail without any
audio. **It does not independently confirm the `seconds → byte` law**, because
the expected 91 came from the sibling's own arithmetic over this ladder. It
verifies implementation against intent, not intent against the machine.

Both builds, analysed identically:

    window       previous build (byte 89)     rebuilt (byte 91)
                 t_peak    10-90%             t_peak    10-90%
      50 ms      10.05      7.25              11.95      7.05
     250 ms      10.10      5.75              11.85      7.25
     500 ms      10.10      6.00              11.60      7.50
    1000 ms      10.10      6.00              11.10      7.00

**t_peak moves 10.1 s → 11.1–11.95 s depending on window.**

**The interpolation rule was never stated and it changes the answer.** Byte 91
sits in the ladder's widest gap, between measured 87 (8.85 s) and 96 (15.10 s):

    linear      11.63 s
    log-linear  11.22 s      <- the better model: ln(t) per byte is 0.0525-0.0656
                                across all seven intervals, 0.0594 on 87->96

The original text quoted 11.6 s — the linear figure — without saying so. **Both
interpolants fall inside the measured 11.10–11.95 s spread, so this capture
cannot discriminate between them**, and any agreement quoted at the few-percent
level is unsupported.

**What IS independent, and it is the result worth keeping.** The target of
**11.40 s** is the sibling's measurement of the *source* program's full rise,
taken on the MPC and owing nothing to this ladder. The machine played the
rebuilt bank at 11.1–11.95 s. **Source asks 11.40, hardware delivers within the
window spread of it, where the previous build sat at 10.1 s.** That is a genuine
end-to-end check of the corrected conversion; the ladder's own agreement with
itself is not.

### Two reporting decisions worth more than the result

**The figure is "within a few percent", not "+1.8%".** The point estimate against
the 11.40 s target is +1.8%, but t_peak spans 11.10–11.95 s across smoothing
windows, so 1.8% claims a precision the spread does not support. **A number
quoted tighter than its own window spread is a false precision**, and the tighter
version reads better, which is exactly why it needs refusing. (The target's
provenance is recorded above for the same reason: a percentage against an
unrecorded denominator cannot be checked by a later reader.)

**The 10-90% statistic collapsed, and that is a result rather than a footnote.**
It ranges 5.75–7.25 on one build and 7.00–7.50 on the other — overlapping, so it
**cannot separate them at all**, while t_peak separates them cleanly and is
stable to 0.05 s on the steadier build. Generalising: **on material that wobbles
near its peak, a crossing-based statistic degrades faster than an extremum-based
one**, because every crossing is referred to a peak that is itself moving. Pick
the statistic from the material, not from convention — 10-90% is the conventional
choice and it was the wrong one here.

## §106 — A window that assumed a plateau, and a probe that could be wrong (2026-09-11)

A cross-machine comparison needs the two machines measured over the *same part
of the note*. The obvious window — "past the attack, inside the hold" — was
agreed on both sides before anyone looked at an envelope. It was wrong, and the
replacement proposed for it was wrong in the opposite direction.

Six presets, five notes, five velocities, held 2.0 s, analysed over 0.35–1.35 s
after note-on. One preset (slot P001 on the bench) has **no steady state at
all**: it swells to its peak at 2.0 s and then decays continuously. Level across
that window, relative to the note's own peak:

    note   window start   window end   change
      24      -18.95         -12.96     +5.99
      38      -19.17         -11.25     +7.92
      52      -26.70          -7.23    +19.47
      65      -10.71          -8.30     +2.41
      79      -15.66         -10.12     +5.54

**A band vector averaged over that is a band vector of a ramp**, and a residual
between two machines each somewhere on its own ramp is dominated by where on the
ramp each landed — the exact artefact a residual exists to avoid.

The proposed fix, 3.5–4.5 s, was **worse**. Tilt across a 1.0 s window on the
worst cell, by start time:

    0.35-1.35   +16.27 dB     <- the original: on the rising ramp
    1.50-2.50    +1.70
    2.50-3.50    +0.93        <- flattest
    3.00-4.00    -5.85
    3.50-4.50   -11.76 dB     <- the proposal: on the decay, and steeper
    7.00-8.00    -1.50

**The flattest window is at the peak**, which is the opposite of where "past the
attack" looks by habit. Two wrong windows for one note, and the reason both were
wrong is a single unexamined assumption: that the material has a plateau. Nobody
checked before designing a measurement that needed one.

### The probe has to be able to come out wrong

The suspicion when the 2.0 s hold showed peaks at 1.90–2.00 s was
§ATTACKTRUNCATION — that the peak was not at 2.0 s but merely cut off there. The
check was **one cell at HOLD 10.0**, ten seconds of hardware:

    true peak      2.009 s          (the HOLD 2.0 reading was 2.003 s)
    10% -> 90%     0.269 -> 1.396 s
    decay          -32 dB by 8 s

So the peak was real and the 2.0 s figures were not truncated. But the value of
the probe was not the answer; it was the **hold it was taken at**. Probing at
6.0 s would have confirmed the peak at 2.0 s and said nothing whatever about
whether 6.0 s was itself a ceiling. **A bound tested at its own value always
confirms itself.** Go somewhere the answer can be wrong, or the check is
decoration.

### The window is chosen per preset, by a rule fixed before the data

No single absolute window is flat for all six: the others peak in 17–142 ms and
decay from there, so a window flat for one is steeply tilted for another. Tilt
matters because it **amplifies any small timing difference between the machines
into a large residual**.

    For each preset, over 1.0 s windows on a 0.25 s grid inside the hold, take
    the one minimising  max(mean |tilt| side A, mean |tilt| side B)  across that
    preset's cells; ties to the earlier window.

**Min-max, not min-mean** (mpc2emu): the artefact scales with whichever side is
steeper, so the quantity to bound is the worse one. Min-mean will trade one
side's flatness for the other's steepness and call it an improvement.

**Both sides, not one** (mpc2emu): tilt is an envelope property, not a filter
property, so reading the other machine's envelope to choose a window leaks
nothing about the thing under test — while choosing on one machine leaves the
other's tilt unbounded.

**The level guard is not optional.** Pure tilt-minimisation has no notion of
*why* a window is flat, and the failure is reachable: on the probe cell the
7.00–8.00 s window has only −1.50 dB of tilt, flatter than everything except
2.50–3.50, and it is flat **because it is 32 dB down and approaching noise**. A
candidate is rejected unless every cell on every side has window RMS at least
12 dB above that cell's own pre-roll floor — the same floor-relative test the
capture harness uses for silence, and for the same reason: a threshold
calibrated against a level is not a threshold. A preset that clears no window
returns **no window**, rather than one obtained by relaxing the guard.

Each side's own individually-best window is reported regardless. **If the two are
far apart for some preset that is an envelope finding in its own right** —
possibly a larger one than any filter corner — and the min-max must not absorb
it silently.

## §107 — What a 1/24-octave band residual can and cannot see (2026-09-11)

Two machines playing the same material at the same note and velocity: subtract
the band vectors and the material's own spectral structure cancels, along with
every definitional choice in the analysis, **provided the choice is applied
identically to both sides**. That is why one analyser is run by both projects
rather than two that agree on paper.

The band resolution was set at 1/24 octave because 1/6 octave is 231 Hz at 2 kHz
and the narrowest feature this board is known to make is 108 Hz — a narrow
feature present on one machine and absent on the other would be half-averaged
away on *both* sides and the difference would read small. That reasoning is
correct, and the limit it leaves can now be stated as a number rather than a
worry.

**Method**: white noise, a notch of known depth and width injected into one copy
only, both put through the band path, peak |band residual| read off. That is
exactly what the residual does to a feature present on one machine.

    a -30 dB feature of the given width, present on one side only
    width (oct)   bands    500 Hz   2 kHz   8 kHz
       0.028       0.67       3.6     5.8     5.0    invisible
       0.042       1.01      15.9    16.9    30.0    alignment-dependent
       0.056       1.34      29.9    30.0    30.0    true depth
       0.083       1.99      30.0    30.0    30.0
       0.250       6.00      30.0    30.0    30.0

**A feature must span about 1.35 of the 1/24-octave bands — 0.056 octave — to be
reported at its true depth. Below ~0.7 bands it is invisible. Between the two,
the answer depends on where the feature falls relative to a band edge**, which is
not a property of the instrument.

Since 0.056 octave is 0.039·f Hz wide, **a 108 Hz feature is faithful up to about
2.8 kHz** and under-reported above it. The failure is a *ceiling*, not a loss of
accuracy:

    108 Hz notch      -12dB   -20dB   -30dB   -50dB
      2000 Hz          12.0    20.0    30.0    50.0
      3200 Hz           7.5     8.8     9.1     9.1
      6400 Hz           2.6     2.8     2.8     2.8

At 6.4 kHz a −20 dB feature and a −50 dB feature both read 2.8 dB. **Reading a
small high-frequency residual as "the machines agree" is wrong in exactly the
direction that matters.** Wide features are unaffected everywhere: a 1/3-octave
feature reads true depth at 100, 400, 1600 and 6400 Hz, so a filter corner
*moving* is always reported faithfully; only genuinely narrow resonances and
notches hit the ceiling, and those need a high-Q setting.

### The residual and the prominence finder have different limits, and not by degree

A prominence measured against a 1-octave smoothed envelope has a second failure
the residual cannot have: a feature that is **wide compared with that envelope**
drags its own reference down and collapses. A −50 dB notch 108 Hz wide reads

      at 100 Hz (±54% of centre, over half an octave):     4.2 dB
      at 200 Hz (±27%):                                   14.3 dB
      at 800 Hz (±6.75%):                                 44.3 dB

So for a 108 Hz feature the prominence finder is trustworthy roughly 800 Hz –
2 kHz, while the residual is trustworthy from below 100 Hz to 2.8 kHz. **The
residual is not merely the more neutral instrument, it is the more capable one**,
because it never touches the envelope. That is a stronger argument for making it
primary than the one originally given for it.

**And a small systematic error is not noise because it is small.** A synthetic
−30 dB notch came back as 28.18 dB and was let through as agreement on a first
pass. The 1.8 dB shortfall is the same envelope effect — systematic, and small
only at that width. *Close enough* is the shape most of this week's errors wore.

## §108 — Guards scoped to the wrong resource, and a check that certifies (2026-09-11)

Three failures in one hour on a two-machine capture night, all the same shape:
**a guard scoped to one resource applied to a hazard that lives on another.**

**The capture harness refuses to start a second run on the same rig** — two runs
on one rig share a MIDI port and a capture pair, and that contamination is
undetectable afterwards, so it must be refused before the first note. Correct,
and it does not cover the JACK **client registration**, which is server-wide. Two
runs on *different* rigs passed the guard cleanly and wedged each other: both
hung in the JACK socket read, wrote nothing, printed nothing — and `jack_lsp`
from a third shell hung too, which is what showed the block was server-side
rather than a slow client. Killing one freed the server immediately.

**A bare `pkill -f 'measure.py'` crosses sessions**, because the process table is
shared and is exactly that kind of resource. It killed two passes belonging to
another session. And a bare pattern can match **the shell issuing it**: a
`pkill -f 'grid6\.sh'` matched its own command line, which contained the script
text being written, and killed the process doing the killing. Match on PIDs read
from `ps`, with an explicit self-exclusion.

**A lock scoped wider than its hazard costs what the hazard would have.** The fix
for the registration wedge was a shared `flock`, and holding it for a whole
six-program pass **serialised the two rigs completely** — 25 minutes of parallel
work became 50 minutes of sequential, one side blocked three minutes with nothing
captured. The hazard is over in the first second or two; everything after it is
per-rig. Correct scope:

    flock "$LOCK" -c "nohup python3 measure.py <rig> <tag> ... > log 2>&1 & sleep 8"
    until ! pgrep -f "measure.py <rig> <tag>" >/dev/null; do sleep 5; done

`& sleep 8` holds the lock only while the client registers, then drops it; the
run continues unlocked. **Both directions of mis-scoping came from not asking
what the resource actually is** — one too narrow for what it touched, one too
wide for what it protected.

### A completion check that cannot tell finished from killed does not fail — it certifies

The worst of the three was local and silent. A runner reported

    01:03:59 GRID_v048 attempt 1 finished

for a pass that had been SIGKILLed **with zero captures written**. Its completion
test was `kill -0` on the child, so *the process is gone* counted as *the work is
done*. It would have handed the comparison a 30-cell velocity row containing
nothing, labelled complete — and unlike the other two, nothing about it was loud.

**Test for an artefact the work produces last, not for a process state.** The
capture harness writes its features file only after the final program, so:

    whole() { [ -f "features_$1.json" ] || return 1
              [ "$(ls captures/$1_00*.wav 2>/dev/null | wc -l)" -eq 6 ]; }

Six captures **and** the features file. The absence of that file is a fact about
the work; the absence of a process is a fact about the process.

**Related: a level spread wide enough to clip one preset and not another.** Across
the same six presets at velocity 16 the peaks span 32.7 dB (−9.2 to −41.9 dBFS).
At velocity 127 the loudest can reach full scale, and **a clipped capture does not
look broken, it looks bright**, because clipping adds harmonics — which lands in a
cross-machine residual as a timbre difference. Check peak dBFS, samples at full
scale, and the **longest consecutive run** of them: one sample at −0.0 dB is a
coincidence, forty in a row is a flat top.

## §109 — Choosing an analysis window, and three rules that were wrong (2026-09-11)

A cross-machine band residual is computed over a 1 s window inside a held note.
Where that window sits is a methodological decision, and on this campaign
**every preset's window moved when the rule changed** — so the choice is not a
detail, it is a named decision with a date and a reason.

Three rules were proposed. The first two were defective and **the defects were
opposite**, which is the useful part.

**TILT — minimise the tilt of the smoothed LEVEL envelope across the window.**
Independent of the comparison statistic, so selection cannot bias the floor.
That independence is the property worth keeping. But **the residual is computed
on the SPECTRUM**, and during a filter sweep the level can be flat while the
spectral content moves as fast as the filter does. On a preset with
`filter_env_cents = -8936` over a 1.92 s decay, the tilt rule chose the window
whose repeat-pair spread is **0.971 dB when 0.075 was available 1.75 s later** —
a factor of thirteen, and close to the worst window on offer.

**REPEAT-PAIR — minimise the measured band difference between two captures of
the same stimulus.** Right quantity, and it breaks the independence: **that
difference IS the floor.** Minimising it over ~20 candidate windows takes the
minimum of twenty noisy floor estimates, which sits well below the true floor,
so every residual is judged against an optimistically small denominator and
significance is systematically overstated. The mirror of the known
one-pair-understates-spread trap, done on purpose. Rejected (mpc2emu).

**DRIFT — spectral movement WITHIN one pass.** Right quantity, independent:
a sweep in progress is visible as the spectrum moving inside a single capture,
so no second pass is touched.

    tilt          level, within pass     independent, WRONG quantity
    repeat-pair   spectrum, across       right quantity, BIASES the floor
    drift         spectrum, within       right quantity, independent

**Validated by scoring each rule's chosen window with a repeat pair the rule
never saw** — validation, not selection:

    preset   tilt window   drift window
     P000      0.971  ->     0.119     8x better, the case the diagnosis was about
     P001      0.050  ->     0.068     worse by 0.018
     P002      0.036  ->     0.013     better by 0.023
     P003      0.216  ->     0.230     worse by 0.014
     P004      0.060  ->     0.056     better by 0.004

**One large gain; everything else at or below the repeat noise.** The honest
claim is "drift fixes the case the diagnosis was about and is a wash elsewhere",
not "drift is better" — six presets with one carrying the whole difference is
the shape that has to be distrusted.

### The scores rank windows and estimate nothing

Drift scores came out at **1.5 to 17.5 dB**. One preset scores **13.62 dB of
within-window drift and repeats to 0.056 dB**, because **a deterministic sweep
drifts hugely and repeats perfectly.** Drift predicts poor repeatability only in
combination with timing jitter, and the rig's jitter is ±5 ms. So a drift score
must never appear in a column adjacent to a residual.

**And a high score at the CHOSEN window is a warning that was missed.** The rule
takes a minimum over candidates and has no disqualification threshold, so
`12.38 dB at the chosen window` means **this preset has no good window**, not
**this window is good**. One preset scored 12.38 against another's 1.54 in output
both sessions read as simply "the window". That is how the output is consumed
rather than a fault in the rule, and it generalises to every campaign that uses
it.

### A guard that is documented and does not exist

`measure.py --hold` help: *"Recorded in the features file so takes at different
holds can never be compared by accident."* The record held
`rig tag program label wav notes velocity` — **no hold.** Files captured at 2.0
and at 6.0 were indistinguishable, on the one constant the campaign had changed
that night. Same species as the `kill -0` completion check (§108) and worse: that
one merely failed, this one was documented as working.

**The fix has a subtlety that matters more than the fix (mpc2emu): a missing
value must be UNKNOWN, never defaulted.** A downstream `get('hold', 2.0)` would
read a 6.0 capture as 2.0 and **pass a guard it should fail** — converting a
*missing* guard into a *wrong* one, which is strictly worse, because the missing
one leaves a human checking by hand and one was. A default here is a fabricated
measurement. Absent on either side → refuse; state it explicitly → stamp it in
the output as ASSUMED so the assumption travels with the numbers.

## §110 — A +786 cent shift, a suppressed warning, and an absence measured in the wrong place (2026-09-11)

Two machines playing the same converted material were compared cell by cell.
Three of six presets turned out to be **playing at the wrong pitch** on the
target side — +831, +210 and +786 cents — so no cross-machine spectral
comparison on those presets means anything.

**The cause was diagnosed correctly by the converter and suppressed.** The writer
emits, once per sample:

    [WARN] '<sample>': stored at 28000 Hz, which the target cannot play.
           It will sound at 44100 Hz -- +786 cents. Resample first.

A build script called the writer directly, bypassing the sample-rate
conformance step, and wrapped the call in `contextlib.redirect_stdout` **to keep
the build output tidy**. Correct, specific, quantified, remedy named — and
unreachable. Two sessions then spent an hour recovering the same fact from the
audio of two machines.

**That is a distinct failure from the rest of this week's collection.** Every
other one was a guard that did not exist, did not fire, or fired on the wrong
thing. **This is the only one where the system diagnosed itself correctly and was
not allowed to say so.**

### Confirming it from the audio, and why a pitch estimator could not

`octave_err` from YIN disagreed across the two machines and was **not usable on
either**: the preset sounds two layers five semitones apart, and an estimator on
two simultaneous harmonic series locks to the lower, the upper, or a common
subharmonic depending on which dominates its window. One side read −1
everywhere, the other read 0, +1, 0, 0, −2 — both deterministic, neither
meaningful.

**The series themselves are meaningful.** Reading the zone map off the device —
same sample id in both voices, root keys 67 and 72, key ranges offset by five —
predicts a second fundamental at `f0 x 2^(-5/12)`, and it is there:

    voice 0  174.73 Hz      voice 1  130.83 Hz   (predicted 130.86, -0.4 cents)

and against the other machine, on both layers independently:

    upper  275.39 / 174.68  =  +788.1 cents
    lower  205.81 / 130.83  =  +784.4 cents
    predicted from the stored sample rate:  +786.4 cents

**Two series, two machines, two cents.** An envelope-modulation rate ratio
measured earlier at 1.580 is +791.9 cents — the same shift a third time, so a
"different modulation rate" finding and a "different pitch" finding were always
one thing.

### An absence is worth only as much as the statement of where you looked

Before the zone map was read, this note's author reported **"no second series a
fourth up — x2.5 against x2790, 61 dB down, absent rather than quieter"** and
built a conclusion on it (*"one layer against two"*). The search was a fourth
**above**, because the other machine's two series sit above each other. **The
second layer is a fourth below.** The quoted number was real and was about a
frequency where nothing was ever expected.

**Writing "no second series in 233.2 ± 3 %" instead of "no second series" would
have made the error visible inside the sentence that contained it.** A negative
result carries its search region or it carries nothing.

### Three tests that could not fail informatively

All three produced a confident number from data that could not carry it, and
none presented as an error — only as a value.

- **Aliased**: an envelope modulation near 1.1 Hz sampled at 0.5 s steps — 1 Hz
  Nyquist. Reported as a measurement.
- **Too short a record**: the same quantity estimated over a 4 s window at
  0.27 Hz — **1.1 cycles**. The resulting 91 % scatter was at least partly the
  estimator and could not be separated from the signal. Fixed by re-capturing at
  a 20 s hold; not by argument.
- **Hypersensitive discriminator**: a predicted beat rate in which **0.6 cents of
  tuning error moves the prediction by 41 %**. The rival hypotheses could not be
  separated by any measurement available, because the discriminator depends on a
  quantity below what can be independently established.

The third is the one worth naming as a class: **a test whose discriminating
power rests on a parameter you cannot measure more accurately than its
sensitivity is not a test**, and the right output is to say so rather than to
report the number it happens to produce.

## §111 — Five definitional mismatches in one day, all inside shared tooling (2026-09-11)

Two projects compared one instrument against another, cell by cell, using **one
analyser run by both sides** specifically so that implementation differences
could not land in the result. Five disagreements arrived anyway, and **not one of
them was arithmetic**. Every one was about *what the arithmetic was applied to*.

    hold unrecorded          the capture schedule was never written to the record,
                             while the help text said it was (see §109)
    attack_ms vs t_peak_ms   ONE function returns both; they differ by a second on
                             the preset under test, and the agreeing one was wrong
    offset origin            one side measured from the note onset at fixed times,
                             the other from each note's own envelope peak
    t90 vs t100              calibration points in one convention, the law in the
                             other, related by a documented 0.9 that nobody applied
    SEG0 vs the whole attack this project read one envelope segment for an envelope
                             that rises through two

**Sharing the code fixed the arithmetic and left every naming and reference
choice untouched, and that is where all five lived.** A shared implementation
guarantees two sides compute the same function; it guarantees nothing about which
output field each reads, what each anchors to, or which of two conventions each
number is in.

### What made them survivable

**Asking which field before comparing, not after.** The `attack_ms` / `t_peak_ms`
pair is the sharpest: two attack numbers out of one trusted function, a second
apart, and **the pair that agreed was the wrong pair**. Reading `attack_ms` on
both sides gives 2.42 s against 2.69 s and reports the conversion as fine.
Reading `t_peak_ms` gives 2.92 against 3.80 — a 30% discrepancy. It was caught
because the other side asked which field the number came from *before* comparing.

**The sign test, which is a better discriminator than any tolerance.** On
`t_peak` the per-note differences are the **same sign on all five notes** (+325
to +1181 ms). On `attack_ms` they change sign — one note runs 455 ms the other
way. **A statistic whose per-note differences flip sign is not measuring the
quantity whose per-note differences do not**, so the `attack_ms` medians
"agreeing" was a median landing between disagreeing signs. No tolerance would
have separated those; the sign pattern does it immediately.

**Per-note comparison rather than two medians.** An across-note spread is a
property of the preset and should reproduce on both machines. Here one side's
spread is 206 ms and the other's 941 ms — **4.6x, deterministic on both** — and
the rank orders disagree. A scalar law error preserves ordering and relative
spread; this does neither, so "the law is 30% out" was never the right
description.

## §112 — An envelope with two attack segments, and a ladder that measured one

`E4_VOICE_VENV_SEG0_RATE` (Atk1) is not the attack when **Atk1 LEVEL is below
100%**: the envelope keeps rising through SEG1 (Atk2) and the peak is at the end
of *that*. Read off the device, one preset in this set:

    Atk1 rate  39   Atk1 LEVEL  43 %     <- the rise stops at 43%
    Atk2 rate  78   Atk2 LEVEL 100 %     <- and continues to full

§105's ladder is SEG0 only, so byte 39 log-interpolates to **0.580 s** against a
**2.92 s** measured `t_peak` — a factor of five, and it very nearly went out as
"the ladder is wrong". **One parameter was read for an envelope that has six.**
The same shape as measuring an absence a fourth above a fundamental whose second
series is a fourth below (§110).

Composed correctly the disagreement vanishes:

    Atk1 covers  0 ->  43 %:  0.580 x 0.43 = 0.249 s
    Atk2 covers 43 -> 100 %:  5.338 x 0.57 = 3.043 s
    total to full level                    = 3.29 s   (measured 2.92, -11%)

and the −11% residual is the sample's own decay pulling the product's peak
**earlier**, which is the predicted direction for decaying material.

**The sibling project's reader had the same fault with a different signature**:
it applied the rate slowdown to segment 1 only and span-scaled neither segment.
The two errors partly cancel, and **cancel exactly at a knee of 45.6%**. This
preset's knee is 43% — 2.6 points from an accidental fixed point, which is the
only reason its number looked right. Across 666 voices in 21 banks, **every
attacked voice is two-segment (130 of 130, zero single-segment), and 48% read
more than 25% wrong** — 0.54x at a 10% knee, 1.61x at 68%.

The justifying comment was *"ATTACK IS DELIBERATELY NOT SPAN-SCALED: it climbs
the full range by definition."* **True of the attack as a whole and false of each
segment** — a correct statement about the wrong unit of analysis, which is the
same family as the four in §111.

### A measurement whose subject is not named is not reproducible

§105's `method` says "one preset with steady material" and **names no preset and
no sample**. That was adequate for a standalone result and is not adequate now
that the ladder is a cross-machine reference: it cannot be re-taken or extended
on its own material.

**Steady material can be established by measurement rather than assertion.**
Flatten the amp envelope to a rectangle — every segment instant, every target
100% — and whatever the level does across the hold is the sample:

    preset   drift over 6 s        max ripple
     A      -10.03 .. +4.87 dB    5.04 .. 14.38 dB    <- unusable
     B       -1.47 .. +0.44        0.22 ..  2.65      <- steady on 3 of 5 notes

Two presets chosen for an unrelated property; one is usable and the other swings
14 dB. **Assuming either was "steady material" was a coin flip**, and the ladder
annotation now records which one, measured, with the numbers.

## §113 — The attack is convex, and a scalar attack time cannot carry that (2026-09-11)

The E4XT's amplitude-envelope attack is **not a linear ramp**. Measured on
material established steady by the §112 rectangle test, single attack segment
(Atk1 level 100, no knee), Atk1 rate byte 72, times from note-on to the first
crossing of each fraction of the plateau, 5 ms smoothing:

    note    t10     t50     t90    t50/t90   implied n in level ~ t^n
      24   0.796   1.615   2.110    0.765           2.20
      38   0.769   1.707   2.188    0.780           2.36
      52   0.846   1.712   2.214    0.773           2.28
      65   0.904   1.753   2.500    0.701           1.66
      79   0.975   1.914   2.633    0.727           1.84

    median t50/t90 = 0.765, spread 0.079 across five notes

    linear in amplitude  -> 0.556
    exponential approach -> 0.301
    MEASURED             -> 0.765     convex: slow start, accelerating finish

**A sibling project measured a conversion target's ramp at 0.500–0.558 over four
rungs — linear.** So the two machines rise by different functions, and the
E4XT spends ~77 % of its time-to-t90 reaching half level where a linear ramp
spends 56 %.

### The consequence is structural, not a tolerance

A converted format that carries **a time** can match the endpoints and cannot
match the middle. On a 3.5 s attack the E4XT is at 13 % of level where a linear
ramp is at 29 %, and reaches half level about half a second later. **That is an
audible difference no value of the time parameter can remove**, and it belongs
beside "the target has no envelope key-follow" and "`DECAY1` has no range left"
as a limit of the target format rather than as a conversion error.

### It also explains a detector disagreement that looked like a defect

Threshold-crossing and argmax disagree by **1.69x** on the same capture — 2.28 s
against 3.85 s. On a straight ramp every sane detector lands near the same
place. **On a convex rise there is no knee, so the two families are measuring
genuinely different points of the curve and must disagree by an amount set by
the curvature.** The 1.69x is the curvature reported in the units of two
conventions; it is not noise and not a bug in either detector.

### Measurement scale is a parameter of "steady", not just of the detector

Material called steady at 0.22–0.71 dB of ripple — RMS over 0.2 s windows —
swings **±1.5 dB** at the 5 ms the detector actually uses. **The figure was right
for the window it was computed over and wrong for the window that consumes it.**
Not a different definition: the same definition at a different *scale*.

A threshold set below that swing is crossed by a ripple peak during the rise and
fires early by construction, which is what a −0.1 dB rule did here. **The
threshold must be chosen for the noisier side's material**, exactly as a window
must be chosen by min-max across both machines (§109) — or the rule is well posed
on one side only.

**So an attack time is quotable only with three things attached: smoothing
width, detector family, and threshold.** Fixed here at **5 ms / threshold /
−3 dB**, which gives byte 72 = 2.035 s. Quoted bare, the same capture supports
1.73 s, 2.28 s, 3.85 s or 4.69 s.

## §114 — Two ways to generalise from a sample, and only one has a cheap fix (2026-09-11)

**NOT LOOKING AT A POPULATION YOU CAN SEE.** A corpus figure taken off 6 of 64
disc images; a shape claim taken off 1 of 5 measured notes. The fix is to check
the denominator, and **nothing in the situation prompts you to** — the number
looks the same either way.

**NOT ASKING A SESSION THAT IS HOLDING THE ANSWER.** The other five notes existed
and were in another session's hands. This mode **exists only when two parties
work one problem**, and its fix is a single question — *do you have the rest?*
— which makes it the cheaper of the two to avoid and, in practice, the one
nobody applies.

The reason it is not applied: **a number arriving from a peer feels like a
result rather than like a sample.** The first failure feels like laziness and is
therefore guarded against; the second feels like collaboration.

### The defence that held: quote measured points, not fitted parameters

A fitted exponent of 2.6 was offered for the attack curve. The five measured
notes support 1.66–2.36, so **the fit sat outside the range of the data it came
from** while looking more precise than any of it. Restated from two columns of
the same table —

    to 10% of level   0.846 s measured against 0.246 s linear   3.44x
    to half           1.712 s against 1.230 s                   1.39x
    half level arrives 0.48 s late

— it reproduced exactly on the other side and survives whatever curve turns out
to fit. **A fitted parameter has freedom that two measured points do not**, and
that freedom is what lets it land outside its own evidence.

### Redundancy is correct for a list like this

The seven definitional-parameter instances (§111, §113) are recorded here **and**
in the sibling project, deliberately. A list whose entire value is being noticed
again next time should not have a single point of failure — and **it means
neither copy has to be canonical**, which is exactly how §105's material got
lost: one record, no second copy, and the omission invisible until something
started depending on it.

### Addendum — when a claim dies, chase the wreckage

Nine claims were refuted across two projects in one day. **Neither of the two
real defects found came from a surviving hypothesis; both fell out of a dying
one.**

    an attack reader wrong on 130 of 130 corpus voices
        fell out of reading ONE envelope segment wrongly, which prompted a
        device read, which showed the two-segment structure

    a board path silently merging two filter shapes into one
        fell out of suppressing a warning, which prompted reading EVERY
        warning, which surfaced 31 that the emitting guard forbids

**A refuted hypothesis has usually moved something on the way down** — a
measurement taken, a field read off the device, a structure inspected — and that
residue is where both findings were. Dropping a dead claim cleanly is the tidy
move and would have cost both.

So: **when a claim is refuted, look at what the refutation touched before
closing it.** That is an instruction, not a moral — the cost is one look and the
alternative is discarding the only new evidence the episode produced.

### Addendum — a wrong lesson drawn from a misdiagnosis outlives the misdiagnosis

A sibling session diagnosed an E4XT silence as cleared RAM, from `5542 kB used`
against source banks of 6.3–15.3 MB on disk. **Only the samples a preset
references load, not whole banks** — the eight resident presets reference
3,510 kB, so that figure meant RAM was FULL. The preset-memory figure said the
same: six presets dump to ~4 kB, so "5 kB used" is eight presets present.

**The diagnosis was wrong. The lesson drawn from it was worse.** It was stated
as *"a catalog answers `is the NAME there`, not `is the SOUND there`"* — and on
this machine presets and samples do **not** survive a power cycle, so a catalog
listing names means they *were* loaded. **The original catalog reading was
correct.**

**And this session accepted the correction and confessed to an error it had not
made**, in writing, twice — because the correction arrived from a peer as a
diagnosis of *this* session's work, and a plausible rule about one's own mistake
is harder to push back on than a factual claim about the world. **It was the user
who refuted it**, from knowing the machine: *"if it lists presets, they have been
loaded after a power cycle."*

**A general lesson extracted from a misdiagnosis is more durable than the
misdiagnosis** — the wrong figure gets corrected when someone re-runs the
command, but the rule propagates into other work and teaches future sessions to
distrust a reading that was right. **So when a diagnosis is retracted, retract
anything generalised from it in the same motion**, and check the arithmetic of a
correction with the same suspicion as the arithmetic of a claim. A correction is
a claim.

**The corollary, which belongs to the sender rather than the receiver: state the
arithmetic, not the conclusion.** The correction arrived as *"your reading was
wrong, the RAM is empty"* rather than *"5542 kB used, against this — check me."*
**A correction delivered as a conclusion removes the recipient's ability to
refuse it**: the denominator error could not have been caught here because it was
never shown. So the receiving failure (accepting a claim about one's own work)
and the sending failure (sending a verdict instead of a calculation) are two
halves of one exchange, and only the sender can fix the second.

**Both here and in the sibling tree, deliberately** (§114): the record that
matters is the one that survives, and neither copy should have to be canonical.

## §115 — Test hardest the part you are most confident in (2026-09-14)

Written after building a static invariant for a sibling project and getting a
false positive in the one check I had reasoned about least.

The invariant routes every modal dialog through a single module, so that a
dialog is interceptable in a test. Two halves: a **call** check (is a modal
constructed or statically invoked?) and an **import** check. The import check
exists because `from x import QMessageBox as MB` renames the symbol and
`MB.warning(...)` then matches nothing in the call scan — **the import line is
the only place the real name still appears.**

It was verified against 21 cases before handover. **Every one of them was a
call.** The import check got four straightforward cases and no adversarial
thought at all. It is the check that produced the false positive.

**That is not bad luck. I tested the part I had thought about.** Confidence
marks where the reasoning has already been done and therefore where the testing
feels redundant — which makes it exactly where the untested reasoning lives.
A sibling put it as: *the memo I keyed carefully and the assertion I wrote
loosely; the literal I pinned and the substring match I did not think about; the
perturbation I designed and the check that it perturbed anything.*

### A defence usually creates a false-positive class, and it is worth naming

The import check cannot distinguish **importing a modal to subclass it** from
**importing one to raise it** — the import line is identical. So the alias
defence necessarily flags every dialog the project legitimately subclasses.

Traced rather than assumed, because the obvious explanation was wrong: a base
class is an `ast.Name` in `ClassDef.bases` and **never** an `ast.Call`, so
`class SettingsDialog(QDialog)` could not have reached the call check at all.
Both of us had attributed it to the wrong half.

**And the exemption list that fixes it must not carry two rationales under one
label.** `NOT_A_MODAL` holding both `QDialogButtonBox` (genuinely not a modal)
and `QDialog` (genuinely is one, but subclassed) invites the next person to
extend it by matching the label rather than the rationale. Renamed to say what
it means — names whose import is legitimate outside the seam — with the reason
written beside each entry.

### Three smaller rules from the same exchange

**Guard the seam, not just the listing.** "No modals outside the seam" is
satisfied by there being no modals *anywhere*, which is indistinguishable from a
healthy tree until the first one is added. So assert the seam module exists
**and actually contains a modal.** Same species as asserting a file listing is
non-empty (§108), one level up.

**A ratchet must fail in both directions.** `BASELINE = 48` failing upward on a
new violation is the obvious half. Failing **downward on a stale baseline** —
someone removes a site without lowering the number — is the half usually left
out, and without it the number quietly stops meaning anything. A stale
threshold is a stale stub (§111) wearing different clothes.

**Deliver a check in the shape of the harness that will run it.** A 204-line
invariant written pytest-shaped, handed to a project whose suites are scripts
with a `main()` and an exit code, **ran and exited 0 having done nothing** — a
file whose entire purpose is catching checks that cannot fail, delivered in a
form that could not fail. One question before writing would have caught it, and
running it caught it in ten seconds where reading it had not.

## §116 — The EOS OS floppy images are packed, and the unpacker is not in them (2026-09-14)

s3ked read an envelope rate table straight out of an Akai firmware image, and
mpc2emu sent over a scanner to repeat it here. Jan supplied `EOS470.zip` and
`EOS_V461.EXE` for the purpose. **The route does not exist on this machine, and
the reason is structural rather than a matter of trying harder.**

### What the files are

```
EOS470.EXE / EOS_V461.EXE   1,480,228 bytes each, same shell, different payload
  0x0000  5,668-byte DOS loader, LZEXE v0.91 ("LZ91" at offset 0x1c)
  0x1624  1,474,560 bytes appended = one 1.44 MB floppy image
```

The loader's own strings say what it is: `Restoring Image `, `Head `, `Track `,
` #1-18`, `==> 100% `, `SelF-eXtractor`. It is a generic DOS disk-imaging
self-extractor. **It writes the image to a floppy verbatim and does nothing
else.** 18 sectors per track, two heads, 80 tracks — standard 1.44 MB geometry.

The image carries an E-mu header in sector 0, big-endian:

```
  0x00  0x76543211                 magic, identical in both
  0x04  0x08860E57 / 0x07D2C274    differs; not a sum8/sum16/sum32 of the body
  0x08  0xF779F1A8 / 0xF82D3D8B    differs; likewise
  0x0c  0x00020602                 IDENTICAL in both -- format version
  0x10  0x0014F755 / 0x001341BE    1,374,037 / 1,262,014 -- payload length
  0x18  "EOS v4.70" / "EOS v4.61"  24-byte banner
  0x200 payload; 0xF6 fill (the DOS format filler) after the data
```

### Why no scan of it can find a table

Everything from 0x200 to the fill is packed. Establishing that took four
probes, and the order matters because the cheap ones are the ones that mislead:

**Entropy alone proves nothing.** 7.19 bits/byte mean over 4 kB windows is
consistent with compression *and* with encryption *and* with a large block of
sample data. It is a reason to look further, not a finding.

**Structure: none.** Autocorrelation over the payload shows no peak above 0.02
— one continuous stream, not a sectored or chunked container. Nothing to index
into.

**Plaintext: none, anywhere.** 256-byte windows across all 5,367 windows of the
payload: 85 fall below 6.0 bits/byte, which is the statistical floor for
windows that short — small windows under-estimate entropy even on uniform data.
68k code sits near 5.0 and there is not one such region. **So there is not even
a plaintext bootstrap on the disk.**

**The one hypothesis worth testing, and how it died.** Both payloads *begin*
with identical byte runs that diverge at the same offsets:

```
  4.70  3b1506 41 0042181c577b9e5e2a80 0008 0c0200 07 5fc8 8004040c8a4f29880ec34170d c6 02080874701203ffcdcd08202
  4.61  3b1506 41 003b4984747c0b47a8b0 0008 0c0200 06 d5a7 8004040c8a4f29880ec34170d 86 22080874701203ffcdcd08202
```

Position-preserving agreement like that is the signature of a **byte-wise
scramble** (XOR keystream), not of compression — compressed streams of similar
inputs desync within a few bytes and never re-align. If it were a scramble,
XORing the two images cancels the keystream and leaves plaintext-vs-plaintext,
which for two point releases of one OS should be mostly zero.

It is not. Outside the trailing fill, agreement runs **1.0–1.3% per 64 kB
block** — and that is what two *uncorrelated* streams of this skew give, since
collision probability for a distribution at 7.19 bits/byte is about 1%, not the
0.39% of uniform bytes. **The excess over 1/256 was the skew, not a signal.**
The matching head bytes are a coincidence of a short prefix. Scramble refuted;
compression confirmed.

**And no standard scheme reads it.** Byte-oriented LZSS across window 2^10–2^13
× length+2/+3 × both flag-bit orders × both offset byte orders (16 combinations,
scored by printable-string yield, not eyeballed): nothing. Bit-oriented LZSS at
six parameter sets × both bit orders, and LZW at 9–12 bits × both bit orders ×
both early-change conventions: every one desyncs inside 8 kB. Not zlib, deflate,
gzip, bz2 or lzma either.

### The structural conclusion

The DOS stub only moves bytes to a floppy. The disk holds no plaintext. So
**the decompressor runs on the E4XT, out of its boot ROM** — which we do not
have and cannot read over either SysEx protocol. The packing scheme is E-mu's
and lives in silicon on the other side of the MIDI cable.

**This is not "we failed to identify the format". It is that the format's
decoder was never in the files.** Jan's two OS images are exactly as far as this
line goes, and a better scanner, a longer parameter sweep, or a third OS version
would all fail for the same reason.

### What this costs, and what it does not

mpc2emu's scanner is sound and its controls pass; it simply has no substrate
here. The choice it was built to settle — whether the envelope rate law is
`ENV_RATE_SWEEP_K` 0.0565 or `ENV_RATE_K` 0.0581, a 2.8% difference that is
inside the noise of both fits — **does not get settled from firmware.** It stays
where it was: a question for the captures, which means it stays open until
something measures it more finely than the fits that produced the disagreement.

**The general form.** s3ked's method transferred as an idea and not as a
procedure, and the part that did not transfer was not the search — it was the
assumption that the firmware file contains the firmware. On the Akai it did. A
technique borrowed from a sibling machine carries the sibling's platform
assumptions silently, and the cheapest place to find that out is before the
search, by asking what the container is, rather than after, by concluding a
table is absent when the whole image is.

### §116 addendum — what makes a negative result reusable

mpc2emu's reading of the above, which is the part worth keeping: the value is
not in "I tried and it didn't work" but in the falsifiers attached to each step
— entropy quoted **with the statistical floor for the window size**, autocorrelation
**with a threshold**, 36 schemes scored by a **metric rather than by eye**, and a
live hypothesis killed by a test **whose expected agreement was computed before
it was run**.

**A negative result with a falsifier attached is worth more than most
positives.** It closes the question for every future EOS version rather than for
the two images in hand — whereas "no luck with the formats I tried" would have
had to be redone by the next person, who would have tried the same formats.

The converse is the failure this same day nearly produced twice: a positive
without a falsifier (§118's forward-decoded jump table, §117's inflated credit)
looks finished and is not.

## §117 — The attack constant is probably right and its recorded reason is wrong (2026-09-14)

mpc2emu flagged that the sentence justifying `_E4XT_ATK_SLOWDOWN` 1.838 → 1.0
"compares a full-level intent against a −3 dB measurement while asserting *at the
same convention*", and that 3.552/1.960 = 1.81 sits uncomfortably close to the
1.838 it killed. **They are right about the sentence. The constant survives
anyway, for a different reason than the one written down, and that is a worse
state than being wrong — the next person to revisit will check the reason.**

### The sentence

`intends` denotes the **full traversal** — §105 settled that from the source
side (the source law's own 10-90%/full ratio is 0.704, not 1.0). The hardware
figure it was compared against, 2.035 s at byte 72, is a **−3 dB threshold
crossing** at 5 ms smoothing. Those are two conventions, and "the machine agrees
with `intends`" asserts they are one.

### How far apart they actually are

From §113's five notes — measured `t90` and the implied exponent in
`level ~ (t/T)^n` — solving for the −3 dB crossing (0.7079 of plateau) and for
the full traversal:

    note    t90     n     t(-3dB)   t(full)   full/-3dB
      24   2.110   2.20    1.892     2.214      1.170
      38   2.188   2.36    1.976     2.288      1.158
      52   2.214   2.28    1.993     2.319      1.164
      65   2.500   1.66    2.163     2.664      1.231
      79   2.633   1.84    2.311     2.788      1.206

    median full/-3dB = 1.170        (t90/-3dB = 1.115, the floor that needs no
                                     extrapolation past the last measured point)
    a linear ramp would give 1.4125  <- the AKAI's factor

**Convexity pulls the two conventions together, it does not spread them.** So
the Akai's 1.4125 — which s3ked confirmed to three decimals on *their* linear
ramp — is the wrong correction to carry across, and carrying it would have
overshot by 21%. A convention factor is a property of the *shape*, and the two
machines do not share one.

**Credit where the first draft of this section misplaced it.** mpc2emu did not
carry 1.4125 across and said so when they raised the flag — "the Akai ramp is
linear and yours is strongly convex, so the Akai argument does not carry over
and this needs your own convention audit, not my inference." They named the
non-transfer before the audit existed and declined to act without it; the solve
above is the audit they asked for, not a correction of them. Writing it as
though a live error had been headed off inflated the finding and took the
judgement off the person who made it.

### So the 1.838 was the detector, and the arithmetic is checkable

    1.838   old bias, measured against argmax t_peak
    1.689   argmax vs -3 dB threshold on one capture (113: 3.85 s vs 2.28 s)
    -----   1.838 / 1.689 = 1.088 residual

with sd 0.050 on the 1.838 (±2.7%). **1.088 is about three of those — small,
and not zero.** And 3.552/1.960 = 1.812 is that same detector gap showing up a
second time, not independent evidence for a machine bias.

**One trap avoided in the writing of this.** The first pass multiplied the two
factors — 1.170 × 1.689 = 1.976 — to "decompose" the 1.838, and overshot by
7.5%. They are not independent: argmax lands *in the plateau*, past the full
traversal, so the 1.689 already contains the 1.170 and then some. Two factors
that overlap cannot be multiplied, and the overshoot was the only thing that
said so.

### What the constant should be, and why the answer is a choice

- Targeting the **−3 dB crossing**: `SLOWDOWN = 1.0`. Correct as it stands.
- Targeting the **full traversal**, which is what `intends` denotes:
  `SLOWDOWN ≈ 1.17` (floor 1.11 without extrapolation). **SUPERSEDED IN SCOPE by
  §119: that 1.17 is five notes of ONE preset at ONE byte, and the ratio is now
  known to vary 7.6% between programs on a single machine. Read it as "~1.17 on
  one preset, spread across presets unmeasured."**

**Nothing in the measurements picks between those.** It is a question of which
point of the curve the conversion should match, and §113 says it cannot match
more than one: the shapes differ so much that on a 3.5 s attack the E4XT is at
13% of level where the source is at 29%.

**The recommendation is to keep 1.0 and rewrite the reason.** Matching at half
power is closer to where the ear weights an attack than matching the last few
percent of the traversal — which is also the part the plateau ripple (±1.5 dB at
5 ms, §113) makes least measurable. That is a defensible choice. It is not the
claim currently recorded, which is that the machine agrees with `intends`.

### The generalisable part

**A constant can be right for a reason that is not the recorded reason, and the
recorded reason is what the next revision will be argued from.** mpc2emu's
instinct — flag it rather than act on it, because the Akai argument does not
carry over — was the correct handling, and the flag arrived with its own
arithmetic so it could be checked rather than accepted. That is the §114
addendum working in the direction it was written for.

**And a convention factor is not a constant of the domain.** 1.4125 is exact for
a linear ramp and simply false here; the same symbol, "the difference between
full and −3 dB", takes a different value on every ramp shape. A number that
transfers between machines is a number whose derivation transfers.

## §118 — The entropy check is two-sided, and it cannot tell you that you succeeded (2026-09-14)

k2kremote ran §116's entropy check on their own firmware image and got the exact
inverse result, which is what makes it worth recording as a method rather than as
a one-off:

```
                        K2000 image        EOS 4.70 image
  mean entropy          5.00 bits/byte     7.19 bits/byte
  windows below 6.0     4040 / 4095        85 / 5367
                        = 98.7%            = 1.6%, the floor for 256-byte windows
  verdict               plaintext 68k      packed end to end
```

**A test that only fires one way is a detector; a test that separates both ways
is a discriminator.** §116 used it to establish absence, which is the weaker
direction — the same check on their side establishes presence, and the two
results together are what make the 7.19 meaningful rather than merely high.

### What it still cannot do

k2kremote had already decoded their DSP-function dispatch before running it — a
bounds check, a linear search of a 67-entry code table, then a jump through a
table indexed by the search's loop register — and validated the result against
**65 codes measured independently on the instrument over several days, zero
disagreements.**

Their own framing of the ordering is the right one: **entropy first because it is
cheap, but behavioural agreement is the only check that is conclusive.** Entropy
would have saved them the attempt had it come out like ours. It could not have
told them the attempt had *worked*.

### Three traps in one exchange, all the same shape

**The failure mode of firmware reverse engineering is a plausible wrong answer,
not an error.** Every instance we hit between us is that:

- **Wrong ISA.** A later-m68k decode accepts addressing modes the 68000 does not
  have and emits a reasonable-looking listing. `-m m68k:68000` pins it. They had
  it right by luck rather than judgement, which is worth saying out loud because
  luck does not repeat.
- **Wrong direction.** Their jump table is indexed by a register counting
  **down**, so it runs in reverse relative to the code list. Decoded forwards it
  yields a complete, plausible, entirely wrong mapping. Nothing internal to the
  decode says so.
- **Wrong substrate.** A disassembler pointed at packed data produces
  instructions, not a complaint (§116).

In all three, the artefact looks like a result. **So the question to ask of a
decode is never "does this look right" but "what does it predict that was not
used to build it".** 65 hardware measurements reproduced by a table derived
without them is an answer. Internal plausibility is not.

### The asymmetry on our side, stated plainly

Theirs is a firmware decode corroborated by hardware. **Ours is the inverse and
has no corroboration available at all**: every E4XT curve we hold is a fit to our
own captures, and §116 closed the only independent route to checking them. That
does not make them wrong — the ladder's byte-follows-across-programs cross-check
is real evidence. It makes them **single-method**, and §111, §113 and §117 are
three separate demonstrations of how much of a measurement is convention rather
than machine.

**The honest position is that s3ked's challenge to our curves was neither
confirmed nor answered.** It was rendered unreachable. Those are different
states and the notes should not let them blur.

The remaining route is a boot-ROM dump off the machine, which is a hardware read
and Jan's call, not ours to plan around.

### §118 addendum — neither result would have survived the other's method

mpc2emu named the symmetry, and it is a stronger statement than the ordering it
comes from:

- **§116's negative is airtight because the expected agreement was computed
  before the XOR was run.** A falsifier fixed in advance is what makes a null
  result binding rather than merely disappointing.
- **k2kremote's positive is airtight because 65 independent hardware readings
  reproduced a table derived without them.** External agreement is what makes a
  decode binding rather than merely plausible.

**Swap the methods and both collapse.** Entropy would never have caught a
reversed jump table — the forward decode is high-quality plaintext either way.
Sixty-five panel readings would never have proved a packed image contains
nothing — there is nothing to read off a panel that speaks to the container.

So "entropy first, behavioural agreement last" is not a preference about
thoroughness. **The two checks answer different questions, and the cheap one
cannot be made to answer the expensive one's question by running it harder.**

**And the reason the §117 credit correction mattered more than the sentence it
was about**, in mpc2emu's framing: the arithmetic survives either attribution,
but *who is answerable for the call* does not. Recording a colleague's
deliberate non-action as an error averted transfers the judgement to whoever
reads it next — the same failure as a wrong recorded reason (§117), one level
up.

## §119 — The shape ratio varies between programs, so §117's 1.170 is an n=1 figure (2026-09-14)

**Stated before it is explained, because it weakens a number this project issued
three hours earlier.**

s3ked measured the full/−3 dB ratio **twice on one Akai in one session**:

```
  ATKCAL program, ATTAK1 60        1.396   (ladder mean 1.4156, sd 0.011)
  a different resident program     1.298   same byte, same machine, same hour
                                   ------- spread 7.6%
  our E4XT, one preset, byte 72    1.170
  a straight amplitude ramp needs  1.4125
```

§117 said "a convention factor is a property of the *shape*, and the two machines
do not share one." **That is now too weak in a way that matters: one machine does
not share one with itself.** The ratio is a shape diagnostic, and envelope shape
varies between programs on the same sampler — demonstrated across two machines
and two programs of one machine, not argued.

### What that does to our own number

§117's 1.170 is the median of five notes **of a single preset at a single byte**.
Five notes is a population on the dimension we sampled and n=1 on the dimension
s3ked just showed is live. That is §114's first failure mode — not looking at a
population you can see — arriving in a section written the same day as the
warning about it.

**§117's fork stands; its coordinates do not.** Which point of the curve the
conversion should match is still the real question, and matching at half power is
still the better answer for the reasons given. But "the alternative is 1.17"
should read **"the alternative is ~1.17 as measured on one preset, and the
spread across presets is unmeasured."** Corrected in place rather than left to
be inherited, per §117's own rule.

### And it forces a re-reading of §105's cross-check

The ladder's cross-check reads: a preset whose panel showed Atk1 rate 89
measured `t_peak` ~10.1 s; byte 89 on **a different preset with different
material** gave 9.10 s — "the timing follows the byte across programs, which a
material artefact could not."

**That is an 11.0% disagreement, and we recorded it as agreement.** Against
measurement noise it is agreement. Against s3ked's §236 — same byte, two
programs, **33% different attack and a different shape**, with every readable
envelope parameter identical or ruled out — 11% is the same size as the effect
they just characterised, and our reading of it assumed the effect does not exist.

It does not overturn the ladder: the byte plainly dominates, 9.1 s against 0.18 s
at byte 20. **It does mean the cross-check proved less than it was quoted for.**
It showed the byte is the main term. It was cited as showing the byte is the only
term.

### The firmware route was closed twice over

s3ked's method needs **published anchors** — four exact integers Akai release,
confirmed by endianness and a `0x7FFF` clamp. Every EOS envelope number we hold
is a fit to captures, so there is nothing to anchor a search on. **Even with a
plain image the search would have been much weaker here**, and their image had no
container at all: a raw 256 KB binary. They did not solve a packing problem; they
did not have one.

So §116's structural close is the second reason the route fails, not the first.

### The caution, now with a live example rather than a principle

The warning issued before any of this was agreed — *firmware says what the
machine intends, captures say what left the converters, and a disagreement is not
automatically the measurement being wrong* — has a case attached to it an hour
old. s3ked's §236 is a 33% attack difference between two programs that **no
firmware table would have predicted**, found only because the audio disagreed
with the intent. Their own conclusion: with a table in hand they would probably
have trusted it over the audio and been wrong.

**A table is a stronger form of evidence about intent and a weaker one about
output.** Our position — captures and no table — is worse for settling
0.0565 vs 0.0581 and better for noticing this.

### §119 addendum — the 11% has a simpler candidate, and we cannot run the test that would settle it

mpc2emu proposed a free test for a multiplicative mechanism: if the envelope
generator is clocked off playback rate, envelope times scale with sample rate
exactly multiplicatively, and 44100/39062.5 = 1.129 sits near our 1.110. They
were explicit that the arithmetic behind it is weak — 8 rates is 56 pairs and a
2% match is near-guaranteed by chance, fitted after seeing the answer — and that
the point is that it is a **prediction**: read the two presets' sample rates and
see whether the ratio is 1.110.

**We cannot run it.** The ladder's rows carry `byte, intended, hold, window,
peak_db, t_peak, rise_10_90, flags` and **no preset and no note**. The
cross-check names neither of its two presets. §111 recorded that the material was
unidentified as a reproducibility gap; this is the first time it has cost a
specific answer, and the answer it cost was to a test that takes a minute.

**But the E4XT's own data kills the clocking half of the hypothesis outright.**
§113 measured `t90` at byte 72 across five notes on one preset:

```
  note   t90     ratio      playback rate vs note 24
    24  2.110   1.000              1.00x
    38  2.188   1.037              2.24x
    52  2.214   1.049              5.04x
    65  2.500   1.185             10.68x
    79  2.633   1.248             23.97x
```

55 semitones is a **23.6x** change in playback rate. If the envelope were clocked
off it, `t90` would fall by 23.6x. It **rises by 1.25x**. Wrong magnitude by a
factor of 19 and wrong sign. The envelope generator is not clocked off
instantaneous playback rate. It could still be clocked off a sample's *declared*
rate, which is constant under transposition — untested, and untestable on this
data for the reason above.

### And this is where §119 was itself too quick

§119 read the 11% cross-check gap as "the size of the effect s3ked
characterised". True, and incomplete: **11% is also the size of an effect we had
already measured and did not control for.** Notes 52 to 65 on a single preset
give 2.500/2.214 = **1.129**, against the cross-check's 10.1/9.10 = **1.110**.

The two cross-check measurements record no note. **So the simplest explanation
for the entire gap is that they were taken at different pitches on the same
machine with the same byte** — no program-dependence required at all.

That is a candidate and not a conclusion: the note-dependence is measured at byte
72 on one preset and the gap is at byte 89 on two others. But it is a mechanism
we have *already observed on this machine*, and program-dependence is one we have
only observed on a different machine. **The known effect should be excluded
before the imported one is invoked**, and §119 invoked the imported one first
because that was the message that had just arrived.

**mpc2emu's instinct to keep the two results apart was right and did not go far
enough.** They separated our multiplicative case from s3ked's additive one. The
third possibility is that ours is neither — that it is an uncontrolled variable
in our own procedure, which is the one explanation that requires no mechanism at
all.

**What would settle it:** re-take two points at byte 89 on one preset at two
known notes, and the same two notes on a second preset. That is RAM-only work on
material that has to be reloaded anyway, and it belongs to whoever holds the
lead. The note-dependence itself — 1.25x across 55 semitones, in the direction of
*slower at higher pitch* — is unexplained and worth a section of its own once
someone measures it deliberately rather than reading it out of a spread.

## §120 — The level test would locate the convexity, and it is the third test in half an hour blocked by a missing column (2026-09-14)

mpc2emu's candidate for §119's note-dependence: "slower at higher pitch" is not
key-follow (which runs the other way), but it is exactly what a **fixed-rate ramp
climbing to a note-dependent level** looks like. Nothing about the rate changes;
the plateau is simply a little higher up the keyboard. Their prediction: a
**+1.92 dB** level offset across 55 semitones, 0.035 dB/semitone — too gentle to
notice by ear and large enough to read off a capture.

### The prediction depends on where the convexity lives, and that makes it better

Their arithmetic takes `t90 ∝ plateau`, which holds for a ramp whose *amplitude*
climbs at a fixed rate. §113 measured the amplitude rise as convex, `level ~
t^2.28`, so there are two placements and they predict different numbers:

```
  convexity in the RAMP        plateau ratio = t ratio         = 1.248  -> +1.92 dB
    (amplitude climbs convexly to L, time-to-plateau ∝ L)
  convexity in the OUTPUT MAP  plateau ratio = (t ratio)^2.28  = 1.657  -> +4.39 dB
    (internal generator ramps linearly at fixed rate, audible level = internal^n)
```

**The `n = 2.28` in row 2 is a band, not a value** — §113's five notes fit 1.66
to 2.36 — so the honest separation is the worst case rather than the headline
one (mpc2emu's check, arithmetic reproduced here):

```
  n 1.66  -> +3.19 dB      row 1 is n-INDEPENDENT (time-to-plateau ∝ L)  +1.92 dB
  n 1.84  -> +3.54         row 3                                          0.00 dB
  n 2.28  -> +4.39
  n 2.36  -> +4.54
                           closest approach, row 2 to row 1:              1.27 dB
```

**1.27 dB at worst, on a quantity measurable to a few tenths.** So the
measurement
does not merely confirm or kill the level hypothesis — **it says whether the
E4XT's convex attack is produced by a convex ramp or by a linear ramp through a
non-linear output stage.** That is a fact about the machine, and it would be the
first one we hold about the envelope generator's internals rather than its
behaviour.

There is a third reading in which `t90` is self-normalising — a fraction of
whatever the plateau is, hence invariant to it — and that one predicts **0.00 dB**
and is also distinguishable. Three placements, three separated predictions, one
capture.

### And it cannot be run

`peak_db` is a column of the ladder, but the ladder's rows vary **byte at one
unrecorded note**: −40.59, −48.72, −52.77, then flat at −53.9 ± 0.1 from byte 72
up. §113's five-note table records `t10`, `t50`, `t90` and **no level at all**.

**That is the third test blocked in half an hour by the same cause:**

```
  mpc2emu's sample-rate test   needs the preset per row   not recorded (§119)
  the uncontrolled-note reading needs the note per row     not recorded (§119)
  the level test                needs the level per note   not recorded (here)
```

Each was a lookup in data we already had. Each cost nothing to have recorded and
cannot now be recovered without re-taking the measurement on material that no
longer exists in RAM.

### The rule, in mpc2emu's framing, which is better than the one §111 had

§111 recorded the unidentified material as a reproducibility gap — a thing that
would be awkward *if* someone wanted to extend the ladder. That undersold it.
**The cost of a missing column is never visible when you decide not to add it,
and it is never paid by the session that omitted it.** It is paid by whoever
arrives with a question the columns would have answered, and they find out only
after the question exists.

So the fix is not "identify the material next time". It is a fixed minimum row:
**`preset`, `note`, and the measured level, on every row of every ladder, always
— including when no current question needs them.** Recorded in the ladder JSON
itself as `row_schema_required`, because the JSON is what gets quoted and the
prose is what gets skipped.

### Honest state of the hypothesis

A candidate, not a conclusion, and the corroboration is ambiguous: s3ked's second
Akai program was a *higher* note and also measured *slower* — same direction,
which is either support or two instances of one confound. And per §119's own
lesson, the confound is the reading to exclude first.

### §120 addendum — the note-dependence is an E4XT property, and the fork's capture must control velocity by measurement

s3ked measured the plateau-level hypothesis on the Akai, `ATTAK1` 0 and 60,
notes 48/72/96:

```
  plateau   +0.00  +0.02  -0.02 dB    flat to 0.02 dB over 48 semitones
  t90        0.19659 0.19666 0.19757   0.5% over 48 semitones
                                       E4XT, for comparison: 1.25x over 55
```

mpc2emu's prediction was +0.035 dB/semitone and this is off by a factor of
eighty — **but the model only had a job where a note-dependence exists, and on
that machine there is none.** A hypothesis applied to a machine with nothing for
it to explain has not failed on its merits, and recording it as "falsified"
would retire a model that has never been tested where it applies.

**What this does settle, and it is worth more than the hypothesis:**
note-dependence is an **E4XT property, not a generality of envelope
generators.** Two machines, one parameter, one has it by 25% and one does not by
0.5%. That was an open possibility this morning. Whatever §120's fork finds is
therefore about this machine's generator specifically, which is a sharper result
than it would have been — the capture is more worth taking, not less.

**And it resolves §120's ambiguous corroboration in the opposite direction.**
The caveat there was that s3ked's second Akai program was a higher note and also
slower — "either support or two instances of one confound". On a machine with no
note-dependence it can be neither: their slower program **cannot** be a note
effect, so it does not corroborate our level hypothesis, and their
program-dependence stands as a real and separate thing rather than as a possible
confound. §119's reading of *our* 11% as a plausible note artefact is unaffected,
because the note-dependence it invokes is ours and is large.

### The capture's protocol has a requirement the fork did not state

s3ked eliminated velocity by **measuring** it rather than by reading `V_ATT1..3`
and `VELDEP` as 0: plateau moves **16.5 dB** across velocity 40→127, attack
moves 1.6%.

§120's fork separates 0.00 / +1.92 / +4.39 dB **on plateau level**. A velocity
sensitivity of that order would swamp all three, and it is exactly the kind of
thing a parameter read reports as absent. **So the capture must hold velocity
fixed and demonstrate the plateau is insensitive to it on the material used,
before any of the three predictions can be told apart.** Without that the fork
measures the wrong quantity precisely.

`velocity` added to `row_schema_required` for the same reason the other columns
are there: it is not needed by today's question.

**The recurring form, now four times today:** a parameter read standing in for a
measurement. The read is usually correct — theirs was — and correctness is not
the issue. A read reports what the machine was told; only a measurement reports
what the machine did, and every gap found today has lived in that difference.

**Two corrections from s3ked, both against their own numbers.**

**The 16.5 dB is a property of their subject, not of their machine** — that
program has its velocity-to-level depth set to 20, and a program with it at 0
should show almost none. So it is an upper bound from one badly-chosen subject
and **must not be used to size our test**; the magnitude belongs to the subject
and only the instruction transfers. Corrected in `row_schema_required`, where it
had been written as a machine property and would have been quoted as an expected
value. **A number crossing a machine boundary without its conditions** is the
form that has cost the most this week — §117's 1.4125, §119's 1.170, and now
this — and here it was caught by the person who supplied it.

**And "a read standing in for a measurement" is not quite the failure.** Their
read of the velocity-to-*attack* fields as 0 was correct: velocity genuinely has
no route to the attack there. What went unchecked was whether some *other* route
existed, and a velocity-to-*level* field sat in the same header. So it is an
**incomplete enumeration of routes**, which is the sharper statement: a read
tells you about the field you read and says nothing about the one you did not
think to. A measurement is how you find the route you did not enumerate — which
is why it substitutes for the read, not because reads are unreliable.

## §121 — The attack's note-dependence is a detector artefact, and §120's fork has nothing left to explain (2026-09-14, live)

Jan freed the E4XT and asked for §120's capture. It was taken, and it destroys
the premise it was built on. **There is no note-dependence in the attack time.**

### What was measured

E4XT Ultra, EOS 4.70, one bank loaded from disk. One preset, **one voice, and
every note inside a single zone** — the loaded presets are three-zone (one
sample on keys 12–66, a second on 67–91, a third on 92–108), so notes
16/28/40/52/64 were chosen to sit entirely on the first. **§113's ladder used
24/38/52/65/79, and 79 is in a different zone from the other four** — a
different sample with its own level, on a test whose prediction was 1.9–4.4 dB.

Amp envelope: Atk1 rate under test, Atk1 level 100 (single segment, no knee),
all later segments rate 0 / level 100 so the note holds at full. Detector: 5 ms
smoothing, threshold-crossing, −3.0 dB, per the agreed convention.

### Two controls, both of which passed

**The write reaches the audio.** §34 recorded a parameter that reads back
correctly and does not sound, so this was checked rather than assumed: t90 at
Atk1 rate 0 is 0.025 s and at rate 72 is 2.34 s, SNR 55 dB. *It first caught a
genuinely silent capture* — `PRESET_SELECT` (223) aims the **editor**, Bank
Select + Program Change changes what **sounds**, and setting only the former
edits a preset that is not playing.

**Velocity does not move the plateau on this material** — −0.12 dB from
velocity 40 to 127. s3ked's protocol requirement (their plateau moved 16.5 dB
on a program with velocity-to-level depth 20) is satisfied here, measured
rather than read off the depth parameter.

### The result that looked clean

```
  note     16      28      40      52      64     ratio 64/16
  t90   1.725   2.175   2.315   2.660   2.855      1.655
```

One zone, one sample, 48 semitones, every column recorded. It reads as a
stronger confirmation of §113's 1.25× than §113 itself.

### And it does not survive being tested

**Smoothing sweep.** The ratio is a function of the detector, not of the machine:

```
  smoothing    5 ms    25 ms   100 ms   400 ms
  t90 ratio    1.655   1.149   0.889    0.889
```

**The no-attack control.** RUN A has an *instant* attack, so any note-dependence
it reports is manufactured. At the same 5 ms it reports **0.060 s at note 16
against 0.020 s at note 64** — a 3× apparent note-effect on a rise that does not
exist.

**And it is not one bad sample.** All 12 presets of the bank were screened with
§112's rectangle test, at the detector's own 5 ms scale rather than at the 0.2 s
scale the figure had previously been quoted at:

```
  sd of 12 sub-window medians     note 20    note 40    note 60
  every preset, without exception  2.1-2.3    0.5-1.8    0.6-2.5
  5 ms max/min swing, note 20      27-41 dB
```

Monotone in pitch, across three different sample sets. **That is transposition,
not material.** A ladder across notes plays ONE sample at many rates, so the
sample's own amplitude modulation is stretched by 2^((origkey−note)/12) — and a
fixed 5 ms detector therefore resolves a different number of sample-periods at
every note.

### The fix, stated before the answer was known

**Scale the detector with the playback rate:** `smoothing(note) = 5 ms ×
2^((origkey−note)/12)`, so every note is measured over the same number of
sample-periods. 31.7 ms at note 16, 2.0 ms at note 64.

```
  rate-scaled   note 16   28      40      52      64     ratio
  t90            2.570   2.521   2.351   2.628   2.472   0.962
  t50            1.745   2.093   2.098   1.821   1.775   1.017

  robustness, base width 2 / 5 / 10 / 20 ms:
    ratio     0.980   0.962   0.795   0.808
    max/min   1.174   1.118   1.282   1.311
```

**Flat, at every base width tried.**

### Why this direction and not the other

A fit that produces the desired answer deserves the question "would it have
produced any answer I asked for". Here it could not, and the asymmetry is
physical:

- The widest rate-scaled window is **31.7 ms against a 2.570 s measurement —
  1.24%**. A 1.655× note-dependence is **1.7 s** of difference. **A 32 ms window
  cannot hide 1.7 s.**
- It *can* manufacture one, because what it fails to reject is a **30 dB**
  ripple whose peaks cross a −3 dB threshold early, and which shrinks with pitch.

**Smoothing can create a spread it cannot remove.** That asymmetry is what makes
the flat reading the trustworthy one, not the fact that it is tidier.

### What this costs

**§120's three-way fork is void.** It asked where a note-dependence comes from;
there is none to explain. The plateau-level hypothesis, the ramp-versus-output-
mapping placement, the 1.27 dB separation — all of it was machinery built to
explain an artefact, and mpc2emu and I refined it through six exchanges without
either of us asking whether the effect was real. **The plateau measurements
agree**: span +1.70 ± 1.12 dB (instant attack) and +0.73 ± 1.36 dB (byte 72),
both consistent with zero, which is what "no note-dependence" predicts.

**The ±1 dB is not assumed.** RUN A and RUN B reach the *same* target level, so
their difference must be zero and measures the method: mean +0.74 dB, sd 0.99,
worst 2.61. A test needing 1.27 dB was never going to be settled on this
material, and that was knowable before the capture.

**§113 is in doubt, and §105 with it.** Both were taken at fixed 5 ms on
transposed material, which is the exact mechanism. §113's material is
unidentified (§111, §120), so this is not a direct refutation — it is the
demonstration that the mechanism exists, is large, and was present in their
method. §113's 1.25× over 55 semitones sits inside what this artefact produces.

### The rule

**A note ladder plays one sample at many rates, so a detector with a fixed
timescale measures a different thing at every rung — and the bias it introduces
varies with note, which is indistinguishable from a note-effect.** Scale the
detector with the playback rate, or measure at one note only.

This is §105's "the analysis window must scale with the value being measured",
one level deeper: the window must scale with **the material's** timescale as
well as the envelope's, and on a sampler those two are decoupled by the keyboard.

**And the procedural error, which is the cheaper lesson.** §112's rectangle test
exists to *qualify* material. It was built into this run as RUN A and then read
as a measurement — so the material was screened after the ladder rather than
before it, and the screening that would have stopped the ladder took four
minutes.

### §121 addendum — the error bar was found second, and what actually found it

VinSamLib read this session as "measuring the method against a question it
cannot answer, and saying so, **before the result is in**", and proposed it to
s3ked as a standing checklist step. **The credit is more than was earned and the
correction changes the rule.**

The ±1 dB was computed **after** the capture, not before. The sequence was: take
the ladder, read the plateau spans, notice that RUN A and RUN B disagreed by
2.5 dB — and only then ask what the method's own reproducibility was. Had the
two runs agreed by luck, a plateau span would have been reported with no error
bar at all and nothing would have prompted one.

**So foresight is not what caught it. Redundancy was.** RUN A (instant attack)
and RUN B (byte 72) reach the *same* target level, so their difference is known
to be zero before either is measured. That makes their disagreement a direct
readout of the method's error, available whether or not anyone thought to ask.

**The rule worth carrying is therefore not "state your uncertainty first"** —
that requires knowing to, which is exactly what fails under the pull of an
interesting result. It is:

> **Build a comparison whose answer you already know into the run itself.** Then
> the method's error is measured as a by-product, and a method too coarse for
> the question announces itself instead of waiting to be asked about.

The no-attack control is the same instrument in the time domain: a rise that
does not exist, measured anyway, so that any gradient it reports is known to be
artefact. **Two knowns carried alongside the unknown**, and between them they
disposed of the whole enquiry — one measured the level error, the other exposed
the timing artefact.

Stating the uncertainty up front is still better than not. But it is the weaker
version, because it depends on the discipline that the result is actively
eroding, and the redundancy version does not.

### §121 addendum 2 — the sibling's null was measured on material immune to the mechanism

mpc2emu supplied the half that cannot be seen from this bench. s3ked swept the
same envelope byte across notes 48/72/96 on the AKAI and got **0.5% across 48
semitones** — against a document of their own citing **941 ms** of note-dependence
in the same quantity, read with a fixed-width detector on transposed material.

The obvious reading is that the AKAI does not have the effect. **It is the wrong
reading, and the reason is the material: their subject was a looped pure tone.**

This artefact needs the sample's *own* amplitude modulation to stretch with
playback rate. A pure tone has none. **So the null does not test the mechanism —
the subject was immune to it.** Any AKAI ladder run on real sampled material is
exposed exactly as ours was, and a reader taking the 0.5% as "this machine
doesn't do that" would generalise from a control that could not have failed.

**This is §110's rule arriving from the other direction.** There, an absence was
worth only as much as the statement of *where* we looked. Here it is worth only
as much as the statement of *what we looked at* — and a clean null on a subject
chosen for its cleanliness is the most persuasive possible way to learn nothing.

**The general form, which is worth more than either result:** a control is only
a control against the specific failure it is capable of exhibiting. A pure tone
is an excellent control for detector linearity and a worthless one for a
material-coupled artefact, and nothing in the number distinguishes those two
uses. **Choosing the cleanest available subject actively removes the thing under
test**, which is the opposite of the instinct it comes from.

### And the detector floor is the same question one scale down

s3ked's remaining open item is a **47 ms floor** at the fastest envelope setting
on that pure tone, note-independent. Note-independence rules out this
mechanism — but our own no-attack control puts a number beside it: at the
fastest setting, with nothing to measure, this rig reports **20–60 ms** at fixed
5 ms smoothing and 16–159 ms rate-scaled. **That is a detector floor, by
construction, since there is no rise there at all.**

Whether theirs is a detector floor or a real envelope minimum is decided the
same way: **change the detector and see whether the floor moves.** A machine's
minimum attack time does not care about the smoothing width; a detector's floor
is roughly proportional to it. One sweep of the analysis parameters over
captures they already hold separates them, with no hardware.

### §121 addendum 3 — the mechanism is carrier leakage, and a pure tone is NOT immune

mpc2emu's rule — *build a comparison whose answer you already know into the
run* — has a free instance in every capture this project takes: **a played
note's pitch is fixed by the note number before anything is measured.** It cost
nothing to run against today's own wavs, and it corrects §121's stated
mechanism and addendum 2's advice to a sibling.

**What it found first.** The preset sounds **one octave below** the note number
— −1198, −1221, −1218, −1209 cents at notes 28/40/52/64, i.e. a consistent
octave with the note-to-note ratios equal-tempered to within 1% (1.974, 2.003,
2.011 for octave steps). So the rate-scaling assumption is confirmed rather than
asserted. **And note 16's fundamental is therefore ~10 Hz** — below the analysis
floor, which is why its ratio came out at 8× rather than 16×: the peak found
there was a harmonic.

**Which makes the real mechanism visible.** A 10 Hz tone measured with a 5 ms
RMS window is measured over **0.05 of a cycle** — the "envelope" is tracking the
waveform, not the envelope. Tested on a synthetic pure tone, constant amplitude,
**no modulation of any kind**:

```
   f0 (Hz)   cycles per 5 ms window   max/min swing of the 5 ms envelope
     10.3            0.052                     20.57 dB
     20.6            0.103                     14.51
     41.2            0.206                      8.32
     82.4            0.412                      1.79
    164.8            0.824                      1.51
    329.6            1.648                      0.67
   1046.5            5.232                      0.26
```

**That is the same ripple-versus-pitch curve the twelve real presets showed, on
material with nothing to modulate.** And with the window scaled to the period —
constant cycles per window — the swing is flat at 1.51 dB across every pitch.

So §121's mechanism was stated one level too specific. It is not that the
sample's own amplitude modulation stretches with playback rate (that is real and
present, but it is not needed). **It is that the detector's window spans a
note-dependent number of carrier cycles, and below about one cycle the carrier
leaks into the envelope and its peaks cross a −3 dB threshold early.** At 10 Hz,
**67% of 5 ms windows sit above the −3 dB line** with no attack in progress at
all.

**The correction to addendum 2, and it is the one that matters for the sibling.**
s3ked's null was measured on a looped pure tone at MIDI note 84 — about
1046 Hz, **5.2 cycles per 5 ms window, 0.26 dB of swing**. Their subject was
immune, and addendum 2 said so, but **for the wrong reason**: not because it was
a pure tone, because it was a HIGH one. A pure tone at 41 Hz shows 8.3 dB of
swing and is fully exposed. Their conclusion survives; the generalisation drawn
from it does not, and "use a clean tone" would have been the wrong lesson to
carry away.

**The rule, in its correct form:**

> **An envelope detector's window must span a fixed number of carrier cycles,
> not a fixed number of milliseconds.** A ladder across notes changes the
> carrier period at every rung, so a fixed window measures a different quantity
> at each — and the bias it introduces varies with note, which is
> indistinguishable from a note-effect.

This is machine-independent and material-independent. It applies to the AKAI,
the K2000 and the MPC exactly as it applies here, and it applies to pitch
detection as much as to envelope detection — which is where VinSamLib had
already routed the weaker version.

**And the free check that found it should be standing practice.** Every capture
this rig makes contains a quantity whose true value is known a priori: the
pitch of the note it played. Checking it costs one FFT, needs no second
measurement to compare against, and validates sample rate, wav header, analysis
scaling and tuning in one number. mpc2emu reports it is what caught a sibling's
hardcoded 44100 against a 48000 rig — a carrier read as 961 Hz where the note
number said 1046.50.

**Two measurements agreeing is much weaker than one measurement matching a value
that was never measured**, and only the second kind is free.

### §121 addendum 4 — the rule used to eliminate, and something survives it

The carrier-cycle rule earns its keep twice on the sibling machines, once
quantitatively and once as an elimination. mpc2emu supplied both.

**It sizes a correction that had been made from first principles.** Their
`ATTAK1` ladder was re-read this morning on the argument that a 5 ms window on a
33 Hz tone is "0.16 of a cycle, so it measured the waveform and not the
envelope" — true, and qualitative. 33 Hz is **0.165 cycles per window**, which
falls between this project's 20.6 Hz (14.5 dB swing) and 41.2 Hz (8.3 dB) rows,
so roughly **11 dB of swing against a −3 dB threshold**. Their old reading ran
17–33% short of the same capture measured with a Hilbert envelope, and an early
threshold crossing is what 11 dB of swing produces. **A synthetic tone put a
number on a correction that had been right and unsized.**

**And it eliminates itself as the explanation for a surviving anomaly.**
s3ked's remaining open item is a 47 ms floor at the fastest envelope setting,
note-independent across notes 48/72/96. Their subject's carrier there:

```
  note 48    131 Hz    0.65 cycles / 5 ms window   mildly exposed
  note 84   1046 Hz    5.23 cycles                 immune
  note 96   2093 Hz   10.47 cycles                 immune
  measured floor       0.0111 / 0.0104 / 0.0108 s  -- flat to 6%
```

**THE FLOOR IS 11 ms, NOT 47 — corrected 2026-09-14 12:15, twenty minutes after
this passage was written.** s3ked withdrew the 47 ms: the same hardcoded 44100
that scaled their times by 8.8% also opened their analysis window at
`int(0.4 x 44100)` samples, which is 0.3675 s at 48000 — **32.5 ms before the
note**, an offset every measured time carried. Re-measured at the true rate with
the window at the note, the floor is 11.1 / 10.4 / 10.8 ms.

**The elimination survives, and now by two independent routes.** The carrier-cycle
argument above is unaffected — the carrier still changes 16x and the floor is
still flat. And s3ked ran a detector-width sweep on the suggestion: **flat to
~2 ms over a hundredfold change in width, in two different detector families**
(Hilbert 0.1-10 ms decimation, and RMS 0.5-10 ms window). Not a detector floor,
not carrier leakage, real.

**What does NOT survive is the analogy this project offered.** 11 ms no longer
sits inside our 20-60 ms no-attack control range, so "it might be the same thing
as your detector floor" is dead — correctly, and it was the weaker half of the
argument. The half that held is the one that used a measurement rather than a
resemblance.

**The carrier changes 16× across that sweep and the floor does not move.** A
carrier-cycle artefact would have to shrink by more than an order of magnitude
over that span. So the 47 ms is **not** this mechanism, and it stands as a real
property of something — the first thing today that has survived elimination
rather than dissolved.

**That is the more valuable use of a rule like this.** Most of today it has been
demolishing results. Here it does the other job: it removes a candidate
explanation and leaves an anomaly with fewer places to hide. A mechanism that
can only ever explain things away is not much of a mechanism; one that can be
ruled *out* by a measurement is.

### The a-priori pitch check becomes a required row

mpc2emu's argument, and it is `row_schema_required`'s exactly: **the cost of a
missing check is never visible when you decide not to run it.** So it stops
being a habit.

Every capture contains a quantity whose true value is fixed before anything is
measured — the pitch of the note played. One FFT validates sample rate, wav
header, analysis scaling and tuning together, against a value nobody measured.
It caught a sibling's hardcoded 44100 against a 48000 rig (carrier read as
961 Hz where the note number said 1046.50), and here it caught an octave nobody
was looking for, which changed what note 16's rate ratio meant.

Added to the ladder's `row_schema_required` as `carrier_hz_measured` and
`carrier_hz_expected_from_note`, with `cycles_per_smoothing_window` beside them,
since that last number is what says whether the row is trustworthy at all.

### §121 addendum 5 — the check that refuses, and it refuses today's own ladder

s3ked, having read the pure-tone table: *"Mine would have read 0.165 and I would
still have taken the measurement, because nothing told me what the number
meant."* **A recorded number with no verdict attached is a number that gets
recorded and ignored** — §108's "a check that certifies", one step earlier.

So `tools/carrier_check.py` does not report, it **refuses**, and the threshold
carries the swing it implies rather than being a bare constant:

```
  cycles/window   0.05   0.10   0.165   0.25   0.33   0.41   0.50   0.66   1.0   5.2
  swing (dB)     21.20  14.81  10.34    6.64   3.93   1.87   0.04   1.79  0.01  0.00

  < 0.41   REFUSE    a pure tone swings > 3 dB; a -3 dB threshold can fire early
  < 2.0    WARN      swing is NON-MONOTONE here -- 0.50 gives 0.04 dB and 0.66
                     gives 1.79 dB, because it depends on the fractional part of
                     window/period, not on how many cycles fit. So "more than
                     half a cycle" is not a safe rule; require whole ones.
  >= 2.0   OK
```

**Pointed at this session's own captures it refuses them**: note 16 at 0.051
cycles REFUSE, note 40 at 0.204 REFUSE, note 64 at 0.820 WARN. **Every rung of
today's ladder would have been stopped before it was recorded**, including the
one whose 1.655x ratio took three analyses and a synthetic control to dismantle.

It carries the a-priori pitch check in the same pass, with one detail that cost
something here: the FFT floor is 8 Hz, not 20. **A preset tuned an octave below
its note numbers puts its fundamental under a naive 20 Hz floor, and the peak
then found is a harmonic** — which reads as a clean measurement of the wrong
thing. That is how note 16's rate ratio first came out 8x instead of 16x.

### Why the a-priori check is different in kind

s3ked's account of their own day is the argument: *every check I ran compared
one of my measurements against another, so a common-mode error in my analysis
was invisible to all of them — nine eliminations, five sections, two peer
projects.* What broke it was the probe note's own frequency, which had been in
the file the whole time, recorded under a heading about something else.

**Two measurements agreeing is much weaker than one measurement matching a value
that was never measured.** Agreement between measurements shares every
assumption the analysis makes; a note number shares none of them. And only the
second kind is free.

### §121 addendum 6 — the tool's threshold was on the wrong quantity, and the structure is half-integer not quarter

s3ked reproduced the pure-tone curve independently — their 0.165 row agrees
with this project's to **0.02 dB** (10.32 against 10.34), two separate
syntheses of the number that governs their own `ATTAK1` ladder — and used it to
find a real defect in `tools/carrier_check.py` as first shipped.

**A threshold on cycles-per-window cannot work.** Cleanliness is a property of
the *fractional part*, so a cut at 0.41 ranks 0.41 (1.87 dB) as worse than 0.66
(1.79 dB) when 0.66 is the worse ratio. **Their fix is correct and is adopted:
synthesise a tone at the measured `f0`, run the actual window over it, and
threshold on the swing that comes back.** Three lines, no table, no constant that
has to be right, and it stays correct when someone changes the smoothing width.
**The cycle count is worth recording and is the wrong thing to decide on.**

The tool now measures. Same verdicts on this session's ladder — note 16 REFUSE
at 20.62 dB, note 40 REFUSE at 8.43 dB, note 64 WARN at 1.54 dB — but for the
quantity that matters rather than for a proxy.

### And a disagreement, stated before it is reconciled

s3ked's table reports the swing collapsing at **quarter-cycle** ratios — 0.25 and
0.75 both 0.04 dB. **This project measures 6.51 dB at 0.25 and 1.88 dB at 0.75.**
We agree at 0.50 and 1.00.

**The arithmetic decides it, and the quarter-cycle reading is wrong.** The mean
of `sin²` over a window `[t0, t0+T]` is

```
  1/2  -  sin(2*pi*f*(2*t0+T)) * sin(2*pi*f*T) / (4*pi*f*T)
```

which vanishes **for all `t0`** if and only if `sin(2*pi*f*T) = 0`, i.e.
`f*T = k/2`. **Cancellation is exact at HALF-INTEGER cycles per window — 0.5,
1.0, 1.5, 2.0 — and at quarter-cycle ratios that term is at its maximum**, so
the result depends on where the window starts. Successive tiled windows step
their start by `T`, so they sample different phases and a real swing appears.
Swept over start phase, 0.25 gives 6.51 dB at every phase, not only some.

So the structure is half-integer, and the practical rule they drew from it —
**many whole cycles with margin**, not "enough" and not "more than half" — is
right, and right for a reason one step different from the one recorded. Sent
back, because their checklist carries the quarter-cycle version.

**Worth noting what made this findable:** an independent synthesis agreeing to
0.02 dB on the row that mattered, and disagreeing by 6.5 dB on a row neither of
us needed. **The agreement is what made the disagreement worth chasing** — two
implementations that agreed everywhere would have proved only that we had
written the same code twice.

## §122 — The firmware route is open after all, and it settles 0.0565 vs 0.0581 (2026-09-14)

§116 concluded that the EOS OS images are packed and the unpacker is not in them,
and inferred the decompressor lives in the sampler's boot ROM. **The first half
stands. The inference was wrong, and Jan's `EOS/` directory is why.**

### The boot loader is on disk, and it is plaintext

`EMU_FLASHPREP_OMNIFLOP.IMG` is not an OS image. It is **"Ultra FLASH Prep
v1.0"**, and the discriminator of §118 calls it instantly:

```
                      entropy   256-byte windows < 6.0
  EOS 4.70 OS image     7.19             1.6%      packed
  FLASH Prep image      5.05            99.4%      PLAINTEXT 68k
```

It contains two complete programs, each with its own runtime copy: a FLASH Prep
utility at file 0, and the **EOS Primary Loader, "Version 01f05"**, from file
`0x15c34`. Strings: `Erasing boot FLASH...`, `Searching for OS...`,
`Download OS from MIDI?`, `Burn to flash?`, `Verifying csum: 0x%08.8x`, the whole
floppy error table, and the 68k exception handlers.

**The load bias is exactly 0x15c34**, confirmed rather than fitted: `pea 0x184bc`
maps to file `0x2e0f0`, which is `"Please insert disk %d."` on the nose.

**And the target is 68020-class, not 68000** — `DIVU.L`, `EXTB.L`, `TST.L An`
are present, and undecodable words fall from 4504 to 3667 when the ISA is
corrected. k2kremote warned that a later-ISA decode accepts what the chip cannot
run; this is the inverse and equally bad, since a 68000 decode desynchronises on
every 68020 instruction.

### The container's magic carries a compression flag in its low nibble

```
  0x76543210   plain     the loader writes the label "none"
  0x76543211   packed    the loader writes the label "Lz77"
```

Both constants appear in the loader as an adjacent compare pair, and the packed
branch stores the bytes `4C 7A 37 37 0A`. **The scheme is E-mu's own and they
call it Lz77.**

### But literals are entropy-coded, which is why nothing decoded it

A crib test settles the shape without reversing anything. The OS shares its
runtime with the loader, so the decompressed image must contain the same
strings; under LZ77 a string's *first* occurrence is emitted as literal bytes, so
those bytes must survive in the compressed stream.

```
  crib                        in the plain loader   in the packed 4.70 payload
  "Fatal: Bus Address error"        found                   absent
  "0123456789abcdef"                found                   absent
  "Floppy CRC Error"                found                   absent
  ... and absent at gaps of 1, 2 and 3 bytes per character
```

**So literals are not bytes.** "Lz77" is LZ77 **with entropy-coded literals**,
which is why 36 byte- and bit-aligned LZSS variants, LZW at four settings, and
every standard library failed, and why the payload entropy is 7.19 rather than
the ~6.5 a byte-literal LZ77 of 68k code would give.

**The decompressor was not found in the FLASH Prep image.** Searched, at both
68000 and 68020: pointer-subtract match copies (0 of 52 byte-copy loops have
one), ring-buffer indexed copies (12 found, all strcmp/checksum/search), window
masks (the 4095/8191/2047 constants are all hardware registers or IEEE-754
exponent masks), and canonical-Huffman decode loops. **That is a statement about
the idioms searched, not a proof of absence** (§110).

### The 4.62 OS image is NOT packed, and that is the way in

`462prep.zip` uses an **older container** — magic `0x12345678`, 24-byte ASCII
banner, length in 512-byte sectors at +0x1c, checksum at +0x20 — and it is
**uncompressed**:

```
  EOS 4.62 payload   1,244,160 bytes   entropy 6.34   42% of 4 kB windows < 6.0
  strings: "Scanning AKAI device", "Akai S1000 Volume", "S3000 preset",
           "Empty file", and the OS's own vocabulary --
           Preset x76, Sample x82, Voice x30, Filter x14, Envelope x6
```

It disassembles as clean 68020 with consistent absolute addressing. **This is a
plaintext EOS operating system**, and it is the substrate mpc2emu's scanner was
built for and never had.

### The table, and what it settles

A vectorised log-linear run search (control: 400 kB of noise, no hit at any
length) finds a **128-entry u16 big-endian table at payload offset `0x0edd56`**,
descending 65535 → 4, a 16384:1 span. 128 entries is one per MIDI parameter byte.

```
  byte range    log-slope per entry      r2
      0-128           0.06224          0.98950
       0-20           0.12824          0.86542
      20-60           0.05964          0.99941
     60-100           0.05638          0.99994   <- the range ours was fitted over
    100-128           0.07775          0.98815
```

**Our two candidate laws, and the firmware's answer:**

```
  ENV_RATE_SWEEP_K   0.0565   fitted from captures over bytes 60..100
  ENV_RATE_K         0.0581   the time-alone law
  firmware, 60..100  0.05638
                              -> -0.2% from 0.0565,  -3.0% from 0.0581
```

**0.0565 is the one. The 2.8% disagreement that "a table would settle and we
could not" is settled, and it went the way the sweep-fitted constant said.**

**And the table is not a single exponential.** r² is 0.99994 over 60–100 and
0.9895 over the whole range; both ends are steeper. **Our law is right exactly
where it was fitted and wrong outside it** — which is a firmware-side account of
§105's "not to be read below ~2 s without a re-take", arrived at independently
of the measurement that prompted that warning.

### Three caveats, all load-bearing

**This is 4.62 and the bench runs 4.70.** The 4.70 image is packed and unreadable,
so this is a cross-check against a neighbouring version, not a reading of the
firmware we are measuring.

**The table's identity is inferred from shape, not proven** — but "inferred from
shape" is a hedge where a number is available, and s3ked was right to say so.
Counted rather than hedged:

```
  monotone 100-entry runs in the image (u16/u32, BE/LE, every alignment)   5,689
  of those, within +-5% of the measured slope                                 42
  distinct tables those 42 windows belong to                                   1
```

**All 42 hits are overlapping windows of a single 128-entry table, which appears
twice in the image** — byte-identical copies 261,396 bytes apart, at `0x0edd56`
and `0x12da6a`. Half the hits were at the second copy, which on first inspection
looked like a rival candidate and is the same table.

**So: one distinct candidate in 5,689 monotone runs, at a tolerance twenty-five
times looser than the match actually achieved.** A log-slope test over a long
window is far more selective than "we matched a shape" sounds: monotone runs are
common and almost none of them grow at a specified rate.

That is a stronger claim than the hedge it replaces, and it is still not proof.
E-mu publish no anchors, so nothing here matches a known value the way s3ked's
four Akai integers did. mpc2emu's caveat remains the operative one: **a hit is a
candidate, not a table** — confirm by changing the parameter on hardware and
predicting an entry.

**The version caveat is the real exposure, not the method caveat.** 4.62 against
the 4.70 on the bench. s3ked offers a mildly encouraging precedent — the S1000
OS v4.40 and S3000XL OS v2.0 tables are byte-identical at all four anchors,
across two machine generations — so envelope tables do seem to survive
revisions. Mildly: two data points, a different manufacturer.

**A table says what the machine intends; the captures say what left the
converters.** They agree here to 0.2%, which is the outcome that needs the least
explaining and therefore the most care. Recorded in
`docs/data/eos462_env_rate_table_candidate.json` with its provenance and every
caveat attached to the data rather than to the prose.

### A second table, deliberately not interpreted

A 128-entry saturating curve sits immediately after it at `0x0ede58`: 38% of full
scale at 10% of index, 97% at 50%, strongly concave. It is tempting to read that
against §113's convex attack. **It is not being read that way**, because nothing
identifies what it is — a velocity curve, a volume law, a pan law and an envelope
shape would all look like this, and the day already contains one fork built on an
effect that turned out not to exist.

### §122 addendum — the corpus weights the defect, and corroborates the identification sideways

§122's second finding — our law is right where it was fitted and wrong outside
it — is a statement about the table. **What it costs depends on where real
presets actually sit, and that number exists only in mpc2emu's corpus.** 380
banks, 285,396 amp-envelope rate bytes:

```
  byte 0 ("instant", not on the curve at all)       191,464   67.1%

  of the 93,932 that DO go through the law:
    1-19     firmware slope 0.128  vs ours 0.0565     1,571    1.7%
    20-59    firmware 0.0596                         84,860   90.3%
    60-100   firmware 0.0564   <- the fitted range     7,421    7.9%
    101-127  firmware 0.0778                              77    0.1%
```

**The headline is right and the consequence is small.** Our law is fitted over a
band holding 7.9% of real usage — but the band holding 90% differs in slope by
only 5.5%, and integrating the piecewise table against our single exponential:

```
  byte 46 (commonest in the corpus)   firmware/ours  0.959
  byte 44 (second commonest)                         0.953
  byte 20                                            0.884
  byte 12                                            0.499
  byte  5                                            0.302
  byte 125                                           1.661
```

**Where the corpus lives we are 4–5% out; where we are out by 2–3x, almost
nothing lives.** So it is a real defect that does not force a writer change, and
if one is made it should be **piecewise**, not a refit — a refit would trade a 4%
error over 90% of the corpus for a better fit over 8% of it.

### A fourth caveat, and it changes where the hardware check should point

mpc2emu's, and it is the one this project would not have thought of: **aim the
confirmation at bytes 20–59, not at the fitted range.** That is where 90% of real
presets sit and where nobody has measured — the fitted range is where we already
know the answer, so confirming there tests the least informative part of the
curve. §115's rule, arriving as a choice of where to point an instrument rather
than as a choice of what to test hardest.

### And the corpus corroborates the identification from a direction of its own

The table descends from 65535 at index 0 to 4 at index 127, so index 0 is the
largest increment — the fastest envelope, i.e. **instant**. The corpus says
**67.1% of all rate bytes are byte 0**, which is exactly what a value meaning
"instant" would attract.

That is weak on its own and it is *independent*: it comes from what preset
authors chose, not from firmware bytes or from our captures. Nothing about a
geometric run's slope predicts that its first entry should be the single
commonest value in a corpus of 285,396 — and it is the kind of agreement the
shape test cannot manufacture.

**Which is also why it earns the sentence it prompted.** Agreement at 0.2%
between a firmware table and a fitted law is the outcome needing the least
explaining and therefore the most care: two of today's errors survived precisely
because agreement went unexamined — a law fitted to a detector reproducing that
detector (§121), and a cross-check whose 11% was recorded as agreement (§119).

### §122 addendum 2 — three strands, and what each one can and cannot say

s3ked's framing on closing, and it is the day's epistemics stated cleanly enough
to keep:

```
  the firmware  says what the machine INTENDS
  the captures  say what LEFT THE CONVERTERS
  the corpus    says what the parameter is FOR
```

**They are not interchangeable, and the third cannot confirm a slope — it can
confirm you have found the right table.** The corpus's 67.1% at byte 0 against a
table whose index 0 is its largest value is worth exactly that much: not evidence
about the rate law, decisive-ish evidence about identity, and independent of both
other strands because it comes from what preset authors chose.

**A third strand sharing no assumptions with the other two** is what this whole
day kept arriving at from different directions — the a-priori pitch check against
a note number, the no-attack control against a rise that does not exist, two runs
that must differ by zero. It is also the strand hardest to arrange, and here it
came the only way it could: from somebody else's data.

### An open item the duplicate creates

s3ked's table appears once; ours appears twice, byte-identically, 261,396 bytes
apart. **The duplicate is the more awkward position, not the more redundant
one.** A unique table makes the consumer set closed by construction — whatever
references it is all there is. Two identical copies means two sites to reconcile,
and **nothing in the image says which one the envelope code actually reaches.**

That matters if the copies ever diverge between versions: reading the wrong one
would give a table that is real, correct-looking, and not the one in use. Not
resolvable without following the references, and not needed for §122's result —
recorded so that nobody later assumes the redundancy is reassuring.

### §122 addendum 3 — what changed between 4.62 and 4.70, and a capability it implies

§122's remaining exposure is that the table is read from **4.62** and the bench
runs **4.70**. Jan supplies the only kind of evidence that bears on it directly:
what the two versions differ by.

> 4.70 added **FAT32 support** and **dynamic filters** — on 4.62 a filter
> parameter change took effect only on the next note; on 4.70 it is audible on a
> note already held. Envelopes should not have changed. *(Jan, from the
> community; he flagged the sourcing himself.)*

**This is a fourth strand and it answers a question none of the other three
can.** Firmware says what the machine intends, captures say what left the
converters, the corpus says what the parameter is for — **none of them can say
what changed between two versions.** Only documentation, or someone who has
followed the machine, can.

**What could be checked, was.** The plaintext 4.62 image contains no `FAT32`,
`FAT16` or `FAT12` strings (`FAT` appears 5 times). Consistent, and weak on its
own: FAT type is normally determined from BPB fields rather than named. The
`E-mu EOS 470 Updater` archive turns out to hold only the four binaries already
in hand — **no release notes**, so no documentary confirmation is available from
the files.

**The substantive argument is stronger than its sourcing.** Both named changes
sit in subsystems adjacent to but distinct from the envelope generator: FAT32 is
the filesystem layer, dynamic filters are the filter-coefficient update path.
Neither has any reason to touch an envelope rate table. That is a structural
argument rather than a recollection, and it is what actually carries the weight.

**So the version caveat moves from "unknown" to "probably fine, and here is how
to settle it"**, without being removed: community recollection is evidence, not
verification, and this is precisely the distinction the day has been about.
mpc2emu's aim point stands — confirm at bytes **20–59**, where 90% of real
presets sit.

### And the dynamic-filter change is a capability, not just a version note

On 4.70 a filter parameter change is audible on a **held** note. That is
directly useful here, and it is new relative to everything in these notes.

**Every filter measurement this project has taken re-triggers the note**, so each
one carries the amplitude envelope's attack and the filter envelope's own sweep
on top of whatever the parameter change did. §113's static-vs-static work went to
some trouble to flatten envelopes precisely to get around that.

A held-note parameter change removes the confound at source: **one note, one
sample, one envelope state, and the only thing that moves is the parameter.**
That is the cleanest available form of the pole-count-versus-resting-corner
question left open in the bench notes, which has been stuck on needing "built
static material with both corners known and equal".

Worth testing before relying on: §34 established that an editor-protocol write
does not reach the sounding preset's *display*, and that voice-level parameters
(id 39) do reach the audio while preset-level ones (`E4_PRESET_VOLUME`) do not.
Whether a filter parameter reaches a **sounding voice** on 4.70 is a one-note
experiment and has not been run.

### §122 addendum 4 — E-MU's own 4.7 addendum settles the version caveat, and corrects half the premise

Jan supplied the primary source: **"EOS 4.7 Operation Manual Addendum", E-MU PN
FI12529 Rev. A**. It is E-MU's own enumeration of what 4.7 changed, and it
answers §122's remaining exposure directly.

**What 4.7 actually added**, by its own table of contents:

```
  To Install EOS version 4.7
  Number-naming convention specification
  EOS FAT                     -- "The major feature in this upgrade ... based on
                                 the FAT32 disk file system"
  Applications                -- renaming banks on a PC, .wav/.aiff transfer
  Miscellaneous Bug Fixes     -- SEVEN items, ALL plug-in / RFX / effects /
                                 Import Wave / MM List
  plus: the RFX Compressor plug-in, and a changed plug-in structure
```

**The sound-generation vocabulary was enumerated BEFORE searching** — thirteen
terms, fixed in one list and not narrowed afterwards. That matters, and mpc2emu
is right that a reader cannot tell the two cases apart from the result: a list
fixed in advance and wide is strong evidence; three words chosen after reading
are worth almost nothing, and both print as "zero occurrences".

```
  filter 0   envelope 0   attack 0   decay 0    release 0   voice 0   oscillat 0
  pitch  0   LFO      0   modulat 0  sound   0  tuning  0
  cord   1   <- "Plug-in MIDI Mod is now set to default when a Cord Destination
                 is changed" -- a modulation cord inside an RFX plug-in bug fix
```

**Twelve of thirteen zero; the thirteenth is in a plug-in line.** Every listed
change is filesystem, plug-in or effects.

**And a correction to this project's own first report of it.** The message that
carried this result to Jan listed the twelve zeros and **silently dropped
`cord`** — the one term that returned a hit. The hit is innocuous and the
conclusion is unchanged, but the reporting was exactly the post-hoc pruning being
argued against, committed in the act of arguing against it and caught by
mpc2emu asking whether the list was fixed in advance rather than by any care of
ours. **A fixed list reported selectively is a chosen list**, and nothing in the
output says which one it was.

**So the version caveat is as answered as a document can answer it.** That is far
stronger than the structural argument in addendum 3, because it is the
manufacturer enumerating the change rather than us reasoning about which
subsystem a feature lives in.

**It is not proof.** A manual addendum documents *user-visible* changes and is
not a changelog; absence from it does not establish absence in code, and the
confirmation mpc2emu asked for — hardware, bytes 20–59 — is still the thing that
would settle it. But the prior has moved a long way.

### And it corrects half of the premise it was offered to support

The recollection that prompted this was "FAT32 **and dynamic filters** — on 4.62
a filter parameter change took effect only on the next note; on 4.70 it is
audible on a held note."

**FAT32 is confirmed by E-MU. The dynamic-filter change is not in this document
at all** — not as a feature, not as a bug fix, not as a mention. So it belongs to
a different version, or it is a community misattribution. **Addendum 3's
"capability, not just a version note" therefore rests on nothing** and is
withdrawn as stated: a held-note filter experiment may still work on 4.70, but
there is no documented basis for expecting it to, and it must be established by
the one-note test rather than assumed.

**Worth naming the shape.** The evidence offered to close a caveat closed it, and
disconfirmed the other half of the same sentence. Taking the supporting half and
not checking the rest would have left a withdrawn capability sitting in the notes
as a planned experiment — and it was the more interesting half, which is exactly
why it needed checking first.

### A free confirmation of §122's loader identification

The addendum's install procedure quotes the machine's own prompts:

```
  "Update FLASH from floppy?"   "Loading OS..."   "Burn to flash?"
```

**All three are strings this project extracted from
`EMU_FLASHPREP_OMNIFLOP.IMG`.** So E-MU's documentation independently confirms
that image is the boot loader — an identification that had rested entirely on
our own disassembly, now corroborated by a source that shares none of its
assumptions. The third strand again, arriving free.

### §122 addendum 5 — the document is for a version that was never officially released, and that weakens the argument this project leaned on

Jan, on the 4.7 addendum:

> The dynamic filter **is** there — rather test it. When that addendum was
> released, E-MU was already on the way out as a company (being bought by
> Creative Labs). **4.7 was actually never officially released.**

**This does not merely restore the filter claim. It undermines the reasoning
addendum 4 used, including the half that went our way.**

Addendum 4 made *two* arguments from the same premise — that the document's
silence is informative:

1. the dynamic-filter change is absent, therefore withdraw it;
2. sound-generation vocabulary is absent across thirteen enumerated terms,
   therefore envelopes are very likely unchanged 4.62 → 4.70.

**Jan's direct observation of the behaviour is a counterexample to (1), and a
counterexample to (1) is a counterexample to the premise.** A document that omits
a real, audible change to the filter path is a document whose silence about the
envelope path proves much less than addendum 4 claimed. **And an addendum for a
version that was never officially released, written while the company was being
absorbed, is exactly the kind of document expected to be incomplete** — which is
a reason to have discounted its silence *before* a counterexample arrived, not
after.

**What survives and what does not:**

- **The document's positive content stands.** FAT32 as the major feature, the
  RFX Compressor, the plug-in restructure, the seven bug fixes. Documents do not
  invent features, and a manufacturer naming its own headline change is reliable.
- **The verbatim loader prompts stand**, and the FLASHPREP identification with
  them — that is positive content too.
- **The absence argument is withdrawn in both directions.** The
  envelopes-unchanged conclusion goes back to resting on addendum 3's
  *structural* argument (FAT32 is the filesystem layer, plug-ins are effects;
  neither has reason to touch an envelope rate table) plus the community
  recollection — which is where it was before the PDF, and weaker than addendum 4
  said.
- **The dynamic-filter capability is restored as a claim to test**, not
  withdrawn and not assumed.

**The generalisable part, and it is uncomfortable because the error was
asymmetric.** The document confirmed something we wanted (the version caveat) and
disconfirmed something we wanted (the held-note capability). The disconfirmation
was accepted immediately and written up as a virtue; the confirmation was not
examined with the same suspicion, and it was the one that needed it, because a
source's silence is only as good as its completeness — which nobody had asked
about. **"Zero occurrences of thirteen terms" is a measurement of the document,
not of the firmware**, and the distinction was available from the start.

## §123 — The 4.70 payload is not compressed at all, and the 4.62 plaintext is what proves it (2026-09-14)

Jan's question — *"knowing the changes from 4.62 to 4.7 are not too fundamental,
wouldn't that help us crack the 4.7 image? The envelope tables, LFOs etc have to
be in there"* — turns out to be the right lever, and it does something better
than help decode the image. **It shows the image was never compressed.**

### The size argument

```
  4.62 PLAIN                     1,244,160 bytes
  4.61 "packed"                  1,262,014 bytes   +1.4% vs the PLAIN 4.62
  4.70 "packed"                  1,374,037 bytes
  what zlib -9 achieves on the 4.62 plaintext:  532,404 bytes  (2.34:1)
```

A real LZ77+Huffman on this content gives **2.34:1**. If 4.61 were that, it would
hold 2.95 MB of OS — against 4.62's 1.24 MB, one point release away. **A packed
image that is 1.4% LARGER than the neighbouring plain one is not a compression of
comparable content.**

### The bit-density argument, which settles it

Compression drives bit density to 0.5 — it must, or there is redundancy left.
XOR/stream encryption does the same, since a keystream is balanced.

```
                          bit density   entropy   max entropy AT that density
  4.62 plaintext OS          0.3396      6.335        7.396    (85.7% of it)
  4.70 "packed" payload      0.3358      7.275        7.366    (98.8%)
  4.61 "packed" payload      0.3359      7.270        7.367    (98.7%)
  zlib of the plaintext      0.5144      7.993        7.995    (100.0%)
```

**The packed payloads sit at the plaintext's own bit density — 0.336 against
0.340 — and at ~98.8% of the maximum entropy available at that density.**

That is not compression and not XOR encryption. Both would move the density to
0.5, and zlib demonstrably does. **Bit count conserved, bit positions scrambled
so the bits read as independent: that is a bit PERMUTATION.**

### What this explains, retrospectively

- **Why 36 byte-aligned LZSS variants, bit-aligned LZSS, LZW at four settings,
  zlib/deflate/gzip/bz2/lzma and a canonical-Huffman search all failed** (§116,
  §122). They were looking for a decoder for a code that was never applied.
- **Why the crib test found nothing at any gap** (§122). A permutation scatters a
  string's bits across the image; no gap size recovers them.
- **Why no decompressor was found in the Primary Loader** (§122). There is none
  to find. The inverse of a bit permutation looks like data-line or bit-order
  remapping — a few mask-and-shift operations on words during the flash path,
  which matches no LZ idiom and is exactly what our searches were blind to.
- **And the "Lz77" label is now doubtful.** It was read from five bytes the
  loader writes on the packed branch (`4C 7A 37 37 0A`). The bytes are certain;
  that they mean a compression scheme is an inference, and the measurement says
  no compression is present. Either the label is for a format variant not used
  here, or those five bytes are something else.

### What it does NOT establish

Which permutation. Simple families are already excluded: de-interleaving the
byte stream 2/3/4/8 ways leaves entropy at 7.27; 8x8, 16- and 32-byte bit
transposition *raises* it to 7.40; bit-stream de-interleave at strides 2–32
across block sizes 64–8192 produces no crib and no entropy drop. **The
permutation is not one of the obvious ones, and it may be long-range.**

### The method point, which is the transferable part

The 4.62 plaintext is not useful here as a *crib* — no crib survives. It is
useful as a **calibration of what the plaintext's statistics are**, and that is
what made a negative decidable. Bit density is a property of the content that a
transform either preserves or destroys, and knowing the content's true value
turned "high entropy, therefore probably compressed" — an inference this project
carried all day from §116 — into a measurement that says otherwise.

**§116's entropy reasoning was not wrong so much as under-determined.** 7.19
bits/byte is consistent with compression, with encryption, and with a bit
permutation, and nothing in §116 distinguished them because there was nothing to
compare against. The discriminator needed a known plaintext of the same content,
and Jan supplied the route to one.

### §123 addendum — "bit permutation" was stated too strongly, and one alternative fits better

§123 concluded the payload is a **bit permutation** because its bit density
matches the plaintext's. Two checks since say that conclusion outran its
evidence, and it is corrected here rather than quietly amended.

**A within-block permutation is excluded at every block size tested.** If the
permutation acted inside blocks of B bytes, each block's bit count would be
conserved and the payload's block-to-block density spread would match the
plaintext's. It does not — and it does not collapse to the iid reference either:

```
   B       4.62 plaintext     4.70 payload     iid at the payload's density
      8    2.717 +- 1.091    2.686 +- 0.550        +- 1.336
    256    2.717 +- 0.760    2.686 +- 0.212        +- 0.236
  16384    2.741 +- 0.391    2.688 +- 0.101        +- 0.030
```

The payload sits **between** the two everywhere: far more uniform than the
plaintext, but with real long-range density variation the iid reference does not
have (0.101 against 0.030 at 16 kB). So the transform mixes over long ranges and
does not conserve block-level structure. A global permutation is consistent with
that; it is no longer the *only* thing consistent with it.

**And a better candidate has appeared: LZ77 bit-packed into fixed-width fields
with no entropy coding.** Offsets and lengths are small numbers, so their high
bits are mostly zero — which produces exactly what is measured: density well
below 0.5, high per-byte entropy from the bit-packing misalignment, and residual
long-range variation where the data matches well or badly. **A 1990s in-house
coder is far more likely to be that than to be a bit-scrambler**, and it is what
the name on the tin says.

**Which also weakens §123's size argument**, and that should be said plainly. It
assumed the 4.62 prep image is content-comparable to 4.61 and 4.70. That is
unestablished: the 4.7 addendum states RFX plug-ins ship *with the OS*, so the
full images may carry plug-in binaries the prep disk does not, and the size
difference would then be content rather than an absence of compression.

**What survives, and it is still worth having:**

- **The payload is not a well-formed entropy-coded stream.** Bit density 0.336
  against zlib's 0.514 on the same content. Whatever it is, it leaves
  substantial redundancy, which rules out the modern LZ+Huffman/arithmetic
  family that most of §116's sweep assumed.
- **That is why the earlier sweeps failed in the direction they did**, and it
  narrows the target rather than identifying it.

**What does not survive: the claim that no compression is present.** It is not
established, and §123 asserted it.

**The error is the day's own, one more time.** A measurement that could not
distinguish three hypotheses was reported as having picked one — the same
under-determination §123 had just diagnosed in §116, committed in the paragraph
that diagnosed it. The check that caught it was available before the claim was
made and took two minutes.

## §124 — Filter modulation reaches a SOUNDING voice, but only by the modulation path (2026-09-14, live)

Jan set up cords on P009 — **cord 9: MIDI F (CC 26) -> FilFreq, +100%; cord 10:
MIDI G (CC 27) -> FilRes, +100%** — and reported the behaviour works from a
controller. Measured, with the control in the design:

```
  windows at CC   0     32     64     96    127
  sweep (CCs sent)   354.1  395.2  626.6  628.1  639.7 Hz   centroid
  control A          351.9  352.2  350.7  349.5  351.1
  control B          353.5  356.8  349.1  350.3  358.9

  >1.5 kHz energy fraction, sweep: 0.0075 -> 0.0316  (4.2x)

  change within the held note: +285.6 Hz against 5.4 Hz worst-case control -- 53x
```

**The filter moves on a note already sounding. Jan's claim is confirmed and this
project's withdrawal of it (§122 addendum 4) was wrong.**

### Two mechanisms, and only one of them reaches the voice

Both were measured on the same bench within twenty minutes, and they disagree:

```
  editor-protocol write, E4_VOICE_FMORPH (id 83), mid-note
      -8.9 Hz against a 7.1 Hz control      -> NO effect on the sounding voice
      (and the parameter read back as 255: the write landed, in the buffer)

  MIDI CC 26 through a modulation cord, mid-note
      +285.6 Hz against a 5.4 Hz control    -> the voice follows it
```

**So "does a parameter change reach a sounding voice" has no single answer — it
depends on which path the change arrives by.** §34 established that an
editor-protocol edit goes to a buffer the panel does not reflect, and that
voice-level parameters (id 39) reach the audio while preset-level ones do not.
This adds the distinction that matters for experiments: **an editor write reaches
the next note; a modulation cord reaches the current one.**

**And it is why the first test returned a clean, correct, misleading negative.**
The measurement was sound, the control was right, the conclusion — "no effect
beyond drift" — was true of what was tested and false of the question being
asked. Nothing in that result said the mechanism had been missed; it took Jan
naming the cords.

### What this unsticks

**Every filter measurement in this project has re-triggered the note**, so each
carries the amplitude envelope's attack and the filter envelope's sweep on top of
whatever the parameter did — three things moving, one of them the subject.
§113's static-vs-static work flattened envelopes specifically to get around that.

A held-note CC change removes it at source: **one note, one sample, one envelope
state, and the only thing that moves is the parameter.** That is a cleaner
instrument than the parked pole-count-versus-resting-corner question was waiting
for, and it does not need the "built static material with both corners known and
equal" that has blocked it.

**Worth recording how it arrived**: not because the rig improved and not because
better material was found, but because a withdrawn claim was reinstated by
someone who had heard the machine do it. The instrument was available all along
and the notes said it was not.

## §125 — The first direct pole-count measurement on the E4XT: FTYPE 0 is 2 poles (2026-09-14, live)

Jan merged the §69 calibration bank (flat looped white noise) and the filter
slope became measurable for the first time. **The result is solid for one filter
type and not obtained for the other two, and the reason is a protocol problem
rather than a measurement one.**

### Subject and method

P013 voice 0: sample 11, origkey 24, **voice key range 24-84**, amp and filter
envelopes both flat rectangles (rate 0 / level 100 on every segment), Q 0, note
24 so nothing is resampled. `H(f) = S(f) / S_open(f)`, the open capture taken at
the same filter type, which divides out the noise draw, the sampler's
reconstruction roll-off and the capture chain together (§69's method).

The skirt is fitted where `H` lies between **-6 and -35 dB of the passband** —
that selects the roll-off itself and excludes both passband and noise floor
without an SNR constant that has to be right. An earlier gate keyed to the
reference's own top-octave roll-off rejected **every point at every corner**, and
printed `nan` rather than failing.

### The result

```
  FTYPE 0, nominal "2-Pole Lowpass"
    FMORPH  50   corner  287.1 Hz   skirt -12.01 dB/oct   implied poles 2.00
    FMORPH  70   corner  398.4 Hz   skirt -12.18            2.03
    FMORPH  90   corner  562.5 Hz   skirt -12.19            2.03
    FMORPH 110   corner  761.7 Hz   skirt -11.98            2.00
```

**Four corners spanning 1.4 octaves, slope constant to 1.5%.** A pole count must
be corner-independent and this one is — which is the property that makes it a
pole count rather than a number that happens to come out near 12.

**RETRACTED: it settles no naming ambiguity, and there was none to settle.**

This section originally claimed the measurement showed `FILTER_TYPE_NAMES`
right and §2's table wrong. **Both halves were mistakes of this session.**

**There is no conflict between the two tables — they are different encodings.**
§2's is the **E4B file byte** (0x00, 0x02, 0x08, 0x09, 0x10, 0x11, 0x12, 0x20…,
grouped by high nibble), confirmed 16 of 16 against the machine's own display.
`FILTER_TYPE_NAMES` is the **SysEx parameter id** (0, 1, 2, 3…, sequential).
A file byte and a parameter id need not share a numbering, and here they do not.
mpc2emu's `_XPM_FILTER_TYPE` writes the file bytes — `0x00` 4-Pole, `0x01`
2-Pole, `0x02` 6-Pole — i.e. §2's table, display-confirmed. **Nothing in the
conversion path is implicated.**

**And the measurement could not have adjudicated anyway.** `E4_VOICE_FTYPE`
(id 82) read back **0 in all three runs** — with the panel on LP2, on LP4, and on
LP6. A reading that never changes identifies nothing, so no id-to-pole-count
mapping was established at any point.

**What the measurement actually establishes is about the machine's labels, not
about any table**: the panel's LP2 / LP4 / LP6 deliver 2.07 / 4.05 / 5.96 poles.
The instrument's own naming is accurate. That is worth having and it is a
different claim.

**The error is worth keeping because it had two stages.** First a table was
misread — two encodings taken as one. Then a stuck read-back was used as
corroboration for the misreading, and a stuck value agrees with whatever it is
pointed at. **A confirmation drawn from a channel that never varies is not weak
evidence, it is no evidence**, and nothing in the number said so: `0` is a
perfectly plausible filter type.

### CORRECTION: LP4 IS obtained — 4.05 poles — and both earlier failures were mine

**LP2 = 2.07 poles, LP4 = 4.05 poles, both corner-independent.** With the filter
type set from the front panel and the slope taken as the classical asymptotic
measure — the drop between **2x and 4x the −3 dB corner**, one octave, checked
clear of the floor:

```
            FMORPH 50    70      90     110     mean   spread
  LP2         2.10     2.08    2.10    2.01     2.07    0.09
  LP4         4.01     4.11    4.07    4.01     4.05    0.10
```

**The E4XT's lowpass delivers the pole count it names.** For the parked
pole-count-versus-resting-corner question, this closes our half: a cascade that
measures 4.05 poles at four corners is not where a slope discrepancy comes from.

**Two analysis errors, and both produced plausible wrong numbers rather than
failures.**

1. **A fixed dB window is a biased estimator of slope.** `−6..−35 dB of the
   passband` spans ~3 octaves on a 2-pole and under 1 octave on a 4-pole, so on
   the steep filter it sat in the *knee* and read too shallow — and less so at
   higher corners, because the window is wider in Hz there. That is precisely
   the "varies with corner" signature, and it was manufactured by the estimator.
   It reported 1.79 → 3.40 poles for a filter that is 4.05.
2. **A Butterworth magnitude fit was worse.** `|H|² = 1/(1+(f/fc)^2n)` returned
   1.8–2.5 poles at **8–13 dB residual**, because LP4 has a **+3.4 dB passband
   bump** the model has no term for and floors at −65 dB, which it cannot
   represent. The residual was the tell and it was printed from the start.

**What found it was reading the response**, third-octave by third-octave, instead
of fitting it: 1000 Hz → 2000 Hz is −13.2 → −37.1 dB on LP4, which is −23.9 dB
per octave and needs no estimator at all.

### The FTYPE parameter does not reflect the live filter

With the panel showing **LP4**, `E4_VOICE_FTYPE` (id 82) **reads back 0
(2-Pole)**. Not stale by a moment — reproducibly, across re-selection, while the
audio demonstrably behaves as a 4-pole.

So the earlier "enumeration set values 0–11 and read every one back correctly"
established nothing: it wrote and read an editor-side value with no bearing on
the filter in the voice. **Id 82 is not a window onto the live filter type**,
in either direction, and any procedure that sets a filter type over the editor
protocol and confirms by read-back is confirming itself.

`E4_VOICE_FMORPH` is not like this — it reaches the voice (the corner moves with
it) and the panel shows the value written. So this is a property of id 82, not of
the protocol.

### LP6: 5.96 poles

Floor-limited at 4x the corner (the response is within 8 dB of the −64 dB floor
there), so the octave is taken lower, past the knee and clear of the floor:

```
  FMORPH  50   315 ->  630 Hz   −9.0 -> −45.9   −36.9 dB/oct   6.15 poles
  FMORPH  70   400 ->  800 Hz   −6.3 -> −41.8   −35.4          5.90
  FMORPH  90   630 -> 1250 Hz  −11.9 -> −47.4   −35.6          5.93
  FMORPH 110   800 -> 1600 Hz  −10.1 -> −43.4   −33.3          5.55
```

**Mean 5.96 over the three best-placed windows.** So the full lowpass family:

```
  panel LP2   2.07 poles      panel LP4   4.05      panel LP6   5.96
```

Windows placed too close to the corner or too near the floor read low (4.62,
5.28, 5.55) — the same estimator bias as before, now understood and visible in
the printed band rather than hidden in a fit.

`E4_VOICE_FTYPE` cannot be set reliably over the editor protocol once voices have
sounded. The evidence is contradictory in a specific way:

- an enumeration pass set values 0-11 and read every one back correctly;
- later runs had the write **refused** by read-back confirmation on 12 retries
  with re-selection between attempts;
- and one earlier run reported `FTYPE 2 refused` while the value was **later
  found to be 2** — so the write had taken and the read-back had lagged.

Writing without gating on read-back then produced slopes that are **not
corner-independent** — 1.79 / 2.41 / 3.03 / 3.41 implied poles across four
corners for a nominal 4-pole, and a single 6.35 followed by 1.75 / 2.40 / 3.36
for a nominal 6-pole. **A pole count cannot vary with corner, so those numbers
are not a pole count** — most likely the reference capture and the measurement
captures were not taken at the same filter type. They are recorded as
uninterpretable rather than as a result.

### What would finish it

**The filter type set from the front panel, which is known to work**, and the
measurement taken from here — the same division of labour that made §124 work
once Jan set up the cords. Nothing about the analysis needs to change: LP2 came
out at 2.00 poles with the machinery exactly as it stands.

**And the general point, which is §124's again one turn later.** A parameter that
reads back correctly is not the same as a parameter that can be written, and
neither is the same as a parameter that reaches the voice. Three distinct
properties, three different failures seen today on three different parameters,
and the editor protocol reports success for all three.

### §125 addendum — the restore is also a repeatability check

Jan set voice 0 back to LP2, its original. Re-measuring rather than assuming:

```
  FMORPH    corner then / now      poles then / now
     50    287.1 / 287.1 Hz          2.10 / 2.10
     70    398.4 / 398.4             2.08 / 2.06
     90    562.5 / 568.4             2.10 / 2.06
    110    761.7 / 767.6             2.01 / 2.03
```

**Corners reproduce to within one FFT bin and pole counts to 0.04**, across three
front-panel filter-type changes and several dozen parameter writes in between.
That is a stronger statement than either individual run: the whole chain —
selection, FMORPH write, capture, reference division, slope measure — returns the
same numbers after being disturbed and put back.

**A restore that is verified by re-measuring costs one capture and answers two
questions at once**: whether the machine is back where it started, and whether
the instrument still reads what it read before. Reading the parameters back only
answers the first, and §125's whole problem was a parameter that read back
correctly and meant nothing.

Final state of P013 voice 0: FTYPE LP2 (panel), FMORPH 251, Q 0, GEN_VOLUME 0,
amp and filter envelopes both flat rectangles — matching the state it was merged
in.

## §126 — EOS 4.70 is open, the table is byte-identical to 4.62, and §123 was wrong (2026-09-14)

Jan suggested searching for public work on the container, and it exists:
**`eosflash` by Nkrypth/Madlabz** — a cross-platform CLI that inspects,
converts, compresses and decompresses EOS firmware. Jan had it cloned at
`~/git-repos/eosflash` within minutes.

```
  eosflash verify eos470.img
    type      : Raw 1.44MB floppy image, 4MB FlashROM
    version   : EOS v4.70
    hardware  : E-MU E4 Ultra (gen3, ColdFire MCF5206E)
    magic     : 0x76543211  (Ultra OS compressed)
    total used: 1965696 bytes (uncompressed), 1374037 bytes (compressed)
    checksum  : stored 0x08860e57, computed 0x08860e57  OK

  eosflash export eos470.img --eos eos470.eos
  eosflash flash  eos470.eos --eos eos470_plain.eos --4mb    ->  1,965,696 bytes
```

**The decompressed 4.70 is plaintext**: entropy **6.333** against 4.62's 6.335,
40.7% of 4 kB windows below 6.0 against 41.9%, and every crib that had been
absent from the packed payload all day — `Fatal: Bus Address error`,
`0123456789abcdef`, `Floppy CRC Error`, `Preset`, `Sample`, `Envelope` — present.

### The result that closes the version caveat

**The 128-entry envelope rate table is BYTE-IDENTICAL between EOS 4.62 and EOS
4.70.** The 4.62 table's 256 bytes appear verbatim in the decompressed 4.70
image, twice, at `0x41490` and `0x1da390`.

```
  log-slope over bytes 60-100 : 0.05638   r2 0.99994
  ENV_RATE_SWEEP_K (ours)     : 0.0565    ->  -0.2%
  ENV_RATE_K       (ours)     : 0.0581    ->  -3.0%
```

**So the firmware cross-check now stands on the version the bench actually runs**,
by direct comparison rather than by inference from a manual addendum. §122's
version caveat — the one that survived every other argument today, and that
§122 addendum 5 correctly refused to let a document close — is closed by
measurement.

### §123 IS RETRACTED

§123 concluded the payload was **not compressed**, from two arguments. Both were
wrong and the retraction is more instructive than the section was.

**It is compressed, 1,965,696 -> 1,374,037, a ratio of 1.43:1.**

- **The bit-density argument assumed strong compression.** "Compression drives
  bit density to 0.5" is true of a coder near the entropy limit — zlib on this
  content reaches 0.514 at 2.34:1. **A 1.43:1 coder leaves a great deal of
  redundancy and its output is nowhere near balanced.** 0.336 is exactly what a
  weak LZ77 with fixed-width fields produces, which is the alternative §123's own
  addendum raised and then did not act on.
- **The size argument's premise was false.** It assumed 4.62's content is
  comparable to 4.70's. It is not: 4.62 is 1,244,160 bytes and 4.70 is
  **1,965,696**, 58% larger — the RFX plug-ins the 4.7 addendum says ship with
  the OS. The addendum had flagged this premise as unestablished and the section
  still leaned on it.
- **And the ISA was wrong too.** E4 Ultra is a **ColdFire MCF5206E**, not 68020.
  68020 merely decoded with fewer invalid words than 68000, and I read a
  minimum over a two-point comparison as an identification.

**The pattern is the day's, in its purest form.** A measurement that could not
distinguish three hypotheses was reported as having picked one; then the
alternative was correctly identified in an addendum and the headline was left
standing anyway. **Writing the correction is not the same as applying it.**

### What actually opened it

Not analysis. **Somebody else had already done the work, and the search that
found them took four queries.** A day of parameter sweeps, crib tests, entropy
statistics and ISA counting produced a partly-wrong characterisation of a format
that a public tool already handles correctly — and the tool also settles the
processor, the checksum algorithm, the compressed/uncompressed magic pair, and
the `.dli` variant in one run.

**The search should have come first.** It is the cheapest possible test of
"is this problem already solved", it costs minutes, and this project reached for
it only after being told to.

## §127 — The table is identified from the code that uses it, not from its shape (2026-09-14)

§122's surviving caveat was that the table's identity was **inferred from shape**
— 128 entries, monotone, log-linear, at the right slope — because E-mu publish no
anchors to match. **With 4.70 decompressed (§126) that caveat is removable, and
it is removed here: the consumer is readable.**

The load base is `0x20000` — the 4 MB ROM's OS offset, which `eosflash`'s own
changelog names. Under it the table sits at `0x00061690` and is referenced
**exactly twice**, both in one routine at body offset `0x3fb38`. ColdFire decodes
it with zero invalid words:

```
  3fb4e:  movew %a1@(20),%d7          ; segment rate field
  3fb52:  movew %a1@(4),%d1           ; plus a second term (modulation)
  3fb5a:  addl  %d1,%d7
  3fb5c:  movel %d7,%d6
  3fb5e:  asrl  #5,%d6                ; >> 5  ->  a 0..127 index
  3fb60:  tstl  %d6 / bpl / moveq #0  ; clamp low
  3fb68:  cmpl  #127,%d6 / ble / moveq #127   ; clamp high
  3fb72:  movel %a1@(36),%d7          ; the running envelope level
  3fb7a:  moveal #398992,%a0          ; <- 0x61690, THE TABLE
  3fb82:  movew %a0@(0,%d6:l:2),%d1   ; table[index], u16, scaled index x2
  3fb86:  mulsl %d1,%d0               ; x elapsed ticks
  3fb8a:  subl  %d0,%d7               ; FALLING segment
  ...
  3fba4:  addl  %d0,%d7               ; RISING segment
  3fba6:  tstl  %d7 ...               ; clamp
```

**That is an envelope segment stepper**: clamp a rate index to 0-127, look up a
per-tick increment, multiply by elapsed ticks, add or subtract it from the
running level. **The two references are the rising and falling branches**, which
is why there are exactly two and not one or many.

### What this settles, and what it adds

**The identification is no longer a shape match.** `docs/data/eos462_env_rate_table_candidate.json`'s
`IDENTITY_IS_INFERRED` caveat is discharged: the table is indexed by a clamped
0-127 envelope rate and its value is the level increment per tick. mpc2emu's
rule — *a hit is a candidate, not a table* — was the right standard, and the
thing that met it was reading the consumer, not more statistics.

**The semantics confirm the corpus corroboration independently.** Table[0] is
65535, the largest increment, so index 0 is the fastest possible segment —
instant. mpc2emu's corpus puts **67.1% of all amp-envelope rate bytes at byte 0**.
Two unrelated facts agreeing, neither derived from the other.

**And a new fact falls out: the rate index is `(field + modulation) >> 5`.**
The internal rate resolution is **32x finer than the MIDI byte**, and the index
is formed by summing a stored field with a second term before clamping. So
envelope rate modulation moves in steps a parameter read cannot see, and any
model that treats the byte as the whole story is quantising something the
machine does not.

### The one caveat that remains, stated precisely

This is the **amp/filter/aux envelope segment stepper** as identified by its
arithmetic; which of the three envelopes a given `a1` block belongs to is not
established here, and the table may be shared by all of them. **That is a
question about the caller, not about the table**, and it is answerable the same
way — by reading the code — rather than on the bench.

## §128 — The filter cutoff law is measured, and it is NOT a table in the OS (2026-09-14)

Jan asked for the filter cutoff table to be checked against our measured curves.
**The curve is now measured properly; the table is not there, and the negative is
informative.**

### The measured law

P013 v0 (flat noise, note 24 root-matched, LP2, Q 0), corner = highest frequency
within 3 dB of the passband of `H = S/S_open`:

```
  FMORPH   20     40     60     80    100    120    140    160    180    200    220    235
  corner  199.2  252.0  351.6  498.0  685.5  949.2 1224.6 1634.8 2039.1 3082.0 5173.8 8109.4 Hz
```

**It is not a single exponential.** Log-slope per byte runs ~0.0165 at the bottom,
settles near 0.013–0.016 through the middle, and then **accelerates sharply above
byte 180** — 0.0207, 0.0259, 0.0300 over the last three segments. The panel reads
**18334 Hz at FMORPH 251**, which needs ~0.051/byte from 235 and confirms the
acceleration continues to the top. Span 20→235 is **40.7:1**.

### No matching table exists in the decompressed 4.70 image

Searched u16 and u32, big- and little-endian, every alignment. **3,336 strictly
ascending 256-entry runs exist**; every one was fitted against the twelve
measured points in log space, where a table proportional to the cutoff frequency
must give slope 1.0 and a small residual.

**The best fit is rms 0.069 in ln (7%) at slope 2.04** — and it is one smooth
data region, the same match reappearing at every 2-byte shift, which is what any
smooth monotone ramp does against any smooth monotone curve. **Nothing in the
image behaves like a per-byte cutoff table.**

### Why that is the expected answer, and what it says about the machine

**The envelope rate table IS in the OS and IS read by OS code** (§127: a segment
stepper indexes it and multiplies by elapsed ticks). Envelope stepping is
software. **Filter cutoff is not**: the byte goes to E-mu's filter hardware,
which does the mapping itself, so the OS never needs a byte→frequency table and
does not carry one.

**That is a structural fact about where the two laws live**, and it has a
practical consequence: the envelope rate law can be read from firmware and
checked against captures (§122, §126), and **the cutoff law can only ever be
measured.** No amount of further firmware work will produce it.

**The one thing the OS would still need is a display conversion** — the panel
shows Hz. That is either computed rather than tabulated, or stored in a form
this search would not recognise, and it was not found. It is also the least
interesting of the three, since a display law is what the machine *says* and the
captures are what it *does*.

### And the measured law is the deliverable

`docs/data/` now has what a firmware table would have given: twelve points across
the byte range on identified material, with the detector convention stated. Its
weakness is the opposite of the envelope table's — **no independent confirmation
exists or can exist**, so it stands on the measurement alone, and the honest
caveat is that it is one filter type (LP2) on one preset at one note. LP4 and LP6
give systematically *lower* corners at the same byte (§125's captures: 257.8 vs
287.1 at FMORPH 50), so the byte→corner map is filter-type dependent and this
table is LP2's.

## §129 — The E4B cord encoding, settled on hardware (2026-09-14, live)

mpc2emu's corpus histogram of modulation destinations rested on the assumption
that the E4B file byte at `voice[190 + 4N + 1]` and the SysEx destination id are
the same enumeration. **Nothing had checked it**, and the filter-type case earlier
the same day (§125) is what a file byte and a parameter id look like when they
are *not* the same scheme.

mpc2emu built the test: one preset, one voice, three cords planted **directly in
the E4B bytes**, in non-adjacent slots, with values the EOS template does not
ship, each triple unique in the file. Jan put it on the card and loaded it to
P019. **The E4XT parses the E4B itself, so nothing of ours is in the path** —
which is the property that makes it a test rather than a consistency check.

### Result

```
  slot   planted in the E4B          read back over SysEx
    3    src 40  dst 73  amt 99      src 40  dst 73 (VEnvAtk)  amt 78
    7    src 41  dst 75  amt 98      src 41  dst 75 (VEnvRls)  amt 77
   11    src 42  dst 82  amt 97      src 42  dst 82 (FEnvDcy)  amt 76
  every other slot zero              every other slot zero
```

**Destinations and sources are byte-identical.** Three non-adjacent codes, so it
is not a coincidence at one value. **§E4BRATEMOD's gate is discharged for all 43
destination codes at once**, and the corpus histogram becomes a real reading of
what modulates what.

The bank was confirmed to be the right one before anything was read, by its
shape rather than its name: exactly three non-zero cords, in slots 3/7/11, with
all fifteen others zero — not a configuration the E4XT ships.

### And the amounts give the unit conversion mpc2emu could not compute

The amounts are **not** identical, and the discrepancy is exact rather than noisy:

```
  file 99 -> 78     file 98 -> 77     file 97 -> 76     file 28 -> 22
  round(file * 100/127):  78            77                76            22
```

**The E4B stores the cord amount as a signed byte in ±127; the SysEx parameter
reports it as a percentage in ±100.** The fourth row is mpc2emu's own template
default — the `+0.220` they had already measured in the corpus — and it lands on
the same law without having been used to derive it.

That is the conversion they said was the last piece and on our side of the line:
**a cord amount of 1.000 in their model is file byte 127, which is SysEx 100%.**

### What is still open

**What SysEx 100% delivers in the envelope generator's internal units.** §127
showed the rate index is `(field + second term) >> 5`, so the modulation arrives
32× finer than the MIDI byte — but the second term's own full scale is computed
in a routine we have not read. **The file↔SysEx leg is now pinned; the
SysEx↔internal leg is not.**

### The method note

**Three values rather than one, non-adjacent, in a shape the instrument does not
ship.** Each choice defends against a different failure: one value can coincide,
adjacent values can be an off-by-one that happens to land, and a shape that could
be a factory preset cannot be distinguished from a leftover bank. The
verification was designed so that a wrong answer could not look like a right one
— which is the thing this project spent the whole day failing to do by accident
and mpc2emu did here on purpose.

### §129 addendum — the fourth row, and the difference between a rule and a mechanism

**The amount law's fourth row is the only part of it that is evidence.**

```
  file  99 -> 78    98 -> 77    97 -> 76        planted for this test
  file  28 -> 22                                NOT planted, NOT used to fit
```

The first three are three points on a line through the origin, and any line
through the origin fits three points chosen to lie on it. **The fourth is
mpc2emu's EOS template default — the `+0.220` from their corpus histogram, an
unrelated source — and `round(28 x 100/127) = 22` was a prediction, not a fit.**

That is the same instrument as the a-priori pitch check (§121 addendum 3) and the
no-attack control (§121): **a quantity whose true value comes from somewhere that
shares none of the measurement's assumptions.** Three of them today, in three
different domains, and each time it was the thing that turned a plausible result
into a checked one.

It also retroactively confirms `cord_byte_to_amount`'s `/127`, which had been an
assumption in mpc2emu's writer since it was written.

### The day's actual shape, stated once

Most of what went wrong today was not a reasoning error. **It was a correct rule,
already written down, not invoked at the moment it mattered:**

- `tools/load_bank.py` had a three-state screen classifier, written this morning
  for this exact popup. A bare threshold was used instead, and the merge sat
  unanswered behind a dialog the classifier would have named.
- §123's own addendum identified weak fixed-field LZ77 as the better candidate,
  and the headline claiming "not compressed" was left standing above it.
- §112's rectangle test exists to *qualify* material. It was built into the run
  and then read as a measurement, so the material was screened after the ladder.
- §110's rule — an absence is worth only as much as the statement of where you
  looked — was recorded weeks ago, and §116 still concluded the decompressor
  "lives in the boot ROM" after looking in two files.

**The fix is not more rules.** It is the shape mpc2emu used for the cord test and
that `row_schema_required` and `tools/carrier_check.py` use here: put the check
where it cannot be skipped. The uniqueness requirement was a line of code that
had to pass before the file could be written. `carrier_check.py` refuses rather
than reports. A required column cannot be omitted and then regretted.

**A rule can be not-reached-for. A mechanism cannot.** That distinction is worth
more than any measurement in this file.

## §130 — Key -> attack is a CORD, the direction comes from firmware, and the writes are unreliable (2026-09-14, live)

Jan's correction to §121: **"no note-dependence in attack time" is a statement
about a preset with no key-to-rate routing, not about the machine.** EOS
implements that as a modulation cord, and he set one up on P019 CORDMAP —
**cord 15: `Key+` (src 8) -> `VEnvAtk` (dst 73), amount +100%** — verified here
by eight consecutive agreeing reads.

### The control result, which is the solid half

P017 (`NOISE XP R72`), noise, origkey 72, zone keys 72-96 — 24 semitones on
material with no carrier, so §121's fixed-timescale artefact cannot apply. Atk1
rate 72, no cord:

```
  note      72      80      88      96
  t90    3.020   2.940   3.000   2.980 s      spread 2.7%
```

**Flat.** That is §121's null reproduced on a different preset, different
material and a different octave. **"No intrinsic note-dependence in the attack"
now rests on two independent subjects**, and the qualifier Jan supplied is the
right one: intrinsic, absent; via a cord, available by design.

### The direction, from firmware rather than from the bench

§127's stepper computes `index = (field + modulation) >> 5`, and the rate table
**descends** — `table[0] = 65535` is the largest per-tick increment, i.e. the
fastest segment. So **a positive modulation raises the index and makes the attack
SLOWER.** `Key+` rises with pitch, so `Key+ -> VEnvAtk` at **+100% makes high
notes slower** — the opposite of the usual musical intent.

**And there is no `Key-` source.** The source table has only `+`, `~` and `<`
forms (`Key+` 8, `Key~` 9; `Vel+` 10, `Vel~` 11, `Vel<` 12; and the same triple
for each envelope). So shortening attacks as pitch rises requires **`Key+` with a
NEGATIVE amount**, or `Key~` (bipolar, centred) with one — not a different
source. Jan's reading was right and the firmware says why.

### What was NOT obtained, and why

**The cord-on measurement.** Two attempts failed at the parameter write, not at
the measurement:

- the cord's `SRC`/`DST` were refused by read-back confirmation on 12 retries,
  then on 10 unconditional pushes — the amount took (100), the source and
  destination did not (read back 0 / 127);
- on the retry the **envelope rate write also failed silently**, and the result
  was four notes at `t90 = 0.020 s` — an instant attack at every note. Return
  values were not checked, so it measured a preset it had not configured.

**This is the third parameter today that cannot be reliably written over the
editor protocol** — `E4_VOICE_FTYPE` (§125), the cord `SRC`/`DST` here, and
intermittently the envelope rate. `E4_VOICE_FMORPH`, `E4_GEN_VOLUME` and the cord
`AMT` write reliably. **Read-back confirmation is not a solution**: §125 showed a
write that succeeded while the read-back disagreed, and §129's cord test showed
reads that were stable and correct. The failure is in the write path for
particular ids, and it is not yet characterised.

**The practical rule until it is:** for those ids, set from the front panel and
read over SysEx — the division of labour that produced §125's pole counts and
§129's cord result. And **check every write's return value**, which this section
did not.

### And the internal-units question is still open

The cord contribution's full scale was not found. What was established:
the stepper's caller passes the envelope block as `a5@(90)` with a tick count of
1; the block's second term is at `+4`; and **`>> 5` recurs elsewhere** (an
unrelated accumulator at `0x5fcca` uses the same `base + mod>>5` idiom), so a
32x-finer modulation store is a firmware-wide convention rather than an envelope
quirk. The routine that computes a cord's contribution from source x amount was
not located.

## §131 — The zone selector breaks voice-parameter addressing; §130 and half of §125 are retracted (2026-09-14, live)

Jan, on §130's claim that three parameters "resist writing over the editor
protocol": *"that would be kind of catastrophic — can you recheck?"* **It is
retracted. Nothing resists writing. The cause was a selector this project was
setting itself.**

### The A/B

Same preset, same voice, same values, same session — the only difference is
whether `SAMPLE_ZONE_SELECT` (id 226) was set before the writes:

```
  WITHOUT zone-select                    WITH zone-select (226 = 0)
    cord11 SRC  wrote 35 -> read  35 OK     wrote 35 -> read 255  IGNORED
    cord11 DST  wrote 56 -> read  56 OK     wrote 56 -> read 255  IGNORED
    FTYPE       wrote  2 -> read   2 OK     wrote  2 -> read   0  IGNORED
    FMORPH      wrote 120 -> read 120 OK    wrote 120 -> read 120 OK
```

**Selecting a zone makes voice-level ids unaddressable** — writes are silently
dropped and reads return fixed junk (255 for the cord fields, 0 for FTYPE) —
while zone-scoped and some voice parameters keep working. `E4_VOICE_FMORPH`,
`E4_GEN_VOLUME`, the envelope rates and the cord `AMT` are unaffected, which is
why the failure looked id-specific.

### What this retracts

**§130's "three parameters cannot be reliably written" — withdrawn entirely.**
They write fine. Every failure was in a helper that called `setp(226, 0)` as part
of its selection preamble.

**§125's "`E4_VOICE_FTYPE` does not reflect the live filter" — withdrawn.** That
conclusion came from reading FTYPE as 0 while the panel showed LP4, using a
capture script whose selection preamble set the zone. With the zone not selected,
FTYPE reads correctly: it reads 0 now, and the panel is on LP2.

So the LP4 / LP6 measurements **could** have been driven entirely over SysEx.
Jan set the filter type at the panel three times for no reason other than this
bug, and §125's "set it from the front panel" rule was a workaround for a
self-inflicted fault. **The measurements themselves stand** — the pole counts are
unaffected, since the filter type was genuinely what the panel said.

### Why it took so long to find, which is the part worth keeping

**The failure was introduced midway through the day and looked like a property of
the machine.** The FTYPE enumeration that succeeded (values 0-11, all read back)
had no zone-select in its preamble; every later run that failed did. The
selector was added to the helpers because zone-scoped reads needed it —
`E4_GEN_SAMPLE`, key ranges — and then it stayed in preambles that went on to
write voice parameters.

**And the diagnosis was reached by eliminating the suspect Jan named, not by
confirming it.** mididings was A/B'd out (identical write rates connected and
disconnected) — and that elimination is what forced the search back onto our own
code. **A hypothesis that is cheap to test and turns out wrong is still the thing
that moved it**, which is the argument for testing the named suspect first even
when it looks unlikely.

**The mechanism-not-a-rule point again.** The A/B that settled it took four
minutes and could have been run the first time a write was refused, six hours
earlier. What made it finally happen was a user asking "recheck" — an external
prompt, not an internal trigger.

### Practical rule

**Do not leave `SAMPLE_ZONE_SELECT` set when addressing voice-level parameters.**
Select preset and voice; select a zone only around the zone-scoped reads that
need it, and re-select the voice afterwards. Any helper that sets 226 as part of
a generic preamble is wrong.

## §132 — `Key+ -> VEnvAtk` measured: full scale is the whole rate range, and the sign was backwards (2026-09-14, live)

With §131's zone-selector fault removed, the cord measurement §130 could not
take now runs. Subject P017 (`NOISE XP R72`): flat looped noise, origkey 72,
zone keys 72-96, Atk1 rate 72, plateau envelope, note root-matched.

### The data

```
  amount    note 72      80      88      96
      0%     3.020    2.960   3.000   2.980 s     (flat -- 131's null)
    +10%     1.940    1.800   1.780   1.740       faster, and faster with pitch
    +20%     1.300    1.200   1.100   1.040
    -10%     4.400    4.620   4.640   4.900       slower, and slower with pitch
   +100%     0.040    0.020   0.020   0.020       SATURATED at every note
   -100%     20.5     20.5    20.5    20.5        SATURATED at every note
```

### The sign was backwards, and the reason is worth more than the correction

§130 predicted from firmware that a positive modulation raises the index and so
makes the attack **slower**. **A positive amount measures FASTER**, and the table
direction is not in doubt (`T[0]=65535`, `T[72]=162`, `T[127]=4`; index 0 is
instant, confirmed independently by 67% of corpus rate bytes sitting at 0).

**The disassembly was right about the structure and could not have been right
about the sign.** `(field + term) >> 5`, the clamp, the two branches — all
correct. But the sign lives in whatever produced `term`, three routines earlier,
which was never read. **A disassembly gives the shape of a computation, not what
a register held before it arrived.** The claim should have been marked as
structure-only when it was made.

Musically the measured direction is the expected one: `Key+` at a **positive**
amount shortens attacks as pitch rises.

### Full scale: an inequality from saturation, then a constant

**The floor needs no calibration.** At +/-100% the index clamps at *every* note,
including note 72 where `Key+` is only 0.567 of its own scale. Going 72 -> 0 is
72 bytes = 2304 internal units, so `0.567 x full >= 2304` gives
**full scale >= 127 bytes**. That is an event that either happened or did not —
no detector convention, no fit, no repeat takes — and any other normalisation of
`Key+` makes it *smaller* at note 72 and therefore pushes the floor **up**.

The unsaturated runs then give the constant, by converting each `t90` through the
firmware table (`t90 ~ 1/T[index]`) to an index and differencing against byte 72:

```
  index shift (bytes)      note 72     80      88      96
        amount +10%          -7.94   -8.90   -9.34   -9.64
        amount +20%         -15.02  -16.12  -17.88  -18.77
        amount -10%          +6.68   +7.86   +7.70   +8.89

  full scale, from the absolute shift:   118 - 136 bytes
  full scale, from the slope in note:     90 - 117 bytes
  slope at 100% amount:              ~0.8 bytes of rate per semitone
```

**So a 100% cord spans essentially the whole 0..127 rate range**, and one
internal unit is 1/32 byte, making full scale ~3200-4100 internal units.

### Two honest limits

**The two estimators disagree by about 20%**, which means `Key+` is not simply
`note/127` — an offset or a different reference (root key, voice key range) would
reconcile them, and none has been established. The *floor* is unaffected, because
it comes from the saturation rather than from either fit.

**And the response is not quite linear in amount**: +20% gives 1.89x the shift of
+10%, not 2.00x, and -10% gives 0.84x the magnitude of +10%. Small, real, and
uncharacterised.

### A cross-check that looked independent and was not — WITHDRAWN

This section originally offered: *"the rate law predicts the measured time to 1%
on a cord it was never fitted to"* — `exp(0.0581 x 7.94) = 1.58` against a
measured `3.020/1.940 = 1.56`. mpc2emu extended it, found the **firmware**
constant 0.0565 fitting three times better, and — correctly — asked whether the
byte shift had passed through a law anywhere, since the whole thing collapses if
it had.

**It had. The law was the table itself.**

```
  idx = index_for( T[72] * t_base / t_measured )   # log-interpolates THE TABLE
  162 * 3.020/1.940 = 252.2  ->  index 64.06,  shift -7.94 bytes
```

The shift is **by construction** the table displacement that reproduces the
measured ratio. Feeding it back through a candidate `k` tests only whether that
`k` matches the table's local log-slope, which over bytes 64-72 is **0.05572**.
So 0.0565 "fitting" and 0.0581 not is a restatement of the table's contents, not
a measurement.

**And the reasoning that was meant to detect this pointed the wrong way.** The
test was: an exact reproduction would prove circularity, a 1.9% miss would rule
it out. But the miss is the *table's own deviation from a pure exponential* over
that span. **A circular derivation through a non-exponential table produces an
inexact-looking agreement — which is the most convincing possible disguise.**

So the independent support for 0.0565 remains **two** lines, not three: the
table's slope over bytes 60-100, and the corpus's byte-0/instant agreement. This
experiment contributes the saturation floor and the sign, and nothing about
`ENV_RATE_K`.

**What would be non-circular**, and it changes the shape of the outstanding bench
check: a byte shift obtained without the table. Set rate byte 60, measure; set
byte 100, measure; take the ratio. **Two rungs, not one** — a single rung gives a
time, and only a ratio discriminates between two candidate slopes.

### What it means downstream

mpc2emu's open question was whether a corpus median amount of 0.110 is "~14 bytes
and matters" or "a few internal steps and is nothing". **It is the first.** And
converted through the rate law it is worse than the byte count suggests, because
the law is exponential: one byte is x1.0598 in envelope time, so 14 bytes is
**x2.25** and the EOS template default at 0.220 is **x5.07** — a 2.03 s attack
becoming 0.40 s. **That default sits on most voices in their corpus and their
reader drops it**, which makes the exposure larger than the authored-cord share
alone.

## §133 — The modulation scale, closed with a source whose value is known (2026-09-14, live)

§132 measured `Key+ -> VEnvAtk` and got two estimates of the full-scale constant
that disagreed by 1.56x — 140 bytes from the absolute shift, 90 from the slope
across notes. **The disagreement was the finding: `Key+` is not `note/127`**, and
every figure derived from it carried an unestablished normalisation.

**Fixed by changing the source rather than the analysis.** `MidiF` (src 35) is
CC 26, whose value is exactly what we send. One note, one rate byte, CC swept:

```
  P017 v0, note 72, Atk1 rate 72, cord MidiF -> VEnvAtk at amount +10%

  CC 26      0      32      64      96     127
  t90     3.020   2.380   2.040   1.740   1.440 s
  shift       0   -4.30   -6.99   -9.88  -13.20 bytes
```

### The constant

```
  full span, CC 0 -> 127 at amount 10%:  -13.20 bytes
  => at amount 100%, full source:        -132 bytes
  => one index byte = 32 internal units  (127, the >>5)
  => full scale = ~4224 internal units
  => 1% of cord amount at full source    = 1.32 bytes = 42 internal units
```

**132 bytes slightly exceeds the 0-127 index range**, which is why a +/-100% cord
saturates at every note (§132) and is consistent with the >= 127 floor that
saturation established. **Two methods, one an inequality from clipping and one a
measurement from an unsaturated sweep, agreeing.**

mpc2emu's corpus median amount of 0.110 is therefore **14.5 bytes**, matching
their own ~14 estimate from the other direction.

### The limit, stated rather than smoothed

**The response is not linear in the source.** Per-CC-unit slope runs -0.0841
(CC 32-64), -0.0903 (64-96), -0.1071 (96-127) — accelerating by 27% across the
range, so the low-CC estimate of the constant (170 bytes from CC 32 alone) is an
outlier and the full-span figure is the one to use. Whether that curvature is in
the source scaling, the amount scaling, or in the `t90 ~ 1/T[index]` assumption
is not established. **132 bytes is a full-span figure, not a local slope.**

### And the bench check that remains, in its corrected form

§132's withdrawn cross-check left one outstanding measurement, and mpc2emu added
the constraint that makes it work:

> Set rate byte 60, measure. Set rate byte 100, measure. Take the ratio.
> **No table, no cord, no fit** — and **two rungs, not one**, because a single
> rung gives a time and only a ratio discriminates between two candidate slopes.
> **Both rungs must sit well inside one piecewise segment**, not straddle a
> boundary: the table is piecewise (0.128 / 0.0596 / 0.0564 / 0.0778) and a ratio
> taken across a break measures a blend and adjudicates neither.

That is materially different from "confirm the table at bytes 20-59", which is
what the list said this morning and which would have spent a bench hour without
separating `ENV_RATE_K` from the firmware constant.

## §134 — The rate law measured without the table: it is piecewise, and neither constant is right everywhere (2026-09-14, live)

The outstanding check from §132/§133, run as specified: set a rate byte, measure
`t90`, set another, measure again, take the ratio. **No table, no cord, no fit** —
audio and byte numbers only. Two pairs, each inside one of the table's piecewise
segments. P017, flat noise, note 72 root-matched, every rung measured twice.

```
  byte      25      55      60     100
  t90    0.210   1.160   1.500  14.520 s     (repeat spreads 0.020/0.000/0.000/0.080)
```

**Byte 25 was quantisation-limited** at the 20 ms smoothing used for the capture —
its two takes, 0.200 and 0.220 s, are exactly one analysis window apart on a
0.21 s rise. Re-analysed from the same audio at finer widths:

```
   k per byte      2ms      5ms     10ms     20ms  |  table   0.0565   0.0581
     60 -> 100   0.05649  0.05577  0.05638  0.05675 | 0.05656  0.05650  0.05810
     25 ->  55   0.05866  0.05787  0.05802  0.05697 | 0.05999  0.05650  0.05810
```

### What it settles

**The law is NOT a single constant.** At matched smoothing (2 ms, the finest the
material supports) the two bands give **0.05649** and **0.05866** — a 3.8%
difference, in the direction the firmware table predicts. **The piecewise
structure found in §122 by reading the table is confirmed by direct measurement**,
independently of the table.

**And neither candidate is right across the range:**

```
  bytes 60-100   measured ~0.0564   ENV_RATE_SWEEP_K 0.0565 fits;  ENV_RATE_K 0.0581 is +2.9% off
  bytes 25- 55   measured ~0.0587   ENV_RATE_K 0.0581 fits (+1.0%); SWEEP_K 0.0565 is -3.8% off
```

Each constant is right in one band and wrong in the other. **So "move
`ENV_RATE_K` to 0.0565" is the wrong question** — it trades an error in the band
holding 90% of corpus usage for a better fit in the band holding 8%. §122's
corpus weighting already implied a piecewise law would be needed; this is the
measurement that establishes it without reading the table at all.

### The limit, and it is not small

**Within-band smoothing spread is 1.8% (60-100) and 3.0% (25-55)**, against a
between-band difference of 3.8%. The effect is larger than the spread but not by
much, and it rests on one preset at one note. **The direction is solid — both
bands are ordered as the table says, at every smoothing width tried — but the
magnitude is not pinned**, and the measured 25-55 slope of 0.0587 sits 2% below
the table's 0.0600 rather than on it.

**What would tighten it**: rungs further apart within each segment (22 and 58;
62 and 98), a second preset, and a detector whose window is chosen per rung
rather than fixed — the fast rung needs a few milliseconds and the slow one does
not care. All bench work, none of it hard.

### The method point

**This is the first measurement today that adjudicates between the two constants
without passing through the table**, and it was only possible because §132's
cross-check was withdrawn as circular and mpc2emu specified what a non-circular
version would need: two rungs rather than one, both inside a single segment.
**The corrected instruction found something the original would have missed** —
"confirm the table at bytes 20-59" would have produced a single time, which
cannot separate two slopes at all.

### §134 addendum — the offset belongs to the measurement, and a second circular check

**mpc2emu's correction, adopted.** §133's conversion model carried `t = t0 + C/T[byte]`
with `t0` = 17.4 ms. **`t0` is the detector's floor** — §130's no-attack control
reports 20-60 ms with no rise present at all — so it belongs to the measurement,
not to the law. Subtract it from measured times when calibrating `C`; never carry
it into a converter.

**The gain is structural, not numerical.** With `t = C/T[byte]` and nothing else,
this project's detector convention survives in **exactly one multiplicative
constant**. Every ratio is the machine's own, so a later re-measurement with a
better detector moves one number and **cannot change the shape**. That is the
failure mode that cost three days on a sibling's attack law, where a detector was
baked into an exponent and the shape was wrong everywhere at once.

**And a second circularity, the same shape as §132's.** The correction was
reported as reproducing the measured 25->100 ratio to **four decimal places**.
It does — because `C` and `t0` were solved from bytes 25 and 100. Two equations,
two unknowns; subtracting `t0` and taking the ratio of its own fit points
recovers `T[25]/T[100]` exactly **whatever the table contains**.

```
  fitted points     M[25]-t0 = C/T[25]    identical by construction
                   M[100]-t0 = C/T[100]   identical by construction
  held-out points   byte 60   +0.83%
                    byte 55   -3.91%
                    ratio 55->60  +4.93%
```

**So these data confirm the table's shape to about 4-5%, not to four decimals.**

**Both of today's circular checks were caught by the same question and by nothing
else: what was this number computed from?** Neither was caught by inspecting how
good the agreement looked — and in both cases the agreement looked *better* the
more circular it was. **An unusually exact agreement between a measurement and a
model is first evidence that the measurement passed through the model.**

**What justifies the table is not these rungs.** They sit mid-range, where any
exponential does well. The justification is that the table is the machine's own
data, identified by its consumer (§127), and that a single exponential is wrong
by a **factor of 2-3 at the ends** (§122). Nothing measured today samples that
region. The argument is "this is the machine's table", not "it fits better".

## §135 — The full-range ladder kills the table-based conversion (2026-09-14, live)

Jan: *"measure more points and the ends?"* — because §134's four rungs all sat
mid-range and the table's entire claimed advantage was in territory nobody had
measured. **Sixteen rungs, byte 3 to 110, per-rung hold and per-rung smoothing,
two takes each. The claimed advantage is not there.**

```
  byte     3      5      8     12     16     20     25     30
  t90  0.0414 0.0470 0.0592 0.0870 0.1133 0.1598 0.2037 0.2749 s
  byte    40     55     60     70     80     90    100    110
  t90  0.5060 1.1900 1.5500 2.7000 4.6600 8.0800 14.490 27.420 s
```

Repeat spreads 0.000-0.060 s, quantisation 0.1-2.2% — **the measurement is not
the limiting factor.**

### The comparison, with the exponential given MORE freedom

```
                              TABLE t=C/T[b]      EXP t=A*exp(k*b)
                              (1 parameter)       (2 parameters)
  all 16 rungs, byte 3-110    mean 7.1%  w 31.0%  mean 9.0%  w 20.5%
  byte >= 12 (13 rungs)       mean 3.9%  w  8.2%  mean 4.0%  w  9.6%
  byte >= 20 (11 rungs)       mean 3.3%  w  9.2%  mean 2.4%  w  4.5%
```

**Over the cleanly measurable range a plain two-parameter exponential fits as
well or better than the table.** And the table's residual is systematic, not
noise: **-8.2% at byte 20, +0.1% at 30, +4.3% at 80, +7.4% at 110** — a monotone
drift, which is the signature of a wrong functional form rather than scatter.

### So `t = C / T[byte]` is wrong, and §133/§134's proposal is withdrawn

The table is the machine's own data and §127 identified it by its consumer, so it
is certainly involved. **What is wrong is the assumed mapping from table value to
attack time.** Fitting `t = C * T^p` gives p = **-0.961** rather than -1, and
adding an offset gives `t0` = 8 ms, p = -0.987, mean 2.7% — better, but now two
and three free parameters, at which point the table has bought nothing an
exponential does not.

**Candidate reasons, none established**: the stepper may not run at a constant
tick; the traversal may not be a simple accumulate to a fixed target; or `t90`
may not be proportional to traversal time. Reading the caller would settle it and
this session did not get there.

### And the low end is OUR floor, not the machine's

Bytes 3, 5 and 8 measure 41, 47 and 59 ms against a **detector floor of 20-60 ms**
(§130's no-attack control, with no rise present at all). Those three rungs carry
the worst residuals in every model (-31% for the table at byte 3) **and they are
the region the whole argument was about.** Excluding them changes the table from
"7.1% mean" to "3.9% mean", which is the difference between a broken model and a
mediocre one — decided entirely by three points we cannot trust.

**So the ends were measured and the answer is that we still cannot see them.**
The fast end needs a detector with a floor well under 10 ms; the slow end above
byte 110 needs holds over a minute and was not attempted.

### What this retracts

**The recommendation sent to mpc2emu an hour ago — adopt `t = C/T[byte]` —
is withdrawn.** It rested on the table being the machine's data, which is true,
plus an assumed inverse mapping, which the measurement rejects. **`ENV_RATE_K`
stays where it is**, and the honest position is the one §134 reached: the law is
piecewise, each constant is right in one band, and nothing measured today
improves on a fitted exponential over the range we can actually see.

**The general form, and it is the day's shape once more:** a model was proposed
on the strength of its provenance — *it is the machine's own table* — rather than
on a fit, and provenance turned out not to be enough. **Being the right data does
not make it the right model.** The table is real; `C/T[byte]` was mine.

### §135 addendum — the durable finding is the floor, and a failure mode of two careful people

**mpc2emu's reframing, which is better than "the table lost":**

> The low end of the EOS rate law **cannot currently be measured at all**, and
> any future proposal resting on it needs a detector before it needs an argument.

Bytes 3/5/8 measure 41/47/59 ms against a no-attack control floor of 20-60 ms
(§130). **The entire region the table's case rested on — bytes 1-19, where
mpc2emu weighted the advantage as a factor of 2-3 — is below this rig's
resolution.** That is a standing constraint on the instrument, not a fact about
this model, and it outlives the proposal that exposed it. A detector with a floor
well under 10 ms is a prerequisite for any work down there.

### And the failure mode, which neither of us would have caught alone

The order of events, stated because it flatters nobody:

1. **I proposed** `t = C/T[byte]`, **flagged that the four mid-range rungs did not
   justify it**, and recommended it anyway.
2. **mpc2emu improved it** — correctly — by moving `t0` out of the model and into
   the measurement, which is genuinely better engineering.
3. **They then reported a four-decimal agreement** that was the fit reproducing
   its own two input points.
4. **I caught that**, and we both restated the honest position: the case rests on
   the table being the machine's data.
5. **Nobody tested it where it claimed to win**, for two rounds of refinement.

**Two careful people improved a model neither had tested at the place it claimed
its advantage, and each improvement made it more persuasive without making it
more true.** Collaboration sharpened the argument and the sharpening was itself
the hazard — a lone author might have shipped it faster, but would also have had
less reason to believe it.

**What broke the loop was a user asking for the measurement neither of us had
run**, and it took one capture session. The question *"has anyone measured the
thing this claim is actually about?"* was available at every step and was asked
by neither participant.

## §136 — The amp-envelope LEVEL law measured to byte 25, and mpc2emu's factor of two resolved (2026-09-14, live)

Two questions arrived from mpc2emu the same evening, and one capture session
answered both. Neither answer is the one I reported first.

### The task, and the floor that had to come first

mpc2emu asked for the amp-envelope level law — attack 0, decay fast, sustain
held at a swept level, plateau depth below attack peak — and asked for the
achievable noise floor *before* any rungs, as a result rather than an obstacle.
Their existing law, `dB below peak = 97.82 − 0.7718 × level_byte`, was fitted
over bytes 80–116 only, so `ENV_FULL_SPAN_DB = 97.82` is that line extrapolated
nearly three times past its data.

Broadband RMS on a noise source gave 59 dB of headroom and put sustain level 0
**0.04 dB above the chain floor** — the full-span point unmeasurable, and the
error direction flatters the existing law, because a noise floor *adds* power to
a plateau so a deep sustain reads higher and the span reads shorter.

A tonal source with a narrowband detector changed the picture: at 82 Hz, a
2^16 FFT has 0.73 Hz bins against 24 kHz of broadband noise. That is where the
reach comes from, and it is the difference between "impossible with this rig"
and a measured law.

### Four instrument failures in one evening, all the same shape

Each returned a confident number for a quantity other than the one asked for.

1. **The floor located by `argmax`.** The silence floor was found by taking the
   maximum bin above 40 Hz and the plateaus were read at a *fixed* bin. Those are
   two different statistics and both were labelled "the floor". The argmax landed
   on 93.75 Hz, a line standing 28.5 dB over its local median — mains hash, not
   the tallest noise (50 Hz sits +21.7 dB, 150 Hz +27.1 dB over local median).
   Inflation: **+19.97 dB**. Read at the signal bin, silence is −106.34 dBFS, not
   −86.37, and sustain 0 sits 2.62 dB below it — about one standard deviation for
   a 7-bin power estimate, so no contradiction and no evidence of a gate.
   The "92.76 dB span, 5 dB from the predicted 97.82" reported on the strength of
   it was floor-limited and is **withdrawn**. There was never a disagreement.

2. **The detector bin hardcoded across an FFT size change.** Bin 112 is 82 Hz at
   2^16. The FFT was then raised to 2^18, where bin 112 is 20.5 Hz. The detector
   aimed at nothing and reported the top rung **62 dB low**. Fix is mechanism, not
   rule: the bin is computed from frequency and FFT size at every call.

3. **A note left sounding by a killed script.** It raised the 82 Hz bin **11.4 dB
   while moving the broadband meter 0.44 dB** — a quiet stuck tone is invisible to
   a broadband meter and lands squarely in the narrowband detector's own bin, so
   the only meter that can see this failure is the one being calibrated. Guards
   added: a floor gate that refuses to proceed until the floor comes down, and
   All Notes Off on every exit path including signal handlers.

4. **The correction for a known bias, noisier than the bias.** This one is new
   and is the reason for the retraction below. Subtracting floor *power* from
   plateau power over-corrects near the floor on a noisy floor estimate, driving
   the result down and the apparent "dB below peak" up. In the broadband run the
   raw floor added power and made spans read short; the correction for it removed
   too much and made them read long. **A correction for a known bias is itself an
   estimator, and near the limit its error can exceed the bias it removes.**

### The cliff that was not there — RETRACTED

The first narrowband ladder showed rungs from byte 127 down to 32 on a clean
line and everything below byte 32 in the noise, with byte 25 reading ~11 dB
*below* where the line predicted — predicted −94.66 dBFS at 12.9 dB above the
floor, which would have been comfortably measurable. That was reported as a
discontinuity between bytes 32 and 25, and mpc2emu matched it against their
corpus: 59 voices at bytes 26 and 29, the densest cluster below byte 32.

**There is no cliff.** Repeating the rungs with +10 dB more output gain
(`E4_GEN_VOLUME`, id 39) walks the law straight through the region:

| byte | gain 0 | gain +10 | 97.78 − 0.7720×byte |
|-----:|-------:|---------:|--------------------:|
| 51 | 58.15 | 57.30 | 58.42 |
| 43 | 64.18 | 63.51 | 64.59 |
| 38 | 68.40 | 67.49 | 68.44 |
| 36 | 69.96 | 68.76 | 69.99 |
| 33 | 72.92 | 71.63 | 72.30 |
| 30 | 76.96 | 73.59 | 74.62 |
| 28 | 81.11 *(read as "floor")* | 75.37 | 76.16 |

Every flagged rung came back into agreement once there was headroom under it,
and **the discrepancy at each rung shrank monotonically with its distance above
the floor** — the signature of a floor artefact, since a property of the machine
would not know how far a rung sat above our noise. The gain test was the whole
experiment: a digital gate stays at the same *byte* when output gain rises; a
converter or chain floor moves down in byte. It moved.

Also withdrawn with it: the argument that sub-cliff scatter proved *silence*
rather than a stuck internal level. The reasoning was sound; its premise is gone.
If the machine has a floor in its level representation, it is below byte 25 and
nobody has reached it.

### What the level law actually measures to

Three sweeps, pooled (29 rungs, bytes 25–127): `96.98 − 0.7641 × byte`,
r² 0.99957. Per sweep:

| sweep | rungs | bytes | fit | rungs above byte 60 |
|---|---:|---|---|---:|
| first ladder | 9 | 32–127 | 97.78 − 0.7720 b | 6 |
| gain 0 | 8 | 33–127 | 97.55 − 0.7688 b | 1 |
| gain +10 | 12 | 25–127 | 96.48 − 0.7608 b | 1 |

The 1.5% spread on slope is larger than any single sweep's internal scatter, and
the last column is why: the two later sweeps were laid out to bracket a cliff, so
their slope is levered off a single top rung. **The headline "0.03% agreement"
reported from the first sweep alone is not the accuracy of the measurement** —
the honest figure is 0.764 ± 0.006 dB/byte and 97.0 ± 0.7 dB at byte 0.
mpc2emu's constants sit at the top of that range, about 1% out, well inside it.
They should not be changed on these numbers.

### mpc2emu's factor of two: their `ENV_RATE_SWEEP` is right

Two hardware-derived laws in their writer disagreed by exactly a factor of two
about one quantity — a duration law (bytes timed to a fall, 2026-06-08) and a
slew law in dB/s (2026-08-24). Three readings: (a) the slew law is 2× too small,
making every E4B decay and release byte wrong since August; (b) `ENV_FULL_SPAN_DB`
is 2× too big; (c) the June timings were taken to an audible threshold near
−48 dB and only the comment claiming "a full fall to silence" is wrong.

(b) died on the span measured above. The remaining two were separated by
measuring a decay's dB/s **directly**, which depends on neither law:

| rate byte | measured dB/s | `ENV_RATE_SWEEP` | ratio |
|---:|---:|---:|---:|
| 60 | 47.35 | 46.59 | 1.016 |
| 72 | 23.00 | 23.65 | 0.973 |
| 80 | 14.78 | 15.05 | 0.982 |
| 90 | 8.47 | 8.55 | 0.991 |

Mean 0.991 ± 0.016. **(a) predicts 2.000 — off by 63σ. (c) predicts 1.000 — off
by 0.6σ.** A second observable from the same captures, the full fall time, lands
on (c) at all four bytes independently (byte 72: 4.25 s measured, (c) 4.07 s,
(a) 2.03 s). The two observables agree with each other, so the linear-accumulator
picture survives the test that could have broken it.

The implied threshold of the June timings, computed from these slopes, is
**47.9 dB, 48.9% of the span**, wandering 47.8–50.1% with no resolvable drift.
mpc2emu's own sharpest contribution was insisting this mattered: an arithmetic
10·log10-for-20·log10 slip must sit on **exactly** 50.00% at every byte, and a
measurement threshold need not. 48.9% with 2.3 points of wander is a threshold.
Their laws are both fine; the comment is wrong.

Caveat, and it is the rig's: the decay fits give r² 0.956–0.982 and the two fast
rates curve (rate 72 reads 29.5 dB/s in the first half of the fall and 15.5 in
the second). That is detector smearing — an 8192-sample window is 0.17 s, and at
47 dB/s the level moves 8 dB inside one window. The slow rates, where the window
is a small fraction of the fall, are straight to 4–9%. Smearing a straight line
preserves its mean slope while ruining its r², which is why the slopes survive.

### A structural link, and a claim retracted from inside it

§127's segment stepper walks a level accumulator by a fixed increment per tick.
Since the level field is now measured to be linear in dB, a fall to sustain 0
must be **straight in dB against time** — which is what the slow rates show. The
two laws are therefore not independent: `dB/s = dB-per-byte × bytes-per-second`,
and a full fall takes `span / (dB/s)`.

**Retracted from that argument: "the internal level resolution is 0.7720/32 =
0.0241 dB per unit".** The `>> 5` in `index = (field + modulation) >> 5` is on
the *rate* path — it truncates a fine rate-plus-modulation sum to a 128-entry
table index, so the fine bits are consumed and discarded there and never reach
the accumulator. The 32 bounds how finely modulation can steer the *rate*, not
how finely a *level* is held. `table[index] × ticks` constrains the accumulator's
width not at all. Worse than a wrong number: it was produced by arithmetic on two
correct numbers, in units nothing had been measured in. It never reached a
tracked file. (Caught by mpc2emu.)

### The amp gain table is not in the image

If the level byte indexed a gain lookup, consecutive entries would differ by a
constant ratio 10^(0.772/20) = 1.0929. A vectorised sliding log-linear fit over
every 64-entry window, as u16 and u32, big and little endian, at every byte
offset, across both the 4.62 and 4.70 bodies, finds **nothing** at 0.772 ± 3%
dB/entry with r² > 0.999 — while the same scan on equal-sized noise also finds
nothing, so the threshold is selective rather than merely strict. The gain is
computed, not tabulated. (A first pass at ±6% on the ratio returned dozens of
hits; ±6% admits 0.23–1.28 dB per entry, which is most smooth monotone data in a
2 MB image. A loose gate in a scanner is the same failure as a loose gate
anywhere else.)

### What the technique can and cannot do

The narrowband reach is bounded by the *source*, not the detector. This preset's
level wobbles ~1.5 dB/s, so widening the FFT past 2^16 spreads its energy across
more bins than the narrower bins remove noise from. Below byte ~20 would need a
synthetic steady tone. mpc2emu's corpus puts 132 voices (6.2%) in the unmeasured
non-zero tail with no single byte carrying more than 27, plus 485 (22.7%) at byte
0 where the conversion is silent either way — a tail, not a cluster, and not
worth a campaign.

### Units, still open

These sweeps drive the SysEx level parameter (0–100%); the writer writes the E4B
0–127 byte, and `SysEx% = byte × 100/127`. The lattice is real and visible: SysEx
90 and 80 are bytes 114 and 102, a 12-step where the neighbours are 13, and that
rung carries the largest residual in the first fit (1.21 dB). Fitting in the
units actually driven and converting the fitted law once is the right order, but
a few points driven **both** ways — SysEx parameter and preset-body byte — still
need to confirm the two paths land together before anything is fitted in byte
units for the writer.

## §137 — LFO→amplitude measured: the swing, the clamp, and the direction that was asserted backwards (2026-09-14, live)

`E4B_LFO_VOLUME_FULL_DB` sat in mpc2emu's code marked UNMEASURED since July.
Measuring it turned up three things, only one of which was the constant.

### Run 1 was clipped, not measured

First attempt, LFO→AmpVol at full cord depth with the unmodulated sustain at
100%:

| source | rate | peak | trough | depth | peak vs unmodulated |
|---|---:|---:|---:|---:|---:|
| `Lfo1~` | 20 | −4.59 | −59.35 | 54.77 | +7.70 |
| `Lfo1~` | 35 | −4.31 | −56.16 | 51.85 | +7.99 |
| `Lfo1+` | 20 | −4.13 | −13.85 | 9.72 | +8.17 |
| `Lfo1+` | 35 | −4.07 | −13.89 | 9.81 | +8.22 |

Every run peaks within 0.6 dB of the same value and the raw maximum is
**−3.96 dBFS in all four**, source and rate irrelevant. That is a clamp, and it
set the peak in every capture — so none of those depths is the modulator's.
The error: the unmodulated level was put at full and a modulator was then asked
to swing it *up*.

**But the clamp is itself a result.** A cord can drive the amp level roughly
**8 dB above what the envelope alone reaches**, and then it stops. That is the
headroom budget for any LFO→AmpVol cord, and it would otherwise be discovered as
clipping in somebody's converted bank.

### Run 2: unmodulated level mid-range, amount swept

Unmodulated level at SysEx 53 (~byte 67): 45.0 dB of room up to the sustain-100
level, 49.0 dB down to the floor. Amount swept 25/50/100 so the onset of
clipping appears in the data instead of being asserted afterwards. Depths from a
**sine fit** to the tracked envelope, not percentiles — p97−p3 folds the
tracker's own scatter into the depth and inflates small depths more than large
ones (it read amount 25 about 3 dB high).

| source | amount | peak-to-trough | tracker scatter | swing centre vs unmodulated |
|---|---:|---:|---:|---:|
| `Lfo1~` | 25 | 23.17 dB | 3.53 dB | +0.98 dB |
| `Lfo1~` | 50 | 47.65 | 2.70 | +1.30 |
| `Lfo1~` | 100 | *clipped* | | |
| `Lfo1+` | 25 | 23.15 | 3.54 | **+13.08** |
| `Lfo1+` | 50 | *clipped* | | |
| `Lfo1+` | 100 | *clipped* | | |

### The two sources have the same swing and differ only in where it sits

23.17 against 23.15 dB at amount 25 — the same number. The *centre* differs:
`Lfo1~` centres the swing on the unmodulated level (+0.98 dB), `Lfo1+` centres
it half a depth **above** it (+13.08 against a half-depth of 11.6).

At a positive amount, therefore:

- **`Lfo1+` (97) swings upward.** The peak rises a full depth above the
  unmodulated level and the trough barely moves. It costs the whole depth in
  headroom, not half, and clips any zone near full scale — which is what broke
  run 1.
- **`Lfo1~` (96) swings symmetrically**, costing depth/2 upward.

mpc2emu's `lfo_volume_depth_to_amount` docstring asserted the *downward* reading
from 2026-07-28 until 2026-09-01, when the assertion was found to rest on
nothing. It is now measured, and it was **backwards for both sources**.

### The depth law, and a question it raises about §133

Peak-to-trough is proportional to amount within 3% (0.927 dB per amount unit at
25, 0.953 at 50), extrapolating to **≈95 dB peak-to-trough at full amount**.

§133 puts cord modulation full scale at 132 bytes of destination field, measured
on a different destination. At §136's 0.7618 dB/byte that predicts **100.6 dB**.
Measured is 5% low, and the obvious explanation does not cover it: detector
smearing at window/period 0.143 attenuates a sine by **1.3%** (−0.11 dB),
computed from the Hann transform rather than guessed. So ~1.3 of the 5 points is
smearing and ~4 is not. What remains is either the 1.3% uncertainty on dB/byte or
**cord amounts scaling differently per destination** — §133's 132 bytes was
measured into a *rate* field and this is a *level* field, and nothing establishes
the scaling is shared. That is a live question for any converter: one
modulation-full-scale constant for all destinations, or one per destination.

For a writer: **0.95 dB peak-to-trough per unit of cord amount with `Lfo1~`**,
measured at amounts 25 and 50, extrapolated above. Never amount 100 with
`Lfo1+` from a normal sustain level.

### A confound that was real in shape and inert in fact

Cord 2 on P009 is `Lfo1~ → Pitch`. Changing the LFO rate drives it too, and a
pitch modulation walks the carrier out of a **fixed-bin** detector, which reads
as amplitude loss with nothing in the output looking wrong. Its amount was
already 0, so run 1 was not corrupted — but the measurement had no way of knowing
that until it looked. Read a shared modulator's other destinations before
changing it; zero and restore them.

### What the constant was actually for — nothing

mpc2emu grepped it on being asked what it meant: `E4B_LFO_VOLUME_FULL_DB` is
referenced by no reader, writer or codec, because **the E4B writer emits no
LFO→AmpVol cord at all**. It was not a stale constant, it was a missing feature:
`LfoVolume` is non-zero on 13,987 of 82,581 corpus instruments (16.9%) and all
of it is silently dropped — a class no diagnostic can see, because nothing in the
path reads the field.

The general form is mechanically findable, and mpc2emu built the audit: enumerate
every leaf tag real corpus files carry, check whether its name appears anywhere
in the reading path, rank by how many files carry a non-modal value. 174 distinct
tags, **114 never mentioned**, 69 of those never varying (harmless defaults). The
largest survivor is a **pitch envelope** — three tags, 7,238 instruments with
non-default values, and no pitch-envelope field in the data model at all.

**The question that found it was "what does this constant mean?", asked about
something that had looked maintained for months.**

## §138 — Is the level-law slope a property of the material? Mostly not (2026-09-14, live)

§136 left the measured slope 1.0–1.3% below mpc2emu's `0.7718 dB/byte`, with a
rep-to-rep repeatability of 0.035 dB — far too large to be scatter. Two candidate
explanations: the material (one preset, one voice, one sample) or the law.

### Carrier frequency: no effect

Same preset and voice, three notes over two octaves:

| note | f0 | slope | byte 0 | r² |
|---:|---:|---:|---:|---:|
| 40 | 41.02 Hz | 0.7575 | 95.98 | 0.999931 |
| 52 | 82.76 | 0.7599 | 96.24 | 0.999933 |
| 64 | 163.33 | 0.7601 | 96.26 | 0.999917 |

Spread 0.35%; byte-0 spread 0.28 dB. A 4:1 change in f0 is the thing that would
expose a detector-aim or carrier-dependent artefact, and it exposes nothing.

### Different material: about 1% of spread, all of it below 0.7718

Three different samples (the preset scan's f0 groupings separate P005–P009,
P010–P012 and P022–P023), floors taken before the note, carriers verified
against their own bin:

| preset | note | f0 | slope | byte 0 | r² |
|---|---:|---:|---:|---:|---:|
| P009 | 52 | 82.76 Hz | 0.7592 | 96.18 | 0.999952 |
| P012 | 64 | 327.39 | 0.7647 | 96.75 | 0.999891 |
| P023 | 64 | 329.59 | 0.7680 | 97.17 | 0.999858 |
| P009 | 52 | 82.76 | 0.7599 | 96.24 | 0.999939 |

Mean **0.7630 ± 0.0036** (0.47%), spread 1.15%. Byte-0 mean 96.59 ± 0.40.

So the material does contribute — 1.15% across samples against 0.35% across notes
of one sample — but it does not close the gap: **mpc2emu's 0.7718 sits above all
four measured values**, 0.5% above even the highest. Their `ENV_FULL_SPAN_DB`
97.82 likewise sits above every measured byte-0 intercept (96.18–97.17).

The practical size of the disagreement is under 1 dB everywhere in the byte
range, and their fit came from bytes 80–116 where the two laws are closest. The
constants are not being changed on this: one machine, one evening. But the
"it is probably the material" hypothesis is now tested and only partly true.

### The r² gate earned its place on its first run

Two of six configurations produced a slope and were rejected by r²:

- P010 note 64: slope **0.1863**, r² 0.747
- P022 note 52: slope 0.7461, r² 0.9989 (just under the 0.999 threshold)

Without the gate, 0.1863 would have entered the average. This follows the failure
in the previous run where **a configuration with no signal at all produced a fit**
— P009 voice 1 returned slope 0.0017 over ten rungs that each passed a >15 dB SNR
test, because the "floor" they were compared against was itself a mains line.
Only r² = 0.13 gave it away, and slightly noisier material would have returned a
plausible r² on a fit of nothing.

### The unifying failure, stated as a mechanism

Three separate failures tonight were one failure:

1. the floor located by `argmax` on silence (found 93.75 Hz mains hash, +19.97 dB)
2. the "carrier prominence" gate measured against the **median** bin — the median
   is −136 dBFS and a mains line at −86 clears it by 50 dB, so on a preset that
   did not sound the detector aimed at hum and passed its own sanity check
3. the floor-power over-correction that manufactured the §136 cliff

**`argmax` finds the largest thing in the band, and the question is always
whether the largest thing is the thing being measured.** The fix is never "use
argmax more carefully"; it is to compare against a reference taken through the
same bin with the signal absent — which turns *what is loudest* into *what
changed when I played a note*.

mpc2emu observed that this generalises past detectors: every measurement tonight
that held up was a difference against a reference through the same path, and
every one that failed was an absolute read.

### Rig properties worth reusing

- Presets 0–23 scanned at three notes for usable carriers; slot numbers only, no
  names read or logged.
- A carrier must clear **its own bin's pre-note floor by 60 dB** to be measured.
- The floor is captured **before** the note. Capturing it after let the previous
  configuration's release tail into it, and every preset but the first failed its
  own floor gate as a result.
- A note left sounding by a killed script raises the carrier bin ~11 dB while
  moving a broadband meter 0.4 dB (§136); All Notes Off belongs on every exit
  path including signal handlers.

## §139 — Cord full scale measured with a constant source: it is the destination's own range, and §133's 132 is retracted (2026-09-14, live)

§137 left the sharpest open question of the evening: §133 put cord modulation
full scale at **132 bytes** measured into a *rate* field, while the LFO→AmpVol
depth into a *level* field extrapolated to ~125 bytes. Either one constant does
not generalise across destinations, or two constants were being treated as one.

### The measurement, with the LFO taken out of it

`DC` (cord source 160) is a **constant** source. Routed to `AmpVol` it shifts the
level by a fixed amount, so there is no sine to fit, no period, no LFO shape and
**no detector smearing** — every complication that cost the LFO route its last
few percent. Sweep the cord amount, read the level shift, convert with §138's
0.7630 dB/byte.

P009 v0, note 52, sustain at SysEx 53 so the shift has room both ways (45.1 dB up
to the sustain-100 level, 53.5 dB down to the floor), amounts swept across both
signs:

| amount | level | shift | SNR | implied bytes |
|---:|---:|---:|---:|---:|
| −45 | −111.61 | −58.95 | −5.4 | *in the floor* |
| −30 | −82.24 | −29.58 | 24.0 | −38.76 |
| −20 | −71.92 | −19.26 | 34.3 | −25.24 |
| −10 | −62.68 | −10.02 | 43.5 | −13.13 |
| 0 | −52.66 | −0.01 | 53.5 | −0.01 |
| +10 | −43.24 | +9.42 | 63.0 | +12.34 |
| +20 | −33.72 | +18.94 | 72.5 | +24.82 |
| +30 | −24.19 | +28.47 | 82.0 | +37.32 |
| +45 | −9.54 | +43.12 | 96.7 | +56.52 |
| +60 | −3.21 | +49.45 | 103.0 | *at the clamp* |

Over the 8 rungs that are neither clamped nor in the floor:

**shift = 0.96442 dB per unit of cord amount, r² 0.999917**, offset −0.29 dB.

At +100%: **96.44 dB = 126.4 bytes** of level field.

### The simpler reading: full scale is the destination's own 0–127 range

126.4 bytes against the destination's full range of 127 is a **0.5% agreement**.
The LFO route's ~125 bytes agrees too, by a method sharing nothing but the
destination. So the natural statement is:

> **A ±100% cord moves its destination across the whole of its own range.**

That also dissolves a puzzle §133 raised about itself. §133 noted that "132 bytes
slightly exceeds the 0–127 index range" and used the excess to explain why a
±100% cord saturates at every note. It does not exceed the range — **it is the
range**, and the excess was extrapolation error.

### Why §133's 132 is the number to doubt, not this one

§133's figure came from a full-span source sweep at **cord amount 10%**, giving
−13.20 bytes, multiplied by ten. A ×10 extrapolation carries any error in the
10% measurement ten times over, and 132/127 = 1.04 is well inside what a 4%
error at 10% amount would produce. This measurement extrapolates ×2.2 from its
furthest clean rung, over eight rungs spanning both signs at r² 0.999917.

**So §133's 132 bytes is retracted in favour of 127 (the destination range),
pending a re-measurement of the rate destination by this method.** What is NOT
established is that rate and level destinations share the scaling — that needs
`DC → FilFreq` or `DC → an envelope rate` measured the same way. The
per-destination question is still open; what has changed is that the evidence
for a *difference* was an extrapolation artefact, not a measured difference.

Note the direction is robust to which dB/byte is used: with mpc2emu's 0.7718
instead of ours, the figure becomes 125.0 bytes — further from 132, closer to
nothing else. Choosing their constant strengthens the retraction.

### Two guards failed and both were about restoring state

1. **The 60 dB carrier-prominence gate fired at 59.6 dB on a good carrier**,
   because it was applied to a reference deliberately set 45 dB *below* the top.
   The gate asks "is there a signal here" and belongs at sustain 100; applied to
   a reduced reference it asks a different question. Moved.
2. **A gate that fires before the restore line leaves the machine modified.**
   The failed run exited at the prominence check with the scratch cord still set,
   and — worse — with cord 5's amount still zeroed. The *next* run then read that
   zero as the original value and faithfully restored it. **State loss cascaded
   through a restore that was working correctly**, because "the original" was
   read from a machine a previous run had already changed.

   Fixes: restore registered with `atexit` so it runs on every exit path
   including a gate's `SystemExit`; the scratch cord cleared *before* asserting
   it is free rather than asserting and dying; and known-good values taken from a
   **verified record** rather than from the machine when a previous run may have
   touched it. Cord 5 was restored to `FEnv+ → FilFreq` amount 100 from the 22:31
   verification.

   This is the same lesson as the killed-script stuck note (§136), one level up:
   there, a crash left the *machine* wrong; here, a crash left the *idea of what
   is correct* wrong, which survives longer and is harder to see.

## §140 — §139's retraction of §133 is itself withdrawn: the rate destination measures 132, and the method cannot tell 132 from 127 (2026-09-14, live)

§139 retracted §133's 132-byte cord full scale in favour of 127, on the strength
of a level destination measuring 126.4. **That retraction was premature and is
withdrawn.** §133's figure stands.

### The rate destination, measured by §139's own clean method

`DC → VEnvDcy` (destination 74, an envelope *rate*), base rate byte 72, cord
amounts ±5 and ±10. A rate destination is read through the byte↔dB/s mapping,
which tonight's four decay slopes (§136) supply:

| rate byte | 60 | 72 | 80 | 90 |
|---|---:|---:|---:|---:|
| dB/s | 47.35 | 23.00 | 14.78 | 8.47 |

Log-linear fit: **d(ln rate)/d(byte) = −0.05728**, r² 0.999510.

| amount | rate / base | byte shift |
|---:|---:|---:|
| −10 | 0.4852 | +12.63 |
| −5 | 0.7262 | +5.59 |
| +5 | 1.5560 | −7.72 |
| +10 | 2.2021 | −13.78 |

**byte shift = −1.3223 per amount unit, r² 0.99945 → 132.2 bytes at ±100%.**

That is §133's 132 to 0.2%, by a method sharing nothing with it — §133 swept a
*source* at 10% amount and multiplied by ten; this holds a *constant* source and
sweeps the amount. Two independent routes to a rate destination both land on 132.

### But the method cannot resolve the question it was built to answer

The rate figure passes entirely through that calibration constant, and it is far
more sensitive to it than the r² suggests:

| d(ln rate)/d(byte) | implied full scale |
|---|---:|
| −0.0553 | 137.0 bytes |
| −0.0556 | 136.2 |
| −0.05728 *(fitted)* | 132.2 |
| −0.0603 | 125.6 |

The three alternatives are the *interval* slopes between adjacent calibration
points — all defensible readings of the same four measurements. They span
125.6–137.0, which **straddles both 127 and 132**. So this measurement supports
132 but cannot exclude 127, and the spread is the same size as the effect being
measured.

The level destination has no such problem: 126.4 bytes comes from dB read
directly against the level law, with no rate calibration in the path.

### Where this actually leaves it

| destination | full scale at ±100% | how direct |
|---|---:|---|
| `AmpVol` (level) | 126.4 bytes | direct; dB → bytes via the level law |
| `VEnvDcy` (rate) | 132.2 ± ~5 | via a 4-point byte↔dB/s calibration |
| §133, a rate destination | 132 | source sweep at 10% amount, ×10 |

**Two rate measurements sit near 132 and one level measurement sits at 126.4**, so
a per-destination difference of ~4.6% is *supported* — but it is not established,
because the rate number's uncertainty overlaps the level number. §139's clean
story ("a cord moves its destination across its own 0–127 range") is attractive
and may be right for level destinations; it is not demonstrated for rate ones.

**For a converter: keep §133's 132 for rate destinations and use 126.4 for level
destinations, and treat the difference as provisional.** Closing it needs the
byte↔dB/s calibration measured properly — more rate bytes, and slow ones where
§136's smearing does not flatten the fall — not more cord sweeps.

### The error, which is the fourth of its kind today

`−0.0565` was a **hand-average of three interval slopes** read off a table, where
`−0.05728` is the least-squares fit of the same four points. A 1.38% difference,
which propagated straight into the byte shift.

That is the same failure as §137's withdrawn `0.0241 dB/unit`: a number arrived at
by arithmetic I performed rather than by a fit or a measurement, then used as
though it carried the authority of the data behind it. Here it was worse than
cosmetic — it turned 132.2 into 134.0, which read as "not 132", which is what
prompted §139's retraction of a correct value in the first place.

**And the shape of the mistake: §139 retracted a measured number in favour of a
rounder one that fitted a nicer story.** 127 is the destination's own range and
explains saturation neatly; 132 explains nothing and looks like an error. The
tidier hypothesis was wrong, and it was believed because it was tidier. VinSamLib
had already observed the converse of this today — an anomaly that gets an
explanation built on top of it stops being an anomaly. This is the same trap
entered from the other side: an anomaly *dissolved* by a tidier reading is just
as dangerous, and neither §139 nor §133 had the measurement needed to choose.

## §141 — The per-destination question, closed as an interval rather than an answer (2026-09-14, live)

§139 said cord full scale is 127 for all destinations. §140 withdrew that and
leaned toward a real rate-versus-level difference. **Both were premature.** With
the calibration measured properly, the data does not distinguish them, and this
section records the interval rather than picking a third story.

### The calibration, measured densely and locally

§140's rate figure swung 125.6–137.0 bytes depending on which
`d(ln rate)/d(byte)` was used, and I filed that spread as uncertainty. **It was
not uncertainty. §134 had already established the rate law is piecewise**, so a
global slope cannot exist and the "defensible readings" I averaged were the
curvature disagreeing with itself. The constant needed was the *local* slope over
the bytes the cord sweep actually reached (58–85 around a base of 72).

Measured: eight rate bytes 58–86, each twice, note 64 so a 4096-sample window is
85 ms and still spans 14 carrier cycles — half the smearing of §136's 8192 window
at 82 Hz, which had flattened exactly the fast end of this calibration.

| byte | 58 | 62 | 66 | 70 | 74 | 78 | 82 | 86 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dB/s | 53.89 | 39.73 | 32.19 | 25.54 | 20.51 | 16.47 | 12.96 | 10.43 |
| repeat | 54.43 | 39.73 | 32.09 | 25.70 | 20.52 | 16.44 | 12.94 | 10.45 |

Repeatability 0.5%. Log-linear fit −0.05761 (r² 0.998282); quadratic term
+0.000175/byte², which varies the local slope 8.5% across ±14 bytes — so the
curvature is real and worth handling exactly rather than averaging.

**Cross-check worth keeping: this calibration was taken at note 64 and the cord
run at note 52.** Interpolated to byte 72 it gives 22.76 dB/s against the cord
run's measured 22.89 — **0.58% apart, so the envelope rate law is
note-independent** and calibrations transfer between notes. That is a free result
and it validates using one carrier to calibrate another.

### The rate destination, with curvature inverted rather than averaged

Inverting the quadratic calibration per rung instead of applying one slope:

| amount | dB/s | effective byte | shift |
|---:|---:|---:|---:|
| −10 | 11.10 | 84.97 | +13.06 |
| −5 | 16.62 | 77.55 | +5.65 |
| +5 | 35.61 | 64.40 | −7.50 |
| +10 | 50.40 | 58.73 | −13.17 |

**−1.3122 bytes per amount unit → 131.2 bytes at ±100%.**

### The two numbers, with their uncertainties propagated

| destination | full scale | ± |
|---|---:|---:|
| `VEnvDcy` (rate) | 131.2 bytes | ±3.9 |
| `AmpVol` (level) | 126.4 bytes | ±0.5, +1.6 from the dB/byte constant |

**Difference 4.8 ± 4.3 bytes = 1.1σ. Not significant.**

Both are consistent with 127. They are also consistent with each other. And they
are consistent with a ~4% difference. **The measurement does not choose**, and
saying so is the result.

The rate figure's error bar is not noise: its residuals run +0.43, −0.42, −0.45,
+0.44 — a symmetric U, so the cord's own response to amount has slight curvature.
Quoting it as ± is a convenience; the shape is real and would need more rungs to
characterise.

### What this section is actually for

Three sections have now been written about one number. §139 asserted 127 because
it was tidy. §140 leaned to a difference because 132.2 landed near §133's 132.
Both times a measurement got attached to whichever story it sat nearest, and both
times the interval would have said *not yet*.

**The useful output of a measurement whose uncertainty spans the candidates is
the interval, not the nearest candidate.** For a converter: the choice between
127 and 132 changes a cord depth by 4%, which is below what the rest of the
conversion chain justifies — use either, note which, and do not spend more bench
time here. If it ever matters, the measurement that would settle it is more cord
rungs (to pin the cord's own curvature) rather than more calibration.

VinSamLib's standing rule from tonight, with the amendment this section earned:
*a measurement with its uncertainty propagated beats a tidy number — and check
whether the uncertainty is uncertainty, or a result you have not recognised yet.*
Here it was both: §140's spread was unrecognised curvature, and what remains
after removing it is genuine and still too wide to choose with.

## §142 — The assignable MIDI controller sources: eight of them, CC number stored directly, and it is a GLOBAL setting (2026-09-14, live)

Asked by mpc2emu, who needed a second continuous-controller source to carry the
K2000's data-entry slider alongside the mod wheel. Answered from the parameter
table plus a read-only hardware query; nothing was written.

### There are eight, and their ids are not contiguous

`MidiA` 20, `MidiB` 21, then `MidiC`–`MidiH` 32–37. (Also in the same family but
fixed in meaning: `MidiVl` 26 volume, `MidPn` 27 pan, `Pedal` 19, `FtSw1/2` 22/23,
`Thumb` 38.)

### The CC assignment is a MASTER parameter, not a preset one

Ids **208–215**, `MIDIGLO_MIDI_A_CONTROL` … `_H_`, category `master.midi`.
`MIDIGLO` is MIDI *global*. So **a preset file cannot carry it** — it is a machine
setting the user configures once, and any conversion that relies on a particular
letter must document the required assignment rather than write it.

The same applies to ids 201–207: Pitch, Mod, Pressure, Pedal, Switch 1/2, Thumb.

### The stored value IS the CC number

The declared range is −1..33, which is not a CC range, and the table the
parameter notes point at — `MIDI_CONTROL_DISPLAY` — **is referenced by ten
parameters and defined nowhere in this tree.** A transcription gap, now closed by
measurement instead.

Read from the machine (read-only; these are Jan's settings):

| id | name | value |
|---:|---|---:|
| 201 | Pitch | 32 |
| 202 | Mod | 1 |
| 203 | Pressure | 33 |
| 204 | Pedal | 3 |
| 205 | Switch 1 | 0 |
| 206 | Switch 2 | 1 |
| 207 | Thumb | 2 |
| 208–215 | MIDI A–H | 21, 7, 23, 24, 25, 26, 27, 28 |

**MIDI F = 26 and MIDI G = 27**, which Jan independently described as "MIDI F
(CC 26) and G (CC 27)", and §133 drove CC 26 through `MidiF` and got the expected
modulation. `Mod = 1` is CC 1, the canonical mod wheel. So:

> **value 0–31 = MIDI CC 0–31; 32 = pitch wheel; 33 = channel pressure; −1 = off.**

Which means EOS restricts assignable controllers to **CC 0–31 only** — the
continuous-controller MSB range — not arbitrary CC numbers. Anything at CC 32 or
above cannot be reached by these sources at all. That is a real constraint on any
converter mapping controllers in.

### `C_nAmt` — a cord can modulate another cord's amount, for any n

`CORD_DESTINATIONS` documents `C00Amt`–`C03Amt` at **168–171**, and §95/§98
measured `ModWheel → 176` driving the amount of **cord 8** on hardware.
168 + 8 = 176, so the rule is:

> **destination `168 + n` sets cord *n*'s amount.**

The spec transcribes only n = 0–3; hardware confirms n = 8. So the "gate a depth"
cord shape is available for any cord, not just the first four.

### The factory mod-wheel pattern, read off a loaded preset

On P009 voice 0:

    cord 1   PitWl  (16) -> Pitch      (48)   amount 6
    cord 2   Lfo1~  (96) -> Pitch      (48)   amount 0
    cord 3   ModWl  (17) -> C02Amt    (170)   amount 13

Cord 3 gates cord 2's depth: **the mod wheel brings in LFO vibrato**, which is the
classic template and confirms mpc2emu's reading that the wheel's job is gating a
depth range rather than driving a parameter.

**On their +8 versus +16 divergence.** SysEx amounts are ±100 where file bytes are
±127, so file byte = SysEx × 127/100:

- `PitWl → Pitch` reads 6 → 7.6 file bytes ≈ **8**, matching their corpus exactly.
- `ModWl → C02Amt` reads 13 → **16.5 file bytes**, matching their template's +16,
  not their corpus's +8.

One preset on one machine is not a factory default, and this bank's provenance is
unknown — so this is a data point, not a ruling. But it does mean the template's
+16 is not obviously wrong, and that the two values may be different generations
of the same template rather than an error.

### §142 addendum — the factory defaults, from the firmware image

The table in §142 above is **Jan's configuration, not the factory defaults** — a
distinction that nearly got baked into mpc2emu's format doc. The defaults are in
the firmware, byte-identical in 4.62 (body `0x12dfa2`) and 4.70 (body `0x1dcff8`):

```
32  1  33  4  5  6  20  21  22  23  24  25  26  27  28
```

Exactly fifteen values, matching the fifteen assignment parameters 201–215 and the
manual's "up to 15 controllers". Read in parameter order:

| parameter | firmware default | Jan's machine | |
|---|---|---|---|
| 201 Pitch | pitch wheel | pitch wheel | |
| 202 Mod | CC 1 | CC 1 | |
| 203 Pressure | chan pressure | chan pressure | |
| 204 Pedal | CC 4 | CC 3 | changed |
| 205 Switch 1 | CC 5 | CC 0 | changed |
| 206 Switch 2 | CC 6 | CC 1 | changed |
| 207 Thumb | CC 20 | CC 2 | changed |
| 208 MIDI A | CC 21 | CC 21 | |
| 209 MIDI B | CC 22 | **CC 7** | changed |
| 210–215 MIDI C–H | CC 23–28 | CC 23–28 | |

The next five bytes are `29, 91, 92, 93, 94` — 91–94 are the MIDI effects-send
controllers, so the block continues into other global defaults.

**MIDI A–H = CC 21–28 is the factory assignment.** mpc2emu predicted exactly that
from the read-back, reasoning that seven values sat on a contiguous run and the
one break landed on CC 7 (MIDI Volume), which no factory block would do. The
firmware confirms it, and also shows Jan has moved Pedal, both switches and Thumb
onto CC 0–3.

This also validates the value encoding independently: `32` and `33` appear in the
default block exactly where Pitch and Pressure are, which is what the
"32 = pitch wheel, 33 = channel pressure" reading predicts.

**Note the trap avoided.** A read-back from one machine looks exactly like a
factory table until something in it is obviously hand-set. Seven of eight values
agreeing with the firmware would have made the eighth look like a firmware
variation rather than a user edit, had the image not been available.

### §142 addendum — EOS does not appear to implement RPN/NRPN

The open question on the CC 6 mapping was whether EOS consumes it as Data Entry
MSB. RPN and NRPN cannot be implemented without recognising **both** selector
pairs — CC 98/99 (NRPN LSB/MSB) and CC 100/101 (RPN LSB/MSB). In the 4.70
disassembly:

| controller | immediate compare sites |
|---|---:|
| CC 1 | 271 |
| CC 7 | 53 |
| CC 27 | 26 |
| CC 98 | 1 (a 32-bit `cmpl`, not a controller test) |
| **CC 99** | **0** |
| CC 100 | 17 (all 32-bit `cmpl #100` — percentage comparisons) |
| **CC 101** | **0** |

EOS dispatches controllers by comparison (CC 1 alone has 271 sites), so the total
absence of 99 and 101 is meaningful rather than an artefact of table-driven
dispatch. **CC 6 should therefore fall through to the generic continuous-controller
path**, making it safe to recommend for an assignable source.

Stated as the weaker evidence it is: this is a negative from a linear disassembly
whose data regions decode as noise, and a jump-table dispatch would leave no
compares at all. A controller sweep on hardware would be stronger. But a
*positive* — CC 6 special-cased — would have killed the recommendation, and it is
not there.

## §143 — Vel+ → Filter Freq: a cord moves BYTES, not cents — and that settles §139/§140/§141 (2026-09-15, live)

Commissioned by mpc2emu, who carry `VEL_FILTER_FULL_CENTS = 9120` marked NOMINAL.
It is not an independent measurement — it is `FILTER_ENV_FULL_CENTS = 4383`
multiplied by the Vel+ source's 2.08-unit span, so it inherits that constant's
base. Their question was the right one: **is a full cord worth a fixed number of
cents at all, or does the span depend on where the corner starts?**

Method as §125: P013 v0, flat noise, note 24 root-matched, LP2, Q 0, every cord
reaching Filter Freq zeroed, one cord Vel+ → Filter Freq. The span is a *ratio*
of corners, 1200·log₂(f₁₂₇/f₁), so it needs no cutoff law — only the same
corner-finding at both velocities.

### Run 1 measured the capture, not the machine

`+100%` at bases 40/70/100 all pinned at 24000 Hz — **the capture's Nyquist, not
the machine's ceiling.** All three were lower bounds and said nothing about
base-dependence, which was the entire question. Saturation detection caught it
(the corner at FMORPH 255 with no cord was measured first, and every full-amount
rung landed there), so the run reported lower bounds rather than three plausible
and meaningless cents figures.

### Run 2: nine rungs, amounts that cannot saturate

| base | amt | f(vel 1) | f(vel 127) | cents | Δbyte |
|---:|---:|---:|---:|---:|---:|
| 40 | 12 | 252.0 | 392.6 | 767.8 | 26.3 |
| 70 | 12 | 398.4 | 673.8 | 909.6 | 31.7 |
| 100 | 12 | 697.3 | 1031.2 | 677.5 | 25.5 |
| 40 | 25 | 252.0 | 720.7 | 1819.5 | 63.1 |
| 70 | 25 | 398.4 | 1048.8 | 1675.6 | 60.7 |
| 100 | 25 | 697.3 | 1669.9 | 1512.0 | 60.9 |
| 40 | 50 | 252.0 | 1710.9 | 3316.3 | 124.1 |
| 70 | 50 | 410.2 | 2777.3 | 3311.4 | 126.1 |
| 100 | 50 | 697.3 | 6375.0 | 3831.2 | 125.9 |

Δbyte is the measured corner converted back through §125's law.

**In cents the same data spreads 9.5%; in bytes it spreads 1.6%** (amount 50) and
3.9% (amount 25). The amount-12 rungs are noisy in both — the smallest shift, so
corner-finding resolution dominates.

> **The cord moves the FMORPH byte by a fixed amount independent of base. The
> cents span varies only because the byte→Hz law is not a uniform number of cents
> per byte.** `VEL_FILTER_FULL_CENTS` as a single constant is the wrong shape of
> model, exactly as mpc2emu suspected.

Round-trip self-check on the inverse law: setting FMORPH 40/70/100 and recovering
the byte from the measured corner gives 40.0 / 67.2–68.9 / 101.0 — accurate to
±3 bytes on shifts of 60–126.

### The number, and it kills "always 127 bytes"

Six well-resolved rungs: **2.485 ± 0.041 bytes per amount unit (1.6%)**, so a
**+100% cord moves 248 bytes of FMORPH — 97.4% of its 0–255 range.**

| destination | measured at ±100% | its range | ratio |
|---|---:|---:|---:|
| `AmpVol` (level) §141 | 126.4 | 127 | 99.5% |
| `VEnvDcy` (rate) §141 | 131.2 | 127 | 103.3% |
| `FMORPH` (filter) | 248.5 | 255 | 97.4% |

**§141 could not distinguish "a cord spans its destination's range" from "a cord
is worth a constant ~127 bytes", because both its destinations happened to have a
range of 127.** FMORPH has twice that, and gives 248 — so the constant-bytes
reading is dead and the destination-range reading is confirmed on a case that can
tell them apart. Mean ratio across three destinations: 100.1% ± 2.4%.

That is §139's claim, which §140 withdrew and §141 left open. **§139's conclusion
was right and its reasoning was not** — it asserted the tidy story from a single
127-range destination that could not discriminate. The claim is safe now because
of a test §139 never ran, not because §139 was vindicated. §133's 132 and §141's
interval stand as fair readings of what was known then.

### `9120` is larger than the filter's entire tuning range

From §125's law plus the panel's own 18334 Hz at FMORPH 251:

```
byte  20 ->   199.2 Hz          byte 20 -> 235   6417 cents
byte 235 ->  8109.4 Hz          byte 20 -> 251   7829 cents
byte 251 -> 18334   Hz (panel)
```

**The whole FMORPH range spans about 7829 cents. 9120 is ~1291 cents more than
the filter can travel at all.** So the constant is not merely base-dependent — no
base makes it reachable. Any conversion asking for 9120 cents of velocity→filter
depth gets a fully-open filter and the remainder is discarded.

### What a writer should do instead

Convert the source's velocity→filter depth to a **byte shift**, not a cents span:
`amount = Δbyte / 2.485`, with Δbyte obtained from the base cutoff and the target
cutoff through the §125 law — the same base-dependent treatment
`e4xt_cents_to_cord_amount` already applies to the filter envelope. A cents-based
constant cannot be made correct by re-measuring it, because the quantity it names
is not constant.

### Rig note

Reading cords past a preset's actual count returns sentinels, not zeros: P013
cords 18–23 read `src -1`, `amt 16383` (0x3FFF). A scan that treats those as real
cords will find nonsense destinations. Stop at the preset's cord count, or reject
`amt 16383`.

## §144 — mpc2emu's composed Vel<→attack law survives falsification; two artefacts both faked the failure (2026-09-15, live)

mpc2emu built a law by composing two results and asked for it to be broken rather
than confirmed — the right request, since the composition was of §143 ("a cord
spans its destination's range") and the exponential attack-byte law, neither of
which was measured on this route:

```
span = t(vel 1) / t(vel 127) = exp(ENV_RATE_K × 1.27 × amount)
       amount 28% -> 7.89×      amount 50% -> 40.0×
```

The destination id checks out from our own transcription rather than their
documentary ordering: `73 = VEnvAtk` (0x49) and `74 = VEnvDcy` (0x4A), so the
manual's order and the independently decoded cord agree with the table.

### Magnitude: confirmed, ~8% low

P013 v0, flat noise, note 24, filter wide open, every cord reaching a Vol-Env
rate destination zeroed, one cord `Vel< → VEnvAtk`, base attack byte 30:

| amount | t(vel 1) | t(vel 127) | span | predicted |
|---:|---:|---:|---:|---:|
| 0 | 0.165 | 0.165 | **1.00** | 1.00 |
| 10 | 0.379 | 0.165 | 2.29 | 2.23 |
| 28 | 1.280 | 0.171 | 7.50 | 7.89 |
| 50 | 6.293 | 0.171 | 36.88 | 40.00 |

The amount-0 control gives exactly 1.00. `t(vel 127)` is constant across all
amounts, which confirms `Vel<` delivers zero at full velocity and full source at
velocity 1 — so the span is set by the full source value, as the model assumes.

### Base-independence: holds, but only after two artefacts were removed

This is the half that looked false twice.

**Take 1 (bases 20–75) appeared to show strong base-dependence** — span falling
8.16 → 6.65 → 3.78. It was truncation: at bases 60 and 75 the envelope never
reached its plateau inside the capture, so the rise read short. The tell was
impossible rather than statistical — **base 75 gave `t(vel 1)` SHORTER than base
60**, which no monotone rate law permits. Plateau equality between the two
velocities (same envelope target, only the rate differs) rejects both cleanly:
ratios 0.849 and 0.215 against ~1.01 for the valid rungs.

**Take 2 (bases 10–50) appeared to show it again at the fast end** — span 11.71 at
base 10 against ~7.2 higher up. That was the *denominator*: `t(vel 127)` is 37 ms
against a 5.3 ms analysis window, seven samples across the whole rise. The plateau
gate protected the numerator and nothing protected the divisor.

**Both artefacts bias in the same direction as the hypothesis under test.** A
truncated numerator makes the span read short at high bases; a quantised
denominator makes it read long at low bases. Either alone reads as
base-dependence, and together they manufacture a clean monotone trend across the
full sweep. That is the configuration to design out rather than correct for.

With both gates applied — plateau ratio ≥ 0.97 **and** denominator ≥ 25 windows:

| base | span |
|---:|---:|
| 26 | 7.26 |
| 34 | 7.74 |
| 42 | 6.78 |
| 50 | 7.12 |

**mean 7.23 ± 0.35 (4.8%)**; trend with base −0.017/byte, i.e. −0.41 across the
range against a scatter of ±0.35. **Base-dependence is not resolved.** The
composition's surprising half stands, over the range that can be measured.

### The 8.4% shortfall decomposes into the two ingredients

Implied exponent `ln(span)/amount = 0.07064`; predicted `0.0581 × 1.27 = 0.0738`.

- their `ENV_RATE_K` 0.0581 against our measured 0.0576 (§141): 0.9% high
- their 1.27 bytes/amount-unit against 1.226 implied here: 3.5% high

Compounded over amount 28 that is ~9%, against the ~8% observed.

### A fourth destination for the range rule

`0.07064 / 0.0576 = 1.226` bytes per amount unit → a +100% cord into `VEnvAtk`
moves **123 bytes, 96.6% of its 127 range.**

| destination | at ±100% | range | ratio |
|---|---:|---:|---:|
| `AmpVol` (level) | 126.4 | 127 | 99.5% |
| `VEnvDcy` (rate) | 131.2 | 127 | 103.3% |
| `FMORPH` (filter) | 248.5 | 255 | 97.5% |
| `VEnvAtk` (rate) | 122.6 | 127 | 96.6% |

**Mean 99.2% ± 2.6% across four destinations**, two ranges and three parameter
families. §143's rule holds on every case tested.

### Why this one is base-independent while §143's filter cord is not

Both are the same cord behaviour — a fixed byte shift. The difference is what the
byte means downstream. A *ratio of times* against an exponential byte→time law
cancels the base exactly. A *span in cents* against the filter's byte→Hz law does
not, because that law is not a uniform number of cents per byte (§125). The cord
is base-independent in both cases; only the unit the answer is quoted in decides
whether the base survives.

### §144 addendum — the two runs agree to 0.02%, and attack shares the decay rate law

mpc2emu read the amount sweep (7.50 at amount 28) and the base sweep (mean 7.23)
as a 3.7% disagreement and chose between them. **They do not disagree.**

The amount sweep was taken entirely at base 30. The base sweep brackets it:

```
base 26 -> 7.26      base 34 -> 7.74
interpolated to base 30:  7.50
amount sweep at base 30:  7.50      -0.02%
```

The 3.7% is a single-base measurement compared against a **multi-base mean**, not
two measurements of the same thing disagreeing. So the choice is not between rival
numbers: `0.07206` is the exponent **at base 30**, `0.07064` is the **mean over
bases 26–50**. Both are correct answers to different questions, and the gap sits
inside the base sweep's own 4.8% scatter.

For a writer applying the constant across arbitrary presets the multi-base mean is
marginally the better estimator, but the difference is 4% in span and nothing
downstream resolves that, so either is defensible.

**The amount-10 exclusion is justified, for a better reason than "noisiest
point".** Its denominator — the unmodulated time at byte 30 — was measured as
0.165 s, where the base sweep's own byte→time law interpolates 0.176 s, 6.1% low.
A small span amplifies denominator error directly: corrected, amount 10 gives
exponent 0.0766 rather than 0.0829, most of the way to the 0.0720 of the other
two. It is denominator scatter, not a small-amount nonlinearity.

**Free result: attack and decay share one rate law.** The base sweep's
`t(vel 127)` values *are* the unmodulated attack times at byte = base, so they
measure the attack byte→time law directly:

| byte | 26 | 34 | 42 | 50 |
|---|---:|---:|---:|---:|
| t | 0.144 | 0.208 | 0.368 | 0.565 s |

`d(ln t)/d(byte) = 0.05841` over bytes 26–50, against the **decay** rate constant
`0.05760` measured over bytes 58–86 (§141) — **+1.4%**. Two different envelope
segments, two disjoint byte ranges, one law. Consistent with §127's single shared
rate table being read by every segment.

(Fitting all six bases gives 0.06694, but bytes 10 and 18 are the
resolution-limited rungs — 7 and 14 windows across the whole rise. The clean four
give 0.05841. The same points that faked base-dependence also steepen this fit.)

**Correction to the range-rule figure above.** §144 divided by 0.0576, the *decay*
constant measured over a different byte range. Using the attack law from the same
run is self-consistent: `0.07064 / 0.05841 = 1.209` bytes per amount unit → **121
bytes, 95.2% of 127** (or 97.1% on the amount-sweep exponent). The four-destination
mean becomes 98.8% ± 2.9% rather than 99.2% ± 2.6% — the rule is unaffected, but
the divisor should come from the same measurement rather than a neighbouring one.

## §145 — The amp RELEASE measured: one straight line in dB, and a detector that anchored to the attack (2026-09-18, live)

mpc2emu asked whether the E4XT's release on a high-sustain program matches their
writer's two-segment model, and whether the shape or only the scale is wrong.
Subject: P003 v0, a converted pad with sustain at 100%. RAM only, nothing saved.

### The read-back confirms the writer

```
Atk1 0/100%   Atk2 0/100%   Dcy1 0/100%   Dcy2 0/100%
Rls1 rate 86 / level 71%      Rls2 rate 15 / level 0%
no cords reach any Vol-Env destination (72/73/74/75)
```

Through our own measured laws: level 71% → byte 90 → **28.1 dB below peak**
(against their inferred `_ENV_SHAPE_KNEE_DB = 29.0`), and rate 86 → **10.5 dB/s**
(§141 measured 10.43/10.45 directly at that byte). So segment 1 = 28.1 dB at
10.5 dB/s = 2.67 s predicted, 2.77 s measured. **The constants their block marks
as "INFERRED … NOT hardware-confirmed" are confirmed.**

### The release is a single straight line in dB

With `Rls2` swept to 86 (equal to `Rls1`), drops every 2 dB, three reps:

| fit | value |
|---|---|
| straight-line fit, −2 to −26 dB | **11.004 dB/s**, r² 0.99879, max resid 0.43 dB |
| rate law prediction for byte 86 | 10.51 dB/s (ratio 1.047) |
| −20 to −50 dB, from the rate sweep | 11.34 dB/s |

So from −2 dB to −50 dB the release is **one straight line at ~11 dB/s** with no
knee anywhere. This extends §136's "the envelope is linear in dB" to the release
segments, and §141's rate law to a release destination — segment 2's measured
rate tracks the law to 3–9% (Rls2 80 → 14.88 vs 14.51; Rls2 86 → 11.43 vs 10.51).

Reachability: the sustain sits at −24 dBFS, so −60 dB below it is under the
capture floor. Everything here is bounded at −50 dB.

### The knee earns nothing on this material

```
MPC reference, −20 to −60 dB:   11.40 dB/s
E4XT at Rls2 = 86, −20 to −50:  11.34 dB/s      0.5% apart
```

At `Rls2 = 86` both segments run at the same rate, which is simply a straight
release — and it matches the reference's whole middle and tail. mpc2emu's
conclusion: `_ENV_SHAPE_BREAK_TIME` should be **removed** for high-sustain
sources rather than retuned. A simpler writer, not a better-calibrated one.

### The detector failure, which produced two false mechanisms before one true one

Two captures of an **unchanged** segment 1 disagreed by 0.6 s. I proposed two
physical causes for that and both were wrong:

1. **"mpc2emu's numbers are pan-contaminated"** — withdrawn. Their script
   power-sums; pan was never the mechanism, and I offered it before testing it.
2. **"the sustained level ripples 16 dB"** — withdrawn. That was measured over
   t = 1.2–6.0 s of a *four-second* note, so almost entirely attack and
   filter-envelope transient. A 25 s hold shows the sustain steady to **2.09 dB**
   with −0.14 dB of drift.

The actual cause was the instrument: **my note-off detector took the sustain as
"median of points within 1 dB of the PEAK".** On a pad whose filter envelope makes
the attack louder than the sustain, that selects attack points only, and note-off
landed ~2.7 s into a 20 s note.

**A broken measurement produces a plausible mechanism faster than it produces an
obvious error** (mpc2emu's phrasing, and they hit the same shape twice the same
day). Both of my proposed mechanisms were physically real effects — pan does
exist, transients do exist — which is exactly why neither looked like a mistake.

The fix, and it is the method to reuse:

- **sustain = median over the last 2.5 s before the scheduled note-off**, not
  anything derived from the peak
- **note-off = first point after that window falling 1 dB below the sustain**
- **the reference level is the sustain median**, so a ~2 dB tremolo ripple cannot
  move every threshold with it
- the MIDI schedule is a fine **prior** — measured latency here is +0.06 to
  +0.19 s, small and stable; search near it and refine in the audio

Rep-to-rep spread went from 0.6 s to **0.017–0.094 s**, and 4 s and 20 s holds
then agreed to 0.1 s — so hold length, the third mechanism I was about to blame,
never mattered either.

### A note on reading cumulative curves

The reference curve read 2.38 / 2.80 / 3.30 / 4.34 / 5.80 / 6.31 s and looked
like a smooth convex fall. As **local rates** it is 4.2 / 23.8 / 20.0 / 9.6 /
6.9 / 19.6 dB/s, which is not a shape any single envelope produces. Cumulative
times always increase smoothly; that is a property of cumulation, not evidence
about the underlying curve. **Differentiate before believing a shape.**

### §145 addendum — the knee conclusion is withdrawn, and the "13 dB ripple" is not a difference between machines

**Withdrawn: "the knee earns nothing on this material."** That rested on the
reference figure `MPC −20 to −60 = 11.40 dB/s`, which mpc2emu has since withdrawn.
Re-measured with the detector method above, the same reference gives **18.20 dB/s**,
which would put the match near `Rls2 = 75`, not 86. The 0.5% agreement in §145 was
against a number that no longer exists. **Nothing about `_ENV_SHAPE_BREAK_TIME`
should be changed on the strength of it.**

What survives untouched: the E4XT release is one straight line at 11.0 dB/s
(r² 0.99879, thirteen points), and the rate law predicts the release destination
to 3–9%. Those are measurements of this instrument and do not depend on any
reference.

**And a comparison I enabled wrongly.** I reported the sustain as "steady to
2.09 dB" without stating the window. That figure came from t = 10–24 s of a
**25 s** hold. mpc2emu measured ~13 dB over the last 2.5 s of a **4 s** hold and
reasonably read the two against each other, concluding that something modulates
on the MPC which our conversion does not carry.

Measured in **their** window, on E4XT captures already in hand:

| window | E4XT ripple |
|---|---:|
| 1.9–4.35 s of a 4 s hold (their window), three reps | **12.45 / 13.42 / 13.37 dB** |
| 1.9–4.35 s of the 25 s hold | 12.73 dB |
| 10–24 s of the 25 s hold (settled) | **2.08 dB** |

**The E4XT ripples the same ~13 dB they measured.** There is no modulation
difference between the machines; the note simply has not settled by 4 s on either,
and it takes ~10 s here. So the ripple cannot explain their S-curve, and this
program is not disqualified as a reference on those grounds.

The difference that IS real is repeatability: their rep spread is 0.38–0.53 s at
every threshold, ours 0.017–0.094 s, **on identically rippling material**. A
sustain-median reference absorbs the ripple; whatever is still moving on their
side is method, not material.

**The lesson is about the quoting, not the measuring.** 2.09 dB was correct and
so was 13 dB; they describe different windows of the same signal, and putting them
side by side manufactured a difference between two machines that are behaving
identically. **A dispersion figure without its window is not a number.** This is
the same failure as §136's floor quoted without saying which bin it was measured
at — and it cost a hypothesis about a missing LFO in the XPM reader.

## §146 — The release ladder on flat noise: no length dependence, and the mismatch is shape not scale (2026-09-18, live)

mpc2emu's E4B release fix had been derived on one sustaining pad and missed by
1.5× on the only other program they tried. Their earlier K2000 release factor had
failed the same way — calibrated at 0.55 s, shipped, 2.6× wrong at 2.85 s. So the
question for the bench was narrow: **does the geometry break as release length
changes, or is the error the same everywhere?**

Jan loaded a noise calibration ISO to P007–P012. Five byte pairs were set, the
ones their converter emits for source releases of 0.25/0.5/1/2/4 s, and each
measured twice.

### No length dependence

| asked | Rls1/Rls2 | measured t(−50 dB) | ratio |
|---:|---|---:|---:|
| 0.25 | 43/29 | 0.272 s | 1.09 |
| 0.50 | 55/41 | 0.565 | 1.13 |
| 1.00 | 68/54 | 1.147 | 1.15 |
| 2.00 | 80/66 | 2.283 | 1.14 |
| 4.00 | 92/78 | 4.523 | 1.13 |

Measured releases span **0.272 to 4.523 s, 16.6×**, and the ratio is flat at
~1.13. **There is no length-dependent bug**; the residual is one constant error.

### A caveat on how that was reported, which is the methodological point

The curves were first reported as "agreeing to within 0.7 dB at every fraction of
R" — plotted as dB below sustain against **t/R**. That axis normalises the release
length out. If the byte→rate law is exponential and the geometry scales R
linearly, the curves *must* collapse; a good part of that agreement is built in by
the choice of axis.

What the collapse does test, and it is not nothing: the byte→rate law was measured
14% out at byte 44 (§145 addendum), so if the emitted bytes had failed to deliver
proportional rates the curves would have separated. They did not. **But "agrees to
0.7 dB" overstates it, and the honest version is the ratio column above.**

Generally: **a normalised axis can manufacture the agreement it is used to
demonstrate.** Report the un-normalised quantity alongside it.

### The mismatch is in the shape, not a scale factor

dB below sustain, at fractions of the asked release:

| | 0.25R | 0.50R | 0.75R | 0.90R | 1.00R |
|---|---:|---:|---:|---:|---:|
| E4XT | −10.9 | −18.7 | −26.6 | −35.3 | −42.1 |
| MPC | −14.6 | −22.7 | −62.6 | −77.6 | *silent* |

Through the first half the E4XT is ~4 dB behind, roughly a constant offset. **Then
the MPC plunges and the E4XT does not** — 36 dB apart at 0.75R. No single
time-scaling constant fixes that; it would drag the first half far too deep while
correcting the second. This retires an earlier framing of the error as a clean
1.99× on the time fed to the segment split.

**The E4XT cannot reproduce what the MPC does here at all.** mpc2emu measured the
MPC gating to digital silence at exactly t = R. The E4XT's envelope steps a level
accumulator at a rate and keeps stepping — there is no parameter meaning "be zero
at time T". So the conversion target cannot be "silence at R"; it has to be a
chosen depth reached by R, and which depth is a judgement about audibility rather
than a measurement.

Floor caveat: the chain floor sat 67 dB below the sustain, so readings at 1.5R
(−66 to −68 dB on all five) are the floor, not the machine. Everything to 1.00R is
real.

### Sustain changes the release shape, and it is structural

Same bytes (55/41), P007 at sustain 100% against P008 at sustain 76%:

| | 0.25R | 0.50R |
|---|---:|---:|
| sustain 100% | −10.9 | −18.8 |
| sustain 76% | −19.0 | −34.0 |

**Nearly twice as deep.** The mechanism is in the machine: the writer places the
knee at 28.1 dB below **peak** (Rls1 level 71%), but the release starts from the
**sustain**. At sustain 100% segment 1 covers 28.1 dB; at sustain 76% the sustain
is already 23 dB down, so segment 1 covers only ~5 dB and the fast segment takes
over almost at once.

So the knee's depth *relative to where the fall begins* depends on sustain. That
explains the 1.5× on their sustain-0.63 program without any new theory — it is a
different branch of their knee clamp, not a mystery about release seconds. It also
scopes the earlier 1.99× figure: derived on sustain-100 material, it applies to
the clamped branch only.

### Rig facts for this bank

- **P007–P012 are silent at note 60.** Zones cover note 24 and 66–96; everything
  here was measured at note 72. The first qualification run read −80 dBFS with the
  note on *and* off and the bank was nearly reported as dead.
- Sustain is flat from 0.6 s, so a 4 s hold is sufficient — unlike the pad in
  §145, which needed 10 s to settle and forced 20 s holds.
- Usable range is ~60 dB over the chain floor at unity gain, the same as the pad.
  The flat top is the gain here, not the dynamic range.

### An "as-found" that was never read

`E4_GEN_VOLUME` on P007 was set to +10 dB for headroom **without reading it
first**, and 0 was written into the originals file as an assumption. The restore
printed +10, which caught it. The true value was recovered from P009/P011/P012 —
untouched presets from the same ISO, all reading 0 dB — and P007 restored.

**Recording an as-found value that was never actually read looks like data and is
not.** Same class as quoting a dispersion without its window (§145 addendum): the
artefact is indistinguishable from a measurement once written down.

### §146 addendum — the knee-clamp explanation is withdrawn; the measurement stands, the inference did not

§146 above concludes: *"the knee's depth relative to where the fall begins depends
on sustain… it is a different branch of their knee clamp, not a mystery about
release seconds."* **The second half is withdrawn.**

mpc2emu checked their writer against it. `_rmid = _env_db_to_level_byte(decay_span
+ _r_mid_db)` — **their knee is already sustain-referenced**, and `_r_mid_db =
min(29.0, 0.48 × rel_span)` does not change branch at sustain 0.63, because
rel_span only falls 97.82 → 93.81 and the clamp stays at 29.0. Their emitted bytes
at the two sustains are Rls1 55/Rls2 41 and Rls1 55/Rls2 42 — essentially
identical rates, with the *level* byte moving to hold the knee 29 dB below the
sustain.

**The P007/P008 comparison set the same Rls1 level (71%) on both**, which fixes
the knee 28.1 dB below *peak* rather than below sustain. On P008, whose sustain is
23 dB down, that leaves segment 1 only ~5 dB to cover instead of 29 — which is
exactly the doubling that was measured. What their writer would emit for P008 is
Rls1 level **46%**, not 71%.

So the measurement is sound and characterises **the instrument at fixed bytes** —
useful, because it shows what happens when the level byte is left alone. It says
nothing about their converter, which never leaves it alone.

**And the MPC goes the other way.** Same program, release 499 ms, sustain 127 vs
80 (the sustain level itself fell 4.02 dB against a predicted 4.03):

| drop | sustain 127 | sustain 80 | diff |
|---|---:|---:|---:|
| −10 dB | 0.200 s | 0.190 s | −0.010 |
| −30 dB | 0.430 | 0.420 | −0.010 |
| −50 dB | 0.470 | 0.460 | −0.010 |

A uniform one-hop offset at every point: **the curve translates, it does not
change shape.** The MPC falls the same dB in the same time regardless of where it
starts. So the two machines differ in kind on this, and the E4XT's fixed-byte
doubling is not a model for it.

**The lesson is about what a comparison holds fixed.** Holding the *bytes* fixed
and varying sustain measures the instrument. Holding the *converter* fixed and
varying sustain measures the conversion. They are different experiments and only
the second bears on the writer — I ran the first and drew a conclusion about the
second. Nothing in the numbers was wrong; the wrong thing was which question they
answered.

The test that would bear on it: set Rls1 level **46%** on P008 — the writer's
sustain-referenced knee — and see whether the E4XT then reproduces the MPC's
sustain-independence. Not run.

**Precious's 1.5× is therefore unexplained again**, and mpc2emu's judgement is to
leave it there: it was a musical program with its own decay mixed into the fall,
measured before the protocol settled, and the noise work has made those pad
numbers suspect. Better an open item than an explanation that does not hold.

### §146 addendum — what the MPC's release shape actually is

Normalised over four release lengths 8× apart, agreeing to 0.02R:

```
−10 dB at 0.39R     −30 dB at 0.86R     −50/−60 dB at 0.95R     SILENT at 1.00R
−20 dB at 0.70R     −40 dB at 0.92R
```

**It spends its last nine percent of R covering thirty dB.** The E4B writer gives
segment 1 0.96R to reach 29 dB, where the MPC is 29 dB down at 0.86R and 60 dB
down at 0.95R. That is the plunge measured above as the E4XT being 36 dB behind at
0.75R, and it is why no single time constant closes the gap — the two curves are
not related by a scale factor in time.

## §147 — Fifteen capture scripts, none of which closed the JACK client (2026-09-18, live)

s3ked traced this machine's two JACK server wedges tonight to clients that outlive
their owners, and the finding applies here harder than it does to them: **not one
of the fifteen capture scripts run from this session called
`_PersistentRecorder.close()`.** That method exists — `hw_measure.py:577`, it
deactivates then closes the client — and it was never called, in ~40 captures.

### Why that is worse than it sounds

The module registers an `atexit` hook for the **MIDI** port (`_release_midi`,
hw_measure.py:228) and none for the recorder. So MIDI was always released and the
audio client never was, and the asymmetry is invisible because the MIDI hook works.

Every one of those scripts ran under a shell `timeout`, which sends **SIGTERM**.
Several were killed that way tonight — the hung `relpan.py`, the `qual.py` that hit
a wedged server. Signal handlers were installed in those scripts, but only to send
All Notes Off; the recorder was not in them.

### Three failure modes, only one of which was on my radar

1. **Construction can fail after `activate()`.** `_PersistentRecorder.__init__`
   calls `client.activate()` and then `reconnect()`, which can raise — a missing
   source port, a busy server, or its own connection read-back assertion. The
   client is then registered and running with **no reference left to close it**.
   (s3ked's finding, in their own `probes/jcap.py`; the same shape is in the
   shared `hw_measure.py` that this session and mpc2emu both use.)

2. **`except Exception` does not catch being killed.** `SystemExit` and
   `KeyboardInterrupt` are not `Exception`s, and **being killed is precisely how
   this failure arrives** — a timeout, a Ctrl-C, a harness killing a hung probe.
   A teardown guarded by `except Exception` runs in every case except the one
   that matters. Catch `BaseException` and handle the signals.

3. **A capture with no deadline is a rig-wide outage, not a failed run.** A
   blocked capture holds the client indefinitely. s3ked measured a sibling's
   6-second capture sitting blocked for 1:54. A deadline converts that into one
   bad measurement.

### Why it is invisible from the client side

To jackd, a client whose owner has died and one that is merely slow look
identical. It keeps writing to the socket. The symptom is `jack_lsp` timing out
**for every session on the machine**, with a jackd thread parked in
`sock_alloc_send_pskb` — blocked writing to a socket nobody reads. **Killing the
offending process does not clear it**; the server needs restarting. That matches
what was seen here twice: `jackd` alive (PID 137100), `jack_lsp` hanging, MIDI
entirely unaffected.

### What was done

`scratchpad/rig.py` wraps the recorder with: teardown on `BaseException` during
construction *and* an orphan-recovery path that reconnects by client name to close
a half-built client; `atexit` plus SIGTERM/SIGINT/SIGHUP handlers; and a
`SIGALRM` deadline around the capture itself.

**The constructor leak is in `hw_measure.py`, which belongs to mpc2emu** — reported
rather than edited, per the convention that each project writes its own tree. It
affects every session using that file.

No stale `eosed-*` clients were resident at the time of writing (277 ports, matching
s3ked's count after their restart), so nothing of this session's is currently leaked.

### The transferable part

**A resource whose release is only on the happy path is not released.** The test
is not "does the teardown exist" — it did, and was correct — but "does it run when
the process is killed", because for a long-running capture that is the normal exit.

s3ked also ran their nine new tests **against the old code as a negative control**
and eight fail there. A test suite that has never failed against the bug it
targets has not been shown to test anything.

### Rig protocol, agreed among the sessions after three collisions today

Say **RIG IS MINE** before touching audio or MIDI, and **RIG IS FREE** when done —
including when the run fails.

### §147 addendum — the orphan-recovery path does not work and is removed

§147 credits `scratchpad/rig.py` with "an orphan-recovery path that reconnects by
client name to close a half-built client". **It cannot do that, and the claim is
withdrawn.**

`jack.Client(name)` takes `use_exact_name=False` by default, and the server "will
modify this name to create a unique variant, if needed". So reconnecting by the
orphan's name registers **`name-01`**, closes that, and leaves the orphan
untouched — while raising nothing and appearing to succeed. And the API exposes
`close()` and `deactivate()` on your *own* client only; there is no call that
closes another client's registration.

**Once a client outlives its owner, only a server restart clears it** — which is
precisely what s3ked observed and why killing the offending process does not help.

It was written, put in a commit message and described to two peers without being
run once. The same evening's lesson, applied to the fix for the evening's lesson:
**code that cannot fail visibly needs a test before it is described as working,
and "it is only a safety net" is not an exemption** — a safety net nobody has
dropped anything into is decoration.

Replaced with the thing that does work for the constructor case: build the
recorder with `cls.__new__(cls)` and call `__init__` by hand, so a failure after
`activate()` still leaves a reference to the client. A plain constructor call
discards the instance when `__init__` raises, which *is* the leak.

mpc2emu's fix in `hw_measure.py` guards this from inside the constructor, which is
cleaner and reaches all three sessions. The external wrapper is a belt for one
session's braces, not a substitute.

### §147 addendum — the cheapest refutation needed no server, and my proposed test would have been the eleventh client

Having withdrawn the orphan-recovery path, this session proposed the test that
would have caught it: register a client, register a second with the same name,
assert the second's `.name` equals the first. It does not, so the path falsifies
in five lines.

**s3ked declined to run it, correctly.** That test needs a live server and
registers two clients — and *creating JACK clients to study what wedges JACK
servers*, while another session held the rig, is a check that can cause the
condition it tests for. They refuted it with no server contact at all:

```
jack.Client.__init__   ->  use_exact_name = False   (the default)
docstring              ->  "the server will modify this name to create a
                            unique variant, if needed"
close(ignore_errors=True) / deactivate(ignore_errors=True)
                       ->  no argument naming another client, and no API
                           anywhere that closes a foreign registration
```

`inspect.signature` and `getdoc`. **The cheapest test for "can I recover an
orphan" needs no orphan, no server and no client — it needs the function
signature.** Mine would have worked and would also have been the eleventh JACK
client of an evening spent diagnosing leaked JACK clients.

Their formulation: **a check that can cause the condition it tests for is a check
with a cost.** Prefer the refutation that touches nothing.

### §147 addendum — why an untested safety net is worse than an untested feature

s3ked's addition to "an untested net is decoration": a net is reached for
*precisely when something has already gone wrong*, so **its failure arrives
compounded, at the moment nobody is in a position to investigate.**

And the unifying statement for the evening's four instances of this shape — two
gates here that passed on material which could not have failed them, VinSamLib's
dialog sweep passing while operating 10 of 25 controls, and this orphan path:

> **A guard with no path to a visible failure reports success identically to a
> guard that works.**

Which is the same sentence as *to jackd, a leaked client and a live one are
identical* — one level up. The shared cause is not carelessness: each was written
while thinking about the subject, and none was written while thinking about the
check. The discipline that catches it is the negative control — run the check
against the broken case and confirm it fails — and it is the step every one of the
four omitted.

## §148 — Comparing EOS's own AKAI import against a converter, and two ways to read the wrong thing (2026-09-20, live)

Jan loaded EOS 4.0's own AKAI import of six S3000-generation `.P3` programs
alongside mpc2emu's conversion of the same source files, and asked which
differed. Read-only parameter reads over the editor protocol, matched by preset
name. The method is sound and worth reusing; two of its readings were not.

### What EOS's import chooses, where the converter chose otherwise

On the one program with an audible difference (Jan: *"more Q and it comes in
earlier"*), voice 0:

| | EOS import | converter |
|---|---:|---:|
| FTYPE | 2-Pole Lowpass | 2-Pole Lowpass |
| FMORPH (base cutoff) | **81** | **0** |
| id 84 (Q) | 119 | 112 |
| `FEnv+ → FilFreq` | 46 | 100 |
| `Key+ → FilFreq` | **8** | **58** |
| filter env Dcy1 | **rate 2 → 47%** | **rate 50 → 19%** |

Both readings of the same source bytes are defensible — the converter treats the
AKAI field as a *corner position* and parks the base at 0 with a full-scale
sweep; EOS parks the base at 81 and sweeps less. The audible difference is not
the resonance byte, which is where the search started.

`Key+ → FilFreq` 58 against 8 is the one worth chasing: the converter's positive
key-follow is documented on its side as an unresolved nonlinearity passed through
uncorrected, and this is independent evidence on its size.

### Retracted: "MEM-ANA STR is +12 on both voices"

Root key read 55/67 on the EOS side and 67/79 on the converter's, ranges
identical, coarse tune 0 on both. Reported as a clean octave defect. **It is not
a defect — it is the same pitch in a different parameterisation.**

The source carries `SPITCH 55`, `SHTUNO −12.059 st`, declared rate 22050 against
an index rate of 44100. The declared/index gap is exactly +12 semitones and the
sample's own tune cancels it. One side resolves to *rate 44100 + root 67*, the
other to *rate 22050 + root 55*. Both sound identical.

**Root key alone cannot separate them**, and the read that would have — the
sample rate beside it — was not taken. Comparing one field of a multi-field
encoding and concluding about the quantity those fields *jointly* determine is
the same error as comparing a dispersion without its window (§145): the number
is right and it is not the quantity in question.

Standing, on the same evidence: SOLDANO 12 B, where the source has
`SPITCH 50, SHTUNO 0`, declared rate equal to index rate — nothing to resolve —
and EOS's import carries coarse tune 13 and fine 30 that the source does not.
That is a genuine disagreement about a field one side reads and the other
does not.

### The bank was replaced mid-read, and the selection check could not see it

An hour into the comparison, the same parameter on the same voice began reading
all-zero where it had read real values. Diagnosed first as intermittent reads,
then as the zone selector (id 226, reading the 16383 no-data sentinel). **Both
wrong. A different bank had been loaded over the comparison set** — a sibling
session's transposition-ceiling test, legitimately, while the rig was believed
free.

Every selection had been verified: preset-select and voice-select were written
and read back, and matched, every time. Preset 13 was still preset 13.

> **Verifying that you addressed slot N is not verifying that slot N still holds
> what it held.**

The check could not fail in the state that made its answers meaningless. Had the
read gone out, it would have reported "the converter writes an all-zero amp
envelope, nothing is reaching the machine" — to the session debugging that exact
field that day.

**Mechanism, not rule: read the preset NAME as part of selection and assert it
against what the comparison expects.** One extra SysEx read per preset, and a
swapped bank becomes impossible to misread rather than merely unlikely.

What made the surviving findings safe was accidental corroboration rather than
any guard: the tuning read produced a coarse tune of −47 on one voice, a value
the sibling session had named in advance from its own file. An empty preset could
not have produced it. **That is luck, and the name assertion is what replaces it.**

### Rig protocol gap this exposed

"RIG IS FREE" was said truthfully about audio capture while a bank was about to be
loaded over the E4XT's RAM. Announcing the *rig* does not announce the *contents*.
A session that is mid-comparison needs to know that the material is changing, not
only that the hardware is available.

### §146 addendum — the noise-ladder timings are crossing-based, and crossings on noise are biased

s3ked has now established directly what was previously inferred: **on a noise
source, a threshold-crossing estimator inherits the source's own amplitude
fluctuation, while a dB-slope fit over many windows averages it away.** Their
DECAY1 sweep across bytes 25–99 on looped white noise with a slope fit reproduced
an independently measured constant to **0.49%** (exponent 0.09728, r² 0.99989);
§118's crossing-based attempt on the same class of material produced
non-monotonic results with no region reaching r² 0.99.

**§146's release ladder was measured on flat noise and its time column is
crossing-based.** It needs re-measuring, not annotating. The captures did not
survive the reboot, so it cannot be refitted from disk.

**What is affected and what is not**, because the two columns differ:

- the *dB below sustain at fractions of R* table reads a **level at a fixed
  time**. On noise that is noisy but **not biased** — a window's fluctuation is
  as likely up as down.
- the **t(−50 dB)** column and every "×R" ratio derived from it are **crossing
  times**, and those are biased **early**: the first window to dip below a
  threshold catches a downward fluctuation, so the fall reads shorter than it is.

**Rep-to-rep agreement does not protect against this.** §146 quoted a 0.072 s mean
spread as evidence the numbers were sound. Both reps carry the same systematic
bias; repeatability measures precision and says nothing about it. That is the
same error as reporting r² for a fit whose axis was normalised (§146's first
addendum) — a statistic that cannot see the defect being offered as evidence
against it.

**Which way it moves the conclusion.** The bias scales as the fluctuation depth
divided by the local slope, so it is *largest at the fast end*. §146's measured
ratios were 1.09 / 1.13 / 1.15 / 1.14 / 1.13 across a 16× span, and the fastest
rung is the lowest — consistent with the estimator depressing it. Correcting it
would raise the fast end toward the others, making the ratio **flatter**. So
**"no length dependence" survives and is strengthened**; the absolute 1.13 is the
part that needs re-measuring.

Re-measurement is on the purpose-built decay ladder (`CD4-DCYLADDER`, 15 rungs,
Dcy1 bytes 8–127, one shared looped-noise sample, sustain 0 so the decay crosses
the full span), with slope fits and per-curve r² throughout.

**Two design requirements carried in from s3ked's own failure on that bank's fast
end**, where their byte-20 point died at r² 0.948 because 61.8 dB passed in ~18 ms
leaving only 42 analysis windows:

- **size the analysis window per rung from that rung's measured rate**, not once
  for the sweep — a fixed window at the fast end returns a confident fit of its
  own smoothing
- **require a span floor** (§30 uses 21 dB) and **report per-curve r²**, so a bad
  rung declares itself rather than averaging in

And a caution about the sections themselves: s3ked reports that **§118's
replacement constant is wrong** — its estimator lesson holds, its own re-measured
number does not — so any other figure from §118 is unconfirmed pending their
review. A separate claim attributed to §30, that it fit slopes *on noise*, is
**not supported by §30**, which describes a source with its own slow decay. The
proposition is now established by s3ked's measurement tonight rather than by
either section.

## §149 — The decay rate law measured on a purpose-built ladder: bytes 32–127 (2026-09-20, live)

mpc2emu built a 15-rung ladder (`CD4-DCYLADDER`) for this: one shared 20 s looped
white-noise sample at −6 dBFS, root key 69, one zone on key 69 only, sustain 0,
attack 0, release 0, and `Dcy1` swept 8 → 127. Every Dcy1 byte was read back out
of the written file before the bank was accepted, so the bytes are measured and
only the generator's *implied seconds* column is arithmetic to be checked.

Method, with the provenance of each rule since all three came from other sessions:

- **Play only note 69.** Any other key resamples the noise and tilts its spectrum,
  and an off-list note still sounds at a plausible level — it looks like a valid
  take. (mpc2emu)
- **Fit a dB slope, never a threshold crossing.** On noise a crossing inherits the
  source's own amplitude fluctuation sample by sample; a slope over hundreds of
  windows averages it away. s3ked established this directly rather than by
  inference: their DECAY1 sweep with a slope fit reproduced an independently
  measured constant to **0.49%** where a crossing estimator on the same material
  gave non-monotonic results with no region reaching r² 0.99.
- **Size the analysis window per rung from that rung's own rate**, require a span
  floor, and report per-curve r² so a bad rung declares itself. (s3ked, after
  their own byte-20 point died at r² 0.948 with only 42 windows across 61.8 dB.)

### The overlap check, which is what makes the ends believable

Bytes 48–86 sit inside the existing 44–86 fit **by design**. A ladder with no
overlap cannot be validated against anything.

| byte | measured | existing law | diff |
|---:|---:|---:|---:|
| 48 | 93.26 | 91.77 | +1.6% |
| 60 | 47.01 | 47.53 | −1.1% |
| 69 | 28.14 | 28.54 | −1.4% |
| 80 | 15.05 | 15.00 | +0.4% |
| 86 | 10.88 | 10.47 | +4.0% |

Mean |error| 1.7%. **The overlap reproduces, so the new ends stand.**

### The law

```
ln(dB/s) = −0.0001222·b² − 0.040902·b + 6.8135      bytes 32–127, 12 rungs, r² 0.998042
```

Against the old 44–86 fit extrapolated: −2.3% at byte 32, +3.6% at 118, **+7.3%
at 127.** So the earlier extrapolation was better than feared — the caution was
right and the error was modest.

**Three rungs refused and one recovered.** Bytes 8, 16 and 24 give no window with
≥60 points: byte 8 falls 22 dB in about 30 ms, which is a limit of the rig's time
resolution and not of its level — more gain cannot buy it. Byte 127 failed on the
first pass at span 18.0 dB because the note was still decaying at note-off; its
floor read −45 dBFS against −82 elsewhere, which is the tell. A hold sized from
the *measured* rate rather than the generator's implied time recovered it at
r² 0.99938.

### Gain: measured, not argued

Jan offered more output gain; mpc2emu cautioned against it, having clipped one of
their own captures that day (267 samples at full scale). Both were right about
different material. Measured on this ladder at the original setting: worst peak
**−15.33 dBFS, zero samples at full scale** on all 15 rungs. After Jan raised the
hardware gain 50% → 60%: peak −11.75 dBFS, still zero clipped.

**The measured rates did not move**: byte 32 236.63 → 233.44, byte 69 28.19 →
28.14, byte 110 2.51 → 2.51. A slope fit is level-independent, and the gain change
is an unplanned control demonstrating it.

A clipping gate now runs before the sweep and aborts it, because **a clipped
source flat-tops the start of every decay and fits a shallower slope on every
rung with a clean r²** — a failure that survives the r² check.

### What it says about the generator's arithmetic

Its implied/measured ratio is **flat at ~0.92 from byte 32 to 102, then breaks**.
A flat ratio is a span-definition difference, not a law error — the same shape
mpc2emu found in the 1.93× — and it resolves: their span is ~30 dB where this
measurement uses 28.1 dB.

| | |
|---|---|
| bytes 32–102, span-matched at 30 dB | ratio **0.983 ± 0.012** — right to ~1% |
| byte 110 | 1.095 |
| byte 118 | 1.185 |
| byte 127 | **1.780** |

**So the generator's rate law is sound to ~1% across bytes 32–102 and diverges
above ~110**, reaching 1.78× at the top of the range. That is the actionable half:
not a scale factor, a range limit.

### Addendum (2026-09-20, live) — the three refused rungs, recovered: the law is range-limited, not universal

The §149 fit above covers bytes 32–127 because bytes 8, 16 and 24 were refused
for want of windows. s3ked pushed back on leaving them there, and on the
explanation I had ready for them:

> "If your extraction returns the right answer on the synthetic, the bad point is
> the E4XT telling you something. That is a finding, and dismissing it as
> instrument would lose it."

They had retracted exactly that move in their own §259, after validating their
fitter against a constructed decay of known rate. So the rungs were recovered
rather than explained.

**How.** Overlapping analysis windows, hop = W/4 instead of W (s3ked's rig), which
buys 4× the window count out of the same 30 ms. Then the extractor was validated
against synthetic exponentials of known rate, and the bias re-calibrated **at the
measured rate of each rung** rather than at an estimate of it — an earlier pass
interpolated byte 8's correction at 880 dB/s when the rung actually measures
~1250, and got −6.18% where the truth is −1.17%.

| byte | measured | recovered from synth | bias | spread |
|---:|---:|---:|---:|---:|
| 8 | 1246.63 | 1232.03 | −1.17% | 3.86% |
| 16 | 846.53 | 832.05 | −1.71% | 2.08% |
| 24 | 375.40 | 373.78 | −0.43% | 2.18% |
| 32 | 236.35 | 236.28 | −0.03% | 0.47% |

Corrected: **1261.40, 861.26, 377.03, 236.42 dB/s.** The spread column is the
honest uncertainty, not the bias — byte 8's whole decay is ~30 ms and only a
handful of windows fit inside it even at hop W/4.

### The negative result

**A single quadratic does not span bytes 8–127.**

```
full 8-127, 15 rungs:   ln(dB/s) = -0.0000155·b² - 0.059038·b + 7.5014   r² 0.996736   max resid 24.5%
32-127, 12 rungs:       ln(dB/s) = -0.0001205·b² - 0.041229·b + 6.8271   r² 0.998011   max resid 16.1%
```

The full-range fit is worse *everywhere* — it buys the fast end by spoiling the
range that already worked. And the 32–127 law extrapolated downward misses badly:

| byte | measured | 32–127 law predicts | law is |
|---:|---:|---:|---:|
| 8 | 1261.40 | 658.23 | −48% |
| 16 | 861.26 | 462.47 | −46% |
| 24 | 377.03 | 319.96 | −15% |

**This is not the rig running out of time resolution.** That failure mode smears a
decay and reports it *slower* than truth; these rungs measure nearly **twice as
fast** as the law predicts. The sign rules the instrument explanation out, which
is the part of s3ked's warning that actually bites — the point I was going to
dismiss is the one carrying the information.

So the rate law is **piecewise**, as §134 said of it generally: 32–127 is one
segment, below ~32 is another, and the knee sits somewhere in 24–32.

### What I should have printed with §149's r²

§149 quotes `r² 0.998042` and nothing else. In log space with 12 points that hides
a single bad rung, so here is the column that belongs beside it:

| byte | measured | fit | resid |
|---:|---:|---:|---:|
| 32 | 236.42 | 217.98 | +8.5% |
| 40 | 147.11 | 146.23 | +0.6% |
| 48 | 92.58 | 96.59 | −4.2% |
| 60 | 47.00 | 50.38 | −6.7% |
| 69 | 28.16 | 30.22 | −6.8% |
| 80 | 15.05 | 15.76 | −4.5% |
| 86 | 10.90 | 10.92 | −0.2% |
| 94 | 6.95 | 6.60 | +5.3% |
| 102 | 4.27 | 3.93 | +8.7% |
| 110 | 2.50 | 2.30 | +8.6% |
| 118 | 1.47 | 1.33 | +10.6% |
| 127 | 0.59 | 0.70 | **−16.1%** |

The law is good to ~16% worst case and ~6% typical. That is fine for its purpose
and it is not what r² 0.998 sounds like.

### For anyone adopting the law

mpc2emu is taking this as the fix for their divergent region above byte 110, so
the valid range matters to them specifically:

- **Use it over bytes 32–127 only.** Quote ±16% worst case.
- **Do not extrapolate below byte 32** — it is −48% at byte 8.
- Below 32 there are three measured points and no fit. Three points and a knee of
  unknown position do not make a law; if that region matters, it needs its own
  ladder at bytes 8–36.

### Addendum 2 (2026-09-20) — the 30 dB span this section closed on is WITHDRAWN by its author

§149 above ends by resolving the generator's flat ~0.92 implied/measured ratio as
a span-definition difference, "their span is ~30 dB where this measurement uses
28.1 dB", and the table quotes **ratio 0.983 ± 0.012, span-matched at 30 dB.**

**mpc2emu has withdrawn the 30 dB figure, so that resolution no longer stands and
the numbers above must not be built on.** Recording it here rather than editing
the section, because the reasoning that produced it is the instructive part.

Their own account of the fault: they compared a span-aware reading of their bytes
against a **span-blind** reading of EOS's. EOS never uses the two-segment decay
shape — Dcy1 rate is 0 on every voice — so their parser takes its plateau
fallback branch, where the whole decay comes from a law that assumes a span which
is neither fixed nor 30 (43.1 dB at byte 4, rising to 51.1 at byte 110). The
"implied EOS span" was therefore a compound of their own parser and the rate
ratio, not a measurement of EOS's convention anywhere. **The 1.93× goes with it**
as a statement about EOS's conversion; it remains a real difference between two
files *as that parser reads them*.

**What survives is the exponent falsification, and why it survives is the point.**
That argument is about the ratio's SHAPE against their own decay byte — an error
in their law would have to slope, and it does not — and it holds however EOS's
side is read, because EOS's bytes are not a function of theirs. The 30 dB claim
was about the ratio's LEVEL, and the level is exactly what the reader asymmetry
corrupts. **A shape argument survived an instrument fault that destroyed a level
argument built from the same numbers** — the same discriminator as this section's
own sign test on byte 8, and worth keeping as a general rule: ask what the
artefact explanation predicts about shape or sign before arguing about size.

**And the process failure is one this project keeps making.** They checked the
below-32 prevalence *in aggregate over all six envelope stages*, got 51%, and
filed it as a caveat. Per stage it was a refutation, because the one stage
carrying EOS's entire decay is the stage their reader handles differently. **The
aggregate hid that a stage was empty.**

### s3ked's correction to the sign test, which belongs with it

s3ked applied §149's sign argument to their own two anomalies and it came out
**decisive on one and silent on the other — the one they had got wrong:**

```
  byte 20   measured 2370.32 vs law 3329.72  ->  reads SLOWER  -- consistent with smearing
  byte 96   measured    2.19 vs law    1.98  ->  reads FASTER  -- smearing ruled out, free
```

**A silent test is not an agreeing test.** Reading slower is exactly what a
resolution limit produces, so the sign test cannot clear byte 20 and only
synthesis could. Worth stating because a cheap test that is decisive most of the
time is the kind that gets treated as decisive always.

They also caught the mirror of this section's own byte-8 bias error. Their control
synthesised each point at its **measured** rate and asked whether the estimator
would report it; the resolution hypothesis actually claims something else — that
the machine is *on* the law and the estimator under-reports — which they had never
tested. Re-run at the law-predicted rate, fed 3329.72, their estimator returns
3313.87 (−0.48%). The refutation stands, but it had been aimed one step off the
hypothesis.

One coincidence noted and explicitly not claimed: their fast end starts
misbehaving at byte 20 and the knee here sits in 24–32. Different machine,
different law. Recorded in case it stops being a coincidence.

## §150 — The Preset FX fields, from the firmware's own tables and confirmed on the machine (2026-09-20, live)

Jan loaded a commercial bank and gave the FX settings his front panel showed for
three presets — algorithm names, parameter values and send percentages. That is a
**known-plaintext attack on the encoding**: the names and numbers are the
plaintext, the wire bytes are the ciphertext, and the only job is to line them up.

### The headline: the committed algorithm tables were off by one, and the app has been showing the wrong effect name for every preset

`FX_A_ALGORITHM_NAMES` and `FX_B_ALGORITHM_NAMES` were transcribed from the
manual's printed list of effects. **The manual's list starts at the first real
effect. The wire encoding reserves value 0 for "Master Effect A"/"Master Effect
B", meaning *inherit the master setting*.** Printed position is not wire value,
and every entry was one low.

Read over SysEx, against what the panel displayed for the same presets:

| preset | panel says | wire byte | old table | new table |
|---|---|---:|---|---|
| P001 FX A | Cavern | 25 | Concert 9 ✗ | Cavern ✓ |
| P001 FX B | Delay Stereo 2 | 20 | Panning Delay ✗ | Delay Stereo 2 ✓ |
| P002 FX A | Spacious Hall | 19 | Bright Hall ✗ | Spacious Hall ✓ |
| P002 FX B | Symphonic | 16 | Ensemble ✗ | Symphonic ✓ |
| P003 FX A | MediumConcert | 32 | Large Concert ✗ | MediumConcert ✓ |
| P003 FX B | Slapback | 7 | Flange 1 ✗ | Slapback ✓ |

**Six for six against the new table and zero for six against the old one.** The
old table was never wrong in a way that looked wrong: every value it returned was
a real effect name, just the neighbouring one.

### Where the tables actually live

In the decompressed EOS 4.70 image (regenerate with `eosflash export` +
`eosflash flash --4mb`; load base `0x20000`), as **pointer tables of fixed-stride
records**, not as a plain string list:

```
  FX A   table at 0x923c4   22-byte records   45 entries (0..44)
  FX B   table at 0x927a2   16-byte records   33 entries (0..32)
  layout: u32 big-endian pointer to a NUL-terminated name, then metadata
```

**Do not read the string pool in address order.** The pool and the pointer table
disagree: the pool runs `Delay Stereo, Delay Stereo 2, Delay Chorus` where the
table runs `Delay, Delay Stereo, Delay Stereo 2, Panning Delay`. Pool order gives
wrong indices for everything from 18 up — and it would have produced a *different*
wrong answer than the manual did, which is how the two were told apart.

Spellings are now the firmware's rather than the manual's (`Brt Hall Pan`, not
`Bright Hall Pan`; `BBall Court`, not `B-Ball Court`), because those are the
strings the LCD actually draws and a TUI meant to match the hardware should match
what the hardware prints.

### FX_B_ALGORITHM's maximum was stale, and the device says so itself

`params.py` carried max **27**, transcribed from the SysEx spec — which is EOS
**4.00**. The firmware table has 33 entries, and the device's own parameter-range
request (`04h`) answers **0..32**.

**27 is exactly `Vibrato`.** Everything above it is the distortion family
(`Distortion 1`, `Distortion 2`, `DistortedFlange`, `DistortedChorus`,
`DistortedDouble`) added after 4.00. So the spec was never wrong; it was current,
and 4.70 grew past it. A reader validating against 27 rejects five legal values.

All sixteen FX ids were range-checked against the device. **Fifteen of sixteen
agreed with the transcription; this was the only drift** — which is both a good
result for the spec and the reason the one mismatch is worth trusting.

### The three PARM slots, and the one the manual could not name

The firmware keeps a single label pool immediately before the algorithm tables,
six strings, three for A then three for B:

```
  FX A:  Decay Time   HF Damping   FxB==>FxA
  FX B:  Feedback     LFO Rate     Delay Time
```

Five of those six already matched what a previous session had taken from the
manual. The sixth is the one the manual does not name: `FX_A_PARM_2` had been
left deliberately unmapped rather than guessed, and it is **`FxB==>FxA`** — a
routing amount feeding the B block's output into A, not an effect parameter.
That is why it reads 0 on every preset seen so far.

The parameter values confirm the ordering independently of any name:

```
  P002 FX A: PARM_0 = 37, PARM_1 = 120      panel: Decay Time 37, HF Damping 120
  P002 FX B: PARM_0 = 48, PARM_1 = 24       panel: Feedback 48, LFO Rate 24
```

**`FX_A_PARM_0`'s range is 0..90 while the other five are 0..127**, so a value of
120 cannot be a Decay Time. The order is pinned by the range alone, with the
labels only agreeing afterwards.

`FX_*_AMT_0..3` need no new work: the existing `FX_AMT_BUS_NAMES` (Main, Sub 1,
Sub 2, Sub 3) is right, and `AMT_0` carried Jan's stated Main sends exactly —
5%, 18%, 3%, 3%, 2%, 6% across the three presets, six for six.

### The trap that nearly produced a false confirmation

The first read selected presets with `send_program_change` and got **identical FX
values for all four presets**. Those values happened to match the P002 hint's FX A
block exactly — algorithm 19, 37, 120, send 3 — which looked like a four-for-four
confirmation.

It was not. **Ids 6–21 follow `PRESET_SELECT` (id 223), not Program Change**, and
223 was pointing at preset 14 the whole time. Preset 14 simply shares P002's FX A
settings, as presets in one library bank often will. Its FX **B** block differed,
which is the only reason the coincidence was visible at all.

**This is §148's lesson arriving in a new costume: the reads were addressed
correctly and identified nothing.** What caught it was reading back id 223 rather
than assuming the selection had moved. A probe that selects should verify the
selection landed, every time, for the same reason a dump should assert the preset
name — and note that the confirming evidence here was an *inconsistency inside a
match*, not a mismatch.

### Method note

No preset data was written. Selection moves `PRESET_SELECT` (navigation, RAM
only), which was read first and restored afterwards; the bank is untouched.

Preset *numbers* appear above. The bank, its source media and its preset names do
not, and must not — they are commercial library material. The shape of a finding
never needs them.

## §151 — Does EOS's AKAI importer map FX? No. And byte 27 is not FX either (2026-09-20)

§150 identified the FX fields in the *SysEx parameter* space. This locates them in
the *file* and then answers Jan's question from the corpus, with no hardware.

### The FX block is preset-header bytes 60–75

`E4B_FORMAT.md` marks `60:82` as "zero". It is not — it is the FX block, laid out
in exactly the order of SysEx ids 6–21:

```
  [60] FX_A_ALGORITHM   [61] Decay Time  [62] HF Damping  [63] FxB==>FxA
  [64..67] FX_A_AMT_0..3        (Main, Sub 1, Sub 2, Sub 3)
  [68] FX_B_ALGORITHM   [69] Feedback    [70] LFO Rate    [71] Delay Time
  [72..75] FX_B_AMT_0..3
```

**The identification is a falsification test, not a pattern match.** Those sixteen
fields carry six different limits — 44, 90, 127, 100, 32, 127 — and §150 pinned
each one against the hardware. If the block sits anywhere else, some preset
somewhere must violate one.

```
  24 banks, 1184 preset headers
    FX block all-zero : 480
    FX block non-zero : 704
    RANGE VIOLATIONS  : 0
```

**704 headers carrying real data and not one byte out of range**, including the
two tight ones (FX A's algorithm ≤ 44, FX B's ≤ 32) where a random byte would
fail ~83% of the time. The four-byte AMT groups also behave as §150 predicted from
the machine: `AMT_0` (Main) carries the send and `AMT_1..3` are usually zero.

### The answer: the importer writes no FX at all

```
  bank                        presets   FX block all-zero   byte 27
  EOS AKAI import (full)          363         363/363       239..250
  EOS AKAI import (subset)         20          20/20        241
  hardware-saved commercial        10           0/10        0
  large factory bank              347           0/347       0
```

**Every one of the 363 imported presets has a completely zero FX block.** Read
through §150's corrected table that is not "no data" — it is a *meaningful*
setting: algorithm 0 is `Master Effect A`/`Master Effect B`, i.e. **inherit the
master effect**, with every send at 0.

So the importer does not map FX, and it does not invent FX either. It leaves each
preset deferring to the master with the sends shut — which for a source format
whose programs carry no EOS-comparable effect state is the defensible choice. Two
non-imported banks in the same corpus carry real per-preset FX, so the field is
being exercised; it is the importer that declines to write it.

### Byte 27 is therefore NOT FX, and that was this project's prediction

mpc2emu's re-save experiment showed byte 27 is **preserved** by the machine, not
generated, so the 239–242 they see comes from the importer — and they recorded
that as "what eosed predicted would point hard at FX".

**That prediction is refuted.** The FX block is bytes 60–75 and it is identically
zero in precisely the banks where byte 27 is non-zero. Byte 27 cannot be the FX
field it was predicted to be, because the real FX field is sitting next to it
holding nothing.

Two corrections to the shape of the evidence as well:

**The range is wider than recorded.** Not 240–242 but **239, 240, 241, 242, 243,
244, 245, 249, 250** — nine distinct values across 363 presets, with 241 the mode
at 249 and 242 next at 78. (Recorded raw: their count is 361 presets and this
walker finds 363 in the full-bank file. The two may be different files; not
reconciled here.)

**It tracks nothing structural.** Cross-tabulated against `num_voices` it is
scattered — 241 appears on voice counts from 1 to 30, 242 on 1 to 40. It is not a
count, an index or a size.

### A hypothesis worth one cheap hardware test

Read as a **signed** byte, every value in the whole 1184-header corpus lands in
**−17..0**, and `E4_PRESET_VOLUME` (SysEx id 1) is a signed dB field with range
**−96..10**. Nothing in the corpus falls outside it.

That fits a per-program gain trim the importer derives from the AKAI source and
everything else leaves at 0 dB, and it explains why the machine preserves the byte
and why 0 is legal. **It is a hypothesis, not a result** — the corpus only ever
exercises −17..0, which is consistent with a volume field but far from proof, and
"signed byte lands in a wide range" is weak evidence on its own.

One SysEx read settles it: load the import, select one of the presets whose byte
27 is 249 (−7) and read id 1. If it reads −7, byte 27 is the preset volume. If it
reads 0, the hypothesis is dead and byte 27 is still unidentified.

### §151 addendum — the "704 headers" figure is worthless as an independence claim, and I wrote it

mpc2emu pushed back that the range test carries much less for the wide-range
fields than for the algorithm bytes. They were right, and checking it properly
made the problem **larger than their version of it**.

```
  total non-zero FX blocks : 704
  DISTINCT blocks          : 6
  contributing banks       : 3, of which two are the same bank round-tripped
                             (_rt_new / _rt_orig -- FX blocks byte-identical)
  690 of the 704 are one single repeated block
```

**So the real n is six distinct FX blocks from two independent sources, not 704.**
"1184 preset headers, 704 non-zero, zero range violations" reads like a corpus
result and is one bank's default effect copied 690 times. I wrote that sentence
and put it in a commit message; it should have read "6 distinct".

**This is the argument-from-a-large-number failure, again.** §138 was argmax over
a big array reporting one artefact; this is 704 samples of one value. The count
was of rows, and the evidence is in distinct rows.

### Which of the sixteen fields actually has evidence

Headroom used = largest value observed against the field's limit. A limit the data
never approached was never tested:

| field | limit | max seen | headroom | presets non-zero |
|---|---:|---:|---:|---:|
| FX_A_ALGORITHM | 44 | 20 | 45% | 704 |
| FX_A_PARM_0 Decay Time | 90 | 60 | 67% | 704 |
| FX_A_PARM_1 HF Damping | 127 | 120 | **94%** | 704 |
| FX_A_PARM_2 FxB==>FxA | 127 | 33 | 26% | **1** |
| FX_A_AMT_0 Main | 100 | 11 | 11% | 702 |
| FX_A_AMT_1..3 Sub 1-3 | 100 | 0 | **0%** | **0** |
| FX_B_ALGORITHM | 32 | 24 | 75% | 704 |
| FX_B_PARM_0 Feedback | 127 | 48 | 38% | **10** |
| FX_B_PARM_1 LFO Rate | 127 | 24 | 19% | 704 |
| FX_B_PARM_2 Delay Time | 127 | 66 | 52% | **9** |
| FX_B_AMT_0 Main | 100 | 10 | 10% | **9** |
| FX_B_AMT_1..3 Sub 1-3 | 100 | 0 | **0%** | **0** |

**Six of the sixteen bytes — every Sub 1-3 send — are non-zero nowhere in the
corpus.** Their placement rests entirely on "the group is four bytes wide and the
first one behaves", which is an argument from layout symmetry and not evidence.
`FX_A_PARM_2` rests on a single preset.

**What does survive, and why it is still worth having:**

- `FX_A_PARM_1` reaching **120 against a limit of 127** is the one genuinely tight
  range result, and it is the byte that cannot sit in the `PARM_0` slot, whose
  limit is 90. That pins the A-side parameter *order* independently of labels.
- The field order matches SysEx ids 6-21 exactly across all sixteen positions.
- **A machine-to-file link exists after all, and I said it did not.** Preset 14 of
  the loaded bank read over SysEx as FX B = algorithm 24, parms 24, 3, 50. One of
  the six distinct file blocks carries `... 24 24 3 50 ...` at bytes 68-71 — four
  bytes, same order, from a different bank. A common factory FX B setting turning
  up identically in a file read and a SysEx read is real corroboration of the
  B-half layout, and it is stronger than anything the range test contributed.

**The §151 headline is unaffected.** "All 363 imported presets have an all-zero FX
block" is a statement about *zeros*, and zero is zero wherever the block sits — it
needs the offsets to be right but not the fields to be individually validated. The
byte-27 refutation likewise only needs the block to be at 60-75 and zero there.

What weakens is any claim about *where each individual field sits inside the
block*, and it weakens most exactly where mpc2emu said it would.

### §150 addendum — the master FX block cannot select "inherit", which is independent proof of the index-0 semantics

Checking the *master* FX ids (228-243) against the device after correcting the
preset ones found two mismatches, and the second was not the one being looked for:

```
  228 MASTER_FX_A_ALGORITHM    device 1..44    ours 0..44   <<<
  236 MASTER_FX_B_ALGORITHM    device 1..32    ours 0..27   <<<
        (the other 14 master FX ids agree exactly, defaults included)
```

The stale maximum on 236 was expected — it is id 14's bug in the second place it
was written. **The minimum is the interesting one: the master FX algorithm starts
at 1, not 0, in both blocks.**

That is exactly what §150's index-0 reading predicts and nothing else explains.
Value 0 is `Master Effect A`/`B`, meaning *inherit the master setting*, so the
master block cannot select it — it would be inheriting from itself. **Had index 0
been `Room 1` as the old tables claimed, there would be no reason for the master
to exclude a plain reverb.**

This matters because it is **independent of the evidence that produced the
correction**. §150 rested on six algorithm values matched against the front panel,
all from one bank. This is a different mechanism (a range request), a different
parameter block, and it agrees. Two of the sixteen master ids were wrong in a way
that only makes sense if the corrected reading is right.

### What it cost in the TUI, which is not nothing

`EditValueScreen` enforces the declared range on submit:

```python
  if not (self.minimum <= value <= self.maximum):
      return
```

So with a maximum of 27, **typing 28-32 and pressing enter did nothing at all** —
no error, no status line, the dialog simply refused. The five distortion
algorithms were unreachable from the editor and the failure was silent. With a
minimum of 0 on the master blocks, stepping down offered a value the device
rejects.

### §150 addendum 2 — the enumerated-value picker, and the rule it is built around

`EditValueScreen` asks for a number. For a parameter whose values are an
enumeration that is the wrong question: nobody knows that Cavern is 25, and the
whole reason §150 exists is that the number-to-name mapping was wrong for a year
without looking wrong.

`ChoiceScreen` (`eosed/app.py`) lists the names instead, for FX algorithms,
filter types, LFO shapes and cord sources/destinations — anything
`params.value_choices()` answers for.

**The design rule comes from the bug it is meant to stop repeating.**

- **Every value in the device's range gets a row, named or not.** An unnamed
  value shows as `(unnamed)` and is still selectable. The temptation is to list
  the names we hold, which would mean a stale or incomplete table silently
  hiding legal values — *exactly* the failure the maximum of 27 produced, where
  typing 28-32 did nothing and said nothing. A picker built from our own table
  would have rebuilt that failure in a new place and made it harder to see.
- **The range comes from the device (`04h`), never from the table's keys.**
  `MASTER_FX_A_ALGORITHM` shares `FX_A_ALGORITHM_NAMES` with the preset field
  but starts at 1, since 0 is "inherit the master". Filtering by the table would
  offer a value the device rejects.

`value_choices()` deliberately returns nothing for `FX_*_PARM_*`, `FX_*_AMT_*`
and the envelope stages. Those names label the **field**, not the value — id 7 is
"Decay Time" whatever it holds — and offering them as choices would invite
picking "HF Damping" as the *value* of "Decay Time". The two questions
`_known_value_name` and `value_choices` answer look similar and are not the same.

Parameters with no enumeration, or a range wider than 512, still get the numeric
dialog.

## §152 — The 8-36 ladder: the overlap joins, and the fast end is not a straight line (2026-09-20, live)

mpc2emu built `CD4-DCYFAST` to reach the rungs §149 could not. The trick is worth
recording because it solved a problem this project had filed as a hard limit:
**more gain cannot buy time resolution, but the BANK can buy distance.** Dcy1's
target level is patched to silence and Dcy2's rate to zero, so Dcy1 carries the
whole 97.82 dB at the same rate byte — 3.37x longer. Byte 8 goes from 33 ms to
116 ms. The byte under test is untouched; only the distance moves.

They captured and handed over the audio without fitting it, on s3ked's principle
that the estimator decides the answer and a second one would make the overlap
rungs meaningless as a check.

### The estimator, validated first

Overlapping windows at hop W/4, window sized per rung so **at most 1 dB falls
inside one window**, points selected by walking forward from the peak and
**stopping** at the floor. Each measured rate was then fed back as a synthetic
exponential and re-extracted:

```
  bias against synthetic at the measured rate: -0.51% to +0.39% on all 15 rungs
```

**A hypothesis of mine died here and it is worth keeping.** The first pass used a
fixed 6 ms window and I attributed the fast-end disagreement to smearing — a long
window averages the fall and reports it slower, which is the right direction.
Re-running at 1 ms changed byte 8 by **0.1%** (1005.70 -> 1004.61). The estimator
was not the problem, and the explanation that fit the direction was still wrong.

### The overlap rungs join

| byte | this ladder | §149 ladder | diff |
|---:|---:|---:|---:|
| 24 | 371.92 | 377.03 | −1.4% |
| 32 | 234.91 | 236.42 | −0.6% |

**Two independently built banks, different spans, different sessions, agreeing to
about 1%.** That is what the overlap was for and it passes.

### The fast end disagrees, and the reason is that it is curved

Fitting only the first *n* dB of each full-span decay:

| byte | 10 dB | 20 dB | 30 dB | 40 dB | 50 dB | §149 |
|---:|---:|---:|---:|---:|---:|---:|
| 8 | 1305.5 | 1169.2 | 1173.8 | 1048.4 | 1002.5 | 1261.40 |
| 16 | 663.8 | 681.9 | 674.8 | 625.5 | 513.5 | 861.26 |
| 24 | 371.4 | 385.1 | 380.7 | 381.5 | 371.0 | 377.03 |
| 32 | 238.0 | 232.0 | 236.0 | 236.0 | 236.1 | 236.42 |

**Bytes 24 and 32 are flat across every window — real straight lines. Bytes 8 and
16 are not.** They fall steadily as more of the decay is included, and their r² is
0.93-0.97 where the slow rungs reach 0.999. The r² was telling us the model was
wrong and the first pass read it as "thin data".

So **"the decay rate at byte 8" is not a single number.** It depends on how much
of the decay is measured, which means the two ladders were never measuring the
same quantity down there: §149's short span sampled mostly the steep early
portion, and byte 8's first 10 dB here reads **1305.5** against §149's **1261.40**,
a 3.5% agreement.

**Byte 16 does not resolve that way and is left open.** Its steepest window reads
663-682 where §149 reported 861.26, and no sub-span of this capture reaches 861.
That is a real disagreement between two ladders, not a span artefact, and it is
recorded unresolved rather than averaged away.

### What this does to §149's law

The law was fitted over 32-127 and **nothing here disturbs it** — both overlap
rungs land within 1.4%. What changes is the meaning of extending it downward:

- Below roughly byte 20 the decay is **not exponential**, so no single rate law can
  describe it and the "knee in 24-32" from §149 addendum 1 is better read as the
  point where a straight-line model stops applying at all.
- §149's three recovered fast rungs (1261.40, 861.26, 377.03) are still real
  measurements, but they are **rates of the early portion**, not of the decay, and
  they should be quoted that way.

**This is the second time today a number was well measured and badly defined.**
The first was mpc2emu's span convention; this is the same shape — the measurement
was sound and the quantity it named was not.

## §153 — Key+ vs Key~: blocked, because zone key range cannot be set live (2026-09-20, live)

The measurement mpc2emu wanted — whether the key-polarity cord family shares a
span, which is load-bearing under two thirds of every third-party bank they read
— **did not happen.** Recording why, and three things the failed attempt
established.

### The blocker

```
  select zone 0, write keylow=0 keyhigh=127   ->  readback 0/127     accepted
  play key 36                                 ->  -70 dBFS           silent
  play key 69                                 ->  -13 dBFS           sounds
  force a reload, program change 1 -> 0       ->  still -70 at key 36
```

**The edit is accepted, stored, reads back correctly, and the live voice mapping
does not follow it.** This project already records that a remote edit is not
reflected until the preset is touched from the front panel. This is a sharper
form: not "the LCD disagrees with the edit" but **"the key mapping disagrees with
the edit"**, and a program-change round trip does not flush it.

So on a bank whose zones are one key wide — which `CD4-DCYFAST`'s are, by design,
since any non-root key resamples the noise and tilts its spectrum — **there is no
second key to measure at and no way to make one over SysEx.** The remaining route
is a purpose-built two-key bank, which needs a card crossing.

### The run that produced a full set of numbers from nothing

The first attempt completed: six captures, three conditions, a corner-frequency
estimator, and this table.

```
  run        k36 Hz    k84 Hz   ratio   cents/oct
  control    2037.5    2822.5   1.385       141.1
  keyplus    3297.5    2553.8   0.774      -110.6
  keytilde   2847.5    2480.0   0.871       -59.8
```

**Every one of those six captures was at the noise floor.** RMS −83.5 dBFS on all
six, identical band profiles; the E4XT was producing nothing, because the zone
was never widened. The estimator returned corner frequencies for room noise, and
the three conditions differed because noise differs.

Two things made it look like a result rather than a failure: the numbers were
plausible in magnitude, and the control was *non-zero* in a way that invited
explanation rather than suspicion. What exposed it was checking the **absolute
level**, which no part of the analysis needed.

**A fit to a non-existent quantity still returns a number** — recorded earlier
tonight about a span convention, and here the non-existent quantity was the
signal itself. The generalisation: an estimator that cannot fail loudly needs a
separate check that its input exists at all, and that check is almost never part
of the estimator.

### Two protocol findings

**`SAMPLE_ZONE_SELECT` (id 226) reads 16383 by default, and zone-scoped
parameters then address nothing while reading back as written.** The first run
wrote `E4_GEN_KEY_LOW`/`HIGH` with no zone selected; both read back correct and
neither had any effect. §148 in a third costume — the readback confirms the
address, not the effect.

**Zone selection breaks voice-level READS but not WRITES.** With zone 0 selected,
writes to the cord ids read back as `(0,0,0)`; re-selecting the voice made them
read `(8,56)` immediately. The writes had landed throughout. Our existing note
says zone select "breaks voice-level addressing", which is too coarse: code that
writes a voice parameter, reads it back to verify and sees zero will conclude the
write failed and retry, wrongly.

### What caught it

mpc2emu's instruction to read the cord's source, destination **and** amount back
after writing — not to trust that the write returned cleanly. The assert fired on
`(0,0,0)` against the expected `(8,56,0)` and stopped the second run before six
more captures reached the analysis.

### Machine state

`CD4-DCYFAST` verified rung by rung afterwards: Dcy1 rate reads 8, 10, 12 … 36
across presets 0–14, matching the ladder exactly. Preset 0's zone, non-transpose,
filter type, cutoff and cord all back to their original values. Nothing was
written to disk at any point.

### §153 addendum — a second route, prepared and not taken

mpc2emu built a purpose-made two-key bank (`KTPOLAR.E4B`, 7 presets, every key
with its own zone rooted on itself so the playback ratio is exactly 1.0 and the
resampling tilt never arises) and pointed out that it may not be needed:
**§153's blocker was a live parameter edit, and a whole-preset send is a
different operation.** If a preset dump establishes its own zones, the same
seven presets can be built against the noise sample already resident in RAM,
with no card crossing.

That is worth testing and it is prepared:

```
  OLD-format dump of preset 0, 360 bytes
  zone param offsets cross-checked: the three bytes reading 69 sit at 80/82/86,
    spaced 0, 1 and 3 params apart at 2 bytes each, matching zone ids
    44 ORIG_KEY, 45 KEY_LOW, 47 KEY_HIGH exactly
  patched to root/low/high = 69/36/84, retargeted to preset 15 ("Empty Preset")
  -> NOT SENT
```

**It is not taken, and the reason is this project's own rule rather than a
judgement about risk.** `send_preset_old` overwrites a whole preset slot, and
`eos/bridge.py` refuses it without `allow_write=True` while requiring the caller
to put it behind an explicit arm-then-fire confirmation — the same gate as the
Master erase utilities. Writing to an empty slot is low-risk in fact, but a
script that simply passes `allow_write=True` is not an arm-then-fire
confirmation; it is the guard being routed around by the one party the guard
exists to stop. The measurement was authorised when the plan was parameter
edits, and a whole-preset write is a different operation class.

`tools/`-adjacent script at `~/temp/eosed-bench/kt_dumproute.py`, inert without
`--fire`, refusing outright if the target slot is not `Empty Preset`.

**If the test passes**, preset dumps establish zones, the measurement runs
against resident RAM and no card moves. **If it fails**, that is a protocol
finding worth as much as the measurement — it would mean zone geometry is
reachable *only* from the front panel or a disk load, which is a real constraint
on what any remote editor can do and belongs in `DISCLAIMER.md`.

### §153 addendum 2 — the preset-dump route, fired: it writes, and it still does not gate the key

Jan approved the whole-preset write. Result: **the dump mechanism works perfectly
and does not solve the problem, because the field it writes is not the one that
decides which key sounds.**

```
  preset 15 (was "Empty Preset"), written from a patched dump of preset 0

    dump bytes 80/82/86  (ORIG_KEY / KEY_LOW / KEY_HIGH)  =  69 / 36 / 84
    live read, no zone selected                           =  69 / 36 / 84
    live read, zone 0 selected                            =  69 /  0 / 127
    keys that sound: 69 ONLY
      36 −70.3   48 −69.5   60 −70.3   68 −68.7   69 −25.8   70 −70.3   84 −70.3
```

Round-trip is exact: dumping preset 15 back and diffing against the source gives
**three differing bytes** — the retarget byte and the two patched ones — so the
send path is sound and the value persists.

**What this establishes:**

- A preset dump **does** write voice-level fields that a live edit also writes,
  and both read back. Neither changes the sounding key.
- `E4_GEN_KEY_LOW`/`KEY_HIGH` at voice level are **not the gate.** The gate is
  the zone's own sample mapping — a separate structure, which the zone-selected
  read shows as a different object (`0/127`, not `36/84`).
- So §153's conclusion narrows rather than reverses: the blocker is not "live
  edits do not reach the voice" but **"the key→sample mapping is not reachable
  through the fields either route writes"**.

**Where the layout defeated me**, recorded so the next attempt starts further on:
the NEW-format header reports 22 global, 29 link, 146 voice and 13 zone
parameters, and params sit at `offset = 22 + 2 × index` — which puts the three
bytes reading 69 at voice indices 7, 8 and 10, i.e. ids 44/45/47 exactly. But
22 + 2×(22+146) already reaches 358 of the dump's 360 bytes, leaving no room for
a 13-parameter zone block. **The header's counts are therefore not all present in
the body**, and the zone block's actual location is unresolved.

**One mistake worth keeping.** Re-deriving the offsets mid-investigation I used
`(offset − 18) / 2` and got `KEY_LOWFADE`/`KEY_HIGH`/`VEL_LOW` — plausible names,
wrong answer, and I briefly believed my original identification had been wrong.
The base is 22, not 18. What caught it was that the *differences* between the
three offsets (0, 1, 3 params) match ids 44, 45, 47 under one base and nothing
sensible under the other. **A layout hypothesis that has to explain three related
fields at once is much harder to get wrong than one checked field at a time.**

### Machine state

`CD4-DCYFAST` presets 0–14 untouched and verified. **Preset 15 now holds a copy
of preset 0 with KEY_LOW/KEY_HIGH 36/84**, where it previously read "Empty
Preset". It cannot be returned to empty without Preset Delete (`71h`), which this
project does not send speculatively, so it is left in place — RAM only, gone on
the next bank load or power cycle. Nothing was written to disk.

### §153 addendum 3 — the 0/127 read is real, and it makes the conclusion stronger than the one it replaces

mpc2emu challenged the `0/127` zone reading as §148 in a third costume — a read
that was not addressing a zone at all. **It was addressing one.** The
discriminator is the sample index, which an unaddressed read cannot produce:

```
  preset  0  zone 0: sample=1 root=69 low=69  high=69     voice: 69/69/69
  preset 15  zone 0: sample=1 root=69 low= 0  high=127    voice: 69/36/84
  preset  0  zone 1: sample=0 root= 0 low=16  high=0      (empty, both presets)
```

`sample=1` on both, an empty zone 1 on both, and the selector reading back the
value written. The read is real, and their file — which says that zone is 69/69 —
is describing the bank on disk, not the object in RAM after a preset send.

**Which makes the result stranger than either explanation on offer.** Writing the
preset moved the zone's key range to **0–127**, not to the 36/84 I patched and
not leaving it at 69/69. So after the send:

```
  zone key range   0 .. 127     (wide open)
  voice key range 36 ..  84
  keys that sound  69 only
```

**Neither range explains the behaviour, so neither is the gate.** The conclusion
is no longer "the zone entry is the gate" — it is that **the playback mapping is
compiled at bank load and is not rebuilt by a remote write**, at parameter level
or at whole-preset level, and a program-change round trip does not rebuild it
either. The structures a remote editor can read and write are the edit-side
representation; what the machine plays from is a separate compiled object that
only a bank load or the front panel regenerates.

That is a stronger statement than the one it replaces and it belongs in
`DISCLAIMER.md`: **a remote editor cannot change which key sounds.** Everything
this project does — parameter edits, preset sends — operates on a representation
the sound engine has already finished reading.

It also explains §153's original symptom without needing the zone entry at all,
and it explains why a program change did not help: selecting a preset chooses
among compiled objects rather than recompiling one.

**What would test it in one line**, once mpc2emu's purpose-built bank is loaded
from a card: its voice window is 36–84 with three zones at 36/36, 60/60, 84/84.
Select zone 1 and a working read must say **60/60**. If it does, the read path is
sound and the compile-at-load reading stands. If it says 0/127 again, then a
preset send is rewriting zone ranges on its own and that is a different finding.

**On method, from mpc2emu and worth keeping next to the base-18 slip:** identify
by a *relation a wrong hypothesis cannot satisfy*, not by a position anything can
occupy. The sample index settled this because an unaddressed read cannot invent
a 1; the key range alone could not have, because 0/127 is exactly what an
unaddressed read might plausibly return.

### §153 addendum 4 — the byte count is right, the default is confirmed, the link prediction is untestable here

mpc2emu's arithmetic against the 360-byte body:

```
  global + voice only      22 + 2*(22+146)        = 358  + 2 = 360   fits
  global + link + voice    22 + 2*(22+29+146)     = 416             no
  all four sets            22 + 2*(22+29+146+13)  = 442             no
```

Only the zone-less, link-less layout fits. **So the send does not carry zone
parameters**, and the 0/127 is the receiver defaulting a range it was never
given — not a send that rewrites zone ranges, which was the worse of the two
outcomes and is now off the table.

**Confirmed against a control they did not have.** Preset 16 was never written
and still reads "Empty Preset":

```
  preset  0  zone (sample, root, low, high) = (1, 69,  69,  69)
  preset 15  zone                           = (1, 69,   0, 127)   created by the send
  preset 16  zone                           = (0,  0,  16,   0)   never created
```

A never-created zone reads `(0, 0, 16, 0)` — so **0/127 is not simply "what an
empty slot says"**. It is what a zone *created by a preset send* says: the send
carried the sample index and the root key and left the key range unset, and the
machine opened it wide. That is a sharper confirmation than the byte count alone,
because it distinguishes "defaulted on creation" from "was always that".

**Actionable, and it belongs in `DISCLAIMER.md`: a preset send silently discards
the zone mapping.** Anyone who sends a multi-zone preset gets zones with no key
ranges back and no error. For a tool whose whole purpose is remote editing, that
is a sharper limitation than the compile-at-load one and it has a victim.

### The link prediction cannot be tested on this material

Their inference predicts link parameters are also absent from the body, so a sent
preset should show defaults rather than the source's values. Measured:

```
  link params identical across presets 0, 15 AND 16
  8 non-zero ids (253, 254, 257-262) — the same 8 in all three
```

Preset 0's link parameters **are already at their defaults**, so carried and
not-carried predict the same reading. The test returns "identical" and means
nothing.

This is the third instance tonight of the rule mpc2emu gave and then sharpened —
**a field that barely varies cannot identify anything downstream of it** — and
the first time it has caught a test of *theirs* rather than of ours. Testing link
carriage needs a preset with non-default links, which nothing on this bank has.

### Where this leaves §153

Two independent facts, each covering what the other cannot:

- **the dump omits zone parameters** → explains the 0/127 reading;
- **the playback mapping is compiled at bank load** → explains why nothing became
  audible at keys 36–84 although both recorded ranges permitted them.

The second is still the one that blocks the measurement, and it is unaffected by
the first.

### §153 addendum 5 — the remaining blocker is one button, and it is not remotely reachable

mpc2emu's two-key bank is on the card (`CD7-KTPOLAR.iso`, verified byte-identical
at 23:42). That does not unblock the measurement, because **the editor protocol
has no load-bank command.** The only bank-scope command in the message set is
`ERASE_RAM_BANK` (`0x74`), which this project does not send.

The panel protocol could in principle drive the front panel to load, but that is
the reverse-engineered protocol, this project's rules require verifying any byte
sequence by capture before writing code against it, and it is adjacent to the
diversion command that must never be sent speculatively. Not a route to take for
convenience.

**So: a remote editor can read everything, write parameters and whole presets,
and cannot load a bank or change which key sounds.** Those two limits are
related — both are things the sound engine reads once, at load, from a path the
editor protocol does not reach — and together they are the honest boundary of
what this project can do without a hand on the machine. `DISCLAIMER.md` should
say so in those terms.

Once the bank is loaded, everything after is automated: zone-1 read first (it
must say 60/60), then seven presets × three keys, with the absolute level of
every take checked before anything is fitted.

### The link question is blocked on the same button

mpc2emu offered to locate link parameters in the preset header by relation: name
a link value read over SysEx, and they scan 1162 presets for the header byte
carrying it. **Neither side can supply the other's half from what is loaded.**
Their corpus can say which header bytes vary; only a SysEx read can say what a
link parameter currently *is*. The three presets read here are all at defaults —
the same 8 non-zero ids (253, 254, 257–262, all 1) and 21 zeros — which is worth
recording as the default vector and discriminates nothing.

Filling it needs any bank with non-default links in RAM, which needs the same
front-panel load. If a third-party bank is ever loaded for other reasons, the
link vector is 29 reads, no audio and no writes — worth grabbing opportunistically.

Their candidate header bytes are explicitly "places to look, no evidence any of
them is a link field", which is the status the thirteen rescale rows had before
the corpus check — and three of those turned out to be untestable rather than
wrong. Some of the eight should be expected to land the same way: present in the
map, never exercised, indistinguishable from absent.

## §154 — Key+ and Key~ share a span; only the pivot differs (2026-09-20, live)

Measured on mpc2emu's purpose-built `CD7-KTPOLAR`: seven presets, one cord each
at slot 6 (`Key+`/`Key~` → `FilFreq`), three root-matched zones at keys 36, 60
and 84 so nothing is resampled. 4-pole lowpass, corner ~1.8 kHz unmodulated,
resonance zero.

### Raw

```
  preset       k36 Hz    k60 Hz    k84 Hz      ratio 36->84    octaves
  CTRL 0       1820.0    1820.0    1820.0          1.000         0.000
  KEY+ 32      2393.8    2832.3    3596.9          1.503         0.587
  KEY~ 32      1478.5    1820.0    2218.5          1.501         0.585
  KEY+ 64      3218.5    5276.9    9864.6          3.065         1.616
  KEY~ 64      1230.8    1820.0    2535.4          2.060         1.043
  KEY+ 96      4675.4   12887.7   saturated           —             —
  KEY~ 96       960.0    1820.0    3240.0          3.375         1.755
```

**The control is flat** — 1820.0 Hz at all three keys, 0.0 cents/octave. The rig
does not vary with key, so the rest means something.

### The answer

**At amount 32, the only amount where both forms stay fully inside the band:**

```
  Key+ spans 0.587 octaves over keys 36 -> 84
  Key~ spans 0.585 octaves
  Key~/Key+ = 0.997        (1.0 = shared span;  2.0 = bipolar over the key range)
```

**The family shares a span.** A bipolar `Key~` — mapping the key range onto
−1..+1 where `Key+` maps it onto 0..+1 — would have covered **twice** the
octaves at the same amount. It covers the same.

**Only the pivot differs.** `Key~` leaves the corner at exactly the unmodulated
1820.0 Hz at **key 60**, on all three amounts independently. `Key+` never reaches
1820 Hz anywhere in range, so its pivot sits at or below key 0.

This is the same structure as the velocity family measured 2026-09-01 —
`Vel+` pivoting at 0, `Vel<` at 127, `Vel~` at 89.4, one shared span — and it is
what mpc2emu's fix assumed. **Their family read is correct as it stands and needs
no scale factor.**

Linearity in amount checks too: `Key~` spans 0.585 / 1.043 / 1.755 octaves at
amounts 32 / 64 / 96, against 1.0 / 2.0 / 3.0 expected ratios — 1.78 and 3.00
measured.

### What the amounts above 32 cannot say

`Key+` at amounts 64 and 96 drives the corner out of the measurable band: the
passband-to-6.4–12.8 kHz tilt falls to 12.0 dB at amount 64 key 84 and to 1.1 dB
at amount 96 key 84, which is a filter wide open. Its apparent 1.616 octaves at
amount 64 is therefore **not** evidence of a larger span, it is an estimator
running out of spectrum. Only the amount-32 pair carries the result.

### Three traps, all of them ones this project had already recorded

1. **`PRESET_SELECT` moves the editor's pointer; the engine plays what Program
   Change selected.** The first full run — 21 captures, all seven presets — played
   **preset 0 every time**. Every corner read exactly 1820.0 Hz and every peak
   −22.8 dBFS. §150 found this for parameter *reads*; it applies to playback too,
   in the opposite direction, and it produced a perfectly self-consistent table
   of zeros.
2. **Cord slot 6 is ids 147/148/149**, not 135/136/137. An assert on the
   destination caught `(96, 48, 0)` — `Lfo1~ → Pitch`, slot 2 — before it reached
   a capture.
3. **Indexing a slot instead of searching for the cord.** Slot 0 reads
   `(10, 64, 0)` identically on all seven presets; the planted cord is at slot 6.
   This is the defect mpc2emu had just fixed on their own side, made again here
   within the hour.

The identical-peaks signature is what exposed (1): 21 captures agreeing to
0.1 dBFS is not a measurement, it is one measurement repeated.

### §154 addendum — the estimator, calibrated; and where the 0.581-vs-0.713 disagreement lives

mpc2emu reduced §154's captures to a full-scale key-tracking slope and got
**0.5827 / 0.5807 / 0.5804** across three amounts, against their standing
constant of **0.713** — which is not a guess: measured 2026-06-12 at r 0.9994 and
independently predicted to 0.07% from an unrelated sensitivity figure. They asked
two questions about the estimator before either number moves. Both are answered.

### The estimator is log-linear, so §154's ratio is safe

Cutoff byte swept on the control preset, cord amount 0, key 60 throughout:

```
  byte  80 -> 618.5 Hz     byte 140 -> 1578.5     byte 180 -> 3156.9
  byte 100 -> 843.1        byte 147 -> 1820.0     byte 200 -> 4612.3
  byte 120 -> 1175.4       byte 160 -> 2263.1

  log2(corner) vs cutoff byte:  0.024010 oct/byte,  r2 0.998835,  max resid 64 cents
  FFT bin resolution 1.5385 Hz  (0.08% at 1820 Hz)
```

**The round numbers are real bin centres, not a coarse grid** — 1820.0 Hz is bin
1183 and 960.0 Hz is bin 624 exactly. And because the estimator tracks the byte
log-linearly, its offset is **multiplicative**: it cancels in any ratio. §154's
polarity result is a ratio of two numbers taken the same way and is untouched by
everything below.

### The captures are self-consistent with the cord model

Predicting each preset from the measured cutoff law plus §139–§141's rule that a
100% cord moves its destination across its full range:

```
  KEY+ 32   predicted 0.5785 oct over keys 36->84,  measured 0.5873   +1.5%
  KEY~ 32   predicted 0.5785                        measured 0.5853   +1.2%
  KEY~ 96   predicted 1.7587                        measured 1.7549   -0.2%
  KEY~ 64   predicted 1.1570                        measured 1.0425   -9.9%   <- the odd one
```

Three of four agree to 1.5%, and `KEY~ 64` is the point mpc2emu independently
flagged as 11% low. **So the captures, the cutoff law and the cord model all
agree with each other.** The disagreement with 0.713 is not in the measurement.

### Where it does live

```
  full cutoff range, measured here      6.12 octaves over bytes 0..255
  E4B_FORMAT.md (57 Hz .. 20 kHz)       8.45 octaves
  ratio                                 1.381

  0.713 / 0.5785                        1.232
```

**Both discrepancies are in the cutoff law, not in the key-tracking arithmetic.**
A full range 1.38× wider than measured here would raise the predicted slope by
the same factor, which overshoots 0.713 rather than reaching it — so the two do
not reconcile by a single scale either, and at least one more assumption is
wrong.

**Caveat on my own number, stated plainly:** `0.024010 oct/byte` is a −12 dB
point, not a −3 dB corner, and its usable span here is bytes 80–200. Above that
the passband-to-6.4–12.8 kHz tilt falls from 73 dB to 32 dB and the estimate
compresses. Extrapolating it across the full 0–255 to get "6.12 octaves" assumes
log-linearity well outside where it was checked, and that assumption is exactly
the kind this project has been wrong about twice tonight.

**Nothing in the code changes on this.** A constant with two independent
derivations is not overturned by one evening, and mpc2emu is right to record it
as open rather than switch. What this addendum establishes is narrower and
firmer: **the estimator is sound, the captures are self-consistent, and the
disagreement is in the byte→Hz cutoff law that both sides inherited rather than
in anything measured tonight.** That is where the next measurement should point.

## §155 — The cutoff law accelerates, and the region both converters aim at is unmeasurable (2026-09-21, live)

mpc2emu asked for the tilt at bytes 217–255, because that is where their own
July calibration is thinnest and — their corpus number — **53.6% of their
AKAI-converted voices carry a chosen cutoff byte, 22 of 41 sitting at byte 245**,
while EOS's own importer concentrates at byte 221 on 814 voices. Measured on
KTPOLAR's control preset, cord amount 0, key 60, cutoff byte swept:

```
  byte  corner Hz   tilt dB    local slope
   200     4509.2      31.7      0.02572
   210     5589.2      25.3      0.03098
   217     6843.1      20.7      0.04172
   221     7450.8      17.4      0.03069
   230     9563.1      12.0      0.04001   <- unusable
   240    15436.9       5.6      0.06908   <- unusable
   245    19946.2       2.8      0.07395   <- unusable
   250        —         0.8                <- no corner in band
   255        —        -0.2                <- no corner in band
```

**At byte 245 the tilt is 2.8 dB.** The filter is open; there is no corner in the
band to estimate. Any Hz value reported there — theirs from July, mine tonight —
is an estimator returning a number for an input that is not present. My earlier
extrapolation predicted 7.4 dB at byte 240 and zero near 252; measured 5.6 and
0.8. The extrapolation was sound and slightly conservative.

**So the byte this project's writer most often chooses sits in the region where
neither calibration can be trusted.** That is a sharper problem than the constant
disagreement it came from, and it lands on every AKAI→E4B conversion already
produced.

### And the law genuinely accelerates

Restricting to points with **tilt ≥ 15 dB** — the acceptance rule mpc2emu
proposed, applied here for the first time:

```
  bytes  80-200   slope 0.02384 oct/byte   (8 points)
  bytes 200-221   slope 0.03508 oct/byte   (4 points)
  quadratic over all 11 usable points: r2 0.999017, max resid 81.5 cents
```

**The slope rises by ~47% between the two regions, inside the trustworthy band.**
So §154's addendum was wrong to treat `0.024010 oct/byte` as the law: it is the
law's *local* slope over 80–200, and extrapolating it across 0–255 to get "6.12
octaves" understates the total. mpc2emu's July observation that a single
exponential "badly underestimates the top" is **confirmed, and confirmed in a
region where the tilt is still 17–31 dB**, which their own top-end points were
not.

**Both halves of the earlier disagreement therefore resolve the same way**: the
byte→Hz law is not a single exponential, my 6.12-octave figure was an
extrapolation of a local slope, and their top-end points are in a region no
noise-source measurement can reach. Neither calibration was wrong about its own
measurement; both were wrong about the shape between them.

### The rule that produced this

Record the tilt beside every point and **refuse to report a corner for any point
below a stated threshold**, rather than reporting one and caveating it. mpc2emu
proposed it; it is the same shape as checking the absolute level before fitting
(§153) and checking that conditions differ before trusting a flat control (§154).
Three sessions, three versions of one rule: **an estimator returns a number
whether or not its input exists, so the check that the input exists cannot live
inside the estimator.**

15 dB is used here as the threshold and is itself a judgement, not a measurement.

### §155 addendum — the two laws disagree by 0.8 octave in the middle, and the convention is unresolved

Checking mpc2emu's claim that their writer collapses a real AKAI filter onto
"wide open" found a larger problem, and the first attempt at it repeated an error
this project had been handed an hour earlier.

**The error:** comparing my **−12 dB points** against their **corners** gave
byte deltas of 34–52 and was meaningless. A 4-pole is −12 dB at 1.391× its
corner. mpc2emu made this exact mistake in the opposite direction earlier the
same night and reported it; it was in front of me when I made it.

**The convention-independent statement**, which assumes nothing about filter
shape: at byte 200 the −12 dB point measures **4509 Hz** with 31.7 dB of tilt,
and 5589 Hz at byte 210, so about 4900 Hz at byte 206. Their table places
**2000 Hz** at byte 205.9, which on any consistent convention is a −12 dB point
of 2782 Hz.

```
  ratio 1.76  ->  0.82 octave, at a byte where tilt is ~30 dB
```

**That is the middle of the range, not the top.** Both calibrations should be
reliable there. The disagreement is therefore not explained by §155's dead zone.

### The convention gates everything and is answerable for free

Whether their FILFRQ-93 collapse is real depends on what their July extractor
measured:

- **if their table records corners**, their byte 245 for 7643 Hz is nearly right
  on my curve (~242) and the collapse is much smaller than feared;
- **if it records −12 dB points**, 245 is ~20 bytes high and the collapse is real
  and audible.

Nothing outside their code can settle it, and until it is settled neither side
can claim a byte is misplaced. **A listening test run before that is spent
attention**: a null result under the first reading tells nobody anything.

**Caveat on this project's own half, stated because it is load-bearing:**
converting −12 dB points to corners assumes a **Butterworth** response. The
E4XT's 4-pole may not be. The 4509 Hz at byte 200 is measured; every corner
derived from it by dividing by 1.391 is not.

### Three open items, in the order they should be taken

```
  1. convention   what did each extractor measure?   free, code-only, gates 2 and 3
  2. middle       0.82 octave apart at byte 206      both nominally reliable
  3. top          byte > 230 unmeasurable by either  needs a source flat past 20 kHz
```

This is the same ordering error the project keeps making in miniature: item 3 was
chased first because it had a number attached, item 2 was found by accident while
checking something else, and item 1 — the cheapest, and the one that decides
whether 2 and 3 are even well-posed — surfaced last.

## §156 — The Butterworth factor is refuted, and §155's "0.82 octave" is void (2026-09-21)

mpc2emu re-ran their July extractor (`hw_measure.spectrum` + `corner_frequency`,
the exact pair that built `_E4XT_CUTOFF_TABLE`) over this session's `ktcal`
captures. Three results, and two of them retract things recorded here.

### The rigs never disagreed

Their estimator at `drop_db=12.0` against mine, same captures:

```
  byte   mine      theirs
   147   1820.0    1772.5
   200   4509.2    4450.2
   210   5589.2    5528.3
   217   6843.1    6659.2
   230   9563.1    9908.2
   240  15436.9   15685.5
```

Two independently written extractors, within a few percent. **Whatever was wrong
was never the measurement.**

### The −12 dB / −3 dB ratio is NOT 1.391

Measured on the same captures:

```
  byte  80  1.22    byte 160  1.74    byte 217  2.05
  byte 120  1.45    byte 180  2.00    byte 230  2.02
  byte 147  1.64    byte 200  2.05    byte 240  2.07
```

**It climbs from 1.22 to 2.05.** A 4-pole Butterworth would give a constant
1.391. Below byte 120 the ratio is *under* 1.391, so the filter is steeper than
4-pole near its corner; above byte 180 the climb is the tilt collapse of §155
arriving from the other side.

**So no single factor converts between the two conventions, and every
cross-convention number either project has quoted is void.** That includes
§155's addendum, which stated a 1.76× / **0.82 octave** disagreement at byte 206
and called it "convention-independent". **It was not** — it converted their
corner to a −12 dB point by multiplying by 1.391, which is precisely the step
that does not hold. The claim is withdrawn.

The Butterworth assumption was flagged as load-bearing in §155 when it was made.
It was load-bearing, and it was wrong. **Flagging an assumption does not
discharge it.**

### At matched convention the gap is 0.27 octave

`table / (−3 dB reading of the same capture)`, thirteen points:

```
  0.791 0.883 0.843 0.893 0.908 0.871 0.826 0.816 0.839 0.830 0.813 0.776 0.711
  median 0.830, sd 0.051, across a 4.5x span of corner frequency
```

A **scale** error of about 1.20×, consistent across the range — not the shape
error the cross-convention comparison implied, and about a quarter of its size.

### §154's polarity result survives an attempt to reproduce it, and that is the strongest thing that happened to it

mpc2emu re-read the `ktpolar2` captures with their own estimator at
`drop_db=3.0`. The control stays flat — 1084.0 Hz at all three keys, so the bank
is sound — but the per-preset readings **quantise**: 1084.0 five times, 1277.3
twice. Their 1/6-octave smoothing is ~12% wide against a total signal of
0.39–0.48 octave, and `Key~/Key+` comes out **1.23** on those values instead of
0.997.

**That is their estimator landing on a grid coarser than the effect, and they
identified it as such rather than as a contradiction.** The −12 dB point sits on
the asymptote and is well conditioned for a *ratio*; the −3 dB point sits in the
knee and is the right choice for a *calibration*. Different questions, different
estimators — which is why §154's ratio and their table can both be sound.

### What it does to the keytrack constant: worse

Converting this session's readings through a measured −12→−3 curve gives
full-scale slopes of **0.41–0.42**, against §154's 0.581 and their standing
0.713. **Three estimates, three conventions, no reconciliation** — and the
conversion's own assumptions are now suspect too.

Their observation, which is the sharpest thing in the exchange: if the 0.713 and
the LFO-sensitivity figure that independently predicted it to 0.07% both came
from this estimator at this convention, **they share one ruler**, and their
agreement would be explained without either being correct. A prediction that
uses the same instrument as the thing it predicts is not an independent check.

**Nothing in either codebase moves on this.** The measurement that settles it is
still a cutoff sweep against a source with energy flat past 20 kHz.

### §156 addendum — the low end, and the 1.391 partly rehabilitated

mpc2emu asked for a downward extension (bytes 20–70) rather than more of the top,
on the grounds that if the 0.830 scale error holds down there their table is
correctable by one multiplication, and if it walks it is a shape error no constant
fixes. Run, and the first attempt failed in a way that proved the session's own
rule.

**The estimator floored.** Bytes 20, 30, 40 and 50 all read **401.5 Hz** — the
same value four times. The estimator searches upward from 400 Hz for a 12 dB
drop, so any corner below 400 Hz returns the first bin of the search range.
**A value repeating exactly is a fact about the apparatus**, and it was caught
immediately for that reason rather than by noticing the physics was wrong.

Re-analysed by dividing each spectrum by the `cut255` capture — mpc2emu's own
method — which removes the source's shape and allows the search to start at
80 Hz:

```
  byte   -12 dB pt   -3 dB pt   ratio
    20      235.4      170.8    1.378
    30      261.5      186.2    1.405
    40      310.8      223.1    1.393
    50      355.4      256.9    1.383
    60      436.9      323.1    1.352
    70      495.4      356.9    1.388
    80      612.3      449.2    1.363
   100      847.7      601.5    1.409
   120     1180.0      821.5    1.436
   140     1595.4     1004.6    1.588
   147     1764.6     1069.2    1.650
   160     2190.8     1235.4    1.773
   180     2955.4     1466.2    2.016
   200     4444.6     2155.4    2.062
```

**Bytes 20–100 average 1.386 against the Butterworth 1.391.** So the filter *is*
4-pole Butterworth where it can be measured cleanly, and the ratio's climb is
confined to bytes above ~120.

**This refines §156 rather than reversing it.** The headline stands — no single
factor converts between conventions across the range, so cross-convention numbers
remain void. But §156's explanation was wrong in both directions: it said the
filter is "steeper than 4-pole near its corner" on the strength of a 1.22 reading
at byte 80, and that reading was contaminated. With the source divided out byte 80
gives 1.363, not 1.22. **The low end is Butterworth; only the top departs.**

Whether the departure above byte 120 is the filter opening out or the −12 dB
point running out of measurable spectrum is **not settled here** — §155 showed the
tilt collapsing over exactly that range, and both explanations predict a climbing
ratio. That is the same ambiguity as the top-end table points, one convention
down.

**What mpc2emu asked for** is the `-3 dB` column above: their `table / measured`
ratio can be computed at bytes 20–70 from it directly, which answers scale-versus-
shape without further hardware.

**Machine state:** cutoff restored to 147, KTPOLAR otherwise untouched, nothing
written to disk. Captures kept in `~/temp/eosed-bench/ktcal/`.

### §156 addendum 2 — resolved: the table is 0.17 octave low, and the open item is a method

mpc2emu ran their extractor against the same fourteen captures. The two agree to
**2.4% from byte 100 upward** — so the disagreement was never the code — and
diverge at exactly one point:

```
  byte  80   1.115    <- 11.5% apart
  byte 100   0.979        byte 160  1.024
  byte 120   0.984        byte 180  1.017
  byte 140   0.997        byte 200  1.006
  byte 147   1.014
```

**At byte 80 the corner is ~450 Hz, inside their extractor's 100–500 Hz reference
band.** Their own function's comments warn the band must be flat or it measures
the source; here the *filter* walks into the band and the reading comes out high.
The reference-divided method does not have that failure because it has no fixed
band.

### Their table, measured against these captures

```
  bytes  20-100   median table/measured 0.916   0.13 octave low   sd 0.033
  bytes 120-200   median 0.866                  0.21 octave low   sd 0.037
  all fourteen    median 0.892                  0.17 octave low   sd 0.041
```

**0.17 octave** — a fifth of the 0.82 this project reported and withdrew, and
smaller again than the 0.27 their own first re-extraction gave.

### The walk is probably the July method, not the law

Band overlap biases a reading **high**, which drives `table/measured` toward 1 —
and the ratio sits highest at the bottom of the table, which is exactly where
every original point was measured with a band the corner approaches. So the mild
walk between the two halves may be the old method failing progressively rather
than the law bending.

### What this settles, and the correction that goes with it

mpc2emu has retracted **"the filter is steeper than 4-pole near its corner"**,
which came from their contaminated byte-80 reading. They describe it as their
point rather than this project's inference — **that is too generous and is not
recorded that way.** §156 stated it as an explanation of the data, in this
project's own words, without checking whether the single low-end point carrying
it was sound. A number received from elsewhere becomes yours the moment you
build an explanation on it.

**The open item is now a method rather than a disagreement:** rebuild the table
with a reference-divided estimator — divide by a wide-open capture instead of
trusting a fixed band, and move the reference window down for low settings. A
day with the rig, and no ambiguity about what to do. That is worth more than the
0.17 octave.

### The rule this session produced, in its final form

**A value repeating exactly is a fact about your apparatus — and it is only
visible upstream of the summary.**

Four instances in one session, each caught only by looking at values rather than
at a derived statistic:

```
  21 captures at 0.1 dBFS apart     one preset played 21 times (§154)
  401.5 Hz four times               an estimator's search floor (§156 add. 1)
  1084.0 Hz five times              a grid coarser than the effect (mpc2emu)
  "1514 of 1514"                    a check that could not fail (k2kremote)
```

Every derived figure above was plausible — a cents/octave slope, a corner
frequency, a polarity ratio, a pass rate. **The summary is exactly the thing
that hides the repetition.**

## §157 — The Ensoniq table validated end to end, and three of its four rows still prove nothing (2026-09-21, live)

**Status: the conversion table is confirmed where it can be, and marked
unverifiable where it cannot. Only the root key is strong evidence.**

Jan imported the first bank of `CD7-ENSVFX` on the E4XT — EOS's own importer
doing the conversion — and the question was whether the table derived from the
firmware in `ENSONIQ_ROLAND_IMPORT.md` predicts EOS's output byte for byte. It
does. The interesting part is how much less that establishes than it sounds.

### Method

Forty presets came back in the dump (`ensdump.py` → SysEx `dump preset`, 360
bytes each). `enscompare.py` reads the ISO's instrument blocks at base 880, runs
each documented law forward, and compares against the dumped zone:

```
  root key   ISO +170            -> zone root key
  volume     TABLE_0x796a4[+208] -> zone volume
  key low    ISO +274            -> zone key low
  key high   ISO +276            -> zone key high
```

30 non-empty presets × 4 fields = **120/120 match, no exceptions.**

### Why 120/120 is the wrong number to quote

Distinct values per field, across the whole bank:

```
  root    6 distinct  (50,55,57,60,62,69)   STRONG
  klow    2 distinct  (21,36)               weak
  khigh   2 distinct  (67,108)              weak
  volume  1 distinct  (0)                   NONE
  pan     1 distinct  (0)                   NONE
  ftune   1 distinct  (0)                   NONE
```

Half the matching fields are **constants**. A converter that hardcoded volume 0
and pan 0 would score exactly the same 120/120 on this bank. The honest reading:

- **Root key is properly validated.** Six distinct values, each predicted from a
  fixed disc offset across ten instruments — a wrong base cannot produce that.
- **Key range is thin but real** (two values, and they co-vary with instrument:
  the guitar reads 36–67 where everything else reads 21–108).
- **Volume is confirmed at one table index.** `+208` reads 127 everywhere,
  `TABLE_0x796a4[127] = 0 dB`, the E4 reads 0. Index 127 of that table is
  established; the other 127 entries are not touched by this bank.
- **Pan and fine tune establish nothing at all.**

This is §154's rule applied to a whole table at once: *a field that barely
varies cannot identify anything downstream of it* — and the summary statistic
is exactly where that disappears from view.

### Base 880 is fixed, not found by name

> **NARROWED 2026-09-21 by §161 — true on this disc (97 of 97), false in
> general: a second disc gives bases of 656, 1104, 1328, 2544 and larger, and
> 880 holds for 13 of 25 there. The argument below refutes name-location, which
> stands; it never established universality. Marked here as well as in §161
> because this is where the claim is stated.**

The earlier reading had the wavesample struct located via its `UNNAMED WS`
string, with a `+10` name match as the supporting evidence. One instrument in
this bank (`ACOUS-GTR`) carries no such string anywhere, and `B = 880` still
gives root 57 and key range 36–67, matching the E4XT exactly. **The base is a
fixed offset within the instrument file.** The name was never the evidence.

### Four presets per instrument; the empty one is real

EOS writes four presets per Ensoniq instrument, suffixed with the two-character
channel code the loader trace predicted at `0x7be64`:

```
  P000 '<instr>  00'  voices=1  z0 smp=1  root=69  k=21..108
  P001 '<instr>  0*'  voices=1  z0 smp=1  root=69  k=21..108
  P002 '<instr>  *0'  voices=0  z0 smp=None            <- EMPTY
  P003 '<instr>  **'  voices=1  z0 smp=1  root=69  k=21..108
```

Same shape on all ten instruments. mpc2emu's warning was that a zero voice count
can be a *size* bug rather than a genuinely empty preset — their own writer
shipped that fault in June — so the discriminating check is theirs: every dump
is 360 bytes regardless, but the `*0` variant carries **62 non-zero bytes against
71–72** and a zone sample index of **0**. It is empty, not miscounted.

**`*0` selects channel 1 alone, which a mono source does not have.** Three
populated and one empty is what a mono instrument predicts. The test that would
confirm it is a stereo Ensoniq instrument — all four variants should populate.

> **RETRACTED 2026-09-21 by §159 — the four suffixes are LAYER masks, and the
> channel picture is the reverse of this: everything sits on channel 1 and
> channel 0 is empty on every instrument. `*0` is layer 1 alone, which these
> instruments do not populate. Marked here because this paragraph is where the
> claim is made; §159 has the firmware gate.**

### The pan prediction is VOID

`ENSONIQ_ROLAND_IMPORT.md` predicted every import lands centre, because `+221`
and `+225` are odd offsets on word-interleaved data and read as filler. Every
imported zone did land centre. **It still proves nothing**, and mpc2emu called
this before the run: the control is the source side, and the source is centre
too —

```
  source +221 (pan)   across 10 instruments: {0: 10}
  source +225 (boost) across 10 instruments: {0: 10}
```

A correct converter and one that ignores pan entirely produce identical output
here. Worse, the original argument was **circular**: the byte was said to read
zero *because* it is filler, and the support offered for "it is filler" was that
it reads zero. Those are one observation wearing two hats.

Both rows are now marked **unverifiable, not verified**. Closing them needs a
disc with a genuinely panned wavesample.

The generalisation is mpc2emu's and it is the sharper form of §154's rule: **the
uniform-field trap applies to the field you are predicting about, not only to
the fields you are reading.** A prediction of "always X" tested on a corpus that
is always X has been restated, not tested.

## §158 — "Always zero" was a property of one disc: the pan row refuted from a four-disc corpus (2026-09-21)

**Status: §157's unverifiable pan row is now refuted, not merely untested. A
hardware test with five distinct predicted values is designed and waiting.**

§157 closed with pan and boost marked unverifiable: every imported zone landed
centre, but the source was centre on all ten instruments, so the run could not
discriminate. mpc2emu's response was that four more Ensoniq discs were sitting
unscanned on this machine and that a prediction of "always zero" cannot be
tested on a corpus that is always zero.

Scanned. 853 wavesamples across five discs:

```
  disc      wavesamples   non-zero +221   non-zero +225
  ref            97             0               0
  A             547           241              13
  B              39             0               6
  C             222            43              39
  D              45            38               1
  ---------------------------------------------------
  total         853           322              59
```

**Only the disc Jan imported is centred throughout.** The document's claim that
`+221` and `+225` are odd-parity bytes of word-interleaved data and therefore
structurally zero — and its consequence, that every EOS Ensoniq import is panned
centre regardless of source, an importer defect — is **withdrawn**. The parity
count it rested on (102 non-zero at even offsets against 4 at odd) was measured
over one disc's parameter area and generalised to the format.

This is the same error as §157's, one level up. There the caution was *a field
that barely varies cannot identify anything*; here the corpus itself barely
varied, and a property of the content got recorded as a property of the format.
**The uniform-field trap does not stop at the field — the corpus can be the
uniform thing.**

### The field is signed, and my survey read it unsigned

`0x78f10` is `moveb %a0@(221),%d0; extbl %d0; mulsl #63,%d0; divsll #127,%d0`.
The `extbl` makes it a **signed** −127…+127 mapping to the E4's −63…+63:

```
  source  -127   -85   -42    0   +42   +85  +127
  E4 pan   -63   -42   -20    0   +20   +42   +63
```

Those six non-zero values are essentially the entire population. Random bytes
would be uniform over 256 values; a seven-point cluster is a control surface.

The first pass of the survey read the byte **unsigned** and reported 213 values
"out of range 0…127", which made a real result look like apparatus failure — and
it nearly got discarded on that basis. The tables have said "signed, truncating"
since they were written; the defect was in the analysis script only. Worth
keeping because the failure mode is the inverse of the usual one: **an apparatus
bug that disguises a true finding as garbage is as expensive as one that
disguises garbage as a finding**, and the instinct that saved it was checking
whether the suspect records were structurally worse than the rest. They were
better.

### What the survey does not reach

Offset 880 is the only wavesample anchor validated against EOS's own output
(10/10). Later wavesamples are interleaved with their audio at a non-fixed
stride — one instrument's second struct sits at 71072, neither 880+288 nor
block-aligned. A structural-signature scanner built to find them scored **0/10
against the E4 dump** (it matched quantised audio and missed the known struct at
880) and was **discarded rather than tuned**: tuning a detector against the
answer it is meant to produce is how a validated apparatus turns into a
confirming one. So this is wavesample 0 per instrument, and §157's end-to-end
check was voice 0 / zone 0.

Plausibility at +880 runs 69–93% on the new discs against 100% on the reference,
so some entries are not wavesamples. The non-zero-pan records specifically score
91%, 100% and 97% on the internal check that root lies inside its own key range,
against that 75–93% baseline — **cleaner than average, so they are not the
failures.**

### The designed test

Directory block **4213** of disc A: 19 instruments, 14 panned, spanning all five
non-zero source values. One import predicts five distinct E4 pan readings —
**−63, −42, −20, +20, +63** — which no wrong law satisfies. If every zone
instead lands centre, the original defect claim was right and `+221` is not
where EOS reads pan.

Either outcome closes the row. It needs one bank imported on the E4XT; writing
the image to the card is Jan's to authorise.

## §159 — The `*0` preset is an empty layer, not a missing channel: §157's explanation refuted (2026-09-21)

**Status: §157's channel reading is withdrawn. The firmware names the mechanism
and it is a layer mask. The same uniform-corpus trap as §158, in the same disc.**

§157 explained the empty fourth preset by saying `*0` selects channel 1, which a
mono instrument does not have, and proposed a stereo instrument as the
confirming test. mpc2emu accepted it as the cheapest open row and asked for a
stereo census. The census was run, and on the way to it the firmware answered
the question directly — differently.

### The gate

```
  0x78d24:  TABLE[0..3] <- instrument@(44), @(46), @(48), @(50)
  0x78d64:  if layer object null                 -> skip
            if !(TABLE[v] & (1<<L))              -> skip
            chanmask = chan ? instrument@(52) : instrument@(54)
            if !(chanmask & (1<<L))              -> skip
            else include layer L in variant v
```

`0x7bdf0` builds each variant by calling the channel builder twice — `chan=1`
then `chan=0` — and writes the suffix from the two bits of `v` at `0x7be64`
(42 `'*'` for a set bit, 48 `'0'` for a clear one).

**Two independent gates.** A per-variant *layer* mask at `+44/+46/+48/+50`, and
a per-channel layer mask at `+52`/`+54`. The suffix bits index the first one.
They carry no channel meaning at all.

### What the disc holds, and why the wrong reading fitted

All 97 instruments on the reference disc are identical in both:

```
  variant masks (v0,v1,v2,v3) = (7, 1, 2, 3)   97 of 97
  channel masks (ch1, ch0)    = (255, 0)       97 of 97
```

So `v2` = layer {1} alone, and only layer 0 is populated — hence empty. And the
channel picture is the **reverse** of what was claimed: everything sits on
channel 1, channel 0 is empty on every instrument. The retracted reading had the
content on channel 0 with `*0` reaching for an absent channel 1.

"Mono lacks channel 1" fitted three-populated-one-empty exactly as well as "only
layer 0 exists", and nothing on that disc could separate them, because **the
mask is constant across all 97 instruments**. §158's lesson arriving a second
time in the same session and on the same disc: a field that never varies cannot
tell you what it means, and here the field was the explanation itself.

Worth naming the specific failure: the explanation was *generated* from the
observation it then explained, and no independent measurement was taken before
it was published to a peer as settled and used to commission work from them.
mpc2emu's stereo census was requested on the strength of it.

### The census, delivered anyway

```
  disc   instruments   distinct variant-mask tuples   both channels populated
  ref         97                    1                        0
  A          547                 many                       74
  B           39                 many                       14
  C          222                 many                       25
  D           45                 several                     0
  ------------------------------------------------------------------------
                                                      113 of 850
```

Dual-channel instruments do exist — 113 across the corpus. The answer stands;
it is simply no longer the answer to the `*0` question. Common variant tuples on
disc A include `(3, 12, 48, 192)`, a clean four-way split of eight layers, and
`(1, 24, 6, 96)`.

### One import now tests three things

Disc A, **bank #40 of 64** (directory block 4213), 25 instruments:

```
  pan:      14 non-zero; predicted E4 pans -63, -42, -20, +20, +63
  layers:   variant masks vary per instrument, so each instrument predicts a
            different pattern of populated/empty variants
  channels: at least one instrument carries (ch1, ch0) = (247, 8)
```

The reference disc could not test the mask model at all — every instrument there
predicts the same thing. This bank predicts 25 different things.

## §160 — Pre-registration: what the bank at block 4213 must produce (2026-09-21, written before the import)

**This section is committed before the disc is imported.** It exists so the
result cannot be read back onto the prediction afterwards, which is the failure
mode of §157 (`*0` explained from the observation it then explained) and §158
(a corpus property recorded as a format property). The laws are fixed here; the
next section records what the machine did.

Disc A, directory block 4213, 25 instrument entries, of which **19** pass the
structural check at +880 and are predicted. The other 6 are not predicted, and
a result for them is not evidence either way.

### The laws being tested

```
  pan_e4 = (int8) ws[221] * 63 / 127          signed, truncating   (0x78f10)
  layer L enters variant v  iff (inst[44+2v] >> L) & 1
                            and (chanmask >> L) & 1                (0x78d64)
  chanmask = chan ? inst[52] : inst[54]
  suffix   = bit1 of v, bit0 of v  ('*' set, '0' clear)            (0x7be64)
```

### The predictions

```
   blk   variant masks        ch1/ch0    root   pan src -> E4
 112833  (3, 144, 6, 10)      (255, 0)     67    -127     -63
 210225  (7, 5, 2, 3)         (7,   0)     60     +42     +20
 177370  (3, 12, 48, 192)     (255, 0)     63    -127     -63
 213136  (7, 2, 1, 3)         (255, 0)     60     -42     -20
 213173  (3, 2, 1, 3)         (255, 0)     72     -42     -20
 124287  (5, 96, 24, 108)     (255, 0)     72     -85     -42
 208892  (3, 1, 4, 7)         (255, 0)     60     +42     +20
 211817  (3, 2, 1, 12)        (255, 0)     60     -85     -42
 102543  (192, 12, 48, 3)     (247, 8)     72    -127     -63
 208596  (3, 1, 7, 4)         (255, 0)     48     -42     -20
  64799  (3, 12, 48, 192)     (255, 0)     67    -127     -63
 209758  (7, 1, 2, 3)         (255, 0)     72     -85     -42
   6121  (1, 2, 4, 8)         (255, 0)     69       0       0
   7385  (3, 12, 48, 192)     (255, 0)     49       0       0
  62418  (3, 12, 48, 192)     (255, 0)      2       0       0
 124636  (3, 60, 192, 42)     (255, 0)      6       0       0
 238943  (3, 12, 48, 192)     (255, 0)      2       0       0
 124509  (3, 224, 28, 23)     (255, 0)     72    +127     +63
 217044  (7, 19, 11, 96)      (255, 0)     56    -127     -63
```

### What counts as a pass, decided now

1. **Pan.** 14 of 19 non-zero, and the distinct E4 pan values must be exactly
   **{−63, −42, −20, 0, +20, +63}**. Five distinct non-zero values is the point:
   a wrong offset or an unsigned read cannot land all five. If every zone reads
   centre, the retracted "importer defect" claim of §158 was right after all.
2. **Layers.** Every one of the 19 predicts **all four variants populated** —
   no empty `*0`. This is the sharpest available discriminator against §157's
   retracted channel reading, which predicted an empty `*0` per instrument on
   the ground that these are mono. If `*0` comes back empty here, the layer-mask
   model is wrong too and both readings fail together.
3. **Root key.** The 19 roots above, including the two reading 2 and the one
   reading 6 — implausible as musical roots, predicted anyway because the law
   says so. Quietly dropping them afterwards would be fitting the apparatus to
   the answer.

### What is NOT being tested

Wavesample 0 only. Later wavesamples interleave with their audio at a stride
that is still unknown, so nothing here predicts voices beyond the first of each
layer, and a mismatch in a later voice is out of scope rather than a refutation.

## §161 — The result: pan confirmed 25/25, the layer model confirmed 100/100, and the fixed base refuted (2026-09-21, live)

**Status: the pan law and the layer-mask model are both confirmed on
out-of-sample data. §158's and §159's retractions are now positively vindicated
rather than merely argued. One assumption failed — the fixed base — and it was
the one carrying the pre-registered predictions.**

Jan loaded the bank at directory block 4213 (Load, not Merge, so the previous
bank was cleared — chosen because a part-full sample RAM would have produced
missing variants, which is exactly what test 2 measures). EOS built 100 presets,
25 instruments × 4 variants. All 100 were dumped over SysEx.

### The pre-registered scores (§160), read exactly as written

```
  TEST 2  variants populated   76/76    PASS
  TEST 1  pan                  17/19
  TEST 3  root key             14/19
  TEST 4  volume (post-hoc)    15/19
```

Every failure in tests 1, 3 and 4 is an instrument whose wavesample struct is
**not at offset 880**. No failure is a law failing.

§160 said the three implausible predicted roots (2, 2, 6) were predicted anyway
and would not be quietly dropped. All three failed. They were the tell: a root
key of 2 is not a root key, and the structural filter — `1 <= root <= 127` —
was too lenient to catch it. That is the pre-registered failure and it is
recorded as a failure.

### Re-scored from the located base: the laws hold

Locating each struct by the relation (root, klow, khigh) — three simultaneous
byte constraints — and then reading the fields that were **not** in the search
key:

```
  pan       25/25     OUT OF SAMPLE
  volume    24/25
```

**Pan is confirmed on every instrument in the bank**, across all six distinct
values:

```
  source  -127   -85   -42    0   +42   +127
  E4 pan   -63   -42   -20    0   +20    +63
```

Pan was never part of the search key, so this is prediction, not fitting.
§158's refutation of "every Ensoniq import lands centre" is now positive: EOS
reads pan, reads it from `+221`, and reads it signed. The "importer defect"
claim is dead in both directions — it was wrong, and the correct law is known.

### The layer-mask model: 100/100, and the retracted model refuted 25/25

TEST 5, derived from the §160 gate with no new law: variants admitting the same
lowest layer must report an identical zone 0.

```
  variants agreeing with their layer class      100
  variants in conflict                            0
  instruments whose masks PARTITION the four      25/25
```

Every instrument's four variants split into more than one layer class, and every
variant agrees with its class and differs from the others exactly as the masks
on the disc dictate. **The retracted channel reading (§157) predicts all four
variants draw identical content. It is refuted on all 25.**

The clearest case: an instrument with masks `(3, 2, 1, 3)` — `00` and `**`
take layers {0,1}, `*0` takes layer {0}, `0*` takes layer {1} alone. Three
variants report pan −20 and the fourth reports 0, because layer 1's wavesample
is centred and layer 0's is not. Nothing about channels predicts that.

### The correction: base 880 is not fixed

`ENSONIQ_ROLAND_IMPORT.md` recorded that the wavesample base is a fixed 880,
on the strength of one instrument that resolved correctly without the
`UNNAMED WS` landmark. That holds on the reference disc — 97 of 97 — and does
**not** generalise. Located bases in this bank:

```
  656, 880, 1104, 1328, 2544, 93200, 97120, 105552, 115280, 129088
  880 holds for 13 of 25
```

The four small values are 224 apart, which is the layer-array stride, but 2544
does not fit that progression and the rule is not established. **The base is an
open problem**, and it is the same open problem as the later-wavesample stride
(§158) seen from the other end.

"Fixed offset, survives a file missing the landmark" was a sound argument
against name-location. It was not an argument for universality, and it got
recorded as one.

### Two smaller results

**The volume table is now exercised at 11 indices** instead of one. §157 could
confirm `TABLE_0x796a4` only at index 127, every zone on the reference disc
reading 0. This bank exercises 0, 2, 74, 80, 89, 100, 101, 105, 109, 116, 127
and matches at all but one. The exception: a source index of 80 maps to −5 in
the table while the E4 reports −3. Index 74 maps to the same −5 and matched on
a different instrument, so the table entry is not obviously wrong; none of the
six candidate structs for that instrument yields −3 either. **Unexplained, and
left unexplained.**

**A velocity-range guess failed and was never a law.** Offsets `+278`/`+280`
were tried as velocity low/high and scored 0/25. They are not velocity. Recorded
so the next session does not retry them, and flagged as an invented offset
rather than a documented one that failed.

### What this bank could test that the reference disc could not

```
  field          reference disc        this bank
  pan            1 value  (0)          6 values
  volume         1 index  (127)        11 indices
  variant masks  1 tuple x97           25 distinct partitions
  velocity high  1 value  (127)        at least 2
```

That is the whole content of §158's lesson, as a table.

### §161 addendum — the index-80 anomaly was a missing term, and it closes the boost row (2026-09-21)

§161 left one volume discrepancy unexplained: a source index of 80 maps to −5 in
`TABLE_0x796a4` while the E4 reported −3. mpc2emu proposed checking whether the
E4 value was a *sum* of zone, voice and preset volumes rather than one field —
a reader taking one where the machine summed two gives exactly that shape of 2 dB
error on one instrument and not others.

It is not a sum. But the instinct — *the discrepancy is a second term, not a bad
table entry* — was right, and it prompted reading the whole of `0x78edc` instead
of just the table it indexes. The function is:

```
  78edc:  moveb %a0@(208),%d1        ; the volume byte
  78ee6:  tstb  %a0@(225)            ; the BOOST flag
  78eea:  beqs  0x78f00              ; clear -> straight to the lookup
  78ef0:  addl  #12,%d0              ; set   -> +12 on the INDEX
  78ef6:  moveb %d0,%d1              ; truncated to a byte
  78efa:  cmpl  ... #127             ; then clamped
  78f00:  TABLE_0x796a4[d1], sign-extended
```

So the law, as my **scoring script** applied it, was incomplete:

```
  volume = TABLE_0x796a4[ ws[225] ? min((ws[208] + 12) & 0xff, 127) : ws[208] ]
```

**`+225` is not a separate parameter. It is a +12 shift on the volume index.**

> **CORRECTED 2026-09-21, same day, by a stale-claim sweep.** The sentence that
> stood here said "the documented law was incomplete" and that every earlier
> description of `+225` as a flag of unknown effect could now be replaced.
> **Both are false.** `docs/ENSONIQ_ROLAND_IMPORT.md` has carried
> `if ws[225] != 0: v = min((v + 12) & 0xff, 127)` since that file's **first
> commit** (`67fd16f`). The law was documented correctly all along.
>
> What was incomplete was **my scoring script**, which applied
> `TABLE[min(ws[208],127)]` with no boost branch — which is why exactly one
> instrument mismatched and why reading `0x78edc` in full "found" a term the
> project already had written down.
>
> The real finding is smaller and still worth having: **the boost term was
> documented but never exercised, and is now measured** — at one instrument,
> n=1. A documented law and a measured one are different things, and claiming
> to have completed a law that was already complete is the overstatement this
> document spent the day cataloguing.

Re-scored across the bank:

```
  volume, TABLE[ws208] only        24/25
  volume, with the +12 boost term  25/25
```

and the one instrument that differed is the one instrument with `ws[225] != 0`:
index 80 + 12 = 92, `TABLE[92]` = −3, E4 reports −3.

**The boost row of §158 moves from unverifiable to measured — at exactly one
point.** One instrument in 25 has the flag set. That is better than the zero
observations it had this morning and is not a distribution: it is the same
standing as `TABLE_0x796a4[127]` after §157. A second disc's boosted instruments
would settle whether the term is always +12 or whether 12 is itself a field.

Worth noting what made this findable: the discrepancy was **left in the commit
as unexplained** rather than rounded off or attributed to a bad table entry. An
anomaly recorded with its exact numbers is a question a colleague can answer;
the same anomaly smoothed away is gone.

## §162 — The Ensoniq sample audio: in-file, 16-bit big-endian PCM (2026-09-21)

**Status: the encoding is identified. Where each wavesample's audio begins and
ends is not, and that is now the second Ensoniq blocker behind the locator.**

mpc2emu asked a question nobody had asked: the survey of 853 wavesamples read
**parameter records only** — had anything ever touched the sample audio? It had
not. A converter needs PCM, and an untouched audio path is a blocker sitting
behind the locator rather than beside it.

### What was measured

The audio is inside the instrument file, not in a separate object. Instrument
file sizes in one bank run from 8 blocks (4096 bytes, parameters only) to 976
blocks (499712 bytes), and the large files are 96–98% dense where a parameter
struct is about 35% dense.

Endianness by successive-difference roughness — real PCM is smooth, so
`mean(|x[i+1]-x[i]|) / mean(|x[i]|)` is small for the correct interpretation and
near or above 1 for the wrong one. On the 499712-byte instrument at three
offsets:

```
  offset     BE       LE
   60000   0.077    1.344
  249856   0.095    1.304
  479712   0.186    1.325
```

**16-bit big-endian.** A 17× separation is not a judgement call.

Strength: corpus-only, one instrument, three sample points, no hardware
cross-check. Enough to fix the encoding, not enough to claim there is no second
format elsewhere on a disc.

### What is still missing, and why the obvious probe failed

Where each wavesample's audio starts and ends. Two struct positions are known
exactly on the reference disc — 880 and 71072, a gap of 70192 bytes — and no
plain big-endian long anywhere in the struct equals that gap, the absolute
offset, the gap halved, or the file size.

That probe could not have worked. The struct's own longs read `0x23004600`,
`0x08800000`, `0x20000000` — **byte-interleaved**, which is the packed-group
encoding the GLM trace attributes to `0x78cc4`, decoding 4-byte groups at struct
`+240`, `+248`, `+256`, `+264` into a 23-bit and a 4-bit value:

```
  hi = (b0 << 15) | (b2 << 7) | (b4 >> 1)
  lo = ((b4 & 1) << 3) | ((b6 >> 5) & 7)
```

Those four groups are the best candidates for the audio pointer, length and loop
points. **That decoder is not implemented here and not validated**, and
implementing it against the two structs whose positions are known exactly is the
specific next piece of offline work — no hardware, no disc write.

### Why this reframes the Ensoniq estimate

The law inventory is in good shape: pan 25/25, volume 25/25, layer masks
100/100, root and key range confirmed. **None of it is reachable by a converter
that cannot find the struct, and none of it produces audio.** Two offline traces
stand between the current state and a path that could be attempted:

```
  0x7ad44 / 0x7ac24 / 0x7a9c4   the three builders under the file walker  -> the locator
  0x78cc4                        the packed-group decoder                 -> the audio
```

Both are firmware reading. Neither needs the rig.

## §163 — The chain rule: a clean hypothesis, tested, refuted 1/18 (2026-09-21)

**Status: REFUTED. `+248` is probably the sample count; the layout rule built on
it is not. The locator and the audio layout remain one unsolved problem.**

§162 left two Ensoniq blockers, the locator and the audio layout, and the
obvious thought is that they are the same blocker: if a wavesample's struct is
followed by its audio, then the next struct's position falls out of the audio
length, and one decoded field solves both.

### The hypothesis, and the single observation that generated it

Decoding the `0x78cc4` packed groups of the one instrument where two struct
positions are known exactly (880 and 71072):

```
  +240  00 00 00 00 00 00 00 00  ->  0
  +248  01 00 11 00 02 00 00 00  ->  34945
  +256  00 00 ab 00 aa 00 00 00  ->  21973
  +264  01 00 11 00 02 00 00 00  ->  34945
```

`880 + 288 + 2×34945 = 71058`, and `align16(71058) = 71072`. Exact.

```
  next_struct = align16(X + 288 + 2 * decode(X+248))
```

### The test, with both ends hardware-derived

Each of an instrument's four variants may draw a different layer and hence a
different wavesample. Locating each variant's struct by the E4XT's reported
(root, klow, khigh) gives several struct positions per instrument, none of them
derived from the rule. Then ask whether the rule connects consecutive ones.

```
  consecutive pairs tested   18
  rule connects               1
  rule fails                 17
```

**Refuted.** The single fit that generated it was one observation, and a rule
generated from one observation fits that observation perfectly. This is the same
shape as §157's `*0` explanation and §158's "always zero" — the third time
today — and the only difference is that this one was tested before it was told
to anybody.

### What survives, because the failures are not random

The predictions land close:

```
   40608 vs  40832   (+224)        278240 vs 278464  (+224)
  105104 vs 105552   (+448 = 2x224)  97104 vs  97120  (+16)
  112496 vs 113520                  70224 vs  72208
```

Several misses are exactly 224 or 448 — the same 224 that appeared among the
small bases in §161 and that matches the layer-array stride. So **`+248` is
plausibly the sample count** and the per-wavesample overhead is not a constant
288: there is additional structure between the audio and the next struct, and
sometimes a multiple of 224 of it.

That is a better-specified open problem than §162 left, and it is still open.

### The correction to §162's framing

§162 listed the locator and the audio layout as blockers #1 and #2. They are
**one problem** — the file's layout — and ranking them against each other is the
wrong question. A converter needs to know where every wavesample's struct AND
audio begin and end, and the same unknown structure governs both.

The remaining route is unchanged and offline: the three builders under the file
walker (`0x7ad44`, `0x7ac24`, `0x7a9c4`), which is where the loader computes
these positions rather than guessing at them.

## §164 — The layout is not an arithmetic chain: a family of hypotheses ruled out, and two code increments (2026-09-21)

**Status: the layout problem stays open, but a whole family of guesses is now
closed, and the walker's own arithmetic is partly read.**

### Two things the trace established

**`0x79024` is the packed-group decoder wrapper.** Called from the file walker
at `0x7aed2` with the block record and a 32-byte local (`%fp@(-32)`), it invokes
`0x78cc4` four times on the record's `+240`/`+248`/`+256`/`+264` groups. So the
decoded wavesample parameters live in a **32-byte structure**, and every
consumer downstream takes that local rather than the raw groups.

**The walker's running position uses +48 and 2-alignment, not 288 and 16.**
At `0x7af1c`:

```
  d7 = %fp@(-8) + %fp@(12) + 48      ; extent + base + 48
  if (d7 & 1) d7 += 1                ; round up to EVEN
```

`%fp@(-8)` is an output of `0x7ab78`, `%fp@(12)` an argument. **This is why
§163's chain rule failed**: it assumed a 288-byte struct and 16-byte alignment,
and the firmware uses neither. What it does *not* establish is that `%fp@(12)`
is the previous struct's position — that is assumed, not read, and the next
section is consistent with it being something else.

### The family that is now ruled out

Searching every rule of the form

```
  next = align( X + overhead + mult * decode(X + field) )
  field    in {240, 248, 256, 264}
  mult     in {1, 2, 4}
  overhead in 0..1200 even
  align    in {1, 2, 4, 8, 16, 32, 256, 512}
```

against the 18 struct pairs whose *both* ends are hardware-derived — located by
matching the root and key range the E4XT reported for each variant:

```
  best fit over the whole family: 3 of 18
```

**No simple arithmetic chain describes this layout.** Not with any of the four
packed fields, any plausible sample-size multiplier, any small overhead, or any
alignment. The next wavesample's position is not a function of the current one
plus a decoded length.

That is worth more than it sounds. §163 refuted one rule; this refutes the
shape. Anyone who reaches for "struct, then audio, then the next struct" now has
a measured reason not to.

It also means the real structure is one of: variable-size per-record headers,
records not contiguous with their audio, a separate record table the walker
indexes, or block-granular placement the file doesn't express arithmetically.
The walker reading `%a5@(10)` (length) and `%a5@(32)` (pointer) **from a block
record** rather than from the wavesample struct points at the last of these:
the positions may simply be listed, not computed.

### A note on the held-out set

The fit used 18 pairs from one disc and the held-out set came back **empty** —
on the reference disc every instrument yields only one locatable struct, because
its instruments are single-layer and all four variants draw the same wavesample.
So this is an unvalidated fit that happened to fit nothing, which is the only
reason it can be reported as a clean negative. Had something scored 17/18, it
would have needed a second disc before it could be believed, and that disc does
not currently exist in a usable form.

### Where the trace stops

`0x7ab78` computes the extent at `%fp@(-8)`, and it calls `0x49ad4` three times
with shifted operands (`d0 << 28`) — fixed-point arithmetic, most likely a rate
or ratio conversion rather than a byte count. Reading it properly is the next
step and it is more than a single pass. `0x7ad44`, `0x7ac24` and `0x7a9c4`
remain the three builders to trace, unchanged from §162.

## §165 — GLM's chain rule tested: supported where testable, and §164's evidence base was confounded (2026-09-21)

**Status: the structure is supported on the 6 pairs where it can be tested. And
§164's "best fit 3 of 18" was measured on a set in which 12 of the 18 pairs
could not have fitted ANY adjacency rule. That is my error, not GLM's.**

A third session traced the loader at instruction level and sent, via mpc2emu, a
corrected rule with a pre-registered prediction:

```
  next_base = align2( base + 48 + extent )
  extent    = f( struct[+12] - struct[+8], rate )      <- a DIFFERENCE
```

and the explanation that §164's family search missed because **the extent is
not a multiple of one field**. Differences and rate compensation were both
outside the searched family.

### What the 18 pairs say

Required extent per pair is `next − base − 48`. Against `2 × (g1 − g0)`, where
`g0`/`g1` are the groups at `+240`/`+248` decoded by `0x78cc4`:

```
  6 of 18 pairs land at ratio 1.0032 … 1.0360
  the other 12 run 1.34, 1.61, 1.63, 2.02, 2.17, 2.75, 3.63, 3.96, 5.15
  and two are near zero
```

**Six is not a poor result — it is the number of pairs the test can reach.** The
ratios above 1.05 are what a gap spanning *more than one entry* looks like.

### The confound, which is mine

My pairs are **consecutive LOCATED structs, not consecutive structs.** Each was
found by matching the root and key range the E4XT reported for one variant. An
instrument with five wavesamples of which two were located yields a "pair" whose
gap spans three extents. **No adjacency rule can fit such a pair, and twelve of
the eighteen are of that kind.**

So §164's "no simple arithmetic chain describes this layout, best fit 3 of 18"
is **overstated**. The family conclusion may still stand — a difference-based
extent was outside the family whatever the pairs were — but the *evidence* was
two-thirds invalid, and the score was reported as though all 18 were fair tests.
I built a validation set out of whatever the hardware happened to identify and
never asked whether its members satisfied the property being tested.

That is a new shape for the day's list: **not a stale claim, but a metric
computed over a population that does not meet the metric's precondition.** A
denominator nobody checked.

### The pre-registered prediction, supported in mechanism

The prediction was that §163's `+224`/`+448`/`+16` residual misses would become
hits. They are not yet numerical hits — the rate term is unidentified — but:

```
  §163 small-residual pairs:  +224, +224, +448, +16
  all four are among the six clean pairs here, at ratios
  1.0121, 1.0032, 1.0091, 1.0054
```

**The residual is now attributable rather than unexplained.** The old rule used
`g1` alone with no `g0` subtraction and no rate term; the leftover was the rate
term. That is the prediction's mechanism confirmed even though its arithmetic
is still open.

### A lead on the excess, offered as a lead only

`req − 2×(g1 − g0)` for the six clean pairs: **502, 470, 478, 512**, then 948
and 2482. Four cluster near 512. GLM's trace notes a **two-byte marker at each
audio block's start** and an `extent, +2`. A per-block overhead accumulating
over a fixed block size would produce exactly a near-constant excess for
similar-length samples. Not tested, and the two outliers are unexplained.

### Field mapping, as far as the data takes it

`g0` is 0 on 16 of 18 structs, and `g1 − g0` behaves as the length. That is
consistent with `+8` = start and `+12` = end, with the difference in **samples**
and ×2 for 16-bit bytes. The rate at `+16` is not identified: `g2` varies from
2847 to 63833 across pairs whose implied rate excess is near-constant, so `g2`
is not the rate in any direct reading.

## §166 — The field mapping is NOT pinned: the code and the data disagree (2026-09-21)

**Status: do not build on §165's field-mapping inference. Reading `0x79024`'s
tail was supposed to close the mapping and instead produced a contradiction
that is not yet resolved.**

### The code, read directly, twice

`0x790ca` — the tail of `0x79024`, storing the four decoded groups:

```
  decode(src+240) -> struct[+0]    (clamped: if > struct[+8], take struct[+8])
  decode(src+248) -> struct[+4]    (clamped: if < struct[+12], take struct[+12])
  decode(src+256) -> struct[+8]
  decode(src+264) -> struct[+12]
  LO of the +264 decode -> struct[+16]        a 4-bit value
  map(src[+238])        -> struct[+20]        2->1, 3->2, 1->3, 4->4, else 0
```

`0x7ab8c` — the extent computation, confirming the relayed reading exactly:

```
  7ab8c:  movel %a5@(12),%d7
  7ab90:  subl  %a5@(8),%d7        ; length = struct[+12] - struct[+8]
```

Both are unambiguous. Composing them, **length must be
`decode(src+264) − decode(src+256)`.**

### The data says otherwise

Across the 18 pairs, required extent against `2 × length`:

```
  length = decode(264) - decode(256)   what the code composes    0 of 18
  length = decode(248) - decode(240)   what §165 tested          6 of 18
```

and the six are not a loose 5% window — five of them sit at **1.0032, 1.0044,
1.0054, 1.0091, 1.0121**, with one at 1.0360. A tight cluster just above 1 is
what a small rate compensation looks like. A coincidence would scatter.

**These cannot both be right, and I am not going to pick the one that suits the
story.** Recorded as a disagreement.

### The candidates, none tested

1. **The object is not the struct I am reading.** `0x79024` is called from
   `0x7aed2` as `0x79024(a2, &fp@(-32))` where `a2` comes from
   `0x78c84(record type)` — an object selected by type, not necessarily the
   disc wavesample block at my located base. If `a2` is a different structure,
   then `+240…+264` are offsets into *it*, and my reading them at
   `located_base + 240` is the error.
2. **My `dec_hi` is wrong.** The signed shift was flagged as load-bearing by the
   source that supplied it; I implemented `(b0<<15) + (b2<<7) + ((int8)b4 >> 1)`
   but have never validated the decoder against a known value.
3. **The 6 of 18 is coincidence.** Least likely given the cluster, but it is the
   explanation that costs nothing to hold and it has not been excluded.

### What this retracts

§165 said the data was "consistent with `+8` = start and `+12` = end, with the
difference in samples". **That inference is withdrawn.** It was built on
`g1 − g0` fitting, and the code says `g1`/`g0` are `struct[+0]`/`struct[+4]`,
which the extent computation does not read. The *structure* — that the extent is
a rate-compensated difference of two decoded fields — survives, because the code
shows it directly. Which two fields does not.

**Nothing here changes the confirmed half:** positions are listed and read back
(`0x7ac24`: length stored at `entry[+60]`, position read from `entry[+28]`),
and the `+48` / align-2 chaining at `0x7af1c`. Those are read from instructions
and do not depend on the field mapping.

### The cheapest next step

Validate the decoder before anything else. `0x78cc4` on a group whose true value
is known independently — the sample length of an instrument whose audio extent
can be measured from the file — separates candidate 2 from candidates 1 and 3 in
one test, and every further inference rests on it.

### §166 addendum — the contradiction dissolves, and it takes §163–§165's arithmetic with it

Both candidates from §166 are eliminated, and the third explanation is worse
than either.

**The decoder is validated.** `0x790be` *enforces* `g0 ≤ g2` and `g1 ≥ g3`
(clamping `g0 = min(g0,g2)`, `g1 = max(g1,g3)`). Real data satisfies both
**17 of 18** before any clamp. A wrong decoder does not satisfy two independent
inequalities across values spanning 0…123440 by accident. `0x78cc4` as
implemented is right, and the structure it reveals is textbook:

```
  g0 .. g1   the OUTER range   (sample start, sample end)
  g2 .. g3   the INNER range   (loop start, loop end), with g3 ≈ g1
```

**The object is the right one.** `0x7ab84` is `moveal %a1,%a5`, and the caller
passes `a1 = %fp@(-32)` — the struct `0x79024` just filled. So
`length = struct[+12] − struct[+8]` really is `g3 − g2`, the **loop** length.

### The actual error is mine, and it is four sections deep

`0x7ae84`'s prologue: `%fp@(12) → %d7`, an **argument**. And at `0x7af1c`:

```
  d7 = %fp@(-8) + %fp@(12) + 48
```

**`%fp@(12)` is a position threaded into the walker by its caller.** It is not
the wavesample struct's offset within the instrument file. §164 flagged exactly
this — *"what this does NOT establish is that `%fp@(12)` is the previous
struct's position — that is assumed, not read"* — and then §163, §164 and §165
all computed `req = next − base − 48` as though it were.

**So `req` was never the extent**, and neither number tests the extent law:

```
  §163  chain rule            1/18     not a test
  §164  family search         3/18     not a test
  §165  g1 − g0 fits          6/18     not a test
  §166  g3 − g2 fits          0/18     not a test
```

The "contradiction" between 6/18 and 0/18 dissolves because neither side was
measuring what it claimed. **§165's supported-mechanism result is withdrawn in
full** — the tight 1.0032…1.0121 cluster is unexplained rather than meaningful,
and I should have treated an unexplained tight cluster as a reason to re-check
the apparatus, which is the rule I applied correctly to the pan survey this
morning and not here.

### What survives

Only what was read from instructions and never depended on the arithmetic:

- positions are **listed and read back** — `0x7ac24` stores length at
  `entry[+60]` and reads position from `entry[+28]`
- the decoded 32-byte struct's layout, now with semantics:
  `+0/+4` sample start/end, `+8/+12` loop start/end, `+16` a 4-bit rate,
  `+20` a mapped flag from source `+238`
- `length = struct[+12] − struct[+8]` is the **loop** length
- `0x78cc4` as implemented, validated 17/18 on the enforced invariants

### The shape, which is the day's fifth distinct one

**An assumption flagged as unread, then built on four times.** §164 wrote the
caveat down correctly and in the right place. Writing a caveat down does not
retire it, and it does not stop the next section from treating the caveated
thing as a given — the caveat stayed in §164 while the quantity travelled.

The operational form: **a flagged assumption should block the computation that
depends on it, not annotate it.** Had `req` been unavailable until `%fp@(12)`
was read, none of the four numbers would exist, and none of them was worth
having.
