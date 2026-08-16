# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# Synthetic only. The probe under test never transmits, and these tests never
# open a MIDI port -- the analysis half is deliberately split from the I/O so
# it can be tested on a machine with no sampler attached.
#
# Worth testing at all because of what the failure looks like: a probe that
# mis-parses does not crash, it quietly produces a wrong summary during the
# one hardware session someone booked to answer a question. That is the same
# class as the vacuous test in §23 -- wrong in a way nothing announces.

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "probes"))

import panel_capture as pc                                    # noqa: E402


PANEL_ENABLE = [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x10, 0xF7]
PANEL_INIT = [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x7F, 0x11, 0x00, 0x08, 0xF7]
EDITOR_FRAME = [0xF0, 0x18, 0x21, 0x00, 0x55, 0x14, 0xF7]


# Real frames from the first live capture (2026-08-14, E4XT Ultra fw 4.70,
# §26). Note the shape: F0 18 7F <devID=05> 7A, NOT the F0 18 7F 00 00 that
# §3's third-party fragments record.
LIVE_BUTTON_DOWN = [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x68, 0x00, 0x01, 0xF7]
LIVE_BUTTON_UP = [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x40, 0x68, 0x00, 0x00, 0xF7]
LIVE_DISPLAY = [0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x50, 0x01, 0x01, 0x00, 0xF7]


def test_classify_recognises_the_real_frame_shape_not_just_the_published_one():
    # The regression that matters most here. The harness originally matched a
    # five-byte prefix from §3 and so filed every real panel frame as generic
    # "sysex" -- it watched the protocol it was built for go past and did not
    # recognise it. Device id is a real field (05 here), not a fixed 00.
    assert pc.classify(LIVE_BUTTON_DOWN) == "panel"
    assert pc.classify(LIVE_DISPLAY) == "panel"
    # ... and §3's published shape must still match, since it may be a
    # different firmware or a different point in the handshake.
    assert pc.classify(PANEL_ENABLE) == "panel"


def test_panel_opcode_reads_byte_five():
    assert pc.panel_opcode(LIVE_BUTTON_DOWN) == 0x40
    assert pc.panel_opcode(LIVE_DISPLAY) == 0x50
    assert pc.panel_opcode(EDITOR_FRAME) is None
    assert pc.panel_opcode([0xF0, 0x18, 0x7F]) is None      # too short to have one


def test_reanalysis_reclassifies_a_log_written_by_an_older_build():
    # The live capture was logged while the classifier still had §3's wrong
    # prefix, so every event carries dialect="sysex" on disk. Re-analysing it
    # after the fix has to produce the corrected answer -- otherwise the fix
    # is invisible exactly where it is needed, and the capture that cost a
    # hardware session stays mislabelled.
    capture = pc.Capture()
    capture.events.append({
        "kind": "frame", "at": 0.0, "port": "Midi Through",
        "dialect": "sysex",                       # what the old build wrote
        "length": len(LIVE_BUTTON_DOWN), "hex": pc.hexs(LIVE_BUTTON_DOWN),
        "bytes": LIVE_BUTTON_DOWN,
    })
    report = capture.report()
    assert "panel      1" in report
    assert "button down/up" in report
    assert "no panel frames" not in report


def test_report_flags_an_unknown_opcode_rather_than_hiding_it():
    # A new opcode is the whole point of a capture session; it must stand out
    # rather than be silently omitted because it is not in the table.
    capture = pc.Capture()
    capture.add_frame([0xF0, 0x18, 0x7F, 0x05, 0x7A, 0x77, 0xF7], port="x", at=0.0)
    assert "unknown" in capture.report()


def test_classify_separates_the_two_dialects():
    # The whole point of §3: these are different protocols on one wire, and
    # conflating them is the documented mistake.
    assert pc.classify(PANEL_ENABLE) == "panel"
    assert pc.classify(EDITOR_FRAME) == "editor"


def test_classify_does_not_claim_other_emu_products():
    # §4: Proteus (18h 0Fh) and Morpheus (18h 0Ch) share E-mu's manufacturer
    # id. Matching on 18h alone would file them as EOS traffic.
    proteus = [0xF0, 0x18, 0x0F, 0x00, 0x55, 0x01, 0xF7]
    morpheus = [0xF0, 0x18, 0x0C, 0x00, 0x01, 0xF7]
    assert pc.classify(proteus) == "sysex"
    assert pc.classify(morpheus) == "sysex"


def test_classify_requires_the_editor_designator():
    # 21h family without the 55h designator byte is not the editor protocol.
    assert pc.classify([0xF0, 0x18, 0x21, 0x00, 0x00, 0xF7]) == "sysex"


def test_classify_handles_non_sysex_and_empty():
    assert pc.classify([0x90, 0x40, 0x7F]) == "non-sysex"
    assert pc.classify([]) == "non-sysex"


