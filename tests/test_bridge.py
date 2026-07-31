# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# These tests use fake MIDI ports — no hardware required.

import time

import pytest

from eos import bridge as bridge_mod
from eos import messages as m
from eos import params as p
from eos.bridge import EosBridge, MultiIn, ThrottledOut


# --- fake rtmidi (for port enumeration / autodetect / ThrottledOut tests) --

class FakeOut:
    def __init__(self):
        self.sent = []

    def send_message(self, message):
        self.sent.append(list(message))


class FakePort:
    """A fake rtmidi MidiIn/MidiOut sharing one port list, for construction tests."""

    PORTS = ["EOS Device", "USB MIDI 1", "USB MIDI 2", "My Synth"]

    def __init__(self, queue_size_limit=None):
        self.opened = None

    def get_ports(self):
        return list(self.PORTS)

    def open_port(self, index):
        self.opened = index

    def ignore_types(self, **kwargs):
        pass

    def send_message(self, message):
        pass

    def get_message(self):
        return None

    def close_port(self):
        pass

    def delete(self):
        pass


class FakeRtmidiModule:
    MidiOut = FakePort
    MidiIn = FakePort


def test_throttle_enforces_gap_for_sysex():
    out = ThrottledOut(FakeOut(), gap=0.05)
    start = time.time()
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x14, 0xF7])
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x14, 0xF7])
    assert time.time() - start >= 0.05


def test_write_gap_defaults_to_the_read_gap():
    """Omitting write_gap must reproduce the single-gap behaviour exactly."""
    out = ThrottledOut(FakeOut(), gap=0.05)
    start = time.time()
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x01, 0xF7], write=True)
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x01, 0xF7], write=True)
    assert time.time() - start >= 0.05


def test_write_gap_applies_after_a_write_not_after_a_read():
    """The gap is time owed *after* a send -- how long the device gets to
    digest what it was just handed -- so a write's larger gap must delay
    whatever follows it, while a read keeps the small one."""
    out = ThrottledOut(FakeOut(), gap=0.0, write_gap=0.20)

    start = time.time()                      # read then read: no write gap owed
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x02, 0xF7])
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x02, 0xF7])
    assert time.time() - start < 0.10

    start = time.time()                      # write then anything: write gap owed
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x01, 0xF7], write=True)
    out.send_message([0xF0, 0x18, 0x21, 0x00, 0x55, 0x02, 0xF7])
    assert time.time() - start >= 0.20


def test_bridge_flags_only_fire_and_forget_sends_as_writes():
    """Requests block for a reply, so the round trip paces them; writes have
    nothing to pace against and must be the ones marked."""
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PARAMETER_EDIT:
            return None                       # a write: no reply exists
        return m.ParameterEdit(values=[(1, 5)]).encode()

    bridge = _bridge_with(handler)
    device = bridge.midi_out

    bridge.get_parameter(1)
    assert device.writes[-1] is False, "a parameter request is not a write"

    bridge.set_parameter(1, 5)
    assert device.writes[-1] is True, "a parameter edit is a write"

    bridge.set_preset_name(3, "x")
    assert device.writes[-1] is True, "a rename is a write"

    bridge.delete_preset(3)
    assert device.writes[-1] is True, "a destructive utility is a write"


def test_non_sysex_is_not_throttled():
    out = ThrottledOut(FakeOut(), gap=1.0)
    start = time.time()
    out.send_message([0x90, 0x40, 0x7F])
    out.send_message([0x80, 0x40, 0x00])
    assert time.time() - start < 0.5


def test_list_ports_and_bidirectional(monkeypatch):
    monkeypatch.setattr(bridge_mod, "rtmidi", FakeRtmidiModule)
    ins, outs = bridge_mod.list_ports()
    assert ins == FakePort.PORTS
    assert outs == FakePort.PORTS
    assert bridge_mod.bidirectional_ports() == FakePort.PORTS  # same list on both sides


def test_standard_opens_matching_port(monkeypatch):
    monkeypatch.setattr(bridge_mod, "rtmidi", FakeRtmidiModule)
    bridge = EosBridge.standard("USB MIDI 1")
    assert bridge.description == "standard:USB MIDI 1"
    assert bridge.midi_out.opened == 1
    assert bridge.midi_in.opened == 1


def test_standard_rejects_unknown_port(monkeypatch):
    monkeypatch.setattr(bridge_mod, "rtmidi", FakeRtmidiModule)
    with pytest.raises(RuntimeError):
        EosBridge.standard("Nonexistent Port")


def test_multi_in_exact_vs_substring(monkeypatch):
    monkeypatch.setattr(bridge_mod, "rtmidi", FakeRtmidiModule)
    exact = MultiIn("USB MIDI 1", exact=True)
    assert len(exact.ports) == 1
    substring = MultiIn("usb midi")
    assert len(substring.ports) == 2  # "USB MIDI 1" and "USB MIDI 2"


