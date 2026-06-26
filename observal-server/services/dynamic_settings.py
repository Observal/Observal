# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Dynamic settings service: DB-backed runtime configuration with Redis cache.

All non-boot-time settings are stored in the `enterprise_config` table and
accessed through this module. No env-var fallback; if a setting isn't in the
DB, the hardcoded default is used. Legacy SSO env vars are imported once at
startup only when the matching DB setting is absent.

Usage:
    from services.dynamic_settings import get, get_int, get_bool

    model_name = get("insights.model_sections")        # returns "" if not set
    batch_days = get_int("insights.batch_period_days")  # returns 14 if not set
    sso_only = get_bool("deployment.sso_only")       # returns False if not set
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from loguru import logger as optic

# ─── Encryption for sensitive values ───────────────────────────────────────
# Uses Fernet symmetric encryption keyed from SECRET_KEY.
# Values are stored as "enc:" + base64(ciphertext) in the DB.
# On key rotation: set OLD_SECRET_KEY=<previous key> in env, restart.
# The system re-encrypts all sensitive values with the new key at startup,
# then you can remove OLD_SECRET_KEY.

_ENC_PREFIX = "enc:"


def _derive_fernet_key(secret: str):
    """Derive a Fernet key from a secret string.

    Uses SHA-256 as a KDF: no salt or iteration count since this is keyed from a
    server-unique SECRET_KEY for at-rest encryption only (not password hashing).
    Identical SECRET_KEY always yields the same Fernet key, which is intentional.
    """
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet():
    """Derive a Fernet key from SECRET_KEY."""
    from cryptography.fernet import Fernet

    from config import settings

    return Fernet(_derive_fernet_key(settings.SECRET_KEY))


def _get_old_fernet():
    """Derive a Fernet key from OLD_SECRET_KEY (for key rotation)."""
    import os

    from cryptography.fernet import Fernet

    old_key = os.environ.get("OLD_SECRET_KEY", "")
    if not old_key:
        return None
    return Fernet(_derive_fernet_key(old_key))


def encrypt_value(value: str) -> str:
    """Encrypt a value for storage. Returns 'enc:' prefixed ciphertext."""
    if not value:
        return value
    f = _get_fernet()
    encrypted = f.encrypt(value.encode())
    return _ENC_PREFIX + encrypted.decode()


def decrypt_value(stored: str) -> str:
    """Decrypt a stored value. Tries current key first, then OLD_SECRET_KEY."""
    if not stored or not stored.startswith(_ENC_PREFIX):
        return stored
    ciphertext = stored[len(_ENC_PREFIX) :].encode()
    # Try current key
    try:
        f = _get_fernet()
        return f.decrypt(ciphertext).decode()
    except Exception:
        pass
    # Try old key (rotation scenario)
    try:
        old_f = _get_old_fernet()
        if old_f:
            return old_f.decrypt(ciphertext).decode()
    except Exception:
        pass
    optic.error("dynamic_settings_decrypt_failed", hint="Neither SECRET_KEY nor OLD_SECRET_KEY can decrypt this value")
    return ""


async def reencrypt_on_key_rotation() -> int:
    """Re-encrypt all sensitive values with the current SECRET_KEY.

    Call at startup. If OLD_SECRET_KEY is set and any values can only be
    decrypted with the old key, they are re-encrypted with the new key.
    Once complete, remove OLD_SECRET_KEY from your env.

    Returns the number of values re-encrypted.
    """
    import os

    if not os.environ.get("OLD_SECRET_KEY"):
        return 0

    try:
        from sqlalchemy import select

        from database import async_session
        from models.enterprise_config import EnterpriseConfig

        count = 0
        async with async_session() as session:
            result = await session.execute(
                select(EnterpriseConfig).where(EnterpriseConfig.key.in_(list(SENSITIVE_KEYS)))
            )
            for cfg in result.scalars().all():
                if not cfg.value or not cfg.value.startswith(_ENC_PREFIX):
                    continue
                # Try current key: if it works, already rotated
                ciphertext = cfg.value[len(_ENC_PREFIX) :].encode()
                try:
                    _get_fernet().decrypt(ciphertext)
                    continue
                except Exception:
                    pass
                # Decrypt with old key, re-encrypt with new
                plaintext = decrypt_value(cfg.value)
                if plaintext:
                    cfg.value = encrypt_value(plaintext)
                    count += 1
            if count > 0:
                await session.commit()
                optic.info("dynamic_settings_reencrypted", count=count)
        return count
    except Exception as e:
        optic.error("dynamic_settings_reencrypt_failed", error=str(e))
        return 0


