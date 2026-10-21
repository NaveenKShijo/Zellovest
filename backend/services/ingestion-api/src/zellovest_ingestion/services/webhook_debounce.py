# """Redis-backed debounce gate for Okta/Ramp webhooks.
# 
# Treats incoming webhooks as change-detection triggers rather than events to
# store immediately. The first webhook opens a five-second window; subsequent
# webhooks during that window are acknowledged but not persisted. When the
# window closes, a single pull-sync fires once. While a sync is running, new
# webhooks are ignored entirely.
# 
# State key: zellovest:debounce:{provider}:{tenant_id}
# 
# Hash fields:
#     phase        -> "window" | "syncing"
#     window_start -> unix timestamp (float, seconds)
#     trigger_count -> int
#     sync_lock    -> "0" | "1"
# 
# TTL: 30 seconds (auto-cleanup if sync crashes mid-flight).
# """
# 
# from __future__ import annotations
# 
# import asyncio
# import time
# from dataclasses import dataclass
# from enum import StrEnum
# from typing import Awaitable, Callable
# 
# import redis.asyncio as redis
# 
# from zellovest_shared.logging_conf import get_logger
# 
# logger = get_logger(__name__)
# 
# DEBOUNCE_WINDOW_SECONDS = 5.0
# DEBOUNCE_KEY_TTL_SECONDS = 30
# 
# 
# class DebounceAction(StrEnum):
#     """Outcome of evaluating an incoming webhook against the debounce gate."""
# 
#     OPEN_WINDOW = "open_window"   # First webhook; window opened, schedule sync
#     JOIN_WINDOW = "join_window"   # Within window; ack only, no storage/sync
#     IGNORE = "ignore"             # Sync in progress; ack only, drop entirely
# 
# 
# @dataclass(slots=True)
# class DebounceResult:
#     action: DebounceAction
#     provider: str
#     tenant_id: str
#     trigger_count: int = 0
# 
# 
# class WebhookDebounce:
#     """Redis-backed debounce state machine per (provider, tenant_id)."""
# 
#     def __init__(self, redis_client: redis.Redis) -> None:
#         self._redis = redis_client
# 
#     def _key(self, provider: str, tenant_id: str) -> str:
#         return f"zellovest:debounce:{provider}:{tenant_id}"
# 
#     async def check(
#         self,
#         provider: str,
#         tenant_id: str,
#     ) -> DebounceResult:
#         """Evaluate an incoming webhook and update debounce state.
# 
#         Returns:
#             OPEN_WINDOW: first webhook; caller should ack + schedule sync after window
#             JOIN_WINDOW: within window; caller should ack only (no storage, no sync)
#             IGNORE: sync in progress; caller should ack only (drop entirely)
#         """
#         key = self._key(provider, tenant_id)
#         now = time.time()
# 
#         pipe = self._redis.pipeline()
#         pipe.hgetall(key)
#         current = (await pipe.execute())[0]
# 
#         phase = _decode(current.get(b"phase", b""))
# 
#         # Case 1: sync in progress -> ignore entirely
#         if phase == "syncing":
#             return DebounceResult(
#                 action=DebounceAction.IGNORE,
#                 provider=provider,
#                 tenant_id=tenant_id,
#             )
# 
#         # Case 2: window already open -> join it, increment trigger count
#         if phase == "window":
#             pipe2 = self._redis.pipeline()
#             pipe2.hincrby(key, "trigger_count", 1)
#             pipe2.expire(key, DEBOUNCE_KEY_TTL_SECONDS)
#             await pipe2.execute()
#             count = int(current.get(b"trigger_count", b"0")) + 1
#             return DebounceResult(
#                 action=DebounceAction.JOIN_WINDOW,
#                 provider=provider,
#                 tenant_id=tenant_id,
#                 trigger_count=count,
#             )
# 
#         # Case 3: idle -> open a fresh window
#         pipe3 = self._redis.pipeline()
#         pipe3.hset(
#             key,
#             mapping={
#                 "phase": "window",
#                 "window_start": str(now),
#                 "trigger_count": "1",
#                 "sync_lock": "0",
#             },
#         )
#         pipe3.expire(key, DEBOUNCE_KEY_TTL_SECONDS)
#         await pipe3.execute()
#         return DebounceResult(
#             action=DebounceAction.OPEN_WINDOW,
#             provider=provider,
#             tenant_id=tenant_id,
#             trigger_count=1,
#         )
# 
#     async def begin_sync(self, provider: str, tenant_id: str) -> None:
#         """Mark the debounce key as syncing (locks out new webhooks)."""
#         key = self._key(provider, tenant_id)
#         await self._redis.hset(
#             key,
#             mapping={"phase": "syncing", "sync_lock": "1"},
#         )
#         await self._redis.expire(key, DEBOUNCE_KEY_TTL_SECONDS)
#         logger.info("debounce_sync_started", provider=provider, tenant_id=tenant_id)
# 
#     async def end_sync(self, provider: str, tenant_id: str) -> None:
#         """Clear debounce state after sync completes; fresh window allowed next."""
#         key = self._key(provider, tenant_id)
#         await self._redis.delete(key)
#         logger.info("debounce_sync_completed", provider=provider, tenant_id=tenant_id)
# 
#     async def schedule_sync(
#         self,
#         provider: str,
#         tenant_id: str,
#         callback: Callable[[], object],
#         delay: float = DEBOUNCE_WINDOW_SECONDS,
#     ) -> None:
#         """Delay ``delay`` seconds, then run ``callback`` between begin/end sync.
# 
#         Wraps ``callback`` in an asyncio.Task so the caller (FastAPI
#         BackgroundTasks) can return immediately while the sync fires later.
#         """
# 
#         async def _run() -> None:
#             try:
#                 await asyncio.sleep(delay)
#                 await self.begin_sync(provider, tenant_id)
#                 result = callback()
#                 if asyncio.iscoroutine(result):
#                     await result
#             except Exception as exc:
#                 logger.error(
#                     "debounce_sync_failed",
#                     provider=provider,
#                     tenant_id=tenant_id,
#                     error_class=type(exc).__name__,
#                 )
#             finally:
#                 await self.end_sync(provider, tenant_id)
# 
#         asyncio.create_task(_run())
# 
# 
# def _decode(value: bytes | str) -> str:
#     if isinstance(value, bytes):
#         return value.decode("utf-8", errors="replace")
#     return str(value)



