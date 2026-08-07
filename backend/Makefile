# Comandos reproducibles de calidad para ContaMind AI (Fase 0).
# En Windows sin `make`, usar los equivalentes en scripts/*.ps1.
PYTHON ?= python
VENV_PY := $(CURDIR)/.venv/Scripts/python.exe

.PHONY: setup lint test test-postgres migrate run

setup:
	python -m venv .venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r requirements-dev.txt

lint:
	$(VENV_PY) -m ruff check . --select E9,F

test:
	$(VENV_PY) -m pytest

test-postgres:
	$(VENV_PY) -m pytest -m postgres

migrate:
	$(VENV_PY) -m alembic upgrade head

run:
	$(VENV_PY) -m uvicorn main:app --reload
