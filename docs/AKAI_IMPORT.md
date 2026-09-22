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

### Endpoints identified both ends — which is NOT the same as the formula being verified

> **Corrected 2026-09-21.** This heading read "Confirmed both ends", and the
> paragraph below it named `PRLOUD` and `PANPOS` together as statable "with full
> confidence". That conflates two different things. `PRLOUD`'s **formula** is
> checked against EOS's own output, 363/363. `PANPOS`'s formula is **read from
> the instruction stream and has never been checked against anything.** What is
> confirmed for pan is that both *endpoints* are identified — the AKAI parameter
> by name, the E4 field by its destination range. An identified source and an
> identified destination do not verify the arithmetic between them.
>
> This overstatement propagated: it is where mpc2emu's consolidated document got
> its "AKAI pan = Confirmed" bucket, which was corrected on review. Fixed at the
> source here.

| AKAI parameter (range) | formula | E4 parameter (range) |
|---|---|---|
| `PRLOUD` loudness `0x19` (0–99) | `clamp((v − 99) × 8 / 10, −96, +10)` | **Preset Volume** (−96…+10 dB) |
| `PANPOS` pan `0x18` (−50…+50) | `clamp(round(clamp(v,−50,50) × 64/50), −64, +63)` | **Pan** (−64…+63) |
| LFO1 Rate `0x21` (0–99) | `T[clamp(v,0,99)]`, table `0x48b24` | **LFO1 Rate** (0–107 observed) |
| LFO2 Rate `0x1D` (0–99) | same table `0x48b24` | **LFO2 Rate** (0–107 observed) |
| program name `0x03-0x0e` (12 chars, AKAI charset) | `charset[c]`, non-printable → space | **Preset name** (16 bytes, space-padded) |
| keygroup count `0x2a` (1–99) | direct | **voice count** |

`PRLOUD` and `PANPOS` both have **identified endpoints**: the AKAI side is named
independently, and the E4 side is pinned by the destination range (−96…+10 is
`E4_PRESET_VOLUME` and nothing else; −64…+63 is the pan byte).

They differ completely in what that buys:

- **`PRLOUD` — formula VERIFIED.** mpc2emu reimplemented the row and matched EOS
  on 363 of 363 presets, zero differences.
- **`PANPOS` — formula UNVERIFIED.** Instruction stream only. No corpus check, no
  hardware. The row could have the wrong rounding, the wrong clamp order, or the
  wrong scale constant and nothing here would show it.

The AKAI-side naming also carries the provenance caveat below: it may be EOS's
author and this project reading the same Akai document, not two independent
reads of the machine.

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

## How well each decoded law matches EOS's actual output

Every law in this document, checked against **363 presets / 2800 voices of EOS's
own AKAI import**. The agreement column is not the interesting one — it is 100%
everywhere. **The strength column is.**

### Conversion laws — these take an AKAI value in and produce an E4 value out

These can be wrong, so testing them means something.

| law | test | strength | agreement | distinct | P(chance) |
|---|---|---|---:|---:|---:|
| `header[27]` volume, input → output | **exact** | **definitive** | 100% (363/363) | — | — |
| `PZT[0]` Attack1 rate, input → output | **exact** | **definitive** | 100% (141/141) | — | — |
| `PZT[6]` Decay2 rate, input → output | **exact** | **definitive** | 100% (141/141) | — | — |
| `PZT[7]` Decay2 level, input → output | **exact** | **definitive** | 100% (141/141) | — | — |
| `PZT[8]` Release1 rate, input → output | **exact** | **definitive** | 100% (141/141) | — | — |
| `PZT[8]` Release1 rate ∈ decay table | membership | strong | 100% (2800/2800) | 49 | 2.4 × 10⁻⁹ |
| `PZT[6]` Decay2 rate ∈ decay table | membership | strong | 100% (2800/2800) | 42 | 4.0 × 10⁻⁸ |
| `PZT[0]` Attack1 rate ∈ attack table | membership | strong | 100% (2800/2800) | 30 | 3.8 × 10⁻⁷ |
| `header[27]` volume ∈ formula image | membership | moderate | 100% (363/363) | 9 | 2.8 × 10⁻⁵ |
| `PZT[7]` Decay2 level ∈ sustain image | membership | **weak** | 100% (2800/2800) | 20 | 7.2 × 10⁻³ |

Strength is read off `P(chance)`: **strong** below 10⁻⁶, **moderate** to 10⁻³,
**weak** above it, **definitive** for an exact input-to-output check. The
membership rows are superseded by the exact rows above them and are kept only to
show what the weaker test was worth before the sources arrived.

### Hardcoded constants — these take nothing in

**These are not laws and the 100% beside them is not a verification.** The
importer writes a fixed value into these fields regardless of the AKAI program,
so "does the output always equal that value" is a question whose answer was
already written in the code. It cannot come out any other way.

What the 2800 voices *do* establish is that the constant is **really the
constant** — that no other code path writes these fields, and that no AKAI
program on a 363-preset disc produced an exception. That is worth knowing and it
is why the rows are here. It is simply a different claim from "this conversion is
correct", and mixing the two in one column is what made this table confusing.

| field | value the importer writes | held across |
|---|---|---|
| `PZT[1]` Attack1 level | **127** (full) | 2800/2800 voices |
| `PZT[2]` Attack2 rate | **0** (instant) | 2800/2800 voices |
| `PZT[3]` Attack2 level | **127** (full) | 2800/2800 voices |
| `PZT[4]` Decay1 rate | **0** (instant) | 2800/2800 voices |
| `PZT[5]` Decay1 level | **127** (full) | 2800/2800 voices |
| `PZT[9]` Release1 level | **0** (silence) | 2800/2800 voices |
| `PZT[10]`/`[11]` Release2 rate/level | **0** / **0** | 2800/2800 voices |
| `header[26]` transpose | within −24…+24 | 363/363 presets |

**Read as a group these constants are the actual finding**, and a more
interesting one than any single row suggests: they are how a **four-stage AKAI
envelope is fitted into a six-stage E4 one.** Attack1 does the attack; Attack2
and Decay1 are pinned open — rate 0, level 127 — so they pass through instantly
at full level and contribute nothing; Decay2 carries decay and sustain; Release1
carries release; Release2 is closed off. Two of the E4's six stages are
deliberately neutralised, and `PZT[4] Decay1 rate = 0` is exactly the "plateau
shape on every voice" mpc2emu observed from the corpus without knowing why.

### The membership rows are now exact

mpc2emu supplied the source disc, and with it every envelope row becomes an exact
input-to-output check rather than a membership test.

**One trap, and it is caused by this importer's own behaviour: voice *i* is not
keygroup *i*.** The zone de-duplication at `0x47f08` breaks the correspondence, so
a naive positional comparison over all programs reports ~2% mismatches that are
purely alignment. **Restricted to single-keygroup programs the correspondence is
unambiguous**:

```
  141 single-keygroup programs, matched to EOS presets by name

    Attack1 rate            141/141   100.00%
    Decay2 rate             141/141   100.00%
    Decay2 level (sustain)  141/141   100.00%
    Release1 rate           141/141   100.00%
    TOTAL                   564/564   zero mismatches
```

