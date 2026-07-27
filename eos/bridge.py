# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosremote contributors
#
# This file is part of eosremote.
# The throttled-output queue, the MultiIn merged-input facade, and the
# rtmidi-backend-client leak fix are ported from the sibling k2kremote
# project's k2kremote/midi_bridge.py, which itself ports them from mpc2emu
# (tests/re_banks/krz_sysex_live.py):
#   Copyright (C) 2025-2026  mpc2emu contributors — GPL-2.0-or-later
#   Copyright (C) 2026  k2kremote contributors — GPL-2.0-or-later
# The autodetect strategy here differs from k2kremote's: EOS provides a
# standard, spec'd MIDI Device Inquiry (see eos.messages), so autodetect
# probes with that rather than a device-specific screen-request heuristic.
#
# eosremote is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# eosremote is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""MIDI transport and high-level operations for the EOS editor protocol.

Unlike k2kremote (which wraps the vendored ``psobot/k2000`` client library),
there is no existing EOS client to lean on, so :mod:`eos.messages` is the
whole protocol layer and this module only adds MIDI I/O and sequencing
around it.

**Throttle default is a conservative guess, not an RE'd value.** k2kremote's
120 ms SysEx-flood floor was reverse-engineered against real K2000 hardware
(see mpc2emu/docs/k2000r_midi_comms.md); no equivalent finding exists yet for
EOS/E4 hardware over this protocol (see docs/RESOLUTION_NOTES.md). ``SEND_GAP``
below is a small, conservative default pending live verification — do not
treat it as a confirmed safe value.

**Dump engine ACK/EOF ordering is inferred, not verified.** The spec states
the transfer "shall follow a method similar to the MIDI Sample Dump
Standard" without spelling out exactly who sends EOF and when. This module
assumes: the requester (us) ACKs each data packet as it arrives, and the
device (as sender of the dump) sends EOF once done. See
docs/RESOLUTION_NOTES.md before relying on this against real hardware.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

import rtmidi  # noqa: E402

from eos import messages as m

# --- defaults ----------------------------------------------------------
SEND_GAP = 0.05            # conservative; NOT reverse-engineered for EOS (see module docstring)
DEFAULT_TIMEOUT = 2.0
AUTODETECT_TIMEOUT = 1.0
DEFAULT_DEVICE_ID = m.DEFAULT_DEVICE_ID
DEFAULT_CONFIG_PATH = "config.toml"  # CWD-relative, matching k2kremote's BridgeConfig convention


# --- last-known-good port cache ---------------------------------------------
# A full autodetect sweep tries every output port (up to ~1s each while a
# port doesn't answer) — on a host with two dozen MIDI ports that's tens of
# seconds. Once a send/receive pair has answered, remember it and try it
# first on the next connection, before falling back to the full sweep (which
# still runs if the cached ports are gone or don't answer, e.g. after
# replugging an interface).

def load_last_ports(path: str = DEFAULT_CONFIG_PATH) -> Optional[Tuple[str, str]]:
    import os
    import tomllib

    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return None
    send_port = data.get("send_port")
    recv_port = data.get("recv_port")
    if isinstance(send_port, str) and isinstance(recv_port, str):
        return send_port, recv_port
    return None


def save_last_ports(send_port: str, recv_port: str, path: str = DEFAULT_CONFIG_PATH) -> None:
    lines = [
        "# eosremote MIDI port cache — last successful autodetect result.",
        "# Tried first on the next connection before falling back to a full scan.",
        f'send_port = "{send_port}"',
        f'recv_port = "{recv_port}"',
    ]
    try:
        with open(path, "w") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass  # the cache is a convenience, not required for correctness


