# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# --demo mode never opens a MIDI port — synthetic only.

import asyncio

from textual.widgets import Header

from eos import params as p
from eosed.app import (
    BROWSER_EXTEND_CHUNK, BROWSER_RESIZE_SETTLE, SAMPLE_USAGE_SCAN_RANGE, _VOICE_PARAM_IDS,
    _MAX_VOICE_SCAN, _MAX_ZONE_SCAN, _voice_sample_info, ConfirmSweepScreen,
    EosedApp)
from eosed.demo import DemoBridge


async def _wait_for(pilot, predicate, tries: int = 60, step: float = 0.05) -> bool:
    for _ in range(tries):
        await pilot.pause(step)
        if predicate():
            return True
    return False


async def _select_preset(pilot, app, row: int = 0) -> None:
    presets = app.query_one("#presets")
    await _wait_for(pilot, lambda: presets.row_count)
    await pilot.click("#presets")
    presets.move_cursor(row=row)
    await pilot.press("enter")
    await _wait_for(pilot, lambda: app.current_preset is not None)


async def _select_voice(pilot, app, row: int = 0) -> None:
    # 'v' either opens a modal voice-select prompt (front-panel 1-based
    # numbering) or, with only one voice (DemoBridge always has exactly
    # one), jumps straight there -- works in either view mode, unlike
    # clicking the Voice pane directly (hidden in compact view).
    await pilot.press("v")
    await pilot.pause()
    if len(app.screen_stack) > 1:
        await pilot.click("#value")
        for ch in str(row + 1):
            await pilot.press(ch)
        await pilot.press("enter")
    await _wait_for(pilot, lambda: app.current_voice is not None)


async def _goto(pilot, app, text):
    await pilot.press("g")
    assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
    await pilot.click("#value")
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")


async def test_app_mounts_and_lists_presets():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        assert await _wait_for(pilot, lambda: table.row_count)
        # The page size is dynamic (sized to the pane's height, see
        # EosedApp._desired_browser_window), not a fixed constant.
        assert table.row_count == app.browser_window
        assert f"presets 0-{app.browser_window - 1}" in app.last_status


async def test_switch_to_samples_bank_and_back():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        assert app.bank == "preset"

        await pilot.press("s")
        await pilot.pause()
        assert app.bank == "sample"
        assert await _wait_for(pilot, lambda: "samples" in app.last_status)
        assert table.get_row_at(0) == ["0", "Demo Kick"]

        await pilot.press("p")
        await pilot.pause()
        assert app.bank == "preset"
        assert await _wait_for(pilot, lambda: "presets" in app.last_status)


async def test_switching_to_samples_bank_clears_preset_detail_panes_immediately():
    # The Voice/Parameters/Samples-used-by panes describe a *preset*, out of
    # scope while browsing the raw Sample bank -- switching should clear
    # them right away, not leave stale preset/voice data on screen until a
    # sample happens to get selected.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        voices = app.query_one("#voices")
        params = app.query_one("#params")
        samples = app.query_one("#samples")
        assert await _wait_for(pilot, lambda: params.row_count == 22)
        assert voices.row_count == 1 and samples.row_count == 1

        await pilot.press("s")
        await pilot.pause()
        assert app.current_preset == 0  # state itself is untouched, just the display
        assert voices.row_count == 0
        assert params.row_count == 0
        assert samples.row_count == 0


async def test_switching_back_to_presets_bank_restores_the_preset_view():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count == 22)

        await pilot.press("s")
        await pilot.pause()
        assert params.row_count == 0

        await pilot.press("p")
        await pilot.pause()
        assert await _wait_for(pilot, lambda: params.row_count == 22)
        assert app._current_param_label == "global"


async def test_selecting_sample_shows_info_in_params_pane_not_stale_data():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        # First view a preset, so the params pane has real, stale-able data.
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count == 22)

        await pilot.press("s")
        await pilot.pause()
        table = app.query_one("#presets")
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: app.current_sample == 0)
        assert app._current_param_ids == []
        assert await _wait_for(pilot, lambda: params.row_count == 2)
        assert params.get_row_at(0)[1:3] == ["Sample number", "0"]
        assert params.get_row_at(1)[1:3] == ["Name", "Demo Kick"]
        assert "sample 0 'Demo Kick'" in app.last_status

        # Selecting a sample isn't a request to edit it -- must not crash
        # (the row keys aren't real parameter ids, unlike a normal params row).
        await pilot.click("#params")
        params.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1  # no EditValueScreen opened, no crash


async def test_rename_sample():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("o")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        rename_input = app.screen_stack[-1].query_one("#value")
        rename_input.value = ""
        await pilot.click("#value")
        for ch in "New Sample":
            await pilot.press(ch)
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: "renamed sample" in app.last_status)
        assert app.bridge.get_sample_name(0).strip() == "New Sample"


async def test_goto_sample():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()

        await pilot.press("g")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.click("#value")
        await pilot.press("1")
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: app.current_sample == 1)


async def test_find_sample_usage_scans_full_range_and_reports_matches():
    # Matches spread past the old 0-127 default (see SAMPLE_USAGE_SCAN_RANGE's
    # docstring: a real bank was found live to hold presets past 127) --
    # this must still find them, confirming the full 0-999 range is used.
    class FakeBridge(DemoBridge):
        _MATCHING_PRESETS = {5: "Foo", 130: "Bar", 269: "Baz"}

        def __init__(self):
            super().__init__()
            self._current_preset = None
            self._current_voice = None

        def set_parameter(self, param_id, value):
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                if self._current_voice == 0 and self._current_preset in self._MATCHING_PRESETS:
                    return 0  # matches DemoBridge's sample 0 ("Demo Kick")
                return -2  # no such voice
            return 0

        def get_preset_name(self, preset, *, timeout=None):
            return self._MATCHING_PRESETS.get(preset, "")

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._sample_usage_early_stop_gap = None  # this test wants the full, uninterrupted sweep
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("u")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        assert "used by 3 preset(s)" in app.last_status
        samples = app.query_one("#samples")
        assert samples.row_count == 3
        rows = {samples.get_row_at(i)[0]: samples.get_row_at(i)[1] for i in range(3)}
        assert rows == {"5": "Foo", "130": "Bar", "269": "Baz"}


async def test_find_sample_usage_second_lookup_is_instant_from_cached_index():
    # A complete sweep records every sample it sees, not just the one that
    # triggered it -- a later lookup for a *different* sample must be
    # instant, with no new hardware calls at all.
    class FakeBridge(DemoBridge):
        _PRESETS = {5: (0, "Foo"), 130: (1, "Bar")}  # preset -> (sample, name)

        def __init__(self):
            super().__init__()
            self.calls = 0
            self._current_preset = None
            self._current_voice = None

        def set_parameter(self, param_id, value):
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                self.calls += 1
                if self._current_voice == 0 and self._current_preset in self._PRESETS:
                    return self._PRESETS[self._current_preset][0]
                return -2  # no such voice
            return 0

        def get_preset_name(self, preset, *, timeout=None):
            return self._PRESETS.get(preset, (0, ""))[1]

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._sample_usage_early_stop_gap = None  # the two matches are far apart -- want the full sweep
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("u")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        assert "used by 1 preset(s)" in app.last_status
        calls_after_full_scan = app.bridge.calls
        assert calls_after_full_scan > 0

        # A different sample, never explicitly scanned for on its own --
        # the index from the first (complete) scan already covers it.
        table.move_cursor(row=1)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 1)
        await pilot.press("u")
        await pilot.pause()

        assert "(cached)" in app.last_status
        assert "used by 1 preset(s)" in app.last_status
        assert app.bridge.calls == calls_after_full_scan  # no new MIDI at all


async def test_cancel_sample_usage_scan():
    import time

    class FakeBridge(DemoBridge):
        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                time.sleep(0.01)  # slow enough to reliably catch mid-scan
                return -2  # no such voice -- every preset is empty
            return 0

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._sample_usage_early_stop_gap = None  # testing user-cancel specifically, not the heuristic
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("u")
        await pilot.pause(0.05)
        assert app._scan_active is True

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=200, step=0.02)
        assert "cancelled" in app.last_status


