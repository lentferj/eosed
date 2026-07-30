# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.
# The SysEx frame layout, command bytes, parameter semantics, and checksum
# algorithm implemented here are transcribed as data from E-mu's own protocol
# specification:
#   "Remote Preset Editing via MIDI SysEx", Draft #30, EOS 4.00
#   Brian Clark, E-mu Systems, 17 February 1999
# No source code from that document is copied (it contains none — it is a
# protocol specification). See docs/RESOLUTION_NOTES.md §1 for where the
# source PDF lives and §3 for why this is NOT the front-panel mirror protocol.
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

"""SysEx frame codec for the EOS remote *editor* protocol.

Frame: ``F0 18 21 <devID> 55 <cmd> [...payload...] F7``

* ``18h`` — E-mu Systems manufacturer id.
* ``21h`` — the E4/EOS family's editor product id (``PRODUCT_ID_E4``).
* ``<devID>`` — SysEx device id, 0-126 unique, 127 = broadcast.
* ``55h`` — the "special editor designator" byte (``EDITOR_DESIGNATOR``).
* ``<cmd>`` — one byte, see :class:`Command`.

Device inquiry uses the *separate*, standard MIDI Non-Realtime Universal
SysEx (``F0 7E <devID> 06 01 F7``), not this frame — see
:func:`build_device_inquiry_request` / :func:`parse_device_inquiry_reply`.

This module intentionally implements only what the specification documents.
Where the spec is ambiguous or silent (e.g. the exact ACK/EOF ordering at the
end of a dump — see :mod:`eos.bridge`), that is called out explicitly rather
than guessed silently.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import ClassVar, Dict, List, Optional, Sequence, Tuple

# --- framing constants --------------------------------------------------

SOX = 0xF0
EOX = 0xF7
MANUFACTURER_ID = 0x18       # E-mu Systems
PRODUCT_ID_E4 = 0x21         # EOS / E4 family editor protocol
EDITOR_DESIGNATOR = 0x55     # "special editor designator" byte
IGNORE_CHECKSUM = 0x7F       # checksum byte value meaning "don't verify"

DEFAULT_DEVICE_ID = 0x00
BROADCAST_DEVICE_ID = 0x7F   # SysEx device id 127; distinct from the
                             # Universal SysEx sub-id also named 0x7F below

NAME_LENGTH = 16             # preset/sample names are always exactly 16 chars


class Command(enum.IntEnum):
    """The command byte, immediately after the ``55h`` editor-designator byte."""

    PARAMETER_EDIT = 0x01
    PARAMETER_REQUEST = 0x02
    PARAMETER_MINMAXDEFAULT_REQUEST = 0x03
    PARAMETER_MINMAXDEFAULT_RESPONSE = 0x04

    PRESET_NAME = 0x05
    PRESET_NAME_REQUEST = 0x06
    PRESET_NAME_CHAR_UPDATE = 0x07
    PRESET_NAME_CHAR_REQUEST = 0x08

    SAMPLE_NAME = 0x09
    SAMPLE_NAME_REQUEST = 0x0A
    SAMPLE_NAME_CHAR_UPDATE = 0x0B
    SAMPLE_NAME_CHAR_REQUEST = 0x0C

    PRESET_DUMP = 0x0D              # sub-commanded; see DumpSubCommand
    PRESET_DUMP_REQUEST = 0x0E      # OLD-format single-preset dump request

    PRESET_MEMORY_REQUEST = 0x10
    PRESET_MEMORY_RESPONSE = 0x11
    SAMPLE_MEMORY_REQUEST = 0x12
    SAMPLE_MEMORY_RESPONSE = 0x13
    CONFIGURATION_REQUEST = 0x14
    CONFIGURATION_RESPONSE = 0x15
    PRESET_NUM_VOICES_REQUEST = 0x16
    PRESET_NUM_VOICES_RESPONSE = 0x17
    PRESET_NUM_LINKS_REQUEST = 0x18
    PRESET_NUM_LINKS_RESPONSE = 0x19
    PRESET_NUM_SZONES_REQUEST = 0x1A
    PRESET_NUM_SZONES_RESPONSE = 0x1B
    VOICE_NUM_SZONES_REQUEST = 0x1C
    VOICE_NUM_SZONES_RESPONSE = 0x1D
    EXTENDED_CONFIGURATION_REQUEST = 0x1E
    EXTENDED_CONFIGURATION_RESPONSE = 0x1F

    NEW_VOICE = 0x20
    DELETE_VOICE = 0x21
    COPY_VOICE = 0x22

    NEW_SAMPLE_ZONE = 0x30
    GET_MULTISAMPLE = 0x31
    DELETE_SAMPLE_ZONE = 0x32
    COMBINE = 0x33
    EXPAND = 0x34

    NEW_LINK = 0x40
    DELETE_LINK = 0x41
    COPY_LINK = 0x42

    SAMPLE_ERASE = 0x50
    SAMPLE_MEMORY_DEFRAG = 0x52

    PRESET_COPY = 0x70
    PRESET_DELETE = 0x71
    MULTIMODE_MAP_DUMP = 0x72
    MULTIMODE_MAP_DUMP_REQUEST = 0x73
    ERASE_RAM_BANK = 0x74
    ERASE_ALL_RAM_PRESETS = 0x75
    ERASE_ALL_RAM_SAMPLES = 0x76

    NEW_DUMP_NAK = 0x79
    NEW_DUMP_ACK = 0x7A
    EOF = 0x7B
    WAIT = 0x7C
    CANCEL = 0x7D
    NAK = 0x7E              # "old" handshake, 1-byte packet numbers
    ACK = 0x7F              # "old" handshake, 1-byte packet numbers


class DumpSubCommand(enum.IntEnum):
    """Sub-command byte following ``Command.PRESET_DUMP`` (``0x0D``)."""

    OLD_DUMP_HEADER = 0x01
    OLD_DUMP_MESSAGE = 0x02
    NEW_DUMP_HEADER = 0x03
    NEW_DUMP_MESSAGE = 0x04
    NEW_DUMP_REQUEST = 0x05


# Destructive, one-shot, no-device-confirmation commands. Never key-bind these
# in a UI; only reachable through an explicit arm-then-fire flow (see
# DISCLAIMER.md and TODO.md).
DESTRUCTIVE_COMMANDS = frozenset({
    Command.PRESET_DELETE,
    Command.DELETE_VOICE,
    Command.DELETE_SAMPLE_ZONE,
    Command.DELETE_LINK,
    Command.ERASE_RAM_BANK,
    Command.ERASE_ALL_RAM_PRESETS,
    Command.ERASE_ALL_RAM_SAMPLES,
})


def is_destructive(command: int) -> bool:
    return command in DESTRUCTIVE_COMMANDS


# --- 14-bit / multi-byte codecs -----------------------------------------
# The spec's universal convention: any "N,N" or "N,N,N,N" field is N MIDI
# data bytes (each 0-127) holding a little-endian base-128 integer. Two-byte
# fields are by far the most common ("u14"/"s14" below); the OLD dump
# header's byte count is the one 4-byte field (up to 28 bits).

def encode_u14(value: int) -> Tuple[int, int]:
    """Encode an unsigned value (0..0x3FFF) as (lsb, msb), each a 7-bit byte."""
    if not 0 <= value <= 0x3FFF:
        raise ValueError(f"value {value} out of unsigned 14-bit range")
    return value & 0x7F, (value >> 7) & 0x7F


def decode_u14(lsb: int, msb: int) -> int:
    return (lsb & 0x7F) | ((msb & 0x7F) << 7)


def encode_s14(value: int) -> Tuple[int, int]:
    """Encode a signed value (-8192..8191) as (lsb, msb), two's complement in 14 bits."""
    if not -8192 <= value <= 8191:
        raise ValueError(f"value {value} out of signed 14-bit range")
    return encode_u14(value & 0x3FFF)


