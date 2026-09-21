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


## The volume law completed: `+225` is a +12 index boost (2026-09-21)

The Ensoniq volume law as documented above reads the table directly. It is
incomplete. `0x78edc` in full:

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