async def test_sample_usage_scan_stops_after_consecutive_empty_presets():
    # Default threshold is 10 (see SAMPLE_USAGE_EARLY_STOP_DEFAULT) -- a
    # match right after exactly that many consecutive empties must still be
    # missed (it's a heuristic, not a guarantee), and the result must still
    # be cached (early-stopping is an accepted tradeoff, unlike a user
    # cancellation).
    class FakeBridge(DemoBridge):
        def __init__(self):
            super().__init__()
            self._current_preset = None
            self._current_voice = None

        def set_parameter(self, param_id, value):
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                if self._current_preset == 0 and self._current_voice == 0:
                    return 0  # preset 0's one voice plays sample 0
                return -2  # everything else, and voice 1+, is "empty"
            return 0

        def get_preset_name(self, preset, *, timeout=None):
            return "Only Match" if preset == 0 else ""

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    assert app._sample_usage_early_stop_gap == 10  # the documented default
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("u")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=200, step=0.02)

        assert "stopped at preset 10 after 10 consecutive empty presets" in app.last_status
        assert "used by 1 preset(s)" in app.last_status  # preset 0 itself, found before the gap

        # Still cached despite stopping early -- a second, different query
        # must not trigger a fresh scan.
        assert app._sample_usage_scanned_range == SAMPLE_USAGE_SCAN_RANGE


async def test_sample_usage_early_stop_configurable_via_config_toml(tmp_path):
    config_path = str(tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text("sample_usage_early_stop = 3\n")
    # demo=False (with a DemoBridge standing in for a real one) exercises the
    # actual config-reading wiring, matching the pattern used for the view-
    # toggle persistence tests -- --demo itself never reads config.toml.
    app = EosedApp(DemoBridge(), allow_write=True, demo=False,
                       connect_kwargs={"config_path": config_path})
    assert app._sample_usage_early_stop_gap == 3

    (tmp_path / "config.toml").write_text('sample_usage_early_stop = "fullscan"\n')
    app2 = EosedApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    assert app2._sample_usage_early_stop_gap is None


async def test_clear_sample_usage_cache():
    class FakeBridge(DemoBridge):
        def __init__(self):
            super().__init__()
            self._current_preset = None
            self._current_voice = None

        def set_parameter(self, param_id, value):
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                if self._current_preset == 0 and self._current_voice == 0:
                    return 0
                return -2
            return 0

        def get_preset_name(self, preset, *, timeout=None):
            return "Only Match" if preset == 0 else ""

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("x")
        assert await _wait_for(pilot, lambda: "no sample-usage cache to clear" in app.last_status)

        await pilot.press("u")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=200, step=0.02)
        assert app._sample_usage_scanned_range is not None

        await pilot.press("x")
        assert await _wait_for(pilot, lambda: "cache cleared" in app.last_status)
        assert app._sample_usage_index == {}
        assert app._sample_usage_scanned_range is None

        # A subsequent lookup must scan fresh, not report "(cached)" again.
        await pilot.press("u")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=200, step=0.02)
        assert "(cached)" not in app.last_status


async def test_cache_all_names_depth_fills_only_the_name_catalogs():
    # "names" depth (see action_cache_everything / EosedApp._run_full_sweep)
    # has no use for a voice/zone walk at all -- must not populate the
    # preset-overview or sample-usage caches, only the two name catalogs.
    class FakeBridge(DemoBridge):
        _PRESETS = {5: "Foo", 130: "Bar"}
        _SAMPLES = {0: "Kick", 1: "Snare"}

        def get_preset_name(self, preset, *, timeout=None):
            if preset not in self._PRESETS:
                raise LookupError("no such preset")
            return self._PRESETS[preset]

        def get_sample_name(self, sample, *, timeout=None):
            if sample not in self._SAMPLES:
                raise LookupError("no such sample")
            return self._SAMPLES[sample]

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._sample_usage_early_stop_gap = None  # "names" depth ignores this anyway -- explicit for clarity
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)

        # No key maps to "names": 'c'/'C' are fixed at structure/full, so this
        # depth is reachable only via cache_depth + cache_all_on_startup.
        app._start_cache_all("names")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        assert app._catalog_cache["preset"] == {5: "Foo", 130: "Bar"}
        assert app._catalog_cache["sample"] == {0: "Kick", 1: "Snare"}
        assert app._preset_overviews == {}
        assert app._sample_usage_index == {}
        assert app._sample_usage_scanned_range is None


async def test_cache_all_sample_names_stop_early_after_consecutive_empty_samples():
    # The sample-name pass now honors the same early-stop gap as the preset
    # walk -- an empty slot is exactly as valid an "empty" signal for a
    # sample as no voices is for a preset, and a sample-name pass that
    # always ran the full 0-999 range regardless of the preset walk having
    # already bailed out looked inconsistent in practice. Live-caught: the
    # real device returns "Empty Sample" (a legitimate-looking name, not a
    # blank string and not an exception) for an unused slot -- this
    # FakeBridge mirrors that exact behavior instead of raising, which is
    # what let two earlier, more naive fixes (blank-check, then
    # any-alnum-check) both look correct here yet still fail live.
    class FakeBridge(DemoBridge):
        def get_preset_name(self, preset, *, timeout=None):
            return ""  # irrelevant here -- keep the preset walk trivial

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                return -2  # no preset has any voices -- keep the preset walk cheap
            return 0

        def get_sample_name(self, sample, *, timeout=None):
            return "Only Sample" if sample == 0 else "Empty Sample"

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._cache_depth = "full"
    assert app._sample_usage_early_stop_gap == 10  # the documented default
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)

        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        # sample 0 has a name, then 10 consecutive misses (samples 1-10)
        # trip the same default gap the preset walk uses.
        assert app._catalog_cache["sample"] == {0: "Only Sample"}
        assert app._catalog_scanned_upto["sample"] == 11
        assert "sample names stopped at 10 after 10 consecutive unnamed samples" in app.last_status


async def test_find_sample_usage_shows_results_in_the_params_pane_too():
    # #samples (where matches were already shown) is hidden in compact
    # view -- a compact-view user pressing 'u' used to see nothing but a
    # truncated one-line status-bar summary. The full match list must also
    # land in #params, which is visible in both view modes.
    class FakeBridge(DemoBridge):
        _MATCHING_PRESETS = {5: "Foo", 130: "Bar"}

        def __init__(self):
            super().__init__()
            self._current_preset = None
            self._current_voice = None

        def set_parameter(self, param_id, value):
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                if self._current_voice == 0 and self._current_preset in self._MATCHING_PRESETS:
                    return 0
                return -2
            return 0

        def get_preset_name(self, preset, *, timeout=None):
            return self._MATCHING_PRESETS.get(preset, "")

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    assert app.compact_view is True  # default -- #samples is hidden right now
    app._sample_usage_early_stop_gap = None
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_sample == 0)

        await pilot.press("u")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count == 2)
        rows = {params.get_row_at(i)[1]: params.get_row_at(i)[2] for i in range(2)}
        assert rows == {"preset 5": "Foo", "preset 130": "Bar"}


