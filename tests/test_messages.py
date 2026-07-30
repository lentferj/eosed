# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# Synthetic only — no hardware/MIDI ports involved.

from dataclasses import replace

import pytest

from eos import messages as m


# --- framing ------------------------------------------------------------

def test_build_and_parse_frame_roundtrip():
    frame = m.build_frame(0x05, [1, 2, 3], device_id=7)
    assert frame[0] == 0xF0 and frame[-1] == 0xF7
    device_id, command, payload = m.parse_frame(frame)
    assert device_id == 7
    assert command == 0x05
    assert payload == bytes([1, 2, 3])


def test_parse_frame_rejects_non_sysex():
    with pytest.raises(ValueError):
        m.parse_frame([0x90, 0x40, 0x7F])


def test_parse_frame_rejects_wrong_manufacturer():
    bad = bytes([0xF0, 0x41, m.PRODUCT_ID_E4, 0, m.EDITOR_DESIGNATOR, 0x05, 0xF7])
    with pytest.raises(ValueError):
        m.parse_frame(bad)


def test_has_valid_header():
    good = m.build_frame(0x05, device_id=0)
    assert m.has_valid_header(good)
    assert not m.has_valid_header([0x90, 0x40, 0x7F])
    assert not m.has_valid_header([])


def test_build_frame_rejects_bad_device_id():
    with pytest.raises(ValueError):
        m.build_frame(0x05, device_id=128)


# --- 14-bit / multi-byte codecs ------------------------------------------

@pytest.mark.parametrize("value", [0, 1, 63, 8191, 8192, 16383])
def test_u14_roundtrip(value):
    assert m.decode_u14(*m.encode_u14(value)) == value


@pytest.mark.parametrize("value", [0, -1, 1, -8192, 8191, -64, 64])
def test_s14_roundtrip(value):
    assert m.decode_s14(*m.encode_s14(value)) == value


def test_u14_out_of_range():
    with pytest.raises(ValueError):
        m.encode_u14(-1)
    with pytest.raises(ValueError):
        m.encode_u14(0x4000)


def test_s14_out_of_range():
    with pytest.raises(ValueError):
        m.encode_s14(-8193)
    with pytest.raises(ValueError):
        m.encode_s14(8192)


@pytest.mark.parametrize("value,n", [(0, 4), (1772606, 4), (127, 1), (16383, 2)])
def test_lsb_bytes_roundtrip(value, n):
    assert m.decode_lsb_bytes(m.encode_lsb_bytes(value, n)) == value


def test_lsb_bytes_too_large_raises():
    with pytest.raises(ValueError):
        m.encode_lsb_bytes(128, 1)  # needs 8 bits, only 7 available in 1 byte


def test_checksum_is_a_7bit_byte():
    for data in ([], [0], [1, 2, 3], list(range(50))):
        assert 0 <= m.checksum(data) <= 0x7F


# --- name padding ----------------------------------------------------------

def test_pad_name_pads_and_truncates():
    # frame = [F0,18,21,dev,55,cmd] (6) + [preset_lsb,preset_msb] (2) + name (16) + [F7]
    assert m.PresetName(preset=0, name="Hi").encode()[8:8 + 16] == b"Hi" + b" " * 14
    long_name = "A" * 20
    frame = m.PresetName(preset=0, name=long_name).encode()
    assert frame[8:8 + 16] == b"A" * 16


def test_pad_name_rejects_non_ascii():
    with pytest.raises(ValueError):
        m.PresetName(preset=0, name="Café").encode()


def test_unpad_name_strips_trailing_spaces():
    raw = list(b"Hi" + b" " * 14)
    assert m._unpad_name(raw) == "Hi"


# --- device inquiry --------------------------------------------------------

def test_device_inquiry_request_bytes():
    req = m.build_device_inquiry_request(device_id=5)
    assert req == bytes([0xF0, 0x7E, 5, 0x06, 0x01, 0xF7])


def test_device_inquiry_reply_roundtrip():
    reply = bytes([0xF0, 0x7E, 0, 0x06, 0x02, 0x18, 0x01, 0x04, 0x04, 0x05,
                   ord('4'), ord('.'), ord('0'), ord('0'), 0xF7])
    parsed = m.parse_device_inquiry_reply(reply)
    assert parsed.device_id == 0
    assert parsed.family_code == (1, 4)
    assert parsed.member_code == (4, 5)
    assert parsed.model == "E4XT"
    assert parsed.revision == "4.00"


def test_device_inquiry_reply_unknown_member_code():
    reply = bytes([0xF0, 0x7E, 0, 0x06, 0x02, 0x18, 0x01, 0x04, 0x7F, 0x7F,
                   ord('9'), ord('.'), ord('9'), ord('9'), 0xF7])
    parsed = m.parse_device_inquiry_reply(reply)
    assert parsed.model is None


def test_device_inquiry_reply_rejects_wrong_manufacturer():
    reply = bytes([0xF0, 0x7E, 0, 0x06, 0x02, 0x41, 0x01, 0x04, 0x00, 0x05,
                   ord('1'), ord('.'), ord('0'), ord('0'), 0xF7])
    with pytest.raises(ValueError):
        m.parse_device_inquiry_reply(reply)


