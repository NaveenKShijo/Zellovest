"""Backfill document and upload vendor links from typed ledger rows.

Revision ID: 0015_backfill_document_vendors
Revises: 0014_human_contract_review
"""

from alembic import op


revision = "0015_backfill_document_vendors"
down_revision = "0014_human_contract_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Populate missing canonical vendor links without overwriting corrections."""
    op.execute(
        """
        UPDATE documents AS d
        SET vendor_id = i.vendor_id
        FROM invoices AS i
        WHERE d.id = i.document_id
          AND d.tenant_id = i.tenant_id
          AND d.vendor_id IS NULL
          AND i.vendor_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE documents AS d
        SET vendor_id = po.vendor_id
        FROM purchase_orders AS po
        WHERE d.id = po.source_document_id
          AND d.tenant_id = po.tenant_id
          AND d.vendor_id IS NULL
          AND po.vendor_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE documents AS d
        SET vendor_id = c.vendor_id
        FROM contracts AS c
        WHERE d.id = c.document_id
          AND d.tenant_id = c.tenant_id
          AND d.vendor_id IS NULL
          AND c.vendor_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE uploads AS u
        SET vendor_id = d.vendor_id::text
        FROM documents AS d
        WHERE u.id = d.upload_id
          AND u.tenant_id = d.tenant_id
          AND u.vendor_id IS NULL
          AND d.vendor_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Keep backfilled links because the migration cannot identify their origin."""
    pass
