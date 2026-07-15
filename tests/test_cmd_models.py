# SPDX-FileCopyrightText: 2026 Nithin <nithin30302@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the `observal registry models` commands."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from observal_cli import cmd_models  # noqa: F401
from observal_cli.main import app as cli_app

runner = CliRunner()


def mock_catalog():
    return {
        "models": [
            {
                "model_id": "c-sonnet",
                "provider": "anthropic",
                "display_name": "Claude 3.5",
                "supported_ides": ["claude-code", "cursor"],
                "release_date": "2024-06-20",
                "deprecated": False,
            },
            {
                "model_id": "gpt-4o",
                "provider": "openai",
                "display_name": "GPT-4o",
                "supported_ides": ["cursor", "vscode"],
                "release_date": "2024-05-13",
                "deprecated": False,
            },
            {
                "model_id": "legacy-model",
                "provider": "unknown",
                "supported_ides": [],
                "deprecated": True,
            },
            # Malformed entry (missing fields)
            {"model_id": "malformed-model"},
        ],
        "_source": "https://models.dev",
        "degraded": False,
    }


def _patch_fetch(return_value=None):
    if return_value is None:
        return_value = mock_catalog()
    return patch("observal_cli.cmd_models.model_catalog.fetch_catalog", return_value=return_value)


class TestModelsList:
    def test_list_models_table(self):
        """Test default table rendering of models."""
        with _patch_fetch() as mock_fetch:
            result = runner.invoke(cli_app, ["registry", "models", "list"])

            assert result.exit_code == 0
            assert mock_fetch.called
            assert "c-sonnet" in result.output
            assert "GPT-4o" in result.output
            assert "(deprecated)" in result.output
            assert "models.dev" in result.output
            assert "count: 4" in result.output

    def test_list_models_json(self):
        """Test JSON output mode."""
        with _patch_fetch():
            result = runner.invoke(cli_app, ["registry", "models", "list", "--output", "json"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 4
            assert data[0]["model_id"] == "c-sonnet"
            assert data[3]["model_id"] == "malformed-model"

    def test_list_models_plain(self):
        """Test plain output mode."""
        with _patch_fetch():
            result = runner.invoke(cli_app, ["registry", "models", "list", "--output", "plain"])

            assert result.exit_code == 0
            # Check standard layout with ID, provider, display name, and IDEs
            assert "c-sonnet" in result.output
            assert "anthropic" in result.output
            assert "Claude 3.5" in result.output
            assert "claude-code,cursor" in result.output
            assert "legacy-model" in result.output
            assert "malformed-model" in result.output

    def test_list_models_filter_ide(self):
        """Test filtering by IDE."""
        with _patch_fetch():
            result = runner.invoke(cli_app, ["registry", "models", "list", "--ide", "claude-code"])

            assert result.exit_code == 0
            assert "c-sonnet" in result.output
            assert "GPT-4o" not in result.output
            # Count should reflect the filtered result
            assert "count: 1" in result.output

    def test_list_models_refresh(self):
        """Test refresh flag is passed down to fetch_catalog."""
        with _patch_fetch() as mock_fetch:
            result = runner.invoke(cli_app, ["registry", "models", "list", "--refresh"])

            assert result.exit_code == 0
            mock_fetch.assert_called_once_with(refresh=True)

    def test_list_models_degraded(self):
        """Test degraded indicator is shown."""
        degraded_catalog = mock_catalog()
        degraded_catalog["degraded"] = True
        degraded_catalog["_source"] = "local_cache"

        with _patch_fetch(degraded_catalog):
            result = runner.invoke(cli_app, ["registry", "models", "list"])

            assert result.exit_code == 0
            assert "(degraded — using snapshot)" in result.output
            assert "source: local_cache" in result.output

    def test_list_models_empty(self):
        """Test empty catalog handles gracefully."""
        with _patch_fetch({"models": []}):
            result = runner.invoke(cli_app, ["registry", "models", "list"])

            assert result.exit_code == 0
            assert "No models found." in result.output

    def test_list_models_fetch_catalog_error(self):
        """Test that fetch_catalog exceptions are handled gracefully (non-zero exit)."""

        def _raise_error(*_a, **_kw):
            raise Exception("Network error: connection timeout")

        with patch("observal_cli.cmd_models.model_catalog.fetch_catalog", side_effect=_raise_error):
            result = runner.invoke(cli_app, ["registry", "models", "list"])

            assert result.exit_code != 0
            assert "Network error" in (result.output or str(result.exception))

    def test_list_models_ide_no_matches(self):
        """Test --ide with value matching no models (catalog populated, but IDE has no matches)."""
        with _patch_fetch():
            result = runner.invoke(cli_app, ["registry", "models", "list", "--ide", "kiro"])

            assert result.exit_code == 0
            # Catalog has 4 models but none support 'kiro' IDE
            assert "No models found." in result.output

    def test_list_models_output_invalid(self):
        """Test --output with invalid value falls back to default table rendering.

        Invalid output formats (e.g., 'xml') are not validated client-side.
        The CLI silently falls back to table rendering.
        """
        with _patch_fetch():
            result = runner.invoke(cli_app, ["registry", "models", "list", "--output", "xml"])

            # Invalid output falls back to default table rendering
            assert result.exit_code == 0
            assert "c-sonnet" in result.output
