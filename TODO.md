<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
-->

# TODO

*What* is open. `docs/RESOLUTION_NOTES.md` tracks *how* to resolve each item.

## Live hardware verification

**Status: in progress.** `eoscli inquire`, `config`, `memory`, `catalog`
(full 0-127 sweep), and `dump` (OLD format) have all been run live against a
real E4XT Ultra — see RESOLUTION_NOTES §7. A real bug was found and fixed in
the process (the dump engine wasn't ACKing the header before expecting data —
see RESOLUTION_NOTES §7). Nothing has been tried live that *writes* to the
device yet.

- Not actually blocked on `~/mididings_e4xt.py`: autodetect finds the real
  hardware send/receive ports directly (bypassing mididings' filter chain
  entirely) rather than routing through it — see RESOLUTION_NOTES §7. No
  changes to mididings were needed or made.
- Still applies: one-session-at-a-time hardware access (same rule as
  k2kremote/mpc2emu).
- Remaining: the NEW-format dump path (`eoscli dump --new-format`) is
  untested live — its header-ACK handling in `dump_preset_new` is
  extrapolated from the OLD-format finding, not independently confirmed
  (RESOLUTION_NOTES §7). Also remaining: the OLD-format link/voice byte
  layout beyond the name+global-parms prefix is not yet correctly parsed
  (RESOLUTION_NOTES §6/§7) — a real captured sample is saved at
  `docs/samples/e4xt_ultra_preset0_old_format.bin` to work from.
  Only after dump reading is solid should any write path be tried live — the
  editor TUI's write actions default to disabled against real hardware for
  exactly this reason (`--allow-write` required; see the Editor TUI section
  below).

## Panel/remote (screen-mirror) protocol — reverse engineering not started

A true k2kremote-equivalent (LCD mirror + front-panel button injection) needs
the undocumented `F0 18 7F 00 00 …` protocol, not the editor protocol this
repo currently implements. See RESOLUTION_NOTES §3 for what fragments are
already known (init/enable/close handshake, a button-press echo) and the RE
method to fill in the rest (display-frame encoding, full button-code table,
wheel encoding). Not started; requires live hardware + a browser running
Ray Bellis's e-remote as the traffic source to capture against.

## Editor TUI (Phase 2 of the plan) — built, unverified on real hardware

**This branch (`extended_view`) reworked the TUI from a 2-pane (Preset |
Parameters) to a 4-pane layout: Preset | Voice | Parameters | Samples.**
It was built and demo-tested autonomously (see commit for the session
context) while `--allow-write` live-hardware trials were paused — **nothing
in this branch has been tried against the real E4XT yet**, unlike the
resize/paging work on `main` below, which was. Treat everything in this
section as demo-verified only until stated otherwise.

`eosremote/app.py`, four `DataTable`s in one `Horizontal`:
- **Preset** (`#presets`) — unchanged from `main`: paged, on-demand catalog
  scan, page size dynamic to the pane's height (see `main`'s entry below),
  `g` to goto, `o` to rename, `m` for the Master menu.
- **Voice** (`#voices`) — every voice of the selected preset (`V1`..`Vn`,
  1-based display / 0-based `VOICE_SELECT`), with a "single"/"multi (N)"
  zone-count hint. Not paged (a preset's voice count is expected to be
  small; unverified against a real multi-voice preset).
- **Parameters** (`#params`) — the selected voice's full `voice.*` group
  (146 params) if a voice is selected, else the preset's GLOBAL group (22
  params). Selecting/deselecting a voice (click a voice row, or `escape` to
  go back) swaps this automatically.
- **Samples** (`#samples`) — **derived, not a browsable bank**: resolves
  whichever voice(s) are in scope down to the raw sample number(s) they
  play and looks up each one's name (`EosRemoteApp._resolve_sample_rows`,
  `_voice_sample_info`). Whole preset in scope (no voice selected) sums
  across every voice, deduped by sample number with a "used by" column
  listing which voice(s) (e.g. `V1,V3`); one voice in scope narrows to just
  that voice's zone(s). Read-only — no rename/edit from this pane.
- Edits a parameter's value in place (device-fetched min/max/default shown),
  renames a preset, and a modal arm-then-fire Master screen (Delete
  Preset / Erase RAM Bank / Erase All RAM Presets / Erase All RAM Samples —
  never bound to a single keypress). All MIDI I/O runs off the UI thread,
  serialized by a lock (`EosBridge` is not thread-safe). 239 tests pass
  against `--demo`/`DemoBridge`, including a dedicated fake-bridge test for
  the multi-voice/multi-zone sample-aggregation logic (DemoBridge itself
  only ever has 1 voice/1 zone, too simple to exercise dedup).

**Known perf caveat, not yet tuned:** selecting a preset walks *every* voice
sequentially (`voice_num_szones` + a `VOICE_SELECT`/`SAMPLE_ZONE_SELECT`
context switch + a parameter read per zone) to populate the Voice and
Samples panes together in one pass. Fine for the handful of voices in
typical presets; untested against a preset with many voices/zones (a big
multisample drum kit, say) — could be slow (each step is a sequential MIDI
round-trip, same caution as the preset catalog scan) and may need a cap or
lazy-per-voice loading if that turns out to matter live.

**Deliberately dropped from `main`'s 2-pane version, not carried into this
layout:** the `p`/`s` Preset/Sample **bank**-switch and sample rename
(superseded here — "Samples" is now a used-by view, not a second browsable
catalog; reachable again by checking out `main` if the old bank-browsing
behavior is wanted back), and Link browsing (no pane for it in this cut;
the previous modal `v`/`l`/`z` drill-down flow is gone in favor of clicking
directly into the Voice pane, but there's no equivalent persistent Link
pane yet — could be a 5th pane later).

**Write actions (edit/rename/Master) default to disabled against real
hardware** — `--allow-write` is required to enable them (always on for
`--demo`). This mirrors the dump-reading caution above: no write path has
been exercised live yet, and this branch's *read* paths (Voice/Samples
panes) haven't either. Once dump reading is fully solid, try `--allow-write`
live in this order: a single low-stakes parameter edit + read-back first,
then rename, then (with real caution and a fresh backup) a Master action —
never start with a Master action.

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
