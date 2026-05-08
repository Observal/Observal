# Observal Registry Codebase Map

## Summary
The codebase implements a multi-component registry system for agents, MCPs (Model Context Protocol servers), skills, hooks, prompts, and sandboxes. Each component type has:
- A SQLAlchemy **model** (database schema)
- A Pydantic **schema** (request/response validation)
- A **listing** table tracking submission metadata
- A **download** table tracking usage

The registry is versioned at the listing level, with agents referencing components via `AgentComponent` join table.

---

## Models: SQLAlchemy ORM

### Base Class
**File:** `observal-server/models/base.py`
- `Base(DeclarativeBase)` — SQLAlchemy declarative base for all models

### Agent Models (`observal-server/models/agent.py`)

#### Enums
- `AgentStatus`: draft, pending, active, rejected, archived
- `AgentVisibility`: public, private

#### Tables

**agents** (main agent table)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| name | String(255) | NOT NULL |
| version | String(50) | NOT NULL |
| description | Text | NOT NULL |
| owner | String(255) | NOT NULL |
| git_url | String(500) | nullable |
| prompt | Text | NOT NULL |
| model_name | String(100) | NOT NULL |
| model_config_json | JSON | default=dict |
| external_mcps | JSON | default=list |
| supported_ides | JSON | default=list |
| required_ide_features | JSON | default=list |
| inferred_supported_ides | JSON | default=list |
| visibility | Enum(AgentVisibility) | default=private |
| owner_org_id | UUID FK → organizations.id | nullable |
| status | Enum(AgentStatus) | default=pending |
| rejection_reason | Text | nullable |
| download_count | Integer | default=0 |
| unique_users | Integer | default=0 |
| created_by | UUID FK → users.id | NOT NULL |
| created_at | DateTime(tz) | default=now(UTC) |
| updated_at | DateTime(tz) | default=now(UTC), onupdate=now(UTC) |

**Unique Constraint:** (name, created_by)

**Relationships:**
- `components` → list[AgentComponent], cascade delete, ordered by order_index, lazy=selectin
- `goal_template` → AgentGoalTemplate | None, cascade delete, lazy=selectin
- `team_accesses` → list[AgentTeamAccess], cascade delete, lazy=selectin

---

**agent_goal_templates**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| agent_id | UUID | FK → agents.id, unique, NOT NULL, cascade delete |
| description | Text | NOT NULL |

**Relationships:**
- `agent` → Agent (back_populates="goal_template")
- `sections` → list[AgentGoalSection], cascade delete, ordered by order, lazy=selectin

---

**agent_goal_sections**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| goal_template_id | UUID | FK → agent_goal_templates.id, NOT NULL, cascade delete |
| name | String(255) | NOT NULL |
| description | Text | nullable |
| grounding_required | Boolean | default=False |
| order | Integer | default=0 |

**Relationships:**
- `goal_template` → AgentGoalTemplate (back_populates="sections")

---

**agent_team_access**
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| agent_id | UUID | FK → agents.id, NOT NULL, cascade delete |
| group_name | String(255) | NOT NULL |
| permission | String(50) | NOT NULL (values: 'view', 'edit') |

**Relationships:**
- `agent` → Agent (back_populates="team_accesses")

---

### AgentComponent (`observal-server/models/agent_component.py`)

**agent_components** (join table for agents & components)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| agent_id | UUID | FK → agents.id, NOT NULL, cascade delete |
| component_type | String(50) | NOT NULL (values: "mcp", "skill", "hook", "prompt", "sandbox") |
| component_id | UUID | NOT NULL (references listing.id) |
| version_ref | Text | NOT NULL (semver or ref) |
| order_index | Integer | default=0 |
| config_override | JSON | nullable |
| created_at | DateTime(tz) | default=now(UTC) |

**Unique Constraint:** (agent_id, component_type, component_id)

---

### MCP Models (`observal-server/models/mcp.py`)

#### Enum
- `ListingStatus`: draft, pending, approved, rejected, archived (shared across all component types)

#### Tables

