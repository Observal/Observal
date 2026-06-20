# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Local repository analysis for MCP server submissions."""

from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
from pathlib import Path

from loguru import logger as optic
from observal_shared.mcp_analysis import (
    analyze_python_entry,
    detect_docker_image,
    detect_env_vars,
    detect_non_python_mcp,
    extract_repo_name,
    find_python_entry,
    infer_command_args,
    is_filtered_env_var,
    is_test_file,
)

_is_filtered_env_var = is_filtered_env_var
_is_test_file = is_test_file
_detect_env_vars = detect_env_vars
_detect_docker_image = detect_docker_image
_infer_command_args = infer_command_args
_detect_non_python_mcp = detect_non_python_mcp
_extract_repo_name = extract_repo_name
_analyze_python_entry = analyze_python_entry

_CLONE_TIMEOUT = 120


def _clone_repo(git_url: str, dest: str) -> str | None:
    """Shallow-clone a repo using system git. Returns error string or None on success."""
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", git_url, dest],
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT,
        )
    except FileNotFoundError:
        return "git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return f"Clone timed out after {_CLONE_TIMEOUT}s"

    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        auth_hints = ("authentication", "403", "404", "could not read username", "terminal prompts disabled")
        if any(hint in stderr for hint in auth_hints):
            return "Repository is private or not accessible."
        if "not found" in stderr or "does not exist" in stderr:
            return "Repository not found. Check the URL."
        return f"git clone failed: {result.stderr.strip()}"
    return None


def _non_python_result(git_url: str, tmp_dir: str, env_vars: list[dict]) -> dict:
    non_python = detect_non_python_mcp(tmp_dir)
    name = extract_repo_name(git_url, tmp_dir)
    docker_image, docker_suggested = detect_docker_image(Path(tmp_dir), git_url)
    cmd, cmd_args = infer_command_args(non_python, docker_image, name)
    result: dict = {
        "name": name,
        "description": "",
        "version": "0.1.0",
        "tools": [],
        "environment_variables": env_vars,
    }
    if non_python:
        result["framework"] = non_python
    if docker_image:
        result["docker_image"] = docker_image
        result["docker_image_suggested"] = docker_suggested
    if cmd:
        result["command"] = cmd
        result["args"] = cmd_args
    return result


def analyze_local(git_url: str) -> dict:
    """Clone a repo locally and analyze it for MCP metadata."""
    optic.trace("git_url={}", git_url)
    empty: dict = {"name": "", "description": "", "version": "0.1.0", "tools": []}

    tmp_dir = tempfile.mkdtemp(prefix="observal_cli_analyze_")
    try:
        clone_err = _clone_repo(git_url, tmp_dir)
        if clone_err:
            return {**empty, "error": clone_err}

        entry_point = find_python_entry(tmp_dir)
        env_vars = detect_env_vars(tmp_dir)
        if not entry_point:
            return _non_python_result(git_url, tmp_dir, env_vars)

        tree = ast.parse(entry_point.read_text(errors="ignore"))
        server_name, server_desc, tools, issues = analyze_python_entry(tree, git_url, tmp_dir)
        relative_entry = str(entry_point.relative_to(tmp_dir))
        docker_image, docker_suggested = detect_docker_image(Path(tmp_dir), git_url)
        cmd, cmd_args = infer_command_args("python", docker_image, server_name, relative_entry)

        result: dict = {
            "name": server_name,
            "description": server_desc,
            "version": "0.1.0",
            "tools": tools,
            "issues": issues,
            "environment_variables": env_vars,
            "entry_point": relative_entry,
        }
        if docker_image:
            result["docker_image"] = docker_image
            result["docker_image_suggested"] = docker_suggested
        if cmd:
            result["command"] = cmd
            result["args"] = cmd_args
        return result
    except Exception:
        return {**empty, "error": "Local analysis failed unexpectedly."}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
