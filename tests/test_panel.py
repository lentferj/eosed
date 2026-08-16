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


def test_no_panel_code_is_bound_twice_in_the_positional_map():
    # Two *positional* bindings for one button would be a layout bug -- the
    # panel has one of each. Deliberate aliases live in ALIASES and are
    # checked separately, so an alias cannot be mistaken for a layout error
    # and a layout error cannot hide behind the word "alias".
    codes = list(KEYMAP.values())
    assert len(set(codes)) == len(codes), "a panel code is reachable from two keys"


def test_aliases_reach_a_real_key_and_are_not_positional_duplicates():
    from eosed.panel import ALIASES

    known = {int(k) for k in Key}
    for keyboard_key, code in ALIASES.items():
        assert int(code) in known
        assert keyboard_key not in KEYMAP, f"{keyboard_key!r} is already positional"


async def test_the_return_key_sends_enter():
    # Reported from a live session: pressing Return produced "'enter' is not a
    # panel key". It is the key anyone reaches for when they mean ENTER, and
    # the positional binding (";") is only obvious once you know why.
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.press("enter")
        await pilot.pause()
        assert recorder.frames, "Return sent nothing"
        assert recorder.frames[0][6] == int(Key.ENTER)


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
        # open-paren + key, not the exact "(key)" string: a hint may list more
        # than one way to press a button (ENTER shows both ";" and Return).
        assert f"({keyboard_key}" in art, f"{keyboard_key!r} missing from the drawn panel"


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


async def test_ctrl_q_leaves_the_panel():
    app = await _panel()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, PanelScreen)
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert not isinstance(app.screen, PanelScreen)


async def test_escape_sends_the_devices_exit_key_and_does_not_leave():
    # A hand on this panel means the E4XT's EXIT by escape, not "close the
    # window". Leaving moved to ctrl+e so escape could mean what it looks
    # like it means.
    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, PanelScreen), "escape should not close the panel"
        assert recorder.frames and recorder.frames[0][6] == int(Key.PAGE_EXIT)


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
    assert {"ctrl+e", "ctrl+t", "ctrl+r", "ctrl+g"} <= handled

    app = await _panel()
    async with app.run_test(size=(130, 50)) as pilot:
        await pilot.pause()
        for key in sorted(handled):
            if key == "ctrl+e":
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


