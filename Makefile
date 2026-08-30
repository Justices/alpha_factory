PYTHON ?= python3

.PHONY: bootstrap test lint typecheck quality check

bootstrap:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

quality:
	$(PYTHON) tools/quality_ratchet.py check --baseline quality-baseline.json

check: lint typecheck quality test
