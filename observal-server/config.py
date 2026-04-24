from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/observal"
    CLICKHOUSE_URL: str = "clickhouse://localhost:8123/observal"
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_SOCKET_TIMEOUT: float = 2.0
    SECRET_KEY: str = "change-me-to-a-random-string"
    EVAL_MODEL_URL: str = ""  # OpenAI-compatible endpoint (e.g., https://bedrock-runtime.us-east-1.amazonaws.com)
    EVAL_MODEL_API_KEY: str = ""  # API key or empty for AWS credential chain
    EVAL_MODEL_NAME: str = ""  # e.g., us.anthropic.claude-3-5-haiku-20241022-v1:0
    EVAL_MODEL_PROVIDER: str = ""  # "bedrock", "openai", or "" for auto-detect
    AWS_REGION: str = "us-east-1"

    # OAuth Settings
    OAUTH_CLIENT_ID: str | None = None
    OAUTH_CLIENT_SECRET: str | None = None
    OAUTH_SERVER_METADATA_URL: str | None = None
    FRONTEND_URL: str = "http://localhost:3000"

    # Public-facing URLs for endpoint discovery.
    # PUBLIC_URL: the base API URL clients use (derived from Request.base_url if empty).
    # OTLP_HTTP_URL: optional override for OTLP collector endpoint (defaults to PUBLIC_URL).
    PUBLIC_URL: str = ""
    OTLP_HTTP_URL: str = ""

    # JWT Settings
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # JWT / Asymmetric key signing
    JWT_SIGNING_ALGORITHM: str = "ES256"  # ES256 (ECDSA) or RS256 (RSA)
    JWT_KEY_DIR: str = "~/.observal/keys"
    JWT_KEY_PASSWORD: str | None = None  # Optional password for private key encryption at rest

    # Long-lived JWT for OTEL hooks (30 days default)
    JWT_HOOKS_TOKEN_EXPIRE_MINUTES: int = 43200

    # Connection pool sizing (tune for N-replica deployments)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    REDIS_MAX_CONNECTIONS: int = 50
    CLICKHOUSE_MAX_CONNECTIONS: int = 20
    CLICKHOUSE_MAX_KEEPALIVE: int = 10
    CLICKHOUSE_TIMEOUT: float = 10.0

    # Git mirror storage (empty = system tempdir; set to shared path for multi-instance)
    GIT_MIRROR_BASE_PATH: str = ""

    # Multi-instance startup: skip DDL when using a dedicated init container
    SKIP_DDL_ON_STARTUP: bool = False

    # Rate limiting
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_AUTH_STRICT: str = "5/minute"

    # ClickHouse data retention
    DATA_RETENTION_DAYS: int = 90

    # Cache TTL defaults (seconds)
    CACHE_TTL_DEFAULT: int = 30
    CACHE_TTL_DASHBOARD: int = 60
    CACHE_TTL_OTEL: int = 15

    @field_validator("DATA_RETENTION_DAYS")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("DATA_RETENTION_DAYS must be >= 0 (0 disables retention)")
        if 0 < v < 7:
            raise ValueError("DATA_RETENTION_DAYS must be >= 7 to prevent accidental data loss")
        return v

    # Deployment mode
    DEPLOYMENT_MODE: Literal["local", "enterprise"] = "local"

    # When True, password-based auth is disabled entirely.
    # Users can only authenticate via SSO (OAuth/OIDC).
    # Blocks: login, token, register, admin user create, admin password reset.
    SSO_ONLY: bool = False

    # SAML 2.0 SSO
    SAML_IDP_ENTITY_ID: str = ""
    SAML_IDP_SSO_URL: str = ""
    SAML_IDP_SLO_URL: str = ""
    SAML_IDP_X509_CERT: str = ""
    SAML_IDP_METADATA_URL: str = ""
    SAML_SP_ENTITY_ID: str = ""
    SAML_SP_ACS_URL: str = ""
    SAML_JIT_PROVISIONING: bool = True
    SAML_DEFAULT_ROLE: str = "user"
    SAML_SP_KEY_ENCRYPTION_PASSWORD: str = ""

    # Demo accounts (seeded on first startup if set and no real users exist)
    DEMO_SUPER_ADMIN_EMAIL: str | None = None
    DEMO_SUPER_ADMIN_PASSWORD: str | None = None
    DEMO_ADMIN_EMAIL: str | None = None
    DEMO_ADMIN_PASSWORD: str | None = None
    DEMO_REVIEWER_EMAIL: str | None = None
    DEMO_REVIEWER_PASSWORD: str | None = None
    DEMO_USER_EMAIL: str | None = None
    DEMO_USER_PASSWORD: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
