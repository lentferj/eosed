# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.
# The parameter ids, names, ranges, units, and display-conversion formulas
# below are transcribed as data from E-mu's own protocol specification:
#   "Remote Preset Editing via MIDI SysEx", Draft #30, EOS 4.00
#   Brian Clark, E-mu Systems, 17 February 1999
# No source code from that document is copied. See docs/RESOLUTION_NOTES.md
# §2 for transcription notes, including one table (LFO rate display) that was
# deliberately left unimplemented due to an unresolved transcription ambiguity
# — see the module-level note near cnv_lfo_rate below.
#
# eosed is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# eosed is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""EOS editor-protocol parameter table.

Every parameter is addressed by a 14-bit id (see :mod:`eos.messages`'s
``ParameterEdit``/``ParameterRequest``). This module gives each id a name,
group, and a *static* min/max transcribed from the specification — but the
device's own ``03h``/``04h`` (Parameter Min/Max/Default Request/Response) is
authoritative at runtime and should be preferred where the two might drift
across EOS versions (see :class:`eos.messages.ParameterRange`).

Ids intentionally absent from :data:`PARAMETERS` (22, 36, 196, 197, 200) are
the specification's own "not used" gaps, not omissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Parameter:
    id: int
    name: str
    group: str
    minimum: int
    maximum: int
    unit: Optional[str] = None
    default: Optional[int] = None
    notes: Optional[str] = None


def _p(id_: int, name: str, group: str, minimum: int, maximum: int, *,
       unit: Optional[str] = None, default: Optional[int] = None,
       notes: Optional[str] = None) -> Parameter:
    return Parameter(id_, name, group, minimum, maximum, unit, default, notes)


