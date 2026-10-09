# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  eosed contributors

PYTHON ?= .venv/bin/python

.PHONY: lint format typecheck test audit check install-dev

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check eos/ eosed/ tests/

format:
	$(PYTHON) -m ruff format eos/ eosed/ tests/
	$(PYTHON) -m ruff check --fix eos/ eosed/ tests/

typecheck:
	$(PYTHON) -m mypy eos/ eosed/

test:
	$(PYTHON) -m pytest

audit:
	# --skip-editable for eosed: it is installed editable from the local
	# checkout, so it is not a distribution on an index and there is nothing
	# for pip-audit to resolve. vinsynlib is a normal index dependency now (it
	# is on PyPI) and is audited with the rest; it used to be skipped here for
	# the same reason as eosed, when it was a sibling checkout.
	$(PYTHON) -m pip_audit --skip-editable || true
	$(PYTHON) -m vulture eos/ eosed/ --min-confidence 80 || true
	$(PYTHON) -m deptry .
	$(PYTHON) -m detect_secrets scan --baseline .secrets.baseline

check: lint typecheck test audit
	@echo "All checks passed."
