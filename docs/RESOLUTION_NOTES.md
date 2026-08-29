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