async def test_cache_all_structure_depth_skips_globals_but_reuses_on_select():
    # "structure" depth walks every voice/zone (needed for the sample-usage
    # index) but deliberately skips each preset's GLOBAL parameter values --
    # selecting that preset afterward must reuse the cached voice/zone/
    # sample work and fetch only the globals it's missing, not redo the
    # whole walk over MIDI again.
    class FakeBridge(DemoBridge):
        def __init__(self):
            super().__init__()
            self._current_preset = None
            self._current_voice = None
            self.get_parameters_calls = 0

        def get_preset_name(self, preset, *, timeout=None):
            return "Demo Grand Piano" if preset == 0 else ""

        def set_parameter(self, param_id, value):
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                if self._current_preset == 0 and self._current_voice == 0:
                    return 0
                return -2
            return 0

        def get_parameters(self, param_ids, *, timeout=None):
            self.get_parameters_calls += 1
            return {pid: 0 for pid in param_ids}

        def get_sample_name(self, sample, *, timeout=None):
            return "Demo Kick" if sample == 0 else ""

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._sample_usage_early_stop_gap = None  # this test wants the full, uninterrupted sweep
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)

        await pilot.press("c")   # 'c' is fixed at "structure" depth
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        assert 0 in app._preset_overviews
        voice_count, _zone_counts, global_ids, global_values, _sample_rows = app._preset_overviews[0]
        assert voice_count == 1
        assert global_values is None  # "structure" depth deliberately skips GLOBAL values
        # The real GLOBAL id list must still be cached even though the values
        # aren't -- otherwise the later lazy fetch has nothing to ask for.
        assert len(global_ids) == 22
        assert app._sample_usage_index.get(0) == [(0, "Demo Grand Piano")]
        assert app._sample_usage_scanned_range == SAMPLE_USAGE_SCAN_RANGE
        calls_after_sweep = app.bridge.get_parameters_calls

        # Selecting preset 0 must reuse the cached voice/zone/sample data --
        # the only new MIDI is the one batched fetch for its GLOBAL values,
        # and it must actually populate the Parameters pane (not 0 rows).
        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app._preset_overviews[0][3] is not None)
        assert app.bridge.get_parameters_calls == calls_after_sweep + 1
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count == 22)


async def test_cache_all_full_depth_makes_preset_selection_free_of_new_midi():
    # The whole point of "full" depth: once it's swept, browsing straight
    # through presets must issue no MIDI at all -- everything a selection
    # needs is already in _preset_overviews/_catalog_cache.
    class FakeBridge(DemoBridge):
        def __init__(self):
            super().__init__()
            self._current_preset = None
            self._current_voice = None
            self.midi_calls = 0

        def get_preset_name(self, preset, *, timeout=None):
            self.midi_calls += 1
            return "Demo Grand Piano" if preset == 0 else ""

        def set_parameter(self, param_id, value):
            self.midi_calls += 1
            if param_id == p.lookup("PRESET_SELECT").id:
                self._current_preset = value
            elif param_id == p.lookup("VOICE_SELECT").id:
                self._current_voice = value

        def get_parameter(self, param_id, *, timeout=None):
            self.midi_calls += 1
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                if self._current_preset == 0 and self._current_voice == 0:
                    return 0
                return -2
            return 0

        def get_parameters(self, param_ids, *, timeout=None):
            self.midi_calls += 1
            return {pid: 0 for pid in param_ids}

        def get_sample_name(self, sample, *, timeout=None):
            self.midi_calls += 1
            return "Demo Kick" if sample == 0 else ""

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._cache_depth = "full"
    app._sample_usage_early_stop_gap = None
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)

        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        assert app._preset_overviews[0][3] is not None  # globals cached too at "full" depth
        assert (0, 0) in app._voice_details  # voice 0's own 146-param group, too
        calls_after_sweep = app.bridge.midi_calls

        await pilot.click("#presets")
        table.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: app.current_preset == 0)
        await pilot.pause()
        assert app.bridge.midi_calls == calls_after_sweep  # no new MIDI at all

        # Browsing into the voice ('v') must be just as free of new MIDI --
        # live-caught: selecting a preset had gotten instant, but 'v' still
        # re-fetched its 146-param group fresh every time.
        await _select_voice(pilot, app)
        assert app.current_voice == 0
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count == len(_VOICE_PARAM_IDS))
        assert app.bridge.midi_calls == calls_after_sweep


async def test_cancelling_cache_all_promotes_nothing():
    import time

    class FakeBridge(DemoBridge):
        def get_preset_name(self, preset, *, timeout=None):
            return "Demo Grand Piano" if preset == 0 else ""

        def get_parameter(self, param_id, *, timeout=None):
            if param_id == p.lookup("E4_GEN_SAMPLE").id:
                time.sleep(0.01)  # slow enough to reliably catch mid-scan
                return -2
            return 0

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._cache_depth = "full"
    app._sample_usage_early_stop_gap = None  # testing user-cancel, not the heuristic
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)

        await pilot.press("C")
        await pilot.pause(0.05)
        assert app._scan_active is True

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=200, step=0.02)
        assert "cancelled" in app.last_status
        assert app._catalog_cache == {"preset": {}, "sample": {}}
        assert app._preset_overviews == {}
        assert app._sample_usage_index == {}
        assert app._sample_usage_scanned_range is None


