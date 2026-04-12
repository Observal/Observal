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

    model_config = {"env_file": ".env"}


settings = Settings()
