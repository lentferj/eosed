<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
-->

# TODO

*What* is open. `docs/RESOLUTION_NOTES.md` tracks *how* to resolve each item.

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
corrected in `eos/params.py`. Still untested live, deliberately: the
Master/erase utilities (`71h`/`74h`/`75h`/`76h`), the device-global
`master.*` parameters, and *writing* `E4_GEN_SAMPLE`.

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
   **Blocked on:** a careful, isolated repro (not a repeat of the full
   traffic pattern) to identify the actual trigger, then either a fix or at
   minimum a documented "don't do this" in `EosBridge`'s docstring. Until
   then, treat any unattended/rapid live automation against a real E4XT as a
   crash risk, not just a cosmetic-desync risk.

## Panel/remote (screen-mirror) protocol — reverse engineering not started

A true k2kremote-equivalent (LCD mirror + front-panel button injection) needs
the undocumented `F0 18 7F 00 00 …` protocol, not the editor protocol this
repo currently implements. See RESOLUTION_NOTES §3 for what fragments are
already known (init/enable/close handshake, a button-press echo) and the RE
method to fill in the rest (display-frame encoding, full button-code table,
wheel encoding). Not started; requires live hardware + a browser running
Ray Bellis's e-remote as the traffic source to capture against.

## Editor TUI (Phase 2 of the plan) — built, read paths verified live

**This branch (`extended_view`) reworked the TUI from a 2-pane (Preset |
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
  serialized by a lock (`EosBridge` is not thread-safe). 296 tests pass
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
sweep. `x` took over "clear usage cache" from `c`. On startup,
`cache_all_on_startup` stays **off** by default (at `"full"` it is 1h 44m
on a large bank) and a new `cache_structure_on_startup` defaults **on**
(~23 min there, and it buys the everyday wins). Neither prompts, both
announce their estimate, and `escape` cancels either.
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
content gap; front-panel checks of P075 ("a bass preset", 1 voice/2 samples,
audible) and P080 ("another bass preset", 1 voice/5 samples, audible) proved
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

Not built: NEW-format dump/restore, and anything from the panel/mirror
protocol (see the section above — that's out of scope for this TUI
entirely).

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
grown from the 14 that motivated this to 20, with `z`/`Z`/`h` and `+`/`-`
joining, which the fold absorbed without any change.

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