async def test_cache_all_on_startup_configurable_via_config_toml(tmp_path):
    config_path = str(tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text("cache_all_on_startup = true\ncache_depth = \"names\"\n")
    app = EosedApp(DemoBridge(), allow_write=True, demo=False,
                       connect_kwargs={"config_path": config_path})
    assert app._cache_all_on_startup is True
    assert app._cache_depth == "names"
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        # DemoBridge's own presets (0, 1, 5) got picked up by the startup sweep.
        assert app._catalog_cache["preset"] == {
            0: "Demo Grand Piano", 1: "Demo Warm Pad", 5: "Demo Bass"}

    (tmp_path / "config.toml").write_text("")  # unset -- must default to off
    app2 = EosedApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    assert app2._cache_all_on_startup is False
    assert app2._cache_depth == "full"  # the documented default


def test_cache_keys_are_fixed_depths_not_the_configured_one():
    """'c' and 'C' mean predictable amounts of work regardless of
    cache_depth, which now only governs the startup sweep."""
    keys = {b.key: b.action for b in EosedApp.BINDINGS}
    assert keys["c"] == "cache_structure"
    assert keys["C"] == "cache_everything"
    assert keys["x"] == "clear_sample_usage_cache"
    assert "a" not in keys, "'a' was replaced by the c/C pair"


async def test_c_and_C_sweep_at_their_own_depths():
    """'c' must not fetch GLOBAL values; 'C' must."""
    for key, expect_globals in (("c", False), ("C", True)):
        app = EosedApp(DemoBridge(), allow_write=True, demo=True)
        app._cache_depth = "names"       # deliberately NOT what the keys use
        app._sample_usage_early_stop_gap = None
        async with app.run_test() as pilot:
            table = app.query_one("#presets")
            await _wait_for(pilot, lambda: table.row_count)
            await pilot.press(key)
            assert await _wait_for(pilot, lambda: not app._scan_active,
                                   tries=400, step=0.02)
            assert app._preset_overviews, f"{key} should walk structure"
            _vc, _zc, _gids, global_values, _rows = app._preset_overviews[0]
            assert (global_values is not None) is expect_globals, (
                f"{key}: globals present={global_values is not None}, "
                f"expected {expect_globals}")


def test_no_sweep_runs_on_startup_unless_asked(tmp_path):
    """Both startup sweeps are opt-in. "structure" is 23 min and "full" is
    1h 44m on a large bank (RESOLUTION_NOTES §20) -- far too long to impose
    on someone who launched the app to look at one preset."""
    config = tmp_path / "config.toml"
    config.write_text("# empty\n")

    kw = {"connect_kwargs": {"config_path": str(config)}}
    app = EosedApp(DemoBridge(), allow_write=True, demo=False, **kw)
    assert app._cache_all_on_startup is False
    assert app._cache_structure_on_startup is False

    config.write_text("cache_structure_on_startup = true\n")
    app = EosedApp(DemoBridge(), allow_write=True, demo=False, **kw)
    assert app._cache_structure_on_startup is True


def test_sweep_estimate_scales_with_used_ram_not_preset_count():
    """Preset COUNT cannot tell a bank of one-voice pads from one of 94-voice
    drum kits; used preset RAM can, and is one query rather than the whole
    walk we are trying to predict (RESOLUTION_NOTES §20)."""
    from eosed.app import _estimate_sweep_seconds

    # A small bank sweeps in seconds at every depth.
    assert _estimate_sweep_seconds("full", 3) < 30
    # The measured commercial bank: 2013 KB used, ~4130 voices.
    assert _estimate_sweep_seconds("full", 2013) > 3000
    # Depth ordering must hold for any bank.
    for used in (50, 500, 2013):
        assert (_estimate_sweep_seconds("names", used)
                < _estimate_sweep_seconds("structure", used)
                < _estimate_sweep_seconds("full", used))
    # Unknown/absent sizing must never fabricate a number.
    assert _estimate_sweep_seconds("full", None) is None
    assert _estimate_sweep_seconds("full", 0) is None
    assert _estimate_sweep_seconds("nonsense", 500) is None


def test_humanize_seconds_reads_naturally():
    from eosed.app import _humanize_seconds
    assert _humanize_seconds(20) == "20 seconds"
    assert _humanize_seconds(600) == "10 minutes"
    assert _humanize_seconds(5400) == "1.5 hours"


async def test_small_bank_sweeps_without_asking():
    """The prompt exists to prevent a surprise, not to add a keystroke to
    every sweep -- a demo-sized bank must start immediately."""
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        assert app._catalog_cache["preset"]        # it really ran
        assert not isinstance(app.screen, ConfirmSweepScreen)


async def test_big_bank_asks_first_and_no_means_no():
    """A bank whose used RAM implies a long sweep must ask, and answering no
    must leave every cache untouched."""
    class BigBank(DemoBridge):
        def preset_memory(self, *, timeout=None):
            from eos import messages as msgs
            return msgs.PresetMemoryResponse(total_kb=8192, free_kb=8192 - 2013,
                                             device_id=self.device_id)

    app = EosedApp(BigBank(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        app._catalog_cache["preset"].clear()
        await pilot.press("C")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmSweepScreen))

        await pilot.press("n")
        await _wait_for(pilot, lambda: not isinstance(app.screen, ConfirmSweepScreen))
        assert not app._scan_active
        assert app._catalog_cache["preset"] == {}, "declining must cache nothing"


async def test_big_bank_yes_runs_the_sweep():
    class BigBank(DemoBridge):
        def preset_memory(self, *, timeout=None):
            from eos import messages as msgs
            return msgs.PresetMemoryResponse(total_kb=8192, free_kb=8192 - 2013,
                                             device_id=self.device_id)

    app = EosedApp(BigBank(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("C")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmSweepScreen))
        await pilot.press("y")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        assert app._catalog_cache["preset"]


async def test_a_key_still_works_in_demo_with_no_startup_config():
    # --demo never reads cache_all_on_startup/cache_depth (same "demo
    # touches no real local state" convention as compact_view/sample_usage_
    # early_stop) -- the 'a' key itself must still work regardless.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    assert app._cache_all_on_startup is False
    assert app._cache_depth == "full"
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        assert app._catalog_cache["preset"] == {
            0: "Demo Grand Piano", 1: "Demo Warm Pad", 5: "Demo Bass"}


async def test_selecting_preset_loads_voices_global_params_and_samples():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        voices = app.query_one("#voices")
        params = app.query_one("#params")
        samples = app.query_one("#samples")
        assert await _wait_for(pilot, lambda: voices.row_count == 1)  # DemoBridge: 1 voice
        assert voices.get_row_at(0) == ["V1", "single"]

        assert await _wait_for(pilot, lambda: params.row_count == 22)  # GLOBAL group size
        assert app.current_voice is None
        assert app._current_param_label == "global"
        # _show_preset_overview's combined status supersedes _show_params's
        # own intermediate one (same race-avoidance pattern as _show_presets).
        assert "voice(s)" in app.last_status

        assert await _wait_for(pilot, lambda: samples.row_count == 1)
        assert samples.get_row_at(0) == ["0", "Demo Kick", "V1"]


async def test_selecting_voice_loads_voice_params_and_that_voices_samples():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _select_voice(pilot, app)

        assert app.current_voice == 0
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count > 22)  # full voice.* group
        assert app._current_param_label == "voice V1"

        samples = app.query_one("#samples")
        assert await _wait_for(pilot, lambda: samples.row_count == 1)
        assert samples.get_row_at(0) == ["0", "Demo Kick", "V1"]


async def test_escape_returns_to_preset_level_view():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _select_voice(pilot, app)
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count > 22)

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: app.current_voice is None)
        assert await _wait_for(pilot, lambda: params.row_count == 22)
        assert app._current_param_label == "global"


def _count_preset_overview_fetches(app):
    # preset_num_voices isn't a clean signal on its own -- the voice-browsing
    # modal also calls it (to know the valid range), independent of a full
    # preset-overview fetch. Count _load_preset_overview itself instead.
    calls = []
    original = app._load_preset_overview

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    app._load_preset_overview = counting
    return calls


async def test_back_to_preset_reuses_cached_overview_no_refetch():
    # Regression test: going voice/link -> back to the *same* preset used
    # to re-walk every voice/zone over MIDI again for data that hadn't
    # changed, making "back" noticeably slow against real hardware.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        calls = _count_preset_overview_fetches(app)
        await _select_voice(pilot, app)

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: app.current_voice is None)
        assert calls == []  # reused the cache, no re-fetch

        await pilot.press("r")  # an explicit refresh still forces one
        await pilot.pause()
        assert calls == [1]


async def test_editing_a_parameter_invalidates_the_cached_overview():
    # A write could change which sample a zone points at -- the cached
    # preset overview (voice/zone/sample data) can no longer be trusted
    # unchanged after one, unlike plain read-only navigation.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        calls = _count_preset_overview_fetches(app)
        await _select_voice(pilot, app)

        params = app.query_one("#params")
        await pilot.click("#params")
        params.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        value_input = app.screen_stack[-1].query_one("#value")
        value_input.value = ""
        await pilot.click("#value")
        for ch in "5":
            await pilot.press(ch)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: "set id" in app.last_status)

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: app.current_voice is None)
        assert calls == [1]  # the edit invalidated the cache -> re-fetched


async def test_editing_a_parameter_invalidates_the_catalog_cache_too():
    # _invalidate_write_sensitive_caches clears every cache-all-filled cache
    # uniformly, not just the preset overview -- a write could change a
    # name just as easily as a sample assignment.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        assert app._catalog_cache["preset"]  # something got cached
        assert app._catalog_scanned_upto["preset"] > 0
        assert app._catalog_scanned_upto["sample"] > 0
        assert app._voice_details  # "full" depth (the demo default) caches these too

        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await pilot.click("#params")
        params.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        value_input = app.screen_stack[-1].query_one("#value")
        value_input.value = ""
        await pilot.click("#value")
        for ch in "5":
            await pilot.press(ch)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: "set id" in app.last_status)

        assert app._catalog_cache == {"preset": {}, "sample": {}}
        assert app._catalog_scanned_upto == {"preset": 0, "sample": 0}
        assert app._voice_details == {}


async def test_edit_value_writes_through_and_refreshes_table():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)

        await pilot.click("#params")
        params.move_cursor(row=0)  # id 0 = E4_PRESET_TRANSPOSE
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)

        value_input = app.screen_stack[-1].query_one("#value")
        value_input.value = ""
        await pilot.click("#value")
        for ch in "5":
            await pilot.press(ch)
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: len(app.screen_stack) == 1)
        assert await _wait_for(pilot, lambda: "set id 0" in app.last_status)
        assert app.bridge.get_parameter(0) == 5
        # the params table must reflect the new value without a manual refresh
        assert await _wait_for(pilot, lambda: params.get_row("0")[2] == "5")


async def test_edit_value_rejects_out_of_range_input():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)

        await pilot.click("#params")
        params.move_cursor(row=0)  # E4_PRESET_TRANSPOSE, range -24..24
        await pilot.press("enter")
        await _wait_for(pilot, lambda: len(app.screen_stack) > 1)

        value_input = app.screen_stack[-1].query_one("#value")
        value_input.value = ""
        await pilot.click("#value")
        for ch in "9999":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.1)
        # out-of-range input must not dismiss the modal
        assert len(app.screen_stack) > 1


async def test_rename_preset():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        await pilot.press("o")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        rename_input = app.screen_stack[-1].query_one("#value")
        rename_input.value = ""
        await pilot.click("#value")
        for ch in "New Name":
            await pilot.press(ch)
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: "renamed" in app.last_status)
        assert app.bridge.get_preset_name(0).strip() == "New Name"
        # every write invalidates the cached preset overview, on principle
        assert app._preset_overviews == {}


