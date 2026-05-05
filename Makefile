.PHONY: lint format check test test-adversarial test-eval-completeness test-all hooks clean migrate check-migrations new-migration reset release-major release-feature release-patch

# ── Linting ──────────────────────────────────────────────

lint:  ## Run all linters
	uv run --with ruff==0.15.10 ruff check .

format:  ## Auto-format all code
	uv run --with ruff==0.15.10 ruff format .
	uv run --with ruff==0.15.10 ruff check --fix .

check:  ## Full pre-commit check on all files
	pre-commit run --all-files

# ── Testing ──────────────────────────────────────────────

test:  ## Run Python tests
	cd observal-server && uv run --with pytest --with pytest-asyncio --with pyyaml --with typer --with rich --with hypothesis pytest ../tests/ -q

test-v:  ## Run Python tests (verbose)
	cd observal-server && uv run --with pytest --with pytest-asyncio --with pyyaml --with typer --with rich --with hypothesis pytest ../tests/ -v

test-adversarial:  ## Run BenchJack self-test suite
	cd observal-server && uv run --with pytest --with pytest-asyncio --with pyyaml --with typer --with rich pytest ../tests/test_adversarial_self.py -v --tb=short

test-eval-completeness:  ## Run eval completeness tests
	cd observal-server && uv run --with pytest --with pytest-asyncio --with pyyaml --with typer --with rich pytest ../tests/test_eval_completeness.py -v --tb=short

test-all: test test-eval-completeness test-adversarial  ## Run all tests including adversarial and completeness

# ── Setup ────────────────────────────────────────────────

hooks:  ## Install pre-commit hooks
	pip install pre-commit
	pre-commit install
	pre-commit install --hook-type commit-msg
	pre-commit install --hook-type pre-push
	@echo "✓ Hooks installed"

# ── Docker ───────────────────────────────────────────────

# Auto-detect enterprise mode: if observal-insights/ exists, use enterprise override
COMPOSE_FILES := -f docker-compose.yml
ifneq (,$(wildcard observal-insights/pyproject.toml))
  COMPOSE_FILES += -f docker-compose.enterprise.yml
  $(info [enterprise mode] observal-insights/ detected)
endif

up:  ## Start Docker stack
	cd docker && docker compose $(COMPOSE_FILES) up -d

down:  ## Stop Docker stack
	cd docker && docker compose $(COMPOSE_FILES) down

migrate:  ## Run database migrations
	cd docker && docker compose $(COMPOSE_FILES) exec observal-api /app/.venv/bin/python -m alembic upgrade head

check-migrations:  ## Validate alembic migration chain (no duplicates, no forks)
	python3 scripts/check_migrations.py

new-migration:  ## Create a new migration: make new-migration MSG="add foo to bar"
	@test -n "$(MSG)" || (echo 'Usage: make new-migration MSG="description"' && exit 1)
	./scripts/new_migration.sh "$(MSG)"

rebuild:  ## Rebuild and restart Docker stack (runs migrations automatically)
	cd docker && docker compose $(COMPOSE_FILES) up --build -d
	@echo "Waiting for API to be healthy..."
	@cd docker && until docker compose $(COMPOSE_FILES) exec observal-api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; do sleep 1; done
	cd docker && docker compose $(COMPOSE_FILES) restart observal-lb
	@echo "API is healthy."

reset:  ## Nuke all Docker volumes and rebuild from scratch (fresh app, no file changes)
	cd docker && docker compose $(COMPOSE_FILES) down -v
	cd docker && docker compose $(COMPOSE_FILES) up --build -d
	@echo "Waiting for API to be healthy..."
	@cd docker && until docker compose $(COMPOSE_FILES) exec observal-api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; do sleep 1; done
	cd docker && docker compose $(COMPOSE_FILES) restart observal-lb
	@echo "API is healthy — all data has been reset."

rebuild-clean:  ## Rebuild from scratch (no Docker cache), remove volumes, and restart
	cd docker && docker compose $(COMPOSE_FILES) down -v && docker compose $(COMPOSE_FILES) build --no-cache && docker compose $(COMPOSE_FILES) up -d
	@echo "Waiting for API to be healthy..."
	@cd docker && until docker compose $(COMPOSE_FILES) exec observal-api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; do sleep 1; done
	cd docker && docker compose $(COMPOSE_FILES) restart observal-lb
	@echo "API is healthy."

logs:  ## Tail Docker logs
	cd docker && docker compose logs -f --tail=50

# ── Cleanup ──────────────────────────────────────────────

clean:  ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ htmlcov/ .coverage

# ── Release ─────────────────────────────────────────────────

release-major:  ## Cut a major release (X.0.0, requires approval)
	tools/release.sh major

release-feature:  ## Cut a feature release (x.Y.0, requires approval)
	tools/release.sh feature

release-patch:  ## Cut a patch release (x.y.Z, auto-publishes)
	tools/release.sh patch

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
