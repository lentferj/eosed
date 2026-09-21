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
read straight from the disc.

**So the distinction is not "EOS importers" but "is there a loader between the
disc and the converter":**

```
  AKAI      flat file, parsed directly        source offsets ARE file offsets
  Ensoniq   loader builds a representation    disproven on real discs
  Roland    assumed the same, untested        nobody has tried
```

**The conflation that produced the wrong rule is worth recording**, because both
projects made it independently and it is subtle (mpc2emu's diagnosis, and better
than the one offered here first). AKAI's `%a5` scratch struct — the thirteen
program-header rescales that a corpus search could not find anywhere in a file —
is about **program-level values being staged for a keygroup pass that runs N
times**. It says nothing about how that pass *reads its source*, and the reading
is a flat file. One importer doing both things at once is exactly what made "not
the file" look like a property of the importer rather than of one code path
inside it.

**A negative result generalises no further than the thing it was measured on.**

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

> **RETRACTED 2026-09-21 — this heading and the section under it are wrong in
> both halves.** The offsets ARE disc offsets: the loader copies the block raw,
> and root key, volume and pan have since been confirmed against EOS's own
> output on hardware, 25/25 for pan and volume. The de-interleaving that made
> the search fail was the wrong transform, applied to the right offsets. See
> "The disc→RAM link: CONFIRMED against a real disc" below and
> RESOLUTION_NOTES §161. Kept because the reasoning is the record of how a
> right answer was argued away.

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
- ~~**Any corpus validation at all.** Every offset here comes from the instruction
  stream and none has been checked against a real Ensoniq or Roland disk.~~
  **Superseded 2026-09-21 for Ensoniq only:** the Ensoniq offsets are now checked
  against a 853-wavesample corpus across five discs AND against EOS's own import
  on hardware (pan 25/25, volume 25/25, layer masks 100/100). **Still true for
  Roland, where no import has ever been run** — that remains the biggest gap. The
  AKAI document's history is the warning: three of its thirteen rescale rows
  turned out to be unverifiable, and one "not read" claim was wrong and had a
  published finding built on it.

## The in-memory representation, identified

A loader trace contributed from an external session
(`GLM_ENSONIQ_LOADER_TRACE.md`) located the machinery behind this document's
blocker. Its instruction-level claims were re-derived here and **all verify**:
`0x7a4b8` is the module entry with a `-520` frame, it pushes the `"PRST"` tag
(`0x50525354`) to `0x19abdc`, takes `lea %fp@(-516),%a1`, fills it via
`bsrw 0x7a1bc`, and passes it as the **fifth** argument to `0x7bf0c`.

**Its headline is wrong, and the correction is the unblock.** That 516-byte
local is *not* the structure this document's source offsets index — it is the
scanner's slot list, 128 records of 4 bytes with a count at `+512`, which is
exactly how `0x7bbe4` consumes it (`movel %a0@(512),%d2` for the count,
`%a0@(0,%d7:l:4)` and `%a0@(2,%d7:l:4)` for the records). A wavesample offset of
`+208` would land inside record 52 of a slot list, which is meaningless.

The accessors give the real answer, and they are three lines each:

```
  0x78c60  instrument   = the long at 0x100037c4            (a single global)
  0x78c68  layer        = 0x102bede0 + index * 224          (fixed array)
  0x78c84  wavesample   = 0x102b5b50 + index * 288          (fixed array)
```

**So EOS's Ensoniq representation is three fixed RAM arrays, not a parsed
buffer.** Every source offset in this document indexes one of them:

| this document's source | array | stride | offsets used | fits |
|---|---|---:|---|---|
| instrument `+10`, `+66` | global at `0x100037c4` | — | 10, 66 | — |
| layer `+40`, `+42` | `0x102bede0` | 224 | 40, 42 | yes |
| wavesample `+170`, `+208`, `+221`, `+225`, `+274`, `+276` | `0x102b5b50` | 288 | max 276 | **yes, 276 of 288** |

**Every wavesample offset falls inside the 288-byte stride and the largest sits
near its top.** That is a consistency check the offsets could have failed and did
not — a wrong reading would scatter past the stride or bunch at the bottom.

### Why the disc search could never have worked

