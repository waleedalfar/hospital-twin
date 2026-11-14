# Hospital Twin — commands (CLAUDE.md §5). Run `make help` for the list.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE_DEV := docker compose -f infra/docker-compose.yml
COMPOSE_TEST := docker compose -f infra/docker-compose.test.yml
# uv ignores any virtualenv that happens to be active in the calling shell and uses backend/.venv.
UV := env -u VIRTUAL_ENV uv run --directory backend
NPM := npm --prefix frontend

.PHONY: faceless help setup db db-down test-db test-db-down dev test test-backend test-frontend lint \
        placeholders e2e verify seed train demo deploy record fed-train verify-live

help: ## List the commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

setup: ## Install backend + frontend deps, pull Docker images, create .env if missing
	@test -f .env || { cp .env.example .env && echo "Created .env from .env.example"; }
	env -u VIRTUAL_ENV uv sync --project backend
	$(NPM) ci --no-fund --no-audit
	cd frontend && npx playwright install chromium
	$(COMPOSE_DEV) pull
	$(COMPOSE_TEST) pull

db: ## Start TimescaleDB (Docker) and run migrations
	$(COMPOSE_DEV) up -d --wait
	$(UV) python -m twin.db.migrate

db-down: ## Stop the development database (data is kept in its Docker volume)
	$(COMPOSE_DEV) down

test-db: ## Start the integration-test TimescaleDB
	$(COMPOSE_TEST) up -d --wait

test-db-down: ## Stop the integration-test database
	$(COMPOSE_TEST) down

dev: db ## Run DB, backend and frontend dev server together (Ctrl-C stops both servers)
	@trap 'kill 0' INT TERM EXIT; \
	$(UV) uvicorn twin.api.main:app --reload --host 127.0.0.1 --port 8000 & \
	$(NPM) run dev & \
	wait

lint: ## ruff, mypy --strict, eslint, tsc --noEmit
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy
	$(NPM) run lint
	$(NPM) run typecheck
	$(UV) python -m twin.common.schema_gen --check
	$(UV) python -m twin.sim.build_layout --check
	$(NPM) run check:types

test-backend: test-db ## Backend unit + integration tests with the coverage gate (85%)
	$(UV) pytest --cov --cov-report=term-missing --cov-report=json:coverage.json

test-frontend: ## Frontend unit tests with the coverage gate (80%)
	cd frontend && npx vitest run --coverage --reporter=default --reporter=json \
		--outputFile.json=test-results/unit-report.json
	node scripts/check_no_skips.mjs vitest frontend/test-results/unit-report.json

test: test-backend test-frontend ## Unit + integration tests

faceless: ## Faceless enforcement test (PROMPT.md §10.4): no character has a facial feature
	cd frontend && npx vitest run tests/engine/characters.test.ts --reporter=default

placeholders: ## Fail if unfinished-work markers are present in the repo
	./scripts/check_placeholders.sh

e2e: db ## Playwright end-to-end tests against the running stack
	cd frontend && npx playwright test
	node scripts/check_no_skips.mjs playwright frontend/test-results/e2e-report.json

verify: lint test faceless placeholders ## Everything in CLAUDE.md §3; fails on any problem
	@echo "make verify: all checks passed"

# `seed` is real from CP1. The other targets below belong to later checkpoints. Until their checkpoint is built they stop with an error
# instead of pretending to work (approved by the human in the CP0 plan).
seed: db ## Generate Synthea patients and load them (reuses existing output; SEED_ARGS=--regenerate forces)
	$(UV) python -m twin.db.seed $(SEED_ARGS)

train: ## Build the training set and train/evaluate models (built in CP5)
	@echo "make train: model training is built in CP5 (PROMPT.md §7). Nothing was run." >&2; exit 1

fed-train: ## Federated training from the command line (built in CP7)
	@echo "make fed-train: federated training is built in CP7 (PROMPT.md §7.6). Nothing was run." >&2; exit 1

verify-live: ## Real Gemini call when a key is present (built in CP6)
	@echo "make verify-live: the Gemini agent is built in CP6 (PROMPT.md §9). Nothing was run." >&2; exit 1

deploy: ## Build and deploy to the Vultr VM (built in CP8)
	@echo "make deploy: deployment is built in CP8 (PROMPT.md §12). Nothing was run." >&2; exit 1

demo: ## Start the stack with the demo scenario script (built in CP9)
	@echo "make demo: the demo scenario is built in CP9 (PROMPT.md §13). Nothing was run." >&2; exit 1

record: ## Record the demo video (built in CP9)
	@echo "make record: the demo recording is built in CP9 (PROMPT.md §13). Nothing was run." >&2; exit 1
