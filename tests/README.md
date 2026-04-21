# Tests

Test suite for the Observal backend, CLI, and web frontend.

## Frameworks

| Layer | Framework | Language |
|-------|-----------|----------|
| Backend unit and integration | pytest + pytest-asyncio | Python |
| CLI | pytest with typer's CliRunner | Python |
| Frontend E2E | Playwright | TypeScript |

## Directory Layout

Python tests live in `tests/` at the repo root. The eval subsystem has its own subdirectory. Frontend E2E tests live in `web/e2e/`.

```
tests/
├── conftest.py           # Adds observal-server to sys.path
├── mock_mcp.py           # Minimal MCP v2024-11-05 server for protocol tests
├── eval/                 # Evaluation pipeline tests (see docs/concepts/evaluation.md)
│   ├── test_phase8*.py   # Scoring pipeline (sanitizer, matching, adversarial, canary)
│   ├── test_eval_*.py    # Eval engine and completeness meta-tests
│   ├── test_score_aggregator.py
│   ├── test_slm_scorer.py
│   ├── test_structural_scorer.py
│   ├── test_adversarial_self.py   # BenchJack self-attacks
│   └── test_ragas_eval.py         # RAGAS metrics
├── test_clickhouse*.py   # ClickHouse DDL, ingestion, retention
├── test_git_mirror.py    # Real git clone/discover/validate (no mocks)
├── test_pull_and_agent_cli.py  # CLI pull and agent commands
├── test_enterprise.py    # Enterprise feature schemas and guards
├── test_payload_crypto.py      # ECIES + AES-256-GCM encryption
├── ...                   # ~30 additional test files
web/e2e/
├── helpers.ts            # Shared utilities (login, API calls, data builders)
├── sso-login.spec.ts     # Real Microsoft Entra ID SSO flow
├── kiro-*.spec.ts        # Kiro agent, CLI, hooks, lifecycle, OTLP tests
└── ...                   # 10 spec files total
```

## Running Tests

### Python

```bash
# All backend and CLI tests
cd observal-server
uv run pytest ../tests/ -q

# Just the eval subsystem
uv run pytest ../tests/eval/ -q

# A specific file
uv run pytest ../tests/eval/test_phase8g_pipeline.py -v
```

Tests run against Python 3.11, 3.12, and 3.13 in CI.

### Frontend E2E

```bash
cd web
pnpm e2e              # all specs
pnpm e2e:kiro         # only Kiro specs
pnpm e2e:ui           # interactive UI mode
```

Playwright runs against Chromium, headless, with a 60-second timeout per test and one retry on failure.

## Configuration

pytest is configured in the root `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Playwright is configured in `web/playwright.config.ts`. It expects the dev server on `http://localhost:3000`.

## Test Categories

| Category | Example files | What they cover |
|----------|--------------|-----------------|
| Scoring pipeline | `eval/test_phase8a_sanitizer.py`, `eval/test_score_aggregator.py` | SLM judges, adversarial scoring, canary detection, structural matching |
| Data pipeline | `test_clickhouse_phase1.py`, `test_ingest_phase2.py` | ClickHouse DDL, OTLP ingestion, data retention |
| Agent system | `test_agent_composition.py`, `test_agent_config_generator.py` | Composition, config generation, environment variables |
| Security | `test_payload_crypto.py`, `test_secrets_redactor.py` | Encryption, PII redaction, prompt injection detection |
| CLI | `test_pull_and_agent_cli.py`, `test_cli_errors.py` | Pull command, agent commands, error handling |
| API and GraphQL | `test_graphql_phase6.py`, `test_review_queue.py` | REST endpoints, GraphQL queries |
| Infrastructure | `test_git_mirror.py`, `test_resilience.py`, `test_health.py` | Git operations, retries, health checks |
| Enterprise | `test_enterprise.py`, `test_audit_logging.py` | EE schemas, audit trail |

## Patterns

- **Async tests**: All async tests use `@pytest.mark.asyncio` with `asyncio_mode = "auto"`, so the decorator is optional.
- **Mocking**: `unittest.mock.AsyncMock` and `MagicMock` for service dependencies. `test_git_mirror.py` is a notable exception that uses real git operations.
- **E2E helpers**: `web/e2e/helpers.ts` provides `loginToWebUI`, `waitForAPI`, `sendKiroOTLPTrace`, and payload builders to keep spec files focused on assertions.
