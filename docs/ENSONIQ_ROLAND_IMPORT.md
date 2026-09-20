<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# EOS's Ensoniq and Roland importers, as read out of the firmware

Companion to [`AKAI_IMPORT.md`](AKAI_IMPORT.md), same method and same image
(EOS 4.70 decompressed, load base `0x20000`).

**Status: the Ensoniq path is traced end to end for the preset, voice and zone
structure. The Roland path is located and its functions enumerated, and its
parameter mapping is NOT yet traced.** Sections are marked accordingly. Nothing
here has been checked against a corpus.

## The three importers share nothing

Established before any tracing, because it decides how much work this is. Every
AKAI conversion primitive was checked for call sites across the whole image:

```
  generic rescaler 0x2f6b4        74 sites   ALL in the AKAI module
  volume law       0x2f6f8         2 sites   ALL AKAI
  envelope helpers 0x2f7c4/ec/14/30  3 each  ALL AKAI
  pan wrapper      0x2f784         6 sites   ALL AKAI
  zone compare     0x2fe78         2 sites   ALL AKAI
  AKAI name conv   0x3060c         8 sites   6 AKAI + 2 adjacent
```

and the AKAI orchestrator, keygroup handler, zone converter and voice/envelope
builder have **exactly one caller each**, all inside AKAI.

**So each importer is a complete separate implementation.** Ensoniq has its own
name converter, its own volume table and its own zone builder, none of them
shared. A reader built against one of them transfers nothing but method.

## Ensoniq (EPS / ASR)

### Where it lives

| address | what |
|---|---|
| `0x772e0` | `"Scanning Ensoniq device"` |
| `0x7a811`–`0x7a85f` | `"Ensoniq Bank"`, `"UNNAMED WS"`, `"Ensoniq sample"`, `"Ensoniq Instrument"` |
| `0x7a534` | entry into the conversion chain |
| **`0x7bdf0`** | **preset builder** — header, then two channel builders |
| `0x7bd60` | preset-header builder |
| `0x7b094` | name converter |
| `0x7bcdc` | channel builder — loops 8 layers |
| `0x7bbe4` | layer walker — walks wavesamples within a layer |
| **`0x7b0e0`** | **zone builder** |
| `0x78edc` | volume law |
| `0x78f10` | pan law |
| `0x796a4` | volume lookup table, 128 entries |

Call chain: `0x7a534 → 0x7bf0c → 0x7bf64 → 0x7bdf0 → {0x7bd60, 0x7bcdc×2}`,
then `0x7bcdc → 0x7bbe4 → {0x7bb90, 0x7b0e0}`.

### The preset builder writes TWO voices

```
  7be06:  jsr 0x78c60         ; fetch the Ensoniq instrument
  7be12:  bsrw 0x7bd60        ; header
  7be24:  bsrw 0x7bcdc        ; channel builder, arg 1
  7be34:  bsrw 0x7bcdc        ; channel builder, arg 0
  7be64:  name[14] / name[15] = '*' (0x2a) or '0' (0x30), per bits 0 and 1
                                of a flags byte
```

**Two calls, one per channel of a stereo pair.** And the importer **overwrites
the last two characters of the preset name** with `*` or `0` to record which
channels are present — so an Ensoniq import's name is not simply its source
name, and a byte-comparison against the source will always differ in those two
positions.

Each channel builder loops **eight layers** (`cmpl #8`), which is the EPS/ASR
layer model, calling the layer walker per layer.

### The preset header

`a5 = header + 2`, pinned the same way as AKAI's: the name field is `memset` to
`0x20` for 16 bytes and the `0x52` constant lands at `a5@(16)` = `header[18:20]`.

| store | header byte | meaning |
|---|---|---|
| `memset(a5, 0x20, 16)` + 17-byte copy via `0x7b094` | `[2:18]` | name, space-padded |
| `movew #82,a5@(16)` | `[18:20]` | the `00 52` constant |
| `clrw a5@(18)` / `(20)` / `(22)` | `[20:26]` | zeroed |
| `moveb a4@(66),a5@(24)` | `[26]` | **transpose**, copied straight from source `+66` |
| `clrb a5@(25)` | `[27]` | **volume — CLEARED TO ZERO** |
| `memset` at `a5+54` (4), `a5+58` (16), `a5+74` (8) | — | same three as AKAI |

**Two differences from the AKAI path worth carrying:**