**mcp_listings** (MCP server registry)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| name | String(255) | NOT NULL |
| version | String(50) | NOT NULL |
| git_url | String(500) | nullable |
| git_ref | Text | nullable |
| description | Text | NOT NULL |
| category | String(100) | NOT NULL |
| owner | String(255) | NOT NULL |
| transport | String(20) | nullable |
| framework | String(100) | nullable |
| docker_image | String(500) | nullable |
| command | String(500) | nullable |
| args | JSON | nullable |
| url | String(1000) | nullable |
| headers | JSON | nullable |
| auto_approve | JSON | nullable |
| mcp_validated | Boolean | default=False |
| tools_schema | JSON | nullable |
| environment_variables | JSON | nullable |
| supported_ides | JSON | default=list |
| setup_instructions | Text | nullable |
| changelog | Text | nullable |
| is_private | Boolean | default=False |
| owner_org_id | UUID FK → organizations.id | nullable |
| bundle_id | UUID FK → component_bundles.id | nullable |
| status | Enum(ListingStatus) | default=pending |
| rejection_reason | Text | nullable |
| submitted_by | UUID FK → users.id | NOT NULL |
| download_count | Integer | default=0 |
| unique_agents | Integer | default=0 |
| created_at | DateTime(tz) | default=now(UTC) |
| updated_at | DateTime(tz) | default=now(UTC), onupdate=now(UTC) |

**Indexes:** status, submitted_by

**Relationships:**
- `validation_results` → list[McpValidationResult], cascade delete, lazy=selectin

---

**mcp_downloads** (usage tracking)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| listing_id | UUID | FK → mcp_listings.id, NOT NULL |
| user_id | UUID | FK → users.id, NOT NULL |
| ide | String(50) | NOT NULL |
| downloaded_at | DateTime(tz) | default=now(UTC) |

---

**mcp_validation_results** (validation run history)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| listing_id | UUID | FK → mcp_listings.id, NOT NULL |
| stage | String(100) | NOT NULL |
| passed | Boolean | NOT NULL |
| details | Text | nullable |
| run_at | DateTime(tz) | default=now(UTC) |

**Relationships:**
- `listing` → McpListing (back_populates="validation_results")

---

### Skill Models (`observal-server/models/skill.py`)

**skill_listings** (Skill registry)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| name | String(255) | NOT NULL |
| version | String(50) | NOT NULL |
| description | Text | NOT NULL |
| owner | String(255) | NOT NULL |
| git_url | String(500) | nullable |
| git_ref | Text | nullable |
| supported_ides | JSON | default=list |
| is_private | Boolean | default=False |
| owner_org_id | UUID FK → organizations.id | nullable |
| bundle_id | UUID FK → component_bundles.id | nullable |
| status | Enum(ListingStatus) | default=pending |
| rejection_reason | Text | nullable |
| submitted_by | UUID FK → users.id | NOT NULL |
| download_count | Integer | default=0 |
| unique_agents | Integer | default=0 |
| created_at | DateTime(tz) | default=now(UTC) |
| updated_at | DateTime(tz) | default=now(UTC), onupdate=now(UTC) |
| skill_path | String(500) | default="/" |
| target_agents | JSON | default=list |
| task_type | String(100) | NOT NULL |
| triggers | JSON | nullable |
| slash_command | String(100) | nullable |
| has_scripts | Boolean | default=False |
| has_templates | Boolean | default=False |
| is_power | Boolean | default=False |
| power_md | Text | nullable |
| mcp_server_config | JSON | nullable |
| activation_keywords | JSON | nullable |

**Indexes:** status, submitted_by

---

**skill_downloads** (usage tracking)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| listing_id | UUID | FK → skill_listings.id, NOT NULL |
| user_id | UUID | FK → users.id, NOT NULL |
| ide | String(50) | NOT NULL |
| downloaded_at | DateTime(tz) | default=now(UTC) |

---

### Hook Models (`observal-server/models/hook.py`)