def _try_port_pair(send_name: str, recv_name: str, timeout: float) -> Optional[bytes]:
    """Probe exactly one send/receive port pair for an E-mu Device Inquiry
    reply. Returns the raw reply bytes, or None if either port no longer
    exists or nothing valid replies within ``timeout``."""
    request = m.build_device_inquiry_request(device_id=m.BROADCAST_DEVICE_ID)

    out = None
    listener = None
    try:
        out = rtmidi.MidiOut()
        out_names = out.get_ports()
        if send_name not in out_names:
            return None
        out.open_port(out_names.index(send_name))

        in_names = _enum_in()
        if recv_name not in in_names:
            return None
        listener = rtmidi.MidiIn(queue_size_limit=8192)
        listener.open_port(in_names.index(recv_name))
        listener.ignore_types(sysex=False)
        while listener.get_message() is not None:  # flush stale input
            pass

        out.send_message(list(request))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = listener.get_message()
            if message is not None:
                data = message[0]
                if (len(data) >= 15 and data[0] == 0xF0 and data[1] == 0x7E
                        and data[3] == 0x06 and data[4] == 0x02
                        and data[5] == m.MANUFACTURER_ID):
                    return bytes(data)
            time.sleep(0.005)
        return None
    except Exception:
        return None
    finally:
        if out is not None:
            out.close_port()
            _delete_quiet(out)
        if listener is not None:
            listener.close_port()
            _delete_quiet(listener)


# --- leak-free rtmidi port helpers (ported from k2kremote/midi_bridge.py) --
# python-rtmidi's close_port() does not tear down the backend ALSA sequencer
# client; only delete() does. Every transient MidiIn/MidiOut (even one built
# only to call get_ports()) would otherwise orphan a client until process
# exit — on a host with many MIDI ports, a single autodetect scan could
# exhaust the ALSA sequencer's client slots.

def _delete_quiet(port) -> None:
    try:
        port.delete()
    except Exception:
        pass


def _enum_in() -> List[str]:
    probe = rtmidi.MidiIn()
    try:
        return probe.get_ports()
    finally:
        _delete_quiet(probe)


def _enum_out() -> List[str]:
    probe = rtmidi.MidiOut()
    try:
        return probe.get_ports()
    finally:
        _delete_quiet(probe)


def list_ports() -> Tuple[List[str], List[str]]:
    """Return ``(input_port_names, output_port_names)`` available on this host."""
    return _enum_in(), _enum_out()


def bidirectional_ports() -> List[str]:
    """Names present as both an input and an output (candidate standard ports)."""
    ins, outs = list_ports()
    in_set = set(ins)
    return [name for name in outs if name in in_set]


def _open_out(port_name: str) -> rtmidi.MidiOut:
    out = rtmidi.MidiOut()
    names = out.get_ports()
    if port_name not in names:
        raise RuntimeError(f"no output port named {port_name!r}; have {names}")
    out.open_port(names.index(port_name))
    return out


def _open_in(port_name: str) -> rtmidi.MidiIn:
    in_port = rtmidi.MidiIn(queue_size_limit=8192)
    names = in_port.get_ports()
    if port_name not in names:
        raise RuntimeError(f"no input port named {port_name!r}; have {names}")
    in_port.open_port(names.index(port_name))
    in_port.ignore_types(sysex=False)
    return in_port


class ThrottledOut:
    """Wrap an ``rtmidi.MidiOut`` so SysEx never floods the device.

    Only ``0xF0``-leading messages are gapped; ordinary MIDI (which this
    protocol never sends, but a caller might for other reasons) passes
    straight through.
    """

    def __init__(self, port: rtmidi.MidiOut, gap: float = SEND_GAP):
        self._port = port
        self._gap = gap
        self._last = 0.0

    def send_message(self, message) -> None:
        is_sysex = len(message) > 0 and message[0] == 0xF0
        if not is_sysex:
            self._port.send_message(message)
            return
        wait = self._gap - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._port.send_message(message)
        self._last = time.time()

    def __getattr__(self, name):
        return getattr(self._port, name)


class MultiIn:
    """An ``rtmidi.MidiIn``-compatible facade polling one or more ports, merged.

    With ``exact=False`` every input whose name *contains* ``name`` is opened
    and polled in turn; with ``exact=True`` (used after autodetect, where the
    cabling is fixed) only the single input whose name *equals* ``name`` is
    opened.
    """

    def __init__(self, name: str, *, exact: bool = False):
        self.ports: List[rtmidi.MidiIn] = []
        for index, port_name in enumerate(_enum_in()):
            matches = (port_name == name) if exact else (name.lower() in port_name.lower())
            if matches:
                port = rtmidi.MidiIn(queue_size_limit=8192)
                port.open_port(index)
                port.ignore_types(sysex=False)
                self.ports.append(port)
        if not self.ports:
            raise RuntimeError(f"no input port matching {name!r}")

    def get_message(self):
        for port in self.ports:
            message = port.get_message()
            if message is not None:
                return message
        return None

    def get_ports(self) -> List[str]:
        return _enum_in()

    def close_port(self) -> None:
        for port in self.ports:
            port.close_port()
            _delete_quiet(port)
        self.ports = []