- **Preset volume is set to 0**, not computed. AKAI runs
  `clamp((v-99)*8/10, -96, +10)`; Ensoniq writes zero. Nothing from the source
  reaches the preset volume field.
- **Transpose is copied unclamped.** AKAI clamps to ±24; this is a plain byte
  move from source offset `+66`. If the Ensoniq value can exceed ±24 the result
  is out of the documented range for that field.

### The name converter (`0x7b094`)

```
  lea %a0@(10),%a0            ; source name starts at +10
  c = *src
  if (unsigned)(c - 32) <= 95 : dest[i] = c      ; printable ASCII passes through
  else                        : dest[i] = ' '
```

**Ensoniq names are plain ASCII** — no character table, unlike AKAI's 6-bit
encoding. Anything outside 32..127 becomes a space.

### The zone builder (`0x7b0e0`) — the parameter mapping

```
  jsr 0x50d20(dest, 0)        ; allocate a zone; NULL -> give up
  d1 = clamp(0x78edc(ws), -96, +10)     ; volume
  d7 = clamp(0x78f10(ws), -64, +63)     ; pan
```

| zone byte | source | meaning |
|---:|---|---|
| `0` | wavesample `+274` | key low |
| `1`, `2` | — | **zeroed** (key low fade) |
| `3` | wavesample `+276` | key high |
| `4` | layer `+40` | velocity low |
| `5`, `6` | — | **zeroed** (velocity fade) |
| `7` | layer `+42` | velocity high |
| `8:10` | `d5` | sample index, word |
| `10:12` | — | **zeroed** (fine tune) |
| `12` | wavesample `+170` | root key |
| `13` | `0x78edc` → table | volume, clamped −96…+10 |
| `14` | `0x78f10` | pan, clamped −64…+63 |

**Fine tune is discarded** — written as zero regardless of source. So is every
key and velocity crossfade.

### Volume and pan laws

`0x78edc`:

```
  v = wavesample[208]
  if wavesample[225] != 0:          ; a boost flag
      v = min((v + 12) & 0xff, 127)
  return TABLE_0x796a4[v]           ; signed
```

128-entry table at `0x796a4`, monotonic non-decreasing, range **−72 … 0**:

```
  -72 -66 -60 -54 -48 -48 -42 -42 -42 -36 -36 -36 -36 -36 -30 -30
  -30 -30 -30 -30 -24 -24 -24 -24 -18 -18 -18 -12 -12 -11 -11 -11
  -11 -11 -11 -10 -10 -10 -10 -10 -10 -10  -9  -9  -9  -9  -9  -9
   -9  -9  -9  -9  -8  -8  -8  -8  -8  -8  -8  -7  -7  -7  -7  -7
   -7  -7  -6  -6  -6  -6  -6  -6  -6  -6  -5  -5  -5  -5  -5  -5
   -5  -4  -4  -4  -4  -4  -4  -4  -4  -4  -3  -3  -3  -3  -3  -3
   -3  -3  -3  -3  -3  -3  -3  -3  -3  -3  -2  -2  -2  -2  -2  -2
   -2  -2  -2  -2  -2  -2  -1  -1  -1  -1  -1   0   0   0   0   0
```

Note the table is **heavily quantised at the quiet end** — the first 29 entries
cover −72 to −12 dB in 14 distinct values — and fine at the loud end. Converting
by a formula rather than this table will diverge most for quiet wavesamples.

`0x78f10`: **`pan = (wavesample[221] × 63) / 127`**, signed, truncating. A second
identical routine at `0x78f28` reads offset `+182` instead, presumably the
layer-level pan.

## THE CONVERSION TABLES

Both importers build an E4 preset the same way AKAI's does — `a5 = header + 2`,
the name field space-padded to 16, the `0x52` constant at `header[18:20]`, and
the same three trailing memsets at `+54`/`+58`/`+74`. What differs is everything
below that.

**Read the source column as "offset into the structure EOS holds", not "offset
into the file."** See the address-space section: for Ensoniq this was tested and
they are *not* file offsets. For Roland it is untested and should be assumed the
same.

**The AKAI importer is the exception and it is proven, not assumed** — see
`AKAI_IMPORT.md`. Its cords sit in two blocks of four, each immediately after one
of the two envelope blocks mpc2emu's parser independently locates in the file, in
the same order both times. That adjacency only holds if AKAI keygroup bytes are
read straight from the disc. **So "EOS importers do not use file offsets" is
false as a general rule** — AKAI parses a flat file directly, and only the other
two build an intermediate.