SSO_ENV_IMPORTS: dict[str, str] = {
    "OAUTH_CLIENT_ID": "oauth.client_id",
    "OAUTH_CLIENT_SECRET": "oauth.client_secret",
    "OAUTH_SERVER_METADATA_URL": "oauth.server_metadata_url",
    "SSO_ONLY": "deployment.sso_only",
    "SAML_IDP_ENTITY_ID": "saml.idp_entity_id",
    "SAML_IDP_SSO_URL": "saml.idp_sso_url",
    "SAML_IDP_SLO_URL": "saml.idp_slo_url",
    "SAML_IDP_X509_CERT": "saml.idp_x509_cert",
    "SAML_IDP_METADATA_URL": "saml.idp_metadata_url",
    "SAML_SP_ENTITY_ID": "saml.sp_entity_id",
    "SAML_SP_ACS_URL": "saml.sp_acs_url",
    "SAML_JIT_PROVISIONING": "saml.jit_provisioning",
    "SAML_DEFAULT_ROLE": "saml.default_role",
    "SAML_SP_KEY_ENCRYPTION_PASSWORD": "saml.sp_key_encryption_password",
}


async def import_sso_env_once() -> int:
    """Import legacy SSO env vars into dynamic settings when DB has no value."""
    import os

    from sqlalchemy import select

    from database import async_session
    from models.enterprise_config import EnterpriseConfig

    async with async_session() as session:
        result = await session.execute(
            select(EnterpriseConfig.key).where(EnterpriseConfig.key.in_(tuple(SSO_ENV_IMPORTS.values())))
        )
        existing = set(result.scalars().all())
        values = {
            setting_key: os.environ[env_key]
            for env_key, setting_key in SSO_ENV_IMPORTS.items()
            if setting_key not in existing and os.environ.get(env_key)
        }
        if not values:
            return 0

        imported = 0
        for setting_key, value in values.items():
            if setting_key in existing:
                continue
            store_value = encrypt_value(value) if setting_key in SENSITIVE_KEYS else value
            session.add(EnterpriseConfig(key=setting_key, value=store_value))
            imported += 1
        if imported:
            await session.commit()
            await invalidate_all()
            await refresh_sync_cache()
            optic.info("dynamic_settings_sso_env_imported count={}", imported)
        return imported


# Redis key namespace for settings cache
_CACHE_PREFIX = "settings:"
_CACHE_TTL = 30  # seconds, short TTL for consistency, Redis is fast

# ─── Default values (hardcoded, no env fallback) ─────────────────────────────
# These match the old env-var defaults from config.py. When a key is not in the
# DB, these are returned. Once configured via the settings page, DB values win.

DEFAULTS: dict[str, str] = {
    # Insights: LLM provider credentials (via LiteLLM)
    "insights.api_key": "",
    "insights.api_base": "",
    "insights.api_version": "",
    # Insights: per-stage models (LiteLLM format: provider/model-name)
    "insights.model_sections": "",
    "insights.model_synthesis": "",
    "insights.model_facets": "",
    # Insights: batch processing
    "insights.batch_enabled": "true",
    "insights.batch_period_days": "14",
    "insights.min_sessions": "5",
    "insights.facet_max_calls": "100",
    "insights.facet_concurrency": "25",
    # Auth
    "auth.self_registration_enabled": "false",
    # OIDC SSO. Changes require an API restart because the Authlib client is built at startup.
    "oauth.client_id": "",
    "oauth.client_secret": "",
    "oauth.server_metadata_url": "",
    # Deployment
    "deployment.sso_only": "false",
    "deployment.frontend_url": "http://localhost",
    "deployment.public_url": "",
    "deployment.cors_origins": "http://localhost:3000",
    # Danger-zone actions (rendered as buttons; value is informational only)
    "danger.purge_traces_insights": "",
    # Security
    "security.allow_internal_git_urls": "false",
    "security.allow_draft_install": "false",
    "security.rate_limit_auth": "10/minute",
    "security.rate_limit_auth_strict": "5/minute",
    # NOTE: Defaults to RFC 1918 private ranges so the Docker compose stack
    # works out of the box (nginx LB connects from a Docker-bridge IP).
    # Tradeoff: any process on the same private network can inject XFF headers
    # that the middleware will trust. For hardened deployments where the API is
    # directly exposed, narrow this to only the actual proxy IP(s).
    "security.trusted_proxy_ips": "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16,127.0.0.1",
    # SAML
    "saml.idp_entity_id": "",
    "saml.idp_sso_url": "",
    "saml.idp_slo_url": "",
    "saml.idp_x509_cert": "",
    "saml.idp_metadata_url": "",
    "saml.sp_entity_id": "",
    "saml.sp_acs_url": "",
    "saml.jit_provisioning": "true",
    "saml.default_role": "user",
    "saml.sp_key_encryption_password": "",
    # JWT (runtime-tunable expiry settings)
    "jwt.access_token_expire_minutes": "60",
    "jwt.refresh_token_expire_days": "30",
    "jwt.hooks_token_expire_minutes": "43200",
    # Resources
    "resource.db_pool_size": "10",
    "resource.db_max_overflow": "20",
    "resource.redis_max_connections": "50",
    "resource.redis_socket_timeout": "2.0",
    "resource.clickhouse_max_connections": "20",
    "resource.clickhouse_max_keepalive": "10",
    "resource.clickhouse_timeout": "10.0",
    # Data
    "data.retention_days": "90",
    "data.cache_ttl_default": "30",
    "data.cache_ttl_dashboard": "60",
    # Observability
    "observability.log_level": "INFO",  # TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL
    "observability.log_format": "json",  # 'json' or 'console' (colorized). Requires restart.
    "observability.enable_openapi": "false",
    "observability.enable_metrics": "false",
    # Misc
    "misc.harness_allowlist": "",
    "misc.default_harness": "",
    "misc.git_mirror_base_path": "",
}

