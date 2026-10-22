# SPDX-License-Identifier: GPL-3.0-or-later
# Developer shortcuts. Python commands run through `uv run`, which keeps .venv in sync with uv.lock.
.PHONY: help test lint fmt

help:  ## list the targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

test:  ## run the Python tests with coverage
	uv run pytest --cov=climblog --cov-report=term-missing

lint:  ## check formatting, lint rules and types (changes nothing)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy

fmt:  ## fix formatting and auto-fixable lint problems
	uv run ruff format .
	uv run ruff check --fix .
