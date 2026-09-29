# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed.  Original work.  GPL-2.0-or-later.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Capture rig with teardown that survives being killed.

WHY THIS IS A TOOL AND NOT A SCRATCHPAD FILE
============================================
It was written twice in the scratchpad and lost twice to a machine reboot --
once when the bench was powered down, once when the E4XT needed a power cycle
to see a reformatted card. A guard that has to be rewritten from memory each
time is not a guard. RESOLUTION_NOTES 147 is the incident it exists for.

WHAT IT GUARDS
==============
1. Construction can fail AFTER activate(). `_PersistentRecorder.__init__`
   activates the client and then connects ports, which can raise. The client is
   then registered and running with no reference left to close it.
   `cls.__new__(cls)` plus an explicit `__init__` keeps a reference to the
   partially built object; a plain constructor call discards it, and that
   discarding IS the leak.

2. `except Exception` does not catch being killed. SystemExit and
   KeyboardInterrupt are not Exceptions, and being killed is precisely how this
   arrives -- a shell `timeout`, a Ctrl-C, a harness killing a hung probe. Catch
   BaseException and handle the signals, or the teardown runs in every case
   except the one that happens.

3. A capture with no deadline is a rig-wide outage. A blocked capture holds the
   client indefinitely and `jack_lsp` then hangs for every session on the
   machine. A SIGALRM deadline turns that into one failed run.

THERE IS NO RECOVERY AFTER THE FACT
===================================
Do not add an "orphan recovery" path. `jack.Client(name)` defaults to
use_exact_name=False and the server "will modify this name to create a unique
variant, if needed" -- so reconnecting by an orphan's name registers `name-01`,
closes that, and leaves the orphan untouched while appearing to succeed. The API
closes your OWN client only. Once a client outlives its owner, only a server
restart clears it. These guards are the whole defence.
"""
import atexit
import os
import signal


class Rig:
    """Wrap the shared `_PersistentRecorder` with teardown on every exit path."""

    def __init__(self, capture, name, deadline_s=180.0):
        import hw_measure
        self._rec = None
        self._closed = False
        cls = hw_measure._PersistentRecorder
        rec = cls.__new__(cls)
        try:
            rec.__init__(capture, name=name)
        except BaseException:
            client = getattr(rec, "client", None)
            if client is not None:
                for fn in ("deactivate", "close"):
                    try:
                        getattr(client, fn)()
                    except BaseException:
                        pass
            raise
        self._rec = rec
        self._deadline = deadline_s
        atexit.register(self.close)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self._on_signal)
        signal.signal(signal.SIGALRM, self._on_deadline)

    def _on_signal(self, signum, frame):
        """Close, but never let a hung close() hold the rig.

        mpc2emu, 2026-09-29: their recorder hung for 45 minutes AFTER a
        completed capture and **swallowed SIGTERM from its own `timeout 900`**
        -- only SIGKILL ended it. That is the alive-but-stuck case RESOLUTION
        NOTES 178a lists as the one the PipeWire churn measurement did not
        cover, observed for the first time. The capture had already been
        written, so the cost was the rig being held, not data.

        A teardown that can hang is not a teardown. The alarm below bounds it:
        if close() has not returned in five seconds, `os._exit` leaves without
        unwinding, which is the right trade -- the process is going away
        either way, and a held rig blocks every session on the machine.
        `os._exit` rather than `sys.exit` because SystemExit can be swallowed
        by an `except` on the way out, which is how the 45 minutes happened.
        """
        signal.signal(signal.SIGALRM, lambda *_: os._exit(1))
        signal.alarm(5)
        try:
            self.close()
        except BaseException:
            os._exit(1)
        # ORDINARY PATH: disarm and die of the signal we were sent, so the exit
        # status is the real one (143 for SIGTERM) and a caller's `timeout` or
        # shell sees what it expects. mpc2emu's version of this fix, which is
        # better than the unconditional `os._exit` this replaced -- that got
        # the rig released but threw away the signal semantics on every run.
        signal.alarm(0)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    def _on_deadline(self, signum, frame):
        raise TimeoutError("capture exceeded its deadline")

    def arm(self):
        signal.alarm(int(self._deadline))
        self._rec.arm()

    def stop_and_write(self, path):
        try:
            self._rec.stop_and_write(path)
        finally:
            signal.alarm(0)

    @property
    def samplerate(self):
        return self._rec.samplerate

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._rec is not None:
                self._rec.close()
        except BaseException:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
