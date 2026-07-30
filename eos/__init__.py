# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors
#
# This file is part of eosed. Original work. GPL-2.0-or-later.

"""The ``eos`` package: the documented E-mu EOS remote editor SysEx protocol.

This is deliberately scoped to the *editor/librarian* protocol only (frame
``F0 18 21 <devID> 55 <cmd> ... F7``), which is fully specified by E-mu (see
``docs/RESOLUTION_NOTES.md`` §1). It is NOT the undocumented front-panel
mirror/button-injection protocol (``docs/RESOLUTION_NOTES.md`` §3) — that one
needs reverse engineering first and does not belong in this package until it
does.
"""
