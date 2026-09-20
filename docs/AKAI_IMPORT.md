<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# EOS's AKAI importer, as read out of the firmware

What EOS 4.70 actually does when it converts an AKAI S1000/S3000 program into an
E4 preset, read from the machine's own code rather than inferred from its output.

This exists because inference had hit a wall. mpc2emu could establish *which*
AKAI byte fed which EOS field by differencing 361 converted programs, but not the
conversion **law** — going through the physical quantity (AKAI rate → Hz → E4XT
byte) reproduced EOS exactly at one anchor and drifted 13 bytes away at the low
end, and from outside the machine there is no way to tell whether EOS is not
Hz-matching or the Hz curve is wrong. The code answers it directly.

## Reproducing the image

```
  eosflash export EMU_EOS470_OMNIFLOP.img --eos eos470.eos
  eosflash flash  eos470.eos --eos eos470_plain.eos --4mb     -> 1,965,696 bytes
  m68k-linux-gnu-objdump -D -b binary -m m68k:68020 \
      --adjust-vma=0x20000 --start-address=0x47778 --stop-address=0x47e44 \
      eos470_plain.eos
```

**Load base is `0x20000`** — every address below is a load address, so the file
offset is `addr - 0x20000`. The ISA is ColdFire MCF5206E; `m68k:68020` decodes it
with no invalid words in this region.

## Where the code lives

| region | what |
|---|---|
| `0x42a00`-`0x44400` | disk browser: AKAI device detection and file identification |
| `0x42a70` | `"AKAI Sampler    "`, 16 bytes space-padded — the browser's device label |
| `0x431c5` | `"Scanning AKAI device"` |
| `0x432d8`-`0x43944` | S1000 file handling; type bytes `0x70`/`0x73` appear as `pea` immediates |
| `0x43b7c`-`0x441fc` | S3000 file handling; type bytes `0xf0`/`0xf3` |
| `0x43a94`, `0x4434c` | `"S1000 preset"`, `"S3000 preset"` — browser descriptors, **not** the importer |
| **`0x48934`-`0x48a0c`** | **the orchestrator**: header convert, then a keygroup loop |
| **`0x47778`-`0x47e44`** | **the program-header converter** (stack frame `-200`) |
| `0x47f08`, `0x48284`, `0x48500` | parallel converters, frames `-208`/`-208`/`-200` |
| `0x48ab0`-`0x48c00`+ | the conversion lookup tables, packed back to back |
| `0x3060c` | AKAI name → ASCII converter |
| `0x31ba4` | AKAI character set |
| `0x2f6f8` | the volume scaler |

**The S1000 and S3000 readers are parallel code**, offset about `+0x8A0`
(`0x433d3`~`0x43c77`, `0x43517`~`0x43dcb`, `0x43763`~`0x4401d`,
`0x43a0e`~`0x442c6`). Anything found in one is checkable against the other for
free, which is a built-in overlap rung — use it.