def test_multi_in_raises_if_nothing_matches(monkeypatch):
    monkeypatch.setattr(bridge_mod, "rtmidi", FakeRtmidiModule)
    with pytest.raises(RuntimeError):
        MultiIn("nothing matches this")


# --- device inquiry autodetect ---------------------------------------------

class _AutodetectPort:
    """A fake in/out port for autodetect: MidiOut records what's sent; a
    scripted MidiIn on the 'answering' port replies with a Device Inquiry
    reply after a send."""

    PORTS = ["Silent Port", "EOS Answering Port"]
    ANSWERING_INDEX = 1

    _pending_reply = None  # class-level: set by MidiOut.send_message, drained by matching MidiIn

    def __init__(self, queue_size_limit=None):
        self.index = None

    def get_ports(self):
        return list(self.PORTS)

    def open_port(self, index):
        self.index = index

    def ignore_types(self, **kwargs):
        pass

    def send_message(self, message):
        if self.index == self.ANSWERING_INDEX:
            reply = bytes([0xF0, 0x7E, 0x00, 0x06, 0x02, 0x18, 0x01, 0x04, 0x04, 0x05,
                           ord('4'), ord('.'), ord('0'), ord('0'), 0xF7])
            _AutodetectPort._pending_reply = list(reply)

    def get_message(self):
        if self.index == self.ANSWERING_INDEX and _AutodetectPort._pending_reply is not None:
            reply = _AutodetectPort._pending_reply
            _AutodetectPort._pending_reply = None
            return (reply, 0.0)
        return None

    def close_port(self):
        pass

    def delete(self):
        pass


class _AutodetectRtmidi:
    MidiOut = _AutodetectPort
    MidiIn = _AutodetectPort


def test_autodetect_finds_answering_port(monkeypatch):
    # config_path=None: autodetect's port cache writes to the real filesystem
    # by default (see the dedicated cache tests below, which use tmp_path) —
    # every other test here must disable it, or a stray real config.toml
    # would be read, and a fake one would be written over any real one.
    _AutodetectPort._pending_reply = None
    monkeypatch.setattr(bridge_mod, "rtmidi", _AutodetectRtmidi)
    tried = []
    bridge = EosBridge.autodetect(timeout=0.5, on_try=tried.append, config_path=None)
    assert tried == ["Silent Port", "EOS Answering Port"]
    assert "EOS Answering Port" in bridge.description
    assert bridge.inquiry is not None
    assert bridge.inquiry.model == "E4XT"


class _NeverAnswersPort(FakePort):
    PORTS = ["Silent A", "Silent B"]


class _NeverAnswersRtmidi:
    MidiOut = _NeverAnswersPort
    MidiIn = _NeverAnswersPort


def test_autodetect_raises_when_nothing_answers(monkeypatch):
    monkeypatch.setattr(bridge_mod, "rtmidi", _NeverAnswersRtmidi)
    with pytest.raises(RuntimeError):
        EosBridge.autodetect(timeout=0.05, config_path=None)


# --- last-known-good port cache ---------------------------------------------

def test_load_last_ports_missing_file_returns_none(tmp_path):
    assert bridge_mod.load_last_ports(str(tmp_path / "does-not-exist.toml")) is None


def test_save_and_load_last_ports_roundtrip(tmp_path):
    path = str(tmp_path / "config.toml")
    bridge_mod.save_last_ports("Out Port", "In Port", path)
    assert bridge_mod.load_last_ports(path) == ("Out Port", "In Port")


def test_load_compact_view_missing_file_returns_none(tmp_path):
    assert bridge_mod.load_compact_view(str(tmp_path / "does-not-exist.toml")) is None


def test_save_and_load_compact_view_roundtrip(tmp_path):
    path = str(tmp_path / "config.toml")
    bridge_mod.save_compact_view(False, path)
    assert bridge_mod.load_compact_view(path) is False
    bridge_mod.save_compact_view(True, path)
    assert bridge_mod.load_compact_view(path) is True


def test_load_cache_all_on_startup_missing_file_returns_none(tmp_path):
    assert bridge_mod.load_cache_all_on_startup(str(tmp_path / "does-not-exist.toml")) is None


