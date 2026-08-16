# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# Synthetic only. The panel screen is driven with run_test() and a fake send
# callable -- no MIDI port is opened and no hardware is reachable, which
# matters more here than elsewhere: this is the one screen whose whole purpose
# is transmitting on an undocumented protocol.

import pytest

from eos import panel as pp
from eos.panel import Key
from eosed.panel import KEYMAP, WHEEL, PanelScreen, render_panel


# --- protocol frames (§28-§30) ----------------------------------------------

def test_open_session_is_the_captured_frame():
    # Byte-for-byte what §28 recorded off the wire. This is the only frame
    # this project sends that it did not first observe, so it is pinned
    # exactly rather than approximately.
    assert pp.open_session(0x05) == [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x10, 0xF7]


def test_open_session_carries_the_device_id_not_a_fixed_byte():
    # §3 recorded this position as fixed 00; §28 showed it is the machine's
    # real device id. Getting this wrong makes a live machine look dead.
    assert pp.open_session(0x00)[3] == 0x00
    assert pp.open_session(0x7F)[3] == 0x7F


def test_button_frames_are_a_down_up_pair():
    down, up = pp.press(0x05, Key.MASTER)
    assert down == [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x5C, 0x00, 0x01, 0xF7]
    assert up == [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x5C, 0x00, 0x00, 0xF7]


def test_dial_encodes_signed_14_bit_lsb_first():
    # The exact values observed in §30, both directions.
    assert pp.dial(0x05, +1)[6:9] == [0x01, 0x01, 0x00]
    assert pp.dial(0x05, +2)[6:9] == [0x01, 0x02, 0x00]
    assert pp.dial(0x05, -1)[6:9] == [0x01, 0x7F, 0x7F]
    assert pp.dial(0x05, -2)[6:9] == [0x01, 0x7E, 0x7F]


def test_dial_round_trips_through_the_parser():
    for delta in (-100, -3, -1, 0, 1, 3, 100):
        assert pp.parse_dial(pp.dial(0x05, delta)) == delta


def test_dial_rejects_out_of_range():
    with pytest.raises(ValueError):
        pp.dial(0x05, 0x2000)


def test_parse_button_accepts_both_byte_orders():
    # Device->host is 7A <devID>, host->device is <devID> 7A (§30). A parser
    # that insisted on one silently drops half the conversation.
    from_device = [0xF0, 0x18, 0x7F, 0x7A, 0x05, 0x40, 0x5C, 0x00, 0x01, 0xF7]
    to_device = [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x5C, 0x00, 0x01, 0xF7]
    assert pp.parse_button(from_device) == (0x5C, True)
    assert pp.parse_button(to_device) == (0x5C, True)


def test_frames_reject_non_7bit_payload():
    with pytest.raises(ValueError):
        pp.button(0x05, 0x80, down=True)


def test_no_close_message_is_exposed():
    # §28a: the only published close frame has its manufacturer id transposed
    # and we have never captured one. Nothing here should offer to send it.
    assert not hasattr(pp, "close_session")


# --- the key map -------------------------------------------------------------

def test_every_bound_key_maps_to_a_real_panel_code():
    known = {int(k) for k in Key}
    for keyboard_key, code in KEYMAP.items():
        assert int(code) in known, f"{keyboard_key!r} maps to unknown code {code:#04x}"


def test_no_keyboard_key_is_bound_twice():
    assert len(set(KEYMAP)) == len(KEYMAP)


def test_no_panel_code_is_bound_twice():
    # Two keyboard keys sending the same panel button would be a layout bug --
    # the physical panel has one of each.
    codes = list(KEYMAP.values())
    assert len(set(codes)) == len(codes), "a panel code is reachable from two keys"


def test_the_whole_panel_is_reachable():
    # Every key code the capture identified must be pressable. If a later
    # session identifies 61h/67h, this fails until they are bound -- which is
    # the point: an unreachable button is an incomplete control surface.
    unbound = {int(k) for k in Key} - {int(c) for c in KEYMAP.values()}
    assert not unbound, f"unreachable panel keys: {[hex(c) for c in sorted(unbound)]}"


def test_bindings_are_positional_along_the_home_rows():
    # The design claim, asserted rather than left in a docstring: the upper
    # panel row runs left-to-right along QWERTY and the lower along ASDF.
    assert [KEYMAP[k] for k in "qwer"] == [
        Key.MASTER, Key.PRESET_MANAGE, Key.PRESET_EDIT, Key.AUDITION]
    assert [KEYMAP[k] for k in "asdfghjkl"] == [
        Key.DISK_BROWSE, Key.SAMPLE_MANAGE, Key.SAMPLE_EDIT,
        Key.ASSIGN_1, Key.ASSIGN_2, Key.ASSIGN_3,
        Key.PAGE_EXIT, Key.PAGE_PREV, Key.PAGE_NEXT]


