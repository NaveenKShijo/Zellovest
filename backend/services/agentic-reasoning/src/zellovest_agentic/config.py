"""Agentic Reasoning Service configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgenticReasoningSettings(BaseSettings):
    """Settings for Agentic Reasoning & Ask AI Service."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service
    service_name: str = Field(default="agentic-reasoning", alias="SERVICE_NAME")
    service_port: int = Field(default=8002, alias="SERVICE_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Database
    database_url: str = Field(alias="DATABASE_URL")
    async_database_url: str = Field(alias="ASYNC_DATABASE_URL")

    # Redis
    redis_url: str = Field(alias="REDIS_URL")

    # JWT
    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")

    # MCP Servers
    mcp_procurement_url: str = Field(default="http://localhost:8001", alias="MCP_PROCUREMENT_URL")
    mcp_document_url: str = Field(default="http://localhost:8003", alias="MCP_DOCUMENT_URL")
    mcp_external_url: str = Field(default="http://localhost:8004", alias="MCP_EXTERNAL_URL")

    # LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    llm_model: str = Field(default="gpt-4-turbo", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")

    # Vector DB
    vector_db_url: str = Field(default="", alias="VECTOR_DB_URL")
    vector_db_api_key: str = Field(default="", alias="VECTOR_DB_API_KEY")

    # API
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")


def get_agentic_reasoning_settings() -> AgenticReasoningSettings:
    """Get cached settings instance."""
    return AgenticReasoningSettings()  # type: ignore[call-arg]