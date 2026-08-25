# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Original work. GPL-2.0-or-later.

"""eoscli — read-only command-line explorer for the EOS editor protocol.

Every subcommand here is documented in README.md. ``--demo`` runs every
command against :class:`eosed.demo.DemoBridge` and never opens a MIDI
port, per the project's synthetic-first hardware rule (see CLAUDE.md).
"""

from __future__ import annotations

import argparse
import sys
from typing import Tuple

from eos import bridge as bridge_mod
from eos import messages as m
from eos import params as p
from eosed.demo import DemoBridge


def _parse_range(text: str) -> Tuple[int, int]:
    lo, _, hi = text.partition("-")
    if not hi:
        raise argparse.ArgumentTypeError(f"expected LOW-HIGH, got {text!r}")
    return int(lo), int(hi)


def _build_bridge(args: argparse.Namespace) -> "bridge_mod.EosBridge":
    if args.port:
        # standard() addresses one device directly, so it needs a concrete id;
        # autodetect treats None as "whichever answers" and uses it to pick
        # between machines.
        return bridge_mod.EosBridge.standard(
            args.port,
            device_id=(m.DEFAULT_DEVICE_ID if args.device_id is None else args.device_id),
            timeout=args.timeout)
    return bridge_mod.EosBridge.autodetect(
        device_id=args.device_id, timeout=args.timeout, config_path=args.config,
        on_try=lambda name: print(f"  trying {name} ...", file=sys.stderr))


def cmd_ports(args: argparse.Namespace) -> None:
    # 'ports' is the first thing a new user runs to see whether anything is
    # wired up, so it answers rather than traces back when the host has no
    # MIDI subsystem at all -- but it says *which* of the two situations it
    # is, since "no ports" and "no ALSA sequencer" need very different
    # fixes.
    try:
        ins, outs = bridge_mod.list_ports()
        both = bridge_mod.bidirectional_ports()
    except bridge_mod.MidiUnavailable as exc:
        ins = outs = both = []
        print(f"warning: {exc}", file=sys.stderr)
    print("MIDI inputs:")
    for name in ins:
        print(f"  {name}")
    print("MIDI outputs:")
    for name in outs:
        print(f"  {name}")
    print("\nBidirectional (standard-rig candidates):")
    for name in both:
        print(f"  {name}")


def cmd_inquire(args: argparse.Namespace, bridge) -> None:
    reply = bridge.inquire()
    print(f"device id      : {reply.device_id}")
    print(f"family code    : {reply.family_code}")
    print(f"member code    : {reply.member_code}")
    print(f"model          : {reply.model or 'unknown'}")
    print(f"firmware       : {reply.revision}")


def cmd_config(args: argparse.Namespace, bridge) -> None:
    cfg = bridge.configuration()
    flags = cfg.option_flags()
    print(f"RAM            : {cfg.ram_mb} MB")
    print(f"128 voices     : {flags.voices_128}")
    print(f"FX card        : {flags.fx_card}")
    print(f"MIDI card      : {flags.midi_card}")
    print(f"Octopus card   : {flags.octopus_card}")
    print(f"Digital I/O    : {flags.digital_io}")
    try:
        ext = bridge.extended_configuration()
    except TimeoutError:
        return
    ext_flags = ext.option_flags()
    print(f"ROM            : {ext.rom_mb} MB")
    print(f"Flash          : {ext.flash_mb} MB")
    print(f"Preset Flash   : {ext_flags.preset_flash}")
    print(f"ADAT I/O       : {ext_flags.adat_io}")


def cmd_memory(args: argparse.Namespace, bridge) -> None:
    preset_mem = bridge.preset_memory()
    sample_mem = bridge.sample_memory()
    print(f"Preset memory  : {preset_mem.free_kb} / {preset_mem.total_kb} kB free")
    print(f"Sample memory  : {sample_mem.total_mb} MB total, "
          f"~{sample_mem.free_10kb * 10} kB free")


def cmd_catalog(args: argparse.Namespace, bridge) -> None:
    lo, hi = args.range
    preset_range = range(lo, hi + 1)

    def progress(n: int) -> None:
        print(f"\r  scanning preset {n}/{hi}...", end="", file=sys.stderr)

    names = bridge.catalog_presets(preset_range, on_progress=progress if args.progress else None)
    if args.progress:
        print(file=sys.stderr)
    for number in sorted(names):
        print(f"{number:4d}  {names[number]}")


def cmd_get(args: argparse.Namespace, bridge) -> None:
    key = int(args.param) if args.param.lstrip("-").isdigit() else args.param
    param = p.lookup(key)
    value = bridge.get_parameter(param.id)
    line = f"{param.name} (id {param.id}) = {p.describe_value(param, value)}"
    if param.unit:
        line += f" {param.unit}"
    print(line)
    try:
        rng = bridge.get_parameter_range(param.id)
        print(f"  device range   : {rng.minimum} .. {rng.maximum} (default {rng.default})")
    except (TimeoutError, LookupError, ValueError):
        # ValueError too: a device that answers with some other frame (or
        # nothing parseable) is exactly the case the static fallback exists
        # for, but it used to escape to main() and abort the command after
        # the value had already been printed.
        print(f"  static range   : {param.minimum} .. {param.maximum} (spec, not device-verified)")


