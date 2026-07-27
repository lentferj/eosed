# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
#
# This file is part of eosremote.  Original work.  GPL-2.0-or-later.
#
# --demo mode never opens a MIDI port — synthetic only.

import pytest

from eosremote import demo as demo_mod
from eosremote.app import EosRemoteApp
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


async def test_app_mounts_and_lists_presets():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        assert await _wait_for(pilot, lambda: table.row_count)
        # The page size is dynamic (sized to the pane's height, see
        # EosRemoteApp._desired_browser_window), not a fixed constant.
        assert table.row_count == app.browser_window
        assert f"presets 0-{app.browser_window - 1}" in app.last_status


async def test_selecting_preset_loads_global_params():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")

        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count)
        assert params.row_count == 22  # GLOBAL group size
        assert app.current_preset == 0
        assert app.current_group == "global"
        assert "global parameters" in app.last_status


async def test_edit_value_writes_through_and_refreshes_table():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")
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
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")
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
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")
        await _wait_for(pilot, lambda: app.current_preset == 0)

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


async def test_master_menu_delete_preset_requires_arm_then_fire():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")
        await _wait_for(pilot, lambda: app.current_preset == 0)

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
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")
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


async def test_browse_voices_and_back_to_global():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)
        await pilot.click("#presets")
        presets.move_cursor(row=0)
        await pilot.press("enter")
        await _wait_for(pilot, lambda: app.current_group == "global")

        await pilot.press("v")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        index_input = app.screen_stack[-1].query_one("#value")
        await pilot.click("#value")
        await pilot.press("1")  # front-panel numbering starts at V1, not 0
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: app.current_group == "voice")
        assert app.current_voice == 0  # V1 displayed -> stored 0-based for VOICE_SELECT
        params = app.query_one("#params")
        assert await _wait_for(pilot, lambda: params.row_count > 22)  # full voice.* group

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: app.current_group == "global")
        assert await _wait_for(pilot, lambda: params.row_count == 22)


async def test_goto_preset_out_of_current_window():
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        presets = app.query_one("#presets")
        await _wait_for(pilot, lambda: presets.row_count)

        await pilot.press("g")
        assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
        goto_input = app.screen_stack[-1].query_one("#value")
        await pilot.click("#value")
        for ch in "5":
            await pilot.press(ch)
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: app.current_preset == 5)
        assert await _wait_for(pilot, lambda: app.current_group == "global")
        # preset 5 is within the initial 0-15 window: no rescan, cursor moves
        assert await _wait_for(pilot, lambda: presets.cursor_row == 5)


async def _goto(pilot, app, text):
    await pilot.press("g")
    assert await _wait_for(pilot, lambda: len(app.screen_stack) > 1)
    await pilot.click("#value")
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")


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
        assert await _wait_for(pilot, lambda: app._bank_state("preset").window_start == expected_start)
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


async def test_demo_never_touches_rtmidi(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "rtmidi", None)
    app = EosRemoteApp(DemoBridge(), allow_write=True, demo=True)
    async with app.run_test() as pilot:
        table = app.query_one("#presets")
        assert await _wait_for(pilot, lambda: table.row_count)
