# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.
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
from eos import params as p

# --- defaults ----------------------------------------------------------
SEND_GAP = 0.05            # conservative; NOT reverse-engineered for EOS (see module docstring)
DEFAULT_TIMEOUT = 2.0
AUTODETECT_TIMEOUT = 1.0
# Bounds on the autodetect reply drain. Neither is a protocol limit — they
# exist so a port that never runs dry cannot spin or accumulate without end.
_MAX_INQUIRY_DRAIN = 64      # messages read from one port in one pass
_MAX_INQUIRY_REPLIES = 32    # Device Inquiry replies kept per probe
DEFAULT_DEVICE_ID = m.DEFAULT_DEVICE_ID
DEFAULT_CONFIG_PATH = "config.toml"  # CWD-relative, matching k2kremote's BridgeConfig convention


# --- config.toml: a flat, local, gitignored key/value store -----------------
# Shared by the port cache below and eosed.app's view-mode preference.
# Read-modify-write (not a blind overwrite) so unrelated keys survive each
# other's saves — this file holds more than one independent setting.

def _read_config_dict(path: str) -> dict:
    import os
    import tomllib

    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except Exception:
        return {}


def _write_config_dict(data: dict, path: str) -> None:
    lines = ["# eosed local config — gitignored, safe to delete."]
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    try:
        with open(path, "w") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass  # the cache is a convenience, not required for correctness


# --- last-known-good port cache ---------------------------------------------
# A full autodetect sweep tries every output port (up to ~1s each while a
# port doesn't answer) — on a host with two dozen MIDI ports that's tens of
# seconds. Once a send/receive pair has answered, remember it and try it
# first on the next connection, before falling back to the full sweep (which
# still runs if the cached ports are gone or don't answer, e.g. after
# replugging an interface).

def load_last_ports(path: str = DEFAULT_CONFIG_PATH) -> Optional[Tuple[str, str]]:
    data = _read_config_dict(path)
    send_port = data.get("send_port")
    recv_port = data.get("recv_port")
    if isinstance(send_port, str) and isinstance(recv_port, str):
        return send_port, recv_port
    return None


def save_last_ports(send_port: str, recv_port: str, path: str = DEFAULT_CONFIG_PATH) -> None:
    data = _read_config_dict(path)
    data["send_port"] = send_port
    data["recv_port"] = recv_port
    _write_config_dict(data, path)


# --- remembered TUI view mode ------------------------------------------------
# eosed.app.EosedApp's compact-vs-extended pane layout, persisted so
# the choice survives a restart (see docs/RESOLUTION_NOTES.md).