Predicted straight from the AKAI keygroup bytes `0x0c`–`0x0f` through the
firmware tables, compared against what EOS actually wrote. **This has a
false-positive rate of zero rather than 2.4 × 10⁻⁹**, and it closes the loophole
the membership tests left open — a second transform whose image lies inside the
first would show here and does not.

mpc2emu ran the same comparison independently and got the same 564/564 from their
own implementation.

**Name matching needs one detail**: EOS writes the 12-character AKAI name into a
16-byte field followed by a NUL, so the field is not simply space-padded; cut at
the NUL before comparing or nothing matches at all.

## How mpc2emu's own converter compares to EOS

The other half of the question: not "did we decode EOS correctly" but "does an
independent converter agree with it". Measured by mpc2emu against the same
material, **disagreements included**, which is the half that carries the
information.

| field | method | corpus | result |
|---|---|---|---|
| preset volume (byte 27) | exact in → out | 363 presets | **363/363** after adopting the firmware formula |
| `filter_resonance` | identical bytes | 1122 voices | **100% identical** |
| pitch | frequency invariant, \|Δ\| ≤ 0.5 semitone | 2731 zones | **98.6%**; median 0.050, p95 0.300, signed mean +0.001 |
| zone counts | equal per preset | 359 presets | 336 equal, **23 differ** |
| `filter_cutoff` | median ratio | 1122 voices | ours **1.88× brighter** |
| `filter_env_cents` | median | 1122 voices | ours **0**, EOS **797** |
| amp env decay | median ratio | 1122 voices | ours 1.93× longer — **withdrawn, see below** |
| filter keytrack | median | 1122 voices | ours 0.000, EOS 0.118 |

**Four caveats that belong with the numbers rather than under them** (mpc2emu's,
and they asked for them to be carried):

1. **The 1.93× is withdrawn as a statement about EOS's conversion.** Both banks
   were read by *their* parser, and EOS's decay arrives as `Dcy1 rate 0` + `Dcy2`
   — the plateau this document shows is hardcoded — which their reader handles on
   a span-blind branch. It remains a real difference between two files as one
   parser reads them, and nothing more.
2. **The 23 differing zone counts are not a defect on either side.** They are the
   zone de-duplication described above.
3. **`filter_env_cents` ours-0 is a documented rule** (depth 0 means no filter
   envelope) meeting an importer that writes a sweep anyway. A disagreement, not
   a gap.
4. **Everything except volume and pitch is a median**, which hides the
   distribution.

## Everything the importer ignores

This is decidable from the code rather than inferable from output, so it is worth
stating completely: **every AKAI field the importer reads, and by complement
every one it does not.**

```
  program common (192 bytes): 49 offsets read
    00 03 18 19 1a 1d 1e 21 22 24 25 26 27 28 29 2a 3b 41 42 48 4b 4c 4d 4e 4f
    50 51 52 54 55 56 57 58 59 5a 5b 5c 5d 5e 5f 61 62 63 64 65 66 6e 6f 70
```

**The method has one trap and it is checked**: a field read through a *pointer*
would not appear as an individual read. Inside the converter the only pointer
bases into the buffer are `0x00` (the buffer itself, handed to the reader) and
`0x03` (the 12-character name). Everything else is an individual byte read, so
the complement below is real and not an artefact of how the search was done.

### Named AKAI parameters the importer drops

| AKAI field | what it is | notes |
|---|---|---|
| `0x0f` MIDI program number | performance routing | arguably not a preset parameter |
| `0x10` MIDI channel | performance routing | — |
| `0x11` polyphony | voice allocation | — |
| `0x13` `PLAYLO` / `0x14` `PLAYHI` | program play range | key ranges also exist per keygroup |
| `0x15` `OSHIFT` | octave shift (±2) | **a real pitch parameter, silently lost** |
| `0x16` `OUTPUT` | individual output assignment | — |
| `0x17` `STEREO` | stereo level (0–99) | sits directly beside `PANPOS`, which *is* converted |
| `0x1f` `PANDEL` | delay in growth of LFO2 | beside `PANDEP`, which is converted |
| `0x23` `LFODEL` | delay in growth of LFO1 | beside `LFODEP`, which is converted |
| `0x60` `MODVLFOD` | amount of control of LFO1 delay | same signed block as seven that are converted |
| keygroup `0x1e` | velocity-zone crossfade | the only named keygroup field not read |

`0x1b` `K_LOUD`, `0x1c` `P_LOUD` and `0x20` `K_PANP` are also unread, but those
are documented "Not used, range 0–0" — see the section above on why that is a
different kind of observation.

**So EOS carries both LFOs' rate and depth and neither of their delays**, and it
carries pan but not stereo level.

The keygroup side is otherwise complete: key range, tune offset, filter
frequency, and both the amp and filter envelopes are all read.

### The inverse question — what another converter keeps and EOS discards

Read from mpc2emu's parser source rather than supplied by them, so **provisional
until they confirm it**; their field list is theirs to state.

| AKAI field | EOS | mpc2emu | note |
|---|---|---|---|
| `0x17` `STEREO` stereo level | **not read** | read → dB, **applied** | applied with an extrapolation warning: the law was measured over 10–99 |
| `0x23` `LFODEL` LFO1 delay | **not read** | read → `lfo1_delay` seconds, **applied** | one of s3ked's three losses; the other converter keeps it |
| keygroup `0x08` filter keyfollow | **read** — builds a cord | read → applied | **corrected**, see the cord section |
| `0x0f` MIDI program number | **not read** | **applied** as the program number | arguably performance state, not a preset parameter |
| `0x15` `OSHIFT` octave shift | **not read** | read, **reported as dropped** | **neither side converts it** |
| `0x11` polyphony | **not read** | read, warning only | neither side converts it |

**So the answer to "does anything survive our path that EOS discards" is yes, and
`LFODEL` is the clearest case**: EOS drops both LFO delays, and mpc2emu carries
LFO1's. That is the mirror of s3ked's loss finding, running the other way.

**`OSHIFT` is the more interesting row.** Both sides read it and neither applies
it — two independent efforts looked at the same octave-shift parameter and both
deferred it. It is not a place either implementation has an edge; it is a gap
they share.

Two things needing mpc2emu's confirmation rather than my reading of their code:

- **Their `akai_program_scope_laws.md` says the goal is to settle laws "so
  `octave_shift`, stereo `LEVEL` and program `PAN` can be applied instead of
  reported", while the parser appears to apply stereo level already** (it feeds a
  gain sum and reports an `applied_db`). Either the document is stale or I am
  misreading the call path.
- ~~Their corpus reports filter keytrack as "ours 0.000, EOS 0.118"~~ —
  **that line of reasoning is dead**, see below. It rested on my claim that
  keygroup `0x08` is not read, which was wrong.

The EOS side of this table also carries one limit: the keygroup read set was
enumerated over the zone/envelope path (`0x46da8`–`0x475b0`). A keygroup byte
read in some other function would not appear in it, so "not read" is firmer for
the program header — where the whole converter was enumerated and its pointer
bases checked — than for keygroup `0x08`.

## Modulation cords — and a retraction

**EOS builds E4 cords from AKAI's per-keygroup modulation fields.** This was
missed at first because the cord amount is not written to a named field: it goes
into the modulation matrix as a `(source, destination, amount)` triple.