def test_load_cache_all_on_startup_reads_bool(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("cache_all_on_startup = true\n")
    assert bridge_mod.load_cache_all_on_startup(str(path)) is True
    path.write_text("cache_all_on_startup = false\n")
    assert bridge_mod.load_cache_all_on_startup(str(path)) is False


def test_load_cache_all_on_startup_invalid_type_returns_none(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('cache_all_on_startup = "yes"\n')  # must be a real bool, not a string
    assert bridge_mod.load_cache_all_on_startup(str(path)) is None


def test_load_cache_depth_missing_file_returns_none(tmp_path):
    assert bridge_mod.load_cache_depth(str(tmp_path / "does-not-exist.toml")) is None


def test_load_cache_depth_accepts_the_three_valid_levels_case_insensitively(tmp_path):
    path = tmp_path / "config.toml"
    for level in ("names", "structure", "full"):
        path.write_text(f'cache_depth = "{level}"\n')
        assert bridge_mod.load_cache_depth(str(path)) == level
    path.write_text('cache_depth = "FULL"\n')
    assert bridge_mod.load_cache_depth(str(path)) == "full"


def test_load_cache_depth_invalid_value_returns_none(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('cache_depth = "everything"\n')
    assert bridge_mod.load_cache_depth(str(path)) is None


def test_cache_all_settings_coexist_with_other_config_keys(tmp_path):
    # Regression guard, same as test_port_cache_and_view_preference_coexist_
    # in_the_same_file below: config.toml holds several independent settings
    # -- writing one must not clobber another.
    path = str(tmp_path / "config.toml")
    bridge_mod.save_compact_view(True, path)
    bridge_mod.save_last_ports("Out Port", "In Port", path)
    data = bridge_mod._read_config_dict(path)
    data["cache_all_on_startup"] = True
    data["cache_depth"] = "names"
    bridge_mod._write_config_dict(data, path)
    assert bridge_mod.load_compact_view(path) is True
    assert bridge_mod.load_last_ports(path) == ("Out Port", "In Port")
    assert bridge_mod.load_cache_all_on_startup(path) is True
    assert bridge_mod.load_cache_depth(path) == "names"


def test_load_send_pc_on_preset_select_missing_file_returns_none(tmp_path):
    assert bridge_mod.load_send_pc_on_preset_select(str(tmp_path / "does-not-exist.toml")) is None


def test_load_send_pc_on_preset_select_reads_bool(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("send_pc_on_preset_select = false\n")
    assert bridge_mod.load_send_pc_on_preset_select(str(path)) is False
    path.write_text("send_pc_on_preset_select = true\n")
    assert bridge_mod.load_send_pc_on_preset_select(str(path)) is True


def test_load_send_pc_on_preset_select_invalid_type_returns_none(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('send_pc_on_preset_select = "yes"\n')  # must be a real bool, not a string
    assert bridge_mod.load_send_pc_on_preset_select(str(path)) is None


def test_port_cache_and_view_preference_coexist_in_the_same_file(tmp_path):
    # Regression guard: config.toml holds more than one independent setting
    # now -- saving one must not clobber the other (read-modify-write, not a
    # blind overwrite).
    path = str(tmp_path / "config.toml")
    bridge_mod.save_last_ports("Out Port", "In Port", path)
    bridge_mod.save_compact_view(False, path)
    assert bridge_mod.load_last_ports(path) == ("Out Port", "In Port")
    assert bridge_mod.load_compact_view(path) is False


def test_load_last_ports_malformed_returns_none(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is not [valid toml")
    assert bridge_mod.load_last_ports(str(path)) is None


def test_load_last_ports_missing_keys_returns_none(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('rig = "standard"\n')  # no send_port/recv_port at all
    assert bridge_mod.load_last_ports(str(path)) is None


def test_autodetect_uses_cached_pair_first_and_skips_full_sweep(monkeypatch, tmp_path):
    _AutodetectPort._pending_reply = None
    monkeypatch.setattr(bridge_mod, "rtmidi", _AutodetectRtmidi)
    config_path = str(tmp_path / "config.toml")
    bridge_mod.save_last_ports("EOS Answering Port", "EOS Answering Port", config_path)

    tried = []
    bridge = EosBridge.autodetect(timeout=0.5, on_try=tried.append, config_path=config_path)
    assert tried == ["EOS Answering Port (cached)"]  # full sweep never ran
    assert bridge.inquiry.model == "E4XT"


def test_autodetect_falls_back_to_full_sweep_when_cache_is_stale(monkeypatch, tmp_path):
    _AutodetectPort._pending_reply = None
    monkeypatch.setattr(bridge_mod, "rtmidi", _AutodetectRtmidi)
    config_path = str(tmp_path / "config.toml")
    bridge_mod.save_last_ports("Nonexistent Port", "Nonexistent Port", config_path)

    tried = []
    bridge = EosBridge.autodetect(timeout=0.5, on_try=tried.append, config_path=config_path)
    assert tried == ["Nonexistent Port (cached)", "Silent Port", "EOS Answering Port"]
    assert bridge.inquiry.model == "E4XT"
    # the stale cache must have been overwritten with the pair that actually worked
    assert bridge_mod.load_last_ports(config_path) == ("EOS Answering Port", "EOS Answering Port")


def test_autodetect_saves_cache_on_first_success(monkeypatch, tmp_path):
    _AutodetectPort._pending_reply = None
    monkeypatch.setattr(bridge_mod, "rtmidi", _AutodetectRtmidi)
    config_path = str(tmp_path / "config.toml")
    assert bridge_mod.load_last_ports(config_path) is None  # nothing cached yet

    EosBridge.autodetect(timeout=0.5, config_path=config_path)
    assert bridge_mod.load_last_ports(config_path) == ("EOS Answering Port", "EOS Answering Port")


def test_autodetect_config_path_none_disables_caching(monkeypatch, tmp_path):
    _AutodetectPort._pending_reply = None
    monkeypatch.setattr(bridge_mod, "rtmidi", _AutodetectRtmidi)
    monkeypatch.chdir(tmp_path)  # would write to CWD's config.toml if caching were on
    EosBridge.autodetect(timeout=0.5, config_path=None)
    assert not (tmp_path / "config.toml").exists()


# --- high-level operations against a scripted fake device -----------------

class FakeDevice:
    """A minimal scripted EOS device. Pass the same instance as both
    midi_out and midi_in to an EosBridge: send_message() decodes what was
    sent and enqueues whatever handle() returns for the next get_message()."""

    def __init__(self, handler):
        self.handler = handler
        self.sent = []
        self.writes = []      # per-send: was it flagged as a fire-and-forget write?
        self.inbox = []

    def send_message(self, message, *, write: bool = False):
        frame = bytes(message)
        self.sent.append(frame)
        self.writes.append(write)
        reply = self.handler(frame)
        if reply is None:
            return
        if isinstance(reply, list):
            self.inbox.extend(reply)
        else:
            self.inbox.append(reply)

    def get_message(self):
        if self.inbox:
            return (list(self.inbox.pop(0)), 0.0)
        return None

    def close_port(self):
        pass


def _bridge_with(handler, **kwargs) -> EosBridge:
    device = FakeDevice(handler)
    bridge = EosBridge(device, device, "fake", timeout=kwargs.pop("timeout", 0.5), **kwargs)
    return bridge


def test_inquire():
    def handler(frame):
        return bytes([0xF0, 0x7E, 0x00, 0x06, 0x02, 0x18, 0x01, 0x04, 0x06, 0x05,
                     ord('3'), ord('.'), ord('0'), ord('0'), 0xF7])

    bridge = _bridge_with(handler)
    reply = bridge.inquire()
    assert reply.model == "E6400"
    assert bridge.inquiry is reply


def test_get_parameter():
    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(req.param_ids[0], 42)]).encode()

    bridge = _bridge_with(handler)
    assert bridge.get_parameter(1) == 42


@pytest.mark.parametrize("param_id, wire, expected", [
    # E4_PRESET_TRANSPOSE (id 0, range [-24, 24]) -- the exact pair confirmed
    # live against an E4XT Ultra rev 4.70 on 2026-07-31.
    (0, -12 & 0x3FFF, -12),
    (0, -24 & 0x3FFF, -24),
    (0, 24, 24),
    (0, 0, 0),
    # E4_PRESET_CTRL_A (id 2, range [-1, 127]): -1 is the "off" sentinel that
    # midi_control_display() renders, and read back as 16383 before this fix.
    (2, 0x3FFF, -1),
    (2, 64, 64),
    # E4_GEN_SAMPLE (id 38) is SIGNED (device minimum -8), so its two
    # undocumented sentinels sign-extend to -1 and -2 -- which is what the
    # voice/zone structure walk compares against (RESOLUTION_NOTES §11/§12,
    # §18a). Ordinary sample numbers are unaffected: they never set bit 13.
    (38, 0x3FFF, -1),       # multisample
    (38, 0x3FFE, -2),       # no such voice
    (38, 999, 999),
    (38, 0, 0),
])
def test_get_parameter_sign_extends_only_signed_params(param_id, wire, expected):
    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(req.param_ids[0], wire)]).encode()

    bridge = _bridge_with(handler)
    assert bridge.get_parameter(param_id) == expected


def test_get_parameter_passes_through_unknown_ids():
    # An id absent from eos.params' table has no signedness to consult; the
    # raw word is the only honest answer.
    unknown = 4000
    assert unknown not in p.PARAMETERS

    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(req.param_ids[0], 0x3FFF)]).encode()

    bridge = _bridge_with(handler)
    assert bridge.get_parameter(unknown) == 0x3FFF


def test_set_then_get_parameter_round_trips_signed_values():
    """The two halves of the bridge's parameter API agree: what set_parameter
    puts on the wire is what get_parameter gives back."""
    store = {}

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PARAMETER_EDIT:
            for pid, value in m.ParameterEdit.decode(frame).values:
                store[pid] = value
            return None
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(pid, store[pid]) for pid in req.param_ids]).encode()

    bridge = _bridge_with(handler)
    for value in (-24, -1, 0, 5, 24):
        bridge.set_parameter(0, value)
        assert bridge.get_parameter(0) == value


