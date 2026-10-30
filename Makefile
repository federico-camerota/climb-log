# SPDX-License-Identifier: GPL-3.0-or-later
# Developer shortcuts. Python commands run through `uv run`, which keeps .venv in sync with uv.lock;
# frontend commands run through pnpm in frontend/.
.PHONY: help install dev build test fixtures api-types lint fmt

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

fixtures:  ## write the fictional journal workbooks to tests/fixtures/ (git-ignored), to open them
	uv run python tests/fictional_journal.py tests/fixtures

API_TYPES := frontend/src/api/schema.ts

api-types:  ## write the frontend's API types from the backend's OpenAPI schema
	@mkdir -p build
	uv run python scripts/openapi.py > build/openapi.json
	$(PNPM) exec openapi-typescript ../build/openapi.json -o ../$(API_TYPES)

lint:  ## check formatting, lint rules and types (changes nothing)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	$(PNPM) lint
	@mkdir -p build
	uv run python scripts/openapi.py > build/openapi.json
	$(PNPM) exec openapi-typescript ../build/openapi.json -o ../build/schema.ts
	@diff -q $(API_TYPES) build/schema.ts >/dev/null || \
		{ echo "$(API_TYPES) is out of date: run make api-types"; exit 1; }

fmt:  ## fix formatting and auto-fixable lint problems
	uv run ruff format .
	uv run ruff check --fix .
	$(PNPM) fmt