async def test_master_menu_delete_preset_requires_arm_then_fire():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        assert 0 in app.bridge.preset_names
        await pilot.press("m")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        # escape without arming must not fire anything
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert 0 in app.bridge.preset_names

        await pilot.press("m")
        await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("1")       # arm delete_preset
        await pilot.press("enter")   # fire
        assert await _wait_for(pilot, lambda: "fired: delete_preset" in app.last_status)
        assert 0 not in app.bridge.preset_names


async def test_master_menu_erase_all_presets():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        assert app.bridge.preset_names  # something's there to erase

        await pilot.press("m")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("3")       # arm erase_all_presets
        await pilot.press("enter")   # fire
        assert await _wait_for(pilot, lambda: "fired: erase_all_presets" in app.last_status)
        assert app.bridge.preset_names == {}


async def test_master_menu_delete_preset_unavailable_without_selection():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        assert app.current_preset is None

        await pilot.press("m")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("1")       # try to arm delete_preset with nothing selected
        await pilot.press("enter")
        await pilot.pause(0.1)
        # must still be showing the modal (armed stayed None), not have fired
        assert len(app.screen_stack) > 1
        await pilot.press("escape")


async def test_writes_disabled_by_default_blocks_edit_rename_and_master():
    app = EosedApp(DemoBridge(), allow_write=False, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)

        await pilot.click("#params")
        params.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: "disabled" in app.last_status)
        assert len(app.screen_stack) == 1  # no EditValueScreen opened

        await pilot.press("o")
        await pilot.pause(0.1)
        assert len(app.screen_stack) == 1  # no RenameScreen opened

        # the Master screen itself is allowed to open (it's just a menu);
        # firing from it is what's gated.
        await pilot.press("m")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("3")
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: "disabled" in app.last_status)
        assert app.bridge.preset_names  # erase_all_presets did NOT fire


async def test_write_mode_toggle_arms_writes_and_colors_the_header():
    # 'w' arms/disarms writes at runtime on top of whatever --allow-write
    # started the session at; the header turns the E4XT badge's own red
    # while armed -- a persistent reminder, not just a status-line message.
    app = EosedApp(DemoBridge(), allow_write=False, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)  # let the initial page load settle first
        header = app.query_one(Header)
        assert app.allow_write is False
        assert "-write-armed" not in header.classes

        await pilot.press("w")
        assert await _wait_for(pilot, lambda: app.allow_write is True)
        assert "-write-armed" in header.classes
        assert "write mode ON" in app.last_status

        # An edit is now actually reachable, unlike before the toggle.
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")
        params.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)  # EditValueScreen opened
        await pilot.press("escape")

        await pilot.press("w")
        assert await _wait_for(pilot, lambda: app.allow_write is False)
        assert "-write-armed" not in header.classes
        assert "write mode OFF" in app.last_status


async def test_write_mode_starts_armed_when_launched_with_allow_write():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        header = app.query_one(Header)
        assert "-write-armed" in header.classes


async def test_selecting_a_preset_sends_a_program_change_by_default():
    # Unlike PRESET_SELECT (the editor protocol's own selector, spec-stated
    # "independent of the front panel's own selection"), a plain MIDI
    # Program Change is what actually makes the device select the preset
    # and redraw its own front-panel LCD -- see docs/RESOLUTION_NOTES.md
    # §14. No key binding: this fires automatically on every preset select.
    class FakeBridge(DemoBridge):
        def __init__(self):
            super().__init__()
            self.pc_calls = []

        def send_program_change(self, preset, *, channel=None):
            self.pc_calls.append(preset)

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    assert app._send_pc_on_preset_select is True  # the documented default
    async with app.run_test() as pilot:
        await _select_preset(pilot, app, row=0)
        assert await _wait_for(pilot, lambda: app.bridge.pc_calls == [0])


async def test_send_pc_on_preset_select_configurable_via_config_toml(tmp_path):
    config_path = str(tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text("send_pc_on_preset_select = false\n")
    # demo=False (with a DemoBridge standing in for a real one) exercises
    # the actual config-reading wiring, matching the pattern used for the
    # other config-backed settings -- --demo itself never reads config.toml.
    app = EosedApp(DemoBridge(), allow_write=True, demo=False,
                       connect_kwargs={"config_path": config_path})
    assert app._send_pc_on_preset_select is False

    (tmp_path / "config.toml").write_text("send_pc_on_preset_select = true\n")
    app2 = EosedApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    assert app2._send_pc_on_preset_select is True

    (tmp_path / "config.toml").write_text("")  # unset -- must default to on
    app3 = EosedApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    assert app3._send_pc_on_preset_select is True


async def test_demo_mode_does_not_touch_config_toml_for_send_pc_setting(monkeypatch):
    # Same "demo touches no real local state" convention already verified
    # for compact_view (test_demo_mode_does_not_touch_config_toml_for_view_
    # preference) -- --demo must never read config.toml, even though the
    # feature itself still defaults on there.
    from eos import bridge as bridge_mod

    def _boom(*a, **k):
        raise AssertionError("--demo must never read config.toml")
    monkeypatch.setattr(bridge_mod, "load_send_pc_on_preset_select", _boom)
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    assert app._send_pc_on_preset_select is True


async def test_goto_preset_out_of_current_window():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)

        await _goto(pilot, app, "5")

        assert await _wait_for(pilot, lambda: app.current_preset == 5)
        assert await _wait_for(pilot, lambda: app._current_param_label == "global")
        # preset 5 is within the initial window (starts at 0): no rescan, cursor moves
        assert await _wait_for(pilot, lambda: presets.cursor_row == 5)


async def test_goto_preset_jumps_window_and_highlights_the_right_row():
    # Regression test: reported bug — "goto 125" visually landed on preset
    # 112 because the table's cursor reset to row 0 after the window
    # rebuilt, instead of highlighting 125's own row (13, within 112-127).
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        window = app.browser_window
        expected_start = (125 // window) * window

        await _goto(pilot, app, "125")
        assert await _wait_for(pilot, lambda: app.current_preset == 125)
        assert await _wait_for(pilot, lambda: app._bank_state("preset").window_start == expected_start)
        assert await _wait_for(pilot, lambda: presets.get_row_at(presets.cursor_row) == ["125", ""])
        assert presets.cursor_row == 125 - expected_start


async def test_goto_preset_within_same_window_does_not_rescan():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)

        scans = []
        original = app.bridge.catalog_presets

        def counting_catalog_presets(*args, **kwargs):
            scans.append(1)
            return original(*args, **kwargs)

        app.bridge.catalog_presets = counting_catalog_presets

        await _goto(pilot, app, "10")  # still within the initial window (starts at 0)
        assert await _wait_for(pilot, lambda: app.current_preset == 10)
        assert presets.cursor_row == 10
        assert scans == []  # no rescan triggered


async def test_cache_all_makes_bank_paging_free_of_new_midi():
    # load_bank_page consults _catalog_cache before hitting the device --
    # after a cache-all sweep, paging to a window the paged browser has
    # never fetched on its own must not call catalog_presets at all.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    app._cache_depth = "names"
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)

        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)

        scans = []
        original = app.bridge.catalog_presets

        def counting_catalog_presets(*args, **kwargs):
            scans.append(1)
            return original(*args, **kwargs)

        app.bridge.catalog_presets = counting_catalog_presets

        await _goto(pilot, app, "500")  # far outside anything paged in before
        assert await _wait_for(pilot, lambda: app.current_preset == 500)
        assert scans == []  # the cache-all sweep already covers this window

        # An explicit refresh still forces a real re-fetch regardless.
        await pilot.press("r")
        assert await _wait_for(pilot, lambda: scans == [1])


