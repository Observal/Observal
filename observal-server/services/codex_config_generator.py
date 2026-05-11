# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Generate ~/.codex/config.toml snippet for Observal OTLP telemetry."""


def generate_codex_config(observal_url: str) -> dict:
    """Return a config dict with toml_snippet and instructions."""
    toml_snippet = f"""[otel]
environment = "production"
log_user_prompt = true

[otel.exporter.otlp-http]
endpoint = "{observal_url}/v1/logs"
protocol = "http"

[otel.trace_exporter.otlp-http]
endpoint = "{observal_url}/v1/traces"
protocol = "http"
"""
    return {
        "toml_snippet": toml_snippet,
        "instructions": [
            "Append the above to ~/.codex/config.toml",
            "Run: codex",
            "Telemetry will flow to Observal automatically.",
        ],
        "config_path": "~/.codex/config.toml",
    }