### Preset header — all three importers side by side

| header byte | AKAI | Ensoniq | Roland |
|---|---|---|---|
| `[2:18]` name | 6-bit charset table, 12 chars | ASCII, non-printable → space, src `+10` | **16-byte memcpy**, ASCII |
| `[18:20]` | `0x0052` | `0x0052` | `0x0052` |
| `[20:26]` | zeroed | zeroed | zeroed |
| `[26]` transpose | `clamp(src, −24, +24)` | `src+66`, **unclamped** | **`src[24] × 12`** (octave → semitones) |
| `[27]` volume | `clamp((v−99)×8/10, −96, +10)` | **0** | **0** |
| `+54`/`+58`/`+74` | memset 4/16/8 | same | same |

**Only AKAI sets a preset volume.** Ensoniq and Roland both write zero.

### Zone — Ensoniq (`0x7b0e0`) and Roland (`0x171434`)

| zone byte | field | Ensoniq source | Roland source |
|---:|---|---|---|
| `0` | key low | wavesample `+274` | patch `+12` |
| `1` | key low fade | **0** | patch `+13` |
| `2` | — | **0** | patch `+14` |
| `3` | key high | wavesample `+276` | patch `+15` |
| `4` | velocity low | layer `+40` | partial `+7` |
| `5` | velocity low fade | **0** | partial `+8` |
| `6` | velocity high fade | **0** | partial `+10` |
| `7` | velocity high | layer `+42` | partial `+9` |
| `8:10` | sample index | word | word |
| `10:12` | fine tune | **0** | **`(partial[6] × 64 + 32) / 100`** |
| `12` | root key | wavesample `+170` | sample `+68` |
| `13` | volume | `TABLE[…]`, clamp −96…+10 | **0** |
| `14` | pan | `(ws[221] × 63)/127`, clamp −64…+63 | `partial[4] × 2`, clamp −64…+63, **or 0** |
| `15`–`21` | — | not written here | zeroed |

**Three differences that matter for a converter:**

- **Ensoniq discards fine tune and every crossfade; Roland carries both.** Roland
  is the richer import by some margin.
- **Roland discards zone volume** (writes 0) where Ensoniq converts it through a
  128-entry table. So the two formats lose *opposite* things.
- **Roland's velocity high and its fade are crossed**: `partial+9` → zone `7`
  (velocity high) and `partial+10` → zone `6` (fade). Written in that order in
  the code, so it is deliberate rather than a reading error, but it is the one
  row here most worth a corpus check.

### The laws in full

**Ensoniq volume** (`0x78edc`) — a table, not a formula:

```
  v = wavesample[208]
  if wavesample[225] != 0:  v = min((v + 12) & 0xff, 127)     ; boost flag
  return TABLE_0x796a4[v]                                     ; signed, −72…0 dB
```

**Ensoniq pan** (`0x78f10`): `(wavesample[221] × 63) / 127`, signed, truncating.

**Roland fine tune**: `(partial[6] × 64 + 32) / 100` — the `+32` is round-half-up
on a divide by 100, so this is `round(cents × 0.64)`. Roland stores ±50 cents;
±32 in E4 units is a half-semitone, so the E4 unit here is 1/64 semitone.

**Roland pan**: `clamp(partial[4] × 2, −64, +63)`, **but forced to 0** when
`(sample[58] >> 1) & 3 == 3` — a sample-format flag, almost certainly the
mono/stereo selector. So a Roland stereo sample imports centred regardless of its
partial's pan setting.

**Roland stereo pairs**: when a helper (`0x50d38`) returns 2, the builder writes a
second set of key-range bytes at **negative** offsets from the current zone
(`a5@(-22)`…`a5@(-9)`), i.e. back-patching the *previous* zone, and rewrites the
source partial's own bytes (`a3@(3) = 127`, `a3@(0,1,2) = 0`). That is a
stereo-pair fixup and it mutates the source structure as it goes.

## Roland (S-700 series) — module map

