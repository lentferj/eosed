<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# TODO

*What* is open. `docs/RESOLUTION_NOTES.md` tracks *how* to resolve each item.

**Status, 2026-08-13 (third session).** Public at
`github.com/lentferj/eosed`, `main` at `de7e7a7`. **392 tests, all synthetic,
running in CI on three operating systems** — Linux (Python 3.11/3.12/3.13),
macOS and Windows (3.11/3.13), seven jobs, green. Every command in the editor
protocol is either verified against a real E4XT Ultra or explicitly listed
below as not, including all four destructive Master utilities (§21a-§21d), the
parameter write path (§18), and the read paths. Nothing in the protocol is
undocumented-and-unlabelled.

**This session** was one question — *have the install instructions been run
outside this machine, and do macOS/Windows need their own steps?* — and the
answer cost three commits and turned up a shipped bug.

Putting `macos-latest` and `windows-latest` in the CI matrix found that
**`config.toml` was silently unreadable on Windows** (RESOLUTION_NOTES §23).
`_write_config_dict` opened the file with no `encoding=`, so Windows used
cp1252, so the em dash in *our own header comment* became byte `0x97`, so
`tomllib` — UTF-8 only by TOML spec — rejected the whole file, so the blanket
`except Exception: return {}` reported it as "no config". The port cache never
persisted, the view preference never persisted, and any hand-edited key was
destroyed the first time the app saved. **Nine tests asserting that exact
round trip had been green on Linux for the life of the project.**

macOS, by contrast, needed nothing: green on both Python versions, first try.

**The README was also wrong rather than merely incomplete** for non-Linux
users: the Quick Start was unrunnable on Windows (`bin/` vs `Scripts\`), the
zsh quoting advice was half wrong (single quotes are literal in `cmd.exe`),
and "python-rtmidi normally installs from a wheel" is false on Python 3.13+,
where there is no wheel for *any* platform and a source build is guaranteed.

The matrix then found a **second** bug the author's platform could not show:
worker results landing after the app shut down (`WorkerFailed`/`NoMatches`),
which had been dismissed as a Windows flake twice before two failures on two
*different* tests made it read as a race. Fixed with an `is_running` guard on
the eight `_show_*`/`_append_*` painters. Not a test artefact — on real
hardware a bank page load is seconds and a cache-all sweep is minutes, all of
it quittable with `q`.

That makes **three** sessions running in which the same pattern produced the
session's real finding, and it is the same one §11/§12/§21c established for
the protocol: **the things this project gets wrong are the things nothing ever
executed.** A vacuous test, an unverified protocol assumption, and a correct
test that only ever runs where the bug does not reproduce all fail
identically — quietly, and only on contact with something that isn't the
author's own machine. The corollary is now explicit in §23: when fixing one,
check that the regression test itself is not inheriting the same blind spot.
The first attempt at the Windows test asserted on the resulting bytes and
would have passed on Linux with the bug still in place.

**But do not over-learn the CI lesson — §24 is the counterweight.** A second
session reviewing this work found that the config bug had a half §23 named and
did not fix: the blanket `except Exception: return {}` still let *any* parse
failure (a stray bracket, a truncated file) silently empty the config, because
saving is read-modify-write. That failing configuration was reachable on this
Linux box the entire time — one malformed file, one save. **No matrix, no
second platform, no hardware.** It survived because the mechanism had been
described in a commit message and nobody wrote the four-line reproduction.

So the session produced two rules, not one, and they are independent:

1. **Run where you do not develop** (§23, the encoding half, the shutdown race).
2. **Write the reproduction even when you think you already understand the
   mechanism** (§24) — especially right after describing it confidently in
   prose. Rule 2 would have caught §24 with none of rule 1's infrastructure.

A third failure mode is worth naming because it is subtler than being wrong:
§23 was *not* false. It described a live mechanism in the past tense, which is
how a reader concludes a path is sound when it is not. §24 opens by
contradicting §23 directly, and §23 carries a forward pointer, deliberately —
see the "no stale claims" convention that the last three sessions have been
about.

**Previous session (2026-08-01, `cef04c7`)** closed the housekeeping list
(CI, packaging metadata, a refreshed `HW_CHECKLIST.md`, the stale
`review-fixes` branch), built the `i` bank-integrity check that §21c called
for, and made the Quick Start followable from a clean clone. Its three bugs,
also none found by reading code: the integrity check's own stale-cache false
negative; `eoscli ports` crashing on any host with no MIDI subsystem (caught
by CI's *first* run, on a test that had been passing vacuously); and
`pip install -e .[dev]` failing in zsh.

The largest open items are unchanged, in rough order of value: root-causing
the §15 device crash (the only thing that can take the machine down, and what
blocks a faster default `SEND_GAP`), the §17 pipelining probe (minutes off
every bank sweep), and the panel/mirror protocol (**since done — see the
Panel/remote protocol section below**). The first two still need hardware.

**Next time there is hardware**, the two cheapest new items are
`HW_CHECKLIST` **E8** and **E9** — run `i` against a bank with a deliberately
erased-but-referenced sample, then repeat with the erase done from the
*front panel*. E9 is the only way to confirm the previous session's
stale-cache fix: nothing this app does can produce a genuinely out-of-band
change to the device.

## Preset restore — the missing half of "editor/librarian" (OLD format BUILT 2026-08-25)

**Status: OLD format built, never sent to hardware. NEW format still not built.**

`EosBridge.send_preset_old` and `eoscli send` exist as of 2026-08-25, with
`dump_target` / `retarget_dump` for choosing the destination slot. Built on
Jan's sign-off, relayed through mpc2emu, who declined to authorise a write path
themselves and put it to him.

**The spec says this direction exists, in its own words** — the transcription
matters because the send handshake was otherwise going to be inferred from the
receive one:

* *"the ability to send a Dump of parameters to the E4."*
* *"Preset Dumps of the Old format may still be Requested from and Dumped to
  the E4."*
* *"When a Dump is requested or initiated..."* — initiated, i.e. by the host.
* *"Only 1 Preset may be Dumped to or from the E4 at a time!"*
* EOF: *"No more packets follow, no response required. Must be sent at end of
  transfer."*
* WAIT: *"Stop sending packets until an ACK is received."*

**What is still inferred, and is marked as such in the code:** the spec says
only that *"generic handshaking messages will be used to negotiate the
transfer"* — it does not state who ACKs what on a host-initiated dump. The
implementation mirrors the receive direction, which §7 confirmed live (the
device waits for a header ACK, then ACKs per packet). **The first live send is
therefore a probe.** Its timeout message says so rather than reporting a bare
`TimeoutError`.

**Guards, because this is the one write that destroys a whole preset:**
`send_preset_old` refuses without `allow_write=True`; `eoscli send` reports the
destination and **reads back the name currently in that slot** before doing
anything, refuses without `--allow-write`, and then requires the preset number
typed back. `--yes` exists for callers that have already asked.

**Suggested first live use, and the reason:** dump a scratch preset, send it
straight back to a *different* scratch slot, dump that slot, compare bytes. A
byte-identical round trip validates the path without depending on the inferred
handshake being semantically right — if the bytes return, it worked.

### Original entry (2026-08-14)

**Status at the time: not built, in either dump format.** `eoscli dump` reads a preset off
the device; nothing sends one back. `eos/messages.py` already encodes the
frames (`PRESET_DUMP` `0Dh` with its OLD/NEW sub-commands, ACK/NAK/WAIT/EOF
handshake), so this is a missing *send path* — a bridge method and a CLI
command — not missing protocol work.

**Why it was worth opening as its own item.** The docs called this project an
"editor/librarian" in six places while it could not put a preset back, which
is the one capability the word *librarian* actually denotes (Galaxy,
SoundDiver, MIDI Quest all mean transmit-back by it). Corrected 2026-08-14 —
the phrase now names E-mu's protocol explicitly, not this tool's coverage of
it, and the README carries an "It is an editor, not a librarian" section.

Two contradictory claims fell out of the same bundling, each true of one half
of "dump/restore" and false of the other:

* README "Not yet implemented" said **NEW-format dump/restore** was missing —
  but `dump_preset_new` and `eoscli dump --new-format` exist.
* README "Known Limitations" said NEW-format **dump/restore is implemented**
  but unverified — and restore is not implemented at all.

Neither was a typo: writing an implemented and an absent capability as one
slash-joined item is what let both survive. Worth remembering next to §23's
"described a live mechanism in the past tense" — same family of documentation
fault, where the sentence is not false so much as unreadable as false.

**Before building it**, note that restore is a *write* to the device and a
whole-preset one: it overwrites a preset slot outright. It belongs behind
`--allow-write` and the arm-then-fire modal like the Master utilities, not on
a plain key. The spec's one-preset-at-a-time rule (CLAUDE.md) applies, and the
ACK/NAK/WAIT/EOF handshake is the part most likely to need a live probe — §7
already caught the dump engine not ACKing its header, and the reverse
direction has never been exercised at all.

## Live hardware verification

**Status: in progress.** `eoscli inquire`, `config`, `memory`, `catalog`
(full 0-127 sweep), and `dump` (OLD format) have all been run live against a
real E4XT Ultra — see RESOLUTION_NOTES §7. A real bug was found and fixed in
the process (the dump engine wasn't ACKing the header before expecting data —
see RESOLUTION_NOTES §7).

**Writing is now verified too (2026-07-31, RESOLUTION_NOTES §18).** Ten
scratch presets (P000-P009, one voice each, no samples) were used to write
every preset-scoped parameter, read it back, then switch away and return and
read it again: **3340 comparisons and 20 renames, all exact**, at 100ms
between sends, with no dropped replies and no §15-style crash. Two real bugs
fell out of it, both about signedness (see §18) — values were never
sign-extended on read, and min/max/default were sign-extended
*unconditionally*, which corrupted `E4_VOICE_DELAY`'s real 0..10000 range
into 0..-6384. Both fixed, and 12 genuinely mis-transcribed envelope ranges
corrected in `eos/params.py`. **Preset Delete (`71h`) is now confirmed live
too** — fired by hand from the arm-then-fire modal against a 3-preset test
bank, deleting exactly its target, freeing preset RAM (8 KB → 5 KB), sparing
samples, and **not compacting** the bank (RESOLUTION_NOTES §21a).
**Erase All RAM Presets (`75h`) is confirmed too** (§21b): presets destroyed,
samples and sample RAM untouched — and it does *not* leave the bank empty:
**P000 always exists on an EOS machine**, so the erase bottoms out at a
single blank `"Untitled Preset"` with preset RAM at 0 KB. "No presets" and
"one Untitled Preset" are therefore the same state, and a name sweep can
never come back completely empty.

**All four Master/erase actions are now verified live (RESOLUTION_NOTES
§21a-§21d)** — `71h`, `74h`, `75h`, `76h` — each fired by hand from the
arm-then-fire modal. `74h` is the union of `75h` and `76h` with nothing left
over. Two device facts came out of it that a client author would not guess:
`preset_memory()` at 0 KB (not an empty name catalog) is the signal presets
are gone, since P000 always exists; and `sample_memory()` never reaches 0 —
~3.00 MB is overhead, and that figure *is* empty. Still untested live: the
device-global `master.*` parameters, and *writing* `E4_GEN_SAMPLE`.

### Find presets with dangling sample references — BUILT, never run live

A voice keeps its `E4_GEN_SAMPLE = N` after sample N is erased — confirmed
live (§21c). Nothing at the voice level distinguishes a live reference from a
dead one, so the Samples pane, `u`, and the cache-all sweep all display an
erased sample exactly as they would a present one.

**Built as `i` (bank integrity check), 2026-08-01.** `EosedApp.
action_check_dangling_samples` plus the pure `eosed.app._dangling_sample_refs`,
reporting `P012 V3 → S045 (missing)` in the status line and mirrored into
`#params` (visible in both view modes, unlike `#samples`). Read-only, so
deliberately not gated on write mode. Bound to `i` rather than the equally
free `d` — a single letter that reads as "delete" has no business next to
this protocol's one-shot destroyers.

**No new MIDI:** it is a filter over what a `"structure"`-depth
`_run_full_sweep` already collects, so it is instant once `c`/`C` or a `u`
lookup has run, and costs exactly one sweep when run cold.

Two exclusions, both deliberate and tested:

* **Sample 0 is never dangling** — an unassigned voice reads
  `E4_GEN_SAMPLE = 0` (seen on the §18 scratch presets) and `S000` reads the
  placeholder on every bank seen so far, so flagging it would report every
  empty voice on the bank.
* **A blank name is not evidence.** `_resolve_sample_rows` falls back to `""`
  when the name fetch *raises* — a transport failure, i.e. "unknown", not
  "missing". Only the device's own literal `"Empty Sample"` reply (§13)
  counts. This is the second feature to depend on that §13 finding being a
  real, well-formed reply rather than a blank one.

The "referenced minus present" formulation in the original design was
**not** used, and deliberately so: `sample_names` is truncated by the
sample-name pass's own early stop (it stopped at 204 on the bank in §13), so
set-differencing against it would flag every sample above the stop point as
missing. The per-sample name resolved during the walk has no such dependency
on how far the sweep ran.

**A stale-cache false negative was found and fixed straight after, while
checking what live confirmation actually existed.** `_resolve_sample_rows`
consulted `_catalog_cache["sample"]` before the device — and that cache is
the *previous* sweep's output. A sample erased **outside this app** (front
panel, or another session) is invisible here, so the stale cached name came
back, the voice still pointing at it looked healthy, and the check reported
the bank clean. That is precisely the §21c scenario the check exists for, and
`x` did not help: it clears the usage index but not the name catalog, so even
a forced re-sweep answered from the stale names. Fixed by having the sweep
pass `use_catalog_cache=False` — a re-sweep that answers from the last
sweep's cache is not a re-sweep. Costs one name fetch per *distinct* sample
per sweep (the within-sweep memo still collapses repeats), and only on the
sweep path; `_load_preset_overview` still uses the cache. Pinned by
`test_re_sweep_sees_a_sample_erased_outside_the_app`.