def decode_s14(lsb: int, msb: int) -> int:
    value = decode_u14(lsb, msb)
    if value & 0x2000:  # bit 13 set -> negative in 14-bit two's complement
        value -= 0x4000
    return value


def encode_lsb_bytes(value: int, n: int) -> List[int]:
    """Encode ``value`` as ``n`` 7-bit MIDI bytes, LSB first (base-128)."""
    if value < 0:
        raise ValueError("value must be non-negative")
    out = []
    remaining = value
    for _ in range(n):
        out.append(remaining & 0x7F)
        remaining >>= 7
    if remaining:
        raise ValueError(f"value {value} does not fit in {n} 7-bit bytes")
    return out


def decode_lsb_bytes(data: Sequence[int]) -> int:
    value = 0
    for i, byte in enumerate(data):
        value |= (byte & 0x7F) << (7 * i)
    return value


def checksum(data_bytes: Sequence[int]) -> int:
    """1's-complement of the sum of ``data_bytes``, masked to a 7-bit byte."""
    return (~sum(data_bytes)) & 0x7F


def _pad_name(name: str) -> List[int]:
    """16 ASCII bytes, space-padded/truncated — the wire format for names."""
    if not name.isascii():
        bad = next(ch for ch in name if not ch.isascii())
        raise ValueError(f"name contains non-ASCII character {bad!r}")
    raw = name.encode("ascii")[:NAME_LENGTH]
    return list(raw) + [0x20] * (NAME_LENGTH - len(raw))


def _unpad_name(raw: Sequence[int]) -> str:
    return bytes(b & 0x7F for b in raw).decode("ascii", errors="replace").rstrip()


# --- generic frame build/parse -------------------------------------------

def build_frame(command: int, payload: Sequence[int] = (), *,
                 device_id: int = DEFAULT_DEVICE_ID) -> bytes:
    if not 0 <= device_id <= 0x7F:
        raise ValueError(f"device id {device_id} out of range")
    return bytes([SOX, MANUFACTURER_ID, PRODUCT_ID_E4, device_id,
                  EDITOR_DESIGNATOR, int(command), *payload, EOX])


def parse_frame(data: Sequence[int]) -> Tuple[int, int, bytes]:
    """Validate and split an editor-protocol frame into (device_id, command, payload)."""
    if len(data) < 7 or data[0] != SOX or data[-1] != EOX:
        raise ValueError("not a SysEx frame")
    if data[1] != MANUFACTURER_ID or data[2] != PRODUCT_ID_E4 or data[4] != EDITOR_DESIGNATOR:
        raise ValueError("not an EOS editor-protocol frame")
    return data[3], data[5], bytes(data[6:-1])


def has_valid_header(data: Sequence[int]) -> bool:
    try:
        parse_frame(data)
        return True
    except (ValueError, IndexError):
        return False


# --- device inquiry (separate Universal Non-Realtime SysEx) -------------

FAMILY_CODE = (0x01, 0x04)  # fixed for the whole EOS/E4 line

FAMILY_MEMBERS: Dict[Tuple[int, int], str] = {
    (0x00, 0x05): "E4",
    (0x01, 0x05): "E64",
    (0x02, 0x05): "E4k",
    (0x03, 0x05): "E64FX",
    (0x04, 0x05): "E4XT",
    (0x05, 0x05): "E4X",
    (0x06, 0x05): "E6400",
    (0x07, 0x05): "E4XT Ultra",
    (0x08, 0x05): "E6400 Ultra",
}