async def test_browser_window_grows_and_shrinks_with_terminal_height():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test(size=(80, 24)) as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        small_window = app.browser_window

        scans = []
        original = app.bridge.catalog_presets

        def counting_catalog_presets(*args, **kwargs):
            scans.append(args[0] if args else kwargs.get("preset_range"))
            return original(*args, **kwargs)

        app.bridge.catalog_presets = counting_catalog_presets

        await pilot.resize_terminal(80, 50)
        await asyncio.sleep(BROWSER_RESIZE_SETTLE + 0.2)
        await _wait_for(pilot, lambda: app.browser_window > small_window)
        grown_window = app.browser_window
        assert grown_window > small_window
        assert presets.row_count == grown_window
        assert len(scans) == 1  # exactly one re-fetch for the grow

        await pilot.resize_terminal(80, 24)
        await asyncio.sleep(BROWSER_RESIZE_SETTLE + 0.2)
        await _wait_for(pilot, lambda: app.browser_window == small_window)
        assert presets.row_count == small_window
        # shrinking back reuses the cached names from the larger fetch above
        assert len(scans) == 1


async def test_pending_resize_debounce_survives_teardown():
    # Regression: the first layout pass fires a resize, which arms the
    # BROWSER_RESIZE_SETTLE debounce -- so a short-lived app routinely shuts
    # down with one still pending. It used to fire against the torn-down
    # screen and raise NoMatches out of the timer, which surfaced as a
    # *different* test failing intermittently (whichever one happened to be
    # running when the stray callback landed) rather than as anything
    # pointing back here. Asserted directly instead of racing the real
    # timing, which is exactly what made the original flake so hard to place.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test(size=(80, 24)) as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)

    # on_unmount must have disarmed it ...
    assert app._resize_timer is None
    # ... and the callback must be harmless even if it was already queued.
    app._settle_browser_resize()


async def test_scrolling_near_bottom_of_page_extends_with_more_rows():
    # Live-caught: the preset/sample pane only ever showed one fetched
    # window, with 'g' (goto) as the only way to reach past it -- easy not
    # to know it exists. Approaching the bottom of the loaded rows (by
    # keyboard/mouse, not just an explicit key) should fetch and append the
    # next chunk rather than requiring 'g' every time.
    class FakeBridge(DemoBridge):
        def catalog_presets(self, preset_range=range(0, 128), *, timeout=None, on_progress=None):
            return {n: f"P{n}" for n in preset_range}

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    async with app.run_test(size=(80, 24)) as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        initial_count = table.row_count

        await pilot.click("#presets")
        table.move_cursor(row=initial_count - 1)  # last loaded row -- within the extend threshold
        assert await _wait_for(pilot, lambda: table.row_count > initial_count, tries=100)
        assert table.row_count == initial_count + BROWSER_EXTEND_CHUNK
        # The new rows must actually be usable, not placeholders.
        assert table.get_row_at(table.row_count - 1) == [str(initial_count + BROWSER_EXTEND_CHUNK - 1),
                                                         f"P{initial_count + BROWSER_EXTEND_CHUNK - 1}"]


async def test_extend_reuses_cache_all_data_with_no_new_midi():
    class FakeBridge(DemoBridge):
        def __init__(self):
            super().__init__()
            self.catalog_calls = 0

        def catalog_presets(self, preset_range=range(0, 128), *, timeout=None, on_progress=None):
            self.catalog_calls += 1
            return {n: f"P{n}" for n in preset_range}

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    app._cache_depth = "names"
    async with app.run_test(size=(80, 24)) as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        initial_count = table.row_count

        await pilot.press("C")
        assert await _wait_for(pilot, lambda: not app._scan_active, tries=400, step=0.02)
        calls_after_sweep = app.bridge.catalog_calls

        await pilot.click("#presets")
        table.move_cursor(row=initial_count - 1)
        assert await _wait_for(pilot, lambda: table.row_count > initial_count, tries=100)
        assert app.bridge.catalog_calls == calls_after_sweep  # extend reused the cache-all sweep


async def test_page_down_up_step_through_the_bank():
    class FakeBridge(DemoBridge):
        def catalog_presets(self, preset_range=range(0, 128), *, timeout=None, on_progress=None):
            return {n: f"P{n}" for n in preset_range}

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    async with app.run_test(size=(80, 24)) as pilot:
        table = app.query_one("#presets")
        await _wait_for(pilot, lambda: table.row_count)
        window = app.browser_window

        await pilot.click("#presets")
        await pilot.press("pagedown")
        assert await _wait_for(pilot, lambda: app._bank_state("preset").window_start == window)
        assert table.get_row_at(0) == [str(window), f"P{window}"]

        await pilot.press("pageup")
        assert await _wait_for(pilot, lambda: app._bank_state("preset").window_start == 0)

        # PageUp at the very first page is a no-op, not an error.
        await pilot.press("pageup")
        await pilot.pause()
        assert "already at the first page" in app.last_status
        assert app._bank_state("preset").window_start == 0


def test_voice_and_zone_caps_cover_the_protocol_ceiling():
    """VOICE_SELECT and SAMPLE_ZONE_SELECT are 0..255 in the spec and in the
    device's own 03h/04h reply, and the EOS 4.0 manual states a preset may
    have up to 256 voices -- so anything less silently truncates real content.

    These were 64 and 32, and both were too small: a commercial bank has drum
    kits of 94 voices and a multisample voice of 62 zones (RESOLUTION_NOTES
    §19). Truncation is invisible at runtime -- the walk just stops early and
    the missing voices look like they do not exist.
    """
    assert _MAX_VOICE_SCAN >= 256
    assert _MAX_ZONE_SCAN >= 256


def test_voice_walk_reaches_a_deep_drum_kit():
    """A 94-voice preset (the deepest found on real hardware) must walk all
    the way, not stop at the old 64 cap."""
    deepest = 94

    class DeepKit(DemoBridge):
        def get_parameter(self, param_id, *, timeout=None):
            from eos import params as p
            if param_id != p.lookup("E4_GEN_SAMPLE").id:
                return 0
            voice = getattr(self, "_voice", 0)
            zone = getattr(self, "_zone", None)
            if zone is not None:
                return 0                      # single-sample voices here
            return -2 if voice >= deepest else 100 + voice

        def set_parameter(self, param_id, value):
            from eos import params as p
            if param_id == p.lookup("VOICE_SELECT").id:
                self._voice, self._zone = value, None
            elif param_id == p.lookup("SAMPLE_ZONE_SELECT").id:
                self._zone = value

    bridge = DeepKit()
    walked = []
    for voice in range(_MAX_VOICE_SCAN):
        info = _voice_sample_info(bridge, 0, voice)
        if info is None:
            break
        walked.append(info[1][0])

    assert len(walked) == deepest
    assert walked[-1] == 100 + deepest - 1     # the last voice really was read


def test_zone_walk_reaches_a_62_zone_voice():
    """The deepest multisample voice found on real hardware had 62 zones,
    nearly double the old 32 cap."""
    zones = 62

    class WideVoice(DemoBridge):
        def get_parameter(self, param_id, *, timeout=None):
            from eos import params as p
            if param_id != p.lookup("E4_GEN_SAMPLE").id:
                return 0
            zone = getattr(self, "_zone", None)
            if zone is None:
                return -1                     # multisample at voice level
            return 0 if zone >= zones else 200 + zone

        def set_parameter(self, param_id, value):
            from eos import params as p
            if param_id == p.lookup("VOICE_SELECT").id:
                self._voice, self._zone = value, None
            elif param_id == p.lookup("SAMPLE_ZONE_SELECT").id:
                self._zone = value

    count, samples = _voice_sample_info(WideVoice(), 0, 0)
    assert count == zones
    assert len(samples) == zones and samples[-1] == 200 + zones - 1