def test_wheel_has_both_directions_and_a_coarse_step():
    assert WHEEL["["] < 0 < WHEEL["]"]
    assert WHEEL["{"] == -10 and WHEEL["}"] == +10


def test_render_panel_shows_every_key_hint():
    art = render_panel()
    for keyboard_key in ("q", "w", "e", "r", "a", "s", "d", "f1", "f6", ";"):
        assert f"({keyboard_key})" in art, f"{keyboard_key!r} missing from the drawn panel"


def test_render_panel_marks_the_armed_state_distinctly():
    assert "disarmed" in render_panel(armed=False)
    assert "ARMED" in render_panel(armed=True)


def test_render_panel_says_the_lcd_is_deliberately_absent():
    # The scope decision has to be visible in the UI, not only in TODO --
    # otherwise a blank rectangle reads as an unfinished feature.
    assert "not mirrored" in render_panel()


# --- the screen --------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.frames = []

    def __call__(self, frame):
        self.frames.append(list(frame))


async def _panel(allow_write=True, send=None):
    from textual.app import App

    class Host(App):
        def on_mount(self):
            self.push_screen(PanelScreen(allow_write=allow_write,
                                         device_id=0x05, send=send))

    return Host()


async def test_opening_the_panel_transmits_nothing():
    # The single most important property: arriving on this screen cannot
    # touch the hardware. Arming is a separate, deliberate act.
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert recorder.frames == []


async def test_keys_are_not_sent_while_disarmed():
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q", "f1", "]")
        await pilot.pause()
        assert recorder.frames == []
        assert "not sent" in app.screen.last_status


async def test_arming_then_pressing_sends_a_down_up_pair():
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.screen.armed
        await pilot.press("q")            # MASTER
        await pilot.pause()
        assert recorder.frames == [
            [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x5C, 0x00, 0x01, 0xF7],
            [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x5C, 0x00, 0x00, 0xF7],
        ]


async def test_cannot_arm_without_write_mode():
    # Two independent gates, not one: write mode is the app-wide decision,
    # arming is the per-session one. Neither alone reaches the device.
    recorder = _Recorder()
    app = await _panel(allow_write=False, send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert not app.screen.armed
        assert "write mode is off" in app.screen.last_status
        await pilot.press("q")
        await pilot.pause()
        assert recorder.frames == []


async def test_wheel_sends_a_single_delta_frame():
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.press("]")
        await pilot.pause()
        assert recorder.frames == [[0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x43,
                                    0x01, 0x01, 0x00, 0xF7]]


async def test_the_mode_is_exclusive_and_swallows_unmapped_keys():
    # The reason this matters: 'z' is Undo in the main view and nothing here.
    # If it leaked, a panel keypress would quietly mutate the preset the user
    # is not looking at.
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()
        assert "not a panel key" in app.screen.last_status
        assert recorder.frames == []


async def test_escape_leaves_the_panel():
    app = await _panel()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, PanelScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PanelScreen)


async def test_a_press_is_highlighted_even_when_nothing_is_sent():
    # With the LCD deliberately absent this is the only feedback the screen
    # can give, so a disarmed press must still show which button was hit.
    app = await _panel()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f3")
        await pilot.pause()
        assert app.screen.last_key == Key.F3


def test_every_panel_line_is_the_same_width():
    # Four separate alignment bugs were fixed by hand before this existed:
    # empty lines padding to full width, a row summing past the panel, hand-
    # counted widths that were wrong by one, and cell width vs character
    # count for box-drawing and em dashes. All of them are one assertion.
    from rich.text import Text

    from eosed.panel import PANEL_WIDTH

    for armed in (False, True):
        art = render_panel(active=Key.MASTER, armed=armed)
        widths = {Text.from_markup(line).cell_len for line in art.split("\n")}
        assert widths == {PANEL_WIDTH + 2}, (
            f"ragged panel (armed={armed}): widths {sorted(widths)}")


def test_visible_width_ignores_markup_but_not_content_brackets():
    from eosed.panel import visible_width

    assert visible_width("[b]abc[/b]") == 3
    # The wheel hints are content that looks like markup; miscounting them is
    # how the wheel row would drift while every other row stayed put.
    assert visible_width("([ ])") == 5


async def test_arming_with_no_device_says_so_rather_than_claiming_reach():
    # --demo has no send path. "ARMED - keys now reach the E4XT" would be true
    # of the armed state and false of this run, which is the exact shape of
    # documentation fault RESOLUTION_NOTES keeps recording.
    app = await _panel(send=None)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.screen.armed
        assert "no device connected" in app.screen.last_status
        await pilot.press("q")
        await pilot.pause()          # must not raise with send=None