> **RETRACTED 2026-09-21 — the disc search works, and this section's own
> example is the counter-evidence.** The struct is a raw copy of the disc block,
> so a base offset reaches it exactly; and the `+10` name match dismissed below
> as a coincidence of convention **was the real thing all along**, as the
> section "The disc→RAM link: CONFIRMED against a real disc" in this same file
> states. The searches failed because they were run against a de-interleaved
> copy, not because the address space was unreachable.

These are absolute RAM addresses populated by the loader. **No base offset into
a disc image can reach them**, which is why §153's packed and raw searches both
failed at every base, and why the `+10` name match was a coincidence of
convention rather than evidence.

### The next target is now specific

The wavesample array is referenced from seven places:

```
  0x78c86   the accessor itself
  0x78dea   inside 0x78dcc -- the per-slot disc loader
  0x78ebe   0x79102   0x79214   0x793b8   0x7946c
```

**`0x78dcc` is where a disc record becomes a 288-byte wavesample.** Tracing it
converts every source offset in this document from "offset into what EOS holds"
to a chain "disc byte → array offset → E4 field", and makes the whole Ensoniq
table corpus-checkable the way AKAI's already is.

That is a much sharper target than the three block builders the external trace
proposed as next steps — those build the *sample* objects, not the wavesample
parameter records.

## The disc→RAM link: CONFIRMED against a real disc, with one correction

A second external trace (`GLM_ENSONIQ_DISC_FORMAT.md`) argues the wavesample
array is filled by a **bulk copy of the Ensoniq disc block**, so the source
offsets are literal disc offsets. **Tested on a real disc, and it is right** —
this retires §153's conclusion and makes the Ensoniq table corpus-checkable.

### The verification

Locating the struct by its name (the converter reads `+10`), the base falls at
raw disc offset **880** within an instrument file, and it is consistent across
every instrument on the disc:

```
  instrument    base   root  vol  pan  flag  klow  khigh
  1+2 HARMS      880     69  127    0     0    21    108
  AGOGO-BEL      880     60  127    0     0    21    108
  ANVIL-LP       880     50  127    0     0    21    108
  CLARINET       880     69  127    0     0    21    108
  CRUNCH-LP      880     67  127    0     0    21    108
```

**The root key varies — 50, 60, 67, 69 — and every value is musical.** That is
the discriminating evidence: a wrong base gives either constants or nonsense,
and this gives sensible per-instrument values at a fixed offset across ten
files. Volume reads 127 and the key range 21–108 on all ten, which is plausible
as this library's defaults and is *not* itself evidence.

**So §153 was wrong, and wrong for an identifiable reason.** Its searches used
a *de-interleaved* copy, and the struct is the **raw** block. The `+10` name
match that §153 dismissed as "a plausible neighbour, a shared convention" was
the real thing all along — it was discarded because every other offset was
being read from the wrong representation.

### The correction: pan and boost read structurally-zero bytes

> **RETRACTED 2026-09-21 by a four-disc corpus survey — see the section
> "`+221` is not a dead byte" below. `+221` is non-zero on 322 of 853
> wavesamples across four other Ensoniq discs. The parity argument below was
> generalised from a single disc and is wrong; the behavioural prediction it
> makes about EOS is withdrawn. The text is kept for the record.**

The disc data is word-interleaved — values at even offsets, zeros at odd — and
the field offsets are not all the same parity:

```
  +170 root key   even    real value
  +208 volume     even    real value
  +274 key low    even    real value
  +276 key high   even    real value
  +221 pan        ODD     always 0
  +225 boost flag ODD     always 0
```

Measured over the parameter area: **102 non-zero bytes at even offsets against
4 at odd.** So `+221` and `+225` land on the interleave's dead bytes, and they
read **0 on all ten instruments**.

**The consequence is a behavioural prediction about EOS**: every Ensoniq import
is panned centre and never volume-boosted, regardless of what the source
specifies — `pan = (0 × 63)/127 = 0`, and the boost flag never fires. Either
those two parameters live somewhere this reading has not found, or **EOS's
Ensoniq importer reads them from the wrong offsets.**

That is testable without a rig the moment an Ensoniq disc is imported on the
E4XT: read the resulting zone's pan byte. Non-zero refutes this; zero on a
source with a panned wavesample confirms an importer defect.

### What this unblocks

