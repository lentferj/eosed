<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# The EOS Ensoniq loader, first trace (GLM-5.3-Flash, 2026-09-21)

External session, written up as its own file rather than into tracked docs.
`ENSONIQ_ROLAND_IMPORT.md` named the blocker precisely: its Ensoniq source
offsets (wavesample `+208`/`+221`/`+274`/`+276`/`+170`/`+225`, layer `+40`/`+42`,
instrument `+10`/`+66`) are offsets into a *representation the loader builds*,
and until that loader is traced, none of them can be validated against a disc.
This is a first pass at that loader. Nothing here changes a single claim in
`ENSONIQ_ROLAND_IMPORT.md`; it locates the machinery behind the wall and
establishes the first file-level facts.

Method: independent reproduction of the image with `eosflash` (not the session
copy), then `m68k-linux-gnu-objdump -b binary -m m68k:68020
--adjust-vma=0x20000`, file offset = address − `0x20000`. Verified against the
existing doc first: `Scanning Ensoniq device` at `0x772e0`, `S770 MR25A` at
`0x17064f`, `AKAI Sampler` at `0x42a70` — all present at their documented
addresses, so the two readings are of the same bytes.

## 1. The entry chain — and who actually owns the buffer

The conversion chain `0x7a534 → 0x7bf0c` documented in
`ENSONIQ_ROLAND_IMPORT.md` is **not** the top of the module. It is the tail of
one big function, and its argument list settles where the packed struct lives.

```
0x7a4b8  linkw %fp,#-520            ; the Ensoniq module ENTRY
7a4d8    push "PRST" ; jsr 0x19abdc ; -> the Ensoniq file-type tag lookup
7a4ea    jsr 0x7959c                ; locate/open, args (fp@8, fp@12, tag)
7a50e    lea %fp@(-516),%a1         ; THE PACKED-STRUCT BUFFER
7a51a    bsrw 0x7a1bc               ; the loader/scan: fills fp@(-516)
7a534    jsr 0x7bf0c                ; THE CONVERSION CHAIN — 5th arg = fp@(-516)
```

**The struct `ENSONIQ_ROLAND_IMPORT.md`'s offsets live in is this function's
own local buffer** (`fp@(-516)` … `fp@(-4)`, ≤ 516 bytes), filled by `0x7a1bc`
and consumed by `0x7bf0c(d6, d5, d4, d3, buffer, progress_cb)`. That is why a
corpus search at any disc base fails: the offsets are offsets into
`0x7a1bc`'s output, one indirection away from the disc. The document's
hypothesis — "EOS's loader parses the Ensoniq file into an in-memory
representation" — is confirmed at this address, not just plausible.

`0x7959c` is upstream of the conversion entirely: called with the "PRST" tag
result and the caller's first two arguments, returning 0 on success. Given its
position it is the *locate/open* step (find the named Ensoniq instrument on the
medium), not the parser — nothing below depends on that guess being settled.

## 2. `0x7a1bc` is the device scanner, not the reader

The 516-byte buffer is not filled in one read; `0x7a1bc` is a **scanner over
128 device slots**:

```
for d6 in 0..127:
    if 0x79210(d6): ...            ; "is there an Ensoniq instrument in slot d6?"
    if 0x795d0() != 0: d5++; ...   ; slot busy/occupied bookkeeping
    else: 0x78dcc(instrument_object, d6)   ; LOAD slot d6 from disc
```

where `instrument_object = 0x78c60()` — the same "fetch the Ensoniq instrument"
helper the preset builder calls. Its result accumulates in a **4-byte-stride
record list** (`lea %a3@(0,%d2:l:4)`), each record `{word slot_or_-1, word
slot}`, with a count at `a3@(512)` — so the scanner output is an array of
`{status, slot}` pairs capped at 128, then deduplicated at `0x7a392` (a
first-match-wins pass that overwrites earlier records with a later slot's
status). The progress callback receives `64 × done / total` — the
"Scanning Ensoniq device" percentage.

So the per-disc instrument loading happens inside **`0x78dcc`**, and the
per-slot chain it drives is:

```
0x7a0b8:  0x79f78(d6, d5, &fileid)        ; open the slot's instrument file
          0x79e04(d6, d5, &fileid, &hdr)  ; read a 56-BYTE FILE HEADER
          size check: actual_size >= hdr[+10]   (else reject)
          0x7afd0(slot, ..., hdr, fileid, callback...)  ; the file walker
```

## 3. The 56-byte Ensoniq file header — three facts

`0x7a0b8` reads a header into a 56-byte local and the walker consumes it.
Two facts established by instruction, not inference:

