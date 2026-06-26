# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


def test_agent_init_flags_write_yaml(tmp_path):
    target = tmp_path / "agent"

    with patch("observal_cli.config.load", return_value={"username": "me"}):
        result = runner.invoke(
            app,
            [
                "agent",
                "init",
                "--dir",
                str(target),
                "--name",
                "Incident Helper",
                "--version",
                "1.2.3",
                "--description",
                "Resolves incidents",
                "--model",
                "claude-sonnet-4",
                "--prompt",
                "Handle incident response.",
                "--harness",
                "kiro",
                "--harness",
                "claude-code",
            ],
        )

    assert result.exit_code == 0, result.output
    data = yaml.safe_load((target / "observal-agent.yaml").read_text())
    assert data["name"] == "incident-helper"
    assert data["version"] == "1.2.3"
    assert data["prompt"] == "Handle incident response."
    assert data["supported_harnesses"] == ["kiro", "claude-code"]


def test_agent_init_prompt_file(tmp_path):
    target = tmp_path / "agent"
    prompt = tmp_path / "PROMPT.md"
    prompt.write_text("Design good frontends.", encoding="utf-8")

    with patch("observal_cli.config.load", return_value={"username": "me"}):
        result = runner.invoke(
            app,
            [
                "agent",
                "init",
                "--dir",
                str(target),
                "--name",
                "frontend-agent",
                "--description",
                "Frontend design",
                "--prompt-file",
                str(prompt),
            ],
        )

    assert result.exit_code == 0, result.output
    data = yaml.safe_load((target / "observal-agent.yaml").read_text())
    assert data["prompt"] == "Design good frontends."
