# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from sqlalchemy import Index

from models.agent import Agent
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing


def test_registry_models_have_global_name_constraints():
    expected = {
        McpListing: "uq_mcp_listings_name",
        SkillListing: "uq_skill_listings_name",
        HookListing: "uq_hook_listings_name",
        PromptListing: "uq_prompt_listings_name",
        SandboxListing: "uq_sandbox_listings_name",
    }

    agent_indexes = {index.name: index for index in Agent.__table__.indexes if isinstance(index, Index)}
    assert "uq_agents_active_name" in agent_indexes
    assert agent_indexes["uq_agents_active_name"].unique is True
    assert {column.name for column in agent_indexes["uq_agents_active_name"].columns} == {"name"}

    for model, constraint_name in expected.items():
        constraints = {constraint.name: constraint for constraint in model.__table__.constraints}
        assert constraint_name in constraints
        assert {column.name for column in constraints[constraint_name].columns} == {"name"}
