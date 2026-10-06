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

"""What the E-mu calls things, declared once.

**The instrument's word is the instrument's.** The E4XT's own panel and
manual say PRESET and BANK, so those are the words every string a user reads
uses here -- the pane headings, the CLI help, the status line, the README.

The wire's word is different and stays in the code that builds wire
messages. On the wire this is a preset number selected by the editor
protocol's own PRESET_SELECT, not a program change at all -- see
:mod:`eos.messages` -- and that selector is a different number from anything
in the user's vocabulary. That translation is not a naming exercise, so it
stays where it is visible.

**A preset is not a voice, and a voice is not a sample.** All three exist in
this protocol and the three panes are exactly them:

* a **preset** is what plays: a set of voices with envelopes, filters and a
  sample assignment. It is what the panel calls a PRESET, and it is the
  instrument's word for one stored sound.
* a **voice** is one voice inside the selected preset, and its parameters
  are addressed only while that voice is selected.
* a **sample** is the audio. The Samples pane is a *derived* view of which
  sample(s) the current selection actually references, not a browsable bank
  -- there is no generic parameter access to a sample's own loop points or
  root key (docs/RESOLUTION_NOTES.md §10).

Conflating them is how a program ends up editing a sample's loop points when
it meant to edit a voice's filter, so the third of them is named in `own`
rather than being left to a reader to infer.

A **flash card** is the other area presets can live in, and it is not a
bank: a card is removable media holding banks. Both words are in `own` for
that reason -- a tool that said "this preset is in bank 3" about a card
would be describing something that cannot be said.
"""

from __future__ import annotations

from vinsynlib.terms import Terminology, register

__all__ = ["TERMS"]

TERMS = Terminology(
    app_name="eosed",
    sound="preset",
    container="bank",
    device="Ensoniq E4XT",
    own={
        # The other two things this protocol addresses, and the three panes
        # are exactly them. See the module docstring.
        "voice": "voice",
        "sample": "sample",
        # Removable media holding banks. Not a bank, and not a card-shaped
        # bank: the distinction is why `flush` and `preset select` mean
        # different things here.
        "flash": "flash card",
        # A preset-slot page of the editing buffer. The panel's own word, and
        # the one the destructive Master operations act on.
        "location": "location",
        # What an unused sample slot reads back as. Documented in
        # eosed/app.py (_EMPTY_SAMPLE_NAME) because it is a fact about this
        # generation of hardware and not a family concept.
        "empty sample": "Empty Sample",
    },
)

#: Registered at import so the family's registry knows what this tool calls
#: its concepts. Registration rather than a monkeypatched module global: a
#: library cannot know the name of the program using it, and passing it in
#: is honest where patching is global.
register(TERMS)
