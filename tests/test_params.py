# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# Synthetic only — no hardware/MIDI ports involved.

import pytest

from eos import params as p


def test_parameter_count_matches_expected_gaps():
    # ids 0-271 (the last one the spec defines, MASTER_AUDITION_KEY) minus
    # the spec's own "not used" gaps (22, 36, 196, 197, 200).
    expected_ids = set(range(0, 272)) - {22, 36, 196, 197, 200}
    assert set(p.PARAMETERS) == expected_ids


def test_link_parameter_count_matches_dump_format():
    # The spec's dump format states 29 Link parameters, 58 bytes per Link —
    # ids 23-35 plus the filter-enable flags at 251-266. A mismatch here means
    # the parameter table and the dump byte count disagree about what a Link is.
    link_ids = [pid for pid, param in p.PARAMETERS.items() if param.group.startswith("link")]
    assert len(link_ids) == 29


def test_lookup_by_id_and_name_agree():
    by_id = p.lookup(1)
    by_name = p.lookup("E4_PRESET_VOLUME")
    assert by_id is by_name
    assert by_id.id == 1


def test_lookup_missing_id_raises_keyerror():
    with pytest.raises(KeyError):
        p.lookup(9999)


def test_lookup_missing_name_raises_keyerror():
    with pytest.raises(KeyError):
        p.lookup("NOT_A_REAL_PARAMETER")


def test_cord_parameters_cover_18_cords():
    cord_ids = [pid for pid, param in p.PARAMETERS.items() if param.group == "voice.cords"]
    assert len(cord_ids) == 54  # 18 cords x (SRC, DST, AMT)
    for cord in range(18):
        assert p.lookup(f"E4_VOICE_CORD{cord}_SRC").minimum == 0
        assert p.lookup(f"E4_VOICE_CORD{cord}_SRC").maximum == 255
        assert p.lookup(f"E4_VOICE_CORD{cord}_AMT").minimum == -100
        assert p.lookup(f"E4_VOICE_CORD{cord}_AMT").maximum == 100


def test_every_parameter_has_sane_range():
    for param in p.PARAMETERS.values():
        assert param.minimum <= param.maximum, f"{param.name}: min > max"


@pytest.mark.parametrize("name,expected_min,expected_max", [
    ("E4_PRESET_TRANSPOSE", -24, 24),
    ("E4_PRESET_VOLUME", -96, 10),
    ("PRESET_SELECT", 0, 999),
    ("GROUP_SELECT", 0, 31),
    ("MASTER_TRANSPOSE", -12, 12),
])
def test_spot_check_known_ranges(name, expected_min, expected_max):
    param = p.lookup(name)
    assert (param.minimum, param.maximum) == (expected_min, expected_max)


# --- display conversion functions: cross-checked against the spec's own
#     worked boundary examples, not just internal self-consistency ----------

def test_glide_rate_matches_spec_reference_table_tail():
    # The spec's separate 0.000-32.738 sec/oct reference list ends at 32.738,
    # which must correspond to the max raw value (127).
    assert p.cnv_glide_rate(127) == "32.738sec/oct"
    assert p.cnv_glide_rate(0) == "0.000sec/oct"


def test_morph_freq_matches_spec_stated_eq_range():
    # Spec: "EQ 2 Low: 83Hz to 9824Hz (see Filter Table 5)" and Filter Table 5
    # is cnv_morph_freq(2*input) for input 0..127 — so raw 0 must be 83Hz.
    assert p.cnv_morph_freq(0) == "83Hz"


def test_morph_gain_boundaries():
    assert p.cnv_morph_gain(0) == "-24.0dB"
    assert p.cnv_morph_gain(127) == "+23.6dB"


def test_filter_table_1_boundaries():
    assert p.filter_table_1(255) == "20000Hz"


def test_master_tuning_sign_and_symmetry():
    assert p.cnv_master_tuning(0) == "+0.0"
    assert p.cnv_master_tuning(64) == "+100.0"
    assert p.cnv_master_tuning(-64) == "-100.0"


def test_chorus_itd_sign_and_symmetry():
    assert p.cnv_chorus_itd(0) == "+0.0ms"
    assert p.cnv_chorus_itd(32) == "+1.451ms"
    assert p.cnv_chorus_itd(-32) == "-1.451ms"


def test_lfo_rate_is_a_fit_and_says_so():
    """It used to raise NotImplementedError: the spec's display table wraps
    across a PDF page and could not be transcribed unambiguously (§6a). It is
    now mpc2emu's hardware-measured fit instead, and the leading "~" is part
    of the contract -- it marks a value that approximates the front panel
    rather than reproducing the spec's table exactly."""
    text = p.cnv_lfo_rate(10)
    assert text.startswith("~") and text.endswith("Hz"), text


