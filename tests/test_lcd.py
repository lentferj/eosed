# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# Synthetic: these run against a capture committed in docs/captures, never
# against hardware.

import json
import pathlib

from eos import lcd

CAPTURE = (pathlib.Path(__file__).resolve().parent.parent
           / "docs" / "captures" / "panel_e4xt_fw470_2026-08-14.jsonl")


def _frames():
    return [json.loads(line)["bytes"] for line in
            CAPTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _full_screen():
    return max(_frames(), key=len)


def test_decodes_a_real_captured_screen():
    bitmap = lcd.decode_display(_full_screen())
    assert bitmap is not None
    assert len(bitmap) == lcd.HEIGHT
    assert all(len(row) == lcd.WIDTH for row in bitmap)


def test_the_decoded_screen_is_not_blank_or_solid():
    # A wrong decoding tends to produce noise near 50% or an almost-empty
    # field; the real screen is mostly background with text on it.
    bitmap = lcd.decode_display(_full_screen())
    lit = sum(sum(row) for row in bitmap)
    fraction = lit / (lcd.WIDTH * lcd.HEIGHT)
    assert 0.05 < fraction < 0.45, f"suspicious ink fraction {fraction:.2f}"


def test_horizontal_rules_are_straight():
    # The regression that matters. The first decoding (MIDI 7->8 byte packing)
    # produced exactly the right *size* -- 2195 septets x 7/8 truncates to
    # 1920 bytes, which is 240x64/8 -- so the arithmetic appeared to confirm
    # it while the picture sheared progressively across the screen. A shear
    # bends the dialog box's own horizontal rules; a correct decode leaves
    # them flat. Size alone cannot tell these apart, which is why this test
    # looks at geometry instead.
    bitmap = lcd.decode_display(_full_screen())
    rows = [sum(row) for row in bitmap]
    best = max(range(lcd.HEIGHT), key=lambda y: rows[y])
    run = 0
    longest = 0
    for bit in bitmap[best]:
        run = run + 1 if bit else 0
        longest = max(longest, run)
    assert longest > 100, (
        f"longest unbroken horizontal run is only {longest}px; a decoded "
        f"screen's box rules should be far longer than that")


def test_decode_rejects_frames_that_are_not_display_frames():
    button = [0xF0, 0x18, 0x7F, 0x7A, 0x05, 0x40, 0x5C, 0x00, 0x01, 0xF7]
    assert lcd.decode_display(button) is None
    assert lcd.decode_display([]) is None


def test_partial_frames_are_recognised_and_not_decoded():
    # 86- and 112-byte 50h frames appear alongside the full ones; their region
    # encoding is unknown, so they must not be rendered as if they were a
    # whole screen (§26).
    partials = [f for f in _frames()
                if len(f) > 6 and f[5] == 0x50 and len(f) < 500]
    assert partials, "capture should contain the short 50h frames"
    for frame in partials:
        assert lcd.is_partial(frame)
        assert lcd.decode_display(frame) is None
    assert not lcd.is_partial(_full_screen())


def test_braille_render_has_the_expected_shape():
    bitmap = lcd.decode_display(_full_screen())
    lines = lcd.to_braille(bitmap)
    assert len(lines) == lcd.HEIGHT // 4
    assert all(len(line) == lcd.WIDTH // 2 for line in lines)
    assert all(all(0x2800 <= ord(ch) <= 0x28FF for ch in line) for line in lines)


def test_halfblock_render_has_the_expected_shape():
    bitmap = lcd.decode_display(_full_screen())
    lines = lcd.to_halfblocks(bitmap)
    assert len(lines) == lcd.HEIGHT // 2
    assert all(len(line) == lcd.WIDTH for line in lines)


def test_renders_are_not_uniform():
    # Catches an all-blank or all-solid decode slipping through the renderers.
    # to_ascii only ever emits two symbols by design, so the bar is "more than
    # one", not "many" -- an assertion tuned to the richer renderers would
    # fail on the honest behaviour of the simplest one.
    bitmap = lcd.decode_display(_full_screen())
    for render in (lcd.to_braille, lcd.to_halfblocks, lcd.to_ascii):
        text = "\n".join(render(bitmap))
        assert len(set(text) - {"\n"}) > 1, f"{render.__name__} produced flat output"
