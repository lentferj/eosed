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
	# --skip-editable for eosed and for vinsynlib: both are installed editable
	# from local checkouts -- vinsynlib from the sibling directory, see
	# [tool.uv.sources] in pyproject.toml -- so neither is a distribution on an
	# index and there is nothing for pip-audit to resolve or report against.
	# Left in, both appear in the skip table on every run, which trains the
	# reader to ignore that table. vinsynlib is this family's own source and is
	# reviewed where it lives.
	$(PYTHON) -m pip_audit --skip-editable || true
	$(PYTHON) -m vulture eos/ eosed/ --min-confidence 80 || true
	$(PYTHON) -m deptry .
	$(PYTHON) -m detect_secrets scan --baseline .secrets.baseline

check: lint typecheck test audit
	@echo "All checks passed."