def test_get_parameter_missing_from_reply_raises():
    def handler(frame):
        return m.ParameterEdit(values=[(999, 1)]).encode()  # wrong id in reply

    bridge = _bridge_with(handler)
    with pytest.raises(ValueError):
        bridge.get_parameter(1)


def test_get_parameter_range():
    def handler(frame):
        return m.ParameterRange(param_id=57, minimum=0, maximum=127, default=64).encode()

    bridge = _bridge_with(handler)
    rng = bridge.get_parameter_range(57)
    assert (rng.minimum, rng.maximum, rng.default) == (0, 127, 64)


def test_get_parameter_range_sign_extends_signed_params():
    # id 0 = E4_PRESET_TRANSPOSE, [-24, 24]: the wire carries -24 as 16360.
    def handler(frame):
        return m.ParameterRange(param_id=0, minimum=-24, maximum=24, default=0).encode()

    bridge = _bridge_with(handler)
    rng = bridge.get_parameter_range(0)
    assert (rng.minimum, rng.maximum, rng.default) == (-24, 24, 0)


def test_get_parameter_range_leaves_large_unsigned_maxima_alone():
    """id 61 = E4_VOICE_DELAY, unsigned 0..10000. Its maximum has bit 13 set,
    so an unconditional sign-extension turned it into -6384 -- caught live
    against an E4XT Ultra rev 4.70 (RESOLUTION_NOTES §18)."""
    def handler(frame):
        return m.ParameterRange(param_id=61, minimum=0, maximum=10000, default=0).encode()

    bridge = _bridge_with(handler)
    rng = bridge.get_parameter_range(61)
    assert (rng.minimum, rng.maximum) == (0, 10000)


