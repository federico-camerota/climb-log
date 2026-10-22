# SPDX-License-Identifier: GPL-3.0-or-later
# Developer shortcuts. Python commands run through `uv run`, which keeps .venv in sync with uv.lock;
# frontend commands run through pnpm in frontend/.
.PHONY: help install dev build test lint fmt

PNPM := pnpm --dir frontend

help:  ## list the targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

install:  ## install Python and frontend dependencies from the lock files, and the git hooks
	uv sync --locked
	$(PNPM) install --frozen-lockfile
	uv run pre-commit install

dev:  ## run backend (:8000, auto-reload) and Vite (:5173, hot reload); open http://127.0.0.1:5173
	@sh scripts/dev.sh

build:  ## build the frontend into backend/climblog/static, served by `climblog serve`
	$(PNPM) build

test:  ## run the Python and frontend tests
	uv run pytest --cov=climblog --cov-report=term-missing
	$(PNPM) test

lint:  ## check formatting, lint rules and types (changes nothing)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	$(PNPM) lint

fmt:  ## fix formatting and auto-fixable lint problems
	uv run ruff format .
	uv run ruff check --fix .
	$(PNPM) fmt
