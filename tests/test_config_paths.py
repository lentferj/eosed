# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Original work. GPL-2.0-or-later.

"""The suite must not write the application's config into the checkout.

`eos.config.DEFAULT_CONFIG_PATH` is the relative string `"config.toml"`.
That is the right default for the application -- a disposable per-checkout
cache of which port answered last, gitignored -- and the wrong thing for a
test, which would drop the file into whatever directory pytest was started
from.

Being gitignored is what makes this worth a test rather than a habit: the
file never appears in `git status`, so the only evidence is somebody
noticing it sitting next to the source.

The first two checks are the family's, one call each into
`vinsynlib.devchecks`. They were this file's own AST walk in each project.

The rest are eosed's, and they are the ones this project needed: it is the
one whose settings writer was broken.
"""

import ast
import os

import pytest

# Imported as a bare `config` on purpose. `devchecks.config_saves_without_path`
# looks for calls of the form `config.save_*` where `config` is a plain Name,
# so a test module that imports the settings module under any other name is
# invisible to the check and passes it vacuously. It was that way in this
# project before -- the suite called `bridge_mod.save_*` throughout and the
# "no test writes config.toml into the checkout" guard was matching nothing.
from eos import config
from vinsynlib import devchecks

#: The two packages this project owns. `vinsynlib` appears in the
#: sibling-import check below, where the library itself is allowed.
OWN = ("eos", "eosed")


# --- the family's two checks ------------------------------------------------


def test_every_config_save_in_the_suite_names_its_file() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    offenders = devchecks.config_saves_without_path(here)
    assert not offenders, (
        f"{offenders} save to config.DEFAULT_CONFIG_PATH, which is relative "
        f"to the working directory. Pass a tmp_path."
    )


def test_the_check_has_something_to_check() -> None:
    """Guard against the search passing because it matched nothing.

    Counts every `config.save_*` in the suite, offending or not:
    `devchecks.config_saves_without_path` returns only the offenders, so
    "none" from it means nothing at all on its own.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    saves = 0
    for _name, tree in devchecks.iter_test_sources(here):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("save_")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "config"
            ):
                saves += 1
    assert saves, "no config.save_* calls found; the check is vacuous"


def test_this_project_imports_no_sibling() -> None:
    """A sibling project's package is not installed beside this one.

    This module carries the history: eosed's settings store was the oldest
    of the family's -- it was the source the other six were ported from --
    and a port is exactly where a module-level `from eos import config`
    turns into `from s3k import config`. It has happened in this family:
    emorphed had a function importing `nano.config`, which is nanosyned's
    package and is not installed beside it, and it raised ImportError the
    moment `--config` was used.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    offenders = []
    for pkg in OWN:
        directory = os.path.join(root, pkg)
        for name in os.listdir(directory):
            if name.endswith(".py"):
                offenders += devchecks.foreign_imports(
                    os.path.join(directory, name), own=(*OWN, "vinsynlib")
                )
    assert not offenders, offenders


# --- the bug this project had -----------------------------------------------


def test_a_quote_in_a_port_name_does_not_corrupt_the_cache(tmp_path):
    """THE regression. A port name is whatever ALSA reports.

    The writer this module replaced emitted ``f'{key} = "{value}"'`` with no
    escaping, so a port name containing a double quote produced a file that
    is not TOML. Three things then happened at once and none of them said
    anything:

    * the writer **refuses to overwrite a file it cannot parse**, which is
      correct and deliberate -- so that first bad write was also the last
      one, and every later run read nothing and wrote nothing;
    * the file is gitignored, so it never appeared in `git status`;
    * nothing read it back, because it is a cache and a cache is by
      definition not worth a test.

    The result is a settings cache that cannot heal without somebody
    deleting the file by hand, with no symptom to point at the cause. This
    is the test that would have caught it, and it is here rather than in the
    library because *this* is where the bug was.
    """
    import tomllib

    path = str(tmp_path / "config.toml")
    awkward = 'MOTIF Synth:1 ("USB")'
    config.save_last_ports(awkward, awkward, path)

    with open(path, "rb") as handle:
        tomllib.load(handle)  # must not raise
    assert config.load_last_ports(path) == (awkward, awkward)


