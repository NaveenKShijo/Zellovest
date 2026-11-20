"""Conversation persistence for Ask AI.

Conversation state belongs to the Agentic Reasoning Service (PRD 25.5). This
store reads and writes only conversation metadata and messages - never domain
tables - and every query is tenant-scoped.

Persistence is best-effort for availability: if the database is unreachable the
answer is still returned, and the failure is logged. It is never silently
treated as a successful save.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from zellovest_shared.db.conversations import AskAiConversation, AskAiMessage
from zellovest_shared.db.session import async_session_context
from zellovest_shared.logging_conf import get_logger

from zellovest_agentic.schemas.ask_ai import (
    AnswerSections,
    Citation,
    ConversationHistory,
    ConversationMessage,
    DataGap,
    EvidenceItem,
    ProposedAction,
    ToolCall,
)

logger = get_logger(__name__)


class ConversationNotFound(LookupError):
    """Raised when a conversation is absent or belongs to another tenant."""


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Return a UUID or None for malformed input."""
    if isinstance(value, uuid.UUID):
        return value
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class ConversationStore:
    """Tenant-scoped conversation reader/writer."""

    def __init__(self, *, enabled: bool = True) -> None:
        """Enable or disable persistence (tests use the latter)."""
        self.enabled = enabled

    async def resolve(
        self,
        *,
        tenant_id: str,
        user_id: str | uuid.UUID | None,
        conversation_id: str | uuid.UUID | None,
        context: dict[str, Any] | None,
        question: str,
    ) -> uuid.UUID:
        """Load an existing conversation or create a new one.

        Args:
            tenant_id: Owning tenant.
            user_id: Signed-in user (may be None for service identities).
            conversation_id: Client-supplied conversation id.
            context: Optional UI context stored on first creation.
            question: First question, used to derive a title.

        Returns:
            The conversation id to use for this request.

        Raises:
            ConversationNotFound: When an explicit id does not exist for this
                tenant.
        """
        requested = _as_uuid(conversation_id)
        if not self.enabled:
            return requested or uuid.uuid4()
        try:
            async with async_session_context() as session:
                if requested is not None:
                    existing = await session.scalar(
                        select(AskAiConversation).where(
                            AskAiConversation.id == requested,
                            AskAiConversation.tenant_id == tenant_id,
                        )
                    )
                    if existing is None:
                        raise ConversationNotFound(str(requested))
                    return existing.id
                conversation = AskAiConversation(
                    tenant_id=tenant_id,
                    user_id=_as_uuid(user_id),
                    title=question.strip()[:120] or "Untitled conversation",
                    context=context or {},
                    message_count=0,
                )
                session.add(conversation)
                await session.commit()
                await session.refresh(conversation)
                return conversation.id
        except ConversationNotFound:
            raise
        except Exception as exc:
            logger.error(
                "ask_ai_conversation_resolve_failed",
                tenant_id=tenant_id,
                error_class=type(exc).__name__,
            )
            return requested or uuid.uuid4()

    async def history(
        self,
        *,
        tenant_id: str,
        conversation_id: uuid.UUID,
        limit: int,
    ) -> list[dict[str, str]]:
        """Return the most recent turns in chronological order."""
        if not self.enabled or limit <= 0:
            return []
        try:
            async with async_session_context() as session:
                rows = (
                    await session.execute(
                        select(AskAiMessage)
                        .where(
                            AskAiMessage.tenant_id == tenant_id,
                            AskAiMessage.conversation_id == conversation_id,
                            AskAiMessage.role.in_(("user", "assistant")),
                        )
                        .order_by(AskAiMessage.created_at.desc())
                        .limit(limit * 2)
                    )
                ).scalars().all()
        except Exception as exc:
            logger.error(
                "ask_ai_history_load_failed",
                tenant_id=tenant_id,
                error_class=type(exc).__name__,
            )
            return []
        return [
            {"role": row.role, "content": row.content[:4000]}
            for row in reversed(rows)
            if row.content
        ]

    async def append_user(
        self,
        *,
        tenant_id: str,
        conversation_id: uuid.UUID,
        user_id: str | uuid.UUID | None,
        content: str,
        correlation_id: str,
    ) -> None:
        """Persist the user question."""
        await self._append(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=content,
            correlation_id=correlation_id,
            payload=None,
        )

    async def append_assistant(
        self,
        *,
        tenant_id: str,
        conversation_id: uuid.UUID,
        user_id: str | uuid.UUID | None,
        content: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist the assistant answer and its structured payload."""
        await self._append(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=content,
            correlation_id=correlation_id,
            payload=payload,
        )

    async def _append(
        self,
        *,
        tenant_id: str,
        conversation_id: uuid.UUID,
        user_id: str | uuid.UUID | None,
        role: str,
        content: str,
        correlation_id: str,
        payload: dict[str, Any] | None,
    ) -> None:
        """Insert one message and update conversation counters."""
        if not self.enabled:
            return
        try:
            async with async_session_context() as session:
                conversation = await session.scalar(
                    select(AskAiConversation).where(
                        AskAiConversation.id == conversation_id,
                        AskAiConversation.tenant_id == tenant_id,
                    )
                )
                if conversation is None:
                    return
                now = datetime.now(UTC)
                session.add(
                    AskAiMessage(
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        user_id=_as_uuid(user_id),
                        role=role,
                        content=content[:20000],
                        correlation_id=correlation_id,
                        payload=payload,
                    )
                )
                conversation.message_count = int(conversation.message_count or 0) + 1
                conversation.last_message_at = now
                if role == "user" and not conversation.title:
                    conversation.title = content.strip()[:120]
                await session.commit()
        except Exception as exc:
            logger.error(
                "ask_ai_message_persist_failed",
                tenant_id=tenant_id,
                role=role,
                error_class=type(exc).__name__,
            )

    async def list_conversations(
        self,
        *,
        tenant_id: str,
        user_id: str | uuid.UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ConversationHistory], int]:
        """Return a page of conversations for one tenant/user."""
        if not self.enabled:
            return [], 0
        try:
            async with async_session_context() as session:
                filters = [AskAiConversation.tenant_id == tenant_id]
                user_uuid = _as_uuid(user_id)
                if user_uuid is not None:
                    filters.append(AskAiConversation.user_id == user_uuid)
                total = await session.scalar(
                    select(func.count()).select_from(AskAiConversation).where(*filters)
                )
                rows = (
                    await session.execute(
                        select(AskAiConversation)
                        .where(*filters)
                        .order_by(
                            AskAiConversation.last_message_at.desc().nullslast(),
                            AskAiConversation.created_at.desc(),
                        )
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                ).scalars().all()
                summaries: list[ConversationHistory] = []
                for row in rows:
                    messages = (
                        await session.execute(
                            select(AskAiMessage)
                            .where(
                                AskAiMessage.tenant_id == tenant_id,
                                AskAiMessage.conversation_id == row.id,
                            )
                            .order_by(AskAiMessage.created_at.asc())
                            .limit(200)
                        )
                    ).scalars().all()
                    question = next(
                        (item.content for item in messages if item.role == "user"), ""
                    )
                    answer = next(
                        (
                            item.content
                            for item in reversed(messages)
                            if item.role == "assistant"
                        ),
                        "",
                    )
                    summaries.append(
                        ConversationHistory(
                            conversation_id=row.id,
                            question=question,
                            answer=answer,
                            created_at=row.created_at,
                            title=row.title,
                            message_count=row.message_count,
                            last_message_at=row.last_message_at,
                        )
                    )
                return summaries, int(total or 0)
        except Exception as exc:
            logger.error(
                "ask_ai_conversation_list_failed",
                tenant_id=tenant_id,
                error_class=type(exc).__name__,
            )
            return [], 0

    async def get_conversation(
        self,
        *,
        tenant_id: str,
        user_id: str | uuid.UUID | None,
        conversation_id: str | uuid.UUID,
    ) -> ConversationHistory:
        """Load one conversation with its ordered message history.

        Raises:
            ConversationNotFound: When the conversation does not exist for this
                tenant (or for this user, when a user id is supplied).
        """
        parsed = _as_uuid(conversation_id)
        if not self.enabled or parsed is None:
            raise ConversationNotFound(str(conversation_id))
        async with async_session_context() as session:
            filters = [
                AskAiConversation.id == parsed,
                AskAiConversation.tenant_id == tenant_id,
            ]
            user_uuid = _as_uuid(user_id)
            if user_uuid is not None:
                filters.append(AskAiConversation.user_id == user_uuid)
            row = await session.scalar(select(AskAiConversation).where(*filters))
            if row is None:
                raise ConversationNotFound(str(conversation_id))
            messages = (
                await session.execute(
                    select(AskAiMessage)
                    .where(
                        AskAiMessage.tenant_id == tenant_id,
                        AskAiMessage.conversation_id == row.id,
                    )
                    .order_by(AskAiMessage.created_at.asc())
                    .limit(500)
                )
            ).scalars().all()

        parsed_messages: list[ConversationMessage] = []
        for item in messages:
            payload = item.payload or {}
            try:
                parsed_messages.append(
                    ConversationMessage(
                        message_id=item.id,
                        role=item.role,
                        content=item.content,
                        created_at=item.created_at,
                        citations=[
                            Citation(**citation)
                            for citation in payload.get("citations") or []
                        ],
                        evidence=[
                            EvidenceItem(**evidence)
                            for evidence in payload.get("evidence") or []
                        ],
                        proposed_actions=[
                            ProposedAction(**action)
                            for action in payload.get("proposed_actions") or []
                        ],
                        data_gaps=[
                            DataGap(**gap) for gap in payload.get("data_gaps") or []
                        ],
                        tool_calls=[
                            ToolCall(**call) for call in payload.get("tool_calls") or []
                        ],
                        sections=(
                            AnswerSections(**payload["sections"])
                            if isinstance(payload.get("sections"), dict)
                            else None
                        ),
                        intent=payload.get("intent"),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "ask_ai_message_decode_failed",
                    tenant_id=tenant_id,
                    error_class=type(exc).__name__,
                )
        question = next((item.content for item in messages if item.role == "user"), "")
        answer = next(
            (item.content for item in reversed(messages) if item.role == "assistant"), ""
        )
        return ConversationHistory(
            conversation_id=row.id,
            question=question,
            answer=answer,
            created_at=row.created_at,
            title=row.title,
            message_count=row.message_count,
            last_message_at=row.last_message_at,
            messages=parsed_messages,
        )


__all__ = ["ConversationNotFound", "ConversationStore"]