**How much of this is confirmed live.** Every fact the check rests on is,
including the exact detection rule: §21c records `P000`'s voices still
reading `E4_GEN_SAMPLE = 1` after the erase *while `get_sample_name(1)`
returned `"Empty Sample"`* — an erased-and-still-referenced slot, not merely
an unused one. What has never run against hardware is the assembled code
path. Covered by 8 synthetic tests (HW_CHECKLIST E8); reproducing it live
means erasing a sample a preset still references, so it wants an expendable
bank — the same §21 setup.

Worth having beyond the erase case: a bank restored from disk with missing
samples, or one assembled by an external writer (mpc2emu writes E4B banks),
shows the same symptom with no other way to detect it short of checking
every voice by hand.

**Re-verified against a full commercial bank (RESOLUTION_NOTES §19).** 990
populated presets, 128MB of samples, 10121 reads: confirmed `E4_GEN_SAMPLE`
has exactly two negative values (§18a), and caught a separate real bug —
`_MAX_VOICE_SCAN`/`_MAX_ZONE_SCAN` were guesses (64/32) that real content
overruns (94-voice drum kits, a 62-zone voice), silently truncating those
presets with no error. Both raised to the protocol's own 256 ceiling.

**A 25ms send gap has been tested and holds (RESOLUTION_NOTES §19a)** —
A/B'd against the known-good 100ms on both risk profiles (self-pacing
reads, and the write bursts that have no reply to throttle against), then
sustained over ~500s of continuous traffic with no errors and no §15-style
crash. **Deliberately not adopted as the `SEND_GAP` default**: §15's crash
is still not root-caused, so there is no reason to spend that safety margin
globally when a caller that wants the speed can pass `gap=`. Worth
revisiting if §15 is ever closed.

- Not actually blocked on `~/mididings_e4xt.py`: autodetect finds the real
  hardware send/receive ports directly (bypassing mididings' filter chain
  entirely) rather than routing through it — see RESOLUTION_NOTES §7. No
  changes to mididings were needed or made.
- Still applies: one-session-at-a-time hardware access (same rule as
  k2kremote/mpc2emu).
- `PRESET_NUM_SZONES` has never been verified and is not called anywhere in
  the app — its siblings in that command family all turned out not to be
  plain counts (§11/§12), so assume nothing about it.
- Remaining: the NEW-format dump path (`eoscli dump --new-format`) is
  untested live — its header-ACK handling in `dump_preset_new` is
  extrapolated from the OLD-format finding, not independently confirmed
  (RESOLUTION_NOTES §7). **Partially resolved for OLD format:** the
  `voice.*` byte layout for ids 53-116 is now known to be a uniform
  `98 + (id-53)*2` (RESOLUTION_NOTES §16, found via a sibling project's
  parameter hunt) — still not hooked up to an actual decoder in this repo,
  and ids below 53 / above 128, plus the link-data layout, remain
  unconfirmed. A real captured sample is saved at
  `docs/samples/e4xt_ultra_preset0_old_format.bin` to work from.
  Only after dump reading is solid should any write path be tried live — the
  editor TUI's write actions default to disabled against real hardware for
  exactly this reason (`--allow-write` required; see the Editor TUI section
  below).

## Multi-device autodetect — designed and unit-tested, never seen hardware (OPEN)

Autodetect can now tell two connected EOS units apart by their SysEx device
id, refuse to guess when several answer without one being requested
(`AmbiguousDevice`), and treat one unit heard on two input ports as one
device. **None of that has ever run with two real machines connected** — the
author has one E4XT Ultra. It is covered only by tests against fake ports.

Single-device autodetect is exercised live constantly and is not in doubt.

**To close this**, with two units on one host and *different* device ids set
(EOS 4.0 manual p. 104):

1. Connect both, run `eoscli inquire` with no `--device-id` — expect a
   refusal listing both ids, not a connection.
2. `eoscli --device-id N inquire` for each — expect the right model/revision
   each time, and confirm against each unit's own front panel.
3. Check the port cache does not pin the wrong machine across restarts:
   connect to one, relaunch, confirm it is still that one.
4. If an interface merges both units onto one input port, confirm they are
   still distinguished by id rather than collapsed.

**Known undetectable, do not chase:** two units left on the *same* id. The
replies are byte-identical, and identical to one unit heard on two ports.
Nothing on the wire separates them.

Worth remembering why this is worth verifying rather than assuming: §11, §12
and the `preset_num_links` case are three separate occasions where a
plausible protocol assumption was wrong on contact with hardware.

## Scripted live automation: `PRESET_SELECT` gotcha + a real device crash (OPEN, 2026-07-28)

A sibling project (mpc2emu) drove this repo's editor protocol unattended for
an amp-envelope calibration sweep and hit two things worth fixing here before
anyone scripts against a real E4XT again:

1. **`PRESET_SELECT` is not "select for playback."** Editing a preset's
   parameters via `set_parameters` without also calling
   `EosBridge.send_program_change(preset)` first silently edits a preset
   that's never actually heard — playback keeps using whatever preset a real
   Program Change last activated. Same root cause as §14, just hit blind by
   a caller that didn't know about §14 yet. Consider a guard/warning in
   `EosBridge` itself (e.g. track "last program-changed preset" and warn on
   `set_parameters` targeting a different one) so the next caller doesn't
   have to rediscover this the hard way.
2. **The device crashed** ("Gen Trap error" fatal firmware fault, needed a
   power cycle) during unattended automation sending plain MIDI channel
   messages (note on/off) with no inter-message gap, on top of an
   already-long burst of SysEx traffic. Not yet root-caused or reliably
   reproduced — see RESOLUTION_NOTES §15 for exactly what was sent.
   **A SECOND Gen Trap has since been recorded, and that one has both a
   trigger and a register dump (§36): an E4B carrying `0x7F` in a voice's
   filter-type byte selects a filter one past the end of the implemented set,
   renders as an empty name, and takes the firmware out. Different
   circumstances, so it does not close this item — but it is the first
   reproducible instance of this fault on the machine.**
   **Blocked on:** a careful, isolated repro (not a repeat of the full
   traffic pattern) to identify the actual trigger, then either a fix or at
   minimum a documented "don't do this" in `EosBridge`'s docstring. Until
   then, treat any unattended/rapid live automation against a real E4XT as a
   crash risk, not just a cosmetic-desync risk.

## E4XT left unresponsive to SysEx and Program Change (OPEN, 2026-08-17)

**Status:** device needs a look at its front panel; nothing lost, nothing
written to disk.

After a long unattended panel-driving session the E4XT reached a state where
it **sounds notes normally and on pitch**, but ignores Program Change and
neither answers nor acts on SysEx. Ruled out by test: bus contention (a
sibling session stopped all traffic on the shared interface and it made no
difference) and stale port bindings (ports resolve by full name, which fails
loudly). Most likely a **modal dialog** left open on the front panel — see
RESOLUTION_NOTES §34 for the full account.

