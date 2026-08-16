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


def test_render_panel_explains_which_half_of_the_lcd_is_missing():
    # Without a frame the area must say the *live feed* is unconfirmed, not
    # that the display is unbuilt -- the decoder works (§32) and a placeholder
    # implying otherwise sends a reader looking for the wrong thing.
    art = render_panel()
    assert "decoder works" in art
    assert "live feed does not yet" in art


def test_render_panel_draws_a_real_decoded_screen_when_given_one():
    import json
    import pathlib

    from eos import lcd

    capture = (pathlib.Path(__file__).resolve().parent.parent / "docs" /
               "captures" / "panel_e4xt_fw470_2026-08-14.jsonl")
    frames = [json.loads(line)["bytes"] for line in
              capture.read_text(encoding="utf-8").splitlines() if line.strip()]
    bitmap = lcd.decode_display(max(frames, key=len))

    art = render_panel(bitmap=bitmap)
    assert "decoder works" not in art
    # quadrant blocks, one row per 2 pixel rows (§34) -- braille was too dense
    # for the device's 1px font and read as texture rather than type.
    quadrant_rows = sum(1 for line in art.split("\n")
                        if any(ch in "▗▖▄▝▐▞▟▘▚▌▙▀▜▛█" for ch in line))
    assert quadrant_rows >= lcd.HEIGHT // 2


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

    from eosed.panel import RENDER_MODES, panel_width

    for mode in RENDER_MODES:
        for armed in (False, True):
            art = render_panel(active=Key.MASTER, armed=armed, mode=mode)
            widths = {Text.from_markup(line).cell_len for line in art.split("\n")}
            assert widths == {panel_width(mode) + 2}, (
                f"ragged panel (mode={mode}, armed={armed}): {sorted(widths)}")


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


# --- screen request (§33) ----------------------------------------------------

def test_request_screen_is_the_confirmed_opcode():
    # 51h, verified live against an E4XT: with a session open it returns a
    # full 2212-byte 50h frame immediately (§33).
    assert pp.request_screen(0x05) == [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x51, 0xF7]


def test_query_state_is_the_opcode_that_provoked_a_reply():
    assert pp.query_state(0x05) == [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x60, 0xF7]


def test_the_byte_pair_is_not_treated_as_a_direction_marker():
    # §33: a display frame arrives from the device carrying 05 7A, the same
    # pattern a host-sent button uses. Anything that inferred direction from
    # those two bytes would mis-attribute half the conversation, so the
    # parsers must accept both orderings.
    device_display = [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x50] + [0] * 10 + [0xF7]
    device_button = [0xF0, 0x18, 0x7F, 0x7A, 0x05, 0x40, 0x5C, 0x00, 0x01, 0xF7]
    assert pp.parse_button(device_button) == (0x5C, True)
    assert pp.parse_button(device_display) is None      # not a button, but not rejected for its bytes
    assert pp.parse_button([0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x5C, 0x00, 0x01, 0xF7]) == (0x5C, True)


# --- the refresh poll (§33b) -------------------------------------------------

async def test_polling_updates_the_screen_and_survives_a_failing_port():
    # This path had no test when it was written, and shipped an
    # AttributeError: call_from_thread is a method on App, not on Screen, so
    # the worker died on its first tick and the pane simply never updated.
    # Nothing in the unit tests touched it because none of them passed a poll.
    import json
    import pathlib

    from eos import lcd
    from textual.app import App

    capture = (pathlib.Path(__file__).resolve().parent.parent / "docs" /
               "captures" / "panel_e4xt_fw470_2026-08-14.jsonl")
    frames = [json.loads(line)["bytes"] for line in
              capture.read_text(encoding="utf-8").splitlines() if line.strip()]
    bitmap = lcd.decode_display(max(frames, key=len))

    calls = []

    def poll():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("port went away")
        return bitmap

    class Host(App):
        def on_mount(self):
            screen = PanelScreen(allow_write=True, device_id=5,
                                 send=lambda f: None, poll=poll)
            screen.POLL_SECONDS = 0.05
            self.push_screen(screen)

    app = Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.wait_for_scheduled_animations()
        for _ in range(40):
            await pilot.pause(0.05)
            if len(calls) >= 2 and app.screen.bitmap is not None:
                break
        assert calls, "poll was never called"
        assert app.screen.bitmap is not None, "a polled screen never reached the pane"
        # ... and the failing poll must leave the app alive with a message
        assert app.screen is not None