| address | what |
|---|---|
| `0x17064f` | `"S770 MR25A"` |
| `0x17065b`–`0x170684` | `"All Perfs"`, `"Empty Volume"`, `"All Patches"`, `"Empty Performnce"` |
| `0x171d68` | `"Roland Performance"` (referenced from `0x170772`) |
| `0x171dac` | `"Roland sample"` (referenced from `0x17114a`) |
| `0x171dbc` | `"patch"` (referenced from `0x171aac`) |
| `0x171dcc` | `"Roland S700 preset"` |
| `0x170600`–`0x172000` | the module, **18 functions** |

Function entries: `0x1706a4` (−88), `0x170788` (−32), `0x1708ec`, `0x1709a4`,
`0x170c58`, `0x170d84` (−80), `0x171048`, `0x1710cc`, `0x171114`, `0x171288`,
`0x171390`, `0x1715a4`, `0x171740`, `0x171860` (−144), `0x1719ac` (**−520**),
`0x171a80`, `0x171b58`, `0x171ba8` (−64).

`0x1719ac` holds a 512-byte buffer and walks an 88-entry table of 16-bit values;
it is a patch/split list handler rather than a parameter converter.

**The Roland object hierarchy is Performance → Patch → Partial → Sample**, which
does not map onto AKAI's program/keygroup or Ensoniq's instrument/layer, so the
conversion shape should not be assumed to resemble either.

### The Roland disc structure, verified

Cross-checked against a library disc (`Sound & Vision - Gigapack I CD 1`) with
k2kremote, who is decompiling the same three import paths out of the Kurzweil
K2000 ROM. Their ROM reading supplied the map; this disc confirmed the layout and
corrected the bases.

```
  sector 0 [4..7]  "S770"        the model digit at [6] is not tested by the
                                 K2000's sniffer, so S-750 matches too
  header LE16 counts at 0x114..0x11C
      Volume 122   Performance 269   Patch 889   Partial 4004   Sample 5761

  directories, 32-byte records, 16-char ASCII name, class tag at +0x10,
  LE16 size at +0x1E
      0x0A0800 .. 0x0A1740   tag 0x40  Volume        122
      0x0A1800 .. 0x0A39A0   tag 0x41  Performance   269
      0x0A5800 .. 0x0AC720   tag 0x42  Patch         889
      0x0CD800 .. 0x0FA820   tag 0x44  Sample       5761
```

At each base the first and last record carry the expected class tag, the count
matches the header exactly, and the record after the last is empty.

**k2kremote's ROM-derived bases are each 0x200 lower**, and the reason their
Performance base looked correct is worth recording: the Volume directory runs to
`0x0A1740`, so their `0x0A1600` sits **inside it** and returns a real, correctly
named, 32-byte-aligned record — of class `0x40`, not `0x41`. **A wrong base
landing on a valid-looking record of the wrong class.** Asserting the class tag
is what catches it; checking that a name looks like a name does not.

The **Partial directory was not found** — the header counts 4004 of them and
probes at `0x0AC720`, `0x0AC800` and `0x0AD000` are empty. It lies between the
Patch and Sample directories, or partials are reached through the patch records'
links rather than a directory.

The **Partial directory** is at `0x0AD800` (base `0x0AD600` + the same `0x200`),
tag `0x43`, 4004 records on this disc — located by k2kremote and confirmed here,
first record and the 4004th both carrying the tag.

**This is the disc's layout, not EOS's reading of it**, and nothing above says
which of these structures EOS walks.

### How EOS decides a disc is Roland

`0x16dd64`, decoded in full:

```
  16dd8c:  bsrw 0x16db8c         ; read sector 0
  16dd94:  pea 0x170650          ; "S770 MR25A"
  16dd9e:  pea %a0@(4)           ; sector 0 + 4
  16dda2:  jsr 0x1a6be8          ; strcmp
  16ddae:  moveq #1,%d7          ; match -> accept
```

**A full string compare against `"S770 MR25A"`**, including the `MR25A` suffix.
The K2000's sniffer, per k2kremote, tests only bytes 4, 5 and 7 (`S`, `7`, `0`)
and deliberately skips the model digit at byte 6, so it accepts S-750 and S-770
alike. **Two importers, the same disc, different notions of what identifies it.**

Tested against three discs, two of them format-version SYS 1.04 and one SYS 2.19:

```
  Gigapack I CD 1    "S770 MR25A"   EOS accepts
  Gigapack I CD 2    "S770 MR25A"   EOS accepts
  L-CDP-05 (SYS 2.19) "S770 MR25A"  EOS accepts
```