def load_compact_view(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    value = _read_config_dict(path).get("compact_view")
    return value if isinstance(value, bool) else None


def save_compact_view(compact: bool, path: str = DEFAULT_CONFIG_PATH) -> None:
    data = _read_config_dict(path)
    data["compact_view"] = compact
    _write_config_dict(data, path)


# --- sample-usage reverse-lookup early-stop threshold ------------------------
# eosed.app.EosedApp's "which presets use this sample" scan
# (action_find_sample_usage) bails out after this many consecutive
# no-voices presets, since a full 0-999 sweep can take several minutes.
# User-edited in config.toml, not written by the app itself: either an int
# (the threshold) or the literal string "fullscan" to disable early-stop
# and always sweep the complete range.

def load_sample_usage_early_stop(path: str = DEFAULT_CONFIG_PATH):
    """Returns an int threshold, the string "fullscan", or None if unset/invalid."""
    value = _read_config_dict(path).get("sample_usage_early_stop")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() == "fullscan":
        return "fullscan"
    return None


# --- "cache all data" sweep (eosed.app's 'a' key / startup option) -------
# A full bank sweep (same walk as the sample-usage lookup above, but keeping
# everything it fetches instead of just the sample->preset mapping) is
# expensive — several minutes on a fully-populated bank — so both how deep it
# goes and whether it runs unattended at startup are user-edited, not
# app-written, same convention as sample_usage_early_stop above. Never
# persisted to disk *by* the app: the cache itself is deliberately in-memory
# only (see eosed.app.EosedApp's cache fields) since a front-panel
# edit is invisible to us and a stale disk cache would confidently lie.

def load_cache_all_on_startup(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    """Run a `cache_depth`-deep sweep on connect. Defaults to OFF.

    At the default "full" depth this is measured at 1h 44m on a large
    commercial bank (docs/RESOLUTION_NOTES.md §20) — far too much to do
    unprompted, which is why `cache_structure_on_startup` below is the one
    that defaults on.
    """
    value = _read_config_dict(path).get("cache_all_on_startup")
    return value if isinstance(value, bool) else None


def load_cache_structure_on_startup(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    """Run a "structure"-depth sweep on connect. Defaults to OFF.

    Opt-in like its `cache_all_on_startup` sibling: at 23 min on a large
    bank it is far cheaper than "full" (1h 44m) but still much too long to
    impose on someone who launched the app to look at one preset. Worth
    turning on for a session you know will involve a lot of browsing —
    afterwards preset selection, bank paging and `u` cost no MIDI at all.
    Cancellable with `escape`, and it announces its estimate rather than
    starting silently.
    """
    value = _read_config_dict(path).get("cache_structure_on_startup")
    return value if isinstance(value, bool) else None


def load_cache_depth(path: str = DEFAULT_CONFIG_PATH) -> Optional[str]:
    """Returns "names", "structure", "full", or None if unset/invalid."""
    value = _read_config_dict(path).get("cache_depth")
    if isinstance(value, str) and value.strip().lower() in ("names", "structure", "full"):
        return value.strip().lower()
    return None


# --- signed parameter values -------------------------------------------------
def _signed_value(param_id: int, raw: int) -> int:
    """Sign-extend a parameter value read off the wire, if it is a signed one.

    Parameter values travel as 14-bit two's complement (`encode_s14`), but the
    device's *value* replies (a Parameter Value Edit reusing command 01h) carry
    no signedness flag, so `ParameterEdit.decode` can only hand back the raw
    unsigned word -- E4_PRESET_TRANSPOSE = -12 arrives as 16372. Its sibling
    03h/04h min/max/default reply *is* decoded signed (`ParameterRange`), so
    without this the two halves of the same parameter disagree: a range of
    [-24, 24] against a current value of 16372.

    Confirmed live 2026-07-31 against an E4XT Ultra (rev 4.70): writing -12
    and -24 to E4_PRESET_TRANSPOSE read back as 16372 and 16360, i.e. exactly
    `value & 0x3FFF` -- the write path and the device are both correct, only
    the read side was missing the sign extension.

    Which parameters are signed comes from `eos.params`' own table (a negative
    `minimum`), the same table that supplies every other per-parameter fact.
    An id absent from the table, or any value without bit 13 set, is passed
    through untouched -- which is what keeps the undocumented 3FFEh/3FFFh
    E4_GEN_SAMPLE sentinels (an unsigned 0..999 parameter) intact.
    """
    if not raw & 0x2000:
        return raw
    try:
        param = p.lookup(param_id)
    except KeyError:
        return raw
    return raw - 0x4000 if param.minimum < 0 else raw


# --- send Program Change on preset select ------------------------------------
# PRESET_SELECT (id 223, the editor protocol's own selector) is spec-stated
# to be "independent of the front panel's own selection" -- selecting a
# preset that way never makes the device redraw its own LCD (see
# DISCLAIMER.md). A plain MIDI Program Change is a completely different,
# ordinary channel voice message (not part of this SysEx protocol at all)
# that genuinely does. User-edited, not app-written, same convention as the
# cache-all settings above; defaults to on (unlike cache_all_on_startup)
# since it's cheap and has no real downside for a session actually being
# played on the hardware.

def load_send_pc_on_preset_select(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    value = _read_config_dict(path).get("send_pc_on_preset_select")
    return value if isinstance(value, bool) else None


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

    Two gaps, because the two kinds of send need different protection --
    measured live, see docs/RESOLUTION_NOTES.md §19b:

    * A **request** is followed by a blocking wait for its reply, so the
      round trip already separates it from the next send and the gap is
      nearly redundant. Dropping it to 5ms changed nothing but latency.
    * A **write** (Parameter Edit, naming, the destructive utilities) is
      fire-and-forget. ``set_parameters`` emits up to 42 edits per frame and
      several frames back to back with *only* this gap between them and no
      reply to pace against, so it is the only thing standing between us and
      an overrun input buffer -- and the failure mode is silent, since a lost
      edit raises nothing and is found only by reading back.

    So ``write_gap`` should be the conservative one and ``gap`` may be cut.
    ``write_gap`` defaults to ``gap``, i.e. the single-gap behaviour this
    class had before, unless a caller asks for the split.

    The gap is applied as time owed *after* a send -- how long the device is
    given to digest what it was just handed -- so the wait before any send is
    determined by whatever preceded it, not by what is about to go out.
    """

    def __init__(self, port: rtmidi.MidiOut, gap: float = SEND_GAP, *,
                 write_gap: Optional[float] = None):
        self._port = port
        self._gap = gap
        self._write_gap = gap if write_gap is None else write_gap
        self._last = 0.0
        self._owed = 0.0

    def send_message(self, message, *, write: bool = False) -> None:
        is_sysex = len(message) > 0 and message[0] == 0xF0
        if not is_sysex:
            self._port.send_message(message)
            return
        wait = self._owed - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._port.send_message(message)
        self._last = time.time()
        self._owed = self._write_gap if write else self._gap

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


class AmbiguousDevice(RuntimeError):
    """More than one EOS device answered the Device Inquiry.

    Distinct device ids are how the protocol expects machines to be told
    apart. The EOS 4.0 Software Manual (p. 104, "MIDI Device ID") says so
    directly -- "allows an external SysEx programming device to distinguish
    between multiple Emulator units. In this case, each Emulator should have
    a different ID number" -- and the SysEx spec provides the mechanism,
    defining 0-126 as unique ids and 127 as the all-broadcast id. (The spec
    itself never states the obligation; it only describes the address space.)

    When two devices answer with different ids there is no basis for picking one,
    so autodetect refuses rather than silently binding to whichever replied
    first — which, with two identical machines, would be decided by MIDI port
    enumeration order and could change between reboots.

    Two devices left on the *same* id are indistinguishable on the wire (the
    reply payloads are byte-identical, and so is one device heard on two
    input ports), so this cannot detect that case. That configuration is a
    protocol violation on the user's side.
    """

    def __init__(self, devices):
        self.devices = devices          # [(device_id, model, recv_port), ...]
        listing = "\n".join(
            f"  device id {did}: {model} on {port}" for did, model, port in devices)
        super().__init__(
            f"{len(devices)} EOS devices answered:\n{listing}\n"
            "Pass --device-id N to choose one, or pin the ports explicitly by "
            "setting send_port/recv_port in the config file.")


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
        # Lazily-read MIDIGLO_BASIC_CHANNEL (id 198) — see basic_channel().
        self._basic_channel: Optional[int] = None

    # -- constructors ---------------------------------------------------
    @classmethod
    def standard(cls, port_name: str, *, gap: float = SEND_GAP,
                 write_gap: Optional[float] = None,
                 device_id: int = DEFAULT_DEVICE_ID,
                 timeout: float = DEFAULT_TIMEOUT) -> "EosBridge":
        """Connect over a single bidirectional port (the portable default).

        ``write_gap`` defaults to ``gap``; see :class:`ThrottledOut` for why
        the two may reasonably differ."""
        out = ThrottledOut(_open_out(port_name), gap=gap, write_gap=write_gap)
        in_port = _open_in(port_name)
        return cls(out, in_port, f"standard:{port_name}", device_id=device_id, timeout=timeout)

    @classmethod
    def autodetect(cls, *, gap: float = SEND_GAP, write_gap: Optional[float] = None,
                   device_id: Optional[int] = None,
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

        ``device_id`` selects *which* device to bind to when more than one is
        connected — ``None`` (the default) means "whichever answers". The
        inquiry itself always goes out broadcast, so every device replies and
        this can tell them apart; the spec requires distinct ids on a shared
        setup for exactly this reason. If several answer with different ids
        and none was requested, :class:`AmbiguousDevice` is raised rather than
        binding to whichever happened to reply first — that choice would
        otherwise fall out of MIDI port enumeration order and could change
        between reboots.

        Note this waits the full ``timeout`` on the port that answers, rather
        than returning at the first reply, so a second device on the same wire
        is actually heard. Costs one extra ``timeout`` on a cold cache.
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
                    # A cached pair that answers with the *wrong* device falls
                    # through to the sweep: the cache remembers ports, and on a
                    # multi-device setup the machine behind a port can change.
                    if device_id is None or reply.device_id == device_id:
                        bridge = cls._connect(cached_send, cached_recv, reply, gap=gap,
                                             write_gap=write_gap, timeout=timeout)
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

        def collect_replies(into):
            """Drain every listener, appending each Device Inquiry reply seen.

            Collects rather than returning the first: two machines on one wire
            both answer a broadcast inquiry, and stopping at the first would
            be exactly the silent mis-binding this is meant to prevent.

            Bounded on both axes. Draining "until the port is empty" trusts
            the port to eventually run dry, and a chatty or wedged one never
            does -- this loop grew to 12GB against a fake that re-answered
            every call. There is no legitimate setup with dozens of EOS units
            on one wire, so a cap costs nothing real and turns a hang into a
            correct answer.
            """
            for name, port in listeners:
                for _ in range(_MAX_INQUIRY_DRAIN):
                    message = port.get_message()
                    if message is None:
                        break
                    data = message[0]
                    if (len(data) >= 15 and data[0] == 0xF0 and data[1] == 0x7E
                            and data[3] == 0x06 and data[4] == 0x02
                            and data[5] == m.MANUFACTURER_ID):
                        if len(into) >= _MAX_INQUIRY_REPLIES:
                            return
                        into.append((name, bytes(data)))

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
                seen: List[Tuple[str, bytes]] = []
                try:
                    for _, port in listeners:  # flush stale input
                        while port.get_message() is not None:
                            pass
                    out.send_message(list(request))
                    # Listen for the whole window even after a reply arrives —
                    # a second machine on the same wire answers too, and we
                    # need to know about it.
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        collect_replies(seen)
                        time.sleep(0.005)
                    collect_replies(seen)
                finally:
                    out.close_port()
                    _delete_quiet(out)
                if not seen:
                    continue

                # Key by device id: the same machine heard on two input ports
                # is one device, not two. Two machines sharing an id are
                # byte-identical on the wire and collapse here too — that case
                # is undetectable and is a protocol violation by the user.
                by_id = {}
                for recv_name, data in seen:
                    try:
                        reply = m.parse_device_inquiry_reply(data)
                    except Exception:
                        continue
                    by_id.setdefault(reply.device_id, (recv_name, reply))
                if not by_id:
                    continue

                if device_id is not None:
                    if device_id not in by_id:
                        continue          # not the one we want; keep sweeping
                    recv_name, reply = by_id[device_id]
                elif len(by_id) > 1:
                    raise AmbiguousDevice(sorted(
                        (did, rep.model or f"member {rep.member_code}", port_name)
                        for did, (port_name, rep) in by_id.items()))
                else:
                    recv_name, reply = next(iter(by_id.values()))

                bridge = cls._connect(out_name, recv_name, reply, gap=gap,
                                 write_gap=write_gap, timeout=timeout)
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
                 gap: float, timeout: float,
                 write_gap: Optional[float] = None) -> "EosBridge":
        out = ThrottledOut(_open_out(send_name), gap=gap, write_gap=write_gap)
        in_port = MultiIn(recv_name, exact=True)
        model = reply.model or f"unknown model {reply.member_code}"
        bridge = cls(out, in_port, f"auto:{send_name} -> {recv_name} ({model} rev {reply.revision})",
                     device_id=reply.device_id, timeout=timeout)
        bridge.inquiry = reply
        return bridge

    # -- low-level send/receive ------------------------------------------
    def _send(self, frame: bytes, *, write: bool = False) -> None:
        """Send one frame. ``write=True`` marks a fire-and-forget write, which
        `ThrottledOut` may gap more conservatively than a request whose reply
        we are about to block on anyway -- see that class's docstring."""
        self.midi_out.send_message(list(frame), write=write)

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
        """Current value of one parameter (device's reply reuses ParameterEdit's
        format), sign-extended for signed parameters -- see `_signed_value`."""
        req = m.ParameterRequest(param_ids=[param_id], device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        edit = m.ParameterEdit.decode(reply)
        for pid, value in edit.values:
            if pid == param_id:
                return _signed_value(pid, value)
        raise ValueError(f"reply did not include parameter {param_id}")

    def get_parameter_range(self, param_id: int, *,
                            timeout: Optional[float] = None) -> m.ParameterRange:
        """The device's own min/max/default for one parameter -- authoritative
        over `eos.params`' transcribed range, which is a different EOS version's.

        Sign-extended through the same `_signed_value` the value read uses, so
        a parameter's range and its current value can never disagree about
        signedness (they did before: a range of [-24, 24] against a value of
        16372).
        """
        req = m.ParameterRangeRequest(param_id=param_id, device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        raw = m.ParameterRange.decode(reply)
        return m.ParameterRange(
            param_id=raw.param_id,
            minimum=_signed_value(param_id, raw.minimum),
            maximum=_signed_value(param_id, raw.maximum),
            default=_signed_value(param_id, raw.default),
            device_id=raw.device_id,
        )

    def get_parameters(self, param_ids, *, timeout: Optional[float] = None) -> Dict[int, int]:
        """Current value of several parameters in as few round trips as the
        spec allows (chunked at ``eos.messages.MAX_PARAMETER_REQUESTS`` ids
        per request). The spec says the response is "a complete Parameter
        Value Edit SYSEX message for each parameter" — i.e. one reply frame
        per requested id, not one combined frame — so this receives frames
        in a loop until every id in the chunk has been seen.

        Values are sign-extended for signed parameters, exactly as
        `get_parameter` does — see `_signed_value`.
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
                        values[pid] = _signed_value(pid, value)
                        remaining.discard(pid)
        return values

    def set_parameter(self, param_id: int, value: int) -> None:
        """Write one parameter. Fire-and-forget — the spec defines no reply
        to a Parameter Value Edit."""
        edit = m.ParameterEdit(values=[(param_id, value & 0x3FFF)], device_id=self.device_id)
        self._send(edit.encode(), write=True)

    def set_parameters(self, values) -> None:
        """Write several (param_id, value) pairs in as few messages as the
        spec allows (``eos.messages.MAX_PARAMETER_EDITS`` per message)."""
        values = list(values)
        for start in range(0, len(values), m.MAX_PARAMETER_EDITS):
            chunk = values[start:start + m.MAX_PARAMETER_EDITS]
            edit = m.ParameterEdit(
                values=[(pid, val & 0x3FFF) for pid, val in chunk], device_id=self.device_id)
            self._send(edit.encode(), write=True)

    # -- naming ----------------------------------------------------------
    def get_preset_name(self, preset: int, *, timeout: Optional[float] = None) -> str:
        req = m.PresetNameRequest(preset=preset, device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        return m.PresetName.decode(reply).name

    def set_preset_name(self, preset: int, name: str) -> None:
        self._send(m.PresetName(preset=preset, name=name, device_id=self.device_id).encode(), write=True)

    def get_sample_name(self, sample: int, *, timeout: Optional[float] = None) -> str:
        req = m.SampleNameRequest(sample=sample, device_id=self.device_id)
        reply = self.send_and_receive(req.encode(), timeout=timeout)
        return m.SampleName.decode(reply).name

    def set_sample_name(self, sample: int, name: str) -> None:
        self._send(m.SampleName(sample=sample, name=name, device_id=self.device_id).encode(), write=True)

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

    # The "Preset Num Of X" siblings (0x16-0x1B: voices/links/preset-zones)
    # do NOT all behave alike despite sharing a command family, byte range,
    # and wire shape — each needed its own independent live check rather
    # than extrapolating from the others (see docs/RESOLUTION_NOTES.md §11
    # for the links story; §12 for preset_num_voices itself turning out to
    # be unreliable too, the same way voice_num_szones already was):
    # - preset_num_voices: **do not trust this as a voice count at all** —
    #   confirmed correct (raw - 1) for one preset on two different bank
    #   states, then directly contradicted live by two more real presets on
    #   a third bank (both front-panel-confirmed to have 1 real voice each,
    #   both playing audible sound, both reading raw=1 -- which the "-1"
    #   fix would report as 0 real voices). Not a fixed offset at all, same
    #   failure mode as voice_num_szones. eosed.app never uses this
    #   method's return value to bound a loop; it walks voice indices
    #   directly instead (see _voice_sample_info's docstring). Kept here,
    #   uncorrected (raw passthrough), only for API completeness.
    # - preset_num_links: wire value IS the plain, direct count -- confirmed
    #   live against preset 0, whose own dump file
    #   independently shows exactly 1 real link, matching the raw wire
    #   value of 1 exactly (no offset). Only one data point, though, and
    #   preset_num_voices' own history is now a specific warning against
    #   trusting a single confirmation — treat this as provisional too.
    # - preset_num_szones: not called anywhere in this codebase and not
    #   independently tested at all -- given confirmed siblings above
    #   disagree with each other, do NOT assume any formula (or no
    #   correction) applies here without its own live check first.
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
        """Raw wire value — **do not trust this as a zone count.**

        Unlike the "Preset Num Of X" trio above, this one isn't off by a
        fixed constant: confirmed live to disagree with the real zone count
        in a preset/voice-dependent way with no consistent formula (one
        voice needed +1, another needed +3 — see docs/RESOLUTION_NOTES.md
        §11). The sibling mpc2emu project independently found the analogous
        on-disk "n_zones" field equally unreliable/redundant for this same
        device family. ``eosed.app._voice_sample_info`` does not use
        this method at all — it detects "is this voice a multisample" from
        the spec-documented 3FFFh sentinel on the voice's own
        ``E4_GEN_SAMPLE`` instead, then walks zones until one reads 0.
        Kept here only for API completeness / a future recalibration.
        """
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
                    # A device may answer a NAK by giving up rather than
                    # resending -- decoding that as a data message would
                    # raise a bare ValueError out of a checksum retry, which
                    # reads like a codec bug rather than "the device ended
                    # the transfer".
                    _, retry_command, _ = m.parse_frame(frame)
                    if retry_command == m.Command.EOF:
                        return bytes(data[:header.byte_count])
                    if retry_command == m.Command.CANCEL:
                        raise DeviceCancelled(
                            f"device cancelled the dump of preset {preset} after a NAK")
                    message = m.OldDumpMessage.decode(frame)
                    if message.verify():
                        break
                else:
                    raise DumpChecksumError(
                        f"packet {message.packet_number} failed checksum after {max_retries} retries")
            data.extend(message.data)
            self._send(m.Ack(packet_number=message.packet_number, device_id=self.device_id).encode())

        # Trim to the count the header promised: the final packet carries
        # "256 Bytes, or LESS" per the spec, but nothing stops a device from
        # padding it out to a full packet, and silently returning the padding
        # would shift every offset a caller computes into the tail.
        return bytes(data[:header.byte_count])

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
                    # Same as the OLD path: the device may end the transfer
                    # in response to a NAK instead of resending.
                    _, retry_command, _ = m.parse_frame(frame)
                    if retry_command == m.Command.EOF:
                        return header, bytes(data[:header.total_bytes])
                    if retry_command == m.Command.CANCEL:
                        raise DeviceCancelled(
                            f"device cancelled the dump of preset {preset} after a NAK")
                    message = m.NewDumpMessage.decode(frame)
                    if message.verify():
                        break
                else:
                    raise DumpChecksumError(
                        f"packet {message.packet_number} failed checksum after {max_retries} retries")
            data.extend(message.data)
            self._send(m.NewAck(packet_number=message.packet_number,
                                device_id=self.device_id).encode())

        # Trimmed for the same reason as the OLD path above.
        return header, bytes(data[:header.total_bytes])

    # -- destructive utilities (fire-and-forget; see DESTRUCTIVE_COMMANDS) --
    # The spec defines no acknowledgement format for any of these four
    # commands (unlike e.g. Preset Copy, which documents a NAK-on-failure).
    # Callers (the CLI, the TUI's Master screen) must never key-bind these to
    # a single keypress — always an explicit arm-then-fire confirmation.
    def delete_preset(self, preset: int) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.PresetDelete(preset=preset, device_id=self.device_id).encode(), write=True)

    def erase_ram_bank(self) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.EraseRamBank(device_id=self.device_id).encode(), write=True)

    def erase_all_ram_presets(self) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.EraseAllRamPresets(device_id=self.device_id).encode(), write=True)

    def erase_all_ram_samples(self) -> None:
        """DESTRUCTIVE, one-shot, no device-side confirmation."""
        self._send(m.EraseAllRamSamples(device_id=self.device_id).encode(), write=True)

    # -- plain MIDI performance messages (not the editor SysEx protocol) -----
    # PRESET_SELECT (id 223) is spec-stated to be "independent of the front
    # panel's own selection" -- a remote edit made after selecting a preset
    # that way is written to a separate buffer the LCD doesn't reflect until
    # the preset is touched from the front panel (see docs/RESOLUTION_NOTES.md
    # and DISCLAIMER.md). Program Change is a completely different, ordinary
    # MIDI channel voice message (not SysEx at all) -- the normal way a
    # keyboard player switches patches during a performance. Bank Select
    # (CC0 MSB / CC32 LSB) precedes it since a bare Program Change only
    # reaches 0-127 and the preset range here is 0-999 (2999 with Preset
    # Flash) -- this follows the universal MIDI Bank Select convention, not
    # something specific to this device; NOT YET independently verified
    # live that the E4XT accepts exactly this MSB/LSB/order for its own
    # preset numbering (see docs/RESOLUTION_NOTES.md before trusting it).
    def basic_channel(self, *, timeout: Optional[float] = None) -> int:
        """The device's ``MIDIGLO_BASIC_CHANNEL`` (id 198), read once and cached.

        A device-global setting, not a per-preset one, so re-reading it on
        every :meth:`send_program_change` was a wasted round trip per preset
        selection. It *can* still be changed from the front panel mid-
        session — call :meth:`forget_basic_channel` if that may have
        happened, or pass ``channel`` explicitly.
        """
        if self._basic_channel is None:
            self._basic_channel = self.get_parameter(198, timeout=timeout)
        return self._basic_channel

    def forget_basic_channel(self) -> None:
        """Drop the cached basic channel so the next read hits the device."""
        self._basic_channel = None

    def send_program_change(self, preset: int, *, channel: Optional[int] = None) -> None:
        """Select ``preset`` via Bank Select + Program Change, not the
        editor protocol's PRESET_SELECT -- this is what actually makes the
        E4/E4XT itself select the preset (and redraw its own front-panel
        display), the same as a musician switching patches live.

        Bank Select MSB is always 0; LSB selects which block of 128
        presets (0 -> 0-127, 1 -> 128-255, ...), Program Change picks
        within that block (0-127) -- confirmed live, all three messages
        required every time (banks aren't "sticky" across calls in a way
        that would let Bank Select be skipped when unchanged).

        ``channel`` defaults to the device's own live
        ``MIDIGLO_BASIC_CHANNEL`` (id 198) rather than assuming channel 0.
        That value is read once per connection and cached
        (:attr:`_basic_channel`): it is a device-global setting, and re-
        reading it cost a full extra request/reply round trip on *every*
        preset selection. Pass ``channel`` explicitly to bypass the cache,
        or call :meth:`forget_basic_channel` if it may have been changed
        from the front panel mid-session.

        **This does NOT check ``MIDIGLO_RCV_PROGRAM_CHANGE`` (id 220).** If
        the device has Program Change reception switched off it will ignore
        these messages and this call is silently a no-op -- checking would
        cost another round trip per selection, so callers that care must
        read id 220 themselves. (An earlier version of this docstring
        claimed the check was done here; it never was.)
        """
        if not 0 <= preset <= 16383:
            raise ValueError(f"preset {preset} out of MIDI bank/program range")
        if channel is None:
            channel = self.basic_channel()
        if not 0 <= channel <= 15:
            raise ValueError(f"channel {channel} out of range 0-15")
        bank, program = divmod(preset, 128)
        # Live-caught: unlike SysEx (throttled by ThrottledOut), plain
        # channel messages pass through with no gap at all -- sending these
        # three back-to-back with zero delay got Bank Select and/or Program
        # Change dropped or misprocessed (commanding preset 52 landed on
        # P049 once, then a second Program Change alone did nothing at
        # all). SEND_GAP between each message, same value already used for
        # SysEx, fixed it -- confirmed landing on the exact commanded
        # preset every time after.
        self._send(bytes([0xB0 | channel, 0, (bank >> 7) & 0x7F]))   # Bank Select MSB
        time.sleep(SEND_GAP)
        self._send(bytes([0xB0 | channel, 32, bank & 0x7F]))         # Bank Select LSB
        time.sleep(SEND_GAP)
        self._send(bytes([0xC0 | channel, program]))                 # Program Change
        # The trailing gap is NOT redundant, despite following the last
        # message here: ThrottledOut only tracks the timestamp of SysEx it
        # sent, so a SysEx issued immediately after this Program Change
        # would see a stale `_last` and go out with no gap at all. This
        # keeps that case covered too.
        time.sleep(SEND_GAP)

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