| header offset | what |
|---:|---|
| `+10` | a **long**: the expected byte size. `0x13e3b8` (the file-position helper) must be `>=` it, or the load is rejected. |
| `+14` | the **file name**, 17 bytes, run through `0x7af88` — ASCII 32..127 passes, anything else becomes a space. Sixteen characters plus terminator. |

Two details worth pinning:

* `0x7af88` (header name) and `0x7b094` (converter name) are **two different
  functions with the same ASCII filter**. `ENSONIQ_ROLAND_IMPORT.md` documents
  the latter reading struct `+10`; the former reads the file header at `+14`.
  One matching offset is a plausible neighbour, not a confirmation — this
  project's own rule, and here it now has a measured answer for the *file*
  side: the name is at **file header `+14`**.
* The size check direction matters for a converter: a truncated file is
  rejected, but an oversized header field is accepted — the reader reads what
  the header names and does not check a ceiling here (what the walker does with
  the size is not yet traced).

## 4. The file walker (`0x7afd0` → `0x7ae84`)

`0x7afd0` copies the 17-byte name from `header+14` into the object, then calls
**`0x7ae84`**, which walks the file's block records. The record fields it reads:

| record offset | use |
|---:|---|
| `+1` (byte) | a type code → `0x78c84` (maps to an E4-side object kind) |
| `+10` (long) | a count/length — copied into the built sample at `a5@(28)` |
| `+32` (long) | pointer — carried into the object at `a1@(52)` |
| `+40`, `+44` | loop start/end: `end − start + 12` with `+2` nudges gated by a flag — **this is where the "Adjust Akai/Ensoniq fractional loops" option reaches the Ensoniq path** (`0x7ae3c`: the option byte is read, `if >= 8: end += 2`, landing in `a5@(44)`) |

Then three builders per block: `0x7ad44` (the **E4 sample object** builder —
fills `a1@(52)` = source `+32`, `a1@(56)` word = flags/rate packed from source
`+36` and a 3-bit field at source `+52` shifted into bits 1-2/6-7/4 of
`a1@(58)`, `a5@(28)` = source `+10`, loop start/end at `a5@(36)`/`a5@(44)`),
`0x7ac24`, and `0x7a9c4`. The bit-packing at `0x7ad44` (three successive
`lsrl/lsll/orl` extractions of source byte `+52`) is the Ensoniq sample-format
flag byte being decomposed — the same flag whose bits drive Roland's
`(sample[58] >> 1) & 3` mono/stereo test in the sibling table, so its Ensoniq
counterpart is here at source `+52`, bits 0-3.

## 5. What this changes in `ENSONIQ_ROLAND_IMPORT.md`

Nothing yet, and that is the finding. What it *changes the plan for*:

1. The source offsets are offsets into the struct built by `{0x7ac24,
   0x7ad44, 0x7a9c4}` under the walker `0x7ae84` — **those three are the next
   trace targets**, in that order of expected payoff. `0x7ad44` is already
   half-read (sample side above); the wave *parameter* fields (`+208` volume,
   `+221` pan, `+274/276` keys) must be written by the one that handles
   wavesample records.
2. Once those are traced, every converter offset in the existing document
   becomes a *chain* of two offsets (disc → struct → zone), and the document's
   tables should be re-based to the disc the way the AKAI document could be
   only because AKAI skips the middle step.
3. The parallel with AKAI is now precise: AKAI's `0x4771c` "read the AKAI
   program into the buffer" is a flat file read; Ensoniq's `0x7a1bc` is a
   scanner-plus-loader. **The middle step is the difference between the two
   formats' tractability**, and it is exactly the middle step this file has
   started.
4. The K2000 reads Ensoniq discs too (its sniffer is format 3, checked against
   `CDR-1 (EPS).iso` in k2kremote's `ROLAND_IMPORT.md`). A second, independent
   reading of the Ensoniq instrument structure — if the K2000 reads the disc
   *directly*, the way it reads AKAI — would cross-check the EOS struct offsets
   from the other side. Nobody has traced that path yet; it is the cheapest
   independent validation of the whole Ensoniq half.

## 6. Method note for the next session

The two "no callers found" searches this trace needed (for `0x7a534` and
`0x7bf0c`) both came up empty against `bsrw`/`jsr`/table scans, and the entry
turned out to be a plain function *containing* the call — found by disassembling
outward from the documented string rather than by xref. In this image the
Ensoniq module has no function table; its regions are found by string
references, as AKAI's were. Budget for region dumps, not symbol search.