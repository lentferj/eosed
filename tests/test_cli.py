# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# --demo mode never opens a MIDI port — synthetic only.

import pytest

from eos import bridge as bridge_mod
from eos import messages as m
from eosed import cli
from eosed.demo import DemoBridge


def test_demo_inquire(capsys):
    cli.main(["--demo", "inquire"])
    out = capsys.readouterr().out
    assert "E4XT" in out
    assert "4.00" in out


def test_demo_config(capsys):
    cli.main(["--demo", "config"])
    out = capsys.readouterr().out
    assert "RAM" in out
    assert "MB" in out


def test_demo_memory(capsys):
    cli.main(["--demo", "memory"])
    out = capsys.readouterr().out
    assert "Preset memory" in out
    assert "Sample memory" in out


def test_demo_catalog_default_range(capsys):
    cli.main(["--demo", "catalog"])
    out = capsys.readouterr().out
    assert "Demo Grand Piano" in out
    assert "Demo Warm Pad" in out
    assert "Demo Bass" in out


def test_demo_catalog_narrow_range_excludes_names(capsys):
    cli.main(["--demo", "catalog", "--range", "2-4"])
    out = capsys.readouterr().out
    assert "Demo Grand Piano" not in out  # preset 0, outside 2-4
    assert out.strip() == ""  # nothing in [2,4] in the demo catalog


def test_demo_get_by_name(capsys):
    cli.main(["--demo", "get", "E4_PRESET_VOLUME"])
    out = capsys.readouterr().out
    assert "E4_PRESET_VOLUME" in out
    assert "dB" in out
    assert "device range" in out


def test_demo_get_by_id(capsys):
    cli.main(["--demo", "get", "183"])
    out = capsys.readouterr().out
    assert "MASTER_TUNING_OFFSET" in out


def test_demo_get_unknown_param_exits_nonzero(capsys):
    # sys.exit(str) sets .code to the message; it's only printed to stderr by
    # the interpreter's top-level handler, which pytest.raises bypasses — so
    # assert on the SystemExit's code/message directly, not captured stderr.
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--demo", "get", "NOT_A_PARAM"])
    assert excinfo.value.code is not None
    assert "error" in str(excinfo.value.code).lower()


def test_demo_dump_old_format(tmp_path, capsys):
    output = tmp_path / "preset0.bin"
    cli.main(["--demo", "dump", "0", str(output)])
    out = capsys.readouterr().out
    assert "OLD format dump" in out
    data = output.read_bytes()
    # OLD payload leads with the preset number, then the name — the layout
    # confirmed live against a real E4XT Ultra dump (RESOLUTION_NOTES §7).
    # This previously asserted a name-first layout, which is the NEW format's
    # shape, and so silently locked in a demo fixture that disagreed with
    # every real capture.
    assert data[:2] == bytes(m.encode_u14(0))
    assert data[2:18] == b"Demo Grand Piano"


def test_demo_dump_new_format(tmp_path, capsys):
    output = tmp_path / "preset0_new.bin"
    cli.main(["--demo", "dump", "0", str(output), "--new-format"])
    out = capsys.readouterr().out
    assert "NEW format dump" in out
    # NEW carries the preset number in the header, NOT the payload, so this
    # one really does start with the name (spec, "NEW Dump Data Formats").
    assert output.read_bytes()[:16] == b"Demo Grand Piano"


def test_demo_dump_missing_preset_exits_nonzero(tmp_path, capsys):
    output = tmp_path / "nope.bin"
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--demo", "dump", "99", str(output)])
    assert excinfo.value.code != 0


def test_ports_lists_something(capsys):
    # 'ports' never touches --demo (it just enumerates real MIDI ports, the
    # same as k2kremote's convention); it must not raise even on a host with
    # no MIDI hardware.
    cli.main(["ports"])
    out = capsys.readouterr().out
    assert "MIDI inputs:" in out
    assert "MIDI outputs:" in out


