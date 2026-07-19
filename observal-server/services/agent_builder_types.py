# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Portable agent manifest and composition models."""

from pydantic import BaseModel, Field


class ManifestComponent(BaseModel):
    """A single component entry in the agent manifest."""

    name: str
    version: str
    git_url: str = ""
    description: str = ""
    order: int = 0
    git_ref: str | None = None
    config_override: dict | None = None
    # MCP-specific
    transport: str | None = None
    tools: dict | None = None
    # Skill-specific
    slash_command: str | None = None
    task_type: str | None = None
    # Hook-specific
    event: str | None = None
    execution_mode: str | None = None
    priority: int | None = None
    handler_type: str | None = None
    handler_config: dict | None = None
    # Prompt-specific
    template: str | None = None
    variables: list[str] | None = None
    # Sandbox-specific
    image: str | None = None
    runtime_type: str | None = None
    resource_limits: dict | None = None
    network_policy: str | None = None
    entrypoint: str | None = None
    runtime_config: dict | None = None

    def model_dump_compact(self) -> dict:
        """Dump only non-None fields for clean manifest output."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ManifestComponents(BaseModel):
    """All components grouped by type."""

    mcps: list[ManifestComponent] = Field(default_factory=list)
    skills: list[ManifestComponent] = Field(default_factory=list)
    hooks: list[ManifestComponent] = Field(default_factory=list)
    prompts: list[ManifestComponent] = Field(default_factory=list)
    sandboxes: list[ManifestComponent] = Field(default_factory=list)

    def model_dump_compact(self) -> dict:
        """Only include non-empty component lists."""
        result = {}
        for key, items in [
            ("mcps", self.mcps),
            ("skills", self.skills),
            ("hooks", self.hooks),
            ("prompts", self.prompts),
            ("sandboxes", self.sandboxes),
        ]:
            if items:
                result[key] = [c.model_dump_compact() for c in items]
        return result


class ManifestError(BaseModel):
    component_type: str
    component_id: str
    reason: str


class AgentManifest(BaseModel):
    """Portable agent manifest - the canonical representation of a composed agent."""

    name: str
    version: str
    prompt: str = ""
    description: str = ""
    model_name: str = ""
    models_by_harness: dict[str, str] = Field(default_factory=dict)
    components: ManifestComponents = Field(default_factory=ManifestComponents)
    errors: list[ManifestError] = Field(default_factory=list)

    def model_dump_compact(self) -> dict:
        """Clean manifest output (no empty lists, no None values)."""
        result: dict = {
            "name": self.name,
            "version": self.version,
            "components": self.components.model_dump_compact(),
        }
        if self.prompt:
            result["prompt"] = self.prompt
        if self.description:
            result["description"] = self.description
        if self.model_name:
            result["model_name"] = self.model_name
        if self.models_by_harness:
            result["models_by_harness"] = dict(self.models_by_harness)
        if self.errors:
            result["errors"] = [e.model_dump() for e in self.errors]
        return result


class CompositionSummary(BaseModel):
    """Lightweight summary of agent composition for API responses."""

    agent_id: str
    agent_name: str
    agent_version: str
    resolved: bool
    component_counts: dict[str, int] = Field(default_factory=dict)
    components: dict[str, list[dict]] = Field(default_factory=dict)
    errors: list[ManifestError] = Field(default_factory=list)
