#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.
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
"""Regenerate the README's screenshots from --demo, headless.

    .venv/bin/python tools/capture_screenshots.py

Every shot runs against DemoBridge, so this needs no hardware and touches no
local config. Re-run it whenever the key legend changes: the legend is
derived from EosedApp.BINDINGS and rendered into every screenshot, so a
keybinding change silently invalidates all of them at once.
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from eosed.app import EosedApp                      # noqa: E402
from eosed.demo import DemoBridge                   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SIZE = (100, 30)
# The 4-pane view splits the same width four ways, so it needs more room
# before columns start truncating ("Demo Grand Pian", "singl").
WIDE = (110, 30)

_GEN_SAMPLE = 38
_VOICE_SELECT = 225
_ZONE_SELECT = 226
_MULTISAMPLE = -1      # signed sentinels, see RESOLUTION_NOTES §18a
_NO_SUCH_VOICE = -2


class ShowcaseBridge(DemoBridge):
    """A demo device with a preset worth photographing: three voices, the
    middle one multisample.

    DemoBridge itself has exactly one single-sample voice per preset, which
    is fine for tests but makes the 4-pane shot pointless — the Voice pane
    shows one row and the Samples pane one sample. Here V1 layers three
    zones over shared samples so the Samples "used by" column has something
    to say (S1 is played by two different voices).
    """

    _VOICES = {
        0: 3,                       # V1 (display) — single sample S3
        1: _MULTISAMPLE,            # V2 — multisample, zones below
        2: 1,                       # V3 — single sample S1, shared with V2
    }
    _ZONES = {0: 1, 1: 2, 2: 5}     # V2's zones -> samples

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._voice = 0
        self._zone = None
        self.sample_names.update({
            1: "E Piano Lo", 2: "E Piano Hi",
            3: "Clav Mid", 5: "Bell Tine"})

    def set_parameter(self, param_id, value):
        if param_id == _VOICE_SELECT:
            self._voice, self._zone = value, None
        elif param_id == _ZONE_SELECT:
            self._zone = value
        else:
            super().set_parameter(param_id, value)

    def get_parameter(self, param_id, *, timeout=None):
        if param_id != _GEN_SAMPLE:
            return super().get_parameter(param_id, timeout=timeout)
        if self._zone is not None:
            return self._ZONES.get(self._zone, 0)     # 0 ends the zone walk
        return self._VOICES.get(self._voice, _NO_SUCH_VOICE)


async def _settle(pilot, tries=200, step=0.02):
    """Let background workers finish so no shot catches a 'loading…' row."""
    for _ in range(tries):
        await pilot.pause()
        await asyncio.sleep(step)
        app = pilot.app
        if not getattr(app, "_scan_active", False) and app.query_one("#presets").row_count:
            return
    raise AssertionError("app never settled")


async def shoot(name, setup, *, compact=True, bridge=None, size=SIZE):
    app = EosedApp(bridge or DemoBridge(), allow_write=True, demo=True)
    app.compact_view = compact
    async with app.run_test(size=size) as pilot:
        await _settle(pilot)
        await setup(pilot, app)
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        (OUT / f"{name}.svg").write_text(app.export_screenshot(title="eosed"))
        print(f"  wrote {name}.svg")


async def select_first_preset(pilot, app):
    table = app.query_one("#presets")
    table.focus()
    table.move_cursor(row=0)
    await pilot.press("enter")
    await _settle(pilot)


async def main():
    print(f"capturing to {OUT} at {SIZE[0]}x{SIZE[1]} (4-pane at {WIDE[0]}x{WIDE[1]})")

    await shoot("compact_view", select_first_preset)

    async def extended_voice(pilot, app):
        await select_first_preset(pilot, app)
        voices = app.query_one("#voices")
        voices.focus()
        voices.move_cursor(row=1)         # V2 -- the multisample one
        await pilot.press("enter")
        await _settle(pilot)
    await shoot("extended_view_voice", extended_voice, compact=False,
                bridge=ShowcaseBridge(), size=WIDE)

    async def edit_dialog(pilot, app):
        await select_first_preset(pilot, app)
        params = app.query_one("#params")
        params.focus()
        params.move_cursor(row=1)         # E4_PRESET_VOLUME
        await pilot.press("enter")
    await shoot("edit_value", edit_dialog)

    async def master(pilot, app):
        await select_first_preset(pilot, app)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("1")            # arm "Delete preset", never fired
    await shoot("master_menu", master)

    async def history(pilot, app):
        await select_first_preset(pilot, app)
        params = app.query_one("#params")
        params.focus()
        params.move_cursor(row=1)
        for _ in range(3):                # a few nudges to populate the log
            await pilot.press("plus")
            await _settle(pilot)
        params.move_cursor(row=0)
        await pilot.press("minus")
        await _settle(pilot)
        await pilot.press("h")
    await shoot("history", history)

    print("done — check the key legend at the bottom of each")


if __name__ == "__main__":
    asyncio.run(main())