Every source offset in the Ensoniq tables above is now a **disc offset** and can
be checked against the corpus the way AKAI's can. The loader is not the gate it
was thought to be — `0x78dcc` copies rather than parses, so tracing it is no
longer required to validate the mapping.

## End-to-end validation against EOS's own import (2026-09-21, live)

Jan imported the first bank of `CD7-ENSVFX` on the E4XT. Every loaded preset was
dumped over SysEx and compared against the ISO run forward through the laws
documented above — source bytes → law → EOS's actual output.

### The forward check

```
  30 non-empty presets (10 instruments x 3 populated variants)
  120 / 120 field comparisons match

    root key   ISO +170            -> E4 zone root        every preset
    volume     TABLE_0x796a4[+208] -> E4 zone volume      every preset
    key low    ISO +274            -> E4 zone key low     every preset
    key high   ISO +276            -> E4 zone key high    every preset
```

**But 120/120 overstates it, and the distinct-value count says by how much:**

```
  root    6 distinct  (50,55,57,60,62,69)   STRONG
  klow    2 distinct  (21,36)               weak
  khigh   2 distinct  (67,108)              weak
  volume  1 distinct  (0)                   NONE -- constant, proves nothing
  pan     1 distinct  (0)                   NONE
  ftune   1 distinct  (0)                   NONE
```

**Only the root key is strongly validated.** Six distinct values, each predicted
correctly from a fixed disc offset across ten instruments — that is a relation a
wrong offset cannot satisfy. The key range carries two values, which is real but
thin. **Volume, pan and fine tune are constant across the whole bank and
validate nothing**, even though every one of them "matched".

The volume law is confirmed at exactly one point: `+208` reads 127 on every
instrument, `TABLE_0x796a4[127] = 0`, and the E4 reads 0. That the table is
right *at index 127* is established; the other 127 entries are not.

### Base 880 is fixed, not name-derived

> **NARROWED 2026-09-21 — true on this disc (97 of 97), false in general. A
> second disc gives bases of 656, 1104, 1328, 2544 and larger; 880 holds for 13
> of 25 instruments there. See RESOLUTION_NOTES §161. The argument below
> refutes name-location, which stands; it never established universality.**

`ACOUS-GTR` has no `UNNAMED WS` string at all, yet `B = 880` gives root 57 and key
range 36–67, matching the E4XT exactly. So the wavesample struct sits at a fixed
offset within the instrument file rather than being located by its name — which
also retires the last trace of §153's "the `+10` name match was the evidence"
reading. The name was never the evidence; the fixed base is.

### Four presets per instrument, and why one is empty

EOS writes **four** presets per Ensoniq instrument, named with the two-character
channel suffix the trace predicted at `0x7be64`:

```
  '1+2 HARMS     00'   sample=1   populated
  '1+2 HARMS     0*'   sample=1   populated
  '1+2 HARMS     **'   sample=1   populated
  '1+2 HARMS     *0'   sample=0   EMPTY
```

The `*0` preset is **genuinely empty, not a miscounted one** — its dump is the
same length with fewer non-zero bytes and a zone sample index of 0. (The
discriminating check, and the warning that a low voice count can be a size bug
rather than an empty preset, are mpc2emu's; their writer shipped exactly that
fault in June.)

**`*0` selects channel 1 alone, which a mono instrument does not have.** Three
populated and one empty is what a mono source predicts; a stereo instrument
should populate all four differently, which is the test that would confirm it.

> **RETRACTED 2026-09-21 — the four suffixes are LAYER masks, not a channel
> selection, and the firmware says so. See "The four variants are layer masks"
> below.**

### The pan prediction is VOID, not confirmed

`ENSONIQ_ROLAND_IMPORT.md` predicted every import lands centre because `+221`
and `+225` are odd offsets on word-interleaved data. **Every imported zone did
land centre — and the prediction still proves nothing**, because the source is
centre too:

```
  source +221 (pan)   across 10 instruments: {0: 10}
  source +225 (boost) across 10 instruments: {0: 10}
```

Centre output is what a correct converter and a broken one both produce here.
**And the original argument was circular**: the byte was said to read zero
*because* it is filler, with "it reads zero" as the support. Those are one
observation.

**Both rows are marked unverifiable, not verified.** Discriminating them needs an
Ensoniq disc with a genuinely panned wavesample. (Control proposed by mpc2emu,
who also supplied the generalisation: the uniform-field trap applies to the field
being *predicted about*, not only to the fields being read.)


