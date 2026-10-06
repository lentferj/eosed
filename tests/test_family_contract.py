# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Original work. GPL-2.0-or-later.

"""eosed keeps the contract the other projects in the family keep.

Every check below is the same one, run against this program rather than
written out again here. The reasons are in docs/UX-SPEC.md section 5 and in
the library: what drifted was never a bug anyone chose, it was a copy that
nobody had a second copy to compare against.

**eosed is an EDITOR, not a browser, and the checks say so.** It has no
favourites store -- there is nothing in an editor to favourite -- so it is
not asked for `f`, `F`, `t` or `n`, and offering them would be a key that
does nothing. It selects with this protocol's own PRESET_SELECT rather than
a program change, so it has no channel; and there is no "select on the
unit" concept to reach with one. Those three are `False` here and in s3ked,
the other editor, and passing them explicitly is what stops a browser-tier
key from being silently demanded of an editor later.
"""

import pytest

from eos.terms import TERMS
from eosed.app import PRESS_NAMES, EosedApp, build_parser
from eosed.cli import build_parser as build_cli_parser
from eosed.demo import DemoBridge
from vinsynlib import conformance, keys


def _subcommand_for(parser, typed: str) -> str:
    """The command name argparse would dispatch for `typed`.

    Not `parse_args` -- that needs every other required argument too, and
    this is about the alias table rather than about the rest of the parser.
    """
    args = parser.parse_args([typed])
    return args.command


def _app() -> EosedApp:
    """An app instance, for the one check that needs its methods.

    `check_bindings` reads the class; `_legend_blocks` is an instance method
    because that is where BINDINGS is in scope. A --demo app opens no port
    and touches no local state, which is what makes constructing one safe
    here.
    """
    return EosedApp(DemoBridge(), allow_write=True, demo=True)


def test_the_editor_flags_match_the_family() -> None:
    # --channel is deliberately not required: PRESET_SELECT is this
    # protocol's own selector, not a program change, so there is no channel
    # to send one on. `forbidden` states that rather than leaving it out.
    problems = conformance.check_flags(
        build_parser(),
        required=("port", "device-id", "timeout", "config", "demo", "allow-write"),
        forbidden=("channel", "favorites", "scan"),
    )
    assert not problems, "\n".join(problems)


def test_the_shared_editor_keys_are_bound() -> None:
    assert not conformance.check_bindings(
        EosedApp, tier="editor", favourites=False, channel=False, select=False
    )


def test_the_legend_is_generated_from_the_bindings() -> None:
    """Not checked against the shared browser legend, and the reason matters.

    `conformance.check_legend` compares a legend against
    `keys.CANONICAL_LEGEND`, which is the *browser* legend: it expects `f
    favourite` and `/ search`, neither of which exists in an editor. There is
    nothing to check it against here, and inventing an editor legend in the
    library to check against would be a second list to keep in step.

    What can be checked -- and is -- is that the blocks are what
    `vinsynlib.keys.legend_from_bindings` produces from these bindings. Both
    the legend at the bottom of the screen and the `? help` screen read that
    one function, so they cannot disagree with each other, and neither can
    disagree with the library.
    """
    app = _app()
    assert app._legend_blocks() == keys.legend_from_bindings(
        EosedApp.BINDINGS, press_names=PRESS_NAMES
    )


def test_the_help_screen_and_the_legend_are_one_list() -> None:
    """`? help` must not be a second copy of the key list.

    This is the whole reason the help screen is assembled from
    `_legend_blocks` rather than written out. A hand-written list is a second
    list to keep in step with BINDINGS, and it drifts; here it is asserted
    that both come from the same call, so a binding added to one cannot be
    missing from the other.
    """
    app = _app()
    blocks = app._legend_blocks()
    assert blocks, "the legend is empty; both screens would be blank"
    # Every block is "key description" -- one space, and the key has no
    # space in it -- which is what makes them printable as a help list too.
    assert all(b.count(" ") >= 1 for b in blocks), blocks


def test_no_favourites_key_is_offered() -> None:
    """The absence is the point, so it is asserted rather than assumed.

    eosed is an editor and has no favourites database. docs/UX-SPEC.md
    section 1 says the keys and flags for favouriting are "absent rather
    than present and broken" -- which cannot be checked by looking for what
    is there, because nothing is.
    """
    from textual.binding import Binding

    bound = {b.key for b in EosedApp.BINDINGS if isinstance(b, Binding)}
    for key in ("f", "F", "t", "n"):
        assert key not in bound, (
            f"{key} is bound in an editor with no favourites store; the spec "
            f"says the keys are absent rather than present and broken"
        )


def test_the_vocabulary_is_declared() -> None:
    assert not conformance.check_terms(TERMS)


def test_both_front_ends_agree_on_the_shared_flags() -> None:
    """`eosed` and `eoscli` are two front doors to one program.

    Scoped to the family's canonical flags: --panel-render is eosed's own
    and need not be on both. Both parsers are built by
    `vinsynlib.cli.add_common_arguments`, so what this catches is the two
    call sites being passed different words.
    """
    from vinsynlib import spec

    app_dests = {a.dest for a in build_parser()._actions}
    cli_dests = {a.dest for a in build_cli_parser()._actions}
    canonical = {f.name.replace("-", "_") for f in spec.CANONICAL_FLAGS}
    missing = sorted(canonical & app_dests - cli_dests)
    # --allow-write and --yes are absent from eoscli on purpose: they exist
    # on its `send` subcommand, which is the only command that writes, and a
    # global copy would be overwritten by the subparser's default. So
    # "missing" here means those two and nothing else.
    assert set(missing) <= {"allow_write", "yes"}, missing


@pytest.mark.parametrize("name", ["hardware", "inquire"])
def test_the_hardware_command_has_both_spellings(name: str) -> None:
    """`hardware` is canonical, `inquire` still works and reaches the handler.

    The spec renamed this command because in another program `config` meant
    "which ROMs are fitted" while the --config flag beside it meant the
    settings file. In THIS program `config` is a genuinely different command
    -- installed options and RAM sizes -- so it is deliberately not an alias
    here, and this test says so rather than leaving it to be discovered by
    somebody typing `eoscli config` and getting the wrong answer.

    The dispatch assertion is the sharp half, and it is there because of a
    bug this test found on its first run: argparse puts the SPELLED name in
    `args.command`, so a dispatch table with one `hardware` entry made every
    alias a KeyError. Aliases work, or they do not.
    """
    from eosed.cli import _COMMANDS, cmd_inquire

    assert _subcommand_for(build_cli_parser(), name) == name
    assert _COMMANDS[name] is cmd_inquire
