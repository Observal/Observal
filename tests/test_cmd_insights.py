# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from typer.testing import CliRunner

from observal_cli.cmd_insights import insights_app

runner = CliRunner()


def test_insights_list_resolves_agent_name_before_report_lookup(monkeypatch):
    calls = []

    def fake_get(path: str, params: dict | None = None):
        calls.append((path, params))
        if path == "/api/v1/agents/ultra-pi":
            return {"id": "c6185803-8c32-4c39-b347-78f8281e306e", "name": "ultra-pi"}
        if path == "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports":
            return []
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("observal_cli.config.resolve_alias", lambda value: value)
    monkeypatch.setattr("observal_cli.cmd_insights.client.get", fake_get)

    result = runner.invoke(insights_app, ["list", "ultra-pi"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("/api/v1/agents/ultra-pi", None),
        ("/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports", None),
    ]


def test_insights_generate_resolves_agent_name_before_generate(monkeypatch):
    calls = []

    def fake_get(path: str, params: dict | None = None):
        calls.append(("GET", path, params))
        if path == "/api/v1/insights/status":
            return {"available": True, "reason": None}
        if path == "/api/v1/agents/ultra-pi":
            return {"id": "c6185803-8c32-4c39-b347-78f8281e306e", "name": "ultra-pi"}
        raise AssertionError(f"unexpected path: {path}")

    def fake_post(path: str, data: dict):
        calls.append(("POST", path, data))
        if path == "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports":
            return {
                "id": "be5aa083-d84a-49e7-8a35-b37b3e687780",
                "status": "pending",
                "period_start": "2026-05-17T00:00:00Z",
                "period_end": "2026-05-31T00:00:00Z",
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("observal_cli.config.resolve_alias", lambda value: value)
    monkeypatch.setattr("observal_cli.cmd_insights.client.get", fake_get)
    monkeypatch.setattr("observal_cli.cmd_insights.client.post", fake_post)

    result = runner.invoke(insights_app, ["generate", "ultra-pi", "--period", "30"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("GET", "/api/v1/insights/status", None),
        ("GET", "/api/v1/agents/ultra-pi", None),
        (
            "POST",
            "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports",
            {"period_days": 30},
        ),
    ]


def _completed_report(report_id: str):
    return {
        "id": report_id,
        "agent_id": "c6185803-8c32-4c39-b347-78f8281e306e",
        "status": "completed",
        "period_start": "2026-05-17T00:00:00Z",
        "period_end": "2026-05-31T00:00:00Z",
        "sessions_analyzed": 103,
        "llm_model_used": "test-model",
        "narrative": {},
    }


def test_insights_show_agent_name_uses_latest_completed_report(monkeypatch):
    calls = []

    def fake_get(path: str, params: dict | None = None):
        calls.append((path, params))
        if path == "/api/v1/agents/ultra-pi":
            return {"id": "c6185803-8c32-4c39-b347-78f8281e306e", "name": "ultra-pi"}
        if path == "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports":
            return [
                {"id": "34029e91-cf7d-4e0d-9b87-a1962e8ef2a7", "status": "failed"},
                {"id": "be5aa083-d84a-49e7-8a35-b37b3e687780", "status": "completed"},
            ]
        if (
            path
            == "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports/be5aa083-d84a-49e7-8a35-b37b3e687780"
        ):
            return _completed_report("be5aa083-d84a-49e7-8a35-b37b3e687780")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("observal_cli.config.resolve_alias", lambda value: value)
    monkeypatch.setattr("observal_cli.cmd_insights.client.get", fake_get)

    result = runner.invoke(insights_app, ["show", "ultra-pi"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("/api/v1/agents/ultra-pi", None),
        ("/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports", None),
        (
            "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports/be5aa083-d84a-49e7-8a35-b37b3e687780",
            None,
        ),
    ]


def test_insights_show_agent_name_accepts_report_row(monkeypatch):
    calls = []

    def fake_get(path: str, params: dict | None = None):
        calls.append((path, params))
        if path == "/api/v1/agents/ultra-pi":
            return {"id": "c6185803-8c32-4c39-b347-78f8281e306e", "name": "ultra-pi"}
        if path == "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports":
            return [
                {"id": "be5aa083-d84a-49e7-8a35-b37b3e687780", "status": "completed"},
                {"id": "b7c416a4-b501-42d7-a066-3cc95b76e656", "status": "completed"},
            ]
        if (
            path
            == "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports/b7c416a4-b501-42d7-a066-3cc95b76e656"
        ):
            return _completed_report("b7c416a4-b501-42d7-a066-3cc95b76e656")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("observal_cli.config.resolve_alias", lambda value: value)
    monkeypatch.setattr("observal_cli.cmd_insights.client.get", fake_get)

    result = runner.invoke(insights_app, ["show", "ultra-pi", "2"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("/api/v1/agents/ultra-pi", None),
        ("/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports", None),
        (
            "/api/v1/agents/c6185803-8c32-4c39-b347-78f8281e306e/insights/reports/b7c416a4-b501-42d7-a066-3cc95b76e656",
            None,
        ),
    ]