def test_a_port_name_with_a_backslash_or_a_control_character_survives(tmp_path):
    """The same bug, with less obvious characters in it.

    A backslash ends a TOML escape, so it is the second character that turns
    a file that looks fine into one that is not. A literal tab or newline is
    not valid inside a TOML basic string at all, and a control character with
    no escape of its own has to be written as \\uXXXX rather than embedded.
    None of these is exotic in a name some driver chose.
    """
    import tomllib

    path = str(tmp_path / "config.toml")
    awkward = "back\\slash\ttab\nnewline\x01control"
    config.save_last_ports(awkward, awkward, path)

    with open(path, "rb") as handle:
        parsed = tomllib.load(handle)
    assert parsed["port"] == awkward, repr(parsed["port"])


def test_the_cache_heals_after_a_bad_write_rather_than_staying_broken(tmp_path):
    """The half of the bug that matters most, and the part that is not TOML.

    A file that cannot be parsed is left alone -- that refusal is right, and
    losing a hand-edited preference to a blind overwrite is worse. What it
    must not do is make every *later* save a no-op as well. A user whose
    cache went bad this way should lose the remembered port once and get it
    back, not be stuck reading nothing for ever.
    """
    import tomllib

    path = tmp_path / "config.toml"
    # Written by a build that escaped nothing, or typed by hand.
    path.write_text('port = "MOTIF\nrecv_port = "MIDI 1\n', encoding="utf-8")
    assert config.load_last_ports(str(path)) is None, "must refuse, not guess"

    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(path.read_text(encoding="utf-8"))

    # The bad file is not overwritten -- and says so.
    before = path.read_text(encoding="utf-8")
    config.save_last_ports("Good Out", "Good In", str(path))
    assert path.read_text(encoding="utf-8") == before

    # Once the user deletes it, saving works and the value round-trips. This
    # is the property that was missing: before, this last line was where
    # somebody had to intervene by hand.
    path.unlink()
    config.save_last_ports("Good Out", "Good In", str(path))
    assert config.load_last_ports(str(path)) == ("Good Out", "Good In")


def test_a_toml_boolean_is_not_a_setting(tmp_path):
    """`isinstance(True, int)` is true, and every setting here is narrower.

    `sample_usage_early_stop` reads an int *or* the string "fullscan", and
    `cache_depth` reads one of three words. A hand-edited `cache_depth =
    true` must read as unset rather than as something the sweep machinery
    would act on, because these settings decide how long an operation takes
    on hardware the user is standing in front of.
    """
    path = str(tmp_path / "config.toml")
    for key in (
        "compact_view",
        "cache_all_on_startup",
        "cache_structure_on_startup",
        "send_pc_on_preset_select",
    ):
        config.settings.update(path, **{key: True})
    # All four are bools, so that one is a legitimate True -- the point is
    # the non-bool shapes below.
    assert config.load_compact_view(path) is True
    assert config.load_cache_all_on_startup(path) is True

    config.settings.update(path, cache_depth=True, sample_usage_early_stop=True)
    assert config.load_cache_depth(path) is None, "true is not a depth"
    assert config.load_sample_usage_early_stop(path) is None, "true is not a threshold"


def test_an_unknown_cache_depth_reads_as_unset(tmp_path):
    """A hand-typed depth that is not one of the three starts nothing.

    The default in `eosed.app` is applied by the caller when this returns
    None. Reading an unrecognised word as itself would start a sweep nobody
    asked for at a depth nothing implements.
    """
    path = str(tmp_path / "config.toml")
    config.settings.update(path, cache_depth="STRUCTURE ")
    assert config.load_cache_depth(path) == "structure"
    config.settings.update(path, cache_depth="everything")
    assert config.load_cache_depth(path) is None


def test_the_settings_store_is_the_shared_one() -> None:
    """eos.config is a binding, not a copy.

    Stated as a test rather than left to review: the failure this guards
    against is somebody re-adding a private TOML reader beside the shared
    one, which is invisible -- the code works, the tests pass, and the copies
    start drifting apart again from a project that looks consistent. The
    escaping tests above are the ones that would fail first, and only for
    this file's own paths.
    """
    from vinsynlib.config import Settings

    assert isinstance(config.settings, Settings)
    assert config.settings.app_name == "eosed"
