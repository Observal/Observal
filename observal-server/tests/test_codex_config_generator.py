# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: AGPL-3.0-only

import tomllib

from services.codex_config_generator import generate_codex_config


def _parsed_toml(observal_url: str) -> dict:
    return tomllib.loads(generate_codex_config(observal_url)["toml_snippet"])


def test_generate_codex_config_builds_otlp_log_and_trace_endpoints():
    parsed = _parsed_toml("https://observal.example")

    assert parsed["otel"]["environment"] == "production"
    assert parsed["otel"]["log_user_prompt"] is True
    assert parsed["otel"]["exporter"]["otlp-http"] == {
        "endpoint": "https://observal.example/v1/logs",
        "protocol": "http",
    }
    assert parsed["otel"]["trace_exporter"]["otlp-http"] == {
        "endpoint": "https://observal.example/v1/traces",
        "protocol": "http",
    }


def test_generate_codex_config_includes_config_path_and_instructions():
    config = generate_codex_config("https://observal.example")

    assert config["config_path"] == "~/.codex/config.toml"
    assert config["instructions"] == [
        "Append the above to ~/.codex/config.toml",
        "Run: codex",
        "Telemetry will flow to Observal automatically.",
    ]


def test_generate_codex_config_allows_relative_endpoint_edge_case():
    parsed = _parsed_toml("")

    assert parsed["otel"]["exporter"]["otlp-http"]["endpoint"] == "/v1/logs"
    assert parsed["otel"]["trace_exporter"]["otlp-http"]["endpoint"] == "/v1/traces"

