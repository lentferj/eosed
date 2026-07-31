# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Original work. GPL-2.0-or-later.

"""A canned, in-memory EOS device for ``--demo`` mode.

Per project convention (see CLAUDE.md's hardware rule, mirrored from
k2kremote): development and demonstration must be possible with **no MIDI
port ever opened**. :class:`DemoBridge` duck-types the subset of
:class:`eos.bridge.EosBridge`'s interface that :mod:`eosed.cli` uses,
backed entirely by canned in-memory data.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from eos import messages as m
from eos import params as p

# Starting state only — each DemoBridge copies these into its own instance
# attributes (see __init__). They are NEVER mutated: a DemoBridge models a
# device whose presets can be renamed, erased and edited, and when that state
# lived in these module-level dicts every instance in a process shared one
# device. A single `erase_all_ram_presets()` (or even a `set_parameter`) then
# leaked into every later DemoBridge — which is exactly why tests needed an
# autouse save/restore fixture to work at all. Two demo sessions in one
# process are now genuinely independent.
_DEFAULT_PRESET_NAMES: Dict[int, str] = {
    0: "Demo Grand Piano",
    1: "Demo Warm Pad",
    5: "Demo Bass",
}
_DEFAULT_SAMPLE_NAMES: Dict[int, str] = {
    0: "Demo Kick",
    1: "Demo Snare",
}
_DEFAULT_PARAM_VALUES: Dict[int, int] = {
    1: 0,      # E4_PRESET_VOLUME
    39: -6,    # E4_GEN_VOLUME
    183: 0,    # MASTER_TUNING_OFFSET
}

# eosed.app walks voice indices directly (preset_num_voices/voice_num_
# szones cannot be trusted live -- see docs/RESOLUTION_NOTES.md §11/§12),
# stopping at the device's own "no such voice" signal. Every demo preset has
# exactly one real voice (index 0); anything else must answer with that
# marker so the walk stops, or every demo preset would appear to have
# _MAX_VOICE_SCAN voices instead of 1.
#
# -2, not 3FFEh: E4_GEN_SAMPLE is signed and EosBridge sign-extends it, so a
# fake bridge has to answer in the same domain the real one now returns.
_GEN_SAMPLE_ID = p.lookup("E4_GEN_SAMPLE").id
_VOICE_SELECT_ID = p.lookup("VOICE_SELECT").id
_NO_SUCH_VOICE_MARKER = -2


def _name_bytes(name: str) -> bytes:
    return name.encode("ascii")[:m.NAME_LENGTH].ljust(m.NAME_LENGTH, b" ")


class DemoBridge:
    """No MIDI port is ever opened by this class."""

    def __init__(self) -> None:
        self.description = "demo (no hardware)"
        self.device_id = m.DEFAULT_DEVICE_ID
        self.inquiry = m.DeviceInquiryReply(
            device_id=0, family_code=m.FAMILY_CODE, member_code=(0x04, 0x05), revision="4.00")
        # This instance's own mutable "device" state — public, so tests can
        # assert against it directly instead of reaching into module globals.
        self.preset_names: Dict[int, str] = dict(_DEFAULT_PRESET_NAMES)
        self.sample_names: Dict[int, str] = dict(_DEFAULT_SAMPLE_NAMES)
        self.param_values: Dict[int, int] = dict(_DEFAULT_PARAM_VALUES)

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
        # Used RAM tracks the demo device's ACTUAL content (a handful of
        # one-voice presets), rather than the arbitrary 2192 KB this used to
        # report. Real banks measure ~0.5 KB of preset RAM per voice, and
        # eosed.app now reads this to estimate how long a cache-all sweep
        # will take -- so a demo claiming a big bank's worth of RAM while
        # holding three presets made the app predict ~95 minutes for a sweep
        # that finishes instantly.
        used_kb = max(1, len(self.preset_names))
        return m.PresetMemoryResponse(total_kb=8192, free_kb=8192 - used_kb,
                                      device_id=self.device_id)

    def sample_memory(self, *, timeout: Optional[float] = None) -> m.SampleMemoryResponse:
        return m.SampleMemoryResponse(total_mb=32, free_10kb=2000, device_id=self.device_id)

    def preset_num_voices(self, preset: int, *, timeout: Optional[float] = None) -> int:
        return 1 if preset in self.preset_names else 0

    def preset_num_links(self, preset: int, *, timeout: Optional[float] = None) -> int:
        return 0

    def preset_num_szones(self, preset: int, *, timeout: Optional[float] = None) -> int:
        return 1 if preset in self.preset_names else 0

    def voice_num_szones(self, preset: int, voice: int, *, timeout: Optional[float] = None) -> int:
        return 1

    def get_parameter(self, param_id: int, *, timeout: Optional[float] = None) -> int:
        if param_id == _GEN_SAMPLE_ID and self.param_values.get(_VOICE_SELECT_ID, 0) != 0:
            return _NO_SUCH_VOICE_MARKER
        return self.param_values.get(param_id, 0)

    def get_parameters(self, param_ids, *, timeout: Optional[float] = None) -> Dict[int, int]:
        return {pid: self.param_values.get(pid, 0) for pid in param_ids}

    def get_parameter_range(self, param_id: int, *,
                            timeout: Optional[float] = None) -> m.ParameterRange:
        param = p.PARAMETERS.get(param_id)
        if param is None:
            raise KeyError(f"no demo data for parameter {param_id}")
        default = param.default if param.default is not None else 0
        return m.ParameterRange(param_id, param.minimum, param.maximum, default, self.device_id)

    def set_parameter(self, param_id: int, value: int) -> None:
        self.param_values[param_id] = value

    def set_parameters(self, values) -> None:
        for param_id, value in values:
            self.set_parameter(param_id, value)

    # -- destructive utilities: real (in-memory) effect, no hardware risk --
    def delete_preset(self, preset: int) -> None:
        self.preset_names.pop(preset, None)

    def erase_ram_bank(self) -> None:
        self.preset_names.clear()

    def erase_all_ram_presets(self) -> None:
        self.preset_names.clear()

    def erase_all_ram_samples(self) -> None:
        self.sample_names.clear()

    def get_preset_name(self, preset: int, *, timeout: Optional[float] = None) -> str:
        if preset not in self.preset_names:
            raise LookupError(f"demo has no preset {preset}")
        return self.preset_names[preset]

    def set_preset_name(self, preset: int, name: str) -> None:
        self.preset_names[preset] = name

    def get_sample_name(self, sample: int, *, timeout: Optional[float] = None) -> str:
        if sample not in self.sample_names:
            raise LookupError(f"demo has no sample {sample}")
        return self.sample_names[sample]

    def set_sample_name(self, sample: int, name: str) -> None:
        self.sample_names[sample] = name

    def catalog_presets(self, preset_range=range(0, 128), *,
                       timeout: Optional[float] = None,
                       on_progress: Optional[Callable[[int], None]] = None) -> dict:
        result = {}
        for number in preset_range:
            if on_progress is not None:
                on_progress(number)
            if number in self.preset_names:
                result[number] = self.preset_names[number]
        return result

    def catalog_samples(self, sample_range=range(0, 128), *,
                        timeout: Optional[float] = None,
                        on_progress: Optional[Callable[[int], None]] = None) -> dict:
        result = {}
        for number in sample_range:
            if on_progress is not None:
                on_progress(number)
            if number in self.sample_names:
                result[number] = self.sample_names[number]
        return result

    def _dump_body(self, preset: int) -> bytes:
        """``<name 16><globals 44>`` — the part both dump formats share.

        No links or voices in the demo, so the globals are zeroed and the
        payload ends there.
        """
        if preset not in self.preset_names:
            raise LookupError(f"demo has no preset {preset}")
        return _name_bytes(self.preset_names[preset]) + bytes(44)

    # The two formats differ in whether the *payload* carries the preset
    # number, and the demo previously got this wrong in both directions by
    # having NEW reuse OLD's bytes verbatim:
    #   OLD — `<preset u14><name><globals>`, confirmed live against a real
    #     E4XT Ultra dump (docs/RESOLUTION_NOTES.md §7). The demo omitted the
    #     leading number entirely, so `eoscli dump --demo` produced a file
    #     shifted two bytes against every real capture.
    #   NEW — `<name><globals>` with the preset number carried in the *header*
    #     instead (spec, "NEW Dump Data Formats"). Reusing OLD's payload put
    #     the number in twice.
    def dump_preset_old(self, preset: int, *, timeout: Optional[float] = None,
                        max_retries: int = 3) -> bytes:
        return bytes(m.encode_u14(preset)) + self._dump_body(preset)

    def dump_preset_new(self, preset: int, *, timeout: Optional[float] = None, max_retries: int = 3):
        data = self._dump_body(preset)
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
