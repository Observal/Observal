# Agent-Centric Database Schema Design

**Date:** 2026-04-10  
**Issue:** [#78](https://github.com/BlazeUp-AI/Observal/issues/78)  
**Epic:** [#77 - Pivot to Agent-Centric Registry](https://github.com/BlazeUp-AI/Observal/issues/77)

## Overview

This spec redesigns the Observal database schema to make agents the primary deliverable while components (MCPs, skills, hooks, prompts, sandboxes) become composable building blocks. Users submit components but only pull complete agents, similar to Docker Hub's model where you pull images (agents) composed of layers (components).

## Objectives

1. **Agent-centric model**: Agents are primary entities; components are dependencies
2. **Git-based versioning**: All components sourced from Git repositories
3. **Organization support**: Private components and agents from day 1
4. **Download tracking**: Deduplicated agent downloads, non-deduplicated component downloads
5. **Simplified component types**: Eliminate confusing "tool calls" type
6. **Telemetry export**: Support for Grafana, Datadog, Loki, OpenTelemetry

## Component Type Decisions

### Eliminated Types
- **Tool Calls**: Removed - anything callable by LLMs must be a FastMCP server
- **GraphRAGs**: Removed as separate type - should be FastMCP wrapped

### Remaining Types (5 total)

| Component | FastMCP? | Git-Sourced | Purpose |
|-----------|----------|-------------|---------|
| MCPs | Required | Yes | Model Context Protocol servers (includes former tool calls) |
| Skills | No | Yes | SKILL.md instruction packages |
| Hooks | No | Yes | Lifecycle callbacks |
| Prompts | No | Yes | Text templates with variables |
| Sandboxes | No | Yes | Docker/LXC container configs |

**Rationale:**
- MCPs enforce FastMCP for tool discovery via `tools/list` protocol
- All types require Git URLs for version control and sharing across instances
- GraphRAGs wrap their functionality in FastMCP and submit as MCPs

## Schema Design

### 1. Foundation Tables

#### Organizations

```sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Organizations enable private component registries. Each org can host private MCPs, skills, etc., visible only to org members.

#### Users (updated)

```sql
ALTER TABLE users ADD COLUMN org_id UUID REFERENCES organizations(id);
-- org_id NULL = personal account (not org member)
```

#### Component Sources

```sql
CREATE TABLE component_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,  -- 'github', 'gitlab', 'bitbucket'
    component_type VARCHAR(50) NOT NULL,  -- 'mcp', 'skill', 'hook', 'prompt', 'sandbox'
    is_public BOOLEAN NOT NULL DEFAULT true,
    owner_org_id UUID REFERENCES organizations(id),
    auto_sync_interval INTERVAL,
    last_synced_at TIMESTAMPTZ,
    sync_status VARCHAR(20),  -- 'pending', 'syncing', 'success', 'failed'
    sync_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(url, component_type)
);

CREATE INDEX idx_component_sources_org ON component_sources(owner_org_id);
CREATE INDEX idx_component_sources_type ON component_sources(component_type);
```

**Purpose:** Tracks Git repositories we mirror components from. Supports scheduled re-sync.

**Key fields:**
- `url`: Git clone URL (github.com/org/repo, gitlab.company.com/team/repo)
- `component_type`: Declares what type of component this source contains
- `is_public`: Public sources visible to all; private sources only to `owner_org_id`
- `auto_sync_interval`: How often to re-pull (e.g., '1 day', '6 hours')

### 2. Component Tables

All component tables follow a shared pattern with type-specific extensions.

#### Shared Fields (all component types)

```sql
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
name VARCHAR(255) NOT NULL,
description TEXT NOT NULL,
owner VARCHAR(255) NOT NULL,

-- Git sourcing
git_url VARCHAR(500) NOT NULL,
git_ref TEXT,  -- latest synced commit/tag

-- Org access control
is_private BOOLEAN NOT NULL DEFAULT false,
owner_org_id UUID REFERENCES organizations(id),

-- Review workflow
status listing_status NOT NULL DEFAULT 'pending',
rejection_reason TEXT,

-- Metadata
submitted_by UUID NOT NULL REFERENCES users(id),
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

#### MCP Listings

```sql
CREATE TABLE mcp_listings (
    -- [shared fields above]
    
    category VARCHAR(100) NOT NULL,
    transport VARCHAR(20),  -- 'stdio', 'http', 'sse'
    fastmcp_validated BOOLEAN DEFAULT false,
    tools_schema JSONB,  -- cached from tools/list
    supported_ides JSONB DEFAULT '[]',
    setup_instructions TEXT,
    changelog TEXT
);

CREATE INDEX idx_mcp_listings_org ON mcp_listings(owner_org_id);
CREATE INDEX idx_mcp_listings_status ON mcp_listings(status);
CREATE INDEX idx_mcp_listings_category ON mcp_listings(category);
CREATE UNIQUE INDEX idx_mcp_listings_name_org ON mcp_listings(name, owner_org_id);
```

**FastMCP validation:**
- `fastmcp_validated`: Set to `true` after validation pipeline confirms FastMCP usage
- Validation checks for `from mcp.server.fastmcp import FastMCP` in cloned repo
- Submission rejected if FastMCP not detected

#### Skill Listings

```sql
CREATE TABLE skill_listings (
    -- [shared fields]
    
    skill_path VARCHAR(500) DEFAULT '/',
    task_type VARCHAR(100) NOT NULL,
    target_agents JSONB DEFAULT '[]',
    triggers JSONB,
    slash_command VARCHAR(100),
    has_scripts BOOLEAN DEFAULT false,
    has_templates BOOLEAN DEFAULT false,
    is_power BOOLEAN DEFAULT false,
    power_md TEXT,
    mcp_server_config JSONB,
    activation_keywords JSONB,
    supported_ides JSONB DEFAULT '[]'
);

CREATE INDEX idx_skill_listings_org ON skill_listings(owner_org_id);
CREATE INDEX idx_skill_listings_status ON skill_listings(status);
CREATE INDEX idx_skill_listings_task_type ON skill_listings(task_type);
CREATE UNIQUE INDEX idx_skill_listings_name_org ON skill_listings(name, owner_org_id);
```

#### Hook Listings

```sql
CREATE TABLE hook_listings (
    -- [shared fields]
    
    event VARCHAR(50) NOT NULL,
    execution_mode VARCHAR(10) DEFAULT 'async',
    priority INTEGER DEFAULT 100,
    handler_type VARCHAR(20) NOT NULL,
    handler_config JSONB DEFAULT '{}',
    input_schema JSONB,
    output_schema JSONB,
    scope VARCHAR(20) DEFAULT 'agent',
    tool_filter JSONB,
    file_pattern JSONB,
    supported_ides JSONB DEFAULT '[]'
);

CREATE INDEX idx_hook_listings_org ON hook_listings(owner_org_id);
CREATE INDEX idx_hook_listings_status ON hook_listings(status);
CREATE INDEX idx_hook_listings_event ON hook_listings(event);
CREATE UNIQUE INDEX idx_hook_listings_name_org ON hook_listings(name, owner_org_id);
```

#### Prompt Listings

```sql
CREATE TABLE prompt_listings (
    -- [shared fields]
    
    category VARCHAR(100) NOT NULL,
    template TEXT NOT NULL,
    variables JSONB DEFAULT '[]',
    model_hints JSONB,
    tags JSONB DEFAULT '[]',
    supported_ides JSONB DEFAULT '[]'
);

CREATE INDEX idx_prompt_listings_org ON prompt_listings(owner_org_id);
CREATE INDEX idx_prompt_listings_status ON prompt_listings(status);
CREATE INDEX idx_prompt_listings_category ON prompt_listings(category);
CREATE UNIQUE INDEX idx_prompt_listings_name_org ON prompt_listings(name, owner_org_id);
```

#### Sandbox Listings

```sql
CREATE TABLE sandbox_listings (
    -- [shared fields]
    
    runtime_type VARCHAR(20) NOT NULL,  -- 'docker', 'lxc'
    image VARCHAR(500) NOT NULL,
    dockerfile_url VARCHAR(500),
    resource_limits JSONB DEFAULT '{}',
    network_policy VARCHAR(20) DEFAULT 'none',
    allowed_mounts JSONB DEFAULT '[]',
    env_vars JSONB DEFAULT '{}',
    entrypoint VARCHAR(500),
    supported_ides JSONB DEFAULT '[]'
);

CREATE INDEX idx_sandbox_listings_org ON sandbox_listings(owner_org_id);
CREATE INDEX idx_sandbox_listings_status ON sandbox_listings(status);
CREATE INDEX idx_sandbox_listings_runtime ON sandbox_listings(runtime_type);
CREATE UNIQUE INDEX idx_sandbox_listings_name_org ON sandbox_listings(name, owner_org_id);
```

### 3. Agent Tables

#### Agents

```sql
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    owner VARCHAR(255) NOT NULL,
    
    -- Git sourcing (optional for agents)
    git_url VARCHAR(500),
    
    -- Org access control
    is_private BOOLEAN NOT NULL DEFAULT false,
    owner_org_id UUID REFERENCES organizations(id),
    
    -- Agent config
    prompt TEXT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    model_config_json JSONB DEFAULT '{}',
    external_mcps JSONB DEFAULT '[]',
    supported_ides JSONB DEFAULT '[]',
    
    -- Status
    status agent_status NOT NULL DEFAULT 'active',
    
    -- Metrics (computed by background job)
    download_count INTEGER DEFAULT 0,
    unique_users INTEGER DEFAULT 0,
    
    -- Metadata
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TYPE agent_status AS ENUM ('draft', 'active', 'archived');

CREATE INDEX idx_agents_org ON agents(owner_org_id);
CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_agents_downloads ON agents(download_count DESC);
CREATE UNIQUE INDEX idx_agents_name_org ON agents(name, owner_org_id);
```

#### Agent Components (polymorphic junction)

```sql
CREATE TABLE agent_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- Polymorphic reference (no FK constraint for future flexibility)
    component_type VARCHAR(50) NOT NULL,
    component_id UUID NOT NULL,
    
    -- Version pinning
    version_ref TEXT NOT NULL,  -- commit hash, tag, or branch
    
    -- Configuration
    order_index INTEGER DEFAULT 0,
    config_override JSONB,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(agent_id, component_type, component_id)
);

CREATE INDEX idx_agent_components_agent ON agent_components(agent_id);
CREATE INDEX idx_agent_components_component ON agent_components(component_type, component_id);
```

**Design notes:**
- Polymorphic `component_id` points to different tables based on `component_type`
- No FK constraint to allow adding new component types without schema changes
- `version_ref` stores commit hash, git tag, or branch name
- `config_override` allows agent-specific customization (e.g., different resource limits)

#### Agent Goal Templates (existing, unchanged)

```sql
CREATE TABLE agent_goal_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE UNIQUE,
    description TEXT NOT NULL
);

CREATE TABLE agent_goal_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_template_id UUID NOT NULL REFERENCES agent_goal_templates(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    grounding_required BOOLEAN DEFAULT false,
    order_index INTEGER DEFAULT 0
);
```

### 4. Download Tracking

#### Agent Downloads (deduplicated)

```sql
CREATE TABLE agent_downloads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- User deduplication
    user_id UUID REFERENCES users(id),  -- NULL for anonymous
    fingerprint TEXT,  -- hash(IP + user-agent) for anonymous
    
    -- Metadata
    source VARCHAR(50) NOT NULL,  -- 'cli', 'web', 'api'
    ide VARCHAR(50),
    installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Prevent duplicate downloads
    UNIQUE(agent_id, user_id),
    UNIQUE(agent_id, fingerprint)
);

CREATE INDEX idx_agent_downloads_agent ON agent_downloads(agent_id);
CREATE INDEX idx_agent_downloads_user ON agent_downloads(user_id);
CREATE INDEX idx_agent_downloads_installed ON agent_downloads(installed_at DESC);
```

**Deduplication logic:**
- **Authenticated users**: `UNIQUE(agent_id, user_id)` - user pulls same agent 15 times = 1 download
- **Anonymous users**: `UNIQUE(agent_id, fingerprint)` - fingerprint = `sha256(IP + user-agent)`
- Background job recomputes `agents.download_count` and `agents.unique_users` periodically

#### Component Downloads (NOT deduplicated)

```sql
CREATE TABLE component_downloads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Polymorphic component reference (no FK constraint)
    component_type VARCHAR(50) NOT NULL,
    component_id UUID NOT NULL,
    version_ref TEXT NOT NULL,
    
    -- Which agent triggered this download
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- Metadata
    source VARCHAR(50) NOT NULL,
    downloaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_component_downloads_component ON component_downloads(component_type, component_id);
CREATE INDEX idx_component_downloads_version ON component_downloads(component_type, component_id, version_ref);
CREATE INDEX idx_component_downloads_agent ON component_downloads(agent_id);
CREATE INDEX idx_component_downloads_downloaded ON component_downloads(downloaded_at DESC);
```

**Download counting logic:**
- **No deduplication**: Every `observal pull <agent>` creates new component_downloads rows
- If 50 agents use `filesystem-mcp@v2.0` and each has 1000 installs → component shows 50,000 downloads
- Version breakdown: query by `component_id` and `version_ref`
- Background job computes per-component download counts and adds to component tables

#### Download Count Fields (add to component tables)

```sql
ALTER TABLE mcp_listings ADD COLUMN download_count INTEGER DEFAULT 0;
ALTER TABLE mcp_listings ADD COLUMN unique_agents INTEGER DEFAULT 0;

ALTER TABLE skill_listings ADD COLUMN download_count INTEGER DEFAULT 0;
ALTER TABLE skill_listings ADD COLUMN unique_agents INTEGER DEFAULT 0;

ALTER TABLE hook_listings ADD COLUMN download_count INTEGER DEFAULT 0;
ALTER TABLE hook_listings ADD COLUMN unique_agents INTEGER DEFAULT 0;

ALTER TABLE prompt_listings ADD COLUMN download_count INTEGER DEFAULT 0;
ALTER TABLE prompt_listings ADD COLUMN unique_agents INTEGER DEFAULT 0;

ALTER TABLE sandbox_listings ADD COLUMN download_count INTEGER DEFAULT 0;
ALTER TABLE sandbox_listings ADD COLUMN unique_agents INTEGER DEFAULT 0;
```

### 5. Supporting Tables

#### Exporter Configs

```sql
CREATE TABLE exporter_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id),  -- NULL for global
    
    exporter_type VARCHAR(50) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    config JSONB NOT NULL,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(org_id, exporter_type)
);

CREATE INDEX idx_exporter_configs_org ON exporter_configs(org_id);
```

**Supported exporters:**
- `grafana`: Prometheus metrics endpoint
- `datadog`: StatsD/DogStatsD
- `loki`: Log streaming
- `otel`: OpenTelemetry protocol

#### Feedback (updated)

```sql
ALTER TABLE feedback ALTER COLUMN listing_type TYPE VARCHAR(50);

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS ck_feedback_listing_type;
ALTER TABLE feedback ADD CONSTRAINT ck_feedback_listing_type 
    CHECK (listing_type IN ('agent', 'mcp', 'skill', 'hook', 'prompt', 'sandbox'));
```

#### Submissions (updated)

```sql
ALTER TABLE submissions ALTER COLUMN listing_type TYPE VARCHAR(50);

ALTER TABLE submissions DROP CONSTRAINT IF EXISTS ck_submission_listing_type;
ALTER TABLE submissions ADD CONSTRAINT ck_submission_listing_type 
    CHECK (listing_type IN ('agent', 'mcp', 'skill', 'hook', 'prompt', 'sandbox'));
```

### 6. Tables to Remove

```sql
DROP TABLE IF EXISTS tool_listings CASCADE;
DROP TABLE IF EXISTS tool_downloads CASCADE;
DROP TABLE IF EXISTS graphrag_listings CASCADE;
DROP TABLE IF EXISTS graphrag_downloads CASCADE;
DROP TABLE IF EXISTS mcp_custom_fields CASCADE;  -- Move to JSONB if needed
DROP TABLE IF EXISTS mcp_validation_results CASCADE;  -- Move to component_sources.sync_error
```

**Rationale:**
- Tool Calls eliminated (functionality moved to MCPs)
- GraphRAGs eliminated (submit as FastMCP servers)
- Custom fields and validation results can use JSONB or component_sources

## Migration Strategy

Since Observal uses `Base.metadata.create_all()` (no Alembic currently):

### Phase 1: Add New Tables
1. Create `organizations` table
2. Add `org_id` column to `users` (nullable initially)
3. Create `component_sources` table
4. Create `agent_components` table
5. Create `agent_downloads` and `component_downloads` tables
6. Create `exporter_configs` table

### Phase 2: Update Existing Tables
1. Add org fields to all component tables (`is_private`, `owner_org_id`)
2. Add `git_url` to all component tables (backfill from existing URLs)
3. Add download count columns to component tables
4. Update `feedback` and `submissions` constraints
5. Add indexes

### Phase 3: Migrate Data
1. Migrate existing `agent_mcp_links` → `agent_components` (type='mcp')
2. Migrate existing `agent_skill_links` → `agent_components` (type='skill')
3. Migrate existing `agent_hook_links` → `agent_components` (type='hook')
4. Backfill `git_url` fields from existing data
5. Set `version_ref` to 'main' or latest commit for existing links

### Phase 4: Remove Old Tables
1. Drop `tool_listings`, `tool_downloads`
2. Drop `graphrag_listings`, `graphrag_downloads`
3. Drop `agent_mcp_links`, `agent_skill_links`, `agent_hook_links`
4. Drop `mcp_custom_fields`, `mcp_validation_results`

### Phase 5: Alembic Setup
1. Install Alembic
2. Initialize: `alembic init alembic`
3. Create baseline migration from current schema
4. Future schema changes use `alembic revision --autogenerate`

## API Impact

### New Endpoints

```
POST /api/v1/component-sources              # Add Git source
GET  /api/v1/component-sources               # List sources
POST /api/v1/component-sources/{id}/sync     # Trigger manual sync

GET  /api/v1/components                      # Unified component browser (all types)
GET  /api/v1/components/{type}/{id}          # Get specific component

POST /api/v1/agents/{id}/pull                # New: replaces install
GET  /api/v1/agents/leaderboard              # Most downloaded agents
GET  /api/v1/agents/{id}/downloads           # Download metrics

GET  /api/v1/organizations                   # List orgs
POST /api/v1/organizations                   # Create org
GET  /api/v1/organizations/{id}/members      # List members
```

### Updated Endpoints

```
POST /api/v1/mcps              # Now requires git_url
POST /api/v1/skills            # Now requires git_url
POST /api/v1/hooks             # Now requires git_url
POST /api/v1/prompts           # Now requires git_url
POST /api/v1/sandboxes         # Now requires git_url

DELETE /api/v1/tools/*         # Remove all tool endpoints
DELETE /api/v1/graphrags/*     # Remove all graphrag endpoints
```

### CLI Impact

```bash
# New commands
observal registry add-source <git-url> --type mcp
observal registry sync [<source-id>]
observal pull <agent-id> --ide cursor          # Replaces: observal install

# Updated commands
observal submit mcp <git-url>                  # Requires git URL
observal submit skill <git-url>
observal submit hook <git-url>
observal submit prompt <git-url>
observal submit sandbox <git-url>

# Removed commands
observal tool *                                # Delete all tool commands
observal graphrag *                            # Delete all graphrag commands
```

## Background Jobs

### Download Count Aggregator

Runs every 5 minutes:
```sql
-- Update agent counts
UPDATE agents SET 
  download_count = (SELECT COUNT(*) FROM agent_downloads WHERE agent_id = agents.id),
  unique_users = (SELECT COUNT(*) FROM agent_downloads WHERE agent_id = agents.id AND user_id IS NOT NULL);

-- Update component counts  
UPDATE mcp_listings SET
  download_count = (SELECT COUNT(*) FROM component_downloads WHERE component_type = 'mcp' AND component_id = mcp_listings.id),
  unique_agents = (SELECT COUNT(DISTINCT agent_id) FROM component_downloads WHERE component_type = 'mcp' AND component_id = mcp_listings.id);
```

### Component Sync Job

Runs based on `component_sources.auto_sync_interval`:
1. Fetch sources where `last_synced_at + auto_sync_interval < NOW()`
2. For each source:
   - `git pull` or `git clone` to `/var/lib/observal/mirrors/{source_id}`
   - Validate components (FastMCP check for MCPs, SKILL.md for skills, etc.)
   - Update component metadata in listings tables
   - Set `last_synced_at`, `sync_status`, `sync_error`

## Validation Rules

### MCPs
- Must have `from mcp.server.fastmcp import FastMCP` in Python files
- Rejection message: "MCPs must use FastMCP. See: https://modelcontextprotocol.io/fastmcp"

### Skills
- Must have SKILL.md file at `skill_path`
- Optional: validate frontmatter schema

### Hooks
- `handler_config` must match `handler_type` schema
- `event` must be valid IDE lifecycle event

### Prompts
- `template` must have valid variable syntax (e.g., `{{variable}}`)
- `variables` array must match template variables

### Sandboxes
- `image` must be valid Docker image reference or Dockerfile URL
- `resource_limits` must have valid CPU/memory values

## Security Considerations

1. **Git URL validation**: Only allow https:// and git@ URLs, block file:// and other protocols
2. **Org isolation**: API endpoints must check `owner_org_id` matches user's `org_id`
3. **Private component access**: Filter queries by `is_private = false OR owner_org_id = current_user.org_id`
4. **Download fingerprinting**: Use `sha256(IP + user-agent)` to prevent IP logging
5. **Git mirroring**: Clone to isolated directory with restricted permissions

## Success Criteria

- [ ] All 5 component types have `git_url` and org fields
- [ ] `agent_components` polymorphic junction table works across all types
- [ ] Agent downloads deduplicated, component downloads not deduplicated
- [ ] Organizations support private components from day 1
- [ ] Migration preserves all existing data
- [ ] No foreign key constraints on polymorphic `component_id`
- [ ] Background jobs compute download counts correctly
- [ ] FastMCP validation rejects non-FastMCP MCPs

## Future Enhancements

- Semver version constraints (`^2.0.0`) in `agent_components.version_ref`
- Component dependency graph visualization
- Automated migration tool from other agent registries
- Component marketplace with paid listings
- Multi-org teams (users belong to multiple orgs)
