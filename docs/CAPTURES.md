<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# What the E4XT recordings are

**The recordings themselves are not in this repository.** They live on the bench
machine under `~/temp/e4xt_ref/`, roughly 4 GB of WAV captures across a dozen
sets, and they cannot be re-made: several are of machine states — pre-fix
converted banks, a disc that has since been overwritten — that no longer exist.

This file is the record of *what* was measured, under *which* conditions, and
which sets are still valid. It is tracked because `RESOLUTION_NOTES.md` reasons
from these captures throughout and a reader cannot check that reasoning against
a description that lives only on one bench. The capture drivers and the rig
harness are bench-local and deliberately not distributed.


Written 2026-08-25 because a sibling project could not identify them by filename
and they cannot be re-made: two of the three sets are of a machine state that no
longer exists.

## Common capture conditions — reproduce these or the sets are not comparable

    note-on velocity 100, hold 3.0 s, note-off, tail 8 s (14-16 s in `ab/`)
    0.5 s of pre-roll before note-on, used as the noise-floor reference
    same audio interface, same gain, untouched across every set below
    E4XT output pair, no external processing
    analysis: 10 ms RMS windows, dBFS relative to full scale

**The gain held from 2026-08-24 17:00 until 2026-08-30 11:58, when it was
changed deliberately — see "Gain generations" at the end of this file.** Every
set described below belongs to the FIRST generation. Anything captured after
that timestamp is 9.27 dB quieter and is not directly comparable on level.

## `preerase/` — 2026-08-24 17:00-17:12, THE ONLY RECORD OF THE PRE-FIX STATE

Notes 26, 40, 52, 64, 72, 84. Whole preset, no voices muted.

| prefix | what it is |
|---|---|
| `pc22_` | the **reference preset** — a hand-built library preset, the thing the conversion was being compared against by ear. Releases in 0.02-0.20 s: its samples carry loop-in-release clear, and it was never imitating the source machine. **Not ground truth for a release** (§71). |
| `pc36_` | the conversion **as Jan auditioned it** — five of its six voices bound to the reference bank's samples by the merge (§66, §67). This is the state the "release is too short" verdict describes, and it cannot be recreated: it required two banks resident whose collision has since been removed. |
| `clean_` | the same conversion **loaded alone**, so its voices bind to its own samples. Same file as `pc36_`, correct bindings, release byte still 69. |

## `ab/` — 2026-08-24 18:58-19:00, the recalibrated conversion

Release byte 80 instead of 69, read back off all three sustaining voices before
capture. `full_n*` are whole-preset at the same six notes as `preerase/`, so they
compare directly against all three sets above. `env_*` are single sustaining
voices with the partner muted, for rate fits rather than listening. §71.

## `keyrel_clean/` — 2026-08-24 17:07-17:09, per-keygroup release measurement

Partner voice muted in each pair, three notes per keygroup. Measurement material,
not listening material: §69 and §73 were computed from these.

## What is missing, and what would make a baseline

There is **no recording of the source machine**. Everything here is the E4XT.
A source-side capture at the same six notes and the same conditions would make
the pair a baseline any future converter change could be tested against without
touching hardware — but see §70's caveat before treating a difference as an
amplitude error.


---

## Gain generations — read this before comparing any two files

There are now **two** gain generations in this archive, and level-based numbers
cannot be compared across the boundary without correcting for it.

