"""Add explicit contract version lineage and stable commercial lines.

Revision ID: 0016_contract_version_lineage
Revises: 0015_backfill_document_vendors
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_contract_version_lineage"
down_revision = "0015_backfill_document_vendors"
branch_labels = None
depends_on = None


change_type = postgresql.ENUM(
    "original",
    "amendment",
    "renewal",
    "price_revision",
    name="contract_change_type",
    create_type=False,
)


def upgrade() -> None:
    """Create version headers and line identities, then backfill legacy rows."""
    change_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "contract_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column(
            "contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contract_versions.id"),
            nullable=True,
        ),
        sa.Column("change_type", change_type, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("contract_start_date", sa.Date(), nullable=True),
        sa.Column("contract_end_date", sa.Date(), nullable=True),
        sa.Column("renewal_date", sa.Date(), nullable=True),
        sa.Column("notice_period_days", sa.Integer(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=True),
        sa.Column("termination_clause", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "contract_id", "version_no", name="uq_contract_versions_no"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "contract_id",
            "source_document_id",
            name="uq_contract_versions_source_document",
        ),
    )
    op.create_index(
        "ix_contract_versions_parent",
        "contract_versions",
        ["tenant_id", "parent_version_id"],
    )
    op.create_index(
        "ix_contract_versions_tenant",
        "contract_versions",
        ["tenant_id"],
    )

    op.create_table(
        "contract_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column(
            "contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id"),
            nullable=False,
        ),
        sa.Column("legacy_line_no", sa.Integer(), nullable=True),
        sa.Column(
            "initial_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "contract_id",
            "legacy_line_no",
            name="uq_contract_lines_legacy_no",
        ),
    )
    op.create_index(
        "ix_contract_lines_contract",
        "contract_lines",
        ["tenant_id", "contract_id"],
    )
    op.create_index("ix_contract_lines_tenant", "contract_lines", ["tenant_id"])

    op.execute(
        """
        INSERT INTO contract_versions (
            id, tenant_id, contract_id, version_no, source_document_id,
            parent_version_id, change_type, effective_from, effective_to,
            title, contract_start_date, contract_end_date, renewal_date,
            notice_period_days, auto_renew, termination_clause
        )
        SELECT
            gen_random_uuid(),
            c.tenant_id,
            t.contract_id,
            t.version_no,
            COALESCE(
                (array_agg(t.amendment_document_id ORDER BY t.created_at)
                    FILTER (WHERE t.amendment_document_id IS NOT NULL))[1],
                CASE WHEN t.version_no = 1 THEN c.document_id ELSE NULL END
            ),
            NULL,
            CASE WHEN t.version_no = 1 THEN 'original' ELSE 'amendment' END::contract_change_type,
            MIN(t.effective_from),
            CASE WHEN bool_or(t.effective_to IS NULL) THEN NULL ELSE MAX(t.effective_to) END,
            c.title,
            c.start_date,
            c.end_date,
            c.renewal_date,
            c.notice_period_days,
            c.auto_renew,
            c.termination_clause
        FROM contract_terms_versioned AS t
        JOIN contracts AS c ON c.id = t.contract_id AND c.tenant_id = t.tenant_id
        GROUP BY
            c.tenant_id,
            t.contract_id,
            t.version_no,
            c.document_id,
            c.title,
            c.start_date,
            c.end_date,
            c.renewal_date,
            c.notice_period_days,
            c.auto_renew,
            c.termination_clause
        """
    )
    op.execute(
        """
        UPDATE contract_versions AS child
        SET parent_version_id = (
            SELECT parent.id
            FROM contract_versions AS parent
            WHERE parent.tenant_id = child.tenant_id
              AND parent.contract_id = child.contract_id
              AND parent.version_no < child.version_no
            ORDER BY parent.version_no DESC
            LIMIT 1
        )
        WHERE child.version_no > 1
        """
    )
    op.execute(
        """
        UPDATE contract_versions AS parent
        SET effective_to = child.effective_from - 1
        FROM contract_versions AS child
        WHERE child.parent_version_id = parent.id
        """
    )
    op.execute(
        """
        INSERT INTO contract_lines (
            id, tenant_id, contract_id, legacy_line_no, initial_document_id
        )
        SELECT
            gen_random_uuid(),
            t.tenant_id,
            t.contract_id,
            t.line_no,
            (array_agg(t.amendment_document_id ORDER BY t.created_at))[1]
        FROM contract_terms_versioned AS t
        GROUP BY t.tenant_id, t.contract_id, t.line_no
        """
    )

    op.add_column(
        "contract_terms_versioned",
        sa.Column("contract_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "contract_terms_versioned",
        sa.Column("contract_line_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE contract_terms_versioned AS t
        SET contract_version_id = v.id
        FROM contract_versions AS v
        WHERE v.tenant_id = t.tenant_id
          AND v.contract_id = t.contract_id
          AND v.version_no = t.version_no
        """
    )
    op.execute(
        """
        UPDATE contract_terms_versioned AS t
        SET contract_line_id = l.id
        FROM contract_lines AS l
        WHERE l.tenant_id = t.tenant_id
          AND l.contract_id = t.contract_id
          AND l.legacy_line_no = t.line_no
        """
    )
    op.alter_column("contract_terms_versioned", "contract_version_id", nullable=False)
    op.alter_column("contract_terms_versioned", "contract_line_id", nullable=False)
    op.create_foreign_key(
        "fk_ctv_contract_version",
        "contract_terms_versioned",
        "contract_versions",
        ["contract_version_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_ctv_contract_line",
        "contract_terms_versioned",
        "contract_lines",
        ["contract_line_id"],
        ["id"],
    )
    op.drop_constraint("no_overlap_contract_terms", "contract_terms_versioned")
    op.execute(
        "ALTER TABLE contract_terms_versioned ADD CONSTRAINT no_overlap_contract_terms "
        "EXCLUDE USING gist (contract_line_id WITH =, "
        "daterange(effective_from, COALESCE(effective_to, 'infinity'::date)) WITH &&)"
    )

    # Historical exceptions used contract_version_id to store a term-row ID.
    # Preserve that reference under its correct name and make contract_version_id
    # point to the new version header.
    op.add_column(
        "reconciliation_exceptions",
        sa.Column("contract_term_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.drop_constraint(
        "reconciliation_exceptions_contract_version_id_fkey",
        "reconciliation_exceptions",
        type_="foreignkey",
    )
    op.execute(
        """
        UPDATE reconciliation_exceptions AS r
        SET contract_term_id = t.id,
            contract_version_id = t.contract_version_id
        FROM contract_terms_versioned AS t
        WHERE t.id = r.contract_version_id
        """
    )
    op.alter_column("reconciliation_exceptions", "contract_term_id", nullable=False)
    op.create_foreign_key(
        "fk_reconciliation_contract_version",
        "reconciliation_exceptions",
        "contract_versions",
        ["contract_version_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_reconciliation_contract_term",
        "reconciliation_exceptions",
        "contract_terms_versioned",
        ["contract_term_id"],
        ["id"],
    )


def downgrade() -> None:
    """Restore exception term-row references and remove lineage tables."""
    op.drop_constraint(
        "fk_reconciliation_contract_term",
        "reconciliation_exceptions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_reconciliation_contract_version",
        "reconciliation_exceptions",
        type_="foreignkey",
    )
    op.execute(
        """
        UPDATE reconciliation_exceptions
        SET contract_version_id = contract_term_id
        """
    )
    op.create_foreign_key(
        "reconciliation_exceptions_contract_version_id_fkey",
        "reconciliation_exceptions",
        "contract_terms_versioned",
        ["contract_version_id"],
        ["id"],
    )
    op.drop_column("reconciliation_exceptions", "contract_term_id")

    op.drop_constraint("no_overlap_contract_terms", "contract_terms_versioned")
    op.execute(
        "ALTER TABLE contract_terms_versioned ADD CONSTRAINT no_overlap_contract_terms "
        "EXCLUDE USING gist (contract_id WITH =, "
        "daterange(effective_from, COALESCE(effective_to, 'infinity'::date)) WITH &&)"
    )
    op.drop_constraint("fk_ctv_contract_line", "contract_terms_versioned", type_="foreignkey")
    op.drop_constraint(
        "fk_ctv_contract_version", "contract_terms_versioned", type_="foreignkey"
    )
    op.drop_column("contract_terms_versioned", "contract_line_id")
    op.drop_column("contract_terms_versioned", "contract_version_id")
    op.drop_index("ix_contract_lines_tenant", table_name="contract_lines")
    op.drop_index("ix_contract_lines_contract", table_name="contract_lines")
    op.drop_table("contract_lines")
    op.drop_index("ix_contract_versions_tenant", table_name="contract_versions")
    op.drop_index("ix_contract_versions_parent", table_name="contract_versions")
    op.drop_table("contract_versions")
    change_type.drop(op.get_bind(), checkfirst=True)