**The label does not vary with format version**, so EOS's stricter match costs
nothing there — the initial worry that it would reject newer discs is
unsupported. What remains is that EOS *would* reject any disc whose label differs
at all, and no S-750 disc is available to test whether those carry a different
one. **The asymmetry is real and its practical consequence is untested.**

Corpus available: `Dokumente/SYNTHS/Roland Samples/` (two raw ISOs plus four
archives, ~2.4 GB) and `Dokumente/SYNTHS/K2000R/Soundsets/`.

## Corpus status — the two halves validated very differently

**The DESTINATION half is fully validated; the SOURCE half is barely touched.**
This distinction matters and was easy to blur, because one cross-check arrived
looking like it validated the whole zone map.

### Destination (E4 zone fields) — independently confirmed, 11 of 11

mpc2emu checked the zone map against their 10 142-entry corpus of real E4B zone
entries. Adding the `+2` this document already derives for the header base, the
fields line up **eleven for eleven with no misses** — a firmware trace and a file
corpus neither of which had seen the other.

It also **resolved two byte pairs their corpus could only mark unknown**. Their
`[7]`/`[8]` — this document's velocity-fade pair — are non-zero on 36 zones and
occur in **mirrored pairs**: two samples over one key range and one full velocity
span, one fading in as the other fades out, 18 pairs of them. The trace supplies
the name, the corpus supplies the semantics, and neither half was sufficient
alone.

Their `[3]`/`[4]` — the key-fade pair — are zero across all 10 142 entries, so
**that pair rests on this firmware trace alone** and no corpus agreed with it.

### Source (Ensoniq file offsets) — NONE confirmed, and the address space is wrong

**Tested and failed.** mpc2emu framed the decisive question: are the firmware's
offsets in *disc* space or in a *packed* (de-interleaved) copy? The disc data is
word-interleaved — parameter bytes alternate with zeros — and the firmware's name
converter reads consecutive bytes, so it cannot be reading the disc bytes
directly.

De-interleaving a real instrument confirms **phase 0 carries the data** and finds
names at packed offsets 5, 333 and 445. Taking the wavesample struct's base as
`445 − 10 = 435` and reading this document's offsets from it gives **zero for
every field**. Taking the other block at `323` gives a boost flag of 127 and a
key range of 0/0. **Neither is a structure this document describes.**

```
  base 435:  transpose 0, root key 0, volume 0, pan 0, key range 0/0
  base 323:  transpose 1, root key 40, boost flag 127, key range 0/0
```

**So the source offsets are not offsets into the disc file at all, packed or
otherwise.** The most likely reading — and it is the same shape as the AKAI
module's scratch struct, where thirteen conversions wrote to a caller-owned
buffer rather than to anything on disk — is that EOS's loader parses the Ensoniq
file into an in-memory representation, and every source offset in this document
is an offset into *that*. If so they **cannot be validated against a disc image
at any base**, and doing it needs the loader traced first.

**And that retracts the one thing this document called confirmed.** The name at
`+10` matching the disc layout was read as evidence the offsets were disc
offsets. It is not: an in-memory struct that also places its name ten bytes in
produces exactly the same observation, and a shared convention is the more likely
explanation once every other offset fails. **One matching field is a plausible
neighbour, not a confirmation** — the same lesson as the base-18-versus-22 slip
and the three all-zero cord rows, arrived at for the third time.

**Status of the source half: nothing in it is validated.**

### One alternative not yet excluded

mpc2emu raised it and it is worth recording: a structure that looks interleaved
is sometimes **stereo**, not padded. Their own project read the wrong copy of
every loop point on mono-right Emulator III samples until 2026, because that
format stores each position twice, once per channel. The zeros argue against it
here — a second channel would hold a value, not a zero — but a *mono*
instrument's second channel would be zeros, and this instrument may be mono.

## What is not established

- **Roland's entire parameter mapping.** Nothing below the module map above.
- **Ensoniq envelopes.** The zone builder writes no envelope fields; they must be
  written by `0x7bb90` or by the layer walker, neither of which is traced.
- **Ensoniq filter, LFO and modulation.** Not found.
- **Any corpus validation at all.** Every offset here comes from the instruction
  stream and none has been checked against a real Ensoniq or Roland disk. The
  AKAI document's history is the warning: three of its thirteen rescale rows
  turned out to be unverifiable, and one "not read" claim was wrong and had a
  published finding built on it.