def test_midi_control_display_labels():
    assert p.midi_control_display(-1) == "off"
    assert p.midi_control_display(32) == "ptwheel"
    assert p.midi_control_display(33) == "chnpres"
    assert p.midi_control_display(5) == "5"


def test_enum_tables_cover_their_full_range():
    assert set(p.VOICE_SOLO_MODES) == set(range(0, 9))
    assert set(p.VOICE_ASSIGN_GROUPS) == set(range(0, 24))
    assert set(p.LFO_SHAPES) == set(range(0, 8))


# --- FX algorithm/parameter name tables + describe_value --------------------

def test_fx_a_algorithm_names_cover_spec_derived_count():
    # 44 names (ids 0-43), matching the manual's row-major table expansion —
    # id 44 (the SysEx spec's stated max) has no known name; see the
    # module-level caveat in eos/params.py.
    assert len(p.FX_A_ALGORITHM_NAMES) == 44
    assert set(p.FX_A_ALGORITHM_NAMES) == set(range(44))
    assert 44 not in p.FX_A_ALGORITHM_NAMES


def test_fx_b_algorithm_names_exceed_old_spec_max():
    # 32 names from the newer EOS 4.0 manual; the older SysEx spec's stated
    # max is only 27 — ids 28-31 are a manual-only, hardware-unconfirmed
    # extension. Both facts are asserted here so a future edit can't silently
    # "fix" this apparent inconsistency without re-reading why it exists.
    assert len(p.FX_B_ALGORITHM_NAMES) == 32
    assert set(p.FX_B_ALGORITHM_NAMES) == set(range(32))
    assert p.lookup("E4_PRESET_FX_B_ALGORITHM").maximum == 27


@pytest.mark.parametrize("value,expected", [
    (0, "Room 1"), (5, "Plate"), (18, "Spacious Hall"), (43, "DelayVerb 9"),
])
def test_fx_a_algorithm_name_spot_checks(value, expected):
    assert p.FX_A_ALGORITHM_NAMES[value] == expected


@pytest.mark.parametrize("value,expected", [
    (0, "Chorus 1"), (24, "Dual Tap 1/3"), (31, "Distorted Double"),
])
def test_fx_b_algorithm_name_spot_checks(value, expected):
    assert p.FX_B_ALGORITHM_NAMES[value] == expected


def test_lfo_rate_matches_the_measured_anchors():
    """The fit is mpc2emu's, read off the E4XT's own rate menu. Its three
    published anchors must be reproduced exactly, and it must be monotonic --
    a quadratic that turned over inside 0..127 would map two bytes to one Hz
    (its vertex sits at ~134, safely outside)."""
    assert p.cnv_lfo_rate(0) == "~0.08Hz"
    assert p.cnv_lfo_rate(64) == "~4.12Hz"
    assert p.cnv_lfo_rate(127) == "~18.01Hz"

    hz = [float(p.cnv_lfo_rate(v).strip("~").rstrip("Hz")) for v in range(128)]
    assert hz == sorted(hz), "LFO rate must increase monotonically with the byte"
    assert all(0.07 < v < 18.1 for v in hz)


def test_lfo_rate_reaches_describe_value_for_both_lfos():
    """It was implemented but unreachable at first -- the function existed and
    describe_value still returned the bare number."""
    for name in ("E4_VOICE_LFO_RATE", "E4_VOICE_LFO2_RATE"):
        text = p.describe_value(p.PARAMETERS_BY_NAME[name], 64)
        assert text == "64 (~4.12Hz)", (name, text)


def test_describe_value_aligned_puts_the_sign_outside_the_digits():
    """Every row's first digit must land in the same column, with the minus
    hanging to its left -- that is what makes the Parameters pane readable as
    a column of numbers, rather than each value starting wherever."""
    volume = p.PARAMETERS_BY_NAME["E4_GEN_VOLUME"]        # -96..10
    pan = p.PARAMETERS_BY_NAME["E4_GEN_PAN"]              # -64..63

    assert p.describe_value_aligned(volume, 0) == " 0"
    assert p.describe_value_aligned(volume, -6) == "-6"
    assert p.describe_value_aligned(pan, -64) == "-64"
    assert p.describe_value_aligned(pan, 63) == " 63"

    # The first digit sits at index 1 regardless of sign or width.
    for param, value in ((volume, 0), (volume, -6), (volume, -96), (pan, 63)):
        text = p.describe_value_aligned(param, value)
        assert text[0] in " -"
        assert text[1].isdigit(), text

    # The "(Name)" suffix still follows, unchanged.
    algo = p.PARAMETERS_BY_NAME["E4_PRESET_FX_A_ALGORITHM"]
    assert p.describe_value_aligned(algo, 0) == " 0 (Room 1)"