```
  46956:  tstb %a3@(8) / beq       ; if the AKAI value is 0, SKIP ENTIRELY
  4695c:  lea %a4@(0,%d7:l:4),%a5  ; 4-byte-stride slot in the matrix
  46962:  moveb #8,%a5@(188)       ; cord SRC = 8  = Key+
  46968:  moveb #56,%a5@(189)      ; cord DST = 56 = FilFreq
  46980:  jsr 0x2f6b4              ; round(clamp(v,-50,50) * 96/50)
  46986:  moveb %d0,%a5@(190)      ; cord AMOUNT
```

With `a5 = voice + 2` — the same base the envelope stores confirm — `a5@(188)`
lands at `voice[190]`, the start of the 20 × 4-byte modulation matrix.

| cord source | destination | scale | AKAI keygroup byte | written |
|---|---|---:|---|---|
| `Key+` | `FilFreq` | 96 | `0x08` | only if non-zero |
| `Vel+` | `VEnvAtk` | 48 | `0x10` | only if non-zero |
| `Vel+` | `VEnvRls` | 48 | `0x11` | only if non-zero |
| `RlsVel` | `VEnvRls` | 48 | `0x12` | only if non-zero |
| `Key+` | `VEnvRls` | 48 | `0x13` | only if non-zero |
| `Vel+` | `FEnvAtk` | 48 | `0x18` | only if non-zero |
| `Vel+` | `FEnvRls` | 48 | `0x19` | only if non-zero |
| `RlsVel` | `FEnvRls` | 48 | `0x1a` | only if non-zero |
| `Key+` | `FEnvRls` | 48 | `0x1b` | only if non-zero |

All use the same rescaler, `round(clamp(v, −50, 50) × scale/50)`, into the amount
byte.

### Which of the nine a corpus can actually check

All nine are read from the code with equal confidence — same rescaler, same
guard, source and destination as literal constants. **Their verifiability is not
equal at all.** Over the 2690 keygroups of the disc behind the reference import:

| cord | AKAI byte | distinct values | non-zero | corpus evidence |
|---|---|---:|---:|---|
| `Vel+ → VEnvAtk` | `0x10` | 14 | 310 (11.5%) | **yes** |
| `Key+ → FilFreq` | `0x08` | 10 | 201 (7.5%) | **yes** |
| `Vel+ → VEnvRls` | `0x11` | 5 | 84 (3.1%) | **yes** |
| `RlsVel → VEnvRls` | `0x12` | 2 | 28 (1.0%) | thin |
| `Vel+ → FEnvAtk` | `0x18` | 2 | 12 (0.4%) | thin |
| `Vel+ → FEnvRls` | `0x19` | 2 | 12 (0.4%) | thin |
| `Key+ → VEnvRls` | `0x13` | 1 | **0** *on this disc* | **see below — non-zero elsewhere** |
| `RlsVel → FEnvRls` | `0x1a` | 1 | **0** *on this disc* | none on any disc checked |
| `Key+ → FEnvRls` | `0x1b` | 1 | **0** *on this disc* | none on any disc checked |

**Three of the nine cannot be checked against this material at all**, because the
source field is zero on every keygroup — and the guard means EOS emits nothing
for them, so the output is equally silent. Three more rest on 12–28 keygroups
holding two distinct values.

**"Zero on this disc" is not "zero".** mpc2emu checked a different AKAI source
ISO — 13 programs, 205 keygroups — and found `0x13` reading **−5 on 17 of them**,
every keygroup of one program. Both counts are correct; they are different discs.
A prevalence without its corpus named is not a measurement, and the column above
now names one.

**That makes `0x13` testable end to end, which nothing here could do.** The
reasoning that it was unverifiable was sound *about this corpus*: EOS emits no
cord for a zero source byte, so EOS's own output can never exercise the row. It
was never a statement about the field. With a program that sets the byte, the
test is one import and one SysEx read:

```
  import that program on the E4XT through EOS's own importer,
  then read the voice's cords.

  a Key+ -> 0x4B cord with amount -5   -> this trace's reading is confirmed
  a cord with a DECAY destination      -> refuted; the AKAI field is the
                                          key->decay dependence its own
                                          documentation names
```

It needs an AKAI disc mounted and a front-panel import, so it is Jan's to
schedule, but it needs no measurement rig — three bytes of one cord decide it.

This does not weaken the *derivation*: these offsets come from instructions, not
from correlating fields against output, so a constant field cannot mislead the
read. It bounds the *verification*, which is a different thing and easy to
conflate when both are reported as "confirmed".

The check is one line — a distinct-value count per source field — and it comes
from mpc2emu, who found it auditing their own voice-window offsets. Their first
phrasing was *"a field that barely varies cannot identify its own offset"*; they
then sharpened it, on the strength of the rows above, to the form that actually
covers them:

> **A field that barely varies cannot identify anything downstream of it** — not
> the offset, not the destination, not the arithmetic.

The sharper form is the one that matters here. `0x1a` is not an offset problem:
its offset is a literal in the instruction stream and is not in doubt. What its
all-zero column cannot support is the *destination* and the *scale* that offset
feeds, and the first phrasing would have passed it.

Their velocity window is 94.4% `(0,127)` across 2530 voices, with its high byte
taking three distinct values in the entire corpus, so agreement there was
measuring the corpus's uniformity rather than anything about the field. Three
instances turned up in one evening — that window, the three all-zero cords above,
and the six of the thirteen header rescales whose source byte is constant across
361 programs.

### RETRACTED: keygroup `0x08` is read, and EOS does not invent key tracking

An earlier version of this document listed keygroup `0x08` among the fields the
importer ignores, and mpc2emu built a finding on it — that EOS writes key
tracking into programs which specify none, since 92.5% of that disc's keygroups
carry `0x08 = 0`. **Both are wrong.** EOS reads the field and, when it is
non-zero, emits a `Key+ → FilFreq` cord; when it is zero it emits **nothing**.
That is the opposite of inventing.

**The failure is worth more than the correction.** The original claim carried an
explicit caveat — that the keygroup read set had been enumerated over the
zone/envelope path only, so "not read" was weaker there than for the program
header. The caveat was correct, it was stated in writing, and then **both parties
reasoned from the claim as though it were established.** Resolving it meant
enumerating the rest of the importer, which took four minutes.

**A caveat the author states and then ignores is worse than no caveat**, because
it makes the limit look considered. The general form, in mpc2emu's words before
either of us acted on it: *"read from somewhere I did not enumerate" and
"invented" predict the same output, and nothing I have separates them.* Something
did separate them; nobody went and did it.

### Confirmed from the file end

mpc2emu traced their 0.118 to its source and it was their own reader: four of
their E4B cord reads **indexed a fixed slot** instead of searching for a
`(source, destination)` pair, and slot 6 is where *their writer's* template puts
`Key+ → FilFreq`. EOS's importer packs the matrix in a different order, so what
they sampled was this importer's **velocity → cutoff** depth
(`21/127 × 0.713 = 0.1179`).

With the cord searched for rather than indexed, the guard checks out against the
file:

```
  Key+ -> FilFreq present in the 2800-voice import :  195 voices = 7.0%
  source keygroups with non-zero filter_keyfollow  :              7.5%
```