**hook_listings** (Hook/lifecycle event registry)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| name | String(255) | NOT NULL |
| version | String(50) | NOT NULL |
| description | Text | NOT NULL |
| owner | String(255) | NOT NULL |
| git_url | String(500) | nullable |
| git_ref | Text | nullable |
| supported_ides | JSON | default=list |
| is_private | Boolean | default=False |
| owner_org_id | UUID FK → organizations.id | nullable |
| bundle_id | UUID FK → component_bundles.id | nullable |
| status | Enum(ListingStatus) | default=pending |
| rejection_reason | Text | nullable |
| submitted_by | UUID FK → users.id | NOT NULL |
| download_count | Integer | default=0 |
| unique_agents | Integer | default=0 |
| created_at | DateTime(tz) | default=now(UTC) |
| updated_at | DateTime(tz) | default=now(UTC), onupdate=now(UTC) |
| event | String(50) | NOT NULL |
| execution_mode | String(10) | default="async" |
| priority | Integer | default=100 |
| handler_type | String(20) | NOT NULL |
| handler_config | JSON | default=dict |
| input_schema | JSON | nullable |
| output_schema | JSON | nullable |
| scope | String(20) | default="agent" |
| tool_filter | JSON | nullable |
| file_pattern | JSON | nullable |

**Indexes:** status, submitted_by

---

**hook_downloads** (usage tracking)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| listing_id | UUID | FK → hook_listings.id, NOT NULL |
| user_id | UUID | FK → users.id, NOT NULL |
| ide | String(50) | NOT NULL |
| downloaded_at | DateTime(tz) | default=now(UTC) |

---

### Prompt Models (`observal-server/models/prompt.py`)

**prompt_listings** (Prompt template registry)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| name | String(255) | NOT NULL |
| version | String(50) | NOT NULL |
| description | Text | NOT NULL |
| owner | String(255) | NOT NULL |
| git_url | String(500) | nullable |
| git_ref | Text | nullable |
| category | String(100) | NOT NULL |
| template | Text | NOT NULL |
| variables | JSON | default=list |
| model_hints | JSON | nullable |
| tags | JSON | default=list |
| supported_ides | JSON | default=list |
| is_private | Boolean | default=False |
| owner_org_id | UUID FK → organizations.id | nullable |
| bundle_id | UUID FK → component_bundles.id | nullable |
| status | Enum(ListingStatus) | default=pending |
| rejection_reason | Text | nullable |
| submitted_by | UUID FK → users.id | NOT NULL |
| download_count | Integer | default=0 |
| unique_agents | Integer | default=0 |
| created_at | DateTime(tz) | default=now(UTC) |
| updated_at | DateTime(tz) | default=now(UTC), onupdate=now(UTC) |

**Indexes:** status, submitted_by

---

**prompt_downloads** (usage tracking)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| listing_id | UUID | FK → prompt_listings.id, NOT NULL |
| user_id | UUID | FK → users.id, NOT NULL |
| ide | String(50) | NOT NULL |
| downloaded_at | DateTime(tz) | default=now(UTC) |

---

### Sandbox Models (`observal-server/models/sandbox.py`)

**sandbox_listings** (Sandbox environment registry)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| name | String(255) | NOT NULL |
| version | String(50) | NOT NULL |
| description | Text | NOT NULL |
| owner | String(255) | NOT NULL |
| git_url | String(500) | nullable |
| git_ref | Text | nullable |
| runtime_type | String(20) | NOT NULL |
| image | String(500) | NOT NULL |
| dockerfile_url | String(500) | nullable |
| resource_limits | JSON | default=dict |
| network_policy | String(20) | default="none" |
| allowed_mounts | JSON | default=list |
| env_vars | JSON | default=dict |
| entrypoint | String(500) | nullable |
| supported_ides | JSON | default=list |
| is_private | Boolean | default=False |
| owner_org_id | UUID FK → organizations.id | nullable |
| bundle_id | UUID FK → component_bundles.id | nullable |
| status | Enum(ListingStatus) | default=pending |
| rejection_reason | Text | nullable |
| submitted_by | UUID FK → users.id | NOT NULL |
| download_count | Integer | default=0 |
| unique_agents | Integer | default=0 |
| created_at | DateTime(tz) | default=now(UTC) |
| updated_at | DateTime(tz) | default=now(UTC), onupdate=now(UTC) |

**Indexes:** status, submitted_by

---

**sandbox_downloads** (usage tracking)
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default=uuid4 |
| listing_id | UUID | FK → sandbox_listings.id, NOT NULL |
| user_id | UUID | FK → users.id, NOT NULL |
| ide | String(50) | NOT NULL |
| downloaded_at | DateTime(tz) | default=now(UTC) |

---

## Schemas: Pydantic Validation

All schemas use `model_config = {"from_attributes": True}` for SQLAlchemy model conversion.

