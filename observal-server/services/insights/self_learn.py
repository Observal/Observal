# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Self-learning pipeline: applies insight suggestions as pending registry items.

Takes a completed InsightReport's suggestions section and materializes them
into actionable registry submissions:
- config_additions → new AgentVersion with updated prompt (pending review)
- features_to_try (skills) → new SkillListing (pending review)
- features_to_try (hooks) → new HookListing (pending review)
- usage_patterns (copyable prompts) → new PromptListing (pending review)

All items enter the review queue under the agent owner's identity.

Selection: callers pass an optional `selection` dict with index arrays
to choose specific suggestions. Omit or pass None to apply all in a category.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml
from loguru import logger as optic
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent, AgentStatus, AgentVersion
from models.hook import HookListing, HookVersion
from models.insight_report import InsightReport, InsightReportStatus
from models.mcp import ListingStatus
from models.prompt import PromptListing, PromptVersion
from models.skill import SkillListing, SkillVersion
from models.user import User
from services.versioning import bump_version

# Separator appended before auto-generated additions to the system prompt
_SELF_LEARN_SEPARATOR = "\n\n# ── Auto-learned from Insights ──\n"

# Maximum slug length for generated names
_MAX_NAME_LEN = 48


async def apply_insight_suggestions(
    report_id: str,
    db: AsyncSession,
    triggered_by: uuid.UUID,
    selection: dict | None = None,
) -> dict:
    """Apply suggestions from a completed insight report.

    Args:
        report_id: The insight report to apply.
        db: Async DB session.
        triggered_by: The admin user triggering the apply.
        selection: Optional dict with keys config_indices, feature_indices,
                   pattern_indices. Each is a list of 0-based indices to apply.
                   None or missing key means apply all in that category.

    Returns a summary dict of what was created.
    """
    # Load report
    stmt = select(InsightReport).where(InsightReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if not report:
        raise ValueError("Report not found")
    if report.status != InsightReportStatus.completed:
        raise ValueError("Report is not completed")
    if report.applied_at is not None:
        raise ValueError("Suggestions have already been applied for this report")

    # Load agent
    agent_stmt = select(Agent).where(Agent.id == report.agent_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise ValueError("Agent not found")

    # Resolve the submitting user (agent owner)
    owner_user = await _resolve_owner_user(agent, db)
    submitter_id = owner_user.id if owner_user else triggered_by

    # Extract suggestions from narrative
    narrative = report.narrative or {}
    suggestions = narrative.get("suggestions", {})
    if not suggestions:
        raise ValueError("Report has no suggestions to apply")

    applied: dict = {
        "agent_version": None,
        "skills": [],
        "hooks": [],
        "prompts": [],
    }

    # Determine which indices to apply per category
    config_indices = _resolve_indices(
        selection.get("config_indices") if selection else None,
        suggestions.get("config_additions", []),
    )
    feature_indices = _resolve_indices(
        selection.get("feature_indices") if selection else None,
        suggestions.get("features_to_try", []),
    )
    pattern_indices = _resolve_indices(
        selection.get("pattern_indices") if selection else None,
        suggestions.get("usage_patterns", []),
    )

    # 1. Create SkillListings and HookListings from features_to_try
    features_to_try = suggestions.get("features_to_try", [])
    created_skill_ids: list[uuid.UUID] = []
    created_hook_ids: list[uuid.UUID] = []

    for idx in feature_indices:
        if idx >= len(features_to_try):
            continue
        feature = features_to_try[idx]
        # Never create MCPs from insights
        if _is_mcp_suggestion(feature):
            continue
        if _is_skill_suggestion(feature):
            skill_info = await _create_skill_listing(
                agent=agent,
                feature=feature,
                submitter_id=submitter_id,
                db=db,
            )
            if skill_info:
                applied["skills"].append(skill_info)
                created_skill_ids.append(uuid.UUID(skill_info["id"]))
        elif _is_hook_suggestion(feature):
            hook_info = await _create_hook_listing(
                agent=agent,
                feature=feature,
                submitter_id=submitter_id,
                db=db,
            )
            if hook_info:
                applied["hooks"].append(hook_info)
                created_hook_ids.append(uuid.UUID(hook_info["id"]))

    # 2. Create PromptListings from usage_patterns
    usage_patterns = suggestions.get("usage_patterns", [])
    created_prompt_ids: list[uuid.UUID] = []

    for idx in pattern_indices:
        if idx >= len(usage_patterns):
            continue
        pattern = usage_patterns[idx]
        if pattern.get("copyable_prompt"):
            prompt_info = await _create_prompt_listing(
                agent=agent,
                pattern=pattern,
                submitter_id=submitter_id,
                db=db,
            )
            if prompt_info:
                applied["prompts"].append(prompt_info)
                created_prompt_ids.append(uuid.UUID(prompt_info["id"]))

    # 3. Create new AgentVersion with selected config additions + linked components
    config_additions = suggestions.get("config_additions", [])
    selected_additions = [config_additions[i] for i in config_indices if i < len(config_additions)]

    if selected_additions or created_skill_ids or created_hook_ids or created_prompt_ids:
        version_info = await _create_agent_version_with_additions(
            agent=agent,
            config_additions=selected_additions,
            submitter_id=submitter_id,
            db=db,
            linked_skill_ids=created_skill_ids,
            linked_hook_ids=created_hook_ids,
            linked_prompt_ids=created_prompt_ids,
        )
        if version_info:
            applied["agent_version"] = version_info

    # Mark report as applied
    report.applied_at = datetime.now(UTC)
    report.applied_items = applied

    await db.commit()

    optic.info(
        "self_learn_applied",
        report_id=report_id,
        agent=agent.name,
        version_created=applied["agent_version"] is not None,
        skills_created=len(applied["skills"]),
        hooks_created=len(applied["hooks"]),
        prompts_created=len(applied["prompts"]),
    )

    return applied


async def handle_component_rejection(
    component_type: str,
    component_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Handle rejection of a self-learn component.

    When a component created by self-learn gets rejected:
    1. Find any InsightReport that references this component in applied_items.
    2. Remove the rejected item from the report's applied_items.
    3. If the agent version depends on the rejected component, mark it as withdrawn.

    Called from the review endpoint when rejecting a listing.
    """
    # Find reports that reference this component

    reports = await db.execute(
        select(InsightReport).where(
            InsightReport.applied_items.isnot(None),
        )
    )

    for report in reports.scalars().all():
        items = report.applied_items or {}
        modified = False

        # Check skills, hooks, prompts lists
        for category in ("skills", "hooks", "prompts"):
            entries = items.get(category, [])
            original_len = len(entries)
            items[category] = [e for e in entries if e.get("id") != str(component_id)]
            if len(items[category]) < original_len:
                modified = True

        if modified:
            report.applied_items = items

            # If an agent version was linked and depends on the rejected component,
            # withdraw it
            version_info = items.get("agent_version")
            if version_info and version_info.get("id"):
                await _withdraw_version_if_dependency_rejected(
                    version_id=uuid.UUID(version_info["id"]),
                    db=db,
                )

    await db.flush()


async def _withdraw_version_if_dependency_rejected(
    version_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Mark an agent version as withdrawn if it had a rejected dependency."""
    version_stmt = select(AgentVersion).where(AgentVersion.id == version_id)
    result = await db.execute(version_stmt)
    version = result.scalar_one_or_none()

    if version and version.status == AgentStatus.pending:
        version.status = AgentStatus.rejected
        version.description = (version.description or "") + " [auto-withdrawn: linked component rejected]"


def _resolve_indices(selected: list[int] | None, items: list) -> list[int]:
    """Return the indices to process. If selected is None, return all indices."""
    if selected is None:
        return list(range(len(items)))
    return [i for i in selected if 0 <= i < len(items)]


async def _resolve_owner_user(agent: Agent, db: AsyncSession) -> User | None:
    """Resolve the agent's owner to a User record."""
    if agent.created_by:
        stmt = select(User).where(User.id == agent.created_by)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    return None


async def _create_agent_version_with_additions(
    agent: Agent,
    config_additions: list[dict],
    submitter_id: uuid.UUID,
    db: AsyncSession,
    linked_skill_ids: list[uuid.UUID] | None = None,
    linked_hook_ids: list[uuid.UUID] | None = None,
    linked_prompt_ids: list[uuid.UUID] | None = None,
) -> dict | None:
    """Create a new pending AgentVersion with config_additions appended to the prompt.

    Links any created skills/hooks/prompts as AgentComponents so the review
    queue enforces approval dependency.
    """
    # Get the latest approved version
    latest_stmt = (
        select(AgentVersion)
        .where(
            AgentVersion.agent_id == agent.id,
            AgentVersion.status == AgentStatus.approved,
        )
        .order_by(AgentVersion.created_at.desc())
        .limit(1)
    )
    latest_result = await db.execute(latest_stmt)
    latest_version = latest_result.scalar_one_or_none()

    if not latest_version:
        optic.warning("self_learn_no_approved_version", agent=agent.name)
        return None

    # Build the new prompt with additions
    current_prompt = latest_version.prompt or ""
    additions_text = _build_additions_text(config_additions)

    # Even without text additions, we might be linking new components
    if not additions_text.strip() and not linked_skill_ids and not linked_hook_ids and not linked_prompt_ids:
        return None

    new_prompt = current_prompt
    if additions_text.strip():
        new_prompt = current_prompt + _SELF_LEARN_SEPARATOR + additions_text

    # Bump patch version
    current_ver = latest_version.version or "1.0.0"
    new_ver = bump_version(current_ver, "patch")

    # Ensure no version collision
    dup_stmt = select(AgentVersion).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.version == new_ver,
    )
    if (await db.execute(dup_stmt)).scalar_one_or_none():
        for _ in range(10):
            new_ver = bump_version(new_ver, "patch")
            dup_stmt = select(AgentVersion).where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.version == new_ver,
            )
            if not (await db.execute(dup_stmt)).scalar_one_or_none():
                break
        else:
            optic.error("self_learn_version_exhaustion", agent=agent.name)
            return None

    total_linked = len(linked_skill_ids or []) + len(linked_hook_ids or []) + len(linked_prompt_ids or [])
    desc_parts = []
    if config_additions:
        desc_parts.append(f"{len(config_additions)} prompt additions")
    if total_linked:
        desc_parts.append(f"{total_linked} linked components")
    description = "Self-learned from insights: " + ", ".join(desc_parts)

    now = datetime.now(UTC)
    new_version = AgentVersion(
        agent_id=agent.id,
        version=new_ver,
        description=description,
        prompt=new_prompt,
        model_name=latest_version.model_name,
        model_config_json=latest_version.model_config_json,
        models_by_ide=latest_version.models_by_ide,
        external_mcps=latest_version.external_mcps,
        supported_ides=latest_version.supported_ides,
        is_prerelease=False,
        status=AgentStatus.pending,
        released_by=submitter_id,
        released_at=now,
    )
    db.add(new_version)
    await db.flush()

    # Copy components from the latest version
    from models.agent_component import AgentComponent

    order_idx = 0
    for comp in latest_version.components or []:
        db.add(
            AgentComponent(
                agent_version_id=new_version.id,
                component_type=comp.component_type,
                component_id=comp.component_id,
                component_name=comp.component_name,
                resolved_version=comp.resolved_version,
                order_index=comp.order_index,
                config_override=comp.config_override,
            )
        )
        order_idx = max(order_idx, (comp.order_index or 0) + 1)

    # Link newly created skills
    for skill_id in linked_skill_ids or []:
        db.add(
            AgentComponent(
                agent_version_id=new_version.id,
                component_type="skill",
                component_id=skill_id,
                component_name="",
                resolved_version="1.0.0",
                order_index=order_idx,
            )
        )
        order_idx += 1

    # Link newly created hooks
    for hook_id in linked_hook_ids or []:
        db.add(
            AgentComponent(
                agent_version_id=new_version.id,
                component_type="hook",
                component_id=hook_id,
                component_name="",
                resolved_version="1.0.0",
                order_index=order_idx,
            )
        )
        order_idx += 1

    # Link newly created prompts
    for prompt_id in linked_prompt_ids or []:
        db.add(
            AgentComponent(
                agent_version_id=new_version.id,
                component_type="prompt",
                component_id=prompt_id,
                component_name="",
                resolved_version="1.0.0",
                order_index=order_idx,
            )
        )
        order_idx += 1

    return {
        "id": str(new_version.id),
        "version": new_ver,
        "additions_count": len(config_additions),
        "linked_components": total_linked,
    }


def _build_additions_text(config_additions: list[dict]) -> str:
    """Build text block from config_additions list."""
    lines = []
    for addition in config_additions:
        text = addition.get("addition", "").strip()
        if not text:
            continue
        where = addition.get("where", "system_prompt")
        why = addition.get("why", "")
        if where in ("system_prompt", "AGENTS.md", "agent_config"):
            if why:
                lines.append(f"# Reason: {why}")
            lines.append(text)
            lines.append("")
    return "\n".join(lines).strip()


def _is_skill_suggestion(feature: dict) -> bool:
    """Check if a features_to_try entry is a skill suggestion."""
    feature_name = (feature.get("feature") or "").lower()
    return "skill" in feature_name or "custom skill" in feature_name


def _is_hook_suggestion(feature: dict) -> bool:
    """Check if a features_to_try entry is a hook suggestion."""
    feature_name = (feature.get("feature") or "").lower()
    return "hook" in feature_name or "lifecycle" in feature_name or "pre-commit" in feature_name


def _is_mcp_suggestion(feature: dict) -> bool:
    """Check if a features_to_try entry is an MCP suggestion (skip these)."""
    feature_name = (feature.get("feature") or "").lower()
    return "mcp" in feature_name or "server" in feature_name


def _derive_name(agent_name: str, label: str, max_len: int = _MAX_NAME_LEN) -> str:
    """Generate a reasonable, readable slug from agent name and label.

    Extracts key action words from the label rather than truncating the
    full text. Aims for names like 'ultra-pi-scope-guard' not
    'ultra-pi-hook-that-checks-whether-planned-file-e'.
    """
    prefix = _slugify(agent_name)[:16].rstrip("-")

    # Extract meaningful words: nouns and verbs, skip filler
    suffix = _extract_keywords(label)
    if not suffix:
        suffix = _slugify(label)[:20]

    available = max_len - len(prefix) - 1
    if available < 4:
        return _slugify(label)[:max_len]
    suffix = suffix[:available].rstrip("-")

    combined = f"{prefix}-{suffix}".rstrip("-")
    return combined or "unnamed"


def _extract_keywords(text: str, max_words: int = 4) -> str:
    """Extract up to max_words meaningful keywords from text for a slug.

    Filters out common stop words and verb fillers to get the
    essence: 'PR review workflow that checks tests' -> 'pr-review-checks-tests'
    """
    stop_words = {
        "a",
        "an",
        "the",
        "that",
        "which",
        "this",
        "with",
        "and",
        "or",
        "for",
        "from",
        "into",
        "onto",
        "upon",
        "about",
        "after",
        "before",
        "during",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "up",
        "it",
        "its",
        "custom",
        "performs",
        "whether",
        "your",
        "when",
        "how",
    }
    words = re.findall(r"[a-z]+", text.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    return "-".join(keywords[:max_words])


def _slugify(text: str) -> str:
    """Convert text to a valid slug."""
    slug = text.lower().strip()
    # Remove common filler words for brevity
    slug = re.sub(r"\b(custom|for|the|a|an|with|and|from)\b", "", slug)
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


async def _create_skill_listing(
    agent: Agent,
    feature: dict,
    submitter_id: uuid.UUID,
    db: AsyncSession,
) -> dict | None:
    """Create a pending SkillListing from a features_to_try suggestion.

    Validates through SkillSubmitRequest and SKILL.md frontmatter validation to
    ensure proper field values.
    Wraps the example in proper SKILL.md frontmatter if not already formatted.
    """
    from pydantic import ValidationError

    from schemas.skill import SkillSubmitRequest
    from services.skill_validator import SkillValidationError, validate_skill_md_content_frontmatter

    one_liner = feature.get("one_liner", "")
    example = feature.get("example", "")

    if not example:
        return None

    # Prefer the LLM-provided name if it's short and valid, else derive one
    raw_name = feature.get("name", "")
    if raw_name and len(raw_name) <= 30 and re.match(r"^[a-z0-9\-]+$", raw_name):
        name = f"{_slugify(agent.name)[:16].rstrip('-')}-{raw_name}"
    else:
        name = _derive_name(agent.name, one_liner or feature.get("feature", "skill"))

    # Build proper SKILL.md content if the example is raw text
    skill_md = _ensure_skill_md_format(name, one_liner, example)

    # Validate through Pydantic schema and stored SKILL.md frontmatter rules.
    try:
        validate_skill_md_content_frontmatter(skill_md)
        validated = SkillSubmitRequest(
            name=name,
            version="1.0.0",
            description=one_liner or f"Skill for {agent.name}",
            owner=agent.owner or "",
            skill_md_content=skill_md,
            delivery_mode="registry_direct",
            target_agents=[agent.name],
            task_type="general",
            supported_ides=["claude-code", "kiro", "pi"],
        )
    except (SkillValidationError, ValidationError) as e:
        optic.warning("self_learn_skill_validation_failed", name=name, errors=str(e))
        return None

    # Check for existing
    existing = await db.execute(
        select(SkillListing).where(
            SkillListing.name == name,
            SkillListing.submitted_by == submitter_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    listing = SkillListing(
        name=validated.name,
        owner=validated.owner,
        submitted_by=submitter_id,
        owner_org_id=agent.owner_org_id,
    )
    db.add(listing)
    await db.flush()

    version = SkillVersion(
        listing_id=listing.id,
        version=validated.version,
        description=validated.description,
        skill_md_content=validated.skill_md_content,
        delivery_mode=validated.delivery_mode,
        target_agents=validated.target_agents,
        task_type=validated.task_type,
        supported_ides=validated.supported_ides,
        status=ListingStatus.pending,
        released_by=submitter_id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id

    return {
        "id": str(listing.id),
        "name": name,
        "description": one_liner,
        "type": "skill",
    }


def _ensure_skill_md_format(name: str, description: str, raw_example: str) -> str:
    """Wrap raw example text in proper SKILL.md frontmatter if missing."""
    if raw_example.strip().startswith("---"):
        return raw_example  # Already has frontmatter

    frontmatter = {
        "name": name,
        "description": description,
        "version": "1.0.0",
        "task_type": "general",
    }
    body = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True).strip()
    return f"""---
{body}
---

# {name}

{raw_example}
"""


async def _create_hook_listing(
    agent: Agent,
    feature: dict,
    submitter_id: uuid.UUID,
    db: AsyncSession,
) -> dict | None:
    """Create a pending HookListing from a features_to_try suggestion.

    Validates through HookSubmitRequest. Converts pseudocode examples
    into proper shell scripts with shebangs.
    """
    from pydantic import ValidationError

    from schemas.hook import HookSubmitRequest

    one_liner = feature.get("one_liner", "")
    example = feature.get("example", "")

    if not example:
        return None

    # Prefer the LLM-provided name if it's short and valid, else derive one
    raw_name = feature.get("name", "")
    if raw_name and len(raw_name) <= 30 and re.match(r"^[a-z0-9\-]+$", raw_name):
        name = f"{_slugify(agent.name)[:16].rstrip('-')}-{raw_name}"
    else:
        name = _derive_name(agent.name, one_liner or feature.get("feature", "hook"))

    # Parse hook metadata from the example
    event, execution_mode, script_content = _parse_hook_example(example)

    # Convert to proper executable script
    script_content = _normalize_script(script_content, name)
    script_filename = f"{name}.sh"

    # Validate through Pydantic schema
    try:
        validated = HookSubmitRequest(
            name=name,
            version="1.0.0",
            description=one_liner or f"Hook for {agent.name}",
            owner=agent.owner or "",
            event=event,
            execution_mode=execution_mode,
            priority=100,
            handler_type="script",
            handler_config={"inline": True},
            scope="agent",
            script_content=script_content,
            script_filename=script_filename,
            supported_ides=["claude-code", "kiro", "pi"],
        )
    except ValidationError as e:
        optic.warning("self_learn_hook_validation_failed", name=name, errors=str(e))
        return None

    # Check for existing
    existing = await db.execute(
        select(HookListing).where(
            HookListing.name == name,
            HookListing.submitted_by == submitter_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    listing = HookListing(
        name=validated.name,
        owner=validated.owner,
        submitted_by=submitter_id,
        owner_org_id=agent.owner_org_id,
    )
    db.add(listing)
    await db.flush()

    version = HookVersion(
        listing_id=listing.id,
        version=validated.version,
        description=validated.description,
        event=validated.event,
        execution_mode=validated.execution_mode,
        priority=validated.priority,
        handler_type=validated.handler_type,
        handler_config=validated.handler_config,
        scope=validated.scope,
        script_content=validated.script_content,
        script_filename=validated.script_filename,
        supported_ides=validated.supported_ides,
        status=ListingStatus.pending,
        released_by=submitter_id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id

    return {
        "id": str(listing.id),
        "name": name,
        "description": one_liner,
        "type": "hook",
    }


def _parse_hook_example(example: str) -> tuple[str, str, str]:
    """Parse hook event and mode from the example text.

    Returns (event, execution_mode, script_content).
    Events must be one of: PreToolUse, PostToolUse, Notification, Stop,
    SubagentStop, SessionStart, UserPromptSubmit.
    """
    lines = example.strip().splitlines()
    event = "Stop"  # safe default
    execution_mode = "async"
    script_lines = []

    for line in lines:
        lower = line.lower().strip()
        if lower.startswith("# hook:"):
            hook_desc = lower.replace("# hook:", "").strip()
            if "commit" in hook_desc or "push" in hook_desc or "before" in hook_desc:
                event = "Stop"
                execution_mode = "blocking"
            elif "start" in hook_desc or "init" in hook_desc or "session" in hook_desc:
                event = "SessionStart"
                execution_mode = "async"
            elif "prompt" in hook_desc or "submit" in hook_desc:
                event = "UserPromptSubmit"
                execution_mode = "sync"
            elif "tool" in hook_desc and "pre" in hook_desc:
                event = "PreToolUse"
                execution_mode = "sync"
            elif "tool" in hook_desc and "post" in hook_desc:
                event = "PostToolUse"
                execution_mode = "async"
            else:
                event = "Stop"
                execution_mode = "async"
        else:
            script_lines.append(line)

    script_content = "\n".join(script_lines).strip()
    if not script_content:
        script_content = example.strip()

    return event, execution_mode, script_content


def _normalize_script(raw_script: str, name: str) -> str:
    """Convert LLM-generated pseudocode into a proper executable script.

    If the content looks like Python pseudocode (uses def, import, class),
    wrap it in a Python shebang. If it looks like shell commands, add bash shebang.
    If it's a mix or unclear, produce a shell script that echos a placeholder.
    """
    lines = raw_script.strip().splitlines()

    # Already has a shebang
    if lines and lines[0].startswith("#!"):
        return raw_script

    # Detect if this is Python pseudocode
    python_indicators = ("def ", "import ", "class ", "context.get", "return {")
    python_score = sum(1 for line in lines if any(ind in line for ind in python_indicators))

    # Detect shell commands
    shell_indicators = ("pytest", "ruff ", "git ", "npm ", "make ", "cd ", "echo ", "exit ")
    shell_score = sum(1 for line in lines if any(ind in line.lower() for ind in shell_indicators))

    if shell_score > python_score:
        # Wrap as proper bash script
        return f"#!/usr/bin/env bash\nset -euo pipefail\n# Generated by Observal Insights for: {name}\n\n{raw_script}"

    if python_score > 0:
        # It's Python pseudocode. Wrap it but mark as needing review.
        return (
            f"#!/usr/bin/env python3\n"
            f"# Generated by Observal Insights for: {name}\n"
            f"# NOTE: This script was auto-generated from insight suggestions.\n"
            f"# Review and adapt before approving.\n\n"
            f"{raw_script}"
        )

    # Default: shell with the content as comments + placeholder
    commented = "\n".join(f"# {line}" for line in lines if line.strip())
    return (
        f"#!/usr/bin/env bash\n"
        f"set -euo pipefail\n"
        f"# Generated by Observal Insights for: {name}\n"
        f"# TODO: Implement the following logic:\n"
        f"{commented}\n\n"
        f'echo "[{name}] Hook executed successfully"\n'
    )


async def _create_prompt_listing(
    agent: Agent,
    pattern: dict,
    submitter_id: uuid.UUID,
    db: AsyncSession,
) -> dict | None:
    """Create a pending PromptListing from a usage_patterns suggestion.

    Validates through PromptSubmitRequest.
    """
    from pydantic import ValidationError

    from schemas.prompt import PromptSubmitRequest

    title = pattern.get("title", "")
    copyable_prompt = pattern.get("copyable_prompt", "")
    detail = pattern.get("detail", "")

    if not copyable_prompt:
        return None

    name = _derive_name(agent.name, title or "prompt")

    # Validate through Pydantic schema
    try:
        validated = PromptSubmitRequest(
            name=name,
            version="1.0.0",
            description=detail or f"Prompt pattern for {agent.name}",
            owner=agent.owner or "",
            category="general",
            template=copyable_prompt,
            variables=[],
            tags=["self-learn", agent.name],
            supported_ides=[],
        )
    except ValidationError as e:
        optic.warning("self_learn_prompt_validation_failed", name=name, errors=str(e))
        return None

    # Check for existing
    existing = await db.execute(
        select(PromptListing).where(
            PromptListing.name == name,
            PromptListing.submitted_by == submitter_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    listing = PromptListing(
        name=validated.name,
        owner=validated.owner,
        submitted_by=submitter_id,
        owner_org_id=agent.owner_org_id,
    )
    db.add(listing)
    await db.flush()

    version = PromptVersion(
        listing_id=listing.id,
        version=validated.version,
        description=validated.description,
        category=validated.category,
        template=validated.template,
        variables=validated.variables,
        tags=validated.tags,
        status=ListingStatus.pending,
        released_by=submitter_id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id

    return {
        "id": str(listing.id),
        "name": name,
        "description": detail or title,
        "type": "prompt",
    }
