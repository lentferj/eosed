# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Original work. GPL-2.0-or-later.
#
# eosed is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# eosed is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.

"""The local settings cache: ports, and this editor's own preferences.

This used to live inside :mod:`eos.bridge`, together with a private
read-modify-write TOML store and five helpers behind it. Both have moved:
the store is :class:`vinsynlib.config.Settings`, and this module is what
:mod:`eos.bridge` re-exports, so ``from eos import bridge as b;
b.load_compact_view(path)`` keeps working and :mod:`eosed.app` keeps
importing it from ``bridge``.

**THE BUG THIS MOVE FIXES, which is why it is worth naming here rather than
only in the commit message.** The writer this file replaces emitted a string
value as::

    lines.append(f'{key} = "{value}"')

No escaping at all. A MIDI port name is not a name anyone chose -- ALSA
client names are whatever the device reports -- so a port called
``"Motif"`` or any string containing a double quote produced a file that is
not TOML at all. The failure was invisible for three reasons at once:

* The writer **refuses to overwrite a file it cannot parse**, and that
  refusal is correct and deliberate. So the first bad write was the last
  one: every later run read nothing and wrote nothing, and said nothing,
  until somebody deleted the file by hand. The cache could not heal, and
  nothing said why it could not.
* `config.toml` is gitignored, so the corrupt file never appeared in
  ``git status``.
* Nothing checked it. It is a cache, on purpose, and a cache is by
  definition not worth a test -- until the one file that is never worth a
  test is the one that cannot be repaired.

Everything the library writes is escaped, including control characters that
have no TOML escape of their own and become ``\\uXXXX``. A control character
in a port name is obscure; a quote in one is not, and either one used to
end the settings cache permanently.

Everything else that was here is the family's now, and was worth moving for
the same reason: read-modify-write so unrelated keys survive each other's
saves, the refusal above, and swallowing only :class:`OSError` -- a
read-only directory or a full disk, where forgetting a preference beats
refusing to run, while anything else is a bug and should be heard.

What stays here is what only this editor knows, and it is a list of
thin wrappers over :meth:`Settings.read` and :meth:`Settings.update`. They
exist because these are *user-edited* settings rather than remembered ones,
and each one has a value space narrower than TOML's:

``compact_view``
    A bool, and the pane layout it decides.
``cache_all_on_startup``, ``cache_structure_on_startup``,
``send_pc_on_preset_select``
    Bools. The first two default OFF and the third ON; the reason is in
    :mod:`eosed.app`, where they are read, because a full-depth sweep is
    measured at 1 h 44 m on a large commercial bank.
``cache_depth``
    One of "names", "structure", "full". Anything else reads as unset,
    rather than as a depth nobody can honour.
``sample_usage_early_stop``
    An int *or* the literal string "fullscan", which disables the
    early-stop heuristic entirely. Two types in one key is the awkward case
    and is why this is not simply a bool.

None of these is ever written by the application. They are hand-edited,
which is exactly why the reader is strict about the type: a typo in
``config.toml`` should read as "unset", and fall back to the documented
default, rather than as a value the sweep machinery then acts on.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from vinsynlib.config import Settings

#: What `sample_usage_early_stop` can hold. Named rather than left as a bare
#: union because the two cases are the whole point of the setting, and a
#: reader -- and mypy -- should be able to see that they are exhaustive.
EarlyStop = int | str

__all__ = [
    "CACHE_DEPTHS",
    "DEFAULT_CONFIG_PATH",
    "FULLSCAN",
    "EarlyStop",
    "load_cache_all_on_startup",
    "load_cache_depth",
    "load_cache_structure_on_startup",
    "load_compact_view",
    "load_last_ports",
    "load_sample_usage_early_stop",
    "load_send_pc_on_preset_select",
    "save_last_ports",
    "settings",
]

#: Local settings, gitignored. Named the way this project has always named
#: it; the library calls the same thing ``DEFAULT_PATH``.
DEFAULT_CONFIG_PATH = "config.toml"

#: One store for this application. Exposed so a caller that needs a key no
#: wrapper below covers can use ``settings.update(path, ...)`` rather than
#: growing a second TOML reader beside it.
settings = Settings("eosed", DEFAULT_CONFIG_PATH)

#: The depths a cache sweep can go to. Anything else in the file is not a
#: depth, and reading it as one would start a sweep nobody asked for.
CACHE_DEPTHS = ("names", "structure", "full")

#: The literal that turns the sample-usage early-stop off. A word rather
#: than a number because "0 consecutive no-voices before bailing" is not
#: what anyone means by it -- they mean "do not stop".
FULLSCAN = "fullscan"


# --- the port pair ------------------------------------------------------------


def load_last_ports(path: str = DEFAULT_CONFIG_PATH) -> Optional[Tuple[str, str]]:
    """The send/receive pair that answered last time, if both are known.

    Only when *both* ends are known. A half-remembered pair is not a pair:
    this tool opens one port and reads the other, and an output-only or
    input-only memory is no connection rather than half of one.

    BEHAVIOUR CHANGE, once: the library reads the output port from the key
    ``port``, where this file wrote ``send_port``. An existing eosed
    ``config.toml`` therefore forgets its remembered port on the first run
    after this change, re-probes, and is rewritten in the new shape. That is
    the whole cost and the file is explicitly disposable. Every other key
    here is unchanged.
    """
    return settings.load_ports(path)


def save_last_ports(send_port: str, recv_port: str, path: str = DEFAULT_CONFIG_PATH) -> None:
    """Remember both ports in one write to the file."""
    settings.save_ports(send_port, recv_port, path)


# --- user-edited preferences --------------------------------------------------
#
# Every reader below returns None -- "not set" -- rather than a default of
# its own, and the caller applies the default. That is deliberate: the
# default is a decision about how long an operation takes, and it belongs
# where the operation is launched, next to the comment explaining the
# measurement behind it.


def load_compact_view(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    """Whether the compact two-pane layout was chosen. See eosed.app."""
    value = settings.read(path)[0].get("compact_view")
    return value if isinstance(value, bool) else None


def load_cache_all_on_startup(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    """Run a `cache_depth`-deep sweep on connect. Defaults to OFF.

    At the default "full" depth this is measured at 1 h 44 m on a large
    commercial bank (docs/RESOLUTION_NOTES.md §20) — far too much to do
    unprompted, which is why `cache_structure_on_startup` below is the one
    that defaults on.
    """
    value = settings.read(path)[0].get("cache_all_on_startup")
    return value if isinstance(value, bool) else None


def load_cache_structure_on_startup(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    """Run a "structure"-depth sweep on connect. Defaults to OFF.

    Opt-in like its `cache_all_on_startup` sibling: at 23 min on a large
    bank it is far cheaper than "full" (1 h 44 m) but still much too long to
    impose on someone who launched the app to look at one preset. Worth
    turning on for a session you know will involve a lot of browsing —
    afterwards preset selection, bank paging and `u` cost no MIDI at all.
    Cancellable with `escape`, and it announces its estimate rather than
    starting silently.
    """
    value = settings.read(path)[0].get("cache_structure_on_startup")
    return value if isinstance(value, bool) else None


def load_cache_depth(path: str = DEFAULT_CONFIG_PATH) -> Optional[str]:
    """One of :data:`CACHE_DEPTHS`, or None if unset or unrecognised."""
    value = settings.read(path)[0].get("cache_depth")
    if isinstance(value, str) and value.strip().lower() in CACHE_DEPTHS:
        return value.strip().lower()
    return None


def load_sample_usage_early_stop(path: str = DEFAULT_CONFIG_PATH) -> Optional[EarlyStop]:
    """An int threshold, the string "fullscan", or None if unset/invalid.

    The two-types-in-one-key case. The sweep bails after this many
    consecutive no-voices presets, and "fullscan" turns that off and sweeps
    the complete range. Neither can be expressed as the other: 0 would mean
    "bail on the first empty slot", which is not what anyone means by
    "do not stop".
    """
    value = settings.read(path)[0].get("sample_usage_early_stop")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lower() == FULLSCAN:
        return FULLSCAN
    return None


def load_send_pc_on_preset_select(path: str = DEFAULT_CONFIG_PATH) -> Optional[bool]:
    """Send a plain Program Change when a preset is selected. Defaults on.

    PRESET_SELECT (id 223, the editor protocol's own selector) is
    spec-stated to be "independent of the front panel's own selection" --
    selecting a preset that way never makes the device redraw its own LCD
    (see DISCLAIMER.md). A plain MIDI Program Change is a completely
    different, ordinary channel voice message (not part of this SysEx
    protocol at all) that genuinely does. Cheap, and no real downside for a
    session actually being played on the hardware.
    """
    value = settings.read(path)[0].get("send_pc_on_preset_select")
    return value if isinstance(value, bool) else None


# --- helpers ------------------------------------------------------------------


def read_all(path: str) -> Dict[str, object]:
    """Every key in the file, for a caller that needs more than one.

    The status is deliberately not surfaced: a reader that cannot act on a
    parse failure gets no settings, which is the same answer as an absent
    file, and the writer -- which *can* act -- is the one that refuses.
    """
    return dict(settings.read(path)[0])