class DeviceCancelled(Exception):
    """The device replied CANCEL to a request (e.g. a non-existent preset)."""


class DumpChecksumError(Exception):
    """A dump data packet's checksum did not match its data after retries."""


class EosBridge:
    """A MIDI connection to an EOS device, plus the editor-protocol operations.

    Build one with :meth:`standard` or :meth:`autodetect`. All calls take a
    generous default timeout; every high-level method sends one request and
    waits for exactly the reply it expects (there is no background poller —
    same "never poll the device" principle as k2kremote's refresh worker,
    just without a persistent worker thread since this protocol has no LCD to
    mirror).
    """

    def __init__(self, midi_out, midi_in, description: str, *,
                 device_id: int = DEFAULT_DEVICE_ID, timeout: float = DEFAULT_TIMEOUT):
        self.midi_out = midi_out
        self.midi_in = midi_in
        self.description = description
        self.device_id = device_id
        self.timeout = timeout
        self.inquiry: Optional[m.DeviceInquiryReply] = None

    # -- constructors ---------------------------------------------------
    @classmethod
    def standard(cls, port_name: str, *, gap: float = SEND_GAP,
                 device_id: int = DEFAULT_DEVICE_ID,
                 timeout: float = DEFAULT_TIMEOUT) -> "EosBridge":
        """Connect over a single bidirectional port (the portable default)."""
        out = ThrottledOut(_open_out(port_name), gap=gap)
        in_port = _open_in(port_name)
        return cls(out, in_port, f"standard:{port_name}", device_id=device_id, timeout=timeout)

    @classmethod
    def autodetect(cls, *, gap: float = SEND_GAP, device_id: int = DEFAULT_DEVICE_ID,
                   timeout: float = AUTODETECT_TIMEOUT,
                   on_try: Optional[Callable[[str], None]] = None,
                   config_path: Optional[str] = DEFAULT_CONFIG_PATH) -> "EosBridge":
        """Find an EOS device on any accessible MIDI port via Device Inquiry.

        Unlike k2kremote's K2000 autodetect (which has to blast a
        device-specific screen request because the K2000 predates General
        MIDI's Device Inquiry), EOS answers the *standard* Universal
        Non-Realtime Device Inquiry — so this probes with that, which will
        also correctly identify *which* EOS model answered.

        If ``config_path`` names a readable port cache (see
        :func:`load_last_ports`/:func:`save_last_ports`), the previously
        successful send/receive port pair is tried first — a full sweep can
        take tens of seconds on a host with many MIDI ports, so a warm cache
        turns a reconnect into a near-instant single probe. Falls through to
        the full sweep if the cache is absent, stale (ports renamed/gone), or
        the device doesn't answer on those ports anymore. Pass
        ``config_path=None`` to disable caching entirely.
        """
        if config_path is not None:
            cached = load_last_ports(config_path)
            if cached is not None:
                cached_send, cached_recv = cached
                if on_try is not None:
                    on_try(f"{cached_send} (cached)")
                data = _try_port_pair(cached_send, cached_recv, timeout)
                if data is not None:
                    reply = m.parse_device_inquiry_reply(data)
                    bridge = cls._connect(cached_send, cached_recv, reply, gap=gap, timeout=timeout)
                    save_last_ports(cached_send, cached_recv, config_path)
                    return bridge

        request = m.build_device_inquiry_request(device_id=m.BROADCAST_DEVICE_ID)

        out_names = _enum_out()
        in_names = _enum_in()

        listeners: List[Tuple[str, "rtmidi.MidiIn"]] = []
        for index, name in enumerate(in_names):
            port = None
            try:
                port = rtmidi.MidiIn(queue_size_limit=8192)
                port.open_port(index)
                port.ignore_types(sysex=False)
                listeners.append((name, port))
            except Exception:
                if port is not None:
                    _delete_quiet(port)

        def find_reply():
            for name, port in listeners:
                message = port.get_message()
                while message is not None:
                    data = message[0]
                    if (len(data) >= 15 and data[0] == 0xF0 and data[1] == 0x7E
                            and data[3] == 0x06 and data[4] == 0x02
                            and data[5] == m.MANUFACTURER_ID):
                        return name, data
                    message = port.get_message()
            return None

        try:
            for index, out_name in enumerate(out_names):
                if on_try is not None:
                    on_try(out_name)
                out = None
                try:
                    out = rtmidi.MidiOut()
                    out.open_port(index)
                except Exception:
                    if out is not None:
                        _delete_quiet(out)
                    continue
                found = None
                try:
                    for _, port in listeners:  # flush stale input
                        while port.get_message() is not None:
                            pass
                    out.send_message(list(request))
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        found = find_reply()
                        if found is not None:
                            break
                        time.sleep(0.005)
                finally:
                    out.close_port()
                    _delete_quiet(out)
                if found is not None:
                    recv_name, data = found
                    reply = m.parse_device_inquiry_reply(data)
                    bridge = cls._connect(out_name, recv_name, reply, gap=gap, timeout=timeout)
                    if config_path is not None:
                        save_last_ports(out_name, recv_name, config_path)
                    return bridge
        finally:
            for _, port in listeners:
                port.close_port()
                _delete_quiet(port)

        raise RuntimeError(
            f"auto-probe: no EOS device answered a Device Inquiry on any of "
            f"{len(out_names)} output ports (listened on {len(listeners)})."
        )

    @classmethod
    def _connect(cls, send_name: str, recv_name: str, reply: m.DeviceInquiryReply, *,
                 gap: float, timeout: float) -> "EosBridge":
        out = ThrottledOut(_open_out(send_name), gap=gap)
        in_port = MultiIn(recv_name, exact=True)
        model = reply.model or f"unknown model {reply.member_code}"
        bridge = cls(out, in_port, f"auto:{send_name} -> {recv_name} ({model} rev {reply.revision})",
                     device_id=reply.device_id, timeout=timeout)
        bridge.inquiry = reply
        return bridge

    # -- low-level send/receive ------------------------------------------
    def _send(self, frame: bytes) -> None:
        self.midi_out.send_message(list(frame))

    def _drain(self) -> None:
        while self.midi_in.get_message() is not None:
            pass

    def _receive(self, timeout: Optional[float] = None) -> bytes:
        """Block until one SysEx message arrives; raise TimeoutError otherwise."""
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        while time.time() < deadline:
            message = self.midi_in.get_message()
            if message is not None:
                data = message[0]
                if data and data[0] == 0xF0:
                    return bytes(data)
            time.sleep(0.002)
        raise TimeoutError("no SysEx reply within timeout")

    def send_and_receive(self, frame: bytes, *, timeout: Optional[float] = None) -> bytes:
        """Drain stale input, send ``frame``, and return the next SysEx reply."""
        self._drain()
        self._send(frame)
        return self._receive(timeout)

    # -- device identity ---------------------------------------------------
    def inquire(self, *, timeout: Optional[float] = None) -> m.DeviceInquiryReply:
        reply = self.send_and_receive(
            m.build_device_inquiry_request(self.device_id), timeout=timeout)
        parsed = m.parse_device_inquiry_reply(reply)
        self.inquiry = parsed
        return parsed

    # -- parameters ----------------------------------------------------------
    def get_parameter(self, param_id: int, *, timeout: Optional[float] = None) -> int:
        """Current value of one parameter (device's reply reuses ParameterEdit's format)."""
        req = m.ParameterRequest(param_ids=[param_id], device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        edit = m.ParameterEdit.decode(reply)
        for pid, value in edit.values:
            if pid == param_id:
                return value
        raise ValueError(f"reply did not include parameter {param_id}")

    def get_parameter_range(self, param_id: int, *,
                            timeout: Optional[float] = None) -> m.ParameterRange:
        req = m.ParameterRangeRequest(param_id=param_id, device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        return m.ParameterRange.decode(reply)

    def get_parameters(self, param_ids, *, timeout: Optional[float] = None) -> Dict[int, int]:
        """Current value of several parameters in as few round trips as the
        spec allows (chunked at ``eos.messages.MAX_PARAMETER_REQUESTS`` ids
        per request). The spec says the response is "a complete Parameter
        Value Edit SYSEX message for each parameter" — i.e. one reply frame
        per requested id, not one combined frame — so this receives frames
        in a loop until every id in the chunk has been seen.
        """
        param_ids = list(param_ids)
        values: Dict[int, int] = {}
        for start in range(0, len(param_ids), m.MAX_PARAMETER_REQUESTS):
            chunk = param_ids[start:start + m.MAX_PARAMETER_REQUESTS]
            req = m.ParameterRequest(param_ids=chunk, device_id=self.device_id)
            self._drain()
            self._send(req.encode())
            remaining = set(chunk)
            while remaining:
                frame = self._receive(timeout)
                edit = m.ParameterEdit.decode(frame)
                for pid, value in edit.values:
                    if pid in remaining:
                        values[pid] = value
                        remaining.discard(pid)
        return values

    def set_parameter(self, param_id: int, value: int) -> None:
        """Write one parameter. Fire-and-forget — the spec defines no reply
        to a Parameter Value Edit."""
        edit = m.ParameterEdit(values=[(param_id, value & 0x3FFF)], device_id=self.device_id)
        self._send(edit.encode())

    def set_parameters(self, values) -> None:
        """Write several (param_id, value) pairs in as few messages as the
        spec allows (``eos.messages.MAX_PARAMETER_EDITS`` per message)."""
        values = list(values)
        for start in range(0, len(values), m.MAX_PARAMETER_EDITS):
            chunk = values[start:start + m.MAX_PARAMETER_EDITS]
            edit = m.ParameterEdit(
                values=[(pid, val & 0x3FFF) for pid, val in chunk], device_id=self.device_id)
            self._send(edit.encode())

    # -- naming ----------------------------------------------------------
    def get_preset_name(self, preset: int, *, timeout: Optional[float] = None) -> str:
        req = m.PresetNameRequest(preset=preset, device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        return m.PresetName.decode(reply).name

    def set_preset_name(self, preset: int, name: str) -> None:
        self._send(m.PresetName(preset=preset, name=name, device_id=self.device_id).encode())

    def get_sample_name(self, sample: int, *, timeout: Optional[float] = None) -> str:
        req = m.SampleNameRequest(sample=sample, device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        return m.SampleName.decode(reply).name

    def set_sample_name(self, sample: int, name: str) -> None:
        self._send(m.SampleName(sample=sample, name=name, device_id=self.device_id).encode())

    # -- memory / configuration -------------------------------------------
    def preset_memory(self, *, timeout: Optional[float] = None) -> m.PresetMemoryResponse:
        req = m.PresetMemoryRequest(device_id=self.device_id)
        return m.PresetMemoryResponse.decode(self.send_and_receive(req.encode(), timeout=timeout))

    def sample_memory(self, *, timeout: Optional[float] = None) -> m.SampleMemoryResponse:
        req = m.SampleMemoryRequest(device_id=self.device_id)
        return m.SampleMemoryResponse.decode(self.send_and_receive(req.encode(), timeout=timeout))

    def configuration(self, *, timeout: Optional[float] = None) -> m.ConfigurationResponse:
        req = m.ConfigurationRequest(device_id=self.device_id)
        return m.ConfigurationResponse.decode(self.send_and_receive(req.encode(), timeout=timeout))

    def extended_configuration(self, *,
                               timeout: Optional[float] = None) -> m.ExtendedConfigurationResponse:
        req = m.ExtendedConfigurationRequest(device_id=self.device_id)
        return m.ExtendedConfigurationResponse.decode(
            self.send_and_receive(req.encode(), timeout=timeout))

    def preset_num_voices(self, preset: int, *, timeout: Optional[float] = None) -> int:
        req = m.PresetNumVoicesRequest(preset=preset, device_id=self.device_id)
        return m.PresetNumVoicesResponse.decode(
            self.send_and_receive(req.encode(), timeout=timeout)).num_voices

    def preset_num_links(self, preset: int, *, timeout: Optional[float] = None) -> int:
        req = m.PresetNumLinksRequest(preset=preset, device_id=self.device_id)
        return m.PresetNumLinksResponse.decode(
            self.send_and_receive(req.encode(), timeout=timeout)).num_links

    def preset_num_szones(self, preset: int, *, timeout: Optional[float] = None) -> int:
        req = m.PresetNumSZonesRequest(preset=preset, device_id=self.device_id)
        return m.PresetNumSZonesResponse.decode(
            self.send_and_receive(req.encode(), timeout=timeout)).num_szones

    def voice_num_szones(self, preset: int, voice: int, *,
                        timeout: Optional[float] = None) -> int:
        req = m.VoiceNumSZonesRequest(preset=preset, voice=voice, device_id=self.device_id)
        return m.VoiceNumSZonesResponse.decode(
            self.send_and_receive(req.encode(), timeout=timeout)).num_szones

    # -- catalog (best-effort scan; the spec has no "list all presets") ---
    def catalog_presets(self, preset_range=range(0, 128), *,
                       timeout: Optional[float] = None,
                       on_progress: Optional[Callable[[int], None]] = None) -> dict:
        """Best-effort {preset_number: name} over ``preset_range``.

        There is no spec'd "give me every preset number in use" command, so
        this simply asks for each number in the range and records whichever
        answer with a real name (skipping timeouts and CANCEL replies, which
        both mean "nothing there").
        """
        names = {}
        for preset in preset_range:
            if on_progress is not None:
                on_progress(preset)
            try:
                reply = self.send_and_receive(
                    m.PresetNameRequest(preset=preset, device_id=self.device_id).encode(),
                    timeout=timeout)
            except TimeoutError:
                continue
            try:
                names[preset] = m.PresetName.decode(reply).name
            except ValueError:
                continue  # e.g. a CANCEL frame instead of a PresetName reply
        return names

    def catalog_samples(self, sample_range=range(0, 128), *,
                        timeout: Optional[float] = None,
                        on_progress: Optional[Callable[[int], None]] = None) -> dict:
        """Best-effort {sample_number: name} over ``sample_range`` — see
        :meth:`catalog_presets` for the same caveat."""
        names = {}
        for sample in sample_range:
            if on_progress is not None:
                on_progress(sample)
            try:
                reply = self.send_and_receive(
                    m.SampleNameRequest(sample=sample, device_id=self.device_id).encode(),
                    timeout=timeout)
            except TimeoutError:
                continue
            try:
                names[sample] = m.SampleName.decode(reply).name
            except ValueError:
                continue
        return names

    # -- preset dump (OLD format) ------------------------------------------
    def dump_preset_old(self, preset: int, *, timeout: Optional[float] = None,
                        max_retries: int = 3) -> bytes:
        """OLD-format single-preset dump. Returns the raw concatenated data
        bytes: confirmed live (2026-07-27, RESOLUTION_NOTES §7) to start with
        a 2-byte (u14) preset number, then the 16-byte name, then 44 bytes of
        global parms (22 signed 14-bit words, in exactly `eos.params`'s
        GLOBAL id order), then link/voice data whose exact byte layout is
        not yet fully cross-checked — see docs/RESOLUTION_NOTES.md §6/§7 and
        the captured sample at docs/samples/.

        Raises :class:`DeviceCancelled` if the preset does not exist, and
        :class:`DumpChecksumError` if a data packet's checksum keeps failing
        after ``max_retries`` NAKs.
        """
        request = m.PresetDumpRequest(preset=preset, device_id=self.device_id)
        reply = self.send_and_receive(request.encode(), timeout=timeout)
        _, command, _ = m.parse_frame(reply)
        if command == m.Command.CANCEL:
            raise DeviceCancelled(f"preset {preset} does not exist on the device")
        header = m.OldDumpHeader.decode(reply)
        # The spec calls the header "the first packet" (packet number 0) —
        # confirmed live (2026-07-27, RESOLUTION_NOTES §7): the device waits
        # for this ACK before sending any data packets.
        self._send(m.Ack(packet_number=header.packet_number, device_id=self.device_id).encode())

        data = bytearray()
        while len(data) < header.byte_count:
            frame = self._receive(timeout)
            _, command, _ = m.parse_frame(frame)
            if command == m.Command.EOF:
                break
            message = m.OldDumpMessage.decode(frame)
            if not message.verify():
                for _ in range(max_retries):
                    self._send(m.Nak(packet_number=message.packet_number,
                                     device_id=self.device_id).encode())
                    frame = self._receive(timeout)
                    message = m.OldDumpMessage.decode(frame)
                    if message.verify():
                        break
                else:
                    raise DumpChecksumError(
                        f"packet {message.packet_number} failed checksum after {max_retries} retries")
            data.extend(message.data)
            self._send(m.Ack(packet_number=message.packet_number, device_id=self.device_id).encode())

        return bytes(data)

    # -- preset dump (NEW format) -------------------------------------------
    def dump_preset_new(self, preset: int, *, timeout: Optional[float] = None,
                        max_retries: int = 3) -> Tuple[m.NewDumpHeader, bytes]:
        """NEW-format single-preset dump. Returns ``(header, raw_data)`` — the
        header's ``num_*_params`` fields tell the caller how the flat
        ``raw_data`` is structured (see the spec's "Dump Data Formats"
        grammar, transcribed in docs/RESOLUTION_NOTES.md §2).
        """
        request = m.NewDumpRequest(preset=preset, device_id=self.device_id)
        reply = self.send_and_receive(request.encode(), timeout=timeout)
        _, command, _ = m.parse_frame(reply)
        if command == m.Command.CANCEL:
            raise DeviceCancelled(f"preset {preset} does not exist on the device")
        header = m.NewDumpHeader.decode(reply)
        # Extrapolated from the OLD-format finding (RESOLUTION_NOTES §7: the
        # header is "packet 0" and needs an ACK before data flows) — NOT yet
        # confirmed live for the NEW format specifically, since NewDumpHeader
        # carries no explicit packet-number field to begin with.
        self._send(m.NewAck(packet_number=0, device_id=self.device_id).encode())

        data = bytearray()
        while len(data) < header.total_bytes:
            frame = self._receive(timeout)
            _, command, _ = m.parse_frame(frame)
            if command == m.Command.EOF:
                break
            message = m.NewDumpMessage.decode(frame)
            if not message.verify():
                for _ in range(max_retries):
                    self._send(m.NewNak(packet_number=message.packet_number,
                                        device_id=self.device_id).encode())
                    frame = self._receive(timeout)
                    message = m.NewDumpMessage.decode(frame)
                    if message.verify():
                        break
                else:
                    raise DumpChecksumError(
                        f"packet {message.packet_number} failed checksum after {max_retries} retries")
            data.extend(message.data)
            self._send(m.NewAck(packet_number=message.packet_number,
                                device_id=self.device_id).encode())

        return header, bytes(data)

    # -- destructive utilities (fire-and-forget; see DESTRUCTIVE_COMMANDS) --
    # The spec defines no acknowledgement format for any of these four
    # commands (unlike e.g. Preset Copy, which documents a NAK-on-failure).
    # Callers (the CLI, the TUI's Master screen) must never key-bind these to
    # a single keypress — always an explicit arm-then-fire confirmation.
    def delete_preset(self, preset: int) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.PresetDelete(preset=preset, device_id=self.device_id).encode())

    def erase_ram_bank(self) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.EraseRamBank(device_id=self.device_id).encode())

    def erase_all_ram_presets(self) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.EraseAllRamPresets(device_id=self.device_id).encode())

    def erase_all_ram_samples(self) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.EraseAllRamSamples(device_id=self.device_id).encode())

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        for port in (self.midi_out, self.midi_in):
            try:
                port.close_port()
            except Exception:
                pass
            raw = getattr(port, "_port", None)
            if raw is not None:
                _delete_quiet(raw)

    def __repr__(self) -> str:
        return f"<EosBridge {self.description!r}>"