_PARAMS: List[Parameter] = [
    # -- GLOBAL (ids 0-21; 22 not used) --------------------------------------
    _p(0, "E4_PRESET_TRANSPOSE", "global", -24, 24, unit="semitones"),
    _p(1, "E4_PRESET_VOLUME", "global", -96, 10, unit="dB"),
    _p(2, "E4_PRESET_CTRL_A", "global", -1, 127, notes="-1 = off"),
    _p(3, "E4_PRESET_CTRL_B", "global", -1, 127, notes="-1 = off"),
    _p(4, "E4_PRESET_CTRL_C", "global", -1, 127, notes="-1 = off"),
    _p(5, "E4_PRESET_CTRL_D", "global", -1, 127, notes="-1 = off"),
    _p(6, "E4_PRESET_FX_A_ALGORITHM", "global", 0, 44),
    _p(7, "E4_PRESET_FX_A_PARM_0", "global", 0, 90),
    _p(8, "E4_PRESET_FX_A_PARM_1", "global", 0, 127),
    _p(9, "E4_PRESET_FX_A_PARM_2", "global", 0, 127),
    _p(10, "E4_PRESET_FX_A_AMT_0", "global", 0, 100),
    _p(11, "E4_PRESET_FX_A_AMT_1", "global", 0, 100),
    _p(12, "E4_PRESET_FX_A_AMT_2", "global", 0, 100),
    _p(13, "E4_PRESET_FX_A_AMT_3", "global", 0, 100),
    _p(14, "E4_PRESET_FX_B_ALGORITHM", "global", 0, 27),
    _p(15, "E4_PRESET_FX_B_PARM_0", "global", 0, 127),
    _p(16, "E4_PRESET_FX_B_PARM_1", "global", 0, 127),
    _p(17, "E4_PRESET_FX_B_PARM_2", "global", 0, 127),
    _p(18, "E4_PRESET_FX_B_AMT_0", "global", 0, 100),
    _p(19, "E4_PRESET_FX_B_AMT_1", "global", 0, 100),
    _p(20, "E4_PRESET_FX_B_AMT_2", "global", 0, 100),
    _p(21, "E4_PRESET_FX_B_AMT_3", "global", 0, 100),

    # -- LINKS (ids 23-35; 36 not used) --------------------------------------
    _p(23, "E4_LINK_PRESET", "link", 0, 999, notes="1255 with Preset Flash"),
    _p(24, "E4_LINK_VOLUME", "link", -96, 10, unit="dB"),
    _p(25, "E4_LINK_PAN", "link", -64, 63),
    _p(26, "E4_LINK_TRANSPOSE", "link", -24, 24, unit="semitones"),
    _p(27, "E4_LINK_FINE_TUNE", "link", -64, 64),
    _p(28, "E4_LINK_KEY_LOW", "link", 0, 127, notes="C-2 -> G8"),
    _p(29, "E4_LINK_KEY_LOWFADE", "link", 0, 127),
    _p(30, "E4_LINK_KEY_HIGH", "link", 0, 127, notes="C-2 -> G8"),
    _p(31, "E4_LINK_KEY_HIGHFADE", "link", 0, 127),
    _p(32, "E4_LINK_VEL_LOW", "link", 0, 127),
    _p(33, "E4_LINK_VEL_LOWFADE", "link", 0, 127),
    _p(34, "E4_LINK_VEL_HIGH", "link", 0, 127),
    _p(35, "E4_LINK_VEL_HIGHFADE", "link", 0, 127),

    # -- VOICE: general (ids 37-56) ------------------------------------------
    _p(37, "E4_GEN_GROUP_NUM", "voice.general", 1, 32),
    _p(38, "E4_GEN_SAMPLE", "voice.general", 0, 999, notes="2999 with Sample Flash/ROM"),
    _p(39, "E4_GEN_VOLUME", "voice.general", -96, 10, unit="dB"),
    _p(40, "E4_GEN_PAN", "voice.general", -64, 63),
    _p(41, "E4_GEN_CTUNE", "voice.general", -72, 24, notes="Voice only"),
    _p(42, "E4_GEN_FTUNE", "voice.general", -64, 64),
    _p(43, "E4_GEN_XPOSE", "voice.general", -24, 24, unit="semitones", notes="Voice only"),
    _p(44, "E4_GEN_ORIG_KEY", "voice.general", 0, 127, notes="60 = C3; Sample only"),
    _p(45, "E4_GEN_KEY_LOW", "voice.general", 0, 127, notes="C-2 -> G8"),
    _p(46, "E4_GEN_KEY_LOWFADE", "voice.general", 0, 127),
    _p(47, "E4_GEN_KEY_HIGH", "voice.general", 0, 127, notes="C-2 -> G8"),
    _p(48, "E4_GEN_KEY_HIGHFADE", "voice.general", 0, 127),
    _p(49, "E4_GEN_VEL_LOW", "voice.general", 0, 127),
    _p(50, "E4_GEN_VEL_LOWFADE", "voice.general", 0, 127),
    _p(51, "E4_GEN_VEL_HIGH", "voice.general", 0, 127),
    _p(52, "E4_GEN_VEL_HIGHFADE", "voice.general", 0, 127),
    _p(53, "E4_GEN_RT_LOW", "voice.general", 0, 127, notes="Voice only"),
    _p(54, "E4_GEN_RT_LOWFADE", "voice.general", 0, 127, notes="Voice only"),
    _p(55, "E4_GEN_RT_HIGH", "voice.general", 0, 127, notes="Voice only"),
    _p(56, "E4_GEN_RT_HIGHFADE", "voice.general", 0, 127, notes="Voice only"),

    # -- VOICE: tuning / chorus / glide (ids 57-64) --------------------------
    _p(57, "E4_VOICE_NON_TRANSPOSE", "voice.tuning", 0, 1, notes="0=off, 1=on"),
    _p(58, "E4_VOICE_CHORUS_AMOUNT", "voice.tuning", 0, 100, unit="%"),
    _p(59, "E4_VOICE_CHORUS_WIDTH", "voice.tuning", -128, 0),
    _p(60, "E4_VOICE_CHORUS_X", "voice.tuning", -32, 32, unit="ms",
       notes="Chorus initial ITD; see cnv_chorus_itd()"),
    _p(61, "E4_VOICE_DELAY", "voice.tuning", 0, 10000, unit="ms"),
    _p(62, "E4_VOICE_START_OFFSET", "voice.tuning", 0, 127),
    _p(63, "E4_VOICE_GLIDE_RATE", "voice.tuning", 0, 127, unit="sec/oct",
       notes="Portamento; see cnv_glide_rate()"),
    _p(64, "E4_VOICE_GLIDE_CURVE", "voice.tuning", 0, 8,
       notes="0=linear .. 8=most exponential"),

    # -- VOICE: mode (ids 65-67) ----------------------------------------------
    _p(65, "E4_VOICE_SOLO", "voice.mode", 0, 8, notes="see VOICE_SOLO_MODES"),
    _p(66, "E4_VOICE_ASSIGN_GROUP", "voice.mode", 0, 23, notes="see VOICE_ASSIGN_GROUPS"),
    _p(67, "E4_VOICE_LATCHMODE", "voice.mode", 0, 1, notes="0=off, 1=on"),

    # -- VOICE: amplifier (ids 68-81) -----------------------------------------
    _p(68, "E4_VOICE_VOLENV_DEPTH", "voice.amp", 0, 16, notes="-96dB to -48dB by 3's"),
    _p(69, "E4_VOICE_SUBMIX", "voice.amp", -1, 3, notes="see SUBMIX_LABELS; 4-7 with Octopus card"),
    _p(70, "E4_VOICE_VENV_SEG0_RATE", "voice.amp.env", 0, 127, notes="Atk1 Rate"),
    _p(71, "E4_VOICE_VENV_SEG0_TGTLVL", "voice.amp.env", 0, 100, unit="%", notes="Atk1 Level"),
    _p(72, "E4_VOICE_VENV_SEG1_RATE", "voice.amp.env", 0, 127, notes="Dcy1 Rate"),
    _p(73, "E4_VOICE_VENV_SEG1_TGTLVL", "voice.amp.env", 0, 100, unit="%", notes="Dcy1 Level"),
    _p(74, "E4_VOICE_VENV_SEG2_RATE", "voice.amp.env", 0, 127, notes="Rls1 Rate"),
    _p(75, "E4_VOICE_VENV_SEG2_TGTLVL", "voice.amp.env", 0, 100, unit="%", notes="Rls1 Level"),
    _p(76, "E4_VOICE_VENV_SEG3_RATE", "voice.amp.env", 0, 127, notes="Atk2 Rate"),
    _p(77, "E4_VOICE_VENV_SEG3_TGTLVL", "voice.amp.env", 0, 100, unit="%", notes="Atk2 Level"),
    _p(78, "E4_VOICE_VENV_SEG4_RATE", "voice.amp.env", 0, 127, notes="Dcy2 Rate"),
    _p(79, "E4_VOICE_VENV_SEG4_TGTLVL", "voice.amp.env", 0, 100, unit="%", notes="Dcy2 Level"),
    _p(80, "E4_VOICE_VENV_SEG5_RATE", "voice.amp.env", 0, 127, notes="Rls2 Rate"),
    _p(81, "E4_VOICE_VENV_SEG5_TGTLVL", "voice.amp.env", 0, 100, unit="%", notes="Rls2 Level"),

    # -- VOICE: filter (ids 82-92) --------------------------------------------
    # NOTE: ids 87-92's *meaning* depends on E4_VOICE_FTYPE (the filter-type
    # dependent overlay: e.g. "2EQ+Lowpass Morph", "Peak/Shelf Morph", ...).
    # The ranges below are those ids' most common shape; see
    # docs/RESOLUTION_NOTES.md §2 for the filter-type overlay tables that were
    # captured, and re-check the source PDF before trusting an id 87-92
    # reading against an unfamiliar filter type.
    _p(82, "E4_VOICE_FTYPE", "voice.filter", 0, 255, notes="max is filter-type dependent ('variable' in spec)"),
    _p(83, "E4_VOICE_FMORPH", "voice.filter", 0, 255, notes="Fc/Morph"),
    _p(84, "E4_VOICE_FKEY_XFORM", "voice.filter", 0, 127, notes="meaning varies by filter type"),
    _p(85, "E4_VOICE_FILT_GEN_PARM1", "voice.filter", 0, 255, notes="reserved for future expansion"),
    _p(86, "E4_VOICE_FILT_GEN_PARM2", "voice.filter", 0, 255, notes="reserved for future expansion"),
    _p(87, "E4_VOICE_FILT_GEN_PARM3", "voice.filter", 0, 255, notes="filter-type dependent; see notes above"),
    _p(88, "E4_VOICE_FILT_GEN_PARM4", "voice.filter", 0, 255, notes="filter-type dependent; see notes above"),
    _p(89, "E4_VOICE_FILT_GEN_PARM5", "voice.filter", 0, 255, notes="filter-type dependent; see notes above"),
    _p(90, "E4_VOICE_FILT_GEN_PARM6", "voice.filter", 0, 255, notes="filter-type dependent; see notes above"),
    _p(91, "E4_VOICE_FILT_GEN_PARM7", "voice.filter", 0, 255, notes="filter-type dependent; see notes above"),
    _p(92, "E4_VOICE_FILT_GEN_PARM8", "voice.filter", 0, 255, notes="filter-type dependent; see notes above"),

    # -- VOICE: filter envelope (ids 93-104) -----------------------------------
    _p(93, "E4_VOICE_FENV_SEG0_RATE", "voice.filter.env", 0, 127, notes="Atk1 Rate"),
    _p(94, "E4_VOICE_FENV_SEG0_TGTLVL", "voice.filter.env", 0, 100, unit="%", notes="Atk1 Level"),
    _p(95, "E4_VOICE_FENV_SEG1_RATE", "voice.filter.env", 0, 127, notes="Dcy1 Rate"),
    _p(96, "E4_VOICE_FENV_SEG1_TGTLVL", "voice.filter.env", 0, 100, unit="%", notes="Dcy1 Level"),
    _p(97, "E4_VOICE_FENV_SEG2_RATE", "voice.filter.env", 0, 127, notes="Rls1 Rate"),
    _p(98, "E4_VOICE_FENV_SEG2_TGTLVL", "voice.filter.env", 0, 100, unit="%", notes="Rls1 Level"),
    _p(99, "E4_VOICE_FENV_SEG3_RATE", "voice.filter.env", 0, 127, notes="Atk2 Rate"),
    _p(100, "E4_VOICE_FENV_SEG3_TGTLVL", "voice.filter.env", 0, 100, unit="%", notes="Atk2 Level"),
    _p(101, "E4_VOICE_FENV_SEG4_RATE", "voice.filter.env", 0, 127, notes="Dcy2 Rate"),
    _p(102, "E4_VOICE_FENV_SEG4_TGTLVL", "voice.filter.env", 0, 100, unit="%", notes="Dcy2 Level"),
    _p(103, "E4_VOICE_FENV_SEG5_RATE", "voice.filter.env", 0, 127, notes="Rls2 Rate"),
    _p(104, "E4_VOICE_FENV_SEG5_TGTLVL", "voice.filter.env", 0, 100, unit="%", notes="Rls2 Level"),

    # -- VOICE: LFOs (ids 105-116) ----------------------------------------------
    _p(105, "E4_VOICE_LFO_RATE", "voice.lfo", 0, 127, notes="see LFO_SHAPES; display table not transcribed, see cnv_lfo_rate()"),
    _p(106, "E4_VOICE_LFO_SHAPE", "voice.lfo", 0, 7, notes="see LFO_SHAPES"),
    _p(107, "E4_VOICE_LFO_DELAY", "voice.lfo", 0, 127),
    _p(108, "E4_VOICE_LFO_VAR", "voice.lfo", 0, 100, unit="%"),
    _p(109, "E4_VOICE_LFO_SYNC", "voice.lfo", 0, 1, notes="0=key sync, 1=free run"),
    _p(110, "E4_VOICE_LFO2_RATE", "voice.lfo", 0, 127, notes="see cnv_lfo_rate()"),
    _p(111, "E4_VOICE_LFO2_SHAPE", "voice.lfo", 0, 7, notes="see LFO_SHAPES"),
    _p(112, "E4_VOICE_LFO2_DELAY", "voice.lfo", 0, 127),
    _p(113, "E4_VOICE_LFO2_VAR", "voice.lfo", 0, 100, unit="%"),
    _p(114, "E4_VOICE_LFO2_SYNC", "voice.lfo", 0, 1, notes="0=key sync, 1=free run"),
    _p(115, "E4_VOICE_LFO2_OP0_PARM", "voice.lfo", 0, 10, notes="Lag0"),
    _p(116, "E4_VOICE_LFO2_OP1_PARM", "voice.lfo", 0, 10, notes="Lag1"),

    # -- VOICE: aux (LFO2-driven / auxiliary) envelope (ids 117-128) ------------
    _p(117, "E4_VOICE_AENV_SEG0_RATE", "voice.aux.env", 0, 127, notes="Atk1 Rate"),
    _p(118, "E4_VOICE_AENV_SEG0_TGTLVL", "voice.aux.env", 0, 100, unit="%", notes="Atk1 Level"),
    _p(119, "E4_VOICE_AENV_SEG1_RATE", "voice.aux.env", 0, 127, notes="Dcy1 Rate"),
    _p(120, "E4_VOICE_AENV_SEG1_TGTLVL", "voice.aux.env", 0, 100, unit="%", notes="Dcy1 Level"),
    _p(121, "E4_VOICE_AENV_SEG2_RATE", "voice.aux.env", 0, 127, notes="Rls1 Rate"),
    _p(122, "E4_VOICE_AENV_SEG2_TGTLVL", "voice.aux.env", 0, 100, unit="%", notes="Rls1 Level"),
    _p(123, "E4_VOICE_AENV_SEG3_RATE", "voice.aux.env", 0, 127, notes="Atk2 Rate"),
    _p(124, "E4_VOICE_AENV_SEG3_TGTLVL", "voice.aux.env", 0, 100, unit="%", notes="Atk2 Level"),
    _p(125, "E4_VOICE_AENV_SEG4_RATE", "voice.aux.env", 0, 127, notes="Dcy2 Rate"),
    _p(126, "E4_VOICE_AENV_SEG4_TGTLVL", "voice.aux.env", 0, 100, unit="%", notes="Dcy2 Level"),
    _p(127, "E4_VOICE_AENV_SEG5_RATE", "voice.aux.env", 0, 127, notes="Rls2 Rate"),
    _p(128, "E4_VOICE_AENV_SEG5_TGTLVL", "voice.aux.env", 0, 100, unit="%", notes="Rls2 Level"),

    # -- VOICE: cords (ids 129-182; 18 cords x SRC/DST/AMT) ---------------------
    *(
        p
        for cord in range(18)
        for p in (
            _p(129 + cord * 3, f"E4_VOICE_CORD{cord}_SRC", "voice.cords", 0, 255,
               notes="see CORD_SOURCES"),
            _p(130 + cord * 3, f"E4_VOICE_CORD{cord}_DST", "voice.cords", 0, 255,
               notes="see CORD_DESTINATIONS"),
            _p(131 + cord * 3, f"E4_VOICE_CORD{cord}_AMT", "voice.cords", -100, 100),
        )
    ),

    # -- MASTER (ids 183+) -------------------------------------------------------
    _p(183, "MASTER_TUNING_OFFSET", "master", -64, 64, notes="see cnv_master_tuning()"),
    _p(184, "MASTER_TRANSPOSE", "master", -12, 12, unit="semitones", notes="0 = off (C)"),
    _p(185, "MASTER_HEADROOM", "master", 0, 15),
    _p(186, "MASTER_HCHIP_BOOST", "master", 0, 1, notes="0=+0dB, 1=+12dB"),
    _p(187, "MASTER_OUTPUT_FORMAT", "master", 0, 2, notes="0=analog, 1=AES pro, 2=S/PDIF"),
    _p(188, "MASTER_OUTPUT_CLOCK", "master", 0, 1, notes="0=44.1kHz, 1=48kHz"),
    _p(189, "MASTER_AES_BOOST", "master", 0, 1, notes="0=off, 1=on"),
    _p(190, "MASTER_SCSI_ID", "master", 0, 7),
    _p(191, "MASTER_SCSI_TERM", "master", 0, 1, notes="spec: 0=on, 1=off (verify against hardware)"),
    _p(192, "MASTER_USING_MAC", "master", -1, 7,
       notes="Avoid Host on SCSI ID: -1=none, 0-7=ID0-7 (7=Mac)"),
    _p(193, "MASTER_COMBINE_LR", "master", 0, 1, notes="0=on, 1=off"),
    _p(194, "MASTER_AKAI_LOOP_ADJ", "master", 0, 1, notes="0=off, 1=on"),
    _p(195, "MASTER_AKAI_SAMPLER_ID", "master", -1, 7, notes="foreign sampler SCSI id; -1=none"),
    # 196, 197 not used
    _p(198, "MIDIGLO_BASIC_CHANNEL", "master.midi", 0, 15,
       notes="31 with MIDI expansion card; displayed as 1-16(32)"),
    _p(199, "MIDIGLO_MIDI_MODE", "master.midi", 0, 2, notes="0=omni, 1=poly, 2=multi"),
    # 200 not used
    _p(201, "MIDIGLO_PITCH_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(202, "MIDIGLO_MOD_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(203, "MIDIGLO_PRESSURE_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(204, "MIDIGLO_PEDAL_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(205, "MIDIGLO_SWITCH_1_CONTROL", "master.midi", -1, 33,
       notes="spec display: -1=off, 0-33=64-97 (unusual; verify against hardware)"),
    _p(206, "MIDIGLO_SWITCH_2_CONTROL", "master.midi", -1, 33,
       notes="spec display: -1=off, 0-33=64-97 (unusual; verify against hardware)"),
    _p(207, "MIDIGLO_THUMB_CONTROL", "master.midi", -1, 33,
       notes="spec display: -1=off, 0-33=64-97 (unusual; verify against hardware)"),
    _p(208, "MIDIGLO_MIDI_A_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(209, "MIDIGLO_MIDI_B_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(210, "MIDIGLO_MIDI_C_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(211, "MIDIGLO_MIDI_D_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(212, "MIDIGLO_MIDI_E_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(213, "MIDIGLO_MIDI_F_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(214, "MIDIGLO_MIDI_G_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(215, "MIDIGLO_MIDI_H_CONTROL", "master.midi", -1, 33, notes="see MIDI_CONTROL_DISPLAY"),
    _p(216, "MIDIGLO_VEL_CURVE", "master.midi", 0, 13, notes="0=linear, 1-13=curve 1-13"),
    _p(217, "MIDIGLO_VOLUME_SENSITIVITY", "master.midi", 0, 31),
    _p(218, "MIDIGLO_CTRL7_CURVE", "master.midi", 0, 2, notes="0=linear, 1=squared, 2=logarithmic"),
    _p(219, "MIDIGLO_PEDAL_OVERRIDE", "master.midi", 0, 1, notes="0=off, 1=on"),
    _p(220, "MIDIGLO_RCV_PROGRAM_CHANGE", "master.midi", 0, 1, notes="0=off, 1=on"),
    _p(221, "MIDIGLO_SEND_PROGRAM_CHANGE", "master.midi", 0, 1, notes="0=off, 1=on"),
    _p(222, "MIDIGLO_MAGIC_PRESET", "master.midi", 0, 128,
       notes="0=off, 1-128 -> presets 000-127"),
    _p(223, "PRESET_SELECT", "master.select", 0, 999,
       notes="independent of the front panel's own selection (spec-stated)"),
    _p(224, "LINK_SELECT", "master.select", 0, 255, notes="max = 255 - NumOfVoices"),
    _p(225, "VOICE_SELECT", "master.select", 0, 255, notes="max = 255 - NumOfLinks"),
    _p(226, "SAMPLE_ZONE_SELECT", "master.select", 0, 255),
    _p(227, "GROUP_SELECT", "master.select", 0, 31),
    _p(228, "MASTER_FX_A_ALGORITHM", "master.fx", 0, 44, default=14),
    _p(229, "MASTER_FX_A_PARM_0", "master.fx", 0, 90, default=54),
    _p(230, "MASTER_FX_A_PARM_1", "master.fx", 0, 127, default=64),
    _p(231, "MASTER_FX_A_PARM_2", "master.fx", 0, 127, default=0),
    _p(232, "MASTER_FX_A_AMT_0", "master.fx", 0, 100, default=10),
    _p(233, "MASTER_FX_A_AMT_1", "master.fx", 0, 100, default=20),
    _p(234, "MASTER_FX_A_AMT_2", "master.fx", 0, 100, default=30),
    _p(235, "MASTER_FX_A_AMT_3", "master.fx", 0, 100, default=40),
    _p(236, "MASTER_FX_B_ALGORITHM", "master.fx", 0, 27, default=1),
    _p(237, "MASTER_FX_B_PARM_0", "master.fx", 0, 127, default=0),
    _p(238, "MASTER_FX_B_PARM_1", "master.fx", 0, 127, default=3),
    _p(239, "MASTER_FX_B_PARM_2", "master.fx", 0, 127, default=0),
    _p(240, "MASTER_FX_B_AMT_0", "master.fx", 0, 100, default=10),
    _p(241, "MASTER_FX_B_AMT_1", "master.fx", 0, 100, default=15),
    _p(242, "MASTER_FX_B_AMT_2", "master.fx", 0, 100, default=30),
    _p(243, "MASTER_FX_B_AMT_3", "master.fx", 0, 100, default=0),
    _p(244, "MASTER_FX_BYPASS", "master.fx", 0, 1, default=0),
    _p(245, "MASTER_FX_MM_CTRL_CHANNEL", "master.fx", -1, 15, default=-1),
    _p(246, "MULTIMODE_CHANNEL", "master.multimode", 1, 16, default=1,
       notes="max 32 with MIDI expansion card"),
    _p(247, "MULTIMODE_PRESET", "master.multimode", -1, 999, default=-1,
       notes="max 1255 with Preset Flash"),
    _p(248, "MULTIMODE_VOLUME", "master.multimode", 0, 127, default=127),
    _p(249, "MULTIMODE_PAN", "master.multimode", -64, 63, default=0),
    _p(250, "MULTIMODE_SUBMIX", "master.multimode", -1, 3, default=-1,
       notes="max 7 with Output expansion card"),
    _p(251, "E4_LINK_INTERNAL_EXTERNAL", "link.filter", 0, 16, default=0),
    _p(252, "E4_LINK_FILTER_PITCH", "link.filter", 0, 1, default=0),
    _p(253, "E4_LINK_FILTER_MOD", "link.filter", 0, 1, default=0),
    _p(254, "E4_LINK_FILTER_PRESSURE", "link.filter", 0, 1, default=0),
    _p(255, "E4_LINK_FILTER_PEDAL", "link.filter", 0, 1, default=0),
    _p(256, "E4_LINK_FILTER_CTRL_A", "link.filter", 0, 1, default=0),
    _p(257, "E4_LINK_FILTER_CTRL_B", "link.filter", 0, 1, default=0),
    _p(258, "E4_LINK_FILTER_CTRL_C", "link.filter", 0, 1, default=0),
    _p(259, "E4_LINK_FILTER_CTRL_D", "link.filter", 0, 1, default=0),
    _p(260, "E4_LINK_FILTER_CTRL_E", "link.filter", 0, 1, default=0),
    _p(261, "E4_LINK_FILTER_CTRL_F", "link.filter", 0, 1, default=0),
    _p(262, "E4_LINK_FILTER_CTRL_G", "link.filter", 0, 1, default=0),
    _p(263, "E4_LINK_FILTER_CTRL_H", "link.filter", 0, 1, default=0),
    _p(264, "E4_LINK_FILTER_SWITCH_1", "link.filter", 0, 1, default=0),
    _p(265, "E4_LINK_FILTER_SWITCH_2", "link.filter", 0, 1, default=0),
    _p(266, "E4_LINK_FILTER_THUMB", "link.filter", 0, 1, default=0),
    # ids 251-266 are the spec's "0 = filter off / 1 = filter on" block; with
    # the 13 at ids 23-35 that makes the 29 Link parameters (58 bytes/link)
    # the dump format's own byte count calls for — the two now agree.

    # -- MASTER, continued (ids 267-271) ---------------------------------------
    # 267-270 sit inside the spec's own "/** ULTRA ONLY PARAMETERS **/" fence
    # — an E4XT/E6400 Ultra has them, a plain E4/E4XT does not. Our unit IS an
    # Ultra (member code (7,5), see docs/RESOLUTION_NOTES.md §7), so these are
    # expected to be live here; on a non-Ultra the device's own 03h/04h
    # min/max/default request is the authoritative "does this exist" check,
    # same as this module's docstring says for every other id.
    _p(267, "MASTER_WORD_CLOCK_IN", "master", 0, 4,
       notes="Ultra only; see WORD_CLOCK_IN_LABELS"),
    _p(268, "MASTER_WORD_CLOCK_PHASE_IN", "master", 0, 511,
       notes="Ultra only; 0.00-359.30 degrees in 512 increments"),
    _p(269, "MASTER_WORD_CLOCK_PHASE_OUT", "master", 0, 511,
       notes="Ultra only; 0.00-359.30 degrees in 512 increments"),
    _p(270, "MASTER_OUTPUT_DITHER", "master", 0, 1, notes="Ultra only; 0=off, 1=on"),
    # 271 is outside the Ultra-only fence — plain E4s have it too.
    _p(271, "MASTER_AUDITION_KEY", "master", 0, 127),
]

PARAMETERS: Dict[int, Parameter] = {p.id: p for p in _PARAMS}
PARAMETERS_BY_NAME: Dict[str, Parameter] = {p.name: p for p in _PARAMS}


# Spec text (Preset Dump Format section): "The Sample [Zone] Parameters
# consist of a subset of the General Parameters. Each additional Sample
# [zone] requires a block of information containing the Sample number, and
# the 12 Sample parameters." — i.e. id 38 (which sample) plus these 12,
# to the exclusion of E4_GEN_GROUP_NUM/CTUNE/XPOSE/RT_* (marked "Voice only"
# above: those apply to the whole multisample voice, not to one zone of it).
SAMPLE_ZONE_PARAM_IDS: List[int] = [38, 39, 40, 42, 44, 45, 46, 47, 48, 49, 50, 51, 52]


def lookup(id_or_name) -> Parameter:
    """Resolve a parameter by numeric id or by name (e.g. "E4_PRESET_VOLUME")."""
    if isinstance(id_or_name, int):
        try:
            return PARAMETERS[id_or_name]
        except KeyError:
            raise KeyError(f"no parameter with id {id_or_name}") from None
    try:
        return PARAMETERS_BY_NAME[id_or_name]
    except KeyError:
        raise KeyError(f"no parameter named {id_or_name!r}") from None


# --- small enumerations (spec's own named value lists) ----------------------

VOICE_SOLO_MODES: Dict[int, str] = {
    0: "Off", 1: "Multiple Trigger", 2: "Melody (last)", 3: "Melody (low)",
    4: "Melody (high)", 5: "Synth (last)", 6: "Synth (low)", 7: "Synth (high)",
    8: "Fingered Glide",
}

VOICE_ASSIGN_GROUPS: Dict[int, str] = {
    0: "Poly All", 1: "Poly16 A", 2: "Poly16 B", 3: "Poly 8 A", 4: "Poly 8 B",
    5: "Poly 8 C", 6: "Poly 8 D", 7: "Poly 4 A", 8: "Poly 4 B", 9: "Poly 4 C",
    10: "Poly 4 D", 11: "Poly 2 A", 12: "Poly 2 B", 13: "Poly 2 C", 14: "Poly 2 D",
    15: "Mono A", 16: "Mono B", 17: "Mono C", 18: "Mono D", 19: "Mono E",
    20: "Mono F", 21: "Mono G", 22: "Mono H", 23: "Mono I",
}

LFO_SHAPES: Dict[int, str] = {
    0: "triangle", 1: "sine", 2: "sawtooth", 3: "square", 4: "0,1,0,-1",
    5: "C,E,G,C", 6: "C,D,F,G", 7: "8st Pent",
}

SUBMIX_LABELS: Dict[int, str] = {
    -1: "voice", 0: "main", 1: "sub1", 2: "sub2", 3: "sub3",
    4: "sub4", 5: "sub5", 6: "sub6", 7: "sub7",  # 4-7 require the Octopus card
}

OUTPUT_FORMAT_LABELS: Dict[int, str] = {0: "analog", 1: "AES pro", 2: "S/PDIF"}
OUTPUT_CLOCK_LABELS: Dict[int, str] = {0: "44.1kHz", 1: "48kHz"}
# Ultra-only (MASTER_WORD_CLOCK_IN, id 267). The spec names 4 explicitly and
# labels the fifth "(future expansion)" — kept as the spec's own wording
# rather than dropped, so a device reporting 4 shows something meaningful.
WORD_CLOCK_IN_LABELS: Dict[int, str] = {
    0: "Internal", 1: "BNC", 2: "AES", 3: "ADAT", 4: "(future expansion)",
}
MIDI_MODE_LABELS: Dict[int, str] = {0: "omni", 1: "poly", 2: "multi"}
CTRL7_CURVE_LABELS: Dict[int, str] = {0: "linear", 1: "squared", 2: "logarithmic"}


def midi_control_display(value: int) -> str:
    """Display string for the MIDIGLO_*_CONTROL family (-1=off, 0-31, 32=ptwheel, 33=chnpres)."""
    if value == -1:
        return "off"
    if value == 32:
        return "ptwheel"
    if value == 33:
        return "chnpres"
    return str(value)


# Partial: the spec allows up to 256 source/destination codes; only the
# named ones actually captured from the source PDF are listed. An
# unrecognised code should be shown as its raw number, not an error.
CORD_SOURCES: Dict[int, str] = {
    0: "Off", 4: "XfdRnd", 8: "Key+", 9: "Key~", 10: "Vel+", 11: "Vel~",
    12: "Vel<", 13: "RlsVel", 14: "Gate", 16: "PitWl", 17: "ModWl",
    18: "Press", 19: "Pedal", 20: "MidiA", 21: "MidiB", 22: "FtSw1",
    23: "FtSw2", 24: "Ft1FF", 25: "Ft2FF", 26: "MidiVl", 27: "MidPn",
    32: "MidiC", 33: "MidiD", 34: "MidiE", 35: "MidiF", 36: "MidiG",
    37: "MidiH", 38: "Thumb", 39: "ThmFF", 48: "KeyGld",
    72: "VEnv+", 73: "VEnv~", 74: "VEnv<",
    80: "FEnv+", 81: "FEnv~", 82: "FEnv<",
    88: "AEnv+", 89: "AEnv~", 90: "AEnv<",
    96: "Lfo1~", 97: "Lfo1+", 98: "White", 99: "Pink", 100: "kRand1", 101: "kRand2",
    104: "Lfo2~", 105: "Lfo2+", 106: "Lag0in", 107: "Lag0", 108: "Lag1in", 109: "Lag1",
    144: "CkDwhl", 145: "CkWhle", 146: "CkHalf", 147: "CkQtr", 148: "Ck8th", 149: "Ck16th",
    160: "DC", 161: "Sum", 162: "Switch", 163: "Abs", 164: "Diode", 165: "FlipFlop",
    166: "Quantiz", 167: "Gain4X",
}

CORD_DESTINATIONS: Dict[int, str] = {
    0: "Off", 8: "KeySust", 47: "FinePtch", 48: "Pitch", 49: "Glide",
    50: "ChrsAmt", 51: "ChrsITD", 52: "SStart", 53: "SLoop", 54: "SRetrig",
    56: "FilFreq", 57: "FilRes", 64: "AmpVol", 65: "AmpPan", 66: "AmpXfd",
    72: "VEnvRts", 73: "VEnvAtk", 74: "VEnvDcy", 75: "VEnvRls",
    80: "FEnvRts", 81: "FEnvAtk", 82: "FEnvDcy", 83: "FEnvRls", 86: "FEnvTrig",
    88: "AEnvRts", 89: "AEnvAtk", 90: "AEnvDcy", 91: "AEnvRls", 94: "AEnvTrig",
    96: "Lfo1Rt", 97: "Lfo1Trig", 104: "Lfo2Rt", 105: "Lfo2Trig",
    106: "Lag0in", 108: "Lag1in",
    161: "Sum", 162: "Switch", 163: "Abs", 164: "Diode", 165: "FlipFlop",
    166: "Quantiz", 167: "Gain4X",
    168: "C00Amt", 169: "C01Amt", 170: "C02Amt", 171: "C03Amt",
}


# --- FX algorithm / parameter names (from the EOS 4.0 Software Manual) -----
# Source: "EOS 4.0 Software Manual", chapter 2 ("Master Effects A/B", pp.
# 97-98) and chapter 8 ("Preset Effects A/B", pp. 283-287) — cross-checked
# against each other (both list the identical names in the identical order,
# in a 3-column table). Neither page prints a numeric id column: the manual
# only names the effects, it never states which number selects which one.
#
# The mapping below ASSUMES id == the table's row-major (left-to-right,
# top-to-bottom) reading order — the standard convention for this kind of
# front-panel selector list, but NOT independently confirmed against real
# hardware or any numbered list in a source document. Expanding the printed
# ranges ("Room 1-3" -> Room 1, Room 2, Room 3; "Hall 1 & 2" -> Hall 1, Hall
# 2; etc.) in that order yields exactly 44 names (ids 0-43) for FX A and
# exactly 32 names (ids 0-31) for FX B.
#
# Two open discrepancies, deliberately not papered over:
#   - FX A: the SysEx spec states max=44 (45 valid ids, 0-44), but only 44
#     names exist here (0-43) — id 44's name is unknown.
#   - FX B: the SysEx spec states max=27 (28 valid ids), but this EOS 4.0
#     manual documents 32 B effects — ids 28-31 here come from the newer
#     manual only and may not exist on hardware running the SysEx spec's
#     original firmware revision. (Our own E4XT Ultra runs EOS 4.70 and
#     reported real config/memory data cleanly all session — plausible this
#     newer unit exposes the full 32, but that has NOT been confirmed by
#     reading FX_B_ALGORITHM's live device-reported max, which is the
#     authoritative check per this module's own docstring.)
#
# VERIFY BEFORE TRUSTING FOR ANYTHING BEYOND A CONVENIENCE UI LABEL: set
# FX_A_ALGORITHM/FX_B_ALGORITHM to a few of these ids live and compare
# against what the front panel actually displays.
FX_A_ALGORITHM_NAMES: Dict[int, str] = {
    0: "Room 1", 1: "Room 2", 2: "Room 3", 3: "Hall 1", 4: "Hall 2", 5: "Plate",
    6: "Delay", 7: "Panning Delay", 8: "Multitap 1",
    9: "Multitap Pan", 10: "3 Tap", 11: "3 Tap Pan",
    12: "Soft Room", 13: "Warm Room", 14: "Perfect Room",
    15: "Tiled Room", 16: "Hard Plate", 17: "Warm Hall",
    18: "Spacious Hall", 19: "Bright Hall", 20: "Bright Hall Pan",
    21: "Bright Plate", 22: "B-Ball Court", 23: "Gymnasium",
    24: "Cavern", 25: "Concert 9", 26: "Concert 10 Pan",
    27: "Reverse Gate", 28: "Gate 2", 29: "Gate Pan",
    30: "Concert 11", 31: "Medium Concert", 32: "Large Concert",
    33: "Large Concert Pan", 34: "Canyon",
    35: "DelayVerb 1", 36: "DelayVerb 2", 37: "DelayVerb 3",
    38: "DelayVerb 4 Pan", 39: "DelayVerb 5 Pan",
    40: "DelayVerb 6", 41: "DelayVerb 7", 42: "DelayVerb 8", 43: "DelayVerb 9",
}

FX_B_ALGORITHM_NAMES: Dict[int, str] = {
    0: "Chorus 1", 1: "Chorus 2", 2: "Chorus 3", 3: "Chorus 4", 4: "Chorus 5",
    5: "Doubling", 6: "Slapback",
    7: "Flange 1", 8: "Flange 2", 9: "Flange 3", 10: "Flange 4", 11: "Flange 5",
    12: "Flange 6", 13: "Flange 7", 14: "Big Chorus", 15: "Symphonic",
    16: "Ensemble", 17: "Delay", 18: "Delay Stereo 1", 19: "Delay Stereo 2",
    20: "Panning Delay", 21: "Delay Chorus",
    22: "Pan Delay Chorus 1", 23: "Pan Delay Chorus 2",
    24: "Dual Tap 1/3", 25: "Dual Tap 1/4", 26: "Vibrato",
    27: "Distortion 1", 28: "Distortion 2", 29: "Distortion Flange",
    30: "Distorted Chorus", 31: "Distorted Double",
}

# FX_*_PARM_0/1(/2) names: the manual states these plainly as fixed labels
# per processor (chapter 3, "Effect Descriptions": "Reverb effects have two
# adjustable parameters — Decay Time and High Frequency Damping"; chapter 2:
# "The 'B' effects have user programmable Feedback, LFO Rate and Delay
# Time"). PARM_2 is not named for FX A anywhere in the manual (left
# unmapped, not guessed). Caveat found while cross-checking: the "Delay" A
# effect's own dedicated description calls its two parameters "Delay Time"
# and "Feedback" instead — i.e. these labels are the general/typical case
# for each processor, not a guarantee that every one of the 44/32 algorithms
# uses them identically. Treat the displayed name as a strong hint, not a
# certainty, for delay-family and other non-reverb/non-chorus algorithms.
FX_A_PARM_NAMES: Dict[int, str] = {0: "Decay Time", 1: "HF Damping"}
FX_B_PARM_NAMES: Dict[int, str] = {0: "Feedback", 1: "LFO Rate", 2: "Delay Time"}

# FX_*_AMT_0-3: NOT algorithm-dependent — always the wet/dry send amount for
# one of the four submix busses (manual, chapter 3, "The Effects Sends":
# "There are 4 effects busses: Main, Sub 1, Sub 2, and Sub 3").
FX_AMT_BUS_NAMES: Dict[int, str] = {0: "Main", 1: "Sub 1", 2: "Sub 2", 3: "Sub 3"}

# --- filter type names (from the EOS 4.0 Software Manual) -------------------
# Source: chapter 8, "Filter Parameters" (pp. 342-345): "Filter Type: 21
# filter types are currently implemented", followed by a single-column,
# one-per-paragraph list in this exact order. Unlike the FX effect tables
# above, this list is NOT a multi-column table — there is no reading-order
# ambiguity — and the count matches the manual's own stated total exactly
# (21). The last three names ("2EQ + Lowpass Morph", "2EQ Morph +
# Expression", "Peak/Shelf Morph") independently cross-check against the
# filter-type-dependent parameter-overlay section headers already
# transcribed from the SysEx spec (docs/RESOLUTION_NOTES.md §2) — real
# corroboration, not just a repeated read of the same source.
#
# Still an assumption, not a hardware-confirmed fact: id == list position
# (0-based). Verify by setting E4_VOICE_FTYPE live and comparing to what the
# front panel shows, same as the FX algorithm tables above.
FILTER_TYPE_NAMES: Dict[int, str] = {
    0: "2-Pole Lowpass", 1: "4-Pole Lowpass", 2: "6-Pole Lowpass",
    3: "2nd Order Highpass", 4: "4th Order Highpass",
    5: "2nd Order Bandpass", 6: "4th Order Bandpass", 7: "Contrary Bandpass",
    8: "Swept EQ, 1-octave", 9: "Swept EQ, 2->1-octave", 10: "Swept EQ, 3->1-octave",
    11: "Phaser 1", 12: "Phaser 2", 13: "Bat Phaser", 14: "Flanger Lite",
    15: "Vocal Ah-Ay-Ee", 16: "Vocal Oo-Ah",
    17: "Dual EQ Morph", 18: "2EQ + Lowpass Morph", 19: "2EQ Morph + Expression",
    20: "Peak/Shelf Morph",
}

# Envelope segment ids (VENV/FENV/AENV) already carry a clean, short role
# label in their `notes` field (e.g. "Atk1 Rate", "Dcy2 Level") — shown as
# the value's bracketed name for the same reason FX_A_PARM_0 shows "(Decay
# Time)": the raw number is meaningless without knowing which segment/role
# it belongs to. Restricted to these three groups specifically (not every
# parameter's `notes`) because those also hold longer caveat sentences that
# would look like a bogus "value name" if shown the same way.
_ENVELOPE_GROUPS = ("voice.amp.env", "voice.filter.env", "voice.aux.env")


def _known_value_name(param: Parameter, value: int) -> Optional[str]:
    """Look up a human-readable name for one parameter's value, across every
    enum/name table this module defines. Returns None if this parameter (or
    this particular value) has no known name — callers should fall back to
    showing the raw number."""
    name = param.name
    if name.endswith("FX_A_ALGORITHM"):
        return FX_A_ALGORITHM_NAMES.get(value)
    if name.endswith("FX_B_ALGORITHM"):
        return FX_B_ALGORITHM_NAMES.get(value)
    if name.endswith(("FX_A_PARM_0", "FX_A_PARM_1")):
        return FX_A_PARM_NAMES.get(int(name[-1]))
    if name.endswith(("FX_B_PARM_0", "FX_B_PARM_1", "FX_B_PARM_2")):
        return FX_B_PARM_NAMES.get(int(name[-1]))
    if name.endswith(("FX_A_AMT_0", "FX_A_AMT_1", "FX_A_AMT_2", "FX_A_AMT_3",
                      "FX_B_AMT_0", "FX_B_AMT_1", "FX_B_AMT_2", "FX_B_AMT_3")):
        return FX_AMT_BUS_NAMES.get(int(name[-1]))
    if param.group == "voice.cords" and name.endswith("_SRC"):
        return CORD_SOURCES.get(value)
    if param.group == "voice.cords" and name.endswith("_DST"):
        return CORD_DESTINATIONS.get(value)
    if name == "E4_VOICE_SOLO":
        return VOICE_SOLO_MODES.get(value)
    if name == "E4_VOICE_ASSIGN_GROUP":
        return VOICE_ASSIGN_GROUPS.get(value)
    if name in ("E4_VOICE_LFO_SHAPE", "E4_VOICE_LFO2_SHAPE"):
        return LFO_SHAPES.get(value)
    if name == "E4_VOICE_SUBMIX":
        return SUBMIX_LABELS.get(value)
    if name == "MASTER_OUTPUT_FORMAT":
        return OUTPUT_FORMAT_LABELS.get(value)
    if name == "MASTER_OUTPUT_CLOCK":
        return OUTPUT_CLOCK_LABELS.get(value)
    if name == "MASTER_WORD_CLOCK_IN":
        return WORD_CLOCK_IN_LABELS.get(value)
    if name == "MIDIGLO_MIDI_MODE":
        return MIDI_MODE_LABELS.get(value)
    if name == "MIDIGLO_CTRL7_CURVE":
        return CTRL7_CURVE_LABELS.get(value)
    if name in ("MIDIGLO_PITCH_CONTROL", "MIDIGLO_MOD_CONTROL", "MIDIGLO_PRESSURE_CONTROL",
               "MIDIGLO_PEDAL_CONTROL", "MIDIGLO_SWITCH_1_CONTROL", "MIDIGLO_SWITCH_2_CONTROL",
               "MIDIGLO_THUMB_CONTROL", "MIDIGLO_MIDI_A_CONTROL", "MIDIGLO_MIDI_B_CONTROL",
               "MIDIGLO_MIDI_C_CONTROL", "MIDIGLO_MIDI_D_CONTROL", "MIDIGLO_MIDI_E_CONTROL",
               "MIDIGLO_MIDI_F_CONTROL", "MIDIGLO_MIDI_G_CONTROL", "MIDIGLO_MIDI_H_CONTROL"):
        return midi_control_display(value)
    if name == "E4_VOICE_FTYPE":
        return FILTER_TYPE_NAMES.get(value)
    if param.group in _ENVELOPE_GROUPS:
        return param.notes
    return None


def describe_value(param: Parameter, value: int) -> str:
    """"123" normally, or "123 (Name)" when a known mapping exists for this
    parameter's current value. See the FX_*_NAMES tables above for the
    manual-derived assumptions behind the FX ones specifically — treat those
    as a strong hint, not a certainty, until verified live."""
    name = _known_value_name(param, value)
    return str(value) if name is None else f"{value} ({name})"


# --- filter Hz/dB display conversions (closed-form; verified against the
#     spec's own C source) --------------------------------------------------

def fil_freq(value: int, maxfreq: int, mul: int) -> int:
    """Port of the spec's ``fil_freq(input, maxfreq, mul)``: input 0..255 ->
    a frequency in Hz, exponentially spaced down from ``maxfreq``."""
    f = maxfreq
    remaining = 255 - value
    while remaining > 0:
        f = f * mul // 1024
        remaining -= 1
    return f


def cnv_morph_freq(value: int) -> str:
    """Filter Table 5: ``cnv_morph_freq(2*input)`` per the spec, input 0..127."""
    return f"{fil_freq(value, 10000, 1006)}Hz"


def cnv_morph_gain(value: int) -> str:
    """Filter Table 4: input 0..127 -> "+d.dddB"/"-d.dddB", -24.0..+23.6dB."""
    gain10x = -240 + (value * 120) // 32
    gain_i = gain10x // 10
    gain_f = abs(gain10x % 10)
    sign = "+" if gain10x >= 0 else "-"
    return f"{sign}{abs(gain_i)}.{gain_f}dB"


def filter_table_1(value: int) -> str:
    """input 0..255 -> Hz, max 20000, mul 1002 (per spec's Filter Table 1)."""
    return f"{fil_freq(value, 20000, 1002)}Hz"


def filter_table_2(value: int) -> str:
    """input 0..255 -> Hz, max 18000, mul 1003 (per spec's Filter Table 2)."""
    return f"{fil_freq(value, 18000, 1003)}Hz"


def filter_table_3(value: int) -> str:
    """input 0..255 -> Hz, max 10000, mul 1006 (per spec's Filter Table 3)."""
    return f"{fil_freq(value, 10000, 1006)}Hz"


# --- glide rate display conversion (transcribed lookup tables) -------------
# Both tables have a clean, unambiguous 16-rows-of-8 layout in the source PDF
# (no page-wrap ambiguity), unlike the LFO rate tables below.

_GLIDE_UNITS1 = (
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 2, 2, 2, 2,
    2, 2, 2, 3, 3, 3, 3, 3,
    4, 4, 4, 4, 5, 5, 5, 5,
    6, 6, 7, 7, 7, 8, 8, 9,
    9, 10, 11, 11, 12, 13, 13, 14,
    15, 16, 17, 18, 19, 20, 22, 23,
    24, 26, 28, 30, 32, 34, 36, 38,
    41, 44, 47, 51, 55, 59, 64, 70,
    76, 83, 91, 100, 112, 125, 142, 163,
)

_GLIDE_UNITS2 = (
    0, 1, 2, 3, 4, 5, 6, 7,
    8, 9, 10, 11, 12, 13, 14, 15,
    16, 17, 18, 19, 20, 21, 22, 23,
    25, 26, 28, 29, 32, 34, 36, 38,
    41, 43, 46, 49, 52, 55, 58, 62,
    65, 70, 74, 79, 83, 88, 93, 98,
    4, 10, 17, 24, 31, 39, 47, 56,
    65, 74, 84, 95, 6, 18, 31, 44,
    59, 73, 89, 6, 23, 42, 62, 82,
    4, 28, 52, 78, 5, 34, 64, 97,
    32, 67, 6, 46, 90, 35, 83, 34,
    87, 45, 6, 70, 38, 11, 88, 70,
    56, 49, 48, 53, 65, 85, 13, 50,
    97, 54, 24, 6, 2, 15, 44, 93,
    64, 60, 84, 41, 34, 70, 56, 3,
    22, 28, 40, 87, 9, 65, 36, 69,
)

assert len(_GLIDE_UNITS1) == 128 and len(_GLIDE_UNITS2) == 128


def cnv_glide_rate(value: int) -> str:
    """``E4_VOICE_GLIDE_RATE`` (id 63) raw 0-127 -> "d.dddsec/oct" display string."""
    msec = (_GLIDE_UNITS1[value] * 1000 + _GLIDE_UNITS2[value] * 10) // 5
    return f"{msec // 1000}.{msec % 1000:03d}sec/oct"


# --- LFO rate display conversion: DELIBERATELY NOT IMPLEMENTED --------------
# The source PDF's lfounits1[]/lfounits2[] tables wrap across a page boundary
# in a way that could not be transcribed unambiguously (a recount produced
# 129 entries against an expected 128 = one extra/misplaced value from the
# page-break reflow). Rather than guess which entry to drop, this is left
# unimplemented — see docs/RESOLUTION_NOTES.md §2. The raw parameter value
# (E4_VOICE_LFO_RATE / LFO2_RATE, 0-127) is unaffected and fully usable for
# control; only the cosmetic "x.xx Hz"-style display string is missing.

def cnv_lfo_rate(value: int) -> str:
    raise NotImplementedError(
        "LFO rate display conversion not transcribed (ambiguous source table; "
        "see docs/RESOLUTION_NOTES.md §2). The raw value is still usable directly."
    )


# --- master tuning offset display conversion --------------------------------
# One value per magnitude 0..64 (clean one-per-line list in the source PDF);
# MASTER_TUNING_OFFSET's raw range is -64..+64, sign taken from the raw value.

_MASTER_TUNING_MAGNITUDE = (
    0.0, 1.2, 3.5, 4.7, 6.0, 7.2, 9.5, 10.7, 12.0, 14.2, 15.5, 17.7, 18.0, 20.2,
    21.5, 23.7, 25.0, 26.2, 28.5, 29.7, 31.0, 32.2, 34.5, 35.7, 37.0, 39.2, 40.5,
    42.7, 43.0, 45.2, 46.5, 48.7, 50.0, 51.2, 53.5, 54.7, 56.0, 57.2, 59.5, 60.7,
    62.0, 64.2, 65.5, 67.7, 68.0, 70.2, 71.5, 73.7, 75.0, 76.2, 78.5, 79.7, 81.0,
    82.2, 84.5, 85.7, 87.0, 89.2, 90.5, 92.7, 93.0, 95.2, 96.5, 98.7, 100.0,
)

assert len(_MASTER_TUNING_MAGNITUDE) == 65


def cnv_master_tuning(value: int) -> str:
    """``MASTER_TUNING_OFFSET`` (id 183) raw -64..+64 -> signed display string."""
    magnitude = _MASTER_TUNING_MAGNITUDE[abs(value)]
    sign = "-" if value < 0 else "+"
    return f"{sign}{magnitude}"


# --- chorus initial ITD display conversion ----------------------------------
# One value per magnitude 0..32 (clean, explicitly indexed list in the source
# PDF); E4_VOICE_CHORUS_X's raw range is -32..+32, sign taken from the raw value.

_CHORUS_ITD_MAGNITUDE_MS = (
    0.000, 0.045, 0.090, 0.136, 0.181, 0.226, 0.272, 0.317, 0.362, 0.408, 0.453,
    0.498, 0.544, 0.589, 0.634, 0.680, 0.725, 0.770, 0.816, 0.861, 0.907, 0.952,
    0.997, 1.043, 1.088, 1.133, 1.179, 1.224, 1.269, 1.315, 1.360, 1.405, 1.451,
)

assert len(_CHORUS_ITD_MAGNITUDE_MS) == 33


def cnv_chorus_itd(value: int) -> str:
    """``E4_VOICE_CHORUS_X`` (id 60) raw -32..+32 -> signed "d.dddms" display string."""
    magnitude = _CHORUS_ITD_MAGNITUDE_MS[abs(value)]
    sign = "-" if value < 0 else "+"
    return f"{sign}{magnitude}ms"
