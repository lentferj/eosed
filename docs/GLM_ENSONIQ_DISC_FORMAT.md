<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# The Ensoniq disc→RAM link, and the envelope/cord verdict (GLM-5.3-Flash, 2026-09-21)

External session file, offline (no hardware, no disc — the plain EOS 4.70
image, disassembled independently). This answers the three stuck questions
directly, in the order of severity given. Every address is a load address;
file offset = address − `0x20000`.

## 1. The disc→RAM link is a raw copy — the offsets ARE disc offsets

A full-image search for stores to the wavesample fields settles it:

```
moveX …,aN@(208)   →  NONE. Only reads:
78ee2  moveb %a0@(208),%d1     ; the volume law 0x78edc
78ee6  tstb  %a0@(225)         ; its boost flag
78f16  moveb %a0@(221),%d0     ; the pan law 0x78f10
7b150  moveb %a4@(170),…       ; the zone builder, root key
7b15e  moveb %a4@(274),…       ; key low
7b16a  moveb %a4@(276),…       ; key high
```

**Nothing writes those offsets, anywhere in the image.** The wavesample
struct (`0x102b5b50 + index × 288`) is therefore filled by a **bulk copy of
the Ensoniq disc block**, and the offsets are literal disc-block offsets —
`+208` is the disc block's byte 208, not a value some loader computed.

The second, independent reason it has to be a raw copy is that the struct is
read **two different ways at once**:

* `+208` (volume), `+221` (pan), `+225` (boost), `+170` (root), `+274`/`+276`
  (key range) are read as **raw single bytes** — `moveb a0@(208)`.
* `+240`, `+248`, `+256`, `+264` are read as **4-byte packed groups** through
  the decoder `0x78cc4`, called four times in `0x79024` (`pea a4@(240)`,
  `(248)`, `(256)`, `(264)`).

A struct built field-by-field by a loader would hold decoded values in every
field, not a mixture of raw bytes and packed groups. The mixture is what the
disc looks like; the struct is the disc block, copied. This also explains
`ENSONIQ_ROLAND_IMPORT.md`'s "parameter bytes alternate with zeros" — the
packed groups are the interleaving, and the raw bytes are the fields the
format stores unpacked.

**Consequence for the corpus check that failed.** mpc2emu de-interleaved a
real instrument (dropped the zero bytes) and read the document's offsets from
the packed result, getting zero everywhere — and concluded the offsets were
not file offsets. The transform was the wrong one. The offsets are **raw**
disc offsets: read them from the un-de-interleaved block, not from the packed
one. `+208` volume, `+221` pan, `+225` boost, `+170` root, `+274`/`+276` key
range should all land on real values when read straight off the block. That
makes the whole Ensoniq table corpus-checkable now, the way AKAI's is.

## 2. The field decoder, and the pointer chain

`0x78cc4` (bitfield decoder), given a pointer to a 4-byte group `[b0 b2 b4 b6]`
(even offsets carry the data — the odd bytes are the zeros):

```
hi  = (b0 << 15) | (b2 << 7) | (b4 >> 1)     ; a 23-bit value
lo  = ((b4 & 1) << 3) | ((b6 >> 5) & 7)      ; a 4-bit value
```

The disc block's pointer is resolved one step further out: `wavesample+272`
is an index, fed to `0x78ca0`, which walks the pointer table at `0x10003620`
backwards (`396 − 4·i`). The file walker's 32-byte directory records (type
`+1`, count `+10`, pointer `+32`, established in `GLM_ENSONIQ_LOADER_TRACE.md`)
locate each block; the block bytes are what the wavesample array holds.

So the complete disc→RAM description, without tracing `0x78dcc` further, is:
**directory record `+32` names a block; the block's bytes are the wavesample
struct, raw, with the offsets above read straight and the `+240`-group fields
decoded by `0x78cc4`.**

## 3. Envelopes and cords: dropped, not converted

The channel builder `0x7bcdc` loops eight layers and, per layer, calls only
the layer walker `0x7bbe4`, which per wavesample calls only the voice builder
`0x7bb90` and the zone builder `0x7b0e0`. The zone builder writes the zone
geometry already in the document and nothing else. The voice builder `0x7bb90`
is the answer to the envelope question:

```
7bb90  jsr 0x51a18        ; create the voice (default setup)
7bbae  memset(a5@(156), 16, 0)   ; a 16-byte block zeroed
7bbbe  memset(a5@(172), 16, 0)   ; a second 16-byte block zeroed
7bbce  jsr 0x50c70(a5@(20))      ; default setup helper
```

**Two 16-byte voice blocks are zeroed; nothing reads any envelope, filter or
LFO value from the source.** The three writes you saw against AKAI's eleven
are these memsets and the default-voice helpers, not cord conversion. The
preset-header builder `0x7bd60` likewise writes only name, transpose and
volume (0); the zone builder writes bytes 0–14 and zeroes 15–21.

So the drop list is much larger than the field list, and it is now positive
rather than "not found": **EOS's Ensoniq importer converts zone geometry,
sample reference, root key, volume and pan, and drops envelopes, filters, LFO
and all cords.** This matches the Roland importer's shape (which also writes
zero volume), and it is the same answer for the Ensoniq half of the document's
"not established" list — they are not established because they are not there.

The one cross-check that would close it completely is naming the two 16-byte
blocks at voice `+156` and `+172` in the E4 voice layout — mpc2emu owns that
layout; if those two offsets are the two envelopes (or the cord blocks), the
"zeroed, not converted" reading is confirmed rather than inferred. It is a
one-line answer from their side, not a hardware session.

## What is still genuinely open

* The disc block layout itself — which fields are raw bytes vs. the
  `0x78cc4`-packed groups, and what the packed groups decode to — is now the
  one piece worth a disc, and it is checkable **from the Ensoniq corpus alone**,
  no K2000R/E4XT session: read a real instrument's block straight off and
  confirm `+208`/`+221`/`+274`/`+276`/`+170` at their literal offsets.
* Whether `+156`/`+172` are envelopes or cords (mpc2emu's E4 voice layout).

Everything else on the Ensoniq path is described. The blocker was the
disc→RAM link, and it turns out the link is identity.