"""Redis-backed debounce gate for Okta/Ramp webhooks.

Treats incoming webhooks as change-detection triggers rather than events to
store immediately. The first webhook opens a five-second debounce window;
subsequent webhooks during that window are acknowledged but not persisted.
When the window closes, a single pull-sync fires. While a sync is running,
new webhooks are ignored.

State key: zellovest:debounce:{provider}:{tenant_id}

Hash fields:
    phase        -> "window" | "syncing"
    window_start -> unix timestamp (float, seconds)
    trigger_count -> int
    sync_lock    -> "0" | "1"

TTL: 30 seconds (auto-cleanup if sync crashes mid-flight).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

import redis  # synchronous client; matches app.state.redis in main.py

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

DEBOUNCE_WINDOW_SECONDS = 5.0
DEBOUNCE_KEY_TTL_SECONDS = 30


class DebounceAction(StrEnum):
    """Outcome of evaluating an incoming webhook against the debounce gate."""

    OPEN_WINDOW = "open_window"   # First webhook; window opened, schedule sync
    JOIN_WINDOW = "join_window"   # Within window; ack only, no storage/sync
    IGNORE = "ignore"             # Sync in progress; ack only, drop entirely


@dataclass(slots=True)
class DebounceResult:
    action: DebounceAction
    provider: str
    tenant_id: str
    trigger_count: int = 0


class WebhookDebounce:
    """Redis-backed debounce state machine per (provider, tenant_id).

    Methods are async def so FastAPI can await them, but redis operations are
    synchronous (compatible with app.state.redis created via
    redis.Redis.from_url in main.py).
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    def _key(self, provider: str, tenant_id: str) -> str:
        return f"zellovest:debounce:{provider}:{tenant_id}"

    async def check(
        self,
        provider: str,
        tenant_id: str,
    ) -> DebounceResult:
        """Evaluate an incoming webhook and update debounce state.

        Returns:
            OPEN_WINDOW: first webhook; caller should ack + schedule sync after window
            JOIN_WINDOW: within window; caller should ack only (no storage, no sync)
            IGNORE: sync in progress; caller should ack only (drop entirely)
        """
        key = self._key(provider, tenant_id)
        now = time.time()

        current = self._redis.hgetall(key)  # sync call, no await
        phase = _decode(current.get(b"phase", b""))

        # Case 1: sync in progress -> ignore entirely
        if phase == "syncing":
            return DebounceResult(
                action=DebounceAction.IGNORE,
                provider=provider,
                tenant_id=tenant_id,
            )

        # Case 2: window already open -> join it, increment trigger count
        if phase == "window":
            self._redis.hincrby(key, "trigger_count", 1)   # sync
            self._redis.expire(key, DEBOUNCE_KEY_TTL_SECONDS)  # sync
            count = int(current.get(b"trigger_count", b"0")) + 1
            return DebounceResult(
                action=DebounceAction.JOIN_WINDOW,
                provider=provider,
                tenant_id=tenant_id,
                trigger_count=count,
            )

        # Case 3: idle -> open a fresh window
        self._redis.hset(
            key,
            mapping={
                "phase": "window",
                "window_start": str(now),
                "trigger_count": "1",
                "sync_lock": "0",
            },
        )
        self._redis.expire(key, DEBOUNCE_KEY_TTL_SECONDS)
        return DebounceResult(
            action=DebounceAction.OPEN_WINDOW,
            provider=provider,
            tenant_id=tenant_id,
            trigger_count=1,
        )

    async def begin_sync(self, provider: str, tenant_id: str) -> None:
        """Mark the debounce key as syncing (locks out new webhooks)."""
        key = self._key(provider, tenant_id)
        self._redis.hset(
            key,
            mapping={"phase": "syncing", "sync_lock": "1"},
        )
        self._redis.expire(key, DEBOUNCE_KEY_TTL_SECONDS)
        logger.info("debounce_sync_started", provider=provider, tenant_id=tenant_id)

    async def end_sync(self, provider: str, tenant_id: str) -> None:
        """Clear debounce state after sync completes; fresh window allowed next."""
        key = self._key(provider, tenant_id)
        self._redis.delete(key)
        logger.info("debounce_sync_completed", provider=provider, tenant_id=tenant_id)

    async def schedule_sync(
        self,
        provider: str,
        tenant_id: str,
        callback: Callable[[], object],
        delay: float = DEBOUNCE_WINDOW_SECONDS,
    ) -> None:
        """Delay ``delay`` seconds, then run ``callback`` between begin/end sync."""

        async def _run() -> None:
            try:
                await asyncio.sleep(delay)
                await self.begin_sync(provider, tenant_id)
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "debounce_sync_failed",
                    provider=provider,
                    tenant_id=tenant_id,
                    error_class=type(exc).__name__,
                )
            finally:
                await self.end_sync(provider, tenant_id)

        asyncio.create_task(_run())


def _decode(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