def test_ports_survives_a_host_with_no_midi_backend(capsys, monkeypatch):
    # The regression CI found on its first run. The test above asserts this
    # works but cannot verify it on a dev box that *has* an ALSA sequencer:
    # rtmidi enumerates fine there and returns an empty list. A host with no
    # /dev/snd/seq at all (containers, headless runners, WSL without sound)
    # raises out of the rtmidi *constructor* instead, which nothing caught.
    # Simulated here so the case is covered regardless of what the host has.
    import rtmidi

    def no_backend(*args, **kwargs):
        raise SystemError(
            "MidiInAlsa::initialize: error creating ALSA sequencer client object.")

    monkeypatch.setattr(rtmidi, "MidiIn", no_backend)
    monkeypatch.setattr(rtmidi, "MidiOut", no_backend)

    cli.main(["ports"])  # must not raise
    captured = capsys.readouterr()
    assert "MIDI inputs:" in captured.out
    assert "MIDI outputs:" in captured.out
    # ... and must say the subsystem is missing, not imply nothing is plugged in.
    assert "no MIDI backend available" in captured.err


def test_list_ports_distinguishes_no_backend_from_no_ports(monkeypatch):
    # The distinction the exception exists to preserve: an empty result is a
    # legitimate answer ("nothing plugged in"), so it must not be conflated
    # with "this machine cannot do MIDI".
    import rtmidi

    class _EmptyProbe:
        def get_ports(self):
            return []

        def delete(self):
            pass

    monkeypatch.setattr(rtmidi, "MidiIn", _EmptyProbe)
    monkeypatch.setattr(rtmidi, "MidiOut", _EmptyProbe)
    assert bridge_mod.list_ports() == ([], [])

    def no_backend(*args, **kwargs):
        raise SystemError("error creating ALSA sequencer client object.")

    monkeypatch.setattr(rtmidi, "MidiIn", no_backend)
    with pytest.raises(bridge_mod.MidiUnavailable):
        bridge_mod.list_ports()


def test_help_does_not_raise(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0


def test_demo_bridge_never_touches_rtmidi(monkeypatch):
    # Belt-and-braces: fail loudly if DemoBridge ever imports/uses rtmidi.
    import sys
    monkeypatch.setitem(sys.modules, "rtmidi", None)
    bridge = DemoBridge()
    assert bridge.inquire().model == "E4XT"
    bridge.close()


def test_demo_bridges_do_not_share_device_state():
    # DemoBridge's backing dicts used to be module-level, so one instance
    # erasing its bank wiped every other instance's too -- process-wide,
    # order-dependent, and the reason the app tests needed an autouse
    # save/restore fixture to pass at all.
    first = DemoBridge()
    second = DemoBridge()

    first.erase_all_ram_presets()
    first.set_sample_name(0, "Renamed")
    first.set_parameter(1, 42)

    assert first.preset_names == {}
    assert second.preset_names, "second bridge lost its presets to the first"
    assert second.get_sample_name(0) == "Demo Kick"
    assert second.get_parameter(1) == 0

    # ... and a bridge built after the damage still starts from the defaults.
    assert DemoBridge().preset_names == second.preset_names


# --- send: the only whole-slot write, so the guard is the thing under test ---

def test_send_without_allow_write_reports_target_and_refuses(tmp_path, capsys):
    blob = tmp_path / "p.bin"
    cli.main(["--demo", "dump", "0", str(blob)])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["--demo", "send", str(blob)])
    out = capsys.readouterr().out
    assert "will overwrite : preset 0" in out
    assert "that slot now" in out          # it looked at the target first


def test_send_reports_when_retargeted(tmp_path, capsys):
    blob = tmp_path / "p.bin"
    cli.main(["--demo", "dump", "0", str(blob)])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["--demo", "send", str(blob), "--preset", "22"])
    out = capsys.readouterr().out
    assert "dump was for   : preset 0" in out
    assert "will overwrite : preset 22" in out


def test_send_armed_and_confirmed_writes(tmp_path, capsys):
    blob = tmp_path / "p.bin"
    cli.main(["--demo", "dump", "0", str(blob)])
    capsys.readouterr()
    cli.main(["--demo", "send", str(blob), "--allow-write", "--yes"])
    out = capsys.readouterr().out
    assert "sent           : preset 0" in out


def test_send_refuses_when_confirmation_does_not_match(tmp_path, capsys, monkeypatch):
    blob = tmp_path / "p.bin"
    cli.main(["--demo", "dump", "0", str(blob)])
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda *_: "not the number")
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--demo", "send", str(blob), "--allow-write"])
    assert "not confirmed" in str(excinfo.value)