def test_device_inquiry_reply_rejects_malformed():
    with pytest.raises(ValueError):
        m.parse_device_inquiry_reply([0xF0, 0x7E, 0xF7])


# --- ParameterEdit / ParameterRequest: checksum semantics ------------------

def test_parameter_edit_checksum_verifies():
    frame = m.ParameterEdit(values=[(6, 20)]).encode()
    decoded = m.ParameterEdit.decode(frame)
    assert decoded.verify()
    assert decoded.values == [(6, 20)]


def test_parameter_edit_detects_corruption():
    frame = bytearray(m.ParameterEdit(values=[(6, 20)]).encode())
    frame[-2] ^= 0x7F  # corrupt the data byte just before the checksum
    frame[-2] &= 0x7F
    decoded = m.ParameterEdit.decode(bytes(frame))
    assert not decoded.verify()


def test_parameter_edit_ignore_checksum_flag():
    frame = m.ParameterEdit(values=[(6, 20)], checksum_byte=m.IGNORE_CHECKSUM).encode()
    decoded = m.ParameterEdit.decode(frame)
    assert decoded.checksum_byte == m.IGNORE_CHECKSUM
    assert decoded.verify()  # ignore flag always verifies


def test_parameter_edit_rejects_too_many_values():
    values = [(i, 0) for i in range(m.MAX_PARAMETER_EDITS + 1)]
    with pytest.raises(ValueError):
        m.ParameterEdit(values=values).encode()


def test_parameter_edit_rejects_empty():
    with pytest.raises(ValueError):
        m.ParameterEdit(values=[]).encode()


def test_parameter_request_rejects_too_many_ids():
    ids = list(range(m.MAX_PARAMETER_REQUESTS + 1))
    with pytest.raises(ValueError):
        m.ParameterRequest(param_ids=ids).encode()


def test_parameter_edit_multi_value_roundtrip():
    values = [(0, 5), (1, 0x1FFF), (255, 300)]
    frame = m.ParameterEdit(values=values).encode()
    decoded = m.ParameterEdit.decode(frame)
    assert decoded.values == values
    assert decoded.verify()


# --- dump message checksum verification ------------------------------------

def test_old_dump_message_verify_detects_corruption():
    frame = bytearray(m.OldDumpMessage(packet_number=0, data=bytes(range(10))).encode())
    frame[-2] ^= 0xFF
    frame[-2] &= 0x7F
    decoded = m.OldDumpMessage.decode(bytes(frame))
    assert not decoded.verify()


def test_new_dump_message_verify_detects_corruption():
    frame = bytearray(m.NewDumpMessage(packet_number=1, data=bytes(range(10))).encode())
    frame[-2] ^= 0xFF
    frame[-2] &= 0x7F
    decoded = m.NewDumpMessage.decode(bytes(frame))
    assert not decoded.verify()


def test_old_dump_message_max_data_enforced():
    with pytest.raises(ValueError):
        m.OldDumpMessage(packet_number=0, data=bytes(300)).encode()


def test_new_dump_message_max_data_enforced():
    with pytest.raises(ValueError):
        m.NewDumpMessage(packet_number=0, data=bytes(300)).encode()


# --- exhaustive round trip over every concrete message class ---------------