def test_parameter_range_and_value_agree_on_signedness():
    """The bug this pair of fixes closes: a range of [-24, 24] reported
    alongside a current value of 16372 for the same parameter."""
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PARAMETER_MINMAXDEFAULT_REQUEST:
            return m.ParameterRange(param_id=0, minimum=-24, maximum=24, default=0).encode()
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(req.param_ids[0], -12 & 0x3FFF)]).encode()

    bridge = _bridge_with(handler)
    rng = bridge.get_parameter_range(0)
    value = bridge.get_parameter(0)
    assert rng.minimum <= value <= rng.maximum
    assert value == -12


def test_set_parameter_is_fire_and_forget():
    sent = []

    def handler(frame):
        sent.append(frame)
        return None  # no reply, matching the spec (no ACK for Parameter Edit)

    bridge = _bridge_with(handler)
    bridge.set_parameter(1, -6 & 0x3FFF)
    assert len(sent) == 1
    edit = m.ParameterEdit.decode(sent[0])
    assert edit.values == [(1, -6 & 0x3FFF)]


def test_set_parameters_chunks_at_max_edits():
    sent = []

    def handler(frame):
        sent.append(frame)
        return None

    bridge = _bridge_with(handler)
    values = [(i, i) for i in range(m.MAX_PARAMETER_EDITS + 5)]
    bridge.set_parameters(values)
    assert len(sent) == 2  # one full chunk of 42, one chunk of 5
    first = m.ParameterEdit.decode(sent[0])
    assert len(first.values) == m.MAX_PARAMETER_EDITS


def test_get_and_set_preset_name():
    state = {"name": "Old Name"}

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_NAME_REQUEST:
            return m.PresetName(preset=5, name=state["name"]).encode()
        if command == m.Command.PRESET_NAME:
            state["name"] = m.PresetName.decode(frame).name
        return None

    bridge = _bridge_with(handler)
    assert bridge.get_preset_name(5) == "Old Name"
    bridge.set_preset_name(5, "New Name")
    assert bridge.get_preset_name(5) == "New Name"


def test_configuration_and_option_flags():
    def handler(frame):
        return m.ConfigurationResponse(options=0b00011, ram_mb=64).encode()

    bridge = _bridge_with(handler)
    cfg = bridge.configuration()
    flags = cfg.option_flags()
    assert cfg.ram_mb == 64
    assert flags.voices_128 and flags.fx_card
    assert not flags.midi_card


def test_memory_queries():
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_MEMORY_REQUEST:
            return m.PresetMemoryResponse(total_kb=8192, free_kb=1000).encode()
        if command == m.Command.SAMPLE_MEMORY_REQUEST:
            return m.SampleMemoryResponse(total_mb=32, free_10kb=500).encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.preset_memory().free_kb == 1000
    assert bridge.sample_memory().total_mb == 32