async def test_samples_pane_aggregates_across_voices_and_dedups():
    # A fake bridge with 3 voices: two single-sample voices sharing sample 7,
    # and one multisample voice (flagged via the voice-level -1 sentinel,
    # not a count field — see EosedApp._voice_sample_info /
    # RESOLUTION_NOTES §11) with 3 zones: samples 7, 9, and 9 again (the
    # same voice hitting the same sample from two different zones -- a very
    # normal pattern, e.g. two key ranges sharing one recording) -- exercises
    # both the cross-voice dedup AND the same-voice-multiple-zones dedup in
    # EosedApp._resolve_sample_rows independent of DemoBridge's
    # simplicity (which only ever has one voice/one zone).
    class FakeBridge(DemoBridge):
        def get_parameter(self, param_id, *, timeout=None):
            from eos import params as p
            if param_id != p.lookup("E4_GEN_SAMPLE").id:
                return 0
            voice = getattr(self, "_voice", None)
            zone = getattr(self, "_zone", None)
            if voice in (0, 1):
                return 7  # single-sample voices, both using sample 7
            if voice == 2:
                if zone is None:
                    return -1  # multisample sentinel at voice level
                return {0: 7, 1: 9, 2: 9}.get(zone, 0)  # zone 3 reads 0 -> ends the scan
            return -2  # no such voice -- stops the walk after voice 2

        def set_parameter(self, param_id, value):
            from eos import params as p
            if param_id == p.lookup("VOICE_SELECT").id:
                self._voice = value
                self._zone = None
            elif param_id == p.lookup("SAMPLE_ZONE_SELECT").id:
                self._zone = value

        def get_sample_name(self, sample, *, timeout=None):
            return {7: "Shared Kick", 9: "Extra Snare"}.get(sample, "")

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        voices = app.query_one("#voices")
        assert await _wait_for(pilot, lambda: voices.row_count == 3)
        assert voices.get_row_at(2) == ["V3", "multi (3)"]

        samples = app.query_one("#samples")
        assert await _wait_for(pilot, lambda: samples.row_count == 2)
        rows = {samples.get_row_at(i)[0]: samples.get_row_at(i) for i in range(samples.row_count)}
        assert rows["7"] == ["7", "Shared Kick", "V1,V2,V3"]
        assert rows["9"] == ["9", "Extra Snare", "V3"]


async def test_view_defaults_to_compact_with_no_stored_preference():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.compact_view is True
        assert "compact" in app.query_one("#tables").classes
        assert app.query_one("#voices").display is False
        assert app.query_one("#samples").display is False


async def test_toggle_view_shows_and_hides_voice_and_samples_panes():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        voices = app.query_one("#voices")
        samples = app.query_one("#samples")

        await pilot.press("e")
        await pilot.pause()
        assert app.compact_view is False
        assert voices.display is True
        assert samples.display is True

        await pilot.press("e")
        await pilot.pause()
        assert app.compact_view is True
        assert voices.display is False
        assert samples.display is False


async def test_view_preference_persists_across_restarts(tmp_path):
    config_path = str(tmp_path / "config.toml")
    # demo=False (with a DemoBridge instance standing in for a real one)
    # exercises the actual persistence wiring in isolation, without needing
    # real hardware — demo=True deliberately skips it (see next test).
    app1 = EosedApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    async with app1.run_test() as pilot:
        await pilot.pause()
        assert app1.compact_view is True  # nothing stored yet -> default
        await pilot.press("e")
        await pilot.pause()
        assert app1.compact_view is False

    app2 = EosedApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    async with app2.run_test() as pilot:
        await pilot.pause()
        assert app2.compact_view is False  # remembered from app1


async def test_demo_mode_does_not_touch_config_toml_for_view_preference(monkeypatch):
    # Regression guard for the same class of bug docs/RESOLUTION_NOTES.md §7
    # already caught for the MIDI port cache: --demo must never read/write
    # real local config.toml.
    from eos import bridge as bridge_mod

    calls = []
    monkeypatch.setattr(bridge_mod, "load_compact_view",
                        lambda *a, **k: calls.append("load"))
    monkeypatch.setattr(bridge_mod, "save_compact_view",
                        lambda *a, **k: calls.append("save"))
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
    assert calls == []


async def test_browse_voices_with_exactly_one_skips_the_prompt():
    # A prompt whose only valid answer is "1" is just an extra keypress —
    # 'v' should jump straight there instead. DemoBridge always has exactly
    # one voice, so this is the path _select_voice takes in every other test.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        await pilot.press("v")
        await pilot.pause()

        assert len(app.screen_stack) == 1  # no modal opened
        assert app.current_voice == 0


async def test_browse_voices_modal_works_in_compact_view():
    # Regression test: 'v' used to only work by clicking the Voice pane
    # directly, which is hidden in the (now-default) compact view. The
    # modal prompt must work regardless of which pane layout is showing.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.compact_view is True
        await _select_preset(pilot, app)
        await _select_voice(pilot, app)

        assert app.compact_view is True  # browsing a voice doesn't change the view
        assert app.current_voice == 0
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count > 22)
        assert app._current_param_label == "voice V1"


async def test_browse_links_with_exactly_one_skips_the_prompt():
    # A prompt whose only valid answer is "1" is just an extra keypress —
    # 'l' should jump straight there instead.
    class FakeBridge(DemoBridge):
        def preset_num_links(self, preset, *, timeout=None):
            return 1

        def get_parameters(self, param_ids, *, timeout=None):
            return {pid: 0 for pid in param_ids}

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        await pilot.press("l")
        await pilot.pause()

        assert len(app.screen_stack) == 1  # no modal opened
        assert await _wait_for(pilot, lambda: app.current_link == 0)
        assert app.current_voice is None
        assert app._current_param_label == "link L1"
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count > 0)

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: app.current_link is None)
        assert app._current_param_label == "global"


async def test_browse_links_with_several_prompts_for_which_one():
    class FakeBridge(DemoBridge):
        def preset_num_links(self, preset, *, timeout=None):
            return 2

        def get_parameters(self, param_ids, *, timeout=None):
            return {pid: 0 for pid in param_ids}

    app = EosedApp(FakeBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        await pilot.press("l")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.click("#value")
        await pilot.press("2")  # front-panel 1-based, like voices
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: app.current_link == 1)
        assert app._current_param_label == "link L2"


async def test_demo_never_touches_rtmidi(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "rtmidi", None)
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        assert await _wait_for(pilot, lambda: table.row_count)


# --- undo log / change history ------------------------------------------------

async def _edit_param(pilot, app, row: int, new_value: str) -> None:
    """Drive the Parameters pane's edit flow for the parameter at ``row``."""
    params = app.query_one("#params")
    await _wait_for(pilot, lambda: params.row_count)
    await pilot.click("#params")
    params.move_cursor(row=row)
    await pilot.press("enter")
    assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
    app.screen_stack[-1].query_one("#value").value = ""
    await pilot.click("#value")
    for ch in new_value:
        await pilot.press(ch)
    await pilot.press("enter")
    assert await _wait_for(pilot, lambda: len(app.screen_stack) == 1)


async def test_edit_records_a_change_and_shows_the_counter():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        assert app._changes == []

        await _edit_param(pilot, app, 0, "5")   # id 0 = E4_PRESET_TRANSPOSE
        assert await _wait_for(pilot, lambda: len(app._changes) == 1)
        change = app._changes[0]
        assert (change.param_id, change.old, change.new) == (0, 0, 5)
        assert change.scope == "global"
        # The count lives in the header subtitle, not the status line, so a
        # later scan/load cannot scroll it away.
        assert "Δ1" in app.sub_title


async def test_undo_restores_the_previous_value_and_reports_it():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)
        assert app.bridge.get_parameter(0) == 5

        await pilot.press("z")
        assert await _wait_for(pilot, lambda: not app._changes)
        assert app.bridge.get_parameter(0) == 0
        # "reverted X from b to a", per the status-line contract
        assert "reverted" in app.last_status
        assert "E4_PRESET_TRANSPOSE" in app.last_status
        assert "from 5 to 0" in app.last_status
        assert "Δ" not in app.sub_title  # counter disappears at zero


async def test_undo_is_step_by_step_and_undo_all_clears_everything():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)
        await _edit_param(pilot, app, 0, "7")
        await _wait_for(pilot, lambda: len(app._changes) == 2)
        assert app.bridge.get_parameter(0) == 7

        await pilot.press("z")  # one step back, not all the way
        assert await _wait_for(pilot, lambda: len(app._changes) == 1)
        assert app.bridge.get_parameter(0) == 5

        await _edit_param(pilot, app, 0, "9")
        await _wait_for(pilot, lambda: len(app._changes) == 2)
        await pilot.press("Z")  # undo all, back to as-loaded
        assert await _wait_for(pilot, lambda: not app._changes)
        assert app.bridge.get_parameter(0) == 0
        assert "back to as loaded" in app.last_status