def _instances():
    return [
        m.ParameterEdit(values=[(6, 20)]),
        m.ParameterRequest(param_ids=[1, 2, 3]),
        m.ParameterRangeRequest(param_id=57),
        m.ParameterRange(param_id=1, minimum=-96, maximum=10, default=0),
        m.PresetName(preset=5, name="Grand Piano"),
        m.PresetNameRequest(preset=5),
        m.PresetNameCharUpdate(preset=5, char_index=0, char="G"),
        m.PresetNameCharRequest(preset=5, char_index=0),
        m.SampleName(sample=12, name="Kick 1"),
        m.SampleNameRequest(sample=12),
        m.SampleNameCharUpdate(sample=12, char_index=0, char="K"),
        m.SampleNameCharRequest(sample=12, char_index=0),
        m.PresetDumpRequest(preset=5),
        m.OldDumpHeader(byte_count=358),
        m.OldDumpMessage(packet_number=0, data=bytes(range(50))),
        m.NewDumpRequest(preset=5),
        m.NewDumpHeader(preset=5, total_bytes=1000, num_global_params=22,
                        num_link_params=29, num_voice_params=146, num_zone_params=13),
        m.NewDumpMessage(packet_number=1, data=bytes(range(100))),
        m.Ack(packet_number=3),
        m.Nak(packet_number=3),
        m.NewAck(packet_number=300),
        m.NewNak(packet_number=300),
        m.Wait(),
        m.Cancel(),
        m.EndOfFile(),
        m.PresetMemoryRequest(),
        m.PresetMemoryResponse(total_kb=8192, free_kb=4096),
        m.SampleMemoryRequest(),
        m.SampleMemoryResponse(total_mb=128, free_10kb=500),
        m.ConfigurationRequest(),
        m.ConfigurationResponse(options=0b10101, ram_mb=32),
        m.PresetNumVoicesRequest(preset=5),
        m.PresetNumVoicesResponse(num_voices=4),
        m.PresetNumLinksRequest(preset=5),
        m.PresetNumLinksResponse(num_links=2),
        m.PresetNumSZonesRequest(preset=5),
        m.PresetNumSZonesResponse(num_szones=1),
        m.VoiceNumSZonesRequest(preset=5, voice=0),
        m.VoiceNumSZonesResponse(num_szones=1),
        m.ExtendedConfigurationRequest(),
        m.ExtendedConfigurationResponse(options1=0x7F, options2=0, ram_mb=128, rom_mb=128, flash_mb=32),
        m.NewVoice(preset=5),
        m.DeleteVoice(preset=5, voice=0),
        m.CopyVoice(src_preset=5, src_voice=0, dst_preset=6, group=3),
        m.NewSampleZone(preset=5, voice=0),
        m.GetMultisample(src_preset=5, src_voice=0, dst_preset=6, dst_voice=1),
        m.DeleteSampleZone(preset=5, voice=0, sample_zone=1),
        m.Combine(preset=5, group=3),
        m.Expand(preset=5, voice=0),
        m.NewLink(preset=5),
        m.DeleteLink(preset=5, link=0),
        m.CopyLink(src_preset=5, src_link=0, dst_preset=6),
        m.SampleErase(sample=12),
        m.SampleMemoryDefrag(),
        m.PresetCopy(src=5, dst=6),
        m.PresetDelete(preset=5),
        m.MultimodeMapDump(raw=bytes((i % 100) for i in range(128))),
        m.MultimodeMapDumpRequest(),
        m.EraseRamBank(),
        m.EraseAllRamPresets(),
        m.EraseAllRamSamples(),
    ]


@pytest.mark.parametrize("instance", _instances(), ids=lambda obj: type(obj).__name__)
def test_message_roundtrip(instance):
    frame = instance.encode()
    assert frame[0] == 0xF0 and frame[-1] == 0xF7
    decoded = type(instance).decode(frame)
    if hasattr(instance, "checksum_byte") and instance.checksum_byte is None:
        # checksum_byte=None means "compute a fresh one on encode()"; decode()
        # always fills in whatever byte was actually on the wire, so compare
        # everything else and verify the computed checksum separately.
        assert decoded.verify()
        decoded_sans_checksum = replace(decoded, checksum_byte=None)
        assert decoded_sans_checksum == instance
    else:
        assert decoded == instance


def test_every_destructive_command_is_flagged():
    destructive_instances = [
        m.PresetDelete(preset=1), m.EraseRamBank(), m.EraseAllRamPresets(),
        m.EraseAllRamSamples(), m.DeleteVoice(preset=1, voice=0),
        m.DeleteSampleZone(preset=1, voice=0, sample_zone=0), m.DeleteLink(preset=1, link=0),
    ]
    for instance in destructive_instances:
        _, command, _ = m.parse_frame(instance.encode())
        assert m.is_destructive(command), f"{type(instance).__name__} should be flagged destructive"


def test_non_destructive_command_not_flagged():
    _, command, _ = m.parse_frame(m.PresetCopy(src=1, dst=2).encode())
    assert not m.is_destructive(command)


# --- multimode map channel decoding -----------------------------------------

def test_multimode_map_channels():
    dump = m.MultimodeMapDump(raw=bytes((i % 100) for i in range(128)))
    channels = dump.channels()
    assert len(channels) == 16  # 128 bytes / 8 bytes-per-channel
    preset, volume, pan, submix = channels[0]
    assert preset == m.decode_u14(0, 1)


def test_multimode_map_rejects_bad_length():
    with pytest.raises(ValueError):
        m.MultimodeMapDump(raw=bytes(100)).encode()


# --- MB-with-0x7F-means-128 encoding (Extended Configuration) --------------

@pytest.mark.parametrize("mb", [0, 1, 64, 126, 128])
def test_extended_config_mb_byte_roundtrip(mb):
    resp = m.ExtendedConfigurationResponse(options1=0, options2=0, ram_mb=32, rom_mb=mb, flash_mb=mb)
    decoded = m.ExtendedConfigurationResponse.decode(resp.encode())
    assert decoded.rom_mb == mb
    assert decoded.flash_mb == mb


def test_extended_config_mb_byte_rejects_127():
    with pytest.raises(ValueError):
        m.ExtendedConfigurationResponse(options1=0, options2=0, ram_mb=0, rom_mb=127, flash_mb=0).encode()


def test_config_options_decode():
    flags = m.decode_config_options(0b10101)
    assert flags.voices_128 is True
    assert flags.fx_card is False
    assert flags.midi_card is True
    assert flags.octopus_card is False
    assert flags.digital_io is True


def test_extended_config_options_decode():
    flags = m.decode_extended_config_options(0x7F)
    assert all([flags.voices_128, flags.fx_card, flags.midi_card, flags.octopus_card,
               flags.digital_io, flags.preset_flash, flags.adat_io])
