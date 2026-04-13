from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/observal"
    CLICKHOUSE_URL: str = "clickhouse://localhost:8123/observal"
    REDIS_URL: str = "redis://localhost:6379"
    SECRET_KEY: str = "change-me-to-a-random-string"
    API_KEY_LENGTH: int = 32
    EVAL_MODEL_URL: str = ""  # OpenAI-compatible endpoint (e.g., https://bedrock-runtime.us-east-1.amazonaws.com)
    EVAL_MODEL_API_KEY: str = ""  # API key or empty for AWS credential chain
    EVAL_MODEL_NAME: str = ""  # e.g., us.anthropic.claude-3-5-haiku-20241022-v1:0
    EVAL_MODEL_PROVIDER: str = ""  # "bedrock", "openai", or "" for auto-detect
    AWS_REGION: str = "us-east-1"

    # OAuth Settings
    OAUTH_CLIENT_ID: str | None = "39372289-d565-4a70-985f-8d36d54a4c71"
    OAUTH_CLIENT_SECRET: str | None = "secret-here"  # OAuth client secret here
    OAUTH_SERVER_METADATA_URL: str | None = (
        "https://login.microsoftonline.com/932446f1-3249-4966-b2a2-8f4bfef64b1b/v2.0/.well-known/openid-configuration"
    )
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