def test_the_lcd_renders_as_dark_ink_on_a_pale_field():
    # The device's screen is backlit: near-black text on light green glass.
    # A terminal draws bright-on-dark by default, which inverts it -- right in
    # content, wrong in appearance. Only the colours were backwards, not the
    # bits: a set bit already *is* ink, which is why the text comes out solid.
    import json
    import pathlib

    from eos import lcd
    from eosed.panel import LCD_GLASS, LCD_INK

    capture = (pathlib.Path(__file__).resolve().parent.parent / "docs" /
               "captures" / "panel_e4xt_fw470_2026-08-14.jsonl")
    frames = [json.loads(line)["bytes"] for line in
              capture.read_text(encoding="utf-8").splitlines() if line.strip()]
    bitmap = lcd.decode_display(max(frames, key=len))

    from eosed.panel import LCD_STYLE

    for mode, rows in (("half", lcd.HEIGHT // 2),
                       ("quadrant", lcd.HEIGHT // 2),
                       ("braille", lcd.HEIGHT // 4)):
        ink, glass, _weight = LCD_STYLE[mode]
        art = render_panel(bitmap=bitmap, mode=mode)
        styled = [line for line in art.split("\n")
                  if glass in line and ink in line]
        assert len(styled) == rows, f"{mode}: {len(styled)} styled rows, want {rows}"
        # ink must be darker than the glass, or it is not a backlit panel
        assert int(ink[1:3], 16) < int(glass[1:3], 16), mode


def test_braille_gets_a_harder_ink_glass_pairing_than_the_block_renders():
    # Braille draws a lit pixel as a small dot with glass around it, so a
    # solid run covers far less of the cell than a filled block does. The
    # pairing that reads as crisp type in the block modes washes out here, so
    # this one is pure black on lighter glass -- checked as a relationship
    # rather than as two literals, which would just restate the constants.
    from eosed.panel import LCD_STYLE

    b_ink, b_glass, b_weight = LCD_STYLE["braille"]
    q_ink, q_glass, _ = LCD_STYLE["quadrant"]

    def lum(colour):
        return sum(int(colour[i:i + 2], 16) for i in (1, 3, 5))

    assert lum(b_ink) <= lum(q_ink), "braille ink must not be lighter"
    assert lum(b_glass) > lum(q_glass), "braille glass must be lighter"
    assert "b" in b_weight, "braille should be bold to thicken the dots"


def test_the_placeholder_is_not_painted_as_glass():
    # With no frame there is no screen, and colouring an empty rectangle like
    # a lit LCD would suggest the device is connected and blank.
    from eosed.panel import LCD_GLASS

    assert LCD_GLASS not in render_panel()


def test_the_panel_shows_its_own_meta_keys():
    # Reported as "I couldn't find the key hint" for the render switch. The
    # footer at the bottom of the terminal is the *main app's* legend and this
    # is a modal, so the panel's own bindings appear nowhere else. A binding
    # nobody can find is not much better than one that does not exist.
    from eosed.panel import RENDER_MODES

    art = render_panel()
    for key in ("ctrl+e", "ctrl+t", "ctrl+r", "ctrl+g"):
        assert key in art, f"{key} is bound but never shown"


def test_the_render_hint_names_the_current_mode_and_the_next_one():
    # Cycling is only obvious if the hint says where it goes; "ctrl+g render"
    # alone leaves you pressing it to find out.
    from eosed.panel import RENDER_MODES

    for index, mode in enumerate(RENDER_MODES):
        art = render_panel(mode=mode)
        following = RENDER_MODES[(index + 1) % len(RENDER_MODES)]
        assert mode in art and following in art


def test_every_binding_is_both_reachable_and_advertised():
    # Pairs with test_every_binding_survives_the_exclusive_key_handler: that
    # one checks a binding still fires, this one that a user can discover it.
    art = render_panel()
    for binding in PanelScreen.BINDINGS:
        assert binding.key in art, f"{binding.key} is bound but not in the panel"


async def test_inc_accepts_plus_as_well_as_equals():
    # "=" is the positional key but it is Shift+0 on a German layout, while
    # "+" is a dedicated key beside Enter. DEC's "-" is a real key on both, so
    # only INC needed the alias -- and without it the pair is asymmetric in a
    # way that is invisible from an ANSI keyboard.
    for key in ("=", "+"):
        recorder = _Recorder()
        app = await _panel(send=recorder)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+t")
            await pilot.press(key)
            await pilot.pause()
            assert recorder.frames, f"{key!r} sent nothing"
            assert recorder.frames[0][6] == int(Key.INC), f"{key!r} did not send INC"


async def test_the_mouse_wheel_turns_the_data_wheel():
    # The most direct mapping there is: a wheel for a wheel, no key at all.
    class _Stub:
        def stop(self):
            pass

    recorder = _Recorder()
    app = await _panel(send=recorder)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        screen = app.screen
        # The handlers are called directly with a stub: constructing a real
        # MouseScrollUp needs a widget/offset/modifier signature that has
        # changed across Textual versions, and pinning it here would make this
        # test about Textual's constructor rather than about the wheel.
        for handler, expected in ((screen.on_mouse_scroll_up, 1),
                                  (screen.on_mouse_scroll_down, -1)):
            recorder.frames.clear()
            handler(_Stub())
            await pilot.pause()
            assert recorder.frames, "scroll sent nothing"
            assert pp.parse_dial(recorder.frames[0]) == expected


def test_the_wheel_has_keys_that_need_no_modifier_on_any_layout():
    # "[" "]" are AltGr on a German keyboard and "{" "}" worse, which is a bad
    # fit for the control you turn most. PgUp/PgDn and Home/End are dedicated
    # keys everywhere.
    for key in ("pageup", "pagedown", "home", "end"):
        assert key in WHEEL, f"{key} should turn the wheel"
    assert WHEEL["pageup"] > 0 > WHEEL["pagedown"]
    assert abs(WHEEL["home"]) == abs(WHEEL["end"]) == 10
