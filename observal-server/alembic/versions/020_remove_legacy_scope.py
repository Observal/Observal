# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Remove the legacy deployment scope and preserve its settings."""

from alembic import op

revision = "020_remove_legacy_scope"
down_revision = "019_team_listing_restrict"
branch_labels = None
depends_on = None


_COPY_SETTINGS = """
DO $$
DECLARE
    legacy_count bigint;
BEGIN
    IF to_regclass('public.organizations') IS NULL THEN
        RETURN;
    END IF;

    EXECUTE 'SELECT count(*) FROM organizations' INTO legacy_count;
    IF legacy_count > 1 THEN
        RAISE EXCEPTION 'scope cleanup aborted: organizations contains % rows; expected zero or one', legacy_count;
    END IF;

    EXECUTE $copy$
        INSERT INTO enterprise_config (id, key, value, updated_at)
        SELECT gen_random_uuid(), 'security.trace_privacy', trace_privacy::text, now()
        FROM organizations
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
    $copy$;
    EXECUTE $copy$
        INSERT INTO enterprise_config (id, key, value, updated_at)
        SELECT gen_random_uuid(), 'registry.registered_agents_only', registered_agents_only::text, now()
        FROM organizations
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
    $copy$;
    EXECUTE $copy$
        INSERT INTO enterprise_config (id, key, value, updated_at)
        SELECT gen_random_uuid(), 'retention.enabled', retention_enabled::text, now()
        FROM organizations
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
    $copy$;
    EXECUTE $copy$
        INSERT INTO enterprise_config (id, key, value, updated_at)
        SELECT gen_random_uuid(), 'retention.trace_days', coalesce(data_retention_days::text, ''), now()
        FROM organizations
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
    $copy$;
    EXECUTE $copy$
        INSERT INTO enterprise_config (id, key, value, updated_at)
        SELECT gen_random_uuid(), 'retention.score_days', coalesce(score_retention_days::text, ''), now()
        FROM organizations
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
    $copy$;
    EXECUTE $copy$
        INSERT INTO enterprise_config (id, key, value, updated_at)
        SELECT gen_random_uuid(), 'retention.max_trace_count', coalesce(max_trace_count::text, ''), now()
        FROM organizations
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
    $copy$;
END $$;
"""

_VALIDATE_SINGLETONS = """
DO $$
DECLARE
    duplicate_count bigint;
BEGIN
    IF to_regclass('public.saml_configs') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM saml_configs' INTO duplicate_count;
        IF duplicate_count > 1 THEN
            RAISE EXCEPTION 'scope cleanup aborted: saml_configs contains % rows; expected zero or one', duplicate_count;
        END IF;
    END IF;

    IF to_regclass('public.exec_dashboard_config') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM exec_dashboard_config' INTO duplicate_count;
        IF duplicate_count > 1 THEN
            RAISE EXCEPTION 'scope cleanup aborted: exec_dashboard_config contains % rows; expected zero or one', duplicate_count;
        END IF;
    END IF;

    IF to_regclass('public.exporter_configs') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM (
                SELECT exporter_type
                FROM exporter_configs
                GROUP BY exporter_type
                HAVING count(*) > 1
            ) duplicate_types
        $query$ INTO duplicate_count;
        IF duplicate_count > 0 THEN
            RAISE EXCEPTION 'scope cleanup aborted: exporter_configs contains duplicate exporter types';
        END IF;
    END IF;
END $$;
"""

_DROP_REFERENCES = """
DO $$
DECLARE
    constraint_row record;
BEGIN
    IF to_regclass('public.organizations') IS NULL THEN
        RETURN;
    END IF;

    FOR constraint_row IN
        SELECT conrelid::regclass AS table_name, conname
        FROM pg_constraint
        WHERE contype = 'f'
          AND confrelid = to_regclass('public.organizations')
    LOOP
        EXECUTE format(
            'ALTER TABLE %s DROP CONSTRAINT %I',
            constraint_row.table_name,
            constraint_row.conname
        );
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(_COPY_SETTINGS)
    op.execute(_VALIDATE_SINGLETONS)
    op.execute(_DROP_REFERENCES)

    for table, column in (
        ("users", "org_id"),
        ("agents", "owner_org_id"),
        ("component_sources", "owner_org_id"),
        ("mcp_listings", "owner_org_id"),
        ("skill_listings", "owner_org_id"),
        ("hook_listings", "owner_org_id"),
        ("prompt_listings", "owner_org_id"),
        ("sandbox_listings", "owner_org_id"),
        ("saml_configs", "org_id"),
        ("scim_tokens", "org_id"),
        ("exec_dashboard_config", "org_id"),
        ("exporter_configs", "org_id"),
        ("migration_jobs", "org_id"),
    ):
        op.execute(f'ALTER TABLE IF EXISTS "{table}" DROP COLUMN IF EXISTS "{column}"')

    op.execute("ALTER TABLE IF EXISTS exporter_configs DROP CONSTRAINT IF EXISTS uq_exporter_configs_org_type")
    op.execute("ALTER TABLE IF EXISTS exec_dashboard_config DROP CONSTRAINT IF EXISTS uq_exec_dashboard_config_org")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_exporter_configs_type ON exporter_configs (exporter_type)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_saml_configs_singleton ON saml_configs ((true))")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_exec_dashboard_config_singleton ON exec_dashboard_config ((true))")
    op.execute("DROP TABLE IF EXISTS organizations")


def downgrade() -> None:
    raise RuntimeError("020_remove_legacy_scope is irreversible")