The browser identifies the file and *then* decides to import rather than load.
The import **options** ("Combine L/R into stereo", "Adjust Akai/Ensoniq
fractional loops", "Akai/Ensoniq conversion", at `0x25d00`-`0x25d3d`) live in the
master/config menu and are a separate thread; they are not the converter.

## The converter's shape

```
  47778:  linkw %fp,#-200          ; 200-byte local buffer for the AKAI program
  47784:  movel %d1,%d7            ; d7 = caller's handle
  47786:  moveal %a1,%a4           ; a4 = the preset object (header + 2)
  47788:  moveal %a0,%a5           ; a5 = the caller's 68-byte SCRATCH struct
  4778a:  lea %fp@(-196),%a1
  47790:  bsrw 0x4771c             ; read the AKAI program into the buffer
```

**The AKAI program is copied to `%fp@(-196)`, so a local reference `%fp@(-N)`
is AKAI program byte `196 - N`.** That mapping is what makes the listing
readable; every "akai byte" below is derived from it.

Each field conversion is one of a small set of idioms:

```
  moveb %fp@(-N),%d7        ; source byte
  extbl %d7                 ; SIGN-EXTENDED -- negative sources are possible
  tstl / bpl / moveq #0     ; clamp low
  moveq #MAX,%d0 / cmpl / bge / moveq #MAX   ; clamp high
  moveal #TABLE,%aN         ; optional lookup
  moveb %aN@(0,%d7),%d1
  moveb %d1,%a5@(OFF)       ; store
```

## The preset header

`%a4` is **`header + 2`**, pinned by the name call: `pea 0xd; movel %a4; pea
%fp@(-193); jsr 0x3060c` writes 13 bytes to `%a4+0`, and the E4B preset header
carries its name at `[2:18]`. Two independent checks agree — the field is first
`memset` to `0x20` for 16 bytes (the header's name is space-padded ASCII), and
`movew #82,%a4@(16)` lands `0x00 0x52` at `header[18:20]`, exactly the `[18]=0x00`
/ `[19]=0x52` constant the format already documents.

| store | header byte | meaning |
|---|---|---|
| `memset(a4, 0x20, 16)` then `0x3060c` 13 bytes | `[2:18]` | name, space-padded |
| `movew #82,%a4@(16)` | `[18:20]` | the `00 52` constant |
| `clrw %a4@(20)` / `clrw %a4@(22)` | `[22:26]` | zeroed |
| `moveb %d7,%a4@(24)`, clamped −24..+24 | `[26]` | **transpose** |
| `moveb %d0,%a4@(25)` from `0x2f6f8` | `[27]` | **volume, dB** |

Only these three stores to `%a4` occur in this function; the rest of the header
is written elsewhere.

### Byte 27 is the preset volume, and this is its exact arithmetic

`0x2f6f8`, called as `f(akai_byte, 99)`:

```
  d7 = clamp(akai_byte, 0, 99)
  d7 = ((d7 - 99) * 8) / 10          ; signed, truncating toward zero
  return clamp(d7, -96, +10)
```

So **`volume_dB = clamp((akai_volume - 99) * 8 / 10, -96, +10)`**, stored as a
signed byte. `-96..+10` is exactly `E4_PRESET_VOLUME`'s range.

It reproduces the observed corpus. Across 363 imported presets byte 27 takes the
nine values 239, 240, 241, 242, 243, 244, 245, 249, 250 — as signed, −17..−6:

| akai volume | arithmetic | dB | byte |
|---:|---|---:|---:|
| 99 | `0 * 8/10` | 0 | 0 |
| 91 | `-8 * 8/10 = -6.4` | −6 | 250 |
| 90 | `-9 * 8/10 = -7.2` | −7 | 249 |
| 82 | `-17 * 8/10 = -13.6` | −13 | 243 |
| 80 | `-19 * 8/10 = -15.2` | −15 | **241** (the mode) |
| 78 | `-21 * 8/10 = -16.8` | −16 | 240 |
| 77 | `-22 * 8/10 = -17.6` | −17 | 239 |

The gaps in the observed set (246, 247, 248 = −10, −9, −8) are reachable; no
source program happened to carry the volumes that produce them.

This **closes** the byte-27 question and **refutes** this project's earlier
prediction that byte 27 pointed at FX. It is the volume, the importer computes
it, and the save path merely preserves it.

## The LFO rate table

**`0x48b24`, 100 entries**, indexed by the AKAI byte clamped to 0..99:

```
   0   2   4   9  11  14  16  20  22  24  27  29  31  33  35  37  39  40  42  43
  45  47  48  50  51  52  53  55  56  57  58  60  61  62  63  64  65  66  67  68
  69  70  71  72  73  74  75  76  76  77  78  79  80  80  81  82  83  84  84  85
  86  86  87  88  88  89  89  90  91  92  92  93  93  94  94  95  95  96  97  97
  98  98  99  99 100 100 101 101 102 102 103 103 104 104 105 105 106 106 107 107
```

**It serves both LFO rates.** The address appears as a 32-bit literal exactly
once, at `0x478a4`, but `%a3` holds it across the following conversion:

```
  478a2:  moveal #0x48b24,%a3      ; AKAI 0x21 -> dest 6
  ...
  47924:  moveal %a3,%a0           ; AKAI 0x1D -> dest 12, SAME table
```

Counting literal references alone would have missed the second use. mpc2emu
confirmed both from the other side — 26 distinct values on the `0x21` path and 11
on `0x1D`, both satisfying `dest == T[src]` across 361 programs.

**EOS does not Hz-match.** The importer computes no frequency: it clamps and
indexes an array. A Hz round-trip disagreeing with EOS is therefore not evidence
that the Hz curve is wrong — but the table is now directly comparable to such a
curve as data, which is a question that can be settled offline.

## The full conversion map

Mechanically extracted; see the confidence note below before relying on a row.
The proportional-rescale rows are given exactly in the next section; the
table below is the raw extraction and its "call" attribution was wrong in
at least two places (`0x50c04`/`0x50c24` are struct initialisers, not
converters), so the columns to trust here are the source and destination.

| dest off | akai byte | table | clamp |
|---:|---:|---|---|
| 0 | 0xc2 | — | — |
| 2 | 0x2a | — | — |
| 3 | 0x29 | — | — |
| 4 | 0x42 | — | — |
| 6 | **0x21** | **0x48b24** | 0..99 |
| 7 | 0x61 | 0x48b88 | 0..3 |
| 12 | **0x1d** | **0x48b24** (via `%a3`) | 0..99 |
| 13 | 0x62 | — | 0..3 |
| 25 | 0x6e | 0x48b8c | 0..99 |
| 32 | 0x1a | — | — |
| 33 | 0x4f | 0x48ab0 | 0..14 |
| 34, 35, 38, 39, 40, 45 | 0x50, 0x58, 0x4c, 0x4d, 0x4e, 0x57 | — | 0..14 |
| 36, 37, 41, 42, 43 | 0x5c, 0x5d, 0x59, 0x5a, 0x5b | — | — |
| 44 | 0x18 | — | — |
| 46 | 0x27 | — | ±24 |
| 47 | 0x28 | — | ±12 |
| 48, 49, 56, 57, 58 | 0x22, 0x1e, 0x24, 0x25, 0x26 | — | — |
| 50, 51, 59, 60, 61, 62, 63, 64 | 0x51, 0x52, 0x54, 0x55, 0x56, 0x63, 0x64, 0x65 | — | 0..14 |
| 53, 54 | 0x5e, 0x5f | — | — |

Other tables seen in the same block:

```
  0x48b88    4 entries, clamp 0..3      0 2 3 255
  0x48b8c  100 entries, clamp 0..99     29 29 29 30 ... 78 81 85
  0x48ab0   15 entries, clamp 0..14     0 17 16 18 20 10 9 97 105 72 80 17 16 20 88
```

## The generic rescaler, which explains most of the conversions

`0x2f6b4(value, lo, hi, scale)`:

```
  c  = clamp(value, lo, hi)
  d7 = (2*c * 2*scale) / (2*hi)      ; signed
  if d7 > 0: d7 += 1
  return d7 >> 1                     ; i.e. round(c * scale / hi)
```

So **`round(clamp(v, lo, hi) * scale / hi)`** — a proportional rescale with
round-half-up. Arguments are pushed `scale, hi, lo, value`; note `lo` is often
pushed with `clrl`, not `pea 0`, which is easy to miss when reading call sites
mechanically.

Every call site in the program converter, with its own constants:

| akai byte | dest off | conversion |
|---:|---:|---|
| 0x1a | 32 | `round(clamp(v,-50,50) * 77/50)` |
| 0x5c | 36 | `round(clamp(v,-50,50) * 75/50)` |
| 0x5d | 37 | `round(clamp(v,-50,50) * 75/50)` |
| 0x59 | 41 | `round(clamp(v,-50,50) * 48/50)` |
| 0x5a | 42 | `round(clamp(v,-50,50) * 48/50)` |
| 0x5b | 43 | `round(clamp(v,-50,50) * 48/50)` |
| 0x5e | 53 | `round(clamp(v,-50,50) * 25/50)` |
| 0x5f | 54 | `round(clamp(v,-50,50) * 48/50)` |
| 0x22 | 48 | `round(clamp(v,0,99) * 32/99)` |
| 0x1e | 49 | `round(clamp(v,0,99) * 32/99)` |
| 0x24 | 56 | `round(clamp(v,0,99) * 32/99)` |
| 0x25 | 57 | `round(clamp(v,0,99) * 32/99)` |
| 0x26 | 58 | `round(clamp(v,0,99) * 32/99)` |

The two shapes are AKAI's signed ±50 controls mapping onto EOS ranges of ±77,
±75, ±48 and ±25, and AKAI's 0-99 depths mapping onto 0-32.

`0x2f784` is a thin wrapper used for one field (akai `0x18` -> dest 44):
`clamp(round(clamp(v,-50,50) * 64/50), -64, +63)` — AKAI's ±50 pan onto EOS's
±64.

## The mapping in human terms

What a person sees on the AKAI's screen, what happens to it, and what they see on
the E4's. **The AKAI names are AKAI's own** (from mpc2emu's
`docs/AKAI_S3000_FORMAT.md`, which derives them from the S1000 structure document
and confirms them against 5,124 library programs).

### Confirmed both ends

| AKAI parameter (range) | formula | E4 parameter (range) |
|---|---|---|
| `PRLOUD` loudness `0x19` (0–99) | `clamp((v − 99) × 8 / 10, −96, +10)` | **Preset Volume** (−96…+10 dB) |
| `PANPOS` pan `0x18` (−50…+50) | `clamp(round(clamp(v,−50,50) × 64/50), −64, +63)` | **Pan** (−64…+63) |
| LFO1 Rate `0x21` (0–99) | `T[clamp(v,0,99)]`, table `0x48b24` | **LFO1 Rate** (0–107 observed) |
| LFO2 Rate `0x1D` (0–99) | same table `0x48b24` | **LFO2 Rate** (0–107 observed) |
| program name `0x03-0x0e` (12 chars, AKAI charset) | `charset[c]`, non-printable → space | **Preset name** (16 bytes, space-padded) |
| keygroup count `0x2a` (1–99) | direct | **voice count** |

`PRLOUD` and `PANPOS` are the two that can be stated with full confidence at both
ends: the AKAI side is named and confirmed independently, and the E4 side is
pinned by the destination range (−96…+10 is `E4_PRESET_VOLUME` and nothing else;
−64…+63 is the pan byte). **mpc2emu reimplemented the `PRLOUD` row and matched
EOS on 363 of 363 presets, zero differences.**

The two LFO rows are confirmed on the E4 side by corpus match rather than by
range (26 distinct values on the LFO1 path, 11 on LFO2, both satisfying
`dest == T[src]` across 361 programs).

### Named on the AKAI side

Names from **s3ked's `s3k/params.py`**, transcribed from Akai's own S1000 /
S2800-S3000-S3200 / S2000-S3000XL-S3200XL SysEx documents. The offset convention
was validated before use: s3ked's keygroup-count offset matches the `0x2a` anchor
the importer's own loop bound confirms.

| AKAI parameter (range) | formula | E4 parameter modulated | dest scale |
|---|---|---|---|
| `V_LOUD` `0x1a` (−50…+50) — velocity → loudness | `round(clamp(v,−50,50) × 77/50)` | Velocity → **Amp Volume** | ±77 |
| `MODVAMP1` `0x5c` (−50…+50) — loudness by assignable source 1 | `× 75/50` | cord → **Amp Volume** | ±75 |
| `MODVAMP2` `0x5d` (−50…+50) — loudness by assignable source 2 | `× 75/50` | cord → **Amp Volume** | ±75 |
| `MODVPAN1` `0x59` (−50…+50) — pan by assignable source 1 | `× 48/50` | cord → **Pan** | ±48 |
| `MODVPAN2` `0x5a` (−50…+50) — pan by assignable source 2 | `× 48/50` | cord → **Pan** | ±48 |
| `MODVPAN3` `0x5b` (−50…+50) — pan by assignable source 3 | `× 48/50` | cord → **Pan** | ±48 |
| `MODVLVOL` `0x5f` (−50…+50) — LFO1 depth control | `× 48/50` | cord → **LFO1 Amount** | ±48 |
| `MODVLFOR` `0x5e` (−50…+50) — LFO1 speed control | `× 25/50` | cord → **LFO1 Rate** | ±25 |
| `PANDEP` `0x1e` (0–99) — depth of **LFO2** | `round(clamp(v,0,99) × 32/99)` | **LFO2 Amount** | 0–32 |
| `LFODEP` `0x22` (0–99) — depth of **LFO1** | `× 32/99` | **LFO1 Amount** | 0–32 |
| `MWLDEP` `0x24` (0–99) — modwheel → LFO1 depth | `× 32/99` | Modwheel → **LFO1 Amount** | 0–32 |
| `PRSDEP` `0x25` (0–99) — aftertouch → LFO1 depth | `× 32/99` | Pressure → **LFO1 Amount** | 0–32 |
| `VELDEP` `0x26` (0–99) — velocity → LFO1 depth | `× 32/99` | Velocity → **LFO1 Amount** | 0–32 |
| `TRANSPOSE` `0x4b` (**−50…+50**) | `clamp(v, −24, +24)` | **Preset Transpose** | −24…+24 |

> **The "E4 parameter modulated" column is an inference, not a decompilation
> result.** It follows from the AKAI parameter's own meaning, corroborated by the
> destination scale (pan cords ±48, volume ±75, LFO-rate ±25). What the code
> establishes is the arithmetic and the scratch-struct offset; **which E4 cord
> slot each one lands in has not been traced** and is the remaining gap.

`0x59`–`0x60` is a **source/amount** structure: `0x55`–`0x58` hold source bytes
(which modulator, 0–255) and `0x59`–`0x60` the signed amounts. That is why the
signed fields are contiguous.

**A hypothesis of mine died here and the way it died is the useful part.** I had
grouped these by EOS's destination scale and suggested the grouping reflected
AKAI structure. It does not: `MODVLVOL` is an **LFO-depth** control sitting in the
same ±48 group as three **pan** controls. The scales are EOS's own per-destination
cord ranges — pan ±48, volume ±75, LFO-rate ±25, LFO-depth ±48 — so my four
groups describe the E4 side, not the AKAI side, and reading them as source
structure was reading the wrong end of the arrow. (Consistent with §139–§141: a
cord's full scale is its destination's own range.)

### What the importer silently drops

Three fields sit inside runs it *does* convert and are never read. Confirmed by
searching the disassembly for the corresponding stack offsets — none appear:

| AKAI parameter | why it is notable |
|---|---|
| `MODVLFOD` `0x60` — amount of control of LFO1 **delay** | same contiguous signed block as the seven that are converted |
| `PANDEL` `0x1f` — delay in growth of LFO2 | sits directly beside `PANDEP`, which is converted |
| `LFODEL` `0x23` — delay in growth of LFO1 | sits directly beside `LFODEP`, which is converted |

**So EOS carries both LFOs' rate and depth and neither of their delays.**

Also: `TRANSPOSE` is **±50 on the AKAI and clamped to ±24** here, so any program
transposed beyond two octaves is silently narrowed.

These are invisible to any agreement metric between two converters — both sides
write a constant and agree perfectly. (s3ked, who also supplied the names.)

### Two different kinds of "never read" — do not merge them

`0x1b K_LOUD`, `0x1c P_LOUD` and `0x20 K_PANP` are documented "Not used", range
0–0, and the importer does not read them either. **That is not the same
observation as the three above**, even though the disassembly says the same
thing about all six:

- for `0x1b`/`0x1c`/`0x20`, "never read" **agrees** with the parameter being
  absent — nothing is lost;
- for `MODVLFOD`/`PANDEL`/`LFODEL`, "never read" means EOS **drops a parameter
  the AKAI really has**.

**And the agreement on the first three is weaker than it looks.** Whoever wrote
EOS's importer very likely worked from Akai's published SysEx documents — the
same documents s3ked's table is transcribed from. So "EOS ignores the fields
Akai's doc calls unused" may be evidence that two parties read one document, not
evidence about the machine. It does rule out a transcription slip on the table's
side for those rows, since an error introduced there would not be mirrored in
E-mu's binary, but it cannot establish that the hardware ignores those bytes.
**Only the machine can.** (s3ked, who raised it against their own contribution.)

This is the shared-bias rule with a shared *source* rather than a shared method,
and it is harder to see: the two artefacts genuinely are independent objects — a
disassembly and a parameter table — while their provenance is one.

### Why the E4 names stop here

`%a5` is EOS's **in-memory voice structure**, and it is *not* the E4B file's
`vpar` layout. Checking two candidates against mpc2emu's `vpar` table gives
inconsistent offsets — the pan destination at `a5+44` would have to be `vpar[55]`
(a shift of 11) while the LFO1 destination at `a5+6` would have to be `vpar[42]`
(a shift of 36). **A single base offset does not satisfy both, so the structure is
a different layout, not a shifted one.** Until it is aligned, naming the
range-only rows would be guessing, and the table above says so rather than
filling the column in.

## The orchestrator, and what `%a5` actually is

`0x48934`-`0x48a0c` is the top-level import routine, and it corrects a claim made
earlier in this document.

```
  48940:  moveal %a1,%a5          ; a5 = the PRESET object being built
  4894c:  pea 0xf0 / jsr 0x31344  ; locate the AKAI S3000 program (type 0xf0)
  48994:  lea %fp@(-68),%a0       ; a0 = a 68-byte SCRATCH struct in THIS frame
  4899c:  moveal %a5,%a1
  4899e:  bsrw 0x47778            ; program-header converter
  489a8:  moveb %fp@(-66),%d0     ; = scratch[2] -- the KEYGROUP COUNT
  489b2:  loop:
            lea %fp@(-68),%a0     ;   the same scratch struct
            moveal %a5,%a1        ;   the same preset object
            bsrw 0x47f08          ;   keygroup converter, ONCE PER KEYGROUP
          addql #1,%d7 / cmpl / blt loop
```

Inside `0x47778` the assignment is `moveal %a1,%a4` / `moveal %a0,%a5`. The
caller passes `a1` = the preset object and `a0` = `&fp@(-68)`. **So `%a4` is the
preset and `%a5` is the caller's scratch struct — not a voice block, and not any
output structure.** The earlier note here guessed `%a5` was a "voice/zone
destination"; it is a **parse context**, 68 bytes, staging program-level values
for the per-keygroup pass that follows.

Two things fall out and both check:

- `scratch[2]` is the loop bound, and the conversion map has `scratch[2]`
  receiving AKAI `0x2a`, which mpc2emu's format doc names **number of keygroups
  (1-99)**. A program-level count becoming the voice count, used as the loop
  bound. Independent confirmation of that row.
- AKAI holds pan, LFO rates and the modulation depths **per program** while the
  E4 holds them **per voice**, so they must be staged once and applied N times.
  That is exactly what a scratch struct consumed in a loop is for.

### Why the rescaled values are not in the file

mpc2emu searched the preset header and the first six voice blocks for the
thirteen rescaler rows, under four rounding conventions, requiring two or more
distinct predicted values. **None matched**, and they control-tested the harness
on three known-good mappings (the volume law, and both LFO table paths) which all
found their targets — so the negative is real.

The structure above explains it. The rescales write to a **scratch struct**, and
what reaches the file is whatever `0x47f08` does with those values afterwards.
Some pass through unchanged — both LFO rates land in the file exactly as the
table produces them — and the rescaled ones evidently do not.

**So the thirteen rows are correct about the code and say nothing yet about the
file.** They are a real description of `0x47778`'s arithmetic and must not be
used to predict E4B bytes until `0x47f08` is traced. Six of them are additionally
untestable against that corpus at all: the source byte is constant across all 361
programs, so their only support is the code.

## Where the envelopes are NOT

**This function converts the AKAI program HEADER only.** Its buffer is 196
bytes and every source offset above is inside it. AKAI attack/decay/sustain/
release live in the **keygroups**, which follow the header, so the amp-decay
span question is *not* answered by this function and nothing above bears on it.

The sibling at `0x47f08` uses a 192-byte buffer filled by `0x47e48`, then walks
a structure in 24-byte steps (`lea %fp@(-158),%a5` / `lea %a5@(24),%a5`) calling
`0x2f880` per item. That is the more likely home of the per-keygroup conversion
and it has **not** been traced.

## The amp and filter envelopes — the keygroup path

AKAI envelopes live in the **keygroup**, not the program header, so they are
reached through the orchestrator's per-keygroup loop:

```
  0x48934  orchestrator      -> loops keygroups
  0x47f08  keygroup handler  -> reads a 192-byte keygroup, finds the four
                                velocity zones at keygroup+0x22 on a 24-byte
                                stride, flags empty ones, DE-DUPLICATES
                                identical zones, then per surviving zone:
  0x475b4  zone converter    -> dispatches to
  0x46fbc  envelope conversion
```

**EOS merges identical velocity zones.** `0x2fe78` compares two zones and the
duplicate is flagged out, so an AKAI keygroup with four identical zones becomes
one E4 zone rather than four.

### The amp envelope, written literally

```
  46fbc:  a4@(12) AKAI attack   -> 0x2f7c4 -> a5@(108)       Atk1 rate
  46fd8:  #127                  ->           a5@(109)        Atk1 level = 127
  46fce:  0                     ->           a5@(110), (112) Atk2 rate = 0, Dcy1 rate = 0
  46fdc:  #127                  ->           a5@(111), (113) Atk2 level = 127, Dcy1 level = 127
  46fe4:  a4@(13) AKAI decay    -> 0x2f7ec -> a5@(114)       Dcy2 rate
  46ff6:  a4@(14) AKAI sustain  -> 0x2f814 -> a5@(115)       Dcy2 level
  47008:  a4@(15) AKAI release  -> 0x2f830 -> a5@(116)       Rls1 rate
  4701a:  0                     ->           a5@(117..119)   Rls1 level, Rls2 rate/level
```

**`Dcy1 rate = 0` and `Dcy1 level = 127` are hardcoded constants.** This is the
"plateau shape" mpc2emu observed across every voice of EOS's own imports, and it
is not emergent — the importer writes it. An AKAI envelope has four stages and
the E4's has six, so EOS spends Atk1 on the attack, leaves Atk2 and Dcy1 inert at
full level, and puts decay/sustain on **Dcy2**.

### The four laws

| stage | AKAI source | conversion |
|---|---|---|
| attack | keygroup `0x0c` | table at **`0x303d0`**, 100 entries, index = clamp(v,0,99) |
| decay | keygroup `0x0d` | table at **`0x30434`**, 100 entries |
| sustain | keygroup `0x0e` | `round(clamp(v,0,99) × 127/99)` — proportional, no table |
| release | keygroup `0x0f` | **the same table as decay**, `0x30434` |

The filter envelope (`0x14`–`0x17`) is converted immediately after by the same
pattern.

```
  attack table 0x303d0 (0..89)
     0   0   0   0   0   0   0   0   0   0   0   0   0   0   0   0   0   0   0   0
     0   1   1   1   1   1   1   1   1   1   1   1   1   1   1   1   1   1   2   2
     2   2   2   3   3   3   4   4   4   5   6   6   7   9  10  11  12  13  14  15
    17  18  19  21  23  25  26  28  29  31  33  35  37  39  40  42  44  46  48  50
    52  54  56  58  60  62  63  65  67  69  71  74  75  77  79  81  83  85  87  89

  decay + release table 0x30434 (0..110)
     0   0   0   0   0   0   0   0   0   1   1   1   1   1   1   2   2   2   2   2
     2   3   3   3   3   3   3   4   4   4   4   5   6   7   8   9  10  11  12  14
    15  16  17  18  19  20  22  23  25  26  28  29  31  32  34  36  37  39  40  42
    44  46  48  50  52  54  55  57  59  61  63  64  66  68  70  72  73  75  76  78
    80  82  84  85  87  89  90  92  93  94  96  97  99 100 102 103 104 106 108 110
```

### Tested against EOS's own output

s3ked pointed out that this claim contradicts a mechanistic one made from the
corpus — that "EOS computes them over a fixed reference of about 29–30 dB" — and
proposed the discriminator: if the table is the whole mechanism, EOS's output
values must all be **members of the table**, and if something computes after the
lookup they will drift off it.

Across **2800 voices** of EOS's own AKAI import:

```
  PZT[4] Decay1 rate  : one distinct value, 0          -- the plateau, as written
  PZT[0] Attack1 rate : 30 distinct, ALL in the attack table, 0 outliers
  PZT[6] Decay2 rate  : 42 distinct, ALL in the decay  table, 0 outliers
```

The decay table holds 74 distinct values spread over 0–110. Forty-two distinct
outputs landing inside that set with no exception is not what post-lookup
arithmetic produces.

**So the table is the mechanism, and a ~30 dB reference — if it is there at all —
is a property of the table's CONTENTS, presumably of whatever generated it.**
That makes a 29.99 dB inference a correct statement about the table's *origin*
and a wrong one about the importer's *behaviour*. The distinction matters for a
reimplementation: copy the table, do not reconstruct the arithmetic.

The honest limit: a post-lookup transform that happens to be the identity on
every value in this corpus would be invisible to this test.

**So there is no span convention in EOS's importer, because the importer does no
time arithmetic at all.** Attack, decay
and release are table lookups and sustain is a proportion. Any attempt to derive
what "span" EOS assumed is deriving a quantity the code never computes — the same
answer the LFO rate gave, and for the same reason.

## Confidence, and what is NOT established

**High — read directly and checked against data:**

- the name converter and its character set
- the volume formula. It reproduces all nine observed byte-27 values, and
  mpc2emu reimplemented it against their own corpus: **363 of 363 presets
  match EOS's byte 27 exactly, zero differences**
- the generic rescaler `0x2f6b4` and the thirteen call sites' constants
- the LFO rate table, validated independently from the corpus at two call sites
- the module map and the `%a4 = header + 2` offset, pinned three ways

**Medium — mechanically extracted, spot-checked only:** the source/destination
columns of the conversion map. The extractor pairs a store with the nearest
preceding source load, clamp and table load, which is right where the idiom is
contiguous and wrong where the compiler interleaved.

**Low — do not build on:**

- **`0x48ab0` is probably not a conversion table.** Its values are not monotonic
  and do not look like a mapping. It may be a mis-pairing.
- ~~The `%a5` struct's identity.~~ **Resolved**: it is the caller's 68-byte
  scratch context, not an output structure. See the orchestrator section. The
  offsets are into that scratch struct and do not correspond to file offsets.
- Anything about the S3000 path. Only the `-200` frame function was read. Its
  parallel is located but not traced.

**Not yet looked at:** the amp-decay span convention, which is the remaining
question the importer's own arithmetic would settle.

### A methodological note that cost time on both sides

A search that cannot fail produces rows, and rows look like results. mpc2emu's
first corpus search for `dest == T[src]` returned dozens of hits that were all
offsets where the predicted value was *constant* and the field was that same
constant — every row true, no content. Filtering to "at least two distinct
predicted values" left three. The same shape sank a claim of this project's on
the same day (704 preset headers that were six distinct values), and it is why
`0x48ab0` and the `0x3B` row are marked unusable rather than reported: **two
points cannot distinguish two tables.**
