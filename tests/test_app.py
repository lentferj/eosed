# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
#
# This file is part of eosremote.  Original work.  GPL-2.0-or-later.
#
# --demo mode never opens a MIDI port — synthetic only.

import asyncio

import pytest

from eosremote import demo as demo_mod
from eosremote.app import BROWSER_RESIZE_SETTLE, EosRemoteApp
from eosremote.demo import DemoBridge


async def _wait_for(pilot, predicate, tries: int = 60, step: float = 0.05) -> bool:
    for _ in range(tries):
        await pilot.pause(step)
        if predicate():
            return True
    return False


@pytest.fixture(autouse=True)
def _reset_demo_state():
    # DemoBridge's backing dicts are module-level, so tests must not leak
    # state into each other.
    saved_presets = dict(demo_mod._DEMO_PRESET_NAMES)
    saved_samples = dict(demo_mod._DEMO_SAMPLE_NAMES)
    saved_params = dict(demo_mod._DEMO_PARAM_VALUES)
    yield
    demo_mod._DEMO_PRESET_NAMES.clear()
    demo_mod._DEMO_PRESET_NAMES.update(saved_presets)
    demo_mod._DEMO_SAMPLE_NAMES.clear()
    demo_mod._DEMO_SAMPLE_NAMES.update(saved_samples)
    demo_mod._DEMO_PARAM_VALUES.clear()
    demo_mod._DEMO_PARAM_VALUES.update(saved_params)


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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        assert await _wait_for(pilot, lambda: table.row_count)
        # The page size is dynamic (sized to the pane's height, see
        # EosRemoteApp._desired_browser_window), not a fixed constant.
        assert table.row_count == app.browser_window
        assert f"presets 0-{app.browser_window - 1}" in app.last_status


async def test_selecting_preset_loads_voices_global_params_and_samples():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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


async def test_edit_value_writes_through_and_refreshes_table():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
        assert app._preset_overview_cache is None


async def test_master_menu_delete_preset_requires_arm_then_fire():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await _select_preset(pilot, app)

        assert 0 in demo_mod._DEMO_PRESET_NAMES
        await pilot.press("m")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        # escape without arming must not fire anything
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert 0 in demo_mod._DEMO_PRESET_NAMES

        await pilot.press("m")
        await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("1")       # arm delete_preset
        await pilot.press("enter")   # fire
        assert await _wait_for(pilot, lambda: "fired: delete_preset" in app.last_status)
        assert 0 not in demo_mod._DEMO_PRESET_NAMES


async def test_master_menu_erase_all_presets():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        assert demo_mod._DEMO_PRESET_NAMES  # something's there to erase

        await pilot.press("m")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        await pilot.press("3")       # arm erase_all_presets
        await pilot.press("enter")   # fire
        assert await _wait_for(pilot, lambda: "fired: erase_all_presets" in app.last_status)
        assert demo_mod._DEMO_PRESET_NAMES == {}


async def test_master_menu_delete_preset_unavailable_without_selection():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=False, demo=True)
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
        assert demo_mod._DEMO_PRESET_NAMES  # erase_all_presets did NOT fire


async def test_goto_preset_out_of_current_window():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        window = app.browser_window
        expected_start = (125 // window) * window

        await _goto(pilot, app, "125")
        assert await _wait_for(pilot, lambda: app.current_preset == 125)
        assert await _wait_for(pilot, lambda: app.preset_window_start == expected_start)
        assert await _wait_for(pilot, lambda: presets.get_row_at(presets.cursor_row) == ["125", ""])
        assert presets.cursor_row == 125 - expected_start


async def test_goto_preset_within_same_window_does_not_rescan():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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


async def test_browser_window_grows_and_shrinks_with_terminal_height():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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


async def test_samples_pane_aggregates_across_voices_and_dedups():
    # A fake bridge with 3 voices: two single-sample voices sharing sample 7,
    # and one multisample voice (flagged via the spec's 0x3FFF voice-level
    # sentinel, not a count field — see EosRemoteApp._voice_sample_info /
    # RESOLUTION_NOTES §11) with 3 zones: samples 7, 9, and 9 again (the
    # same voice hitting the same sample from two different zones -- a very
    # normal pattern, e.g. two key ranges sharing one recording) -- exercises
    # both the cross-voice dedup AND the same-voice-multiple-zones dedup in
    # EosRemoteApp._resolve_sample_rows independent of DemoBridge's
    # simplicity (which only ever has one voice/one zone).
    class FakeBridge(DemoBridge):
        def preset_num_voices(self, preset, *, timeout=None):
            return 3

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
                    return 0x3FFF  # multisample sentinel at voice level
                return {0: 7, 1: 9, 2: 9}.get(zone, 0)  # zone 3 reads 0 -> ends the scan
            return 0

        def set_parameter(self, param_id, value):
            from eos import params as p
            if param_id == p.lookup("VOICE_SELECT").id:
                self._voice = value
                self._zone = None
            elif param_id == p.lookup("SAMPLE_ZONE_SELECT").id:
                self._zone = value

        def get_sample_name(self, sample, *, timeout=None):
            return {7: "Shared Kick", 9: "Extra Snare"}.get(sample, "")

    app = EosRemoteApp(FakeBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.compact_view is True
        assert "compact" in app.query_one("#tables").classes
        assert app.query_one("#voices").display is False
        assert app.query_one("#samples").display is False


async def test_toggle_view_shows_and_hides_voice_and_samples_panes():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app1 = EosRemoteApp(DemoBridge(), allow_write=True, demo=False,
                        connect_kwargs={"config_path": config_path})
    async with app1.run_test() as pilot:
        await pilot.pause()
        assert app1.compact_view is True  # nothing stored yet -> default
        await pilot.press("e")
        await pilot.pause()
        assert app1.compact_view is False

    app2 = EosRemoteApp(DemoBridge(), allow_write=True, demo=False,
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
    assert calls == []


async def test_browse_voices_with_exactly_one_skips_the_prompt():
    # A prompt whose only valid answer is "1" is just an extra keypress —
    # 'v' should jump straight there instead. DemoBridge always has exactly
    # one voice, so this is the path _select_voice takes in every other test.
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
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

    app = EosRemoteApp(FakeBridge(), allow_write=True, demo=True)
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

    app = EosRemoteApp(FakeBridge(), allow_write=True, demo=True)
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
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        assert await _wait_for(pilot, lambda: table.row_count)
