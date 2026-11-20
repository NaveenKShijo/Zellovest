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

    # MCP Servers (PRD 25; one process per logical server)
    mcp_procurement_url: str = Field(
        default="http://localhost:8101/mcp", alias="MCP_PROCUREMENT_URL"
    )
    mcp_document_url: str = Field(
        default="http://localhost:8102/mcp", alias="MCP_DOCUMENT_URL"
    )
    mcp_external_url: str = Field(
        default="http://localhost:8103/mcp", alias="MCP_EXTERNAL_URL"
    )
    mcp_service_token: str = Field(default="dev-internal-token", alias="MCP_SERVICE_TOKEN")
    mcp_confirmation_secret: str = Field(default="", alias="MCP_CONFIRMATION_SECRET")
    mcp_connect_timeout_seconds: float = Field(
        default=10.0, alias="MCP_CONNECT_TIMEOUT_SECONDS"
    )
    mcp_transport_grace_seconds: float = Field(
        default=5.0, alias="MCP_TRANSPORT_GRACE_SECONDS"
    )
    mcp_max_retries: int = Field(default=2, ge=0, le=5, alias="MCP_MAX_RETRIES")
    mcp_retry_backoff_seconds: float = Field(default=0.25, alias="MCP_RETRY_BACKOFF_SECONDS")
    mcp_circuit_failure_threshold: int = Field(
        default=3, ge=1, le=20, alias="MCP_CIRCUIT_FAILURE_THRESHOLD"
    )
    mcp_circuit_reset_seconds: float = Field(
        default=30.0, alias="MCP_CIRCUIT_RESET_SECONDS"
    )
    mcp_default_actor_role: str = Field(
        default="procurement_member", alias="MCP_DEFAULT_ACTOR_ROLE"
    )

    # Agent orchestration guardrails
    agent_max_plan_steps: int = Field(default=6, ge=1, le=10, alias="AGENT_MAX_PLAN_STEPS")
    agent_max_tool_calls: int = Field(default=8, ge=1, le=20, alias="AGENT_MAX_TOOL_CALLS")
    agent_history_turns: int = Field(default=6, ge=0, le=30, alias="AGENT_HISTORY_TURNS")
    agent_evidence_chars: int = Field(default=6000, alias="AGENT_EVIDENCE_CHARS")
    agent_conversation_persistence: bool = Field(
        default=True, alias="AGENT_CONVERSATION_PERSISTENCE"
    )
    ask_ai_confirmation_ttl_seconds: int = Field(
        default=900, ge=60, le=3600, alias="ASK_AI_CONFIRMATION_TTL_SECONDS"
    )

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