def test_preset_num_voices_returns_the_raw_unreliable_value():
    # Live-hardware finding (docs/RESOLUTION_NOTES.md §12): a "-1" correction
    # looked confirmed (two different bank states, cross-checked against
    # each preset's own dump file) until two more real presets (front-panel-
    # confirmed, audibly playing) directly contradicted it -- not a fixed
    # offset at all, the same failure mode as voice_num_szones.
    # eosed.app no longer uses this method's return value at all.
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_NUM_VOICES_REQUEST:
            return m.PresetNumVoicesResponse(num_voices=3).encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.preset_num_voices(0) == 3


def test_preset_num_links_is_a_plain_count_unlike_its_sibling():
    # Live-hardware finding (docs/RESOLUTION_NOTES.md §11): a first fix
    # assumed this sibling of preset_num_voices shared the same "+1" wire
    # offset (same command family, same wire shape) -- wrong. Confirmed
    # live against preset 0, whose own dump file
    # independently shows exactly 1 real link: the raw wire value was 1,
    # matching directly with no correction at all.
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_NUM_LINKS_REQUEST:
            return m.PresetNumLinksResponse(num_links=1).encode()  # 1 real link
        return None

    bridge = _bridge_with(handler)
    assert bridge.preset_num_links(0) == 1


def test_preset_num_szones_returns_the_raw_unverified_value():
    # Not called anywhere in this codebase and not independently tested at
    # all (docs/RESOLUTION_NOTES.md §11) -- given its two siblings above
    # disagree with each other, this deliberately applies no correction
    # rather than guessing one.
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_NUM_SZONES_REQUEST:
            return m.PresetNumSZonesResponse(num_szones=4).encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.preset_num_szones(0) == 4


def test_voice_num_szones_returns_the_raw_unreliable_value():
    # Deliberately NOT corrected (docs/RESOLUTION_NOTES.md §11): confirmed
    # live to disagree with the real zone count in a preset/voice-dependent
    # way with no consistent formula (one voice needed +1, another +3) --
    # eosed.app._voice_sample_info does not use this method at all.
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.VOICE_NUM_SZONES_REQUEST:
            return m.VoiceNumSZonesResponse(num_szones=1).encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.voice_num_szones(0, 1) == 1


def test_catalog_presets_skips_timeouts_and_cancels():
    names = {0: "Piano", 2: "Bass"}

    def handler(frame):
        req = m.PresetNameRequest.decode(frame)
        if req.preset in names:
            return m.PresetName(preset=req.preset, name=names[req.preset]).encode()
        if req.preset == 1:
            return m.Cancel().encode()  # explicit "doesn't exist"
        return None  # simulate silence -> caller sees a TimeoutError

    bridge = _bridge_with(handler, timeout=0.05)
    result = bridge.catalog_presets(range(0, 4))
    assert result == {0: "Piano", 2: "Bass"}


def test_catalog_presets_progress_callback():
    def handler(frame):
        return None

    bridge = _bridge_with(handler, timeout=0.02)
    seen = []
    bridge.catalog_presets(range(0, 3), on_progress=seen.append)
    assert seen == [0, 1, 2]


# --- bulk parameter fetch --------------------------------------------------

def test_get_parameters_single_chunk():
    # spec: response is one ParameterEdit-format frame *per parameter*, not
    # one combined frame -- so the fake device must reply once per request.
    # 183 (MASTER_TUNING_OFFSET) is signed, so it goes out on the wire as
    # two's complement and must come back sign-extended, not as 16379.
    on_the_wire = {1: 10, 6: 20, 183: -5 & 0x3FFF}

    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        return [m.ParameterEdit(values=[(pid, on_the_wire[pid])]).encode()
                for pid in req.param_ids]

    bridge = _bridge_with(handler)
    result = bridge.get_parameters([1, 6, 183])
    assert result == {1: 10, 6: 20, 183: -5}


def test_get_parameters_chunks_at_max_requests():
    ids = list(range(m.MAX_PARAMETER_REQUESTS + 5))
    requests_seen = []

    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        requests_seen.append(len(req.param_ids))
        return [m.ParameterEdit(values=[(pid, pid)]).encode() for pid in req.param_ids]

    bridge = _bridge_with(handler)
    result = bridge.get_parameters(ids)
    assert requests_seen == [m.MAX_PARAMETER_REQUESTS, 5]
    assert result == {pid: pid for pid in ids}


def test_get_parameters_ignores_unrequested_ids_in_reply():
    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        # device throws in an id we didn't ask for (shouldn't happen, but be robust)
        return m.ParameterEdit(values=[(req.param_ids[0], 42), (999, 1)]).encode()

    bridge = _bridge_with(handler)
    result = bridge.get_parameters([1])
    assert result == {1: 42}


# --- destructive utilities (fire-and-forget) --------------------------------