### Agent Schemas (`observal-server/schemas/agent.py`)

**Request Classes:**
- `GoalSectionRequest`: name, description?, grounding_required?
- `GoalTemplateRequest`: description, sections[1+]
- `ExternalMcp`: name, command, args[], env{}
- `ComponentRef`: component_type, component_id, config_override?
- `TeamAccessRequest`: group_name, permission (view|edit)
- `AgentCreateRequest`: all fields required/defaulted
- `AgentUpdateRequest`: all fields optional
- `AgentValidateRequest`: components[]
- `AgentInstallRequest`: ide, env_values{}, options{}, platform?

**Response Classes:**
- `GoalSectionResponse`: name, description?, grounding_required, order
- `GoalTemplateResponse`: description, sections[]
- `McpLinkResponse`: mcp_listing_id, mcp_name, order
- `ComponentLinkResponse`: component_type, component_id, component_name, version_ref, order, config_override?
- `AgentResponse`: id, name, version, description, owner, prompt, model_name, model_config_json, external_mcps[], supported_ides[], required_ide_features[], inferred_supported_ides[], status, rejection_reason?, created_by, created_by_email, created_by_username?, created_at, updated_at, mcp_links[], component_links[], goal_template?, visibility, team_accesses[], user_permission?
- `AgentSummary`: id, name, version, description, owner, model_name, supported_ides[], required_ide_features[], inferred_supported_ides[], status, rejection_reason?, download_count, average_rating?, component_count, created_by_email, created_by_username?, created_at?, updated_at?, components_ready, blocking_components[], visibility
- `ValidationResult`: valid, issues[]
- `ValidationIssue`: severity (error|warning), component_type?, component_id?, message
- `AgentInstallResponse`: agent_id, ide, config_snippet, warnings[]

**Validation:**
- name: regex validated (alphanumeric, hyphens, underscores, 64 char max)
- version: semver validated (x.y.z format)
- component_types: enum {mcp, skill, hook, prompt, sandbox}

---

### MCP Schemas (`observal-server/schemas/mcp.py`)

**Support Classes:**
- `McpEnvVar`: name, description?, required?
- `McpHeader`: name, description?, required?
- `ClientAnalysis`: tools[], issues[], framework, entry_point, command?, args?, docker_image?

**Request Classes:**
- `McpSubmitRequest`: all fields for submission
- `McpDraftRequest`: relaxed version of McpSubmitRequest
- `McpUpdateRequest`: all fields optional
- `McpInstallRequest`: ide, env_values{}, header_values{}
- `McpAnalyzeRequest`: git_url

**Response Classes:**
- `McpValidationResultResponse`: stage, passed, details?, run_at
- `McpListingResponse`: full listing with validation results
- `McpListingSummary`: id, name, version, description, category, owner, supported_ides[], status, rejection_reason?
- `McpInstallResponse`: listing_id, ide, config_snippet
- `McpAnalyzeResponse`: name, description, version, tools[], environment_variables[], issues[], error, command?, args?, framework?, docker_image?
- `ReviewActionRequest`: reason?

---

### Skill Schemas (`observal-server/schemas/skill.py`)

**Request Classes:**
- `SkillSubmitRequest`: name, version, description, owner, git_url?, skill_path, archive_url?, target_agents[], task_type, triggers?, slash_command?, has_scripts, has_templates, supported_ides[], is_power, power_md?, mcp_server_config?, activation_keywords?
- `SkillDraftRequest`: relaxed defaults
- `SkillUpdateRequest`: all optional
- `SkillInstallRequest`: ide, scope?

**Response Classes:**
- `SkillListingResponse`: id, name, version, description, owner, git_url?, task_type, target_agents[], supported_ides[], is_power, status, rejection_reason?, submitted_by, created_at, updated_at
- `SkillListingSummary`: id, name, version, description, task_type, owner, target_agents[], status, rejection_reason?
- `SkillInstallResponse`: listing_id, ide, config_snippet

---

### Hook Schemas (`observal-server/schemas/hook.py`)

**Request Classes:**
- `HookSubmitRequest`: name, version, description, owner, event, execution_mode, priority, handler_type, handler_config, input_schema?, output_schema?, scope, tool_filter?, file_pattern?, supported_ides[]
- `HookDraftRequest`: relaxed defaults
- `HookUpdateRequest`: all optional
- `HookInstallRequest`: ide, platform?