def cmd_dump(args: argparse.Namespace, bridge) -> None:
    if args.new_format:
        header, data = bridge.dump_preset_new(args.preset)
        print(f"NEW format dump: preset {header.preset}, {len(data)}/{header.total_bytes} bytes")
    else:
        data = bridge.dump_preset_old(args.preset)
        print(f"OLD format dump: preset {args.preset}, {len(data)} bytes")
    with open(args.output, "wb") as handle:
        handle.write(data)
    print(f"wrote {args.output}")


def cmd_send(args: argparse.Namespace, bridge) -> None:
    """Send a preset file back to the device -- the only whole-slot write here.

    Arm-then-fire, like the Master utilities: ``--allow-write`` arms it and a
    typed confirmation fires it. And it LOOKS AT THE TARGET first -- an
    overwrite that does not tell you what it is about to destroy is how a
    reference preset goes missing without anyone noticing which one it was.
    """
    with open(args.file, "rb") as handle:
        data = handle.read()
    if len(data) < 2:
        raise SystemExit(f"{args.file}: too short to be a preset dump")

    came_from = bridge_mod.EosBridge.dump_target(data)
    preset = came_from if args.preset is None else args.preset
    if preset != came_from:
        data = bridge_mod.EosBridge.retarget_dump(data, preset)

    print(f"  file           : {args.file} ({len(data)} bytes)")
    print(f"  dump was for   : preset {came_from}")
    print(f"  will overwrite : preset {preset}")
    try:
        print(f"  that slot now  : {bridge.get_preset_name(preset)!r}")
    except Exception as exc:                     # noqa: BLE001 - advisory only
        print(f"  that slot now  : unreadable ({exc.__class__.__name__}) -- "
              f"proceed only if you know what is there")

    if not args.allow_write:
        raise SystemExit(
            "refusing: this overwrites the whole preset slot. Re-run with "
            "--allow-write once you have checked the target above.")
    if not args.yes:
        typed = input(f"  type the preset number {preset} to confirm: ").strip()
        if typed != str(preset):
            raise SystemExit("not confirmed; nothing sent")

    written = bridge.send_preset_old(data, allow_write=True)
    print(f"  sent           : preset {written}, {len(data)} bytes")
    try:
        print(f"  slot now reads : {bridge.get_preset_name(written)!r}")
    except Exception:                            # noqa: BLE001
        print("  slot now reads : (name read-back failed)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eoscli", description=__doc__)
    parser.add_argument("--port", help="MIDI port name (default: autodetect via Device Inquiry)")
    parser.add_argument("--device-id", type=int, default=None,
                        help="SysEx device id. With autodetect, selects WHICH device to "
                             "use when several are connected; the EOS manual says each "
                             "unit should have a different id. Default: whichever answers")
    parser.add_argument("--timeout", type=float, default=bridge_mod.DEFAULT_TIMEOUT,
                        help="seconds to wait for any one reply "
                             "(default: %(default)s)")
    parser.add_argument("--config", default=bridge_mod.DEFAULT_CONFIG_PATH, metavar="FILE",
                        help="local settings file: caches the last successful autodetect port "
                             "pair, and holds the view/cache-sweep/program-change "
                             "preferences (default: config.toml; ignored if absent)")
    parser.add_argument("--demo", action="store_true",
                        help="use a canned in-memory device; never opens a MIDI port")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list MIDI ports")
    sub.add_parser("inquire", help="identify the connected EOS device")
    sub.add_parser("config", help="installed options and RAM/ROM/Flash sizes")
    sub.add_parser("memory", help="Preset/Sample memory totals and free space")

    catalog = sub.add_parser("catalog", help="list preset names over a range")
    catalog.add_argument("--range", dest="range", type=_parse_range, default=(0, 127),
                         help="preset range LOW-HIGH (default: 0-127)")
    catalog.add_argument("--progress", action="store_true", help="show scan progress on stderr")

    get = sub.add_parser("get", help="read one parameter's current value")
    get.add_argument("param", help="parameter id (int) or name (e.g. E4_PRESET_VOLUME)")

    dump = sub.add_parser("dump", help="dump a preset to a file")
    dump.add_argument("preset", type=int)
    dump.add_argument("output", help="output file path")
    dump.add_argument("--new-format", action="store_true", help="use the NEW dump format")

    send = sub.add_parser("send", help="send a preset file to the device (OVERWRITES a slot)")
    send.add_argument("file", help="preset dump file, as written by `dump`")
    send.add_argument("--preset", type=int, default=None,
                      help="destination preset (default: the one the dump came from)")
    send.add_argument("--allow-write", action="store_true",
                      help="arm the write; without it the command only reports the target")
    send.add_argument("--yes", action="store_true",
                      help="skip the typed confirmation (for scripts that have already asked)")

    return parser


_COMMANDS = {
    "inquire": cmd_inquire,
    "config": cmd_config,
    "memory": cmd_memory,
    "catalog": cmd_catalog,
    "get": cmd_get,
    "dump": cmd_dump,
    "send": cmd_send,
}


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ports":
        cmd_ports(args)
        return

    try:
        bridge = DemoBridge() if args.demo else _build_bridge(args)
    except RuntimeError as exc:
        sys.exit(f"error: {exc}")

    try:
        _COMMANDS[args.command](args, bridge)
    except (LookupError, TimeoutError, ValueError) as exc:  # KeyError is a LookupError
        sys.exit(f"error: {exc}")
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
