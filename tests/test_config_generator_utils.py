# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from observal_cli.cmd_pull import _dict_to_toml, _write_file
from observal_cli.cmd_scan import _parse_project_mcp_servers


def test_dict_to_toml():
    d = {"mcp.servers": {"my-server": {"command": "npx", "args": ["a", "b"], "env": {"K": "V"}}}}
    toml = _dict_to_toml(d)
    assert "[mcp.servers.my-server]" in toml
    assert 'command = "npx"' in toml
    assert 'args = ["a", "b"]' in toml
    assert 'env.K = "V"' in toml


def test_parse_project_mcp_servers():
    codex_conf = {"mcp": {"servers": {"c-serv": {}}}}
    gemini_conf = {"mcpServers": {"g-serv": {}}}
    copilot_conf = {"servers": {"cp-serv": {}}}
    opencode_conf = {"mcp": {"o-serv": {}}}

    assert _parse_project_mcp_servers(codex_conf, "codex") == {"c-serv": {}}
    assert _parse_project_mcp_servers(gemini_conf, "gemini-cli") == {"g-serv": {}}
    assert _parse_project_mcp_servers(copilot_conf, "copilot") == {"cp-serv": {}}
    assert _parse_project_mcp_servers(opencode_conf, "opencode") == {"o-serv": {}}


def test_write_file_merge_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[mcp.servers.old]\ncommand = 'echo'\n")

    content = {"mcp.servers": {"new": {"command": "observal-shim"}}}
    res = _write_file(p, content, merge_mcp=True)
    assert res == "merged"

    merged = p.read_text()
    assert "[mcp.servers.old]" in merged
    assert "[mcp.servers.new]" in merged
    assert "observal-shim" in merged