# Sensitive keys: values are masked in API responses unless explicitly revealed
SENSITIVE_KEYS: set[str] = {
    "insights.api_key",
    "oauth.client_secret",
    "saml.idp_x509_cert",
    "saml.sp_key_encryption_password",
}

SETTING_FEATURES: dict[str, str] = {}

RESTART_REQUIRED_KEYS: set[str] = {
    "oauth.client_id",
    "oauth.client_secret",
    "oauth.server_metadata_url",
}


# Section definitions for the settings schema endpoint
def _setting_label(key: str) -> str:
    label = key.rsplit(".", 1)[-1].replace("_", " ").title()
    return (
        label.replace("Api", "API")
        .replace("Url", "URL")
        .replace("Sso", "SSO")
        .replace("Oauth", "OAuth")
        .replace("Jwt", "JWT")
        .replace("Idp", "IdP")
        .replace("Jit", "JIT")
        .replace("Slo", "SLO")
        .replace("Acs", "ACS")
        .replace("X509", "X.509")
        .replace("Sp ", "SP ")
        .replace("Db ", "DB ")
        .replace("Ttl", "TTL")
        .replace(" Id", " ID")
    )


def settings_schema() -> list[dict[str, Any]]:
    """Return admin settings metadata for the web UI."""
    sections = []
    for section in SECTIONS:
        items = []
        for key in section["keys"]:
            items.append(
                {
                    "key": key,
                    "label": _setting_label(key),
                    "subtitle": "",
                    "default": DEFAULTS.get(key, ""),
                    "requires_feature": SETTING_FEATURES.get(key) or section.get("requires_feature"),
                    "restart_required": key in RESTART_REQUIRED_KEYS,
                }
            )
        sections.append({**section, "settings": items})
    return sections