**Blocked on:** Jan looking at the front panel (and, if it is a modal,
cancelling it). Do **not** send blind keypresses to clear it — the Utils
menus carry Erase RAM Bank/Presets/Samples with no second confirmation.

Two things to fix here regardless of how the device is recovered:

1. **`send_program_change` can silently not take effect.** The existing
   entry above covers `PRESET_SELECT` not being "select for playback"; this
   is the next layer — the Program Change itself was ignored, and nothing in
   the API said so. A caller measuring anything per-preset gets a clean,
   completely wrong answer. Consider a verification helper that reads the
   selection back (or at minimum a documented "confirm the preset changed
   before trusting per-preset measurements").
2. **Panel driving needs a display-alive precondition.** The screen is
   fetched over the same SysEx path that can go quiet, so it is possible to
   keep sending keypresses into pages nobody can see. Any scripted panel
   driver should refuse to send a key once a screen request has failed.

## Rate-compensation on playback — ANSWERED (resolved, 2026-08-17)

Does EOS honour a sample's stored rate when it plays it? The sibling
mpc2emu project's E4B writer depends on the answer.

**Resolved: `[58-59]` is authoritative for playback pitch; `[54-57]` drives
the displayed rate and duration.** Settled with a mirror pair of banks whose
two fields contradict each other — see RESOLUTION_NOTES §35. Both directions
landed within half a cent of prediction. The text below records why the
earlier routes could not answer it and is kept for that reason.

The disk route (load one of the machine's own banks and compare a low-rate
sample against a 44.1 kHz one, each at its own root key) was attempted and
**cannot answer the question even when run perfectly**: in machine-written
material the stored rate at `[54-57]` and the pitch offset at `[58-59]`
agree, so the device's own files cannot separate which field it reads.

**Blocked on:** a bank whose two fields *disagree*, loaded from media the
device can read — i.e. mpc2emu's `PITCHCHK.E4B` written to the Zulu SD.
That is a physical swap, and it is the only instrument that can answer this
rather than merely the most convenient one.

Vehicle for when it resumes, already surveyed: bank B02 on D0 (6.0 MB) mixes
~31524/31969/32103/32144 Hz with ~44001/44053/44100 Hz. P000 V0 plays sample
1 (31524 Hz) at root MIDI 50; P011 V0 is single-voice, single-zone, playing
sample 44 (44100 Hz) at root MIDI 60.

## Envelope sustain: RESOLVED — there was no 2.58x gap (2026-08-18; closed 2026-08-22)

**RESOLVED 2026-08-22 (§45): the two banks agree.** Measured in one session
through one capture path, ENVSPAN's byte-107 preset gives 0.2045 and SUSLEVEL's
byte-107 preset gives 0.2031 — 0.69% apart, against a 2-3% take-to-take spread.

**The discrepancy was a mislabelled axis.** The bank has no byte-108 preset; its
sweep is non-uniform (64 72 80 88 96 100 104 107 110 113 116 118 120 122 124
127) and had been indexed as though the steps were uniform, so 0.4565 — which
belongs to byte 116 — was filed under 108 and compared against a correctly
labelled 107.

**The law is refitted and §39's is superseded:** 0.754 dB/byte, R^2 0.9999 over
bytes 64-122, against §39's 0.547 dB/byte at R^2 0.980. The old slope is 38% low
and its scatter was the mislabelling. `env_seconds_to_rate(seconds, span_db)`
is no longer blocked on an unexplained anomaly; it is blocked only on someone
writing it against the corrected law.

Original framing follows.

**Status: the SHAPE of the sustain-level law is solid; its ABSOLUTE anchoring is
not.** §39 fitted `dB below peak = 0.547 x byte - 66.14` (R^2 0.980) over bytes
80-116, and §37's rate law was confirmed on a second dataset. Neither result is
in question here.

What is unresolved is the metric they are expressed in. `sustain/peak` divides by
the attack peak, which is **source-dependent** — and two banks disagree at
nominally the same setting:

    ENVSPAN  byte 107  ->  sustain/peak 0.177
    SUSLEVEL byte 108  ->  sustain/peak 0.4565

Bytes one apart cannot differ by 2.58x. Crest factor accounts for 1.377 of it;
**1.87x, or 5.4 dB, is unaccounted for by either this project or mpc2emu.** So
what exists is a relative law measured within one bank, needing a per-source
offset before it can calibrate anything — which is why
`env_seconds_to_rate(seconds, span_db)` stays unwritten.

**Update 2026-08-22: SUSANCHOR has been run, and the answer is the third case --
ZERO offset.** HRM-SIN measured +0.13/-0.12/-0.06/-0.09/+0.09 dB across the five
bytes: mean -0.01 dB, spread 0.25 dB, no trend, against a within-run
repeatability of 2.14%. Controls read 1.0002 and 0.9999. `sustain/peak` is
source-independent (§42).

That **removes** an explanation rather than supplying one. Crest factor is a
property of the source, so if the source does not matter then neither does
crest factor -- and the 1.377 it was said to account for goes with it. The gap
is not 1.87x unexplained on top of an understood 1.377; **the whole 2.58x is
unexplained.** What is left has to be a difference between the two banks --
envelope settings, presets, measurement window, or an error in one of the two
original measurements -- and this experiment cannot say which.

**Now blocked on: a controlled comparison of the two BANKS**, not of two
sources. The cheapest form is to re-measure ENVSPAN's byte 107 and SUSLEVEL's
byte 108 in one pass through one capture path, the way SUSANCHOR did for the
sources. Both discs still exist, parked as `XX_*.disabled` on the card.

The original framing, for the record: `CD2-SUSANCHOR.iso`, id 2 — 12 presets on keys 36-47, one key each, the
same five level bytes (84/92/100/108/116) rendered on BOTH sources in one bank,
one pass, one capture path, so everything but the source is held constant and
the difference between the two curves IS the source term. Interleaved SIN/HRM
rather than blocked, so capture-path drift cannot land entirely in the quantity
being measured. Controls are byte 127 on the sine at both ends: they must agree
and each must read near 1.0.

Subtract HRM-SIN in dB per byte and read the answer off the shape:

    constant offset  ->  the slope is source-independent; only the anchor moves,
                         and a per-source offset closes it
    growing offset   ->  sustain/peak is not measuring the parameter at all
    ZERO offset      ->  the ENVSPAN/SUSLEVEL gap is NOT the source, and two
                         banks of near-identical presets differ by 5.4 dB for a
                         reason nobody currently has a candidate for

It mounted correctly on 2026-08-18 (boot log: `Opening /CD2-SUSANCHOR.iso for
id:2`) and was simply never measured — the session moved on to §36-§39. It was
briefly suspected of failing to mount because a stray `CD2-*.csv` looked like it
was stealing the id; the boot log shows the ISO won that race and the CSV was
the casualty. The CSV now lives in `expected/`, which is not scanned, so the
question cannot arise again.

Related and separately open: the filter envelope's rate -> time is uncalibrated
altogether (§41), and `CD4-NOISE.iso` was placed on the card on 2026-08-22 to
settle it. Both want the same rig, so they are worth doing in one session.

## Name-catalog pipelining — the largest remaining speed win (OPEN, needs a live probe)

Every catalog scan is strictly serial: send one name request, block for the
reply, repeat — so a 0-999 sweep has a ~50s floor in send-throttle alone, and
that is most of why a full cache-all runs into minutes (§20 measured 2.5 min
for names alone, 1h 44m at full depth).

Name replies carry their own preset/sample number, so they do **not** need to
be matched positionally — the same property `get_parameters` already exploits
to batch 64 ids per request. If the device queues more than one outstanding
request, K round trips collapse into one pipeline depth.

**Blocked on** a live probe, because the failure mode is silent and ugly: if
it does not queue, dropped replies read as "this preset has no name", which is
indistinguishable from an empty slot and would quietly corrupt the very
catalogs this is meant to speed up. Procedure, and why the voice walk is
*not* a candidate for the same treatment, in RESOLUTION_NOTES §17.

## Housekeeping

**`tools/capture_screenshots.py` produces a spurious full-file diff on every
run.** Textual stamps a randomised CSS class name into each export
(`.terminal-533059608-…` → `.terminal-2843853891-…`), so all five SVGs come
back modified with no content change whatsoever. Left as folklore this will
eventually get committed by someone who assumes the diff is real, or hide a
change that is. Check with `git diff --numstat docs/screenshots/` — equal
insert/delete counts on every file is the signature of pure noise. Only
commit regenerated screenshots when a real UI change motivated the run.


**Done (2026-08-13).** CI extended to **macOS and Windows** — seven jobs, and
it paid for itself on the first run again by exposing the cp1252 config bug
(RESOLUTION_NOTES §23). The workflow also smoke-tests both console scripts
now, since "is `eoscli` on PATH after an install" is exactly what the Quick
Start promises and exactly what differs between `bin/` and `Scripts\`. The
README gained a Windows install block, a per-platform compiler table for
Python 3.13+, and a Platform notes section; `pyproject.toml`'s classifiers
widened from Linux-only to all three.

**Done (2026-08-01).** CI added (`.github/workflows/tests.yml` — the full
synthetic suite on Python 3.11/3.12/3.13, on every push and PR);
`pyproject.toml` gained `[project.urls]`, classifiers and keywords (no
`License ::` classifier — the `license` field already carries the SPDX
expression and PEP 639 deprecates saying it twice); `HW_CHECKLIST.md`
refreshed (new section E for the cache/sweep features, C10 and D7 ticked,
D5 marked partial, and the §21-superseded "do not fire a destructive op"
note removed); the merged `review-fixes` branch deleted.

**CI earned its keep on the first run**, which is worth recording because it
is the exact argument that motivated adding it. `test_ports_lists_something`
asserts `eoscli ports` "must not raise even on a host with no MIDI hardware"
— and had been passing **vacuously** on the dev box for the whole life of the
project, because that machine has an ALSA sequencer (it has real MIDI
hardware attached), so rtmidi enumerates fine and simply returns an empty
list. A hosted runner has no `/dev/snd/seq` at all, which is the harder case:
rtmidi raises out of the *constructor*, so nothing was catching it, and the
command traced back. Anyone running `eoscli ports` in a container, on a
headless server, or on WSL without sound would have hit the same thing —
plausibly the very first command they tried. Fixed with a typed
`eos.bridge.MidiUnavailable`, deliberately **not** flattened to two empty
lists: "nothing is plugged in" and "this machine cannot do MIDI" need
different fixes, so `ports` now prints which one it is. The vacuous test
stays (it does still cover the ordinary host) and two real ones join it,
both simulating the constructor failure so the case remains covered on a
machine that has a sequencer.

**README Quick Start made followable from a clean clone**, which it had
never been: no `git clone` step, no stated Python version (3.11+ lived only
in `requires-python`), and `pip install -e .[dev]` as the sole documented
install — which fails outright in zsh, the default shell on macOS, since it
globs the brackets. Plain `pip install -e .` is the default now (nothing in
`eos/` or `eosed/` imports pytest, so the dev extra was never needed to
*run* the tool), with the quoted extra offered for the suite.

**Then actually executed from an empty directory**, rather than left as
another fixed-by-inspection claim: `git clone` → `python3 -m venv` →
`pip install -e .` → `eoscli --demo inquire` → the TUI (launched headless
against `DemoBridge`, since the real thing needs a terminal) → the quoted
dev extra → the full suite, **384 passed** from the fresh clone. No wheel
fallback was needed; `python-rtmidi` 1.5.8 and `textual` 8.2.8 installed
from wheels on Python 3.11.2. The clone also confirmed the gitignores hold
in the direction that matters: no `CLAUDE.md`, no `config.toml`, no
`HW_CHECKLIST.md` in the published tree.

**Still open:**

- **CI runs on deprecated Node 20 actions.** `actions/checkout@v4` and
  `actions/setup-python@v5` both warn; GitHub is force-running them on Node
  24 and everything passes, so this is noise, not breakage. One-line bumps
  when it is worth clearing — now on **seven** jobs rather than three, so the
  annotation noise has more than doubled.
- **The zsh half of the install note is still asserted, not tested**, but it
  no longer gates anyone: the README now says to use *double* quotes, which
  work in bash, zsh, PowerShell and `cmd.exe` alike, so the shell-specific
  claim is an explanation rather than an instruction. This box still has no
  zsh. Worth 30 seconds on any macOS machine if the sentence is ever
  rewritten.
- **Nobody has driven real hardware from macOS or Windows.** CI covers
  install, both entry points, demo mode and the full suite on all three
  platforms, but hosted runners have no MIDI interface, so every live claim
  in this repo rests on Linux sessions with one E4XT Ultra. The README's
  "Platform notes" is careful to describe what CoreMIDI and WinMM *do* rather
  than what eosed has been seen doing on them; keep that distinction if the
  section is edited. Needs someone with the hardware on one of those
  platforms — see RESOLUTION_NOTES §23 for what the matrix does and does not
  prove.
- **~~Windows 3.11 flake~~ — resolved, and it was never a flake.** Filed here
  as "watching not fixing" after one failure; it recurred on a *different*
  test with the same signature, which is what made it legible as a race
  rather than noise. Two real defects came out of it: worker completions
  crashing when they land after shutdown (fixed with the `is_running` guard),
  and then the new guard's own test racing the startup load it shared an app
  with. **Kept in the record deliberately**: "intermittent on one platform"
  read as noise twice before it read as a bug, and the cost of that reading
  was two red CI runs on `main`. One failure on one platform is a sample of
  one, not evidence of flakiness.
- **No convention for two sessions in one working tree.** Two Claude sessions
  worked in this tree simultaneously for the better part of an hour and
  neither knew until a `git status` showed unexpected files — after both had
  already written to disk and run the suite. Nothing was lost, but only
  because one committed by explicit path rather than `git commit -a` and the
  other checked before committing: two independent pieces of care, neither
  required by anything — and, the uncomfortable half, **neither aimed at
  this**. One ran `git status` to see what it was about to commit, not to
  detect another session; the other used pathspecs for tidiness. The safety
  was a by-product of ordinary habits, which is precisely the kind that stops
  working the day someone is in a hurry. This is the same shape as the hardware rule in
  `CLAUDE.md` (one session drives the E4XT at a time, because two on one MIDI
  port corrupts a measurement) applied to a resource that has no such rule.
  Open question for the author, not to be settled unilaterally: a lock file,
  a peer check before the first *write* (reviewing concurrently is harmless —
  contention starts at the first edit), or a line in each `CLAUDE.md`.

- **`docs/samples/e4xt_ultra_preset0_old_format.bin` provenance is undecided.**
  The preset *name* was scrubbed (§7), but the parameter values are still a
  commercial preset's, and the file is public. Either keep it as a small
  interoperability artefact, or regenerate the equivalent from a
  self-authored preset and drop the question entirely.

## Panel/remote protocol — **DONE (2026-08-16/17)**; remote disk load was the reason

**Status: the protocol is reverse engineered, the mirror is built, and the use
case below is met.** Front-panel mode (`k`) mirrors the 240×64 LCD live and
sends every key; the machine's own disk pages are reachable through it, so
choosing a drive, browsing banks, checking one and loading it all happen from
the desk. Done repeatedly against the E4XT Ultra on 2026-08-17/18 — see
RESOLUTION_NOTES §26-§34. The RE is this project's own, from captures of the
device echoing physical presses (§3's correction).

The original entry follows, kept because it records why the work was worth
doing and what was checked before starting.

**The use case, stated first because it is what makes this worth doing:**
choose a disk, browse what is on it, and load a bank — from the desk, without
walking to the rack. Banks are already written to HD images and mounted via a
SCSI emulator (ZuluSCSI); the only step that still requires standing at the
machine is telling it to load one.

Until now this item read as "a k2kremote-equivalent would need this", which is
a capability in search of a reason and is why it never got started. It has a
reason now, and the reason **reorders the work**.

**None of it is reachable from the editor protocol — checked, not assumed.**
The full command table (`01h`-`7Ah` in `eos/messages.py`) has no disk surface
whatsoever: no drive selection, no directory read, no load, no save, no mount.
Every command is RAM-scoped. The EOS 4.0 manual documents no SysEx disk
control either. **Auto Bank Load** (Master → Bank → Auto, F2/F3) is the only
documented remote-ish path and is not this: it fires once at power-up, on a
bank chosen at the panel, with no browsing.

**The sibling technique does not port.** s3ked does remote loads on the Akai
S3000 by writing the LOAD page's type-of-load register (its §75/§93 — value 1
fires a load with no `GO`). That works because Akai's *documented* SysEx also
carries the browse half: `RVOLLIST`/`VOLLIST` (`35h`/`36h`) for volumes and
`RHDDIR`/`HDDIR` (`37h`/`38h`) for directory entries. EOS has no equivalent to
aim at, so on this machine **both** halves — browse and load — have to come
out of the undocumented panel protocol.

**Which makes the display frame the blocker, not a later polish step.**
Browsing a disk you cannot see is not browsing, and injecting keypresses at a
machine whose screen you cannot read means navigating blind through menus that
also contain the erase utilities. Order: **screen readback first**, then
navigation, then the load trigger. Do not start at the buttons because they
look easier.

**Harness is built and waiting: `probes/panel_capture.py`.** Passive — it
never transmits, since §3's rule forbids writing code against unverified
bytes and a prober that sends is already breaking it. It listens while a human
drives the device from its own front panel (this originally read "while a
browser running Ray Bellis's e-remote drives the device" — that was the plan
and it was not taken; see RESOLUTION_NOTES §3),
timestamps every frame, separates panel from editor traffic (and from
Proteus/Morpheus, §4), supports typed markers so a capture records *what the
operator did*, and diffs consecutive same-length frames to expose which byte
offsets move — the shape a delta-encoded screen has. `--analyse FILE` re-runs
the summary offline, so the thinking happens after the rack is closed.
Analysis is unit-tested synthetically (`tests/test_panel_capture.py`), because
a probe that mis-parses does not crash — it quietly wastes the session.

### Scope decision, 2026-08-14: **no screen mirror.** Not negotiable on taste

**SUPERSEDED 2026-08-16 — the mirror was built (`k`).** Kept for the record.
It was built from this project's own captures of the device echoing physical
presses; e-remote's traffic was never captured, then or later.

The reason it was reversed is not that the objection stopped mattering. eosed exists to support mpc2emu, and the measurements mpc2emu needs -- stepping a parameter across its range, then reading back both what the machine SAYS it is and what comes out of the audio outputs -- cannot be automated without driving the panel and reading the screen. The mirror is measurement apparatus first; that it also happens to be useful at the desk is a by-product. Everything measured on 2026-08-17/18 — the filter-type table,
the envelope rate and sustain laws, the stereo and single-cycle confirmations —
was obtained by scripts driving the panel and reading the mirrored screen. None
of it was reachable any other way.

The first capture succeeded (§26) and the temptation it creates is to keep
going straight: decode the bitmap fully, mirror the LCD, inject keypresses.
**That is Ray Bellis's e-remote, rebuilt from its own traffic.** Permitted —
the protocol is E-mu's, the facts are E-mu's, and §3 has always limited us to
wire observation and never his code — but it is poor form, and it is not what
this project is for. Ruled out deliberately, recorded so a later session does
not drift back into it by momentum.

**The model is s3ked.** s3ked does not mirror the Akai's screen. It finds the
specific register an operation needs and drives it from its own UI. eosed
should do the equivalent, which for this feature means:

* **Browse from the disk image, not from the device.** The banks are written
  to HD images here before they are ever mounted, so the directory is already
  known off-device. mpc2emu parses E4B; `emu3fs`/`emu3bm` cover the EIII side.
  Reading the image gives a real browser with names, sizes and slots — no
  bitmap parsing, no OCR of a 240×64 screen.
* **Use the panel protocol for one thing: select bank N and fire the load.**
  A key-code table and a deterministic navigation sequence, not a display
  decoder.

This is a large reduction in scope *and* in risk. It also inverts the ordering
this item carried a few hours ago ("screen readback first"): that was correct
for a mirror and is wrong for this. The screen is still worth *reading* for
confirmation — verifying the machine is on the page we think it is before
firing a load — but confirming a known layout is a far smaller problem than
decoding one well enough to browse from.

### RE method changes too: capture the front panel, not e-remote

§3 records that the E4XT **echoes its own front-panel activity** — every
physical press emits a down/up pair. So the key-code table can be built by a
human pressing keys on the actual machine while `probes/panel_capture.py`
listens, with e-remote nowhere in the loop. It was only ever a convenient
traffic source, never a necessary one.

Open question for the next session, and the only thing that might still need
his tool: whether the device echoes unprompted, or whether something must
first "open" remote communication. If it echoes cold, the dependency is zero.

**Also worth simply asking him.** Ray Bellis published fragments of this RE
voluntarily. Saying what this project is building and asking whether he minds,
or whether he would share what he knows, costs nothing and is the difference
between deriving from someone's work and collaborating with them. Either way
he is credited in the README's third-party table.

Still needs live hardware for every part of it.

## Editor TUI (Phase 2 of the plan) — built, read paths verified live

**This work (originally the `extended_view` branch, long since merged and the
branch deleted) reworked the TUI from a 2-pane (Preset |
Parameters) to a 4-pane layout: Preset | Voice | Parameters | Samples**,
with a `v` key to toggle between that and the original compact 2-pane view
(default: compact; remembered across restarts against real hardware, see
below). Built autonomously, then live-tested against the real E4XT Ultra —
**a real, two-stage bug was found and fixed in the process** (see
RESOLUTION_NOTES §11): the live `preset_num_voices`/`voice_num_szones`
commands do not answer with plain counts, and only careful cross-checking
(a real preset's own dump file, plus a parallel finding in the sibling
mpc2emu project about the analogous on-disk field) got the fix right after
a first attempt got the direction backwards. Verified correct against two
different real presets, one single-voice-style and one where both voices
are multisample sharing the same 3 samples.

`eosed/app.py`, four `DataTable`s in one `Horizontal`:
- **Preset** (`#presets`) — unchanged from `main`: paged, on-demand catalog
  scan, page size dynamic to the pane's height (see `main`'s entry below),
  `g` to goto, `o` to rename, `m` for the Master menu.