**Emitted only where the source says something, and the prevalence matches to
half a percentage point.** Nothing is invented, and the decompiled guard is
confirmed independently of the decompilation.

Two things worth carrying from how that was found. Their first estimate of the
harm was **67.2%** and it was wrong in their own favour — it counted every voice
whose slot 6 was not exactly `Key+ → FilFreq`, but most of those hold `Key~`, the
same routing at a different pivot carrying the same depth. The honest figure is
**2.7%**, a 25× overstatement caught by asking what the count counted. And the
one-number error was the smaller half: the slot-indexing defect affects four
reads across every third-party bank they parse.

This also explains, from a second direction, why a search for the thirteen
rescaled program-header values found nothing in the header or the voice blocks:
several of them are **cord amounts**, which sit in the matrix beside a source and
a destination byte rather than at a named field offset.

## A provenance caveat that applies to this whole document

**Where a finding here agrees with Akai's published documentation, that
agreement is probably not independent evidence.** Whoever implemented EOS's AKAI
importer had to learn the format from somewhere, and the obvious somewhere is
Akai's own SysEx/format documents — the same documents every third-party field
table is transcribed from. So:

```
  Akai's doc  ->  a third-party parameter table      a transcription
  Akai's doc  ->  EOS's importer                     probably another one
  the AKAI's own firmware                            the thing being described
```

**A doc/firmware agreement is corroboration; a doc/EOS agreement may be
circular.** This bites specifically on:

- the **character set** at `0x31ba4` and its 12-character cap — EOS reading the
  name as 12 characters from program offset `+3` matches Akai's documented
  `PRNAME`, and that is two readings of one document, not two measurements;
- the **"not used" fields** `0x1b`/`0x1c`/`0x20` being unread, already noted in
  its own section;
- **every field name** in the mapping tables, which come from a transcription.

What EOS's firmware *does* independently establish is its own **arithmetic and
its choices** — the conversion tables, the constants, the clamps, and the drop
list. Those have no counterpart in Akai's documents and cannot have been
transcribed from them.

It also does one thing a document cannot: **it says how EOS's author read the
layout.** A disagreement between this trace and a field table would have been a
warning worth chasing. Agreement is weaker than it looks, and disagreement would
have been strong. (s3ked, who raised it against a corroboration this document
had claimed.)

## The AKAI source offsets ARE file offsets — unlike the other two importers

A later finding in `ENSONIQ_ROLAND_IMPORT.md` — that Ensoniq's source offsets
index EOS's in-memory structure rather than the disc file — was generalised into
a rule. **It does not apply to this document, and the exception is provable.**

The nine cords here read AKAI keygroup bytes `0x08`, `0x10`–`0x13` and
`0x18`–`0x1b`. mpc2emu's parser, written from library discs and with no knowledge
of this trace, independently places the **amp envelope at `0x0c`–`0x0f`** and the
**filter envelope at `0x14`–`0x17`**. Laid together:

```
  0x0c-0x0f   amp envelope        (their parser)
  0x10-0x13   four cords          (this trace)
  0x14-0x17   filter envelope     (their parser)
  0x18-0x1b   four cords          (this trace)
```

**Two blocks of four, each immediately following an envelope block, and the four
cords appear in the same order both times** — `Vel+`→attack, `Vel+`→release,
`RlsVel`→release, `Key+`→release. That regularity is a relation a wrong reading
cannot produce: a misplaced base would scatter the cords rather than land them
twice in the same pattern adjacent to two independently-located blocks.

So for AKAI the file is parsed directly — flat, no loader building an
intermediate — and **the source column of this document is checkable against a
disc**, which is why mpc2emu's corpus work on it succeeded where the same
approach failed on Ensoniq. (Observation theirs; the adjacency verified here.)

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

- ~~**`0x48ab0` is probably not a conversion table.** Its values are not monotonic
  and do not look like a mapping. It may be a mis-pairing.~~
  **RETRACTED 2026-09-22 — it is the `MODSFILT` enum map**, read at `0x47d54`.
  It is not monotonic **because an enum map is not monotonic**: it maps AKAI
  modulation-source selectors onto E4B source ids. The property used to dismiss
  it was the property that identifies it. See below.
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

## O7 ANSWERED: keygroup `0x13` is key → amp-envelope RELEASE (2026-09-22, live)

The one AKAI cord row no corpus could settle, because `0x13` is zero on the
reference disc and the guard means EOS's output is silent about it. Jan loaded a
disc whose 17-keygroup bass program carries `0x13 = -5` on **every** keygroup,
with the other six env-cord bytes zero throughout — so the imported preset can
carry only one cord from that family and there is nothing to confuse it with.

**Read back from the E4XT, identical on all 8 voices:**

```
  cord 7   SRC=8 (Key+)   DST=56  (0x38 FilFreq)   AMT=8
  cord 8   SRC=8 (Key+)   DST=75  (0x4b VEnvRls)   AMT=-4
```

**`0x4B` = `VEnvRls` = amp-envelope RELEASE.** Not `0x4A` (`VEnvDcy`, decay),
which is what AKAI's own documentation calls that byte.

**So the sibling project's writer has been right all along**, and the
documentation reading was wrong about what *this firmware* does with the byte.
Both outcomes were pre-registered, so neither side could adjust after the fact.

### The disambiguation is clean

Two `Key+`-sourced cords are present, and they are not confusable: `cord 7` goes
to `FilFreq`, which is the **`0x08`** routing (key → filter frequency, already
confirmed), and `cord 8` goes to `VEnvRls`, which is the `0x13` routing under
test. The six sibling bytes being zero is what makes cord 8 unambiguous.

### And a free data point: the scale

`0x13 = -5` on the disc produced a cord amount of **-4**. The scale of this
routing has never been measured — the destination was the whole question — so
this is recorded raw and uninterpreted. One source value and one amount does not
determine a law; a disc with three magnitudes in one volume would.

### The cord-amount scale, three positive points — and the asymmetry NOT measured

Read back from the same loaded bank, read-only, no import. **Only 6 of the
disc's 13 programs are in RAM**, and the program carrying keyfollow −24 *and*
+24 is not among them.

```
  Key+ -> FilFreq       from AKAI filter_keyfollow
     kf   4   ->   6
     kf   5   ->   8
     kf  12   ->  18

  Vel+ -> VEnvAtk       from AKAI vel_to_attack
     va  -5   ->   4      SIGN INVERTED
     va  -8   ->   6      SIGN INVERTED
```

`round(kf * 96/64)` reproduces all three keyfollow points exactly, and
`round(-va * 48/64)` reproduces both attack points. **96 and 48 are the scale
constants this document already records** for those two rows, so the fit uses no
free parameter beyond the divisor — but it is a fit to **three points and two
points**, from one bank, and it is recorded as that rather than as a law.

**The sign inversion on `vel_to_attack` is the substantive finding**: a negative
AKAI value produces a positive E4 cord amount, on both observations. A converter
copying the sign through would route the modulation the wrong way.

### What this does NOT answer, which is what was actually asked

The sibling project's conversion comment states that the negative keyfollow side
is corrected by a measured ~0.6× while **the positive side is "a real,
unresolved nonlinearity"**. Measuring that asymmetry needs values on both sides
of zero.

