# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for `observal team` commands. Client is mocked, no live server."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()

# All team commands are gated on server_supports("teamspaces"); mock it True.


@pytest.fixture(autouse=True)
def _support_teamspaces():
    with patch("observal_cli.client.server_supports", return_value=True):
        yield


def _teams_all():
    return [
        {"id": "t1", "name": "Platform Tools", "handle": "platform-tools", "role": None, "member_count": 3},
        {"id": "t2", "name": "SRE", "handle": "sre", "role": "owner", "member_count": 1},
    ]


def _members():
    return [
        {"id": "u1", "email": "alice@example.com", "username": "alice", "name": "Alice", "role": "owner"},
        {"id": "u2", "email": "bob@example.com", "username": "bob", "name": "Bob", "role": "member"},
    ]


def test_team_list_calls_mine_endpoint():
    with patch("observal_cli.cmd_team.client.get", return_value=_teams_all()) as mock_get:
        result = runner.invoke(app, ["team", "list", "--output", "json"])
    assert result.exit_code == 0, result.output
    assert mock_get.call_args.args[0] == "/api/v1/teams"
    assert "platform-tools" in result.output


def test_team_list_all_uses_all_endpoint():
    with patch("observal_cli.cmd_team.client.get", return_value=_teams_all()) as mock_get:
        result = runner.invoke(app, ["team", "list", "--all", "--output", "json"])
    assert result.exit_code == 0, result.output
    assert mock_get.call_args.args[0] == "/api/v1/teams/all"


def test_team_create_posts_handle_and_name():
    with patch("observal_cli.cmd_team.client.post", return_value={"id": "t9", "name": "X", "handle": "x"}) as mock_post:
        result = runner.invoke(app, ["team", "create", "X", "--handle", "x", "--description", "d"])
    assert result.exit_code == 0, result.output
    body = mock_post.call_args.kwargs["json_data"]
    assert body == {"name": "X", "handle": "x", "description": "d"}
    assert mock_post.call_args.args[0] == "/api/v1/teams"


def test_team_show_resolves_handle_to_id():
    with patch(
        "observal_cli.cmd_team.client.get",
        side_effect=[_teams_all(), {"name": "SRE", "handle": "sre", "role": "owner"}, _members()],
    ) as mock_get:
        result = runner.invoke(app, ["team", "show", "sre"])
    assert result.exit_code == 0, result.output
    # First call resolves handle -> id via /teams/all, then detail + members.
    paths = [call.args[0] for call in mock_get.call_args_list]
    assert paths[0] == "/api/v1/teams/all"
    assert paths[1] == "/api/v1/teams/t2"
    assert paths[2] == "/api/v1/teams/t2/members"
    assert "SRE" in result.output


def test_team_show_accepts_uuid_directly():
    uid = "11111111-1111-1111-1111-111111111111"
    with patch(
        "observal_cli.cmd_team.client.get", side_effect=[{"name": "SRE", "handle": "sre", "role": "owner"}, _members()]
    ) as mock_get:
        result = runner.invoke(app, ["team", "show", uid])
    assert result.exit_code == 0, result.output
    # No /teams/all resolution when a UUID is passed.
    assert mock_get.call_args_list[0].args[0] == f"/api/v1/teams/{uid}"


def test_team_members_add_sends_email_or_username():
    uid = "11111111-1111-1111-1111-111111111111"
    with patch(
        "observal_cli.cmd_team.client.post", return_value={"email": "bob@example.com", "role": "reviewer"}
    ) as mock_post:
        result = runner.invoke(app, ["team", "members", "add", uid, "bob@example.com", "--role", "reviewer"])
    assert result.exit_code == 0, result.output
    assert mock_post.call_args.args[0] == f"/api/v1/teams/{uid}/members"
    assert mock_post.call_args.kwargs["json_data"] == {"role": "reviewer", "email": "bob@example.com"}


def test_team_members_add_username_strips_at_prefix():
    uid = "11111111-1111-1111-1111-111111111111"
    with patch("observal_cli.cmd_team.client.post", return_value={"email": "b@x", "role": "member"}) as mock_post:
        result = runner.invoke(app, ["team", "members", "add", uid, "@alice"])
    assert result.exit_code == 0, result.output
    assert mock_post.call_args.kwargs["json_data"] == {"role": "member", "username": "alice"}


def test_team_members_remove_resolves_member_by_username():
    uid = "11111111-1111-1111-1111-111111111111"
    with (
        patch("observal_cli.cmd_team.client.get", return_value=_members()) as mock_get,
        patch("observal_cli.cmd_team.client.delete", return_value={}) as mock_del,
    ):
        result = runner.invoke(app, ["team", "members", "remove", uid, "@bob", "-y"])
    assert result.exit_code == 0, result.output
    assert mock_get.call_args.args[0] == f"/api/v1/teams/{uid}/members"
    assert mock_del.call_args.args[0] == f"/api/v1/teams/{uid}/members/u2"


def test_team_members_remove_unknown_user_errors():
    uid = "11111111-1111-1111-1111-111111111111"
    with patch("observal_cli.cmd_team.client.get", return_value=_members()):
        result = runner.invoke(app, ["team", "members", "remove", uid, "@nobody", "-y"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_team_delete_requires_confirmation_without_yes():
    uid = "11111111-1111-1111-1111-111111111111"
    with patch("observal_cli.cmd_team.client.delete") as mock_del:
        result = runner.invoke(app, ["team", "delete", uid], input="n\n")
    assert result.exit_code != 0
    mock_del.assert_not_called()


def test_team_leave_posts_leave_endpoint():
    uid = "11111111-1111-1111-1111-111111111111"
    with patch("observal_cli.cmd_team.client.post", return_value={}) as mock_post:
        result = runner.invoke(app, ["team", "leave", uid])
    assert result.exit_code == 0, result.output
    assert mock_post.call_args.args[0] == f"/api/v1/teams/{uid}/leave"


@pytest.mark.parametrize("bad", ["not-a-uuid", "missing-team"])
def test_team_show_unknown_handle_errors(bad: str):
    with patch("observal_cli.cmd_team.client.get", return_value=_teams_all()):
        result = runner.invoke(app, ["team", "show", bad])
    assert result.exit_code != 0


def test_team_commands_blocked_when_server_unsupported():
    """On an older server without teamspaces, commands exit cleanly with a message."""
    with patch("observal_cli.client.server_supports", return_value=False):
        result = runner.invoke(app, ["team", "list"])
    assert result.exit_code == 1
    assert "not supported" in result.output