**Response Classes:**
- `HookListingResponse`: id, name, version, description, owner, event, execution_mode, priority, handler_type, handler_config, scope, supported_ides[], status, rejection_reason?, submitted_by, created_at, updated_at
- `HookListingSummary`: id, name, version, description, event, scope, owner, status, rejection_reason?
- `HookInstallResponse`: listing_id, ide, config_snippet

---

### Prompt Schemas (`observal-server/schemas/prompt.py`)

**Request Classes:**
- `PromptSubmitRequest`: name, version, description, owner, category, template, variables[], model_hints?, tags[], supported_ides[]
- `PromptDraftRequest`: relaxed defaults
- `PromptUpdateRequest`: all optional
- `PromptRenderRequest`: variables{}

**Response Classes:**
- `PromptListingResponse`: id, name, version, description, owner, category, template, variables[], tags[], supported_ides[], status, rejection_reason?, submitted_by, created_at, updated_at
- `PromptListingSummary`: id, name, version, description, category, owner, status, rejection_reason?
- `PromptRenderResponse`: listing_id, rendered

---

### Sandbox Schemas (`observal-server/schemas/sandbox.py`)

**Request Classes:**
- `SandboxSubmitRequest`: name, version, description, owner, runtime_type, image, dockerfile_url?, resource_limits{}, network_policy, allowed_mounts[], env_vars{}, entrypoint?, supported_ides[]
- `SandboxDraftRequest`: relaxed defaults
- `SandboxUpdateRequest`: all optional
- `SandboxInstallRequest`: ide

**Response Classes:**
- `SandboxListingResponse`: id, name, version, description, owner, runtime_type, image, resource_limits{}, network_policy, supported_ides[], status, rejection_reason?, submitted_by, created_at, updated_at
- `SandboxListingSummary`: id, name, version, description, runtime_type, owner, supported_ides[], status, rejection_reason?
- `SandboxInstallResponse`: listing_id, ide, config_snippet

---

## Services: Config Generation

### agent_config_generator.py
Main entry: `generate_agent_config(agent, ide, observal_url, mcp_listings?, component_names?, env_values?, options?, platform?, skill_listings?, otlp_http_url?)`

Helpers:
- `_check_ide_compatibility(agent, ide)` → list[str] warnings
- `_sanitize_name(name)` → str
- `_wrap_kiro_prompt(prompt, agent_name)` → str
- `_inject_agent_id(mcp_config, agent_id)` → None
- `_build_mcp_configs(agent, ide, observal_url, mcp_listings?, env_values?)` → dict
- `_build_skill_configs(agent, skill_listings?)` → list[dict]
- `_generate_skill_file(skill, ide, scope?)` → dict | None
- `_build_rules_content(agent, component_names?)` → str

**IDE-specific generators:** kiro, claude-code, gemini-cli, codex, copilot, copilot-cli, opencode, cursor, vscode

### config_generator.py
Shared utilities for all component types.

Main entry: `generate_config(listing, ide, proxy_port?, observal_url?, env_values?, header_values?)` → dict

Helpers:
- `_build_server_env(listing, env_values?)` → dict[str, str]
- `_build_run_command(name, framework?, docker_image?, server_env?, stored_command?, stored_args?)` → list[str]
- `_substitute_dollar_vars(args[], env?)` → list[str]
- `_otlp_env(observal_url)` → dict
- `_claude_otlp_env(observal_url)` → dict
- `_gemini_otlp_env(observal_url)` → dict
- `_gemini_settings(observal_url)` → dict

---

## Alembic Migrations (Latest 10)

Most recent first:
1. `0019_add_agent_team_access.py` (agent_team_access table)
2. `0018_add_saml_config_and_scim_token.py`
3. `0017_add_org_trace_privacy.py`
4. `0016_add_ide_feature_fields.py` (required_ide_features, inferred_supported_ides)
5. `0015_add_webhook_secret_to_alert_rules.py`
6. `0014_add_draft_to_listing_status.py` (ListingStatus.draft added)
7. `0013_add_mcp_command_args_url_headers.py` (command, args, url, headers to mcp_listings)
8. `0011_agent_review_and_bundles.py` (bundle_id foreign key, status enum)
9. `0010_add_agents_name_uniqueness.py` (unique constraint on name + created_by)
10. `0001_add_rbac_roles_and_is_demo.py`