def test_describe_value_aligned_never_breaks_on_a_boundary():
    """Same walk describe_value gets: a label table indexing on the raw value
    must not explode at min/max/0 in the aligned form either."""
    for param in p.PARAMETERS.values():
        for value in (param.minimum, param.maximum, 0):
            text = p.describe_value_aligned(param, value)
            assert text[0] in " -", (param.name, value, text)
            assert text[1].isdigit(), (param.name, value, text)


def test_describe_value_fx_algorithm():
    param = p.lookup("E4_PRESET_FX_A_ALGORITHM")
    assert p.describe_value(param, 18) == "18 (Spacious Hall)"
    param_b = p.lookup("MASTER_FX_B_ALGORITHM")
    assert p.describe_value(param_b, 24) == "24 (Dual Tap 1/3)"


def test_describe_value_fx_parm_and_amt():
    parm0 = p.lookup("E4_PRESET_FX_A_PARM_0")
    assert p.describe_value(parm0, 40) == "40 (Decay Time)"
    parm2 = p.lookup("E4_PRESET_FX_A_PARM_2")  # not documented -> no name
    assert p.describe_value(parm2, 5) == "5"
    amt1 = p.lookup("E4_PRESET_FX_A_AMT_1")
    assert p.describe_value(amt1, 20) == "20 (Sub 1)"
    b_parm2 = p.lookup("MASTER_FX_B_PARM_2")
    assert p.describe_value(b_parm2, 7) == "7 (Delay Time)"


def test_describe_value_falls_back_to_raw_number_when_unmapped():
    param = p.lookup("E4_PRESET_VOLUME")
    assert p.describe_value(param, -6) == "-6"


def test_describe_value_cord_source_and_destination():
    src = p.lookup("E4_VOICE_CORD0_SRC")
    assert p.describe_value(src, 17) == "17 (ModWl)"
    dst = p.lookup("E4_VOICE_CORD0_DST")
    assert p.describe_value(dst, 48) == "48 (Pitch)"


def test_describe_value_voice_solo_and_midi_control():
    solo = p.lookup("E4_VOICE_SOLO")
    assert p.describe_value(solo, 2) == "2 (Melody (last))"
    ctrl = p.lookup("MIDIGLO_PITCH_CONTROL")
    assert p.describe_value(ctrl, -1) == "-1 (off)"
    assert p.describe_value(ctrl, 32) == "32 (ptwheel)"


# --- filter type names + envelope segment labels ----------------------------

def test_filter_type_names_cover_manuals_stated_count():
    # "21 filter types are currently implemented" (manual, ch. 8)
    assert len(p.FILTER_TYPE_NAMES) == 21
    assert set(p.FILTER_TYPE_NAMES) == set(range(21))


@pytest.mark.parametrize("value,expected", [
    (0, "2-Pole Lowpass"), (1, "4-Pole Lowpass"), (7, "Contrary Bandpass"),
    (18, "2EQ + Lowpass Morph"), (19, "2EQ Morph + Expression"), (20, "Peak/Shelf Morph"),
])
def test_filter_type_name_spot_checks(value, expected):
    assert p.FILTER_TYPE_NAMES[value] == expected


def test_describe_value_filter_type():
    ftype = p.lookup("E4_VOICE_FTYPE")
    assert p.describe_value(ftype, 0) == "0 (2-Pole Lowpass)"
    assert p.describe_value(ftype, 18) == "18 (2EQ + Lowpass Morph)"


def test_filter_type_names_match_sysex_spec_overlay_headers():
    # Cross-check: the last three filter type names independently corroborate
    # the filter-type-dependent parameter-overlay headers transcribed from
    # the SysEx spec (docs/RESOLUTION_NOTES.md §2) — not just a repeated
    # read of the same source.
    assert p.FILTER_TYPE_NAMES[18] == "2EQ + Lowpass Morph"
    assert p.FILTER_TYPE_NAMES[20] == "Peak/Shelf Morph"


@pytest.mark.parametrize("param_name,value,expected", [
    ("E4_VOICE_VENV_SEG0_RATE", 87, "87 (Atk1 Rate)"),
    ("E4_VOICE_VENV_SEG0_TGTLVL", 50, "50 (Atk1 Level)"),
    ("E4_VOICE_FENV_SEG3_TGTLVL", 55, "55 (Atk2 Level)"),
    ("E4_VOICE_AENV_SEG5_RATE", 12, "12 (Rls2 Rate)"),
])
def test_describe_value_envelope_segments(param_name, value, expected):
    assert p.describe_value(p.lookup(param_name), value) == expected