**All three keyfollow points here are positive.** The bank contains no negative
keyfollow at all, so this says nothing about the asymmetry — and a ratio of
exactly 1.5 on the positive side does not imply the negative side is 1.5. The
program with ±24 in one program remains the material that would settle it, and
it is on the disc but not loaded.

The **pivot** question — whether the E4XT's Key source pivots at note 64 as the
AKAI does — is not addressable by read-back at all. It needs audio at both ends
of the keyboard.

### The keyfollow cord law read from the firmware — and it does NOT match the fit

The cord-writing site, read rather than inferred:

```
  44644:  moveb %d0,%a5@(189)     ; cord DESTINATION
  44648:  pea 0x60                ; scale = 96
  4464c:  moveb %a3@(8),%d0       ; keygroup byte 0x08 -- the keyfollow
  44650:  pea 0x32                ; hi  = +50
  44654:  pea 0xffffffce          ; lo  = -50
  4465a:  movel %d0,%sp@-         ; value
  4465c:  jsr 0x2f6b4
  44662:  moveb %d0,%a5@(190)     ; cord AMOUNT
```

```
  amount = round(clamp(kf, -50, +50) * 96 / 50)      = kf * 1.92
```

### EOS clamps at ±50 — the knee question is answered

The sibling project's converter saturates `key_track_to_filter_amount` at 1.0
oct/oct, i.e. `kf = 12`, and asked whether EOS knees anywhere above that.
**It does not: EOS's only saturation is the clamp at ±50**, read as literal
`pea` operands. There is no knee at 12, 24, or anywhere below 50. Their
saturation is their own arithmetic running out, not a model of the machine —
which is what they suspected.

**This is answerable from the firmware alone**, independent of the disagreement
below, and it did not need the ±24 disc after all.

### And the firmware law contradicts the three measured points

```
  kf reported by the sibling project    4      5     12
  amount measured on the E4XT           6      8     18
  amount predicted by kf * 96/50        8     10     23
```

**None of the three matches.** And solving the other way gives non-integer
sources — 6/1.92 = 3.13, 18/1.92 = 9.38 — so no integer keyfollow produces 18
under this law at all.

`round(kf * 96/64)` fits all three measurements exactly, but **64 is not in the
instruction stream; 50 is.** So a fit that works has a divisor the firmware does
not contain, and the firmware's own divisor produces none of the observations.

**A `>> 6` hypothesis was proposed and is refuted.** The head of `0x2f6b4`, which
an earlier read of this function truncated away, sets the divisor explicitly:

```
  2f6b8:  movel %sp@(12),%d6->d1   value
  2f6bc:  movel %sp@(16),%d0       lo
  2f6c0:  movel %sp@(20),%d6       hi      <- the divisor
  2f6e4:  divsll %d1,%d7,%d7               <- divide by 2*hi
```

There is no shift by six. The divisor is the `hi` argument, so `96/50` stands.

**And the contradiction is harder than "the numbers differ".** Tabulating the
law over every integer keyfollow:

```
  kf   0  1  2  3  4  5  6  7  8  9 10 11 12
  amt  0  2  4  6  8 10 12 13 15 17 19 21 23
```

**6 and 8 are reachable — from `kf` 3 and 4, not 4 and 5. `18` is not reachable
from any integer keyfollow at all.** So at least one measured amount cannot have
come from this code path with any source byte whatsoever.

### The most likely cause is the image, not the law

The sibling project's `kf` values were read from a local 62.9 MB file. **The
image actually on the card is 36.7 MB.** They verified the two carry the same
*program count* — not the same *bytes*. Two of the three measurements being
off-by-one in `kf` (3 vs 4, 4 vs 5) is exactly what a different build of the same
library would produce.

This project cannot check it: the card is in the E4XT and not mounted here.
**Nobody should fit a scale until the source bytes come from the image that was
actually imported.**

**Something between the disc byte and `%a3@(8)` is unaccounted for.** The most
likely candidate, by the pattern this project has hit repeatedly, is that the
sibling's `kf` values are read from the **disc** while `%a3@(8)` is a byte in
**EOS's own buffer** — the same source-frame problem that has now appeared on the
Ensoniq, Roland and AKAI arms. **Not resolved, and not to be fitted around.**

### RESOLVED: the law was right, the measurement went through a rescaling instrument

The "impossibility" was an artifact of how this project measured, not of the
firmware or of the sibling project's parser. Both were correct throughout.

**There are two keyfollow cord sites** — `0x44632` and `0x46956`, the S1000 and
S3000 arms — and they are **identical instruction for instruction**: same guard
on `kg[0x08]`, same `SRC=8`, `DST=56`, same `scale 96, hi 50, lo -50`. So the
second-site hypothesis is confirmed in existence and refuted in content.

**The firmware stores** `round(clamp(kf, -50, +50) * 96/50)`.

**The SysEx cord-amount parameter is a ±100 field** — `_p(131 + cord*3, ...,
-100, 100)` in this project's own `eos/params.py` — while the stored cord byte
is ±127. So a read-back returns `round(stored * 100/127)`:

> **Divisor corrected from 128 to 127 (2026-09-22).** Every point below agrees
> under both, because they differ only where `stored * 100` crosses a boundary
> that 128 rounds down and 127 rounds up — `stored 96` being the first such
> value either project measured. See the enum-table confirmation below:
> **`/127` scores 12/12 and `/128` scores 8/12.**

```
  kf   firmware stores   x100/128   measured
   4         8              6           6
   5        10              8           8
  12        23             18          18
```

**All three exact.** And the composition is the punchline:

```
  96/50  *  100/128  =  1.5000  =  96/64
```

**That is why `96/64` fitted.** It was not a divisor hiding in the instruction
stream; it was the product of the firmware's law and the wire scaling, and it
fitted because it is the true end-to-end relation. Both "irreconcilable"
readings were the same relation seen from either side of an instrument.

### The shape

**Measured through an instrument that rescales, then compared against the
pre-instrument quantity.** The `-100, 100` range was in this project's own
parameter table the whole time — as visible as the front-panel `B123` was when a
0-based index was being read as 1-based.

The rule this adds to *audit the instrument*: **an instrument that converts units
is not neutral, and its conversion belongs in the comparison.** Declaring an
observation impossible should first ask what the observation passed through —
three points that cannot exist are better evidence of a transform than of a
firmware that cannot produce its own output.

## The keyfollow mirror and the vel_to_attack law, measured (2026-09-22, live)

Three volumes loaded by Jan, giving both keyfollow signs and the `vel_to_attack`
rail. Predictions were registered **in wire units** beforehand — through the
`x100/128` correction rather than against it — so the comparison sits on one
side of the instrument.

### Keyfollow: 17 of 17 exact, and PERFECTLY SYMMETRIC

```
  kf   -12   -7   -2    3    4    5   12
  wire -18  -10   -3    5    6    8   18      predicted
  wire -18  -10   -3    5    6    8   18      measured
```

**`kf +12 -> +18` and `kf -12 -> -18`**, in different volumes, on material the
correction was never fitted to. **EOS's keyfollow is symmetric: there is no
asymmetry to model.**

