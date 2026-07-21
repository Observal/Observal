# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from sqlalchemy import Index

from models.agent import Agent
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing


def test_registry_models_have_namespace_slug_constraints():
    expected = {
        McpListing: "uq_mcp_listings_namespace_slug",
        SkillListing: "uq_skill_listings_namespace_slug",
        HookListing: "uq_hook_listings_namespace_slug",
        PromptListing: "uq_prompt_listings_namespace_slug",
        SandboxListing: "uq_sandbox_listings_namespace_slug",
    }

    agent_indexes = {index.name: index for index in Agent.__table__.indexes if isinstance(index, Index)}
    index = agent_indexes["uq_agents_active_namespace_slug"]
    assert index.unique is True
    assert {column.name for column in index.columns} == {"namespace", "slug"}

    for model, constraint_name in expected.items():
        constraints = {constraint.name: constraint for constraint in model.__table__.constraints}
        assert constraint_name in constraints
        assert {column.name for column in constraints[constraint_name].columns} == {"namespace", "slug"}