def build_device_inquiry_request(device_id: int = BROADCAST_DEVICE_ID) -> bytes:
    return bytes([SOX, 0x7E, device_id, 0x06, 0x01, EOX])


@dataclass
class DeviceInquiryReply:
    device_id: int
    family_code: Tuple[int, int]
    member_code: Tuple[int, int]
    revision: str

    @property
    def model(self) -> Optional[str]:
        return FAMILY_MEMBERS.get(self.member_code)


def parse_device_inquiry_reply(data: Sequence[int]) -> DeviceInquiryReply:
    if (len(data) < 15 or data[0] != SOX or data[-1] != EOX or data[1] != 0x7E
            or data[3] != 0x06 or data[4] != 0x02):
        raise ValueError("not a Device Inquiry reply")
    if data[5] != MANUFACTURER_ID:
        raise ValueError(f"not an E-mu device inquiry reply (mfr id {data[5]:#x})")
    device_id = data[2]
    family = (data[6], data[7])
    member = (data[8], data[9])
    revision = "".join(chr(b) for b in data[10:14])
    return DeviceInquiryReply(device_id, family, member, revision)


# --- field-message helpers ------------------------------------------------
# Most commands are just a fixed sequence of unsigned fields (1 raw byte, a
# u14 pair, or a 4-byte lsb-first count) with no checksum. Rather than hand-
# write encode/decode for each of the ~25 such commands (and risk a
# copy-paste slip in one of them), field layout is declared once per class as
# FIELDS and a shared base does the packing/unpacking.

def _encode_fields(fields: Sequence[Tuple[str, int]], values: Dict[str, int]) -> List[int]:
    out: List[int] = []
    for name, width in fields:
        value = values[name]
        if width == 1:
            out.append(value & 0x7F)
        elif width == 2:
            out.extend(encode_u14(value))
        else:
            raise ValueError(f"unsupported field width {width}")
    return out


def _decode_fields(fields: Sequence[Tuple[str, int]], payload: Sequence[int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    i = 0
    for name, width in fields:
        if width == 1:
            out[name] = payload[i]
            i += 1
        elif width == 2:
            out[name] = decode_u14(payload[i], payload[i + 1])
            i += 2
        else:
            raise ValueError(f"unsupported field width {width}")
    return out


# These two are plain mixins, deliberately NOT decorated with @dataclass:
# dataclass field inheritance keeps an inherited field's ORIGINAL position
# even when a subclass re-declares it, so a base-class `device_id` field
# (which needs a default) would force every subclass field to also have a
# default (TypeError: "non-default argument follows default argument").
# Each concrete subclass below declares its own `device_id` field instead,
# always last, and gets `encode`/`decode` for free from the mixin.

class _FieldMessage:
    """Mixin for fixed-field, no-checksum editor messages.

    Subclasses set ``COMMAND`` and ``FIELDS = [(name, width), ...]`` (width 1
    = raw byte, width 2 = u14 pair), and are themselves ``@dataclass``es
    declaring one field per FIELDS entry plus a trailing
    ``device_id: int = DEFAULT_DEVICE_ID``.
    """

    COMMAND: ClassVar[int] = 0
    FIELDS: ClassVar[Sequence[Tuple[str, int]]] = ()

    def encode(self) -> bytes:
        values = {name: getattr(self, name) for name, _ in self.FIELDS}
        payload = _encode_fields(self.FIELDS, values)
        return build_frame(self.COMMAND, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]):
        device_id, command, payload = parse_frame(data)
        if command != cls.COMMAND:
            raise ValueError(f"{cls.__name__}: expected command {cls.COMMAND:#x}, got {command:#x}")
        values = _decode_fields(cls.FIELDS, payload)
        return cls(device_id=device_id, **values)


class _NoFieldMessage:
    """Mixin for commands that carry no payload at all.

    Subclasses set ``COMMAND`` and are themselves ``@dataclass``es declaring
    just ``device_id: int = DEFAULT_DEVICE_ID``.
    """

    COMMAND: ClassVar[int] = 0

    def encode(self) -> bytes:
        return build_frame(self.COMMAND, [], device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]):
        device_id, command, _ = parse_frame(data)
        if command != cls.COMMAND:
            raise ValueError(f"{cls.__name__}: expected command {cls.COMMAND:#x}, got {command:#x}")
        return cls(device_id=device_id)


# -- Parameter Edit / Request (0x01 / 0x02) — checksummed, variable length --

MAX_PARAMETER_EDITS = 42     # spec: "no more than 256 Data Bytes, or 42 edits"
MAX_PARAMETER_REQUESTS = 64  # spec: "no more than 256 Data Bytes, or 64 IDs"