SECTIONS: list[dict[str, Any]] = [
    {
        "id": "auth",
        "title": "Authentication",
        "description": "Authentication policy for public entry points.",
        "icon": "key",
        "danger": True,
        "keys": [k for k in DEFAULTS if k.startswith("auth.")],
    },
    {
        "id": "insights",
        "title": "Agent Insights",
        "description": "Configure LLM provider for the insights engine. Supports any LiteLLM-compatible provider (Anthropic, OpenAI, Bedrock, Gemini, Azure, Ollama, etc).",
        "icon": "sparkles",
        "keys": [k for k in DEFAULTS if k.startswith("insights.")],
    },
    {
        "id": "danger",
        "title": "Danger Zone",
        "description": "Destructive maintenance actions. Use only when you intentionally want to purge stored data.",
        "icon": "alert-triangle",
        "danger": True,
        "keys": [k for k in DEFAULTS if k.startswith("danger.")],
    },
    {
        "id": "deployment",
        "title": "Deployment",
        "description": "Core deployment configuration. Changes may affect authentication and access. Proceed with caution.",
        "icon": "server",
        "danger": True,
        "keys": [k for k in DEFAULTS if k.startswith("deployment.") and k != "deployment.sso_only"],
    },
    {
        "id": "security",
        "title": "Security",
        "description": "Security policies and rate limiting. Misconfiguration can expose the instance to attacks.",
        "icon": "shield",
        "danger": True,
        "keys": [k for k in DEFAULTS if k.startswith("security.")],
    },
    {
        "id": "sso",
        "title": "SSO",
        "description": "OIDC, SAML, and SSO-only authentication settings.",
        "icon": "key",
        "danger": True,
        "keys": [
            "deployment.sso_only",
            "oauth.client_id",
            "oauth.client_secret",
            "oauth.server_metadata_url",
            *[k for k in DEFAULTS if k.startswith("saml.")],
        ],
    },
    {
        "id": "jwt",
        "title": "JWT Token Expiry",
        "description": "Token lifetime settings. Shorter values improve security but increase re-authentication frequency.",
        "icon": "clock",
        "keys": [k for k in DEFAULTS if k.startswith("jwt.")],
    },
    {
        "id": "resource",
        "title": "Resource Tuning",
        "description": "Connection pool sizes and query limits. Changes take effect on next connection. May require restart for pool sizes.",
        "icon": "database",
        "keys": [k for k in DEFAULTS if k.startswith("resource.")],
    },
    {
        "id": "data",
        "title": "Data & Retention",
        "description": "Data retention policies and cache TTLs.",
        "icon": "hard-drive",
        "keys": [k for k in DEFAULTS if k.startswith("data.")],
    },
    {
        "id": "observability",
        "title": "Observability",
        "description": "Logging and metrics configuration.",
        "icon": "activity",
        "keys": [k for k in DEFAULTS if k.startswith("observability.")],
    },
    {
        "id": "misc",
        "title": "Miscellaneous",
        "description": "Other system settings.",
        "icon": "settings",
        "keys": [k for k in DEFAULTS if k.startswith("misc.")],
    },
]


# ─── Cache + DB read layer ───────────────────────────────────────────────────


async def get(key: str, default: str | None = None) -> str:
    """Get a setting value. Checks Redis cache first, then DB, then hardcoded default.

    Args:
        key: Dotted setting key (e.g., "insights.model_sections")
        default: Override default (if None, uses DEFAULTS dict)

    Returns:
        The setting value as a string.
    """
    optic.trace("reading setting: {}", key)
    # 1. Try Redis cache
    try:
        from services.redis import get_redis

        r = get_redis()
        cached = await r.get(f"{_CACHE_PREFIX}{key}")
        if cached is not None:
            return cached
    except Exception:
        # Redis down, fall through to DB
        pass

    # 2. Read from DB
    value = await _read_from_db(key)

    if value is not None:
        # Cache the DB value
        try:
            from services.redis import get_redis

            r = get_redis()
            await r.set(f"{_CACHE_PREFIX}{key}", value, ex=_CACHE_TTL)
        except Exception:
            pass
        return value

    # 3. Return hardcoded default
    if default is not None:
        return default
    return DEFAULTS.get(key, "")


async def get_int(key: str, default: int | None = None) -> int:
    """Get a setting as an integer."""
    raw = await get(key)
    if not raw:
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "0")
        try:
            return int(fallback)
        except (ValueError, TypeError):
            return 0
    try:
        return int(raw)
    except (ValueError, TypeError):
        optic.warning("dynamic_settings_invalid_int", key=key, value=raw)
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "0")
        try:
            return int(fallback)
        except (ValueError, TypeError):
            return 0


async def get_float(key: str, default: float | None = None) -> float:
    """Get a setting as a float."""
    raw = await get(key)
    if not raw:
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "0.0")
        try:
            return float(fallback)
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        optic.warning("dynamic_settings_invalid_float", key=key, value=raw)
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "0.0")
        try:
            return float(fallback)
        except (ValueError, TypeError):
            return 0.0


async def get_bool(key: str, default: bool | None = None) -> bool:
    """Get a setting as a boolean."""
    raw = await get(key)
    if not raw:
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "false")
        return fallback.lower() in ("true", "1", "yes")
    return raw.lower() in ("true", "1", "yes")


async def get_list(key: str, separator: str = ",") -> list[str]:
    """Get a setting as a list of strings (split by separator)."""
    raw = await get(key)
    if not raw:
        return []
    return [item.strip() for item in raw.split(separator) if item.strip()]


async def invalidate(key: str) -> None:
    """Invalidate a cached setting (call after writes)."""
    try:
        from services.redis import get_redis

        r = get_redis()
        await r.delete(f"{_CACHE_PREFIX}{key}")
    except Exception:
        pass