@pytest.mark.parametrize("method_name,expected_command", [
    ("erase_ram_bank", m.Command.ERASE_RAM_BANK),
    ("erase_all_ram_presets", m.Command.ERASE_ALL_RAM_PRESETS),
    ("erase_all_ram_samples", m.Command.ERASE_ALL_RAM_SAMPLES),
])
def test_destructive_no_arg_methods_send_expected_command(method_name, expected_command):
    def handler(frame):
        return None

    bridge = _bridge_with(handler)
    getattr(bridge, method_name)()
    assert len(bridge.midi_out.sent) == 1
    _, command, _ = m.parse_frame(bridge.midi_out.sent[0])
    assert command == expected_command
    assert m.is_destructive(command)


def test_delete_preset_sends_expected_command():
    def handler(frame):
        return None

    bridge = _bridge_with(handler)
    bridge.delete_preset(42)
    assert len(bridge.midi_out.sent) == 1
    decoded = m.PresetDelete.decode(bridge.midi_out.sent[0])
    assert decoded.preset == 42
    assert m.is_destructive(m.Command.PRESET_DELETE)


# --- dump engine: OLD format -------------------------------------------

def test_dump_preset_old_happy_path():
    name = b"Grand Piano     "
    payload = name + bytes(range(40))  # 56 bytes total, arbitrary "preset data"

    def handler(frame):
        _, command, fpayload = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            return [
                m.OldDumpHeader(byte_count=len(payload)).encode(),
                m.OldDumpMessage(packet_number=0, data=payload).encode(),
                m.EndOfFile().encode(),
            ]
        if command == m.Command.ACK:
            return None  # device doesn't need to respond to our ACK
        return None

    bridge = _bridge_with(handler)
    data = bridge.dump_preset_old(5)
    assert data == payload
    # bridge must ACK the header (packet 0, confirmed live — see
    # RESOLUTION_NOTES §7) as well as the one data packet.
    acks = [f for f in bridge.midi_out.sent if m.parse_frame(f)[1] == m.Command.ACK]
    assert len(acks) == 2
    assert m.Ack.decode(acks[0]).packet_number == 0  # the header


def test_dump_preset_old_raises_on_nonexistent_preset():
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            return m.Cancel().encode()
        return None

    bridge = _bridge_with(handler)
    with pytest.raises(bridge_mod.DeviceCancelled):
        bridge.dump_preset_old(999)


def _corrupt(frame: bytes) -> bytes:
    corrupted = bytearray(frame)
    corrupted[-2] ^= 0xFF
    corrupted[-2] &= 0x7F
    return bytes(corrupted)


def test_dump_preset_old_retries_on_checksum_failure():
    payload = bytes(range(20))
    good_data = m.OldDumpMessage(packet_number=0, data=payload).encode()

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            # queue the header *and* an initially-corrupt first data packet
            return [m.OldDumpHeader(byte_count=len(payload)).encode(), _corrupt(good_data)]
        if command == m.Command.NAK:
            return good_data  # resend correctly on retry
        return None

    device = FakeDevice(handler)
    bridge = EosBridge(device, device, "fake", timeout=0.5)
    data = bridge.dump_preset_old(5)
    assert data == payload
    naks = [f for f in device.sent if m.parse_frame(f)[1] == m.Command.NAK]
    assert len(naks) == 1
    acks = [f for f in device.sent if m.parse_frame(f)[1] == m.Command.ACK]
    assert len(acks) == 2  # the header ack, plus the eventually-good data packet


def test_dump_preset_old_gives_up_after_max_retries():
    payload = bytes(range(20))
    good_data = m.OldDumpMessage(packet_number=0, data=payload).encode()

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            return [m.OldDumpHeader(byte_count=len(payload)).encode(), _corrupt(good_data)]
        if command == m.Command.NAK:
            return _corrupt(good_data)  # always corrupt -> permanent failure
        return None

    device = FakeDevice(handler)
    bridge = EosBridge(device, device, "fake", timeout=0.5)
    with pytest.raises(bridge_mod.DumpChecksumError):
        bridge.dump_preset_old(5, max_retries=2)


# --- dump engine: NEW format ---------------------------------------------

def test_dump_preset_new_happy_path():
    payload = bytes(range(60))

    def handler(frame):
        _, command, fpayload = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP and fpayload and fpayload[0] == m.DumpSubCommand.NEW_DUMP_REQUEST:
            header = m.NewDumpHeader(preset=5, total_bytes=len(payload), num_global_params=22,
                                     num_link_params=0, num_voice_params=0, num_zone_params=0)
            return [
                header.encode(),
                m.NewDumpMessage(packet_number=1, data=payload).encode(),
                m.EndOfFile().encode(),
            ]
        return None

    bridge = _bridge_with(handler)
    header, data = bridge.dump_preset_new(5)
    assert data == payload
    assert header.total_bytes == len(payload)
    # header ack (extrapolated from the OLD-format finding, unconfirmed live
    # for NEW format — see RESOLUTION_NOTES §7) plus the one data packet.
    acks = [f for f in bridge.midi_out.sent if m.parse_frame(f)[1] == m.Command.NEW_DUMP_ACK]
    assert len(acks) == 2