---

## Directory Structure

```
observal-server/
├── models/
│   ├── base.py               (Base declarative class)
│   ├── agent.py              (Agent, AgentComponent, AgentGoalTemplate, AgentGoalSection, AgentTeamAccess)
│   ├── agent_component.py    (AgentComponent — join table for agents + components)
│   ├── mcp.py                (McpListing, McpDownload, McpValidationResult)
│   ├── skill.py              (SkillListing, SkillDownload)
│   ├── hook.py               (HookListing, HookDownload)
│   ├── prompt.py             (PromptListing, PromptDownload)
│   └── sandbox.py            (SandboxListing, SandboxDownload)
├── schemas/
│   ├── agent.py              (Agent request/response schemas)
│   ├── mcp.py                (MCP request/response schemas)
│   ├── skill.py              (Skill request/response schemas)
│   ├── hook.py               (Hook request/response schemas)
│   ├── prompt.py             (Prompt request/response schemas)
│   ├── sandbox.py            (Sandbox request/response schemas)
│   └── ... (other schemas)
├── services/
│   ├── config_generator.py           (Shared config generation utilities)
│   ├── agent_config_generator.py     (Agent-specific config generation)
│   ├── hook_config_generator.py      (Hook-specific config generation)
│   ├── skill_config_generator.py     (Skill-specific config generation)
│   ├── sandbox_config_generator.py   (Sandbox-specific config generation)
│   └── codex_config_generator.py     (Codex IDE specifics)
└── alembic/
    └── versions/
        ├── 0019_add_agent_team_access.py
        ├── 0018_add_saml_config_and_scim_token.py
        ├── ... (earlier migrations)
```

---

## Key Design Patterns

### Version Management
- **Current approach:** Version stored as string on listing. No separate version history table.
- **Component reference:** AgentComponent.version_ref stores version at attachment time.
- **Semver validation:** Enforced in schemas via `validate_semver()`.

### Listing Status Flow
- **States:** draft → pending → approved/rejected → archived
- **Shared enum:** `ListingStatus` used by all 5 component types (mcp, skill, hook, prompt, sandbox)

### Component Composition
- **Agent references components via AgentComponent join table**
  - agent_id, component_type, component_id, version_ref, config_override
  - Allows version pinning and per-component overrides
  - Unique constraint: (agent_id, component_type, component_id)

### Privacy & Ownership
- **is_private:** Boolean on each listing
- **owner_org_id:** Optional org owner
- **team_accesses:** RBAC on agents only (via AgentTeamAccess)
- **submitted_by:** UUID reference to users table

### Usage Tracking
- **download_count:** Incremented on install
- **unique_agents/users:** Aggregated count
- Separate Download tables for detailed tracking (mcp_downloads, skill_downloads, etc.)

### IDE Registry
- **IDE support:** Each component lists supported_ides[] (JSON)
- **Config generation:** IDE-specific generators in services/
- **Fallback behavior:** Default rules/mcp paths when IDE not in registry

---

## Planning Notes for Version Tables

When adding version history tables for each component:

1. **Current state:** Version info is flat on listing row
2. **New approach:** Create component_type_versions tables
   - Tables: mcp_versions, skill_versions, hook_versions, prompt_versions, sandbox_versions
   - Each has: id (UUID PK), listing_id (UUID FK), version (String), created_at (DateTime), ...
   - Foreign key constraint on listing_id with cascade delete
   - Listing can have (is_current_version_id UUID FK → component_type_versions.id)

3. **Migration path:**
   - Create new _versions tables
   - Copy current listing data into _versions (created_at = now)
   - Add is_current_version_id FK to listing
   - Update existing code to load current version from FK

4. **Query impact:**
   - Current: SELECT listing... WHERE id=X
   - New: SELECT listing... WITH INNER JOIN ... ON is_current_version_id = versions.id
   - OR: Keep version denormalized on listing, maintain versions table for audit trail only

5. **Component attachment impact:**
   - AgentComponent.version_ref already stores version string
   - When resolving component at install time, query for versions row matching listing_id + version_ref
   - If not found, fallback to is_current_version (graceful upgrade)
