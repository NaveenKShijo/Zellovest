"""Checkpoint idempotency tests (SQLite-backed, no Postgres needed)."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from zellovest_shared.db.base import Base
from zellovest_shared.db.models import EntityType, SyncMode
from zellovest_shared.db.repository import SyncStatus, mark_checkpoint


@pytest.fixture
def session():  # type: ignore[no-untyped-def]
    """In-memory SQLite session (enum types stored as VARCHAR)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()


def test_duplicate_event_id_unique_constraint(session):  # type: ignore[no-untyped-def]
    """Two checkpoints with the same event_id violate the unique constraint."""
    from sqlalchemy.exc import IntegrityError

    from zellovest_shared.db.models import IngestionSyncCheckpoint

    session.add(
        IngestionSyncCheckpoint(
            sync_id=uuid.uuid4(),
            tenant_id="t1",
            entity_type=EntityType.EVENTS,
            mode=SyncMode.EVENT_TRIGGERED,
            status=SyncStatus.PENDING,
            event_id="evt_dup",
        )
    )
    session.commit()
    session.add(
        IngestionSyncCheckpoint(
            sync_id=uuid.uuid4(),
            tenant_id="t1",
            entity_type=EntityType.EVENTS,
            mode=SyncMode.EVENT_TRIGGERED,
            status=SyncStatus.PENDING,
            event_id="evt_dup",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_mark_checkpoint_lifecycle(session):  # type: ignore[no-untyped-def]
    """PENDING -> RUNNING -> SUCCESS advances cursors and timestamps."""
    from zellovest_shared.db.models import IngestionSyncCheckpoint

    checkpoint = IngestionSyncCheckpoint(
        sync_id=uuid.uuid4(),
        tenant_id="t1",
        entity_type=EntityType.CARD_TRANSACTIONS,
        mode=SyncMode.INCREMENTAL,
        status=SyncStatus.PENDING,
    )
    session.add(checkpoint)
    session.commit()
    mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING, cursor_token="cur_1")
    assert checkpoint.attempt_count == 1
    assert checkpoint.started_at is not None
    mark_checkpoint(session, checkpoint, status=SyncStatus.SUCCESS, cursor_token="cur_2")
    assert checkpoint.last_success_cursor == "cur_2"
    assert checkpoint.finished_at is not None


def test_mark_checkpoint_failure_truncates(session):  # type: ignore[no-untyped-def]
    """Error logs are truncated and terminal state sets finished_at."""
    from zellovest_shared.db.models import IngestionSyncCheckpoint

    checkpoint = IngestionSyncCheckpoint(
        sync_id=uuid.uuid4(),
        tenant_id="t1",
        entity_type=EntityType.BILLS,
        mode=SyncMode.SCHEDULED,
        status=SyncStatus.RUNNING,
    )
    session.add(checkpoint)
    session.commit()
    mark_checkpoint(session, checkpoint, status=SyncStatus.FAILED, error_log="E" * 9000)
    assert len(checkpoint.error_log or "") <= 4000
    assert checkpoint.finished_at is not None