def test_dump_preset_new_raises_on_nonexistent_preset():
    def handler(frame):
        _, command, fpayload = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP and fpayload and fpayload[0] == m.DumpSubCommand.NEW_DUMP_REQUEST:
            return m.Cancel().encode()
        return None

    bridge = _bridge_with(handler)
    with pytest.raises(bridge_mod.DeviceCancelled):
        bridge.dump_preset_new(999)


def test_close_does_not_raise():
    def handler(frame):
        return None

    bridge = _bridge_with(handler)
    bridge.close()  # should not raise even though FakeDevice has no delete()


def test_basic_channel_is_read_once_and_cached():
    # send_program_change fires on every preset selection; re-reading the
    # device-global MIDIGLO_BASIC_CHANNEL (id 198) each time cost a full
    # extra request/reply round trip per selection.
    reads = []

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PARAMETER_REQUEST:
            req = m.ParameterRequest.decode(frame)
            reads.append(req.param_ids)
            return m.ParameterEdit(values=[(req.param_ids[0], 3)]).encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.basic_channel() == 3
    assert bridge.basic_channel() == 3
    assert reads == [[198]]  # exactly one round trip, not two

    bridge.forget_basic_channel()
    assert bridge.basic_channel() == 3
    assert reads == [[198], [198]]


def test_send_program_change_uses_cached_channel_and_sends_bank_select():
    def handler(frame):
        if frame[0] != 0xF0:
            return None
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(req.param_ids[0], 2)]).encode()  # channel 2

    bridge = _bridge_with(handler)
    bridge.send_program_change(200)
    bridge.send_program_change(201)

    channel_messages = [f for f in bridge.midi_out.sent if f[0] != 0xF0]
    # 3 per call (Bank MSB, Bank LSB, Program Change), on the reported channel
    assert len(channel_messages) == 6
    assert channel_messages[0] == bytes([0xB0 | 2, 0, 0])     # MSB always 0 here
    assert channel_messages[1] == bytes([0xB0 | 2, 32, 1])    # 200 // 128 == 1
    assert channel_messages[2] == bytes([0xC0 | 2, 200 % 128])
    # Only the first call needed to ask the device for the basic channel.
    assert len([f for f in bridge.midi_out.sent if f[0] == 0xF0]) == 1


def test_send_program_change_rejects_out_of_range_channel():
    def handler(frame):
        req = m.ParameterRequest.decode(frame)
        return m.ParameterEdit(values=[(req.param_ids[0], 99)]).encode()  # nonsense channel

    bridge = _bridge_with(handler)
    with pytest.raises(ValueError):
        bridge.send_program_change(0)


def test_dump_preset_old_trims_padding_to_header_byte_count():
    # The spec says the last packet holds "256 Bytes, or LESS"; a device that
    # pads it to a full packet must not leak that padding into the result,
    # or every offset a caller computes into the tail shifts.
    payload = bytes(range(100))
    padded = payload + bytes(28)

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            return m.OldDumpHeader(byte_count=len(payload)).encode()
        if command == m.Command.ACK and m.Ack.decode(frame).packet_number == 0:
            return m.OldDumpMessage(packet_number=1, data=padded).encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.dump_preset_old(0) == payload


def test_dump_preset_old_handles_eof_in_response_to_a_nak():
    # A device may answer a NAK by ending the transfer rather than resending.
    # That used to hit OldDumpMessage.decode and raise a bare ValueError out
    # of a checksum retry, which reads like a codec bug.
    good = bytes(range(50))

    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            return m.OldDumpHeader(byte_count=200).encode()
        if command == m.Command.ACK:
            # a packet whose checksum does not match its data
            return m.OldDumpMessage(packet_number=1, data=good, checksum_byte=0x01).encode()
        if command == m.Command.NAK:
            return m.EndOfFile().encode()
        return None

    bridge = _bridge_with(handler)
    assert bridge.dump_preset_old(0) == b""  # ended cleanly, nothing accumulated


def test_dump_preset_old_raises_device_cancelled_when_nak_is_answered_with_cancel():
    def handler(frame):
        _, command, _ = m.parse_frame(frame)
        if command == m.Command.PRESET_DUMP_REQUEST:
            return m.OldDumpHeader(byte_count=200).encode()
        if command == m.Command.ACK:
            return m.OldDumpMessage(packet_number=1, data=bytes(10), checksum_byte=0x01).encode()
        if command == m.Command.NAK:
            return m.Cancel().encode()
        return None

    bridge = _bridge_with(handler)
    with pytest.raises(bridge_mod.DeviceCancelled):
        bridge.dump_preset_old(0)