async def invalidate_all() -> None:
    """Invalidate all cached settings."""
    try:
        from services.redis import get_redis

        r = get_redis()
        # Use SCAN to find and delete all settings keys
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=f"{_CACHE_PREFIX}*", count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass


async def get_all() -> dict[str, str]:
    """Get all settings from DB, merged with defaults for missing keys.

    Returns a dict of all known settings with their current values.
    """
    db_values = await _read_all_from_db()
    result = dict(DEFAULTS)
    result.update(db_values)
    return result


async def get_section(section_id: str) -> dict[str, str]:
    """Get all settings for a specific section."""
    prefix = f"{section_id}."
    all_settings = await get_all()
    return {k: v for k, v in all_settings.items() if k.startswith(prefix)}


# ─── Internal DB access ──────────────────────────────────────────────────────


async def _read_from_db(key: str) -> str | None:
    """Read a single setting from the database. Decrypts if sensitive."""
    try:
        from sqlalchemy import select

        from database import async_session
        from models.enterprise_config import EnterpriseConfig

        async with async_session() as session:
            result = await session.execute(select(EnterpriseConfig.value).where(EnterpriseConfig.key == key))
            row = result.scalar_one_or_none()
            if row is None:
                return None
            # Decrypt if it's an encrypted value
            if row.startswith(_ENC_PREFIX):
                return decrypt_value(row)
            return row
    except Exception as e:
        optic.warning("dynamic_settings_db_read_error", key=key, error=str(e))
        return None


async def _read_all_from_db() -> dict[str, str]:
    """Read all settings from the database. Decrypts sensitive values."""
    try:
        from sqlalchemy import select

        from database import async_session
        from models.enterprise_config import EnterpriseConfig

        async with async_session() as session:
            result = await session.execute(select(EnterpriseConfig.key, EnterpriseConfig.value))
            settings_dict = {}
            for row in result.all():
                value = row.value
                if value and value.startswith(_ENC_PREFIX):
                    value = decrypt_value(value)
                settings_dict[row.key] = value
            return settings_dict
    except Exception as e:
        optic.warning("dynamic_settings_db_read_all_error", error=str(e))
        return {}


def mask_value(key: str, value: str) -> str:
    """Mask sensitive values for API display."""
    if key not in SENSITIVE_KEYS:
        return value
    if not value or len(value) <= 4:
        return "••••••••"
    return "••••••" + value[-4:]


# ─── Sync cache for module-level / sync-function access ──────────────────────
# Populated once at startup via `load_sync_cache()`, refreshed on setting writes.

_sync_cache: dict[str, str] = {}
_sync_cache_loaded: bool = False


def get_sync(key: str, default: str | None = None) -> str:
    """Synchronous setting access from the in-memory cache.

    Falls back to DEFAULTS if not in cache. Call `load_sync_cache()` at startup.
    """
    if key in _sync_cache:
        return _sync_cache[key]
    if default is not None:
        return default
    return DEFAULTS.get(key, "")


def get_sync_int(key: str, default: int | None = None) -> int:
    """Synchronous int setting access."""
    raw = get_sync(key)
    if not raw:
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "0")
        try:
            return int(fallback)
        except (ValueError, TypeError):
            return 0
    try:
        return int(raw)
    except (ValueError, TypeError):
        if default is not None:
            return default
        return 0


def get_sync_bool(key: str, default: bool | None = None) -> bool:
    """Synchronous bool setting access."""
    raw = get_sync(key)
    if not raw:
        if default is not None:
            return default
        fallback = DEFAULTS.get(key, "false")
        return fallback.lower() in ("true", "1", "yes")
    return raw.lower() in ("true", "1", "yes")


async def load_sync_cache() -> None:
    """Load all settings into the sync cache. Call once at startup."""
    optic.debug("loading dynamic settings sync cache")
    global _sync_cache, _sync_cache_loaded
    try:
        db_values = await _read_all_from_db()
        _sync_cache = dict(DEFAULTS)
        _sync_cache.update(db_values)
        _sync_cache_loaded = True
        optic.info("dynamic_settings_cache_loaded", count=len(db_values))
    except Exception as e:
        optic.warning("dynamic_settings_cache_load_failed", error=str(e))
        _sync_cache = dict(DEFAULTS)
        _sync_cache_loaded = True


async def refresh_sync_cache() -> None:
    """Refresh the sync cache (call after writes)."""
    await load_sync_cache()