What that does *not* mean, stated because the sibling project asked for it in
advance: their `AKAI_KEYFOLLOW_NEG_SCALE = 0.622` measures **the S3000XL's own
tracking**, not EOS's conversion. A symmetric EOS does not refute it — it means
EOS does not model the sampler's asymmetry. Two different quantities, named as
different *before* the result arrived.

### vel_to_attack: scale 48, settled at four discriminating points

```
  va -50  ->  38      1:1 predicts 39,  x48/50 predicts 38      twice
  va -14  ->  10      1:1 predicts 11,  x48/50 predicts 10      twice
  va  -8  ->   6      both predict 6                            twice
```

```
  stored = round(clamp(va, -50, +50) * 48/50)
  wire   = round(stored * 100/128)          sign inverted
```

`48` is the constant already recorded for that row, so this confirms the
documented value and refutes the `1:1` alternative where the two differ most.
The `-8 -> 6` points independently reproduce a measurement taken yesterday from
a different disc.

### An absence that was an apparatus artifact

Five programs appeared to lack the predicted `kf -12` cord. The scanner broke
out of its voice loop at the first voice with no matching cord:

```python
  if not got and v > 0: break
```

**The cords were on voice 13**, past several empty voices, in every case. A
re-scan without the break found `-18` exactly where predicted.

**And the reasoning that nearly excused it was wrong.** Noting that the `-7`
programs were interleaved among the `-12` ones, this project argued a
truncation "would have to hit exactly the `-12` programs and spare both `-7`
ones, five times running" — and it did, because the `-7` programs carry their
cord on an early voice and the `-12` programs carry it on voice 13. **A pattern
that looks too selective for an apparatus fault is not evidence against one.**
The scan settled it; the argument about the scan did not.

### The two envelope rate tables, dumped — with width, count and direction READ

Requested for a firmware-simulation build. All three properties are read from
the indexing sites at `0x2f7c8` (attack) and `0x2f7ec` (decay/release), not
inferred from the address gap:

```
  2f7d0:  moveq #99,%d0          ; clamp 0..99, both tables identically
  2f7d8:  moveal #0x303d0,%a0    ; base
  2f7de:  andl #255,%d1
  2f7e4:  addal %d1,%a0          ; base + index        <- NO scaling: ENTRY = 1 BYTE
  2f7e6:  moveb %a0@,%d0         ; byte read           <- FORWARD: AKAI 0 -> table[0]
```

- **entry width 1 byte** — `addal` with no `:l:2` or `:l:4` scaling
- **100 entries each** — clamp `0..99`, and `0x303d0 + 100 == 0x30434` exactly,
  so the two tables are contiguous
- **index direction forward** — not reversed

```
T_atk  0x303d0  100 bytes
    0: 00 00 00 00 00 00 00 00 00 00
   10: 00 00 00 00 00 00 00 00 00 00
   20: 00 01 01 01 01 01 01 01 01 01
   30: 01 01 01 01 01 01 01 01 02 02
   40: 02 02 02 03 03 03 04 04 04 05
   50: 06 06 07 09 0a 0b 0c 0d 0e 0f
   60: 11 12 13 15 17 19 1a 1c 1d 1f
   70: 21 23 25 27 28 2a 2c 2e 30 32
   80: 34 36 38 3a 3c 3e 3f 41 43 45
   90: 47 4a 4b 4d 4f 51 53 55 57 59

T_dec  0x30434  100 bytes
    0: 00 00 00 00 00 00 00 00 00 01
   10: 01 01 01 01 01 02 02 02 02 02
   20: 02 03 03 03 03 03 03 04 04 04
   30: 04 05 06 07 08 09 0a 0b 0c 0e
   40: 0f 10 11 12 13 14 16 17 19 1a
   50: 1c 1d 1f 20 22 24 25 27 28 2a
   60: 2c 2e 30 32 34 36 37 39 3b 3d
   70: 3f 40 42 44 46 48 49 4b 4c 4e
   80: 50 52 54 55 57 59 5a 5c 5d 5e
   90: 60 61 63 64 66 67 68 6a 6c 6e
```

**Both are monotonic non-decreasing**, `T_atk` spanning 0…89 and `T_dec` 0…110.
`T_atk` is flat at 0 for its first 21 entries — so AKAI attack values 0–20 all
import as rate 0, and the first 21 source values are not distinguishable in the
result.

## Three corrections to the cord table (2026-09-22)

### 1. The sign rule is PER-SOURCE, and the table needs a sign column

`negl %d0` appears in exactly four blocks — `0x46998`, `0x469dc`, `0x46aa4`,
`0x46ae8` — and those are the four **`Vel+` (source 10)** cords. It is in none
of the `Key+` or `RlsVel` blocks.

**So the inversion belongs to the source, not the destination.** This matters
because this project's measurements looked like the opposite: twelve
`vel_to_attack` points all inverted, while O7's `Key+ -> VEnvRls` did not, and
the obvious theory — *"E4B envelope destinations are rates where AKAI's are
times, so envelope cords invert"* — fits all twelve and predicts that O7 inverts
too. **It doesn't.** The refuting measurement was in this document for hours.

*A theory that explains every point you have is not thereby right; it is
untested against the points you did not look at.*

The nine-cord table above is correct on source, destination and scale, and
**has no sign column. It needs one:** source 10 inverts, sources 8 and 13 do
not.

### 2. There is a TWIN emitter at `0x4430c` and it is NOT the AKAI arm

Same shape, same rescaler, same slot cursor, same destination constants,
reached only through a pointer at `0x1f901e`. **The AKAI arm is `0x4647c`**,
settled by call graph rather than by reading either block:

```
  0x4647c <- 0x473a6 in 0x46da8 <- 0x47650 in 0x475b4
          <- 0x47fea in 0x47f08 <- 0x489c0 in 0x48934
```

**This project read `0x44632` earlier and reported it as the AKAI keyfollow
cord.** It is the twin's. The constants happen to be identical, so nothing
derived from it was wrong — but the attribution was, and a block being
byte-identical to the one you wanted is not evidence that it is the one you
wanted.

### 3. `0x46942` is a CALL, and its cord IS a keygroup-byte row

Recorded as "a cord whose source is a runtime value in `%d6`, not a keygroup
byte". Read:

```
  468f4:  moveb %a5@(61),%d6      ; a SOURCE id
  468fc:  moveb %a3@(153),%d5     ; keygroup byte 0x99  <- the value
  46904:  moveq #80,%d0
  46906:  cmpl  %d6,%d0
  46910:  movel %d7,%d4           ; if source == 80 (FEnv+), capture this slot
  46912:  pea 0x60 / 0x32 / 0xffffffce    ; scale 96, hi 50, lo -50
  46920:  jsr 0x2f6b4
  4692a:  movel %d0,%d6           ; d6 is now the AMOUNT
  46940:  moveq #56,%d0           ; destination FilFreq
  46942:  bsrw 0x46370            ; a SHARED emitter, not an inline write
```

**`%d6` is the amount, not the source.** The source is `%a5@(61)`, and the
converted value is `%a3@(153)` — **keygroup byte `0x99`**. So this is a
keygroup-byte row after all: `kg[0x99] -> FilFreq, scale 96`, with a
runtime-determined source id.

