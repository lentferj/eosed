# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
#
# This file is part of eosremote.  Original work.  GPL-2.0-or-later.
#
# Synthetic only — no hardware/MIDI ports involved.

import pytest

from eos import params as p


def test_parameter_count_matches_expected_gaps():
    # ids 0-258 minus the spec's own "not used" gaps (22, 36, 196, 197, 200).
    expected_ids = set(range(0, 259)) - {22, 36, 196, 197, 200}
    assert set(p.PARAMETERS) == expected_ids


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


def test_lfo_rate_deliberately_not_implemented():
    # See docs/RESOLUTION_NOTES.md §2 — transcription ambiguity, not a bug.
    with pytest.raises(NotImplementedError):
        p.cnv_lfo_rate(10)


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
