# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for MCP config parsing functions in cmd_mcp.py.

Covers _parse_server_json_manifest, _parse_direct_config, and _unwrap_mcp_config.
"""

from observal_cli.cmd_mcp import (
    _parse_direct_config,
    _parse_server_json_manifest,
    _unwrap_mcp_config,
)

# --- _parse_server_json_manifest ---


class TestParseServerJsonManifest:
    """Tests for the server.json manifest parser."""

    def test_returns_none_for_non_manifest(self):
        """Non-manifest config returns None."""
        assert _parse_server_json_manifest({"command": "npx", "args": []}) is None
        assert _parse_server_json_manifest({"url": "http://x.com"}) is None
        assert _parse_server_json_manifest({}) is None

    def test_remotes_basic(self):
        """Parses a remotes-only manifest with URL and variables."""
        cfg = {
            "remotes": [
                {
                    "type": "sse",
                    "url": "https://api.example.com/mcp",
                    "variables": {
                        "API_KEY": {"description": "Your API key"},
                        "ORG_ID": {"description": "Organization ID"},
                    },
                }
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert result is not None
        assert result["url"] == "https://api.example.com/mcp"
        assert result["transport"] == "sse"
        assert len(result["environment_variables"]) == 2
        names = {ev["name"] for ev in result["environment_variables"]}
        assert names == {"API_KEY", "ORG_ID"}

    def test_remotes_streamable_http(self):
        """Handles streamable-http type."""
        cfg = {
            "remotes": [
                {
                    "type": "streamable-http",
                    "url": "https://api.example.com/v2/mcp",
                }
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert result["transport"] == "streamable-http"
        assert result["url"] == "https://api.example.com/v2/mcp"

    def test_packages_only_implies_docker(self):
        """Packages-only manifest implies stdio/docker transport."""
        cfg = {
            "packages": [
                {
                    "runtimeArguments": [
                        {"value": "API_KEY={key}", "description": "API key"},
                        {"value": "SECRET={secret}", "description": "Secret"},
                    ]
                }
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert result is not None
        assert result["transport"] == "stdio"
        assert result["framework"] == "docker"
        assert len(result["environment_variables"]) == 2

    def test_packages_ignores_lowercase_vars(self):
        """Only UPPERCASE variable names from packages are extracted."""
        cfg = {
            "packages": [
                {
                    "runtimeArguments": [
                        {"value": "API_KEY={key}", "description": "Key"},
                        {"value": "not_a_var=something", "description": "Lower"},
                    ]
                }
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert len(result["environment_variables"]) == 1
        assert result["environment_variables"][0]["name"] == "API_KEY"

    def test_packages_no_equals_sign_skipped(self):
        """Runtime args without '=' are skipped."""
        cfg = {
            "packages": [
                {
                    "runtimeArguments": [
                        {"value": "justaflag", "description": "No equals"},
                    ]
                }
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert "environment_variables" not in result

    def test_registry_format_unwraps_server_envelope(self):
        """Registry format with server envelope is unwrapped."""
        cfg = {
            "server": {
                "name": "inference-sh",
                "title": "Inference.sh MCP",
                "description": "Fast LLM inference",
                "remotes": [
                    {
                        "type": "sse",
                        "url": "https://inference.sh/mcp",
                        "variables": {"TOKEN": {"description": "Auth token"}},
                    }
                ],
            },
            "_meta": {"version": "1.0"},
        }
        result = _parse_server_json_manifest(cfg)
        assert result is not None
        assert result["_server_name"] == "Inference.sh MCP"
        assert result["_description"] == "Fast LLM inference"
        assert result["url"] == "https://inference.sh/mcp"
        assert result["transport"] == "sse"
        assert len(result["environment_variables"]) == 1

    def test_registry_format_uses_name_if_no_title(self):
        """Falls back to 'name' field if 'title' is absent."""
        cfg = {
            "server": {
                "name": "my-server",
                "remotes": [{"url": "http://x.com"}],
            }
        }
        result = _parse_server_json_manifest(cfg)
        assert result["_server_name"] == "my-server"

    def test_registry_format_packages_with_meta(self):
        """Registry format with packages array nested under server."""
        cfg = {
            "server": {
                "title": "Docker MCP",
                "description": "Runs in Docker",
                "packages": [
                    {
                        "runtimeArguments": [
                            {"value": "DB_HOST={host}", "description": "Database host"},
                        ]
                    }
                ],
            }
        }
        result = _parse_server_json_manifest(cfg)
        assert result["_server_name"] == "Docker MCP"
        assert result["_description"] == "Runs in Docker"
        assert result["transport"] == "stdio"
        assert result["framework"] == "docker"
        assert result["environment_variables"][0]["name"] == "DB_HOST"

    def test_multiple_remotes_uses_first_url(self):
        """Only the first remote's URL is used."""
        cfg = {
            "remotes": [
                {"url": "https://first.example.com", "type": "sse"},
                {"url": "https://second.example.com", "type": "streamable-http"},
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert result["url"] == "https://first.example.com"
        assert result["transport"] == "sse"

    def test_remotes_variable_meta_non_dict(self):
        """Variable metadata that isn't a dict defaults to empty description."""
        cfg = {
            "remotes": [
                {
                    "url": "http://x.com",
                    "variables": {"KEY": "just a string"},
                }
            ]
        }
        result = _parse_server_json_manifest(cfg)
        assert result["environment_variables"][0]["name"] == "KEY"
        assert result["environment_variables"][0]["description"] == ""


# --- _unwrap_mcp_config ---


class TestUnwrapMcpConfig:
    """Tests for the harness config unwrapper."""

    def test_mcp_servers_wrapper(self):
        """Unwraps {mcpServers: {name: config}} format."""
        cfg = {"mcpServers": {"my-server": {"command": "npx", "args": ["-y", "server"]}}}
        inner, name = _unwrap_mcp_config(cfg)
        assert name == "my-server"
        assert inner["command"] == "npx"

    def test_mcp_servers_multiple_keys(self):
        """Multiple keys in mcpServers returns the whole dict."""
        cfg = {"mcpServers": {"a": {"command": "x"}, "b": {"command": "y"}}}
        inner, name = _unwrap_mcp_config(cfg)
        assert name is None

    def test_bare_config_with_command(self):
        """Bare config dict with command key."""
        cfg = {"command": "python3", "args": ["-m", "myserver"]}
        inner, name = _unwrap_mcp_config(cfg)
        assert inner is cfg
        assert name is None

    def test_bare_config_with_url(self):
        """Bare config dict with url key."""
        cfg = {"url": "http://x.com/mcp", "type": "sse"}
        inner, name = _unwrap_mcp_config(cfg)
        assert inner is cfg
        assert name is None

    def test_single_named_key(self):
        """Single named key wrapping a config dict."""
        cfg = {"inference-sh": {"command": "docker", "args": ["run", "img"]}}
        inner, name = _unwrap_mcp_config(cfg)
        assert name == "inference-sh"
        assert inner["command"] == "docker"

    def test_single_named_key_no_config_keys(self):
        """Single named key but inner dict lacks config keys — returns as-is."""
        cfg = {"something": {"foo": "bar"}}
        inner, name = _unwrap_mcp_config(cfg)
        assert inner is cfg
        assert name is None


# --- _parse_direct_config ---


class TestParseDirectConfig:
    """Tests for the main config parser entry point."""

    def test_stdio_bare_config(self):
        """Bare stdio config is parsed correctly."""
        cfg = {"command": "npx", "args": ["-y", "@example/mcp-server"], "env": {"API_KEY": "xxx"}}
        result = _parse_direct_config(cfg)
        assert result["transport"] == "stdio"
        assert result["command"] == "npx"
        assert result["args"] == ["-y", "@example/mcp-server"]
        assert result["framework"] == "typescript"
        assert any(ev["name"] == "API_KEY" for ev in result["environment_variables"])

    def test_stdio_python_framework(self):
        """Python command is detected."""
        cfg = {"command": "python3", "args": ["-m", "myserver"]}
        result = _parse_direct_config(cfg)
        assert result["framework"] == "python"

    def test_stdio_docker_framework(self):
        """Docker command extracts docker_image."""
        cfg = {"command": "docker", "args": ["run", "-i", "--rm", "myimage:latest"]}
        result = _parse_direct_config(cfg)
        assert result["framework"] == "docker"
        assert result["docker_image"] == "myimage:latest"

    def test_stdio_unknown_framework(self):
        """Unknown command results in None framework."""
        cfg = {"command": "mybin", "args": []}
        result = _parse_direct_config(cfg)
        assert result["framework"] is None

    def test_sse_config(self):
        """SSE config with URL is parsed."""
        cfg = {"url": "https://api.example.com/mcp", "type": "sse"}
        result = _parse_direct_config(cfg)
        assert result["transport"] == "sse"
        assert result["url"] == "https://api.example.com/mcp"

    def test_sse_default_type(self):
        """SSE config without explicit type defaults to 'sse'."""
        cfg = {"url": "https://api.example.com/mcp"}
        result = _parse_direct_config(cfg)
        assert result["transport"] == "sse"

    def test_sse_with_headers(self):
        """SSE config with headers dict converts to list."""
        cfg = {
            "url": "http://x.com",
            "type": "sse",
            "headers": {"Authorization": "Bearer tok"},
        }
        result = _parse_direct_config(cfg)
        assert len(result["headers"]) == 1
        assert result["headers"][0]["name"] == "Authorization"
        assert result["headers"][0]["value"] == "Bearer tok"

    def test_sse_with_auto_approve(self):
        """autoApprove is mapped to auto_approve."""
        cfg = {"url": "http://x.com", "autoApprove": ["read_file", "list_dir"]}
        result = _parse_direct_config(cfg)
        assert result["auto_approve"] == ["read_file", "list_dir"]

    def test_wrapped_mcp_servers_format(self):
        """Handles mcpServers wrapper and extracts server name."""
        cfg = {"mcpServers": {"my-mcp": {"command": "node", "args": ["server.js"], "env": {"PORT": "8080"}}}}
        result = _parse_direct_config(cfg)
        assert result["_server_name"] == "my-mcp"
        assert result["command"] == "node"
        assert result["framework"] == "typescript"

    def test_server_json_manifest_delegated(self):
        """server.json manifest is handled by _parse_server_json_manifest."""
        cfg = {"remotes": [{"url": "https://api.example.com/mcp", "type": "sse", "variables": {"KEY": {}}}]}
        result = _parse_direct_config(cfg)
        assert result["url"] == "https://api.example.com/mcp"
        assert result["transport"] == "sse"

    def test_dollar_var_detection_in_args(self):
        """$VAR references in args are detected."""
        cfg = {"command": "npx", "args": ["-y", "server", "--token", "$MY_TOKEN"]}
        result = _parse_direct_config(cfg)
        assert "MY_TOKEN" in (result.get("_dollar_vars_detected") or [])
        # Should also be in environment_variables
        names = {ev["name"] for ev in result.get("environment_variables", [])}
        assert "MY_TOKEN" in names

    def test_dollar_var_detection_in_env_values(self):
        """$VAR references in env values are detected."""
        cfg = {"command": "npx", "args": [], "env": {"TOKEN": "$SECRET_TOKEN"}}
        result = _parse_direct_config(cfg)
        assert "SECRET_TOKEN" in (result.get("_dollar_vars_detected") or [])

    def test_env_as_list_passthrough(self):
        """Env dict keys become environment_variables list."""
        cfg = {"command": "npx", "args": [], "env": {"A": "1", "B": "2"}}
        result = _parse_direct_config(cfg)
        names = {ev["name"] for ev in result["environment_variables"]}
        assert names == {"A", "B"}

    def test_registry_format_end_to_end(self):
        """Full registry format through _parse_direct_config."""
        cfg = {
            "server": {
                "title": "My MCP",
                "description": "Does things",
                "remotes": [
                    {
                        "type": "streamable-http",
                        "url": "https://my.server/mcp",
                        "variables": {"API_KEY": {"description": "Key"}},
                    }
                ],
            },
            "_meta": {"version": "1.0"},
        }
        result = _parse_direct_config(cfg)
        assert result["_server_name"] == "My MCP"
        assert result["_description"] == "Does things"
        assert result["url"] == "https://my.server/mcp"
        assert result["transport"] == "streamable-http"
        assert result["environment_variables"][0]["name"] == "API_KEY"

    def test_sse_dollar_var_in_header_values(self):
        """$VAR in header values are detected and added to env vars."""
        cfg = {
            "url": "http://x.com",
            "type": "sse",
            "headers": {"Authorization": "Bearer $API_TOKEN"},
        }
        result = _parse_direct_config(cfg)
        assert "API_TOKEN" in (result.get("_dollar_vars_detected") or [])
        names = {ev["name"] for ev in result.get("environment_variables", [])}
        assert "API_TOKEN" in names

    def test_stdio_auto_approve(self):
        """autoApprove on stdio config is mapped to auto_approve."""
        cfg = {"command": "npx", "args": ["-y", "server"], "autoApprove": ["read", "write"]}
        result = _parse_direct_config(cfg)
        assert result["auto_approve"] == ["read", "write"]
