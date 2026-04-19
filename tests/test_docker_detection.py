"""Tests for docker image detection, command/args inference, direct config parsing,
and config preview building."""

import tempfile
from pathlib import Path


def _make_tmpdir_with_files(file_map: dict[str, str]) -> str:
    """Create a temp directory with the given file tree. Returns path."""
    tmp = tempfile.mkdtemp(prefix="observal_test_")
    for relpath, content in file_map.items():
        full = Path(tmp) / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return tmp


# ═══════════════════════════════════════════════════════════
# 1. CLI _detect_docker_image
# ═══════════════════════════════════════════════════════════


class TestDetectDockerImageCli:
    """Tests for observal_cli.analyzer._detect_docker_image."""

    def test_compose_image(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files(
            {"docker-compose.yml": "services:\n  mcp:\n    image: ghcr.io/org/my-server:latest\n"}
        )
        image, suggested = _detect_docker_image(Path(tmp), "https://github.com/org/repo")
        assert image == "ghcr.io/org/my-server:latest"
        assert suggested is False

    def test_compose_build_only_no_image(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files({"docker-compose.yml": "services:\n  mcp:\n    build: .\n"})
        image, suggested = _detect_docker_image(Path(tmp), "https://github.com/org/repo")
        # Falls through to GHCR inference since compose has no image
        assert image == "ghcr.io/org/repo"
        assert suggested is True

    def test_readme_ghcr_reference(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files({"README.md": "Run with:\n```\ndocker run ghcr.io/myorg/my-mcp-server\n```\n"})
        image, suggested = _detect_docker_image(Path(tmp), "https://gitlab.com/org/repo")
        assert image == "ghcr.io/myorg/my-mcp-server"
        assert suggested is False

    def test_ghcr_inferred_from_github_url(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files({"src/main.py": "# no docker files"})
        image, suggested = _detect_docker_image(Path(tmp), "https://github.com/acme/cool-server")
        assert image == "ghcr.io/acme/cool-server"
        assert suggested is True

    def test_ghcr_strips_dot_git(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files({"src/main.py": ""})
        image, suggested = _detect_docker_image(Path(tmp), "https://github.com/org/repo.git")
        assert image == "ghcr.io/org/repo"
        assert suggested is True

    def test_no_detection_non_github(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files({"src/main.py": ""})
        image, suggested = _detect_docker_image(Path(tmp), "https://gitlab.com/org/repo")
        assert image is None

    def test_compose_takes_priority_over_readme(self):
        from observal_cli.analyzer import _detect_docker_image

        tmp = _make_tmpdir_with_files(
            {
                "docker-compose.yml": "services:\n  mcp:\n    image: registry.io/org/compose-img\n",
                "README.md": "docker run ghcr.io/org/readme-img\n",
            }
        )
        image, suggested = _detect_docker_image(Path(tmp), "https://github.com/org/repo")
        assert image == "registry.io/org/compose-img"
        assert suggested is False


# ═══════════════════════════════════════════════════════════
# 2. Server _detect_docker_image
# ═══════════════════════════════════════════════════════════


class TestDetectDockerImageServer:
    """Tests for services.mcp_validator._detect_docker_image."""

    def test_readme_pattern(self):
        from services.mcp_validator import _detect_docker_image

        tmp = _make_tmpdir_with_files({"README.md": "Use ghcr.io/org/my-server to run"})
        image, suggested = _detect_docker_image(Path(tmp), "https://gitlab.com/org/repo")
        assert image == "ghcr.io/org/my-server"
        assert suggested is False

    def test_ghcr_inference(self):
        from services.mcp_validator import _detect_docker_image

        tmp = _make_tmpdir_with_files({"main.py": ""})
        image, suggested = _detect_docker_image(Path(tmp), "https://github.com/org/server")
        assert image == "ghcr.io/org/server"
        assert suggested is True

    def test_server_matches_cli(self):
        """Both implementations should return the same results."""
        from observal_cli.analyzer import _detect_docker_image as cli_detect
        from services.mcp_validator import _detect_docker_image as server_detect

        test_cases = [
            ({"README.md": "Run ghcr.io/org/my-img"}, "https://github.com/org/repo"),
            ({"src/main.py": ""}, "https://github.com/acme/server"),
            ({"src/main.py": ""}, "https://gitlab.com/org/repo"),
        ]
        for files, url in test_cases:
            tmp = _make_tmpdir_with_files(files)
            root = Path(tmp)
            cli_result = cli_detect(root, url)
            server_result = server_detect(root, url)
            assert cli_result == server_result, f"Mismatch for files={files}, url={url}"


# ═══════════════════════════════════════════════════════════
# 3. _infer_command_args
# ═══════════════════════════════════════════════════════════


class TestInferCommandArgs:
    """Tests for _infer_command_args from the CLI analyzer."""

    def test_docker_image(self):
        from observal_cli.analyzer import _infer_command_args

        cmd, args = _infer_command_args(None, "ghcr.io/org/server", "my-mcp")
        assert cmd == "docker"
        assert args == ["run", "-i", "--rm", "ghcr.io/org/server"]

    def test_typescript(self):
        from observal_cli.analyzer import _infer_command_args

        cmd, args = _infer_command_args("typescript-mcp-sdk", None, "my-mcp")
        assert cmd == "npx"
        assert args == ["-y", "my-mcp"]

    def test_go(self):
        from observal_cli.analyzer import _infer_command_args

        cmd, args = _infer_command_args("go-mcp-sdk", None, "my-mcp")
        assert cmd == "my-mcp"
        assert args == []

    def test_python(self):
        from observal_cli.analyzer import _infer_command_args

        cmd, args = _infer_command_args("python-mcp", None, "my-mcp")
        assert cmd == "python"
        assert args == ["-m", "my-mcp"]

    def test_python_from_entry_point(self):
        from observal_cli.analyzer import _infer_command_args

        cmd, args = _infer_command_args(None, None, "my-mcp", entry_point="src/main.py")
        assert cmd == "python"
        assert args == ["-m", "my-mcp"]

    def test_docker_overrides_framework(self):
        from observal_cli.analyzer import _infer_command_args

        for fw in ("python-mcp", "typescript-mcp-sdk", "go-mcp-sdk"):
            cmd, args = _infer_command_args(fw, "img:latest", "my-mcp")
            assert cmd == "docker", f"Framework {fw} with docker_image should use docker"
            assert "img:latest" in args

    def test_no_framework_no_image(self):
        from observal_cli.analyzer import _infer_command_args

        cmd, args = _infer_command_args(None, None, "my-mcp")
        assert cmd is None
        assert args is None

    def test_server_matches_cli(self):
        """Both implementations should return the same results."""
        from observal_cli.analyzer import _infer_command_args as cli_infer
        from services.mcp_validator import _infer_command_args as server_infer

        test_cases = [
            ("python-mcp", None, "my-mcp", None),
            ("typescript-mcp-sdk", None, "my-mcp", None),
            ("go-mcp-sdk", None, "my-mcp", None),
            (None, "ghcr.io/org/img", "my-mcp", None),
            (None, None, "my-mcp", "main.py"),
            (None, None, "my-mcp", None),
        ]
        for fw, img, name, ep in test_cases:
            cli_result = cli_infer(fw, img, name, ep)
            server_result = server_infer(fw, img, name, ep)
            assert cli_result == server_result, f"Mismatch for ({fw}, {img}, {name}, {ep})"


# ═══════════════════════════════════════════════════════════
# 4. _parse_direct_config
# ═══════════════════════════════════════════════════════════


class TestParseDirectConfig:
    """Tests for observal_cli.cmd_mcp._parse_direct_config."""

    def test_stdio_docker(self):
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {
            "command": "docker",
            "args": ["run", "-i", "--rm", "ghcr.io/org/server"],
            "env": {"MY_TOKEN": "abc"},
        }
        parsed = _parse_direct_config(cfg)
        assert parsed["transport"] == "stdio"
        assert parsed["framework"] == "docker"
        assert parsed["command"] == "docker"
        assert parsed["docker_image"] == "ghcr.io/org/server"
        assert len(parsed["environment_variables"]) == 1
        assert parsed["environment_variables"][0]["name"] == "MY_TOKEN"

    def test_stdio_python(self):
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {"command": "python", "args": ["-m", "my_server"]}
        parsed = _parse_direct_config(cfg)
        assert parsed["framework"] == "python"
        assert parsed["command"] == "python"
        assert parsed["args"] == ["-m", "my_server"]

    def test_sse_with_headers(self):
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {
            "type": "sse",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer tok", "X-Custom": "val"},
            "autoApprove": ["search", "read"],
        }
        parsed = _parse_direct_config(cfg)
        assert parsed["transport"] == "sse"
        assert parsed["url"] == "https://example.com/mcp"
        assert len(parsed["headers"]) == 2
        assert parsed["headers"][0]["name"] == "Authorization"
        assert parsed["auto_approve"] == ["search", "read"]

    def test_sse_defaults_type(self):
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {"url": "https://example.com/mcp"}
        parsed = _parse_direct_config(cfg)
        assert parsed["transport"] == "sse"
        assert parsed["url"] == "https://example.com/mcp"

    def test_npx_framework(self):
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {"command": "npx", "args": ["-y", "my-package"]}
        parsed = _parse_direct_config(cfg)
        assert parsed["framework"] == "typescript"

    def test_unwrap_mcpservers_wrapper(self):
        """Full mcpServers wrapper should be unwrapped and server name extracted."""
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {
            "mcpServers": {
                "github": {
                    "command": "docker",
                    "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "your-token"},
                    "disabled": False,
                    "autoApprove": [],
                }
            }
        }
        parsed = _parse_direct_config(cfg)
        assert parsed["_server_name"] == "github"
        assert parsed["command"] == "docker"
        assert parsed["docker_image"] == "ghcr.io/github/github-mcp-server"
        assert len(parsed["environment_variables"]) == 1

    def test_unwrap_named_server(self):
        """Single named key wrapping a config dict should be unwrapped."""
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {
            "gitlab": {
                "command": "docker",
                "args": ["run", "--rm", "-i", "-env", "GITLAB_TOKEN", "registry.example.com/gitlab-mcp-server:latest"],
                "env": {"GITLAB_TOKEN": "your-token"},
            }
        }
        parsed = _parse_direct_config(cfg)
        assert parsed["_server_name"] == "gitlab"
        assert parsed["command"] == "docker"
        assert parsed["docker_image"] == "registry.example.com/gitlab-mcp-server:latest"

    def test_unwrap_sse_from_mcpservers(self):
        """SSE config inside mcpServers wrapper should be parsed correctly."""
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {
            "mcpServers": {
                "docs-server": {
                    "type": "sse",
                    "url": "https://docs-api.example.com",
                    "headers": {"Authorization": ""},
                    "autoApprove": ["search_knowledge_sources"],
                }
            }
        }
        parsed = _parse_direct_config(cfg)
        assert parsed["_server_name"] == "docs-server"
        assert parsed["transport"] == "sse"
        assert parsed["url"] == "https://docs-api.example.com"
        assert parsed["headers"][0]["name"] == "Authorization"
        assert parsed["auto_approve"] == ["search_knowledge_sources"]

    def test_docker_with_volume_mounts_and_env_flags(self):
        """Complex docker args with -v mounts and -env flags (Jira-style)."""
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {
            "command": "docker",
            "args": [
                "--rm", "-i",
                "-v", "/Users/user/Downloads/Jira Attachments:/tmp",
                "-env", "JIRA_EMAIL", "-env", "JIRA_TOKEN", "-env", "JIRA_URL",
                "registry.example.com/jira-mcp-proxy:latest",
            ],
            "env": {
                "JIRA_URL": "https://my-org.atlassian.net",
                "JIRA_EMAIL": "user@example.com",
                "JIRA_TOKEN": "token",
            },
        }
        parsed = _parse_direct_config(cfg)
        assert parsed["command"] == "docker"
        assert parsed["docker_image"] == "registry.example.com/jira-mcp-proxy:latest"
        assert len(parsed["environment_variables"]) == 3

    def test_unknown_command_still_parses(self):
        """Any command type should be accepted, framework is just None."""
        from observal_cli.cmd_mcp import _parse_direct_config

        cfg = {"command": "my-custom-binary", "args": ["--serve"]}
        parsed = _parse_direct_config(cfg)
        assert parsed["command"] == "my-custom-binary"
        assert parsed["args"] == ["--serve"]
        assert parsed["framework"] is None


# ═══════════════════════════════════════════════════════════
# 5. _build_config_preview
# ═══════════════════════════════════════════════════════════


class TestBuildConfigPreview:
    """Tests for observal_cli.cmd_mcp._build_config_preview."""

    def test_stdio_preview(self):
        from observal_cli.cmd_mcp import _build_config_preview

        parsed = {
            "command": "docker",
            "args": ["run", "-i", "--rm", "ghcr.io/org/server"],
            "environment_variables": [
                {"name": "MY_TOKEN", "description": "", "required": True},
            ],
        }
        preview = _build_config_preview("my-server", parsed)
        server = preview["my-server"]
        assert server["command"] == "docker"
        # -e flags should be injected before the image
        assert "-e" in server["args"]
        assert "MY_TOKEN=<MY_TOKEN>" in server["args"]
        assert server["env"] == {"MY_TOKEN": "<MY_TOKEN>"}

    def test_sse_preview(self):
        from observal_cli.cmd_mcp import _build_config_preview

        parsed = {
            "transport": "sse",
            "url": "https://example.com/mcp",
            "headers": [
                {"name": "Authorization", "description": "Bearer token", "required": True},
            ],
            "auto_approve": ["tool_name"],
            "environment_variables": [],
        }
        preview = _build_config_preview("my-sse-server", parsed)
        server = preview["my-sse-server"]
        assert server["type"] == "sse"
        assert server["url"] == "https://example.com/mcp"
        assert server["headers"] == {"Authorization": "<Authorization>"}
        assert server["autoApprove"] == ["tool_name"]
        assert server["disabled"] is False