**THE BOUNDARY IS E4XT-ONLY.** What changed is the E4XT's own output level, in
its analogue path. The AKAI and the K2000 are recorded through different
capture ports (`system:capture_13/14` and `17/18` against the E4XT's `15/16`)
and were not touched. An `akai_*` or `k2000_*` file captured tomorrow is at the
same gain as one captured last week — those two machines have ONE generation,
not two, and no correction applies to them ever.

| generation | machine | when | prefixes | level |
|---|---|---|---|---|
| **G0** | E4XT | 2026-08-22 and earlier | `e4xt_*`, `e4xt_s1*` — **the conversion-matrix baseline behind RESULTS.json** | ~16 dB below G1, NOT cleanly correctable — see below |
| **G1** | E4XT | 2026-08-24 17:00 → 2026-08-30 11:58 | everything in this directory, plus `sp_e4xt*`, `sp_full*`, `cd1v2_*`, `sw_*`, `v3_*`, `cd3krz_*` | reference |
| **G2** | E4XT | from 2026-08-30 11:58 | `cd3krz2_*`, `v127chk_*`, and every E4XT capture after | **−9.27 dB** |

### G0 exists, and finding it cost a wrong conclusion

The line at the top of this file said the gain had not been altered since
2026-08-24 17:00. That is true and it does **not** cover the 22 Aug captures,
which predate it — and those are the ones RESULTS.json's whole baseline is
built from. Assuming they belonged to G1 produced a confident, wrong claim
that a converter had regressed by 15 dB.

**The test that settled it, and the one to reach for again:** the E4B reference
bank at PC 0-9 is *unchanged* material captured in both the 22 Aug baseline and
the 28 Aug pass. Same presets, verified by comparing tracked f0 per note. Any
level difference between those two captures is gain, because nothing else about
them differs. It came out at **+16.4 dB median** — the same size as the "15 dB
regression" seen on converted material. **An unchanged control captured in both
epochs is what distinguishes a converter change from a bench change**, and the
sibling session's byte-for-byte diff of the two written files said the same
thing independently.

**G0 is not correctable by a single number.** The anchor's ten presets spread
over 9.2 dB (+10.5 to +19.7), so there is no scalar that maps G0 onto G1. Part
of that is likely the 0.8 s note gap those captures used — a previous note's
tail still decaying into the next note's window, which `measure.py`'s own
comment records as contaminating 14 of 136 E4XT pre-rolls before the gap was
raised to 3.0 s. So G0 is both quieter and dirtier.

**Therefore: no level-based comparison against the 22 Aug baseline is safe**,
with or without a correction. Ratio-based measures are unaffected and remain
valid across all three generations — sustain ratio, decay in dB/s, third-octave
distance, cents, anything referenced to a file's own peak or noise floor. Every
conclusion drawn from those stands.
| — | S3000XL | unchanged throughout | `akai_*`, `sp_akai*` | no boundary |
| — | K2000 | unchanged throughout | `k2000_*` | no boundary |

A cross-machine comparison therefore spans the boundary on one side only: an
E4XT G2 file against an AKAI file needs the +9.27 dB applied to the E4XT side
alone. Applying it to both would reintroduce exactly the error it removes.

### Why it changed

The E4XT was **hard clipping**. On the KRZ→E4B material four of seven captured
programs hit digital full scale, the worst with 65332 samples pinned there and
761 runs of three or more consecutive — the signal squared off, not merely
grazing the ceiling. Jan heard it before any measurement flagged it.

Jan reset the output level by ear on 2026-08-30 11:58, against the
worst-clipping patch held live (the organ preset at slot 3, note 36 — 20776
clipped samples, the worst of its four notes), with the selection verified on
the machine's own LCD first.

### Why the figure is measured rather than recorded

**The change is not in any device parameter.** `MASTER_HEADROOM` (185) is still
6 and `MASTER_HCHIP_BOOST` (186) is still 1 — the +12 dB output boost is still
on — so the adjustment was made in the analogue path and there is nothing to
read back. The only way to pin the generation is to measure it.

Two programs did not clip in G1, so their G1 peaks are trustworthy anchors:

    program 1   -0.04 dBFS (G1)  ->  -9.31 dBFS (G2)
    program 2   -0.04 dBFS (G1)  ->  -9.31 dBFS (G2)

Two independent programs agreeing to 0.01 dB. **G2 = G1 − 9.27 dB.**

### What this does and does not invalidate

- **Level-based comparisons across the boundary need +9.27 dB applied to G2**
  (or −9.27 to G1). They are correctable, not lost.
- **Ratio-based measures are unaffected**: sustain ratio, decay rate in dB/s,
  third-octave spectral distance, anything referenced to a file's own peak or
  its own noise floor. Every conclusion this project has drawn from those
  survives the boundary untouched.
- **Two G1 files are clipped and must not be used for anything level-based**:
  `cd1v2_011` (11 samples at full scale) and `cd1v2_007` (3). The rest of the
  G1 set is clear.

### The check that should have caught it earlier

`measure.py`'s `peak_db` is a **5 ms moving average of |signal|** (line 200-204).
A clipped burst of eleven samples lasts 0.2 ms and averages away to nothing in a
5 ms window, so **`peak_db` cannot detect short clipping and never could.** Every
"no clipping" assurance based on it — including two of mine on 2026-08-29 — was
reading a statistic incapable of answering the question.

The test that works is one line and belongs in every capture pass:

    max(abs(sample)) >= 32767      # and count consecutive runs

Run it on the raw frames, not on any smoothed envelope.


---

## Capture sets added 2026-08-27 → 08-30, in `../matrix/captures/`

All E4XT. Which gain generation each belongs to is in the table above; the
boundary falls inside this list, between `cd3krz_` and `cd3krz2_`.

| prefix | date | what it is |
|---|---|---|
| `sw_p1*` | 08-27 | six-arm Key→FilterFreq cord sweep, one process, one gain: cord 0/−10/−20/−29/−40/−46 on the top voice |
| `v3_p1*` | 08-28 | the same voice stacked vs solo, at two cord amounts — the 2×2 that showed the underlying layer contributes 0.05 dB at the top of the keyboard |
| `cd1v2_*` | 08-28 | 22-preset comparison bank, PC 0-21. **`cd1v2_007` and `cd1v2_011` are CLIPPED** — 3 and 11 samples at full scale. Do not use either for anything level-based. |
| `cd3krz_*` | 08-30 11:45 | KRZ→E4B, **VOID: four of seven hard-clipped**, worst 65332 samples at full scale. Kept only as the evidence that prompted the gain change. |
| `cd3krz2_*` | 08-30 11:57 | KRZ→E4B re-run after the gain change. Clean, all twelve clear. **This is the usable KRZ set.** |
| `v127chk_*` | 08-30 | the three hottest programs at velocity 127. **All three still clip** even at G2 — the velocity 100→127 step measures +4.70 dB on three programs agreeing to 0.02 dB, and the current setting has only ~3.5 dB of margin at velocity 100. |
| `velre_*`, `g1g2_*` | 08-30 | six UNCHANGED presets re-captured to measure what the sustain metric does when nothing changes. See §81 — it moves by up to 0.058, which is the noise floor nobody had established. |
| `velvol/pick_*` | 09-01 | P000-P009 at note 48, velocity 127, **nothing edited**. The untouched G2 baseline: peaks −4.67 to −6.58 dBFS, zero clipped, body 70–74 dB above each file's own pre-roll. Also the screening set that showed all ten voices are dark (centroids 149–430 Hz). |
| `velvol/law_amt*` | 09-01 | the velocity→volume law. P008 v0, nine velocities, cord 0 amount 0/24/50/100. `amt000` is the CONTROL and the most reusable file here — 0.01 dB across the whole velocity range proves that cord is the only velocity→volume path in the voice. |
| `velvol/piv_*` | 09-01 | all three velocity sources at ±10 against an amount-0 control, voice volume 0 and −12. Includes the `E4_GEN_VOLUME` dB-label pair (`piv_vol000_amt000` / `piv_vol012_amt000`): asked −12, measured −8.86. |
| `velvol/vt_*` | 09-01 | the `Vel~` dispute round — amounts ±5/±10/±25 at voice volume −20, and ±10 at −40. The amount-invariance is what excludes a fixed insertion loss. |
| `velvol/vf_*`, `vtff_*` | 09-01 | `Vel+` and `Vel~` into FilFreq on P000. Two of these are CONTROLS THAT REFUSED (`vf_p008_*`, and the byte-80 base) and are kept for that reason — see §85. |
| `velvol/fcresp_*` | 09-01 | centroid vs cutoff byte on P000, nine Fc values in one armed capture. **Read this before choosing a filter operating point on this bank:** +10.6 Hz/byte over bytes 20–60, flat above 80, then reversing. |

### Two things in here that are not captures

- **The velocity gap is unclosed.** Every capture in this archive is velocity
  100. `v127chk_*` shows the same material clipping at 127, which is what a
  hand actually plays. Setting an output ceiling against a velocity-100 signal
  leaves it about 4.7 dB short, and that is how the current setting was made.
- **Every 09-01 capture is G2 and none clipped.** The velocity→volume work
  runs DOWNWARD from the baseline — `Vel<` only attenuates below velocity
  127 — so the ceiling was never approached. Where those runs ran out was
  the BOTTOM: at cord amount 100 the three lowest velocities fall under the
  −88 dBFS bench floor. Those points are unmeasurable here, **not silence**.
- **The 09-01 controls that refused are kept deliberately**, the same way
  `cd3krz_*` is. A control that correctly stopped a run is evidence about
  the method, and two of them are the only record of why a filter operating
  point cannot be picked from a byte→Hz table.
- **`cd3krz_*` is void but not deleted.** It is the only recording of the
  clipping, and a set that proves why a bench setting changed is worth more
  than the disk it costs. It is labelled here so nobody measures it by accident.

---

## Cleared 2026-08-30 — the absence of things is deliberate

This directory held 998 MB. It now holds 587 MB. What went:

- **158 screenshot/state directories** (`nav_*`, `m1`-`m11`, `s4a`-`s5c`, and
  the rest) — LCD grabs from panel navigation, no audio in any of them.
- **27 measurement sets from 22-23 August**, older than a week and with their
  findings already recorded in eosed's `RESOLUTION_NOTES.md`: `anchor`, `grid`,
  `depth`, `qcal`, `rate`, the `depthfind`/`cornerfind` pair, the `fenv*` set,
  the `noisecal*` pair, and the small one-off probes alongside them.

**The three sets this file exists to identify were not touched**, nor were
`dumps/`, the scripts, or any measurement set from 24 August onward.

If a future reader wonders where a directory referenced in an old note went:
it was cleared deliberately on Jan's instruction, not lost. The findings
survive in `RESOLUTION_NOTES.md`; the audio behind them does not, and could not
be reproduced anyway — the bench gain has changed twice since (G0 → G1 → G2).

---

## Are the 09-01 captures from the right ports? Yes, and by effect rather than by trust

mpc2emu found on 2026-09-02 that a cached `_PersistentRecorder` had kept the
first instrument's inputs while MIDI port, channel and program change all
followed a switch correctly — producing an "MPC capture" of the K2000's inputs
that was clean, analysable and entirely wrong.

**eosed's rig could not reproduce that**, because `CAPTURE` is a module constant
and this project talks to one machine. But that is an accident of scope, not a
check, so `rig._recorder()` now calls `reconnect(CAPTURE)` on every use — it is
idempotent, and it reads the connection back instead of trusting `connect()` not
to raise, which is what distinguishes a silent capture from an ABSENT AUDIO PATH
from a silent capture of a closed filter. Those are identical in the file.

**The 09-01 set is independently verified by effect**, which is stronger than a
port check: every parameter edit produced the level or spectral change it
predicted, repeatedly, at r² > 0.999 — a −12 dB volume edit moved the capture by
8.86 dB with 0.03 dB of spread across nine velocities, and three cord amounts
returned the same dB-per-percent constant to ±0.07 %. **A recording of the wrong
machine cannot track edits made to this one.**

That is the general form worth keeping: *a signal-based gate cannot tell you
which machine you recorded, but a manipulation that shows up in the signal can.*

## The whole E4B column (`krE4/ s3E4/ s1E4/ matrix6/`) measures a defective build — 2026-09-06

Every E4B row in the MX9 matrix was written by a converter that applied the
velocity-pivot trim **twice**: once to the voice-level volume and once to every
zone volume, while the velocity cord restores only one copy. Measured on the
resident preset by zeroing the four bytes the editor protocol cannot reach:
**+29.50 dB**, ramp intact (see eosed `docs/RESOLUTION_NOTES.md` §92).

**Every trimmed preset in these four sets therefore sits ~29 dB below where the
conversion intended.** Untrimmed presets (organs here, and anything with no
velocity cord) are unaffected — the split is per-preset, not per-row, so a row
is not uniformly shifted and cannot be corrected by subtracting a constant.

    krE4/       KR-E4    6 of 12 presets trimmed
    s3E4/       S3-E4    trimmed throughout
    s1E4/       S1-E4    trimmed throughout (23.9 dB swing on all six)
    matrix6/    MPC-E4   built with the same writer

These files stay. They are a correct record of what that build produced, and
the pre-fix state is worth keeping for exactly the reason `preerase/` was
(§preerase): once the medium is rewritten there is no way back to it. **What
they must not be used for is conversion fidelity** — relative shape within a
preset (velocity ramp, key tracking, spectrum) still reads; absolute level
across presets does not.

Recapture needs the fixed banks on the machine, and the E4XT loads from an ISO
on a card in the drive emulator — no host path while it is in the drive. So
this waits on a card crossing, together with the `ATKSHAPE` bank.

**When it happens, capture `S3-E4` first, not `KR-E4`.** KR-E4 rises uniformly
and cannot distinguish the right fix from an unconditional one — all its
trimmed voices are multi-zone, so both emit the same bytes. S3-E4 splits: 30 of
36 trimmed voices are single-zone and must stay put, 6 must rise. It is the
only row in the column that can fail in both directions. Same grid, same
session gain as the pre-fix sets, or the comparison is not a comparison.

## Post-fix capture, staged 2026-09-06 16:5x — drivers ready, waiting on the card

Four drivers exist and are staged: `matrix_s3_post.py`, `matrix_kr_post.py`,
`matrix_s1_post.py`, `matrix_mpc_post.py`. Each is its pre-fix driver with the
output redirected to `<set>_post/` and **two guards that refuse to run**:

    if OUT ends with the pre-fix directory name  -> refuse
    if the results file already exists           -> refuse

**Both guards were verified by executing them, not by reading them** (§87: a
rule written down is not a rule installed). The pre-fix directories cannot be
overwritten by these scripts even if invoked with the wrong argument, which
matters because once the card is rewritten the pre-fix state cannot be
re-created — the same reason `preerase/` was kept.

The grids are unchanged from the pre-fix runs and must stay that way:

    S3-E4   6 presets x 5 keys (36/48/60/72/84) x 9 velocities   30 captures
    KR-E4  12 presets, same keys and velocities                  60 captures
    S1-E4   6 presets                                            30 captures
    MPC-E4 11 programs incl. the drum probe                      61 captures

**Order: S3-E4 first.** It is the only row that can fail in two directions.

**Read the results from `_refit.json`, never from the free-anchor file** —
see ANALYSIS_FILES.md and §94. And **do not score drum cells in the `early`
window**: it opens at 100 ms, those samples last ~80 ms, and anchor jitter of
±50 ms then manufactures level differences up to 31 dB (§95). Use `full` and
`attack` for percussive material.

**Known bad cell on the new disc:** MPC-E4 P010 plays 262.6 Hz at every key —
a converter bug filed and deliberately not fixed. Not a conversion result.

### Revised plan — MATRIX6 stays on the card, so the pre side is re-captured too

MATRIX7 goes to a free id and MATRIX6 is left where it is, so **both generations
are resident in one session** and the pre/post needs no cross-session
comparison. Three of the four rows are then one-variable pairs — trim only:

    KR-E4    9 bytes differ    trim only
    S3-E4    6 bytes           trim only
    S1-E4    6 bytes           trim only
    MPC-E4 137 bytes           trim + sample-name truncation  <- TWO variables

**Capture order, pre and post adjacent per row** so any drift within the session
falls between rows rather than inside a pair:

    S3-E4 (MATRIX6) -> S3-E4 (MATRIX7)     the discriminating row, first
    KR-E4 pre -> post
    S1-E4 pre -> post
    MPC-E4 pre -> post                     interpret last, two variables

Drivers `matrix_*_pre2.py` write to `<set>_pre2/` and `matrix_*_post.py` to
`<set>_post/`, both carrying the two guards, all eight verified by execution.

**The 09-06 sets (`s3E4/ krE4/ s1E4/ matrix/`) are not touched by any of them**
and become a third, cross-session copy of the MATRIX6 state. That is a free
control worth reading: **if `_pre2` reproduces them, cross-session comparison on
this bench is sound and §G0's gain-generation worry is bounded; if it does not,
the size of the difference is the size of the error in every cross-session
number this project has ever quoted.** Either answer is worth having, and it
costs nothing but the capture time already being spent.

## The measurement is a mono sum of a stereo capture — stated, not implicit

Every stage averages the two channels — `mono = raw.reshape(-1, 2).mean(axis=1)`
in the capture drivers, the windows pass, the refit and `velvol_seg`. The files
themselves are true stereo; the *measurement* is mono.

**What that costs, and what it does not.** For centred material the sum is
exact. For decorrelated material it is a −3 dB convention applied identically to
every cell, so it cancels in any comparison and survives only in absolute
levels. Nothing in the corpus is anti-phase — the most negative L/R correlation
found anywhere is −0.07 — so there is no cancellation risk. **It is lossy for
anything pan-dependent**, which matters for the calibrated pan law and not at
all for level or trim work.

**The corpus splits by source format, and it is the material, not the rig:**

    bank / set                 n    L/R corr median   mono-like (corr > 0.99)
    s3E4      (09-06 morning)  6         +1.0000            6/6
    s3E4_pre2 (09-06 evening)  6         +1.0000            6/6
    s3E4_post (09-06 evening)  6         +1.0000            6/6
    krE4      (09-06 morning) 12         +0.0142            0/12
    matrix5   MPC             10         +0.9999            8/10

S3000-sourced presets are mono: R is the same signal as L within a constant
+0.37 to +0.42 dB, residual 25–53 dB down after gain matching — one signal, two
channels, a fixed interface trim. **KRZ-sourced presets are genuinely
decorrelated stereo, 0 of 12 mono-like**, which is proof on its own that neither
the rig nor the instrument sums to mono.

Checked because Jan asked whether the EMU was recording mono during the S3-E4
run. It was not; that row simply is mono. **The same bank measured before and
after a card removal gives the same answer**, which is what rules out anything
having changed with the audio stack tonight.