The gate capture is conditional on that source id being **80 (`FEnv+`)**, which
is what later feeds the computed-destination cord at `0x46bb0`.

**Not read:** what structure `%a5` is here, so `%a5@(61)` is "a source id" and
nothing more. Stated as a limit rather than guessed.

## The MODSFILT enum map, found: `0x48ab0` is a conversion table after all

The blocker on the assignable mod-matrix cords was never an address — it was the
map from an AKAI modulation-source selector to an E4B source id. **It is in the
firmware and it was already in this document, dismissed.**

```
  47d42:  tstl %d1 ; bpl           ; negative -> 0
  47d4a:  moveq #14,%d0            ; clamp to 14
  47d54:  moveal %a4,%a0           ; a4 = 0x48ab0, loaded at 0x47a08
  47d5c:  addal %d0,%a0            ; base + index, 1-byte entries
  47d5e:  moveb %a0@,%d7
  47d60:  moveb %d7,%a5@(59)       ; -> the staged source id
```

```
  src_id = TABLE_0x48ab0[ clamp(MODSFILT, 0, 14) ]
```

and the table decodes **entirely** into known E4B sources:

```
  sel   id   name          sel   id   name
    0    0   Off             8  105   Lfo2+
    1   17   ModWl           9   72   VEnv+
    2   16   PitWl          10   80   FEnv+     <- the gate id
    3   18   Press          11   17   ModWl
    4   20   MidiA          12   16   PitWl
    5   10   Vel+           13   20   MidiA
    6    9   Key~           14   88   AEnv+
    7   97   Lfo1+
```

**Not one entry falls outside `CORD_SOURCES`.** Selector 10 mapping to 80 is
exactly the gate condition at `0x46910`, which is independent confirmation that
the table and the emitter are the same mechanism.

### It confirms the sibling project's enum reading

Their parser carries `5 = velocity, 8 = LFO2, 10 = env2`, observed on two
programs and flagged as *possibly one library's common template rather than a
fixed convention*. The firmware agrees at all three: `5 -> Vel+`, `8 -> Lfo2+`,
`10 -> FEnv+`. **Their convention is EOS's convention**, and the remaining
twelve entries are now available rather than needing a corpus hunt or rig time.

### The dismissal was the identification

This document had `0x48ab0` under *"Low — do not build on: its values are not
monotonic and do not look like a mapping."* Both observations were correct. **An
enum map is not monotonic and does not look like a mapping** — it looks like
noise, because it is a permutation of unrelated ids rather than a curve.

**The property used to rule it out was the property that identifies it.** The
other tables nearby are rate and level curves, so "not a curve" read as "not a
table" — a classification inherited from its neighbours rather than tested
against what it could be.

### The staging struct `%a5`, partially mapped — what the seven unmodelled blocks read

The sibling project's remaining blocker is that seven blocks at `0x46582`…
`0x4675c` take both source id and amount from the staging struct rather than
from keygroup bytes. **`%a5` is the caller's 68-byte scratch context** — already
resolved in this document — and every offset in play (33, 34, 50, 53, 59, 60,
61) fits inside it.

Three of those fields are now read:

```
  46efc:  clamp d7 to [-72, +24]
  46f0e:  moveb %d7,%a5@(33)          ; COARSE TUNE, not volume -- see below

  46f14:  sign-preserving mask to 63
  46f2a:  moveb %d0,%a5@(34)          ; +-63, pan-shaped
```

**`%a5@(53)` has two paths, selected by the stereo test:**

```
  46f34:  moveb %a0@(58),%d0          ; the SAMPLE's byte 58
  46f38:  lsrl #1 ; andl #3
  46f42:  subql #3                    ; (sample[58] >> 1) & 3 == 3 ?

  STEREO:
  46f46:  moveb %a3@(44),%d0          ; kg[0x2C]
  46f4c:  sign-preserving >> 1        ; halved
  46f5a:  moveb %d0,%a5@(53)

  MONO:
  46f60:  moveb %a2@(18),%d0          ; the SAMPLE's byte 18
  46f68:  jsr 0x2f784                 ; a helper
  46f70:  moveb %a3@(44),%d1          ; kg[0x2C]
  46f7a:  addl %d1,%d0                ; SUM of the two
  46f74:  pea 0x20 / 0x40 / 0xffffffc0   ; scale 32, hi +64, lo -64
  46f88:  jsr 0x2f6b4
  46f8e:  moveb %d0,%a5@(53)
```

So the mono path **sums a sample-derived value with a keygroup byte** and
rescales at `hi = 64` — the only `hi = 64` in the AKAI arm, and the first field
found here that mixes sample and keygroup data.

**And `(sample[58] >> 1) & 3 == 3` appears here too**, the same test as the
Roland arm's pan force-to-zero. It is a shared stereo idiom across importers,
not a Roland-specific one.

~~**`%a5@(50)` is NOT read.** No byte-width write to it was found in the AKAI
region; it may be written at another width or through a different register.
Stated as a gap rather than guessed, since the seven blocks need it.~~

> **RETRACTED — it was found, by `head`.** `0x47cc8: moveb %d1,%a5@(50)`, in the
> program-header converter, fed by **the same `0x48ab0` enum map**:
>
> ```
>   47cba:  clamp(selector, 0, 14)
>   47cbc:  moveal %a4,%a0        ; 0x48ab0
>   47cc4:  addal %d0,%a0
>   47cc6:  moveb %a0@,%d1
>   47cc8:  moveb %d1,%a5@(50)
> ```
>
> **So the seven unmodelled blocks are the program's own mod-matrix slots and
> their sources come off the map already in hand.** Only the amount side
> remains.
>
> The search was correct and **the output was truncated**: 17 lines matched and
> `head -12` printed twelve. `0x47cc8` was line fifteen. The same truncation hid
> the header converter's own writes to `(33)`, `(34)` and `(53)` at `0x47a1a`,
> `0x47a66` and `0x47ce6` — the writes that matter most, since the keygroup-pass
> copies this project did read are the later ones.

### Every truncation applied for readability became a claim about the data

Fourth instance today, and the first in a **search** rather than a read:

```
  tail -20 on 0x2f6b4        cut the head that set the divisor
  a window starting 0x1714e4 began 0x18 bytes after the pan force-to-zero
  a voice loop breaking early missed cords on voice 13
  head -12 on a 17-line result reported a byte as absent
```

**`head`, `tail` and an early `break` are not display choices when their output
becomes a finding.** Each was applied to keep a message readable and each turned
into "this is not there". The rule that covers all four: **a negative from a
search is a claim about the search** — so state the match count, not the matches.

### `%a5@(33)` is Coarse Tune, not volume — and the range IS the identification

This document read `-72..+24` as "dB-shaped". **`-72..+24` is exactly the E4B
Coarse Tune range**; preset volume is `-96..+10`, which differs at both ends.

That matters beyond one field, because **the range match is how `header[27]` was
pinned as the volume field in the first place** — *"−96…+10 is exactly
`E4_PRESET_VOLUME`'s range, which is the corroboration that the destination is
the volume field rather than something that merely fits in a byte."* The same
test, applied here, points at tuning and was not applied.

**When a clamp looks like a known field's range, check it against the format
doc before naming it.** `%a5@(34)`'s sign-preserving `±63` is Pan, and that one
stands.

