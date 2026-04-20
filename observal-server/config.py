from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    # JWT Settings
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # JWT / Asymmetric key signing
    JWT_SIGNING_ALGORITHM: str = "ES256"  # ES256 (ECDSA) or RS256 (RSA)
    JWT_KEY_DIR: str = "~/.observal/keys"
    JWT_KEY_PASSWORD: str | None = None  # Optional password for private key encryption at rest

    # Long-lived JWT for OTEL hooks (30 days default)
    JWT_HOOKS_TOKEN_EXPIRE_MINUTES: int = 43200

    # Rate limiting
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_AUTH_STRICT: str = "5/minute"

    # ClickHouse data retention
    DATA_RETENTION_DAYS: int = 90

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
