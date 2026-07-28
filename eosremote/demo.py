# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
#
# This file is part of eosremote. Original work. GPL-2.0-or-later.

"""A canned, in-memory EOS device for ``--demo`` mode.

Per project convention (see CLAUDE.md's hardware rule, mirrored from
k2kremote): development and demonstration must be possible with **no MIDI
port ever opened**. :class:`DemoBridge` duck-types the subset of
:class:`eos.bridge.EosBridge`'s interface that :mod:`eosremote.cli` uses,
backed entirely by canned in-memory data.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from eos import messages as m
from eos import params as p

_DEMO_PRESET_NAMES: Dict[int, str] = {
    0: "Demo Grand Piano",
    1: "Demo Warm Pad",
    5: "Demo Bass",
}
_DEMO_SAMPLE_NAMES: Dict[int, str] = {
    0: "Demo Kick",
    1: "Demo Snare",
}
_DEMO_PARAM_VALUES: Dict[int, int] = {
    1: 0,      # E4_PRESET_VOLUME
    39: -6,    # E4_GEN_VOLUME
    183: 0,    # MASTER_TUNING_OFFSET
}

# eosremote.app walks voice indices directly (preset_num_voices/voice_num_
# szones cannot be trusted live -- see docs/RESOLUTION_NOTES.md §11/§12),
# stopping at the device's own 0x3FFE "no such voice" signal. Every demo
# preset has exactly one real voice (index 0); anything else must answer
# with that marker so the walk stops, or every demo preset would appear to
# have _MAX_VOICE_SCAN voices instead of 1.
_GEN_SAMPLE_ID = p.lookup("E4_GEN_SAMPLE").id
_VOICE_SELECT_ID = p.lookup("VOICE_SELECT").id
_NO_SUCH_VOICE_MARKER = 0x3FFE


def _name_bytes(name: str) -> bytes:
    return name.encode("ascii")[:m.NAME_LENGTH].ljust(m.NAME_LENGTH, b" ")


class DemoBridge:
    """No MIDI port is ever opened by this class."""

    def __init__(self) -> None:
        self.description = "demo (no hardware)"
        self.device_id = m.DEFAULT_DEVICE_ID
        self.inquiry = m.DeviceInquiryReply(
            device_id=0, family_code=m.FAMILY_CODE, member_code=(0x04, 0x05), revision="4.00")

    def inquire(self, *, timeout: Optional[float] = None) -> m.DeviceInquiryReply:
        return self.inquiry

    def configuration(self, *, timeout: Optional[float] = None) -> m.ConfigurationResponse:
        return m.ConfigurationResponse(options=0b00011, ram_mb=32, device_id=self.device_id)

    def extended_configuration(self, *,
                               timeout: Optional[float] = None) -> m.ExtendedConfigurationResponse:
        return m.ExtendedConfigurationResponse(
            options1=0b0011111, options2=0, ram_mb=32, rom_mb=16, flash_mb=0,
            device_id=self.device_id)

    def preset_memory(self, *, timeout: Optional[float] = None) -> m.PresetMemoryResponse:
        return m.PresetMemoryResponse(total_kb=8192, free_kb=6000, device_id=self.device_id)

    def sample_memory(self, *, timeout: Optional[float] = None) -> m.SampleMemoryResponse:
        return m.SampleMemoryResponse(total_mb=32, free_10kb=2000, device_id=self.device_id)

    def preset_num_voices(self, preset: int, *, timeout: Optional[float] = None) -> int:
        return 1 if preset in _DEMO_PRESET_NAMES else 0

    def preset_num_links(self, preset: int, *, timeout: Optional[float] = None) -> int:
        return 0

    def preset_num_szones(self, preset: int, *, timeout: Optional[float] = None) -> int:
        return 1 if preset in _DEMO_PRESET_NAMES else 0

    def voice_num_szones(self, preset: int, voice: int, *, timeout: Optional[float] = None) -> int:
        return 1

    def get_parameter(self, param_id: int, *, timeout: Optional[float] = None) -> int:
        if param_id == _GEN_SAMPLE_ID and _DEMO_PARAM_VALUES.get(_VOICE_SELECT_ID, 0) != 0:
            return _NO_SUCH_VOICE_MARKER
        return _DEMO_PARAM_VALUES.get(param_id, 0)

    def get_parameters(self, param_ids, *, timeout: Optional[float] = None) -> Dict[int, int]:
        return {pid: _DEMO_PARAM_VALUES.get(pid, 0) for pid in param_ids}

    def get_parameter_range(self, param_id: int, *,
                            timeout: Optional[float] = None) -> m.ParameterRange:
        param = p.PARAMETERS.get(param_id)
        if param is None:
            raise KeyError(f"no demo data for parameter {param_id}")
        default = param.default if param.default is not None else 0
        return m.ParameterRange(param_id, param.minimum, param.maximum, default, self.device_id)

    def set_parameter(self, param_id: int, value: int) -> None:
        _DEMO_PARAM_VALUES[param_id] = value

    def set_parameters(self, values) -> None:
        for param_id, value in values:
            self.set_parameter(param_id, value)

    # -- destructive utilities: real (in-memory) effect, no hardware risk --
    def delete_preset(self, preset: int) -> None:
        _DEMO_PRESET_NAMES.pop(preset, None)

    def erase_ram_bank(self) -> None:
        _DEMO_PRESET_NAMES.clear()

    def erase_all_ram_presets(self) -> None:
        _DEMO_PRESET_NAMES.clear()

    def erase_all_ram_samples(self) -> None:
        _DEMO_SAMPLE_NAMES.clear()

    def get_preset_name(self, preset: int, *, timeout: Optional[float] = None) -> str:
        if preset not in _DEMO_PRESET_NAMES:
            raise LookupError(f"demo has no preset {preset}")
        return _DEMO_PRESET_NAMES[preset]

    def set_preset_name(self, preset: int, name: str) -> None:
        _DEMO_PRESET_NAMES[preset] = name

    def get_sample_name(self, sample: int, *, timeout: Optional[float] = None) -> str:
        if sample not in _DEMO_SAMPLE_NAMES:
            raise LookupError(f"demo has no sample {sample}")
        return _DEMO_SAMPLE_NAMES[sample]

    def set_sample_name(self, sample: int, name: str) -> None:
        _DEMO_SAMPLE_NAMES[sample] = name

    def catalog_presets(self, preset_range=range(0, 128), *,
                       timeout: Optional[float] = None,
                       on_progress: Optional[Callable[[int], None]] = None) -> dict:
        result = {}
        for number in preset_range:
            if on_progress is not None:
                on_progress(number)
            if number in _DEMO_PRESET_NAMES:
                result[number] = _DEMO_PRESET_NAMES[number]
        return result

    def catalog_samples(self, sample_range=range(0, 128), *,
                        timeout: Optional[float] = None,
                        on_progress: Optional[Callable[[int], None]] = None) -> dict:
        result = {}
        for number in sample_range:
            if on_progress is not None:
                on_progress(number)
            if number in _DEMO_SAMPLE_NAMES:
                result[number] = _DEMO_SAMPLE_NAMES[number]
        return result

    def dump_preset_old(self, preset: int, *, timeout: Optional[float] = None,
                        max_retries: int = 3) -> bytes:
        if preset not in _DEMO_PRESET_NAMES:
            raise LookupError(f"demo has no preset {preset}")
        name = _name_bytes(_DEMO_PRESET_NAMES[preset])
        return bytes(name) + bytes(44)  # name + zeroed global parms; no links/voices in the demo

    def dump_preset_new(self, preset: int, *, timeout: Optional[float] = None, max_retries: int = 3):
        data = self.dump_preset_old(preset, timeout=timeout)
        header = m.NewDumpHeader(preset=preset, total_bytes=len(data), num_global_params=22,
                                 num_link_params=0, num_voice_params=0, num_zone_params=0,
                                 device_id=self.device_id)
        return header, data

    def send_program_change(self, preset: int, *, channel: Optional[int] = None) -> None:
        pass  # no MIDI is ever sent in demo mode -- see EosBridge.send_program_change

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"<DemoBridge {self.description!r}>"