async def test_undo_replays_in_reverse_order():
    # Two edits to *different* parameters, so undoing in the wrong order
    # would still leave both at their original values and hide the bug --
    # the order is asserted through the log itself.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)
        await _edit_param(pilot, app, 1, "3")
        await _wait_for(pilot, lambda: len(app._changes) == 2)

        await pilot.press("z")
        assert await _wait_for(pilot, lambda: len(app._changes) == 1)
        # the *second* edit was undone first
        assert "E4_PRESET_VOLUME" in app.last_status
        assert app._changes[0].param_id == 0


async def test_history_overlay_lists_every_change():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)
        await _edit_param(pilot, app, 1, "3")
        await _wait_for(pilot, lambda: len(app._changes) == 2)

        await pilot.press("h")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        table = app.screen_stack[-1].query_one("#history")
        assert table.row_count == 2
        # columns: # | Scope | Parameter | Old | New
        assert table.get_row("1") == ["1", "global", "E4_PRESET_TRANSPOSE", "0", "5"]
        assert table.get_row("2")[2] == "E4_PRESET_VOLUME"

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) == 1)


async def test_history_overlay_opens_with_no_changes():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await pilot.press("h")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        assert app.screen_stack[-1].query_one("#history").row_count == 1  # the placeholder row


async def test_selecting_a_different_preset_discards_the_undo_log():
    # Every write goes to whatever PRESET_SELECT points at, so a log for a
    # preset that is no longer selected could not be replayed safely.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app, row=0)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)

        await _select_preset(pilot, app, row=1)
        assert app._changes == []
        await pilot.press("z")
        assert await _wait_for(pilot, lambda: "nothing to undo" in app.last_status)


async def test_reselecting_the_same_preset_keeps_the_undo_log():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app, row=0)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)

        await _select_preset(pilot, app, row=0)  # same preset again
        assert len(app._changes) == 1


async def test_undo_is_gated_behind_write_mode():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _edit_param(pilot, app, 0, "5")
        await _wait_for(pilot, lambda: len(app._changes) == 1)

        await pilot.press("w")  # disarm writes
        await pilot.press("z")
        assert await _wait_for(pilot, lambda: "writes disabled" in app.last_status)
        assert len(app._changes) == 1        # nothing undone
        assert app.bridge.get_parameter(0) == 5


async def test_no_op_edit_is_not_recorded():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await _edit_param(pilot, app, 0, "0")  # id 0 already reads 0
        assert await _wait_for(pilot, lambda: "unchanged" in app.last_status)
        assert app._changes == []


async def test_undo_of_a_voice_scoped_edit_restores_the_voice_selection():
    # A parameter id means "this voice's field" only while VOICE_SELECT
    # points at it, so the undo has to re-select before writing back.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        await _select_voice(pilot, app)
        assert await _wait_for(pilot, lambda: app.current_voice == 0)

        await _edit_param(pilot, app, 0, "5")
        assert await _wait_for(pilot, lambda: len(app._changes) == 1)
        change = app._changes[0]
        assert change.voice == 0 and change.scope == "V1"

        await pilot.press("z")
        assert await _wait_for(pilot, lambda: not app._changes)
        assert "[V1]" in app.last_status


async def test_history_shows_the_scope_each_change_was_made_under():
    # The same parameter id edited under two different selections is two
    # different fields, so the history has to say which -- a row that only
    # named the parameter would be ambiguous.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test(size=(120, 32)) as pilot:
        await _select_preset(pilot, app)
        await _edit_param(pilot, app, 0, "5")           # global scope
        await _wait_for(pilot, lambda: len(app._changes) == 1)
        await _select_voice(pilot, app)
        assert await _wait_for(pilot, lambda: app.current_voice == 0)
        await _edit_param(pilot, app, 0, "3")           # voice scope
        await _wait_for(pilot, lambda: len(app._changes) == 2)

        await pilot.press("h")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        table = app.screen_stack[-1].query_one("#history")
        assert [table.get_row(str(n))[1] for n in (1, 2)] == ["global", "V1"]


# --- +/- nudge and in-dialog stepping -----------------------------------------

async def test_plus_and_minus_nudge_the_highlighted_parameter():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")
        params.move_cursor(row=0)  # id 0 = E4_PRESET_TRANSPOSE, starts at 0

        await pilot.press("+")
        assert await _wait_for(pilot, lambda: app.bridge.get_parameter(0) == 1)
        await pilot.press("=")  # same as '+', without needing shift
        assert await _wait_for(pilot, lambda: app.bridge.get_parameter(0) == 2)
        await pilot.press("-")
        assert await _wait_for(pilot, lambda: app.bridge.get_parameter(0) == 1)
        assert "E4_PRESET_TRANSPOSE" in app.last_status


async def test_nudging_clamps_to_the_device_reported_range():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")
        params.move_cursor(row=0)

        # E4_PRESET_TRANSPOSE's maximum is 24; park just below it.
        app.bridge.set_parameter(0, 24)
        await pilot.press("+")
        assert await _wait_for(pilot, lambda: "already at its maximum" in app.last_status)
        assert app.bridge.get_parameter(0) == 24
        assert app._changes == []  # a refused nudge is not a change


async def test_consecutive_nudges_collapse_into_one_undo_entry():
    # Holding '+' is one edit as far as the user is concerned; ten log
    # entries would make both 'z' and the history useless for it.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")
        params.move_cursor(row=0)

        for _ in range(3):
            await pilot.press("+")
        assert await _wait_for(pilot, lambda: app.bridge.get_parameter(0) == 3)
        assert len(app._changes) == 1
        # ... and it keeps the value the run STARTED from, so one undo
        # returns the whole run.
        assert (app._changes[0].old, app._changes[0].new) == (0, 3)

        await pilot.press("z")
        assert await _wait_for(pilot, lambda: not app._changes)
        assert app.bridge.get_parameter(0) == 0


async def test_nudging_a_different_parameter_starts_a_new_undo_entry():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")

        params.move_cursor(row=0)
        await pilot.press("+")
        assert await _wait_for(pilot, lambda: len(app._changes) == 1)
        params.move_cursor(row=1)
        await pilot.press("+")
        assert await _wait_for(pilot, lambda: len(app._changes) == 2)


async def test_nudge_is_gated_behind_write_mode():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")
        params.move_cursor(row=0)

        await pilot.press("w")  # disarm
        await pilot.press("+")
        assert await _wait_for(pilot, lambda: "writes disabled" in app.last_status)
        assert app.bridge.get_parameter(0) == 0


async def test_nudge_ignores_rows_that_are_not_parameters():
    # select_sample borrows the Parameters pane for read-only info, keyed by
    # something that isn't a parameter id.
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _wait_for(pilot, lambda: app.query_one("#presets").row_count)
        await pilot.press("s")  # sample bank
        app.select_sample(0)
        await pilot.pause()
        await pilot.click("#params")
        await pilot.press("+")
        await pilot.pause(0.2)
        assert app._changes == []  # no crash, nothing recorded


async def test_edit_dialog_arrow_keys_step_the_value():
    app = EosedApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)
        params = app.query_one("#params")
        await _wait_for(pilot, lambda: params.row_count)
        await pilot.click("#params")
        params.move_cursor(row=0)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)

        field = app.screen_stack[-1].query_one("#value")
        assert field.value == "0"
        await pilot.press("up")
        assert field.value == "1"
        await pilot.press("pageup")
        assert field.value == "11"
        await pilot.press("down")
        assert field.value == "10"
        await pilot.press("pagedown")
        assert field.value == "0"
        # stepping below the minimum clamps rather than wrapping
        await pilot.press("pagedown")
        assert field.value == "-10"
        for _ in range(3):
            await pilot.press("pagedown")
        assert field.value == "-24"  # E4_PRESET_TRANSPOSE's minimum

        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) == 1)
        assert await _wait_for(pilot, lambda: app.bridge.get_parameter(0) == -24)
