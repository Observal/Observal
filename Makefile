.PHONY: lint format check test test-adversarial test-eval-completeness test-all hooks clean

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
	cd observal-server && uv run --with pytest --with pytest-asyncio --with pyyaml --with typer --with rich pytest ../tests/ -q

test-v:  ## Run Python tests (verbose)
	cd observal-server && uv run --with pytest --with pytest-asyncio --with pyyaml --with typer --with rich pytest ../tests/ -v

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
	@echo "✓ Hooks installed"

# ── Docker ───────────────────────────────────────────────

up:  ## Start Docker stack
	cd docker && docker compose up -d

down:  ## Stop Docker stack
	cd docker && docker compose down

rebuild:  ## Rebuild and restart Docker stack
	cd docker && docker compose up --build -d

logs:  ## Tail Docker logs
	cd docker && docker compose logs -f --tail=50

# ── Cleanup ──────────────────────────────────────────────

clean:  ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ htmlcov/ .coverage

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