- **Voice** (`#voices`) — every voice of the selected preset (`V1`..`Vn`,
  1-based display / 0-based `VOICE_SELECT`), with a "single"/"multi (N)"
  zone hint derived by actually walking zones (see below), not by trusting
  a count field. Not paged — which is now known to be a real question and
  not a hypothetical: a commercial bank's drum kits have **94 voices**
  (RESOLUTION_NOTES §19), so this pane renders 94 rows in one go. It works,
  but the "voice count is expected to be small" assumption it was built on
  is false, and paging (or at least a scroll hint) is worth revisiting.
- **Parameters** (`#params`) — the selected voice's full `voice.*` group
  (146 params) if a voice is selected, else the preset's GLOBAL group (22
  params). Selecting/deselecting a voice (click a voice row, or `escape` to
  go back) swaps this automatically.
- **Samples** (`#samples`) — **derived, not a browsable bank**: resolves
  whichever voice(s) are in scope down to the raw sample number(s) they
  play and looks up each one's name (`EosedApp._resolve_sample_rows`,
  `_voice_sample_info`). Whole preset in scope (no voice selected) sums
  across every voice, deduped by sample number with a "used by" column
  listing which voice(s) (e.g. `V1,V3`); one voice in scope narrows to just
  that voice's zone(s). Read-only — no rename/edit from this pane.
