"""PostgreSQL persistence for Ask AI conversations (PRD 22-24).

The Agentic Reasoning Service owns conversation state. Conversations and
messages live in the deployment database so a page reload, a second device, or
an audit replay can reconstruct exactly what the analyst asked, which tools
ran, what evidence was returned, and which actions were proposed or approved.

Messages store the user question and the assistant payload separately from the
rendered answer: the answer is markdown for display, while ``payload`` keeps
the structured citations, evidence, tool traces, data gaps, and proposed
actions used to produce it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from zellovest_shared.db.base import Base


class AskAiConversation(Base):
    """One Ask AI conversation owned by a tenant and user."""

    __tablename__ = "ask_ai_conversations"
    __table_args__ = (
        Index("ix_ask_ai_conv_tenant_user", "tenant_id", "user_id"),
        Index("ix_ask_ai_conv_tenant_last", "tenant_id", "last_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # No FK: conversation history survives user deactivation/deletion, while
    # the row remains tenant-scoped and auditable.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="Untitled conversation")
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AskAiMessage(Base):
    """One user, assistant, or action message inside a conversation."""

    __tablename__ = "ask_ai_messages"
    __table_args__ = (
        Index("ix_ask_ai_msg_conversation_time", "conversation_id", "created_at"),
        Index("ix_ask_ai_msg_tenant_corr", "tenant_id", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ask_ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["AskAiConversation", "AskAiMessage"]
