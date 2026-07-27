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

`eosremote/app.py`: preset browser (paged, on-demand catalog scan), a
parameter table for the selected preset's GLOBAL group with drill-down into
a specific voice/link (setting `PRESET_SELECT`/`VOICE_SELECT`/`LINK_SELECT`
context first), in-place value editing with device-fetched min/max/default,
whole-name preset rename, and a modal arm-then-fire Master screen (Delete
Preset / Erase RAM Bank / Erase All RAM Presets / Erase All RAM Samples —
never bound to a single keypress). All MIDI I/O runs off the UI thread,
serialized by a lock (`EosBridge` is not thread-safe). 198 tests pass,
including the write paths, against `--demo`/`DemoBridge`.

**Write actions (edit/rename/Master) default to disabled against real
hardware** — `--allow-write` is required to enable them (always on for
`--demo`). This mirrors the dump-reading caution above: no write path has
been exercised live yet. Once dump reading is fully solid, try `--allow-write`
live in this order: a single low-stakes parameter edit + read-back first,
then rename, then (with real caution and a fresh backup) a Master action —
never start with a Master action.

Not built: NEW-format dump/restore, and anything from the panel/mirror
protocol (see the section above — that's out of scope for this TUI
entirely).

**Presets/params pane resizing — fixed, verified live.** The two panes
weren't following terminal resizes consistently (presets looked frozen at a
fixed page size while params looked like it scaled) — root cause and fix in
RESOLUTION_NOTES §10. Confirmed live against the E4XT Ultra: resizing the
terminal now visibly changes how many presets are fetched/shown per page,
and shrinking back down doesn't re-hit the device for names it already has.

**Preset/Sample bank switch + sample-zone drill-down — built, demo-tested,
not yet tried live.** `p`/`s` switch the left browser pane between the
Preset and Sample catalogs (same dynamic paging as before, one bookmark +
cache per bank — see `EosRemoteApp._bank_state`/`_switch_bank`); rename
(`o`) works against whichever bank is active. Within a preset's voice
(`v`), `z` drills one level further into that voice's Sample Zone
(`SAMPLE_ZONE_SELECT`), showing the 13-parameter subset the spec calls out
as zone-scoped rather than voice-wide (`eos.params.SAMPLE_ZONE_PARAM_IDS`).
**Deliberately out of scope**, per the spec (no generic parameter access
exists for it in this protocol): a raw sample's own loop points, root key,
sample rate, playback direction — that would need the separate MIDI Sample
Dump Standard, not yet investigated at all.

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