def test_known_fragments_are_recognised_but_only_exactly():
    assert pc.describe_known(PANEL_INIT) == "init handshake"
    assert pc.describe_known(PANEL_ENABLE) == "enable remote"
    # A frame that merely starts like one must not be labelled as it -- the
    # published fragments are third-party and unverified, so a loose match
    # would manufacture agreement with a document we have not confirmed.
    assert pc.describe_known(PANEL_INIT[:-1] + [0x00, 0xF7]) is None


def test_diff_positions_finds_changed_offsets():
    assert pc.diff_positions([1, 2, 3], [1, 9, 3]) == [1]
    assert pc.diff_positions([1, 2, 3], [1, 2, 3]) == []


def test_diff_positions_refuses_different_lengths():
    # A length change is a different message, not a diff. Reporting it as one
    # would spray false "varying offsets" exactly where the display encoding
    # is supposed to show up.
    assert pc.diff_positions([1, 2, 3], [1, 2]) == []


def test_summarise_diffs_separates_moving_bytes_from_structure():
    # Three same-length frames where only offset 5 ever moves: that is the
    # shape a delta-encoded screen would have, and offsets that never move are
    # header/opcode.
    frames = [
        [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x01, 0xF7],
        [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x02, 0xF7],
        [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x03, 0xF7],
    ]
    stats = pc.summarise_diffs(frames)[7]
    assert stats["count"] == 3
    assert stats["varying"] == {5: 2}
    assert 5 not in stats["constant"]
    assert 0 in stats["constant"] and 6 in stats["constant"]


def test_summarise_diffs_groups_by_length_independently():
    short = [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x10, 0xF7]
    long_a = [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x20, 0x00, 0xF7]
    long_b = [0xF0, 0x18, 0x7F, 0x00, 0x00, 0x20, 0x01, 0xF7]
    summary = pc.summarise_diffs([short, long_a, long_b])
    assert set(summary) == {7, 8}
    assert summary[7]["varying"] == {}      # only one frame of this length
    assert summary[8]["varying"] == {6: 1}


def test_capture_records_frames_markers_and_round_trips_through_a_file(tmp_path):
    capture = pc.Capture()
    capture.add_marker("about to press F1", at=0.0)
    capture.add_frame(PANEL_ENABLE, port="E4XT", at=0.5)
    capture.add_frame(EDITOR_FRAME, port="E4XT", at=0.9)

    path = tmp_path / "panel.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in capture.events) + "\n",
                    encoding="utf-8")

    reloaded = pc.load_capture(str(path))
    assert reloaded.events == capture.events
    # --analyse must produce the same summary offline as the live run did,
    # since the whole point is thinking about it after the rack is closed.
    assert reloaded.report() == capture.report()


def test_report_names_the_panel_frames_and_flags_an_empty_capture():
    empty = pc.Capture()
    empty.add_frame(EDITOR_FRAME, port="x", at=0.0)
    text = empty.report()
    assert "no panel frames" in text

    live = pc.Capture()
    live.add_frame(PANEL_INIT, port="x", at=0.0)
    live.add_frame(PANEL_ENABLE, port="x", at=0.1)
    text = live.report()
    assert "init handshake" in text
    assert "enable remote" in text


def test_report_recognises_fragments_in_a_log_without_the_known_field():
    # Found by running --analyse on a hand-built log: report() used to read
    # the stored "known" key, so a log that lacked it reported "no known
    # fragments seen" while containing the handshake -- which reads as the
    # finding that §3's published bytes do not match this device. Wrong in
    # the most expensive direction, so the label is derived from the bytes.
    capture = pc.Capture()
    capture.events.append({
        "kind": "frame", "at": 0.1, "port": "E4XT", "dialect": "panel",
        "length": len(PANEL_INIT), "hex": pc.hexs(PANEL_INIT),
        "bytes": PANEL_INIT,          # note: no "known" key
    })
    assert "init handshake" in capture.report()


def test_report_tolerates_a_frame_event_with_no_bytes():
    # Defensive: a truncated final line in a log killed mid-session should
    # summarise what survived rather than take the analysis down with it.
    capture = pc.Capture()
    capture.events.append({"kind": "frame", "at": 0.0, "dialect": "panel", "length": 0})
    capture.report()


def test_report_says_so_when_no_known_fragment_appears():
    # A capture with panel traffic but none of §3's fragments is a real
    # finding -- the published handshake would be wrong or version-specific --
    # so it must be stated, not left as an absence the reader has to notice.
    capture = pc.Capture()
    capture.add_frame([0xF0, 0x18, 0x7F, 0x00, 0x00, 0x42, 0xF7], port="x", at=0.0)
    assert "none" in capture.report()