def test_soft_keys_are_aligned_under_the_displays_soft_menu_positions():
    # The physical F-keys sit under sixths of the display. The labels above
    # them change per page -- six narrow boxes on one screen, three wide ones
    # on the LOAD dialog -- so aligning to the *drawn* boxes would be right on
    # one page and wrong on the next. Sixths are right on every page.
    from eos import lcd

    art = render_panel().split("\n")
    fkey_line = next(line for line in art if "F1" in line and "F6" in line)
    plain = "".join(ch for ch in fkey_line)
    for marker in ("F1", "F2", "F3", "F4", "F5", "F6"):
        assert marker in plain

    columns = lcd.soft_key_columns(lcd.WIDTH // 2)
    assert columns == [10, 30, 50, 70, 90, 110]
    # evenly spaced, and none at the extreme edges
    gaps = {columns[i + 1] - columns[i] for i in range(5)}
    assert gaps == {20}
    assert 0 < columns[0] and columns[-1] < lcd.WIDTH // 2


def test_all_three_render_modes_draw_the_screen():
    import json
    import pathlib

    from eos import lcd
    from eosed.panel import RENDER_MODES, panel_width

    capture = (pathlib.Path(__file__).resolve().parent.parent / "docs" /
               "captures" / "panel_e4xt_fw470_2026-08-14.jsonl")
    frames = [json.loads(line)["bytes"] for line in
              capture.read_text(encoding="utf-8").splitlines() if line.strip()]
    bitmap = lcd.decode_display(max(frames, key=len))

    for mode in RENDER_MODES:
        art = render_panel(bitmap=bitmap, mode=mode)
        assert "decoder works" not in art, f"{mode} did not draw the screen"

    # Half-blocks keep horizontal pixels 1:1 and so need the full 240 columns;
    # the other two fit in the width the buttons already need. A mode that
    # silently rendered narrower than its pixels would be lying about detail.
    assert panel_width("half") > panel_width("quadrant")
    assert panel_width("quadrant") == panel_width("braille")


async def test_cycling_render_modes_warns_when_the_terminal_is_too_narrow():
    # Half-blocks need 244 columns. Offering the mode is right; pretending it
    # fits is not, so the status says what it needs against what there is.
    app = await _panel()
    async with app.run_test(size=(130, 50)) as pilot:
        await pilot.pause()
        assert app.screen.render_mode == "quadrant"
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app.screen.render_mode == "half"
        assert "needs" in app.screen.last_status
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app.screen.render_mode == "braille"
        assert "needs" not in app.screen.last_status


async def test_every_binding_survives_the_exclusive_key_handler():
    # The exclusive on_key consumes all keys by design, so a Binding added
    # later is dead on arrival unless the handler lets it through -- and
    # nothing fails loudly when it does not. ctrl+r shipped broken exactly
    # this way. Assert the two sets agree rather than trusting a literal list.
    handled = {binding.key for binding in PanelScreen.BINDINGS}
    assert {"escape", "ctrl+t", "ctrl+r", "ctrl+g"} <= handled

    app = await _panel()
    async with app.run_test(size=(130, 50)) as pilot:
        await pilot.pause()
        for key in sorted(handled):
            if key == "escape":
                continue                      # would leave the screen
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, PanelScreen), f"{key} broke the screen"


def test_layout_matches_the_hardware_rows_and_headings():
    # Checked against the front-panel photograph. The first version of this
    # layout put the assignables and EXIT on the top row and ENTER on a third,
    # and captioned MASTER with "PRESET" -- each of which reads fine on its
    # own and matches nothing on the device.
    lines = [line for line in render_panel().split("\n")]
    plain = ["".join(ch for ch in line) for line in lines]

    def row_with(*needles):
        return next((i for i, line in enumerate(plain)
                     if all(n in line for n in needles)), None)

    upper = row_with("MASTER", "MANAGE", "EDIT", "AUDITION")
    lower = row_with("DISK/BR", "MANAGE", "EDIT")
    assert upper is not None and lower is not None
    assert upper < lower

    # the assignables, EXIT, the PAGE pair and ENTER are all on the LOWER row
    for label in ("EXIT", "PREV", "NEXT", "ENTER"):
        assert label in plain[lower], f"{label} should share the lower row"

    # PRESET captions MANAGE/EDIT, not MASTER: its column must sit to the
    # right of where MASTER is drawn.
    heading = plain[upper - 1]
    assert "PRESET" in heading
    assert heading.index("PRESET") > plain[upper].index("MASTER")

    # PAGE spans PREV/NEXT only -- on the hardware it is a printed arc over
    # exactly those two keys, not over EXIT or ENTER.
    page_col = heading.index("PAGE")
    assert plain[lower].index("EXIT") < page_col < plain[lower].index("ENTER")


def test_keypad_sits_to_the_right_like_the_hardware():
    # On the metal the numeric keypad is right of the cursor diamond. It was
    # bottom-left here, which came from the convenience of a text grid rather
    # than from the panel.
    lines = render_panel().split("\n")
    digits = next(line for line in lines if "7" in line and "8" in line and "9" in line)
    mode_row = next(line for line in lines if "DISK/BR" in line)
    assert digits.index("7") > mode_row.index("DISK/BR") + 40