- Edits a parameter's value in place (device-fetched min/max/default shown),
  renames a preset, and a modal arm-then-fire Master screen (Delete
  Preset / Erase RAM Bank / Erase All RAM Presets / Erase All RAM Samples —
  never bound to a single keypress). All MIDI I/O runs off the UI thread,
  serialized by a lock (`EosBridge` is not thread-safe). The suite passes
  against `--demo`/`DemoBridge`, including a dedicated fake-bridge test for
  the multi-voice/multi-zone sample-aggregation logic (DemoBridge itself
  only ever has 1 voice/1 zone, too simple to exercise dedup) and tests for
  the view-toggle's default/persistence behavior.

**Two live-caught follow-ups to cache-all, both from the same session it
shipped in.** First: the sample-name catalog pass (the second half of
`_run_full_sweep`, after the preset walk) always ran the complete 0-999
range even when the preset walk itself had just bailed out early via the
consecutive-empty-presets heuristic — inconsistent, and slower than it
needed to be for the same reason the heuristic exists at all. Fixed by
replacing the single `catalog_samples(...)` bulk call with the app's own
per-sample loop (mirroring the preset loop's shape exactly), using
"did `get_sample_name` find anything" as the per-item signal and honoring
the *same* `gap` value — a sample without a name is just as valid an
"empty" signal as a preset without voices. Only applies when that gap is
actually active (`"structure"`/`"full"` depth); `"names"` depth's "always
a complete catalog" guarantee is unchanged. `_catalog_scanned_upto["sample"]`
now reflects wherever that pass actually stopped, not an unconditional
"the whole range", and the status note gained a second clause
(`"; sample names stopped at N after G consecutive unnamed samples"`)
when it fires. Second: `u`'s results (`_show_sample_usage_results`) were
only ever written into the `#samples` pane and the status bar's own
5-item truncation — but `#samples` is hidden in compact view (the
default), so a compact-view user got nothing but that truncated one-liner
for anything past 5 matches. Fixed the same way `select_sample` already
solved the identical problem for plain sample info: mirror the full match
list into `#params` too, which is visible in both view modes — `preset N`
/ name pairs, non-editable (`_current_param_ids = []`, same guard
`action_edit_value` already has for other borrowed-`#params` rows).

**Third live-caught follow-up, live-hardware-only (never surfaced
synthetically), took three attempts before the actual root cause was
found: the sample-name early-stop fix above still didn't bail out early
on real hardware.** Reported live: S195 was the first genuinely empty
sample slot on the bank in hand, with nothing after it, yet the
sample-name pass still ran the complete 0-999 range, twice over across
two different guessed fixes. **First attempt** assumed the device pads
an empty slot with plain ASCII spaces and checked `fetched.strip()` for
blankness — still ran the full range live. **Second attempt** assumed
some other non-whitespace filler (NUL, `0xFF`, decode-replacement
garbage) and checked for the absence of any letter/digit — also still
ran the full range live. **Actual root cause**, found only by directly
probing the raw wire reply instead of guessing a third byte pattern: an
empty sample slot's `SAMPLE_NAME` reply is a completely normal,
well-formed frame containing the literal, human-readable placeholder
name **`"Empty Sample"`** — confirmed for every unused slot probed, 0
through 999 — and `PRESET_NAME` has the identical device-wide
convention, replying `"Empty Preset"` for an unused preset. Both earlier
guesses failed for the same reason: that string is neither blank nor
free of letters, so neither heuristic could tell it apart from a real
name without ever having been checked against what the device actually
sends. **Fixed** by comparing the fetched sample name (case-folded,
stripped) against this exact placeholder and treating a match as empty
— `eosed.app._EMPTY_SAMPLE_NAME`. **Verified live**, precisely: a
direct, read-only run of the app's own sweep against the real E4XT
Ultra stopped the sample-name pass at sample 204 — exactly 195 (the
first empty slot) plus the default 10-consecutive-empty gap. `get_preset_name`
wasn't touched at any point: its own early-stop signal already comes
from the voice walk (§12), never from name-lookup success, so it was
never exposed to this failure mode in the first place — though it does
mean the plain preset/sample bank browser has always displayed
"Empty Preset"/"Empty Sample" as literal text for unused slots, a
pre-existing cosmetic quirk not introduced by cache-all and not yet
addressed. Full account: `docs/RESOLUTION_NOTES.md` §13.

**Fourth live-caught follow-up: `cache_depth = "full"` cached each
preset's own data but not any voice's, so `v` (browse voices) still did a
lot of fresh MIDI work post-sweep.** Reported live: preset selection had
gotten instant, but browsing into a voice hadn't — each voice's own
146-parameter group was never part of the sweep at any depth. Asked
whether to fold this into `"full"` depth, add a separate depth level, or
leave it out for now; chose folding it into `"full"` (it's already the
"fetch everything" tier). `_run_full_sweep` now also fetches every
voice's parameter group during the same per-voice walk that already
determines zone/sample structure — `EosedApp._voice_details`, keyed
by `(preset, voice)`, storing `(sample numbers, param values)` so
`_load_voice_detail` can skip *both* the zone re-walk and the param
fetch on a cache hit, not just the latter. Structurally the most
expensive addition yet — one batched request per **voice**, not per
preset — so `"full"`-depth sweeps on banks with many multi-voice presets
(drum kits, layered patches) will take noticeably longer than before this
fix; `"structure"` depth is unaffected and remains the cheaper,
voice-params-excluded tier. Cleared uniformly by
`_invalidate_write_sensitive_caches`, same as every other cache-all
cache.

**Live-caught: the preset/sample pane only ever showed one fetched
window, with `g` (goto) as the only way to reach past it — not a
regression, this has been true since the very first commit, but easy not
to know exists.** Reported live as "presets and samples only show the
first 50 entries now — and no way to get further down"; confirmed `g`
does work, but the user recalled other navigation existing before. Two
additions, not mutually exclusive:

- **Infinite-scroll extend**: scrolling near the bottom of the currently
  loaded rows — by arrow keys, mouse wheel, or anything else that moves
  the cursor, not a dedicated key — fetches and *appends* the next
  `BROWSER_EXTEND_CHUNK = 50` entries in the background
  (`EosedApp._extend_bank_page`, triggered from
  `on_data_table_row_highlighted` once the cursor is within
  `BROWSER_EXTEND_THRESHOLD = 10` of the end of what's loaded). Reuses
  `_catalog_cache`/`_catalog_scanned_upto` first if a cache-all sweep
  already covers the range — no MIDI at all in that case. One in-flight
  extend per bank at a time (`self._extending`), guarded on the UI thread
  before the background worker is dispatched, not inside it.
- **`PageDown`/`PageUp`**: jump a whole page forward/back, replacing the
  page (same as `g`, just without typing a number). `DataTable` already
  binds these two keys itself (scrolling the cursor within whatever rows
  are currently loaded) — overriding them on the shared
  `_FillWidthDataTable` class would have also stolen them from the
  146-row Parameters table, where that built-in scrolling is exactly
  what's needed. Fixed by giving the bank browser its own subclass,
  `_BankBrowserTable`, that redefines just those two keys for itself.

**`a` — cache-all: one deliberate sweep filling every cache the app has,
built directly on top of `u`'s reverse-lookup sweep rather than as a
separate walk.** Motivation: every cache before this was narrow — the
paged bank browser only ever held its currently-visible window, the
single-slot preset-overview cache only remembered the *last* preset
viewed, and `u`'s own full-bank sweep threw away almost everything it
fetched, keeping only the sample→preset mapping. So the same preset's
voices/zones got re-walked over MIDI every time it was revisited, and a
complete sweep couldn't be reused for anything but the one sample that
triggered it. `EosedApp._run_full_sweep(depth)` is now the single
shared walk both `u` (always at `"structure"` depth, for one sample) and
`c`/`C` (`action_cache_structure`/`action_cache_everything`, at fixed
"structure"/"full" depths respectively) run —
returning a dict the caller decides whether to promote into the real
caches (`EosedApp._promote_sweep_result`) or, for a cancelled sweep,
discard (same "no way to tell 'not found' from 'not reached'" reasoning
`u` already had). Three depths, `cache_depth` in `config.toml`:
`"names"` (preset + sample name catalogs only — cheap, and, having no
voice signal to drive the early-stop heuristic from, always a complete,
uninterrupted sweep regardless of the configured gap), `"structure"`
(adds the voice/zone/sample walk — `_preset_overviews` keyed by every
preset now, not just one, and the `u` index), `"full"` (**default** —
also each preset's GLOBAL values, one batched `get_parameters` call per
preset). `cache_all_on_startup = true` runs it automatically right after
the first bank page loads; both settings are read-only from `config.toml`
(no `save_*`, matching `sample_usage_early_stop`) and skipped for
`--demo`, same "demo touches no real local state" convention as the
other view/scan settings — the `c`/`C` keys themselves still work in demo.

**Keys and startup defaults reworked once §20 measured the real cost.**
`a` (one key, sweeping at the configured `cache_depth`) became two keys at
*fixed* depths — `c` = "structure", `C` = "full" — so each means a
predictable amount of work; `cache_depth` now only governs the startup
sweep. `x` took over "clear usage cache" from `c`. On startup, **neither sweep
runs by default**: `cache_all_on_startup` stays off (1h 44m at `"full"`)
and the new `cache_structure_on_startup` is off too (~23 min) — a big
improvement over `"full"` but still far too long to impose on someone who
launched the app to look at one preset. Both are explicit opt-ins, neither
prompts, both announce their estimate, and `escape` cancels either.
**Deliberately never persisted to disk**: a front-panel edit is invisible
to this app, so a saved cache could confidently serve data that no longer
matches the device — every launch genuinely re-scans.

A real gap surfaced while wiring this up: `select_preset` (Enter/
double-click) had *never* consulted the preset-overview cache at all —
only returning from a voice/link view or the Sample bank did
(`_show_or_reload_preset_overview`). With only ever one preset cached at
a time this didn't matter much, but once `_preset_overviews` became a
real multi-preset dict (keyed by preset number, filled in wholesale by a
cache-all sweep), a plain preset selection clearly needed to check it
too — otherwise the entire feature would do nothing for the most common
navigation path. Fixed by routing `select_preset` through the same
`_show_or_reload_preset_overview` reuse logic; `r` (`action_refresh`)
still forces a genuine re-fetch regardless, calling `_load_preset_overview`
directly. A `"structure"`-depth cache entry (no GLOBAL values) is upgraded
to a full one in place on first access rather than re-walking everything
just to fetch the missing globals (`_load_preset_globals_only`).

`load_bank_page` (the paged bank browser) also consults the same
catalog-name cache before hitting the device for a window it's never
paged to on its own — `_catalog_scanned_upto` tracks how far each bank
has actually been swept (a sparse `{number: name}` dict can't otherwise
tell "no name here" from "not scanned yet"). `action_refresh` (`r`)
passes `force=True` to bypass this deliberately, so an explicit refresh
still means a real one.

`_invalidate_write_sensitive_caches` clears every one of these caches
uniformly on any write — a parameter edit, a rename, or a Master action —
same "don't reason out which specific writes are safe to leave alone"
principle already applied to the preset-overview and sample-usage caches
before this.

**How "is this voice a multisample, and how many zones" is actually
determined** (not from `voice_num_szones` — see RESOLUTION_NOTES §11 for
why that field can't be trusted at all): a voice's own `E4_GEN_SAMPLE`
(no zone selected) reads the spec's `0x3FFF` sentinel if and only if it's
genuinely multisample; if so, zones are walked from 0 (`SAMPLE_ZONE_SELECT`)
until one reads `E4_GEN_SAMPLE == 0`, empirically the clean, consistent
signature of "past the real data" in every case tested — capped at 256
zones as a safety bound, not a trusted count (was 32, which real content
overran: a commercial bank has a multisample voice with 62 zones — see
RESOLUTION_NOTES §19).

**Known perf caveat, not yet tuned:** selecting a preset walks *every* voice
sequentially (a `VOICE_SELECT`/`SAMPLE_ZONE_SELECT` context switch + a
parameter read per zone) to populate the Voice and Samples panes together
in one pass. Fine for the handful of voices in the two real presets tested
so far; untested against a preset with many voices/zones (a big multisample
drum kit, say) — could be slow (each step is a sequential MIDI round-trip,
same caution as the preset catalog scan) and may need a cap or lazy-per-voice
loading if that turns out to matter.

**That walk is now cached, live-caught as a real slowness bug:** going
voice/link → `escape` back to the preset-level view used to re-run the
*entire* walk above from scratch, even though nothing about a voice/link
drill-down changes what it would recompute — noticeably slow in practice
against real hardware for anything but a trivial preset. Fixed:
`EosedApp._preset_overview_cache` holds the last `_load_preset_overview`
result, reused by `action_back_to_preset` when it's for the same preset (no
MIDI at all); invalidated by every real write, uniformly and on principle
rather than reasoning out which specific ones are "safe" to leave alone —
a parameter edit (`_apply_edit`), a Master action (`_fire_master_action`,
destructive), and a rename (`_apply_rename`, even though a rename only
touches the name, not voice/zone/sample data). An explicit `r` refresh
always bypasses the cache regardless, and the parameter-edit dialog's
starting value is always a fresh `get_parameter` read, never taken from
this (or any) cached display — editing was never at risk of acting on
stale data even before this cache existed. Selecting a *different* preset
always still does a full fetch — this only memoizes "the same preset, no
time elapsed, nothing written."

**`p`/`s` Preset/Sample bank-switch is back, reconciled with the 4-pane
layout** — it was cut when the 4-pane rework first landed (reasoning at the
time: "Samples" is now a used-by view, not a second browsable catalog, so
the two seemed redundant), but cherry-picking that rework onto `main`
(which had the bank-switch) surfaced that this quietly deleted a whole
working feature rather than superseding it — they're not actually the same
thing: the bank-switch lets you browse/rename the *raw sample bank*
(names, independent of any preset), while the Samples pane shows *what a
preset/voice uses*. Both now coexist: `self.bank` ("preset"/"sample")
governs only what the `#presets` pane itself browses. `current_preset`/
`current_voice`/`current_link` are never cleared by a bank switch (so
switching back restores exactly what was showing, reusing
`_preset_overview_cache` when possible — no re-fetch), but the *display*
of the Voice/Parameters/Samples-used-by panes clears immediately on
switching to the Sample bank (live-caught: leaving stale preset data
visible while browsing an unrelated catalog read as a bug, not as
"nothing to do with this view yet"). `o` (rename) and `g` (goto) are
bank-aware, same as before the rework. No dedicated tests existed for this
feature even before it was cut (only smoke-tested manually) — added proper
coverage for it now.

**Selecting a sample now shows what little info exists for it, instead of
stale data or a refusal-sounding message.** `select_sample` used to leave
the Parameters pane showing whichever preset/voice was last viewed and set
a status message ("no directly-editable parameters...") that read like an
edit request had been declined — selecting a sample isn't a request to
edit it. Confirmed by re-checking the spec text directly (searched again
for length/rate/stereo-mono/loop, found nothing) that a sample's number
and name really is the ceiling for this protocol; anything else (loop
points, root key, sample rate) needs the separate, unimplemented MIDI
Sample Dump Standard. Now clears the pane and shows those two fields as
plain, non-editable rows; `action_edit_value` guards against a `ValueError`
from these rows' non-numeric keys instead of risking a crash if Enter is
pressed on one.

**`u` — opt-in reverse lookup, "which presets use this sample."** Symmetric
with the Samples pane's forward direction, but far more expensive: a full
preset-range sweep, each preset needing at least a per-voice (and, for
multisample voices, per-zone) sample read — the same walk
`_load_preset_overview` already does for one preset, repeated across the
whole range. Deliberately not automatic; shows live
progress in the status bar and is cancellable via `escape`
(`_sample_scan_active`/`_cancel_sample_scan`). Scans
`SAMPLE_USAGE_SCAN_RANGE = range(0, 1000)` — the *full* `PRESET_SELECT`
wire range, not the `range(0, 128)` default `catalog_presets`/
`catalog_samples` use elsewhere. That default was believed "confirmed
populated" on this hardware from an earlier live sweep, but that sweep's
own upper bound was arbitrary (matching the code default, not a proven
capacity) — live-caught while building this: a real bank on hand was found
to hold presets up to at least P269. Silently under-scanning here would
have given a confident, wrong answer to exactly the question this feature
answers. **Live-timed at ~4 minutes for a full 0-999 sweep** on that same
bank — confirmed to genuinely reach 999, not hang or error out partway.

A *complete* sweep (or one that stops via the early-stop heuristic below,
as opposed to a user cancellation) records every sample it saw along the
way, not just the one that triggered it, into
`EosedApp._sample_usage_index` — every later lookup, for *any* sample,
is then instant with no MIDI at all, until a real write invalidates it
(`_invalidate_write_sensitive_caches`, shared with `_preset_overview_cache`
and called from `_apply_edit`/`_apply_rename`/`_fire_master_action`
uniformly, same "don't reason out which writes are safe to leave be"
principle). A cancelled/partial sweep's findings are shown once but not
persisted as this index — no way to tell "not found" from "not scanned
yet" for whatever a cancellation didn't reach.

**Early-stop heuristic, configurable in `config.toml`.** Bails out after
`SAMPLE_USAGE_EARLY_STOP_DEFAULT = 10` *consecutive* no-voices presets —
a strong "past the real data" signal, not a certainty (a bank with an
unusually large deliberate gap could have a real preset sitting past the
stop point that this would then miss; this is a heuristic the user
explicitly accepted the tradeoff on, not a discovered protocol fact).
`eos.bridge.load_sample_usage_early_stop` reads a user-edited (not
app-written) `sample_usage_early_stop` key: an int overrides the
threshold, the literal string `"fullscan"` disables early-stop entirely.
Sharing `config.toml` with the port cache and view-mode preference via the
same read-modify-write helpers, and skipped for `--demo` for the same
"demo touches no real local state" reasoning as those two.

**Two follow-ups from live testing:** the final status now names the exact
preset the sweep stopped at (`stopped at preset N after ...`/`cancelled at
preset N, partial`/`full sweep to preset N`) — live-caught as a gap once
the status line's *progress* text (which preset it's currently on) had
already scrolled past by the time a run finished, leaving no way to tell
whether an early stop landed somewhere sensible without re-running it.
`x` (`action_clear_sample_usage_cache`) manually clears
`_sample_usage_index`/`_sample_usage_scanned_range` on demand — previously
the only way to force a fresh sweep was an actual write.

**`preset_num_voices`'s "-1" correction (§11) turned out to be wrong too —
abandoned entirely, same fix shape as `voice_num_szones`.** Live use of `u`
against the user's real 270-preset bank appeared to stop early at a genuine
content gap; front-panel checks of P075 (1 voice/2 samples,
audible) and P080 (1 voice/5 samples, audible) proved
otherwise — both raw `preset_num_voices` values were `1`, which the `-1`
fix turned into a false "no voices". A timing/race explanation was checked
and ruled out first (a 4-variant probe: with/without re-setting
`PRESET_SELECT`, with/without a 150ms settle delay, twice each, across
presets 65-100 — all identical). The real cause: like `voice_num_szones`,
this count field simply isn't reliable, full stop — not off by a different
constant, not fixable by another correction attempt. Found the same kind of
signal §11 already used for zones, one level up: a voice's own
`E4_GEN_SAMPLE` reads a consistent `0x3FFE` (16382) when that voice index
doesn't exist, distinct from the `0x3FFF` multisample sentinel. Fixed by
dropping `preset_num_voices` from every call site (`_load_preset_overview`,
`_start_browse_voices`, the `u` scan) in favor of walking voice indices
directly via `EosedApp._voice_sample_info`, which now returns `None`
to signal "stop" instead of trusting a count; capped at
`_MAX_VOICE_SCAN = 256` as a safety bound, same non-trusted-count pattern
as `_MAX_ZONE_SCAN` (was 64, and real drum kits run to 94 voices — the
truncation was silent, see RESOLUTION_NOTES §19). `eos.bridge.EosBridge.preset_num_voices` now returns
the raw wire value unmodified (kept for API completeness only, like
`voice_num_szones`); `DemoBridge` updated to answer `-2` for any
non-zero `VOICE_SELECT` so demo presets (all single-voice) still walk
correctly. Full writeup: RESOLUTION_NOTES §12. This also explains the
early-stop false trigger above — presets that genuinely had voices were
being counted as empty, manufacturing a "gap" that never existed on the
device.

**View toggle is `e` (Extended view), not `v`** — after the first pass
reused `v` for the view toggle (displacing "browse voices"), live testing
showed that regressed a real, previously-working flow: with no persistent
Voice pane visible in the (now-default) compact view, there was no way to
select a voice at all. Fixed by moving the toggle to `e` and restoring `v`
as a modal voice-select prompt (`action_browse_voices`, same front-panel
1-based numbering as before, reusing the same `select_voice` the Voice pane
itself calls) — works in *either* view mode, not just extended. `l`
(browse Links) came back the same way, symmetric with `v`: a modal prompt
into `select_link`/`_load_link_detail`, showing that link's parameter group
in the Parameters pane; `escape` clears either a selected voice or link
back to the preset-level GLOBAL view. There is still no persistent Link
*pane* (no "used by" or samples concept applies to a Link) — just the modal,
matching how Links worked before this branch existed. The `escape` binding
is now visible in the footer (was `show=False`) — hiding it was itself a
live-caught discoverability bug: there was no on-screen hint for how to
back out of a selected voice/link at all. Both the Voice and Link prompts
also now skip straight to the only entry when there's exactly one (e.g.
DemoBridge's single voice) instead of asking a question with one possible
answer — read-only navigation, so no downside to it being wrong compared
to the prompt it replaces (which offered the same single choice anyway).

**`preset_num_links` needed its own live check, not the same fix as its
`preset_num_voices` sibling** — restoring `l` surfaced this immediately:
pressing it against preset 0 (independently known, from its own saved dump
file, to have exactly 1 real link) reported "no links". The bridge method
had inherited a `-1` correction extrapolated from `preset_num_voices`
(same command family, same wire shape) with no independent test of its
own — turns out `preset_num_links`'s raw wire value is already the plain,
direct count (confirmed: raw `1`, matching the known real answer of 1
exactly). Fixed by dropping the correction for that method specifically;
see RESOLUTION_NOTES §11 for why this is now the *third* time in this
section that "same family as an already-confirmed sibling" turned out not
to be evidence of anything.

**"Used by" in the Samples pane used to list a voice once per zone, not
once per voice** — also caught live (preset 0, voice V2, 16 real zones):
a voice with several zones sharing one underlying sample (a normal
pattern) showed that voice repeated once per matching zone
(`V2,V2,V2,V2,V2`) instead of once. Fixed in
`EosedApp._resolve_sample_rows` (a set instead of a list per sample
number).

**View toggle (`e`) and its persistence:** `EosedApp.compact_view`
defaults to `True` (compact 2-pane: Preset | Parameters) on a fresh install
with no config yet; toggling is remembered in `config.toml` (see
`eos.bridge.load_compact_view`/`save_compact_view`, sharing that
already-gitignored file with the MIDI port cache via a proper read-modify-
write so the two settings can't clobber each other) so it survives a
restart — but **only against real hardware**. `--demo` deliberately never
reads or writes that file at all, matching the project's "demo touches no
real local state" convention and avoiding the exact test-pollution bug
docs/RESOLUTION_NOTES.md §7 already caught once for the port cache.

**Write actions (edit/rename/Master) default to disabled against real
hardware** — `--allow-write` is required to enable them (always on for
`--demo`). **The parameter-edit and rename paths are now verified live**
(2026-07-31, RESOLUTION_NOTES §18), in exactly the prescribed order: one
low-stakes parameter edit + read-back first, then the full parameter set,
then renames. A Master action has still never been fired against real
hardware, and should only ever be tried by hand with a fresh backup — never
from a script, and never as the first thing tried in a session.

**`w` — runtime write-mode toggle, on top of `--allow-write` rather than
instead of it.** `--allow-write` still sets the *starting* state (armed
for `--demo`, disarmed by default against real hardware) but
`action_toggle_write_mode` can arm or disarm `self.allow_write` at any
point during a session either way — never persisted, unlike
`compact_view`; every fresh launch starts back at whatever
`--allow-write` says. `_prompt_edit`/`action_rename`/`_on_master_result`
needed no changes at all: all three already re-read `self.allow_write`
fresh at the moment of the action rather than caching it, so the toggle
"just worked" for gating once it existed. The header bar
(`Header.-write-armed` CSS class, `background: $accent` — the E4XT
badge's own red) turns red while armed and back to its default grey
when disarmed, toggled from `_update_write_mode_indicator` (called from
both the toggle action and `on_mount`, so a session launched already
armed via `--allow-write`/`--demo` shows red immediately, not only after
the first toggle). The existing "writes disabled" status message on a
blocked edit/rename/Master attempt now points at `w` instead of only
`--allow-write`.

**Live-caught: a remote rename worked (the device's own data changed)
but the front-panel LCD only showed it after touching the preset
physically — expected per spec (`PRESET_SELECT` is "independent of the
front panel's own selection"), but the user asked whether *anything*
could force a redraw.** Checked exhaustively for a SysEx command to do
this — every `eos.messages.Command` byte, the raw specification text
(searched "screen"/"panel"/"LCD"/"display"/"refresh"/"redraw" — the only
hit is the spec's own stated design goal that the remote editor
*replaces* the front panel display, not drives it) — confirmed there
isn't one. **The user's own suggestion, a plain MIDI Program Change,
turned out to be exactly right** — an ordinary channel voice message,
not part of this SysEx protocol at all, the same thing a keyboard player
sends switching patches, and it genuinely does make the device select
the preset and redraw its own LCD.

`EosBridge.send_program_change(preset, *, channel=None)`: Bank Select
MSB always 0, LSB selects which 128-preset block, Program Change picks
within it (per the user's own description of the scheme, confirmed
live) — `channel` defaults to reading the device's live
`MIDIGLO_BASIC_CHANNEL` rather than assuming 0. **First live attempt
looked like a bank/program math bug but wasn't**: commanding preset 52
landed on P049 (off by exactly −3, not a classic ±1 index mismatch),
then a second Program Change to preset 3 did nothing at all. Ruled out
MultiMode first (`MIDIGLO_MIDI_MODE` read back as `0` = omni, not
multi) before finding the real cause: unlike SysEx (already throttled by
`ThrottledOut`), the three plain channel messages were being sent with
*zero* gap between them, and the MIDI interface dropped/misprocessed
rapid ungapped channel messages. Fixed by inserting the same `SEND_GAP`
(50ms) already used for SysEx between each of the three messages.
**Re-verified live across three presets spanning two banks** (10, 52,
300) — each landed on the exact commanded number. Full account:
`docs/RESOLUTION_NOTES.md` §14.

`EosedApp` now sends one automatically on every `select_preset` (no
key binding), gated by `self._send_pc_on_preset_select` —
`send_pc_on_preset_select` in `config.toml`, user-edited like the other
cache-all-adjacent settings, defaulting to **on** (unlike
`cache_all_on_startup`) since it's cheap and has no real downside for a
session actually being played on the hardware. `--demo` never reads
`config.toml` for it (same convention as the others) but the feature
still defaults on there too — `DemoBridge.send_program_change` is a
plain no-op, matching the "demo never opens real MIDI" rule while still
exercising the same call path. There is still no way to *read back*
which preset the device currently has selected via any SysEx query —
probed directly (`PRESET_SELECT` before/after) and confirmed it stays
unaffected — so verifying a Program Change landed correctly still needs
the physical front panel, not something this app can check for itself.

**`z`/`Z`/`h` — an in-memory undo log, step and full undo, and a change
history.** Every parameter edit and rename to the selected preset is
recorded with the value it replaced *and the selection it was made under*
(voice/link/global). The protocol is stateful — a parameter id means "this
voice's field" only while `VOICE_SELECT` points at it (§11) — so an undo
re-selects that scope before writing the old value back; without that it
would land on whatever happens to be selected at undo time, the same
wrong-target write class §15 records against live automation. That is also
why scope is a *column* in the history rather than a suffix on the
parameter name: the same id under two voices is two different fields.
Pending count goes in the header subtitle (`preset 12 · Δ3`), not the
status line, which any load or scan overwrites. Scope is deliberately
in-memory and per-preset, discarded when a different preset is selected: a
remote edit only lives in the device's RAM until the bank is saved to disk
on the machine, so reloading or power-cycling is the real "undo
everything" and nothing here needs to survive a restart. Undo is a write,
so it is gated behind write mode exactly like an edit.

**`+`/`-` — nudge a value from the Parameters pane, arrow keys inside the
dialog.** Typing the full number was previously the only way to change a
parameter. `+`/`-` (with `=` as an unshifted `+`) step the highlighted
parameter by 1 without opening anything; inside the edit dialog the arrow
keys step by 1 and PageUp/PageDown by 10. Arrow keys are deliberately
*not* bound in the pane itself — there they move the row cursor, the one
navigation the app cannot give up. Nudges clamp to the device's own
03h/04h reported range rather than the static table (standing project
rule), fetched once per parameter and cached since that range does not
change under us, and cleared alongside the other write-sensitive caches.
Consecutive nudges of the same parameter in the same scope collapse into
one undo entry keeping the value the run *started* from — holding `+` for
ten steps is one edit as far as `z` and the history are concerned. A
refused nudge (already at the limit) records nothing.

**Parameter values are described in human terms far more widely now**
(`eos/params.py`, `describe_value`), extending what filter types and
envelope stages already did to every family where the raw wire number is
meaningless on its own — so the Parameters pane can be checked against the
front panel directly. Key fields show note names (the octave offset is
*not* scientific pitch: the spec's own "60 = C3" and "C-2 → G8" both pin a
-2 offset), and the matching `*FADE` fields are deliberately excluded,
being widths in semitones rather than keys. Also: the link filter flags
and other 0/1 switches, SCSI termination and Combine L/R (which the spec
states with *inverted* sense, 0 = on, kept that way rather than silently
normalised), amp envelope depth in dB, glide curve, LFO sync, velocity
curve, magic preset, MIDI channels shown 1-based as panels display them,
and the -1 = off/none sentinels. **One open inference:**
`E4_LINK_INTERNAL_EXTERNAL` — the SysEx spec gives its 0..16 range but
never says what the values mean; the EOS 4.0 Software Manual's "Link Type"
section supplies "an internal preset or an external MIDI device" and "up
to 16 external MIDI devices", which is exactly 1 + 16. Marked INFERRED in
the docstring; **the off-by-one direction (channel 1 at value 1 vs value
0) is the assumption doing the work and still needs a live check** against
the panel's own Link Type field — the same check `FX_A`/`FX_B_ALGORITHM`
have been waiting on.

Not built: preset **restore** in either format (NEW-format *dump* is built —
see the Preset restore section), and anything from the panel/mirror protocol
(see the section above — that's out of scope for this TUI entirely).

**On `main` (not this branch): presets/params pane resizing — fixed,
verified live.** The two panes weren't following terminal resizes
consistently (presets looked frozen at a fixed page size while params
looked like it scaled) — root cause and fix in RESOLUTION_NOTES §10.
Confirmed live against the E4XT Ultra: resizing the terminal now visibly
changes how many presets are fetched/shown per page, and shrinking back
down doesn't re-hit the device for names it already has. This branch
carries the same dynamic-window/resize-debounce/shrink-cache-reuse logic
for the Preset pane (`BROWSER_MIN_WINDOW`/`BROWSER_FETCH_MULTIPLIER`/
`BROWSER_RESIZE_SETTLE`, `_desired_browser_window`, `_settle_browser_resize`)
unchanged — only demo/pytest-verified again here, not re-tried live, since
this branch's work happened without hardware access.

**Fixed: the key-hint bar now wraps to as many lines as the terminal width
needs, instead of Textual's built-in `Footer`.** Now that the cache keys
joined `q p s g r o v l u c e m` plus `enter`/`escape`, `Footer` (hardcoded
to `height: 1` with horizontal scroll on overflow, not wrap — see
`textual/widgets/_footer.py`'s `Footer`/`FooterKey` `DEFAULT_CSS`) was
getting crowded, clipping/scrolling entries instead of reflowing them.
Replaced with `eosed.app._KeyHints`, a plain `Static` that folds its
text to `self.size.width` via a new `wrap_blocks` helper — **ported from
the sibling k2kremote project** (`k2kremote/app.py`'s `wrap_blocks`, same
author, GPL-2.0-or-later; see `LICENSE`'s third-party table, updated
accordingly), which solved the identical problem for its own legend.
Unlike k2kremote's separate `keymap.LEGEND_BLOCKS` table, the legend text
here is derived directly from `BINDINGS` (`EosedApp._legend_blocks`,
`f"{key} {description}"` for every binding with `show=True`) — one source
of truth for both key dispatch and the displayed hint, nothing to keep in
sync by hand. Re-folds on its own `on_resize`, same per-widget pattern
already used by `_FillWidthDataTable`'s column-stretch, rather than
k2kremote's App-level `on_resize` override. Not a fixed two rows — however
many lines the fold actually needs at the current width and binding count
(1 on a wide terminal, 3+ on a narrow one). The binding count has since
grown from the 14 that motivated this to 22 shown, with `z`/`Z`/`h`, `+`/`-`
and `i` joining, which the fold absorbed without any change.

## Dump field order vs. E4B_FORMAT.md — partially verified

See RESOLUTION_NOTES §6/§7. **Confirmed live:** OLD-format dump payload =
`<preset number:2><name:16><global parms:44, 22 signed words in eos.params'
GLOBAL id order>` — all fields decoded to correct, in-range values against a
real preset. **Not yet confirmed:** the link/voice/sample-zone byte layout
beyond that prefix; a first attempt at walking it (assuming "58 bytes/link")
landed on an implausible result. Cross-check against
`../mpc2emu/docs/E4B_FORMAT.md`'s independently RE'd structure, or against
the NEW-format dump (whose header states per-section parameter counts
explicitly) once that path is live-verified.

## Two clients on one port: replies land in the wrong queue (OPEN, 2026-08-23)

**Status:** observed live, not yet handled in code.

With the eosed TUI running and a second client (a probe script) on the same
`ESI M4U eX` ports, a `get_parameter` came back raising
`ValueError: reply did not include parameter 223` — the frame in the queue was
a reply to the *other* client's request. ALSA delivers the device's replies to
every subscriber, so both clients see both conversations.

This is not a device fault and not a bug in the request/reply framing. It is
that `EosBridge._receive` takes the next frame and `get_parameter` then insists
that frame answers *its* question. `get_parameters` already tolerates it —
it matches ids and keeps receiving until every requested id has been seen —
so the fix is to make the single-parameter path behave like the plural one:
keep reading until the requested id arrives or the timeout expires, discarding
frames that answer something else, rather than failing on the first mismatch.

Worth doing regardless of multi-client use: it is the same shape as any
unsolicited or late frame arriving mid-conversation.

**Workaround meanwhile,** and it is the hardware rule anyway: one client at a
time. A probe that must run alongside the TUI should confirm its selector
before trusting any read, and retry on mismatch.

## Preset snapshot/replay — a stand-in, and why restore still matters (2026-08-24)

**Status:** `tools/preset_snapshot.py` exists and is verified end to end. The
real item above — protocol-level preset restore — is still open and this does
not close it.

The gap it covers: the E4XT's RAM does not survive a power cycle (§48), and
restore is not built, so **every hand-built reference preset on this bench has
been one power cycle away from gone.** A session's worth of parameter edits had
no way back except reading the values out of a chat log. That surfaced when a
bank needed loading from a new SCSI volume, which requires a card swap, which
requires a power cycle, which would have destroyed the reference preset the new
bank was to be compared against.

`capture` / `verify` / `replay` over the voice parameter table, 128 ids per
voice. Verified on a scratch preset: capture, perturb three parameters, `verify`
reported exactly those three, `replay` restored them, `verify` came back
identical.

**What it is not.** It replays voice parameters only — no sample zones, no
links, no preset-level fields, no name, no sample data. A preset whose character
lives in its zone layout does not come back from it. **Protocol-level restore is
still the right fix**, and this exists because that does not.

`verify` writes nothing, so checking a capture is free. A capture nobody has
restored from is a backup nobody has restored from.

## Filter envelope: the rate law is measured on a RISE only (2026-08-24)

**Status:** open, low priority, needs the bench. **Blocked on:** a filter-inert
subject with a filter cord deliberately added.

§43 fitted the filter envelope's rate byte to 0.9998 across bytes 24–88 — but
every point is a transition **upward to target 100**. Whether a *release*
segment obeys the same law has never been measured. The amplitude envelope's
segments were only shown to share one scale by measuring them (§63, §69), so
nothing entitles anyone to assume it here.

**Why it is worth having and not worth doing yet.** The sibling project's filter
release computes its span in dB, from a law that maps an *amplitude* sustain
byte to dB below peak, for an envelope §56 says the machine runs on a **cutoff
byte** scale. It still lands within 2 rate bytes across 30 combinations, worst
case 1.19× in time, because that unit error and §43's 0.52× distance difference
very nearly cancel. Correcting a 1.19× error against an assumed reference is how
it becomes a 1.4× one — so the measurement has to come first, and the amplitude
error it would have masked (1.8×) is already fixed.

**The procedure**, when it earns the time: the calibration bank is filter-inert
by design, so add a `FEnv → FilFreq` cord in RAM on one of its noise presets,
park the envelope so the release is the only stage moving, and time a downward
traversal at several rate bytes. §43's two measurement traps apply unchanged —
the corner's low end is invisible, so measure to a completion instant rather
than a t10, and keep the source stationary.

**It becomes urgent** if a listening test on the recalibrated bank reports
something the amplitude release does not explain. §70: the filter carries more
of what a listener hears than the amplitude envelope does at some pitches, so
that residual would look like an amplitude error and would not be one.