@dataclass
class ParameterEdit:
    """Command 0x01 — write one or more (param_id, value) pairs.

    ``values`` holds already-packed 14-bit values (use :func:`encode_u14`-
    compatible ints, i.e. call ``value & 0x3FFF`` yourself for signed data —
    :mod:`eos.params` provides the per-parameter signed/unsigned convention).
    The device's response to a *request* (0x02) reuses this exact format, one
    message per parameter.
    """

    values: List[Tuple[int, int]]
    device_id: int = DEFAULT_DEVICE_ID
    # None (the default when constructing one to send) means "compute a fresh
    # checksum on encode()". A decoded instance holds the checksum byte that
    # was actually on the wire, so callers can call verify() before trusting
    # the data (e.g. before ACKing a dump packet).
    checksum_byte: Optional[int] = None

    def _data_bytes(self) -> List[int]:
        data: List[int] = []
        for param_id, value in self.values:
            data.extend(encode_u14(param_id))
            data.extend(encode_u14(value & 0x3FFF))
        return data

    def verify(self) -> bool:
        """True if no checksum was sent/received, or it matches the data."""
        if self.checksum_byte is None or self.checksum_byte == IGNORE_CHECKSUM:
            return True
        return self.checksum_byte == checksum(self._data_bytes())

    def encode(self) -> bytes:
        if not self.values:
            raise ValueError("ParameterEdit needs at least one (id, value) pair")
        if len(self.values) > MAX_PARAMETER_EDITS:
            raise ValueError(f"at most {MAX_PARAMETER_EDITS} parameter edits per message")
        data = self._data_bytes()
        byte_count = 2 * len(self.values)
        cksum = checksum(data) if self.checksum_byte is None else self.checksum_byte
        return build_frame(Command.PARAMETER_EDIT, [byte_count, *data, cksum],
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "ParameterEdit":
        device_id, command, payload = parse_frame(data)
        if command != Command.PARAMETER_EDIT:
            raise ValueError(f"not a PARAMETER_EDIT frame: {command:#x}")
        byte_count = payload[0]
        body = payload[1:1 + byte_count * 2]
        cksum = payload[1 + byte_count * 2]
        pairs = [
            (decode_u14(body[i], body[i + 1]), decode_u14(body[i + 2], body[i + 3]))
            for i in range(0, len(body), 4)
        ]
        return cls(values=pairs, device_id=device_id, checksum_byte=cksum)


@dataclass
class ParameterRequest:
    """Command 0x02 — request the current value of one or more parameters."""

    param_ids: List[int]
    device_id: int = DEFAULT_DEVICE_ID
    checksum_byte: Optional[int] = None  # see ParameterEdit.checksum_byte

    def _data_bytes(self) -> List[int]:
        data: List[int] = []
        for param_id in self.param_ids:
            data.extend(encode_u14(param_id))
        return data

    def verify(self) -> bool:
        if self.checksum_byte is None or self.checksum_byte == IGNORE_CHECKSUM:
            return True
        return self.checksum_byte == checksum(self._data_bytes())

    def encode(self) -> bytes:
        if not self.param_ids:
            raise ValueError("ParameterRequest needs at least one parameter id")
        if len(self.param_ids) > MAX_PARAMETER_REQUESTS:
            raise ValueError(f"at most {MAX_PARAMETER_REQUESTS} parameter ids per message")
        data = self._data_bytes()
        byte_count = len(self.param_ids)
        cksum = checksum(data) if self.checksum_byte is None else self.checksum_byte
        return build_frame(Command.PARAMETER_REQUEST, [byte_count, *data, cksum],
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "ParameterRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.PARAMETER_REQUEST:
            raise ValueError(f"not a PARAMETER_REQUEST frame: {command:#x}")
        byte_count = payload[0]
        body = payload[1:1 + byte_count * 2]
        cksum = payload[1 + byte_count * 2]
        ids = [decode_u14(body[i], body[i + 1]) for i in range(0, len(body), 2)]
        return cls(param_ids=ids, device_id=device_id, checksum_byte=cksum)


# -- Parameter min/max/default (0x03 / 0x04) — no checksum ------------------

@dataclass
class ParameterRangeRequest:
    param_id: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.PARAMETER_MINMAXDEFAULT_REQUEST,
                            encode_u14(self.param_id), device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "ParameterRangeRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.PARAMETER_MINMAXDEFAULT_REQUEST:
            raise ValueError(f"not a PARAMETER_MINMAXDEFAULT_REQUEST frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), device_id)


@dataclass
class ParameterRange:
    param_id: int
    minimum: int
    maximum: int
    default: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [*encode_u14(self.param_id), *encode_s14(self.minimum),
                   *encode_s14(self.maximum), *encode_s14(self.default)]
        return build_frame(Command.PARAMETER_MINMAXDEFAULT_RESPONSE, payload,
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "ParameterRange":
        device_id, command, payload = parse_frame(data)
        if command != Command.PARAMETER_MINMAXDEFAULT_RESPONSE:
            raise ValueError(f"not a PARAMETER_MINMAXDEFAULT_RESPONSE frame: {command:#x}")
        param_id = decode_u14(payload[0], payload[1])
        minimum = decode_s14(payload[2], payload[3])
        maximum = decode_s14(payload[4], payload[5])
        default = decode_s14(payload[6], payload[7])
        return cls(param_id, minimum, maximum, default, device_id)


# -- Preset / Sample naming (0x05-0x0C) — no checksum -----------------------

@dataclass
class PresetName:
    preset: int
    name: str
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [*encode_u14(self.preset), *_pad_name(self.name)]
        return build_frame(Command.PRESET_NAME, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "PresetName":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_NAME:
            raise ValueError(f"not a PRESET_NAME frame: {command:#x}")
        preset = decode_u14(payload[0], payload[1])
        name = _unpad_name(payload[2:2 + NAME_LENGTH])
        return cls(preset, name, device_id)


@dataclass
class PresetNameRequest:
    preset: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.PRESET_NAME_REQUEST, encode_u14(self.preset),
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "PresetNameRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_NAME_REQUEST:
            raise ValueError(f"not a PRESET_NAME_REQUEST frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), device_id)


@dataclass
class PresetNameCharUpdate:
    preset: int
    char_index: int  # 0-15
    char: str        # single ASCII character
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        if not 0 <= self.char_index <= NAME_LENGTH - 1:
            raise ValueError(f"char_index {self.char_index} out of 0-15 range")
        payload = [*encode_u14(self.preset), self.char_index, ord(self.char) & 0x7F]
        return build_frame(Command.PRESET_NAME_CHAR_UPDATE, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "PresetNameCharUpdate":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_NAME_CHAR_UPDATE:
            raise ValueError(f"not a PRESET_NAME_CHAR_UPDATE frame: {command:#x}")
        preset = decode_u14(payload[0], payload[1])
        return cls(preset, payload[2], chr(payload[3]), device_id)


@dataclass
class PresetNameCharRequest:
    preset: int
    char_index: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [*encode_u14(self.preset), self.char_index]
        return build_frame(Command.PRESET_NAME_CHAR_REQUEST, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "PresetNameCharRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_NAME_CHAR_REQUEST:
            raise ValueError(f"not a PRESET_NAME_CHAR_REQUEST frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), payload[2], device_id)


@dataclass
class SampleName:
    sample: int
    name: str
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [*encode_u14(self.sample), *_pad_name(self.name)]
        return build_frame(Command.SAMPLE_NAME, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "SampleName":
        device_id, command, payload = parse_frame(data)
        if command != Command.SAMPLE_NAME:
            raise ValueError(f"not a SAMPLE_NAME frame: {command:#x}")
        sample = decode_u14(payload[0], payload[1])
        name = _unpad_name(payload[2:2 + NAME_LENGTH])
        return cls(sample, name, device_id)


@dataclass
class SampleNameRequest:
    sample: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.SAMPLE_NAME_REQUEST, encode_u14(self.sample),
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "SampleNameRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.SAMPLE_NAME_REQUEST:
            raise ValueError(f"not a SAMPLE_NAME_REQUEST frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), device_id)


@dataclass
class SampleNameCharUpdate:
    sample: int
    char_index: int
    char: str
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        if not 0 <= self.char_index <= NAME_LENGTH - 1:
            raise ValueError(f"char_index {self.char_index} out of 0-15 range")
        payload = [*encode_u14(self.sample), self.char_index, ord(self.char) & 0x7F]
        return build_frame(Command.SAMPLE_NAME_CHAR_UPDATE, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "SampleNameCharUpdate":
        device_id, command, payload = parse_frame(data)
        if command != Command.SAMPLE_NAME_CHAR_UPDATE:
            raise ValueError(f"not a SAMPLE_NAME_CHAR_UPDATE frame: {command:#x}")
        sample = decode_u14(payload[0], payload[1])
        return cls(sample, payload[2], chr(payload[3]), device_id)


@dataclass
class SampleNameCharRequest:
    sample: int
    char_index: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [*encode_u14(self.sample), self.char_index]
        return build_frame(Command.SAMPLE_NAME_CHAR_REQUEST, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "SampleNameCharRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.SAMPLE_NAME_CHAR_REQUEST:
            raise ValueError(f"not a SAMPLE_NAME_CHAR_REQUEST frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), payload[2], device_id)


# -- Preset dump (0x0D sub-commanded, 0x0E) ---------------------------------

@dataclass
class PresetDumpRequest:
    """Command 0x0E — request the OLD-format dump of a preset by number.

    *If a non-existent preset is requested, the response is a CANCEL message*
    (per spec). Only one preset may be dumped to/from the device at a time.
    """

    preset: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.PRESET_DUMP_REQUEST, encode_u14(self.preset),
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "PresetDumpRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_DUMP_REQUEST:
            raise ValueError(f"not a PRESET_DUMP_REQUEST frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), device_id)


@dataclass
class OldDumpHeader:
    """0x0D/0x01 — OLD dump format header: total byte count only."""

    byte_count: int
    packet_number: int = 0  # spec: always 0 (the header is the first packet)
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [DumpSubCommand.OLD_DUMP_HEADER, self.packet_number,
                   *encode_lsb_bytes(self.byte_count, 4)]
        return build_frame(Command.PRESET_DUMP, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "OldDumpHeader":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_DUMP or payload[0] != DumpSubCommand.OLD_DUMP_HEADER:
            raise ValueError("not an OLD_DUMP_HEADER frame")
        return cls(decode_lsb_bytes(payload[2:6]), payload[1], device_id)


@dataclass
class OldDumpMessage:
    """0x0D/0x02 — OLD dump format data message: up to 256 bytes + checksum."""

    MAX_DATA: ClassVar[int] = 256

    packet_number: int  # low 7 bits of a running count
    data: bytes
    device_id: int = DEFAULT_DEVICE_ID
    checksum_byte: Optional[int] = None  # see ParameterEdit.checksum_byte

    def verify(self) -> bool:
        if self.checksum_byte is None or self.checksum_byte == IGNORE_CHECKSUM:
            return True
        return self.checksum_byte == checksum(self.data)

    def encode(self) -> bytes:
        if len(self.data) > self.MAX_DATA:
            raise ValueError(f"OLD dump message data exceeds {self.MAX_DATA} bytes")
        cksum = checksum(self.data) if self.checksum_byte is None else self.checksum_byte
        payload = [DumpSubCommand.OLD_DUMP_MESSAGE, self.packet_number & 0x7F,
                   *self.data, cksum]
        return build_frame(Command.PRESET_DUMP, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "OldDumpMessage":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_DUMP or payload[0] != DumpSubCommand.OLD_DUMP_MESSAGE:
            raise ValueError("not an OLD_DUMP_MESSAGE frame")
        packet_number = payload[1]
        body = bytes(payload[2:-1])
        cksum = payload[-1]
        return cls(packet_number, body, device_id, checksum_byte=cksum)


@dataclass
class NewDumpRequest:
    """0x0D/0x05 — request the NEW-format dump of a preset by number."""

    preset: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [DumpSubCommand.NEW_DUMP_REQUEST, *encode_u14(self.preset)]
        return build_frame(Command.PRESET_DUMP, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "NewDumpRequest":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_DUMP or payload[0] != DumpSubCommand.NEW_DUMP_REQUEST:
            raise ValueError("not a NEW_DUMP_REQUEST frame")
        return cls(decode_u14(payload[1], payload[2]), device_id)


@dataclass
class NewDumpHeader:
    """0x0D/0x03 — NEW dump format header: per-section parameter counts let
    the parser stay forward-compatible with EOS versions that add parameters.
    """

    preset: int
    total_bytes: int
    num_global_params: int
    num_link_params: int
    num_voice_params: int
    num_zone_params: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        payload = [
            DumpSubCommand.NEW_DUMP_HEADER,
            *encode_u14(self.preset),
            *encode_lsb_bytes(self.total_bytes, 4),
            *encode_u14(self.num_global_params),
            *encode_u14(self.num_link_params),
            *encode_u14(self.num_voice_params),
            *encode_u14(self.num_zone_params),
        ]
        return build_frame(Command.PRESET_DUMP, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "NewDumpHeader":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_DUMP or payload[0] != DumpSubCommand.NEW_DUMP_HEADER:
            raise ValueError("not a NEW_DUMP_HEADER frame")
        preset = decode_u14(payload[1], payload[2])
        total_bytes = decode_lsb_bytes(payload[3:7])
        num_global = decode_u14(payload[7], payload[8])
        num_link = decode_u14(payload[9], payload[10])
        num_voice = decode_u14(payload[11], payload[12])
        num_zone = decode_u14(payload[13], payload[14])
        return cls(preset, total_bytes, num_global, num_link, num_voice, num_zone, device_id)


@dataclass
class NewDumpMessage:
    """0x0D/0x04 — NEW dump format data message: up to 244 bytes + checksum,
    with a 2-byte (u14) running packet count starting at 1."""

    MAX_DATA: ClassVar[int] = 244

    packet_number: int
    data: bytes
    device_id: int = DEFAULT_DEVICE_ID
    checksum_byte: Optional[int] = None  # see ParameterEdit.checksum_byte

    def verify(self) -> bool:
        if self.checksum_byte is None or self.checksum_byte == IGNORE_CHECKSUM:
            return True
        return self.checksum_byte == checksum(self.data)

    def encode(self) -> bytes:
        if len(self.data) > self.MAX_DATA:
            raise ValueError(f"NEW dump message data exceeds {self.MAX_DATA} bytes")
        cksum = checksum(self.data) if self.checksum_byte is None else self.checksum_byte
        payload = [DumpSubCommand.NEW_DUMP_MESSAGE, *encode_u14(self.packet_number),
                   *self.data, cksum]
        return build_frame(Command.PRESET_DUMP, payload, device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "NewDumpMessage":
        device_id, command, payload = parse_frame(data)
        if command != Command.PRESET_DUMP or payload[0] != DumpSubCommand.NEW_DUMP_MESSAGE:
            raise ValueError("not a NEW_DUMP_MESSAGE frame")
        packet_number = decode_u14(payload[1], payload[2])
        body = bytes(payload[3:-1])
        cksum = payload[-1]
        return cls(packet_number, body, device_id, checksum_byte=cksum)


# -- Generic dump handshake (ACK/NAK/WAIT/CANCEL/EOF) ------------------------

@dataclass
class Ack:
    """Old-style ACK (0x7F) — 1-byte packet number."""

    packet_number: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.ACK, [self.packet_number & 0x7F], device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "Ack":
        device_id, command, payload = parse_frame(data)
        if command != Command.ACK:
            raise ValueError(f"not an ACK frame: {command:#x}")
        return cls(payload[0], device_id)


@dataclass
class Nak:
    """Old-style NAK (0x7E) — 1-byte packet number; resend that packet."""

    packet_number: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.NAK, [self.packet_number & 0x7F], device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "Nak":
        device_id, command, payload = parse_frame(data)
        if command != Command.NAK:
            raise ValueError(f"not a NAK frame: {command:#x}")
        return cls(payload[0], device_id)


@dataclass
class NewAck:
    """NEW-style ACK (0x7A) — 2-byte (u14) packet number."""

    packet_number: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.NEW_DUMP_ACK, encode_u14(self.packet_number),
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "NewAck":
        device_id, command, payload = parse_frame(data)
        if command != Command.NEW_DUMP_ACK:
            raise ValueError(f"not a NEW_DUMP_ACK frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), device_id)


@dataclass
class NewNak:
    """NEW-style NAK (0x79) — 2-byte (u14) packet number; resend that packet."""

    packet_number: int
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        return build_frame(Command.NEW_DUMP_NAK, encode_u14(self.packet_number),
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "NewNak":
        device_id, command, payload = parse_frame(data)
        if command != Command.NEW_DUMP_NAK:
            raise ValueError(f"not a NEW_DUMP_NAK frame: {command:#x}")
        return cls(decode_u14(payload[0], payload[1]), device_id)


@dataclass
class Wait(_NoFieldMessage):
    """0x7C — stop sending packets until an ACK is received."""

    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.WAIT


@dataclass
class Cancel(_NoFieldMessage):
    """0x7D — abort the dump."""

    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.CANCEL


@dataclass
class EndOfFile(_NoFieldMessage):
    """0x7B — no more packets follow; no response required. Must be sent
    at the end of a transfer (by whichever side is sending the dump)."""

    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.EOF


# -- Configuration / memory / count queries (0x10-0x1F) ---------------------

@dataclass
class PresetMemoryRequest(_NoFieldMessage):
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_MEMORY_REQUEST


@dataclass
class PresetMemoryResponse(_FieldMessage):
    total_kb: int
    free_kb: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_MEMORY_RESPONSE
    FIELDS = (("total_kb", 2), ("free_kb", 2))


@dataclass
class SampleMemoryRequest(_NoFieldMessage):
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.SAMPLE_MEMORY_REQUEST


@dataclass
class SampleMemoryResponse(_FieldMessage):
    total_mb: int
    free_10kb: int  # spec: "Total Sample Memory Free (in 10's of kBytes)"
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.SAMPLE_MEMORY_RESPONSE
    FIELDS = (("total_mb", 2), ("free_10kb", 2))


@dataclass
class ConfigurationRequest(_NoFieldMessage):
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.CONFIGURATION_REQUEST


@dataclass
class ConfigOptions:
    voices_128: bool
    fx_card: bool
    midi_card: bool
    octopus_card: bool
    digital_io: bool


def decode_config_options(byte: int) -> ConfigOptions:
    return ConfigOptions(
        voices_128=bool(byte & 0x01),
        fx_card=bool(byte & 0x02),
        midi_card=bool(byte & 0x04),
        octopus_card=bool(byte & 0x08),
        digital_io=bool(byte & 0x10),
    )


@dataclass
class ConfigurationResponse(_FieldMessage):
    options: int
    ram_mb: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.CONFIGURATION_RESPONSE
    FIELDS = (("options", 1), ("ram_mb", 2))

    def option_flags(self) -> ConfigOptions:
        return decode_config_options(self.options)


@dataclass
class PresetNumVoicesRequest(_FieldMessage):
    preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_NUM_VOICES_REQUEST
    FIELDS = (("preset", 2),)


@dataclass
class PresetNumVoicesResponse(_FieldMessage):
    num_voices: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_NUM_VOICES_RESPONSE
    FIELDS = (("num_voices", 2),)


@dataclass
class PresetNumLinksRequest(_FieldMessage):
    preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_NUM_LINKS_REQUEST
    FIELDS = (("preset", 2),)


@dataclass
class PresetNumLinksResponse(_FieldMessage):
    num_links: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_NUM_LINKS_RESPONSE
    FIELDS = (("num_links", 2),)


@dataclass
class PresetNumSZonesRequest(_FieldMessage):
    preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_NUM_SZONES_REQUEST
    FIELDS = (("preset", 2),)


@dataclass
class PresetNumSZonesResponse(_FieldMessage):
    num_szones: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_NUM_SZONES_RESPONSE
    FIELDS = (("num_szones", 2),)


@dataclass
class VoiceNumSZonesRequest(_FieldMessage):
    preset: int
    voice: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.VOICE_NUM_SZONES_REQUEST
    FIELDS = (("preset", 2), ("voice", 2))


@dataclass
class VoiceNumSZonesResponse(_FieldMessage):
    num_szones: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.VOICE_NUM_SZONES_RESPONSE
    FIELDS = (("num_szones", 2),)


@dataclass
class ExtendedConfigurationRequest(_NoFieldMessage):
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.EXTENDED_CONFIGURATION_REQUEST


@dataclass
class ExtendedConfigOptions:
    voices_128: bool
    fx_card: bool
    midi_card: bool
    octopus_card: bool
    digital_io: bool
    preset_flash: bool
    adat_io: bool


def decode_extended_config_options(byte: int) -> ExtendedConfigOptions:
    return ExtendedConfigOptions(
        voices_128=bool(byte & 0x01),
        fx_card=bool(byte & 0x02),
        midi_card=bool(byte & 0x04),
        octopus_card=bool(byte & 0x08),
        digital_io=bool(byte & 0x10),
        preset_flash=bool(byte & 0x20),
        adat_io=bool(byte & 0x40),
    )


def _decode_mb_byte(raw: int) -> int:
    """0-126 MB directly; 0x7F is defined by the spec to mean 128 MB."""
    return 128 if raw == 0x7F else raw


def _encode_mb_byte(mb: int) -> int:
    if mb == 128:
        return 0x7F
    if not 0 <= mb <= 126:
        raise ValueError(f"MB value {mb} out of encodable range (0-126 or 128)")
    return mb


@dataclass
class ExtendedConfigurationResponse:
    options1: int
    options2: int
    ram_mb: int
    rom_mb: int
    flash_mb: int
    device_id: int = DEFAULT_DEVICE_ID

    def option_flags(self) -> ExtendedConfigOptions:
        return decode_extended_config_options(self.options1)

    def encode(self) -> bytes:
        payload = [self.options1 & 0x7F, self.options2 & 0x7F,
                   *encode_u14(self.ram_mb),
                   _encode_mb_byte(self.rom_mb), _encode_mb_byte(self.flash_mb),
                   0, 0, 0, 0]  # 4 reserved bytes
        return build_frame(Command.EXTENDED_CONFIGURATION_RESPONSE, payload,
                            device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "ExtendedConfigurationResponse":
        device_id, command, payload = parse_frame(data)
        if command != Command.EXTENDED_CONFIGURATION_RESPONSE:
            raise ValueError(f"not an EXTENDED_CONFIGURATION_RESPONSE frame: {command:#x}")
        ram_mb = decode_u14(payload[2], payload[3])
        return cls(payload[0], payload[1], ram_mb,
                   _decode_mb_byte(payload[4]), _decode_mb_byte(payload[5]), device_id)


# -- Voice / SZone / Link utilities (0x20-0x42) ------------------------------

@dataclass
class NewVoice(_FieldMessage):
    preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.NEW_VOICE
    FIELDS = (("preset", 2),)


@dataclass
class DeleteVoice(_FieldMessage):
    preset: int
    voice: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.DELETE_VOICE
    FIELDS = (("preset", 2), ("voice", 2))


@dataclass
class CopyVoice(_FieldMessage):
    src_preset: int
    src_voice: int
    dst_preset: int
    group: int  # 0-31, single raw byte on the wire (unlike Combine's group)
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.COPY_VOICE
    FIELDS = (("src_preset", 2), ("src_voice", 2), ("dst_preset", 2), ("group", 1))


@dataclass
class NewSampleZone(_FieldMessage):
    preset: int
    voice: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.NEW_SAMPLE_ZONE
    FIELDS = (("preset", 2), ("voice", 2))


@dataclass
class GetMultisample(_FieldMessage):
    src_preset: int
    src_voice: int
    dst_preset: int
    dst_voice: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.GET_MULTISAMPLE
    FIELDS = (("src_preset", 2), ("src_voice", 2), ("dst_preset", 2), ("dst_voice", 2))


@dataclass
class DeleteSampleZone(_FieldMessage):
    preset: int
    voice: int
    sample_zone: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.DELETE_SAMPLE_ZONE
    FIELDS = (("preset", 2), ("voice", 2), ("sample_zone", 2))


@dataclass
class Combine(_FieldMessage):
    preset: int
    group: int  # 0-31, but sent as a u14 pair on the wire (unlike CopyVoice's group)
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.COMBINE
    FIELDS = (("preset", 2), ("group", 2))


@dataclass
class Expand(_FieldMessage):
    preset: int
    voice: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.EXPAND
    FIELDS = (("preset", 2), ("voice", 2))


@dataclass
class NewLink(_FieldMessage):
    preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.NEW_LINK
    FIELDS = (("preset", 2),)


@dataclass
class DeleteLink(_FieldMessage):
    preset: int
    link: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.DELETE_LINK
    FIELDS = (("preset", 2), ("link", 2))


@dataclass
class CopyLink(_FieldMessage):
    src_preset: int
    src_link: int
    dst_preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.COPY_LINK
    FIELDS = (("src_preset", 2), ("src_link", 2), ("dst_preset", 2))


# -- Sample utilities (0x50, 0x52) ------------------------------------------

@dataclass
class SampleErase(_FieldMessage):
    sample: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.SAMPLE_ERASE
    FIELDS = (("sample", 2),)


@dataclass
class SampleMemoryDefrag(_NoFieldMessage):
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.SAMPLE_MEMORY_DEFRAG


# -- Misc utilities (0x70-0x76) — several are one-shot destroyers -----------

@dataclass
class PresetCopy(_FieldMessage):
    """Destroys whatever preset already exists at ``dst`` (spec-stated)."""

    src: int
    dst: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_COPY
    FIELDS = (("src", 2), ("dst", 2))


@dataclass
class PresetDelete(_FieldMessage):
    """DESTRUCTIVE, one-shot, no device-side confirmation. See DESTRUCTIVE_COMMANDS."""

    preset: int
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.PRESET_DELETE
    FIELDS = (("preset", 2),)


@dataclass
class MultimodeMapDump:
    """0x72 — 8 bytes/channel (preset, volume, pan, submix), 16 or 32 channels."""

    raw: bytes
    device_id: int = DEFAULT_DEVICE_ID

    def encode(self) -> bytes:
        if len(self.raw) not in (128, 256):
            raise ValueError("multimode map must be 128 bytes (16ch) or 256 bytes (32ch)")
        return build_frame(Command.MULTIMODE_MAP_DUMP, list(self.raw), device_id=self.device_id)

    @classmethod
    def decode(cls, data: Sequence[int]) -> "MultimodeMapDump":
        device_id, command, payload = parse_frame(data)
        if command != Command.MULTIMODE_MAP_DUMP:
            raise ValueError(f"not a MULTIMODE_MAP_DUMP frame: {command:#x}")
        return cls(bytes(payload), device_id)

    def channels(self) -> List[Tuple[int, int, int, int]]:
        """Decode into per-channel (preset, volume, pan, submix) tuples."""
        out = []
        for i in range(0, len(self.raw), 8):
            preset = decode_u14(self.raw[i], self.raw[i + 1])
            volume = decode_u14(self.raw[i + 2], self.raw[i + 3])
            pan = decode_s14(self.raw[i + 4], self.raw[i + 5])
            submix = decode_s14(self.raw[i + 6], self.raw[i + 7])
            out.append((preset, volume, pan, submix))
        return out


@dataclass
class MultimodeMapDumpRequest(_NoFieldMessage):
    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.MULTIMODE_MAP_DUMP_REQUEST


@dataclass
class EraseRamBank(_NoFieldMessage):
    """DESTRUCTIVE, one-shot, no device-side confirmation. See DESTRUCTIVE_COMMANDS."""

    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.ERASE_RAM_BANK


@dataclass
class EraseAllRamPresets(_NoFieldMessage):
    """DESTRUCTIVE, one-shot, no device-side confirmation. See DESTRUCTIVE_COMMANDS."""

    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.ERASE_ALL_RAM_PRESETS


@dataclass
class EraseAllRamSamples(_NoFieldMessage):
    """DESTRUCTIVE, one-shot, no device-side confirmation. See DESTRUCTIVE_COMMANDS."""

    device_id: int = DEFAULT_DEVICE_ID
    COMMAND = Command.ERASE_ALL_RAM_SAMPLES