## The `0x48ab0` enum table CONFIRMED on hardware (2026-09-22, live)

250 AKAI programs imported by Jan across four volumes, chosen by the sibling
project for **selector coverage rather than convenience** — all 11 selectors
that occur in a 163-volume corpus. Predictions written to disk **before any
read-back**, keyed by preset name, with both stored and wire values.

The discriminating power is entirely in the rare rows: selectors 5 and 10
account for **1112 of 1482 occurrences**, so a wrong table would pass on the
bulk. Selectors 2 and 11 occur **once each in 250 presets**.

```
  preset          selector   expected      measured        verdict
  VEL SAMP+HLD        2      PitWl  16     PitWl  16       OK
  M.WHL FLTMOD        7      Lfo1+  97     Lfo1+  97       OK
  WV BELLSWEEP       14      AEnv+  88     AEnv+  88       OK
  SEQ LINE #4        11      ModWl  17     ModWl  17       OK
  SOFTMT MWCS         4      MidiA  20     MidiA  20       OK
  MUTE 21CS           4      MidiA  20     MidiA  20       OK

  source ids: 6 of 6 presets correct, 0 wrong
```

**`src = TABLE_0x48ab0[clamp(MODSFILT, 0, 14)]` is measured, not inferred.** And
selector 11 returning the same id as selector 1 confirms the table's
**duplicate rows are real** rather than a transcription artifact.

### The amounts corrected the wire divisor

```
  x100/127   12/12
  x100/128    8/12
```

`stored 96` is the first value either project had measured where the two differ,
and it appears three times here. **The divisor is 127.** Every earlier
measurement remains correct — they agree under both.

### And a value that was going to cost a card swap

`SEQ LINE #4` carries `Key+ 36` — **keyfollow 24**, twice the previous maximum,
and `24 * 1.5 = 36` exactly. Both projects spent an afternoon arranging to load
a disc for the `+-24` pair; it arrived incidentally in material loaded for an
unrelated purpose. **Coverage chosen for one question answered another**, which
is an argument for picking material by spread rather than by target.

### What this does not settle

It tests the **table**. Not the seven program-level slots, whose amounts remain
staged out of reach; and not slot ordering, since those seven run first and
shift the base — **a sim/device diff must align on `(src, dst)`, not on slot
number**, or every cord of an affected voice reports as misplaced.

### The "26/27" residual: a prediction counted as a measurement

The sibling project scored both wire divisors against "all 27 measured
(stored → wire) pairs we jointly hold" and reported `127` at **26/27**, with the
one failure at `va = -17 -> wire 12`, hypothesising a one-digit slip in reading
the source byte and offering to check the ISO.

**No such measurement exists.** Every `VEnvAtk` wire value this project has ever
read is 2, 4, 6, 10 or 38:

```
  va   -3  stored  3  wire  2
  va   -5  stored  5  wire  4
  va   -8  stored  8  wire  6
  va  -14  stored 13  wire 10
  va  -50  stored 48  wire 38      5 distinct pairs, 9 observations
```

`va -17 -> 12` is **the `x48/50` column of their own discrimination table** —
the table they sent to separate the two candidate laws. It is a predicted row
that never had a measurement to agree or disagree with.

So the residual does not need explaining and the ISO does not need reading:
**the score is 26/26, and the 27th point was never an observation.** `127` is
unrefuted across everything actually measured.

**The shape:** a prediction table and a measurement set were merged, and the
merged set was then used to score the thing the predictions were derived from.
Every row looked like data because every row had the same columns. **A table's
provenance is not visible in its shape**, which is why the two should not share
a container — and the tell was that it claimed twelve `vel_to_attack` pairs
where only five distinct ones were ever read.

### The complete measured keyfollow set, stated so it can be checked

Asked directly whether any further points in the sibling project's set were not
this project's measurements. Enumerated from the logs rather than recalled:

```
   kf  wire  /127  /128   where measured
  -12   -18   -18   -18   4 string programs, voice 13
   -7   -10   -10   -10   STRING PAD, STRNG PAD CH
   -2    -3    -3    -3   MELLOW LEAD, MELLOW TWO
    3     5     5     5   AIRVOICE ONE, GENTLE WINDS/TWO, WRM.SYNSTRGS
    4     6     6     6   CS PIANO-L, GENTLE WINDS/TWO
    5     8     8     8   EL-BASS REZ1, VS FANTASY
   12    18    18    18   SOLDANO 12 B, AIRVOICE ONE, VS FANTASY
   24    36    36    36   SEQ LINE #4
```

**Eight distinct pairs where both sides are held.** `kf 14 -> 21` is not among
them; it was the second phantom row, from the same pre-registration table as
`va -17`.

**No keyfollow point discriminates the divisors.** All eight agree under `/127`
and `/128` — the divisor rests entirely on the three stored-96 cord amounts.

**One unpaired measurement:** `WV BELLSWEEP` carries `Key+` at wire `-13`, and
this project does not hold its source keyfollow. It is a usable ninth point to
whoever can read that byte, and is recorded as unpaired rather than dropped.

### Why the count check works, and where it was available

The tell was arithmetic: twelve `vel_to_attack` pairs claimed against five ever
read, and eight keyfollow pairs against seven. **Ask the measurer how many
distinct points they hold before scoring anything against a table** — it costs
one question and catches the whole class, and neither project ran it in either
direction.

### `%a5@(53)` re-read in full, because the sibling project cannot check it

They flagged this as a claim they have no way to verify and will take on faith.
Re-read completely rather than left as first stated. **Two corrections to this
project's own account.**

**1. The "helper" is not a black box.** `0x2f784` was named and not read:

```
  2f788:  pea 0x40 / 0x32 / 0xffffffce    rescale(v, -50, +50, scale 64)
  2f798:  bsrw 0x2f6b4
  2f7a4:  then clamp the RESULT to [-64, +63]
```

```
  helper(v) = clamp( round(clamp(v, -50, 50) * 64/50), -64, +63 )
```

So the mono path is fully expanded, with no unread step:

```
  a5@(53) = rescale( helper(sample[18]) + kg[0x2C], -64, +64, scale 32 )
```

**2. There are THREE writers, not two.** Counted rather than listed:

```
  matches: 3
    46f5a   the STEREO branch
    46f8e   the MONO branch
    47ce6   the PROGRAM-HEADER converter
```

`0x47ce6` is the write that `head -12` hid earlier, and this project had not
noticed it applies to the same field. **The ordering between the header
converter's write and the keygroup pass's two is NOT established** — whichever
runs later wins, and which that is has not been read.

**So the two-branch law is the keygroup pass's behaviour, not necessarily the
final value of the field.** Stated as a limit, because the project relying on it
cannot discover the limit themselves.

### Where checking-your-own-side stops working

The habit that caught the unscoped offset list and the phantom measurement was
the same one: **check your own side before acting on the other side's framing.**
It worked both times because the receiving side held the primary source — logs
on one side, ISOs on the other.

**Where the receiver does not hold the primary source, it cannot fire.** Only
this project has the EOS image; only they have the AKAI corpus. Claims crossing
in those directions get no second reading, and are the ones worth re-reading
before sending rather than after being asked.