def test_describe_value_does_not_leak_long_caveat_notes_as_a_fake_name():
    # E4_VOICE_FILT_GEN_PARM3's notes are a caveat sentence, not a value
    # name — must not be shown in brackets as if it were one.
    param = p.lookup("E4_VOICE_FILT_GEN_PARM3")
    assert p.describe_value(param, 9) == "9"


# --- derived value descriptions ---------------------------------------------

def test_note_name_matches_the_specs_own_boundary_values():
    # The -2 octave offset is pinned by the spec's own two statements about
    # these fields: "60 = C3" (E4_GEN_ORIG_KEY) and the range "C-2 -> G8".
    assert p.note_name(0) == "C-2"
    assert p.note_name(60) == "C3"
    assert p.note_name(127) == "G8"


def test_key_parameters_display_note_names_but_fades_do_not():
    for name in ("E4_GEN_ORIG_KEY", "E4_GEN_KEY_LOW", "E4_GEN_KEY_HIGH",
                 "E4_LINK_KEY_LOW", "E4_LINK_KEY_HIGH", "MASTER_AUDITION_KEY"):
        assert p.describe_value(p.lookup(name), 60) == "60 (C3)"
    # A fade is a width in semitones, not a key -- labelling it "C-2" would
    # be actively wrong, so these must stay bare numbers.
    for name in ("E4_GEN_KEY_LOWFADE", "E4_GEN_KEY_HIGHFADE",
                 "E4_LINK_KEY_LOWFADE", "E4_LINK_KEY_HIGHFADE"):
        assert p.describe_value(p.lookup(name), 0) == "0"


def test_volenv_depth_spans_the_specs_stated_db_range():
    # Spec: "-96dB to -48dB by 3's" -- the top of the raw range must land on
    # -48 exactly, which is what confirms the 3 dB step.
    assert p.volenv_depth_display(0) == "-96dB"
    assert p.volenv_depth_display(16) == "-48dB"


def test_all_fifteen_link_filter_flags_describe_as_on_off():
    flags = [param for param in p.PARAMETERS.values()
             if param.name.startswith("E4_LINK_FILTER_")]
    # 15, not 16: ids 251-266 is 16 parameters, but 251 is the link *type*.
    assert len(flags) == 15
    for param in flags:
        assert p.describe_value(param, 0) == "0 (off)"
        assert p.describe_value(param, 1) == "1 (on)"


def test_scsi_term_and_combine_lr_keep_the_specs_inverted_sense():
    # Both are stated 0 = on / 1 = off. Normalising them silently would
    # misreport the device.
    for name in ("MASTER_SCSI_TERM", "MASTER_COMBINE_LR"):
        assert p.describe_value(p.lookup(name), 0) == "0 (on)"
        assert p.describe_value(p.lookup(name), 1) == "1 (off)"


def test_link_type_covers_internal_plus_sixteen_midi_channels():
    param = p.lookup("E4_LINK_INTERNAL_EXTERNAL")
    assert p.describe_value(param, 0) == "0 (internal)"
    assert p.describe_value(param, 1) == "1 (MIDI ch 1)"
    # The manual's "up to 16 external MIDI devices" has to reach the
    # parameter's own maximum, or the inference behind this mapping is wrong.
    assert p.describe_value(param, param.maximum) == "16 (MIDI ch 16)"


def test_channel_and_offset_style_displays():
    assert p.describe_value(p.lookup("MIDIGLO_BASIC_CHANNEL"), 0) == "0 (ch 1)"
    assert p.describe_value(p.lookup("MASTER_FX_MM_CTRL_CHANNEL"), -1) == "-1 (off)"
    assert p.describe_value(p.lookup("MIDIGLO_MAGIC_PRESET"), 0) == "0 (off)"
    assert p.describe_value(p.lookup("MIDIGLO_MAGIC_PRESET"), 1) == "1 (preset 000)"
    assert p.describe_value(p.lookup("MIDIGLO_VEL_CURVE"), 0) == "0 (linear)"
    assert p.describe_value(p.lookup("MASTER_USING_MAC"), -1) == "-1 (none)"


def test_describe_value_never_raises_across_every_parameters_full_range():
    # A label table that indexes or slices on the raw value must not explode
    # on a boundary -- the device is the authority on range, not our table.
    for param in p.PARAMETERS.values():
        for value in (param.minimum, param.maximum, 0):
            assert isinstance(p.describe_value(param, value), str)
