"""Agentic Reasoning Service configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to backend/.env so the service boots regardless of the
# process working directory (uvicorn CWD varies between local runs).
_BACKEND_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class AgenticReasoningSettings(BaseSettings):
    """Settings for Agentic Reasoning & Ask AI Service."""

    model_config = SettingsConfigDict(
        env_file=(str(_BACKEND_ENV_FILE), ".env"), extra="ignore"
    )

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

    # Groq is the primary provider for RAG; the shared key is also used by
    # structured document extraction workers.
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_api_url: str = Field(
        default="https://api.groq.com/openai/v1/chat/completions",
        alias="GROQ_API_URL",
    )
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    groq_timeout_seconds: float = Field(default=90.0, alias="GROQ_TIMEOUT_SECONDS")
    rag_evaluator_model: str = Field(default="", alias="RAG_EVALUATOR_MODEL")

    # Langfuse Cloud tracing (loaded from backend/.env; never sent to clients).
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com", alias="LANGFUSE_BASE_URL"
    )

    # Vector DB
    vector_db_url: str = Field(default="", alias="VECTOR_DB_URL")
    vector_db_api_key: str = Field(default="", alias="VECTOR_DB_API_KEY")

    # API
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")


def get_agentic_reasoning_settings() -> AgenticReasoningSettings:
    """Get cached settings instance."""
    return AgenticReasoningSettings()  # type: ignore[call-arg]