## `+221` is not a dead byte: the interleave argument refuted (2026-09-21)

The section above concluded that `+221` (pan) and `+225` (boost) sit on odd
offsets of word-interleaved data, read structurally zero, and therefore that
**every** EOS Ensoniq import lands centre — an importer defect. mpc2emu pointed
out that the disc Jan imported cannot test a prediction of "always zero", and
that four more Ensoniq discs were sitting on this machine unscanned.

They were scanned. **The prediction is refuted.**

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

Only the reference disc — the one Jan imported — is centred throughout. That is
why the end-to-end run could not discriminate, exactly as predicted, and it is
why "always 0" survived: it was a property of one disc's content, restated as a
property of the format.

### The values are a pan control, and the field is signed

`0x78f10` sign-extends before scaling — `moveb %a0@(221),%d0; extbl %d0;
mulsl #63,%d0; divsll #127,%d0` — so the source byte is a **signed** −127…+127,
mapping to the E4's −63…+63. Read that way the corpus values stop being
nonsense and become a seven-position control:

```
  source  -127   -85   -42    0   +42   +85  +127
  E4 pan   -63   -42   -20    0   +20   +42   +63
```

Those six values account for essentially the whole non-zero population. Random
bytes would be uniform over 256; a seven-point cluster is a control surface.

**This corrects an error in the survey, not in the table** — the table has said
"signed, truncating" since it was written. The first pass of the survey script
read the byte unsigned and flagged 213 values as "out of range 0…127", which is
what made the result look like garbage. They were negative.

### A caveat on the survey's reach

Offset 880 is the only wavesample anchor validated against EOS's own output
(10/10 on the reference disc). Structs for a **second and later** wavesample are
interleaved with their audio at a stride that is not fixed — `ACOUS-GTR`'s
second struct sits at 71072, which is neither 880+288 nor block-aligned, and a
structural-signature scanner written to find them scored **0/10 against the E4
dump** and was discarded rather than tuned. So this survey is wavesample 0 of
each instrument, and the end-to-end check earlier was voice 0 / zone 0 only.

Plausibility at +880 on the four new discs runs 69–93% (100% on the reference),
so some entries are not wavesamples. The records carrying non-zero pan are
**cleaner than average** on the internal check that root lies inside its own key
range — 91%, 100% and 97% against a 75–93% baseline — so they are not the
failures.

### The test this designs

Directory block **4213** of disc A holds 19 instruments, 14 of them panned,
spanning every one of the five non-zero source values. Importing that one bank
predicts five distinct E4 pan readings:

```
  -63, -42, -20, +20, +63
```

**Five distinct values is a relation a wrong law cannot satisfy**, which is
precisely what the reference disc could not offer. If the import instead lands
every zone at centre, the original defect claim is correct after all and `+221`
is not where EOS reads pan. Either way the row stops being unverifiable.

This needs one hardware import and costs nothing else; it is Jan's call, since
writing a disc image to the card is his to authorise.


## The four variants are layer masks, not channel selection (2026-09-21)

The `*0`-is-empty explanation above — that the suffix picks a channel and a mono
instrument lacks channel 1 — is **wrong**. The firmware names the mechanism
exactly, and it is not channels.

### The gate

`0x78d64` decides whether layer `L` enters variant `v`:

```
  0x78d24:  TABLE[0..3] <- instrument@(44), @(46), @(48), @(50)
  0x78d64:  if layer object is null            -> skip
            if !(TABLE[v] & (1<<L))            -> skip
            chanmask = chan ? instrument@(52) : instrument@(54)
            if !(chanmask & (1<<L))            -> skip
            else include
```

and `0x7bdf0` builds each variant by calling the channel builder twice, `chan=1`
then `chan=0`, writing the suffix from the two bits of `v` at `0x7be64`
(`'*'` = 42 for a set bit, `'0'` = 48 for a clear one).

So there are **two independent gates**: a per-variant layer mask at
`+44/+46/+48/+50`, and a per-channel layer mask at `+52` (channel 1) and `+54`
(channel 0). The suffix bits index the first. They say nothing about channels.

### What the reference disc actually holds

All 97 instruments carry **identical** masks:

```
  variant masks (v0,v1,v2,v3) = (7, 1, 2, 3)    on 97 of 97
  channel masks (ch1, ch0)    = (255, 0)        on 97 of 97
```

