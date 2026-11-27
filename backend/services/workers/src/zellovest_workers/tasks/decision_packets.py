"""Background workers that pre-compute evidence-backed decision packets."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from zellovest_shared.db.core import Tenant
from zellovest_shared.db.intelligence import MaverickAlert, ReconciliationException
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.db.transact import Contract
from zellovest_shared.decision_packets import (
    build_ap_investigation_packet_sync,
    build_maverick_review_packet_sync,
    build_renewal_dossier_packet_sync,
    refresh_tenant_decision_packets_sync,
)
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="zellovest.workers.tasks.decision_packets.precompute_ap_investigation_packet",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def precompute_ap_investigation_packet(tenant_id: str, exception_id: str) -> dict[str, Any]:
    """Build and persist an AP investigation packet immediately after an exception fires."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        packet = build_ap_investigation_packet_sync(
            session, tenant_id=tenant_id, exception_id=uuid.UUID(exception_id)
        )
        session.commit()
        return {
            "tenant_id": tenant_id,
            "exception_id": exception_id,
            "packet_id": str(packet.id) if packet else None,
            "status": "completed" if packet else "not_found",
        }
    except Exception as exc:
        session.rollback()
        logger.warning(
            "precompute_ap_packet_failed",
            tenant_id=tenant_id,
            exception_id=exception_id,
            error_class=type(exc).__name__,
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.decision_packets.precompute_renewal_dossier_packet",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def precompute_renewal_dossier_packet(tenant_id: str, contract_id: str) -> dict[str, Any]:
    """Build and persist an executive renewal dossier for an upcoming renewal."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        packet = build_renewal_dossier_packet_sync(
            session, tenant_id=tenant_id, contract_id=uuid.UUID(contract_id)
        )
        session.commit()
        return {
            "tenant_id": tenant_id,
            "contract_id": contract_id,
            "packet_id": str(packet.id) if packet else None,
            "status": "completed" if packet else "not_found",
        }
    except Exception as exc:
        session.rollback()
        logger.warning(
            "precompute_renewal_packet_failed",
            tenant_id=tenant_id,
            contract_id=contract_id,
            error_class=type(exc).__name__,
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.decision_packets.precompute_maverick_packet",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def precompute_maverick_packet(tenant_id: str, alert_id: str) -> dict[str, Any]:
    """Build and persist a consolidation decision packet for a Maverick alert."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        packet = build_maverick_review_packet_sync(
            session, tenant_id=tenant_id, alert_id=uuid.UUID(alert_id)
        )
        session.commit()
        return {
            "tenant_id": tenant_id,
            "alert_id": alert_id,
            "packet_id": str(packet.id) if packet else None,
            "status": "completed" if packet else "not_found",
        }
    except Exception as exc:
        session.rollback()
        logger.warning(
            "precompute_maverick_packet_failed",
            tenant_id=tenant_id,
            alert_id=alert_id,
            error_class=type(exc).__name__,
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.decision_packets.refresh_all_tenant_decision_packets",
    queue=QUEUE_ANALYTICS,
    max_retries=2,
)
def refresh_all_tenant_decision_packets() -> dict[str, Any]:
    """Celery Beat sweep ensuring every active tenant's decision packets stay fresh."""
    factory = get_session_factory()
    session: Session = factory()
    totals = {"ap_investigation": 0, "renewal_dossier": 0, "maverick_review": 0}
    tenants_processed = 0
    try:
        tenant_ids: set[str] = set()
        for model in (Tenant, Contract, ReconciliationException, MaverickAlert):
            rows = session.execute(select(distinct(model.tenant_id))).scalars().all()
            tenant_ids.update(str(t) for t in rows if t)

        for tenant_id in sorted(tenant_ids):
            try:
                counts = refresh_tenant_decision_packets_sync(session, tenant_id)
                tenants_processed += 1
                for key in totals:
                    totals[key] += counts.get(key, 0)
            except Exception as exc:
                session.rollback()
                logger.warning(
                    "decision_packet_tenant_refresh_failed",
                    tenant_id=tenant_id,
                    error_class=type(exc).__name__,
                )
        return {"tenants_processed": tenants_processed, **totals}
    finally:
        session.close()