Read through the gate: `v0` = layers {0,1,2}, `v1` = layer {0}, `v2` = layer
{1}, `v3` = layers {0,1}. Every layer is present on **channel 1**, and
**channel 0 is empty on every instrument** — the exact opposite of the retracted
claim, which had the content on channel 0 and `*0` reaching for a missing
channel 1.

`*0` is `v2` = **layer 1 alone**, and these instruments only have layer 0
populated. That is the whole explanation. It is not about mono or stereo, and
the E4 voice counts confirm it: `v0`, `v1` and `v3` all return the same voices
(layer 0's), `v2` returns none.

### Why the error survived

"Mono instrument lacks channel 1" fitted the observation — three populated, one
empty — and the observation could not distinguish it from "these instruments
have only layer 0", because **on that disc the masks are constant**. Identical
on 97 of 97 instruments. The same uniform-corpus trap as the pan row, in a disc
that also happens to be uniform in exactly this field.

A mask that never varies cannot tell you what the mask means.

### The other discs vary, which is what makes the model testable

```
  disc   instruments   distinct variant-mask tuples   both channels populated
  ref         97                    1                        0
  A          547                 many                       74
  B           39                 many                       14
  C          222                 many                       25
  D           45                 several                     0
```

Common tuples on disc A include `(3, 12, 48, 192)` — a clean four-way split of
eight layers, two per variant — and `(1, 24, 6, 96)`. Where the reference disc
offers one mask repeated 97 times, disc A offers a genuine distribution, and
**113 of 850 instruments across the corpus have both channel masks non-zero**,
so dual-channel instruments do exist. They are simply not what `*0` was about.

### The designed test, updated

Disc A, **bank #40 of 64** (directory block 4213), 25 instruments, tests both
open questions in one import:

```
  pan:      14 instruments non-zero, predicted E4 pans -63, -42, -20, +20, +63
  layers:   variant masks vary per instrument -- (3,144,6,10), (7,5,2,3),
            (3,12,48,192), (1,2,4,8), (3,224,28,23) among them
  channels: at least one instrument carries (ch1,ch0) = (247, 8)
```

Five distinct predicted pans no wrong law satisfies, and a per-instrument
variant-mask prediction that the reference disc could not make at all, since
there every instrument predicted the same thing.


## The volume law MEASURED (not completed): `+225`'s +12 index boost, n=1 (2026-09-21)

> **Heading and opening sentence corrected the same day.** They read "The
> volume law completed" and "as documented above reads the table directly. It
> is incomplete." **Both false** — the law in this document's own conversion
> table has carried the `+225` branch since the file's first commit
> (`67fd16f`). What was incomplete was the *scoring script*. This section
> survived a correction pass three minutes earlier that fixed a different
> sentence in this same paragraph and left the heading and the opening line
> standing: the exact failure the heading rule had just been written to
> describe. See RESOLUTION_NOTES §161 addendum.

The Ensoniq volume law was documented with its boost branch from the start, but
that branch had **never been exercised by any measurement**. `0x78edc` in full:

```
  volume = TABLE_0x796a4[ ws[225] ? min((ws[208] + 12) & 0xff, 127) : ws[208] ]
```

`+225`, labelled "a boost flag" in the prose of this document though its effect
was given correctly in the law from the first commit onward,
**adds 12 to the volume table index** — truncated to a byte, then clamped to
127. Measured: the one instrument in a 25-instrument bank with `ws[225] != 0`
has `ws[208] = 80`, and `TABLE[92] = -3` is what the E4XT reports, where
`TABLE[80] = -5` is what the table alone predicts. With the term, volume scores
25/25 on that bank; without it, 24/25.

Confirmed at one point only — one instrument carries the flag. See
RESOLUTION_NOTES §161 addendum.

## The Roland parameter regions located, and the source-offset assumption refuted (2026-09-21)

The Roland tables above carry source offsets — `partial[4]` pan, `partial[6]`
fine tune, `partial[9]`/`[10]` the crossed velocity pair, `patch[13]`/`[14]` the
key fades, `src[24]` transpose. This document said those are offsets into what
EOS *holds*, and that their being file offsets was **assumed by analogy with
Ensoniq, not established**. That assumption is now **refuted**.

### Where the parameter records are

The directories at `0x0A0800`…`0x0CD800` are name plus a doubly-linked index
list (`+0x10` class tag, `+0x12` index, `+0x14` prev, `+0x16` next) with **no
file pointer**. The parameter records are a separate area, located by scanning
for runs of name-bearing slots whose length equals the header's own count:

```
  class         base        stride   records   count matches header
  Volume        0x10D800       256       122   exact
  Performance   0x115800       512       269   exact
  Patch         0x155800       512       889   exact
  Partial       0x1D5800       128      4004   exact
  Sample        not located — no name-bearing run after the Partial region
```

**These bases are identical on both discs of a two-disc library with different
counts**, so they are fixed format offsets rather than per-disc values. Each
record begins with the same 16-byte name as its directory entry.

### Why the source offsets cannot be file offsets

Every law offset below 16 lands **inside the name**. Surveyed across 3987
partials, `+4`, `+6`, `+9`, `+10` all read 32…120 — printable ASCII, on every
record. The same for `patch[13]`, `[14]`, `[24]`.

**A field that is 100% printable ASCII on four thousand records is a name, not a
parameter.** So the Roland source columns need a base offset within the record,
exactly as Ensoniq's needed 880, and **no row in the Roland tables can be
corpus-checked until that base is found.**

### What the record looks like instead

The 128-byte partial record's parameter area begins at `+16` and contains a
**repeating 16-byte sub-record**: offsets `+16…+30`, `+32…+46`, `+48…+62` have
matching profiles field for field, and `+27`/`+43`/`+59` are zero on every
record. That is the partial's sample slots, which is consistent with a Roland
partial addressing several samples.

### Choosing a test disc by measurement rather than by size

Counting parameter bytes that vary at all, and those taking eight or more
distinct values, over the non-header records:

```
                 records   varying bytes   rich (>=8 values)
  disc 1 Patch       872              92                  51
  disc 1 Partial    3987              82                  48
  disc 2 Patch       910             101                  92
  disc 2 Partial    2874              91                  59
```

**Disc 2 is the richer disc on every measure, and it is the smaller one** — 497
MB against 589 MB, with 2880 partials against 4004. Picking on size would have
picked the weaker test, which is the §157 lesson arriving before the experiment
instead of after it.

### The Roland object graph, and choosing a bank by content

The parameter records link downward by index, all **LE16, `0xffff`-terminated,
1-based**:

```
  Volume      +32   -> performance ids   (256-byte record)
  Performance +256  -> patch ids         (512-byte record, 127 slots)
  Patch       +256  -> partial ids       (512-byte record, 128 slots = a key map)
```

The patch's array is 128 entries filling the record exactly, one per MIDI key —
so a patch maps keys to partials directly rather than holding a zone list.

Walking that graph makes a bank's content measurable before any import. Counting
parameter-byte offsets in `+16…+63` of the reachable partials that take six or
more distinct values ("rich") and those that vary at all:

```
  rich  vary  perf  patch  part   bank
    12    22     3      8   140   (E-guitars)
     9    27     4     97   153   (synth basses)
     9    24     8     78   165   (analog synth, large)
     9    23     2     18    51   (two mono synths)
```

on a disc with 69 banks that reach any partials. **The richest bank is also one
of the smallest** — 8 patches against 97 — so richness and size are not the same
axis here, which is the whole reason for measuring rather than taking the
biggest.

## EOS's Roland import unit, and a volume-level import that silently drops most of a bank (2026-09-21, live)

First Roland import ever run on the E4XT. Two findings, both from Jan's own
experiments at the panel rather than from the disc analysis.

### The import unit is the PATCH; the bank list shows PERFORMANCES

The panel lists a volume's **performances**. Importing one performance produces
**one preset per patch it references**. Confirmed on a 3-performance volume:

```
  volume  ->  performance A  ->  2 patches   ->  2 presets
              performance B  ->  2 patches   ->  2 presets
              performance C  ->  6 patches   ->  6 presets
                                              --------------
              all three, loaded individually    10 presets
```

The operator sees three entries in the bank and gets ten presets, because the
third entry is a six-patch container. **This corrects the session's own
planning error:** the bank was chosen and sized in *patches* from the object
graph, and quoted as though patches were presets. They are — but the bank list
is one level above them, so "8 patches, a small bank" described something the
operator never sees.

### A volume-level import yields a strict subset

> **RETRACTED 2026-09-21, within the hour, by the machine's operator.** There is
> no silent loss and no selection rule. **Pressing Load with the cursor on the
> VOLUME loads the first performance in it** — Jan's hypothesis, and it is
> exactly right: performance 1 holds 2 patches, and 2 is what a volume-level
> load produced. The section below reads a defect into a cursor position.
>
> It survived as long as it did because of an **off-by-one in this project's own
> index resolution**: the patch ids in a performance's list are **0-based**, and
> reading them 1-based made the two loaded presets look as though they came from
> two different performances, which no "first performance" rule could explain.
> Resolved 0-based, performance 122 alone is `['E-Guitar 1', 'E-Guitar 2']` —
> precisely what loaded — and the union of all three performances is precisely
> the 10 that a per-performance load produced.
>
> **The correct statement is that the E4XT's dialogue states it will load a
> single bank from the folder and offers a choice of which** — the scope is
> announced and chosen at the moment of the action, so it is not silent, not
> implicit, and not a surprise. Jan's correction, to this project's own
> retraction. See §168.

Importing the **whole volume** gives **2 presets**, not 10. The two are the
*second* patch of the first performance and the *first* patch of the second —
nothing at all from the six-patch third.

**It is not a memory limit.** Measured on the device immediately after:

```
  sample memory   128 MB total, 117.2 MB free   (~11 MB used)
  preset memory   4485 KB total, 4443 KB free   (99% free)
```

Nor is it a merge artifact: a clean **Load** of the volume gives the same 2.

**So EOS's volume-level Roland import silently produces a fraction of the
material, with no error and no resource pressure.** Anyone converting a Roland
library volume-by-volume would lose most of it and have nothing to indicate the
loss. The selection rule is not established — 2 of 10, taking one patch from
each of the two small performances and none from the large one, is the whole of
what is known.

**Practical consequence: import performance-by-performance, never by volume.**

### Field variation in the result

Across the first 14 presets dumped (a different pair of banks):

```
  velocity ranges   VARY   94..101, 1..66, 89..97, 1..58, 1..70, 101..110, 1..63
  key ranges        vary   21..21, 36..47, 36..49, 0..127
  root key          varies 36, 45, 48, 52, 60
  pan               0 on all 14      <- constant
  volume            0 on all 14      <- constant
  coarse tune      -1 on all 14      <- constant
  fine tune         0 on all 14      <- constant
```

The velocity spread is the useful part: it is what the **crossed velocity-high
and fade row** needs — the row this document already flags as surprising, where
`partial+9` → zone 7 and `partial+10` → zone 6 appear swapped in the
instruction stream.

**Pan, volume and both tunes are constant, so those Roland rows remain
untestable on this material** — declared before the analysis rather than after
it, which is the one habit §158 was supposed to leave behind.

## The Roland record base SOLVED, and the velocity mapping measured (2026-09-21, live)

The section above recorded that the Roland source offsets cannot be file offsets
— every one below 16 lands inside the record's name — and that no Roland row
could be corpus-checked until a base was found. **The base is found.**

### The structure

```
  partial record   0x1D5800 + (id - 1) * 128
  sub-records      +16 + k*16          one per E4 velocity zone
  within a sub-record:
      +7   velocity low
      +8   velocity low fade
      +9   velocity high
      +10  velocity high fade
```

**The documented law offsets were right all along** — they are offsets into the
**16-byte sub-record**, not into the partial record and not into the file. That
is the same shape as Ensoniq's base 880: a correct table addressed from the
wrong origin.

### How it was found

One imported preset had **overlapping** velocity zones where every other preset
in the bank was contiguous — 5–6 units of overlap with a fade of 7, against fade
0 everywhere else. Searching the whole partial region for a record containing
all three of that preset's velocity split points returned 13 of 2880 records,
and the offsets were **25, 41, 57** — a stride of 16, which is the sub-record
structure already identified. `25 = 16 + 9`, and `+9` is exactly where the table
says velocity high lives.

**A single preset with non-default values did what a whole bank of defaults
could not.** The bank was chosen for parameter variation, and the one preset
that varied is the one that solved it.

### Validation against EOS's own output

```
  384 field comparisons, 384 match, 0 mismatch

  field        distinct   strength
  vlow             10     STRONG
  vhigh             9     STRONG
  vlowfade          2     weak  (0 and 7)
  vhighfade         2     weak  (0 and 7)
```

The partial is located **by name**, independently of the mapping under test, so
only the offsets are being tested. Velocity low and high are strongly validated.
**The two fade rows rest on two values each** — but the non-default value 7
appears at exactly the internal zone boundaries and 0 at the outer edges, which
a wrong offset does not reproduce.

### The "crossed" row needs re-examination, by its owner

This document flags a row as surprising: Roland's velocity high and its fade
appearing **crossed**, `partial+9` → zone byte 7 and `partial+10` → zone byte 6.

Measured, the four fields map in **natural ascending order** to velocity low,
low fade, high, high fade — `+7`, `+8`, `+9`, `+10` — 384/384.

Whether that contradicts the crossed reading depends on the **E4B zone-entry
byte indexing**, which is mpc2emu's, not this project's. So the finding here is
the semantic mapping, stated as such; the byte-index question goes to them
rather than being resolved from this side.

### What this unblocks

Every Roland row in the tables above can now be addressed and corpus-checked,
against 2880 partial records on this disc alone. The Roland path moves from
"nothing hardware-confirmed" to "velocity mapping confirmed, the rest
addressable."

### Key ranges come from the patch key map, and EOS caps a patch at 8 voices

Key range and root are **not in the partial record** — no sub-record offset and
no fixed partial offset matches the E4's reported values on any of 96 anchored
zones. They come from the **patch's 128-entry key map** at `patch+256`:

```
  E4 zone key range = a contiguous RUN of the same partial id in the key map
  E4 key            = key-map index + 21          (21 = the E4's lowest key)
  and EOS takes the FIRST 8 RUNS ONLY
```

Measured on presets whose key map holds more runs than EOS imported:

```
  preset          runs in key map   E4 voices
    (guitar 1)          21              8      13 runs DISCARDED
    (chord)             13              8       5 discarded
    (velo-play)         13              8       5 discarded
    (heaven)             5              5       none lost
```

**A Roland patch with more than eight key zones loses everything above the
eighth, silently.** Combined with the volume-level import dropping most of a
bank, EOS's Roland path is lossy in two independent ways, neither reported.

### Where the law does NOT hold — three cases, unexplained

Across 14 presets the law matches 11 and fails 3, and the failures are not
alike:

```
  two presets   key map has 4 runs, EOS built 3 voices — one run dropped with
                the other three matching exactly
  one preset    key map has 11 runs, EOS built a SINGLE zone spanning 0..127
```

The single-full-range case is the more interesting: several presets in the same
import came back as one `0..127` zone rather than a key map, and which presets
do this is not established. **The law is recorded as holding on 11 of 14, not as
general**, and the three exceptions are the next thing to chase — offline, from
captures already in hand.

### EOS's own names for the Roland hierarchy, from the LOAD dialogue

Photographed at the panel. The import dialogue reads:

```
  Drive:  D7 <cd-rom>
  Folder: F065 <name>          <- the Roland VOLUME
  Bank:   B123 <name>          <- the Roland PERFORMANCE   (a selector)
  [Cancel]      [Merge]      [Load]
```

So the terminology maps:

```
  EOS "Folder"  =  Roland Volume
  EOS "Bank"    =  Roland Performance
  EOS preset    =  Roland Patch
```

**`Bank:` is a chooser with the first entry pre-filled**, and Load acts on the
selected bank. There are **two routes to the same operation** — set `Bank:` in
this dialogue, or navigate into the folder and choose the bank there.

**There is no volume-level import at all.** Every load is bank-level; the
"volume-level import drops material" finding described an operation that does
not exist. A bank was chosen — by the pre-filled default — and that bank was
loaded.

**This naming is why the level question was hard.** The browser's top list
(`F061`…`F070`) shows folders, so "the bank I loaded" and "the bank in the
object graph" were two different levels throughout, and this project spent the
session sizing work in the wrong unit and then reading a defect into the gap.
The operator's screen names all three levels unambiguously; nothing in the disc
image or the ROM does.

**And the dialogue confirms the index base independently**: the performance this
project indexes as 122 displays as `B123`. Internal numbering is **0-based**,
display is **1-based** — the same off-by-one that produced the retracted
finding, visible on the front panel the whole time.
