"""modality on registrations; portfolio clients, commercials, signature tracking and import log

Existing registrations predate the One7 line and are all Normal: the column is added with
server_default 'normal', so no row is left without a modality.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercials",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_key", sa.String(120), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "portfolio_clients",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("external_id", sa.String(64), nullable=True),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False),
        sa.Column("commercial_id", sa.UUID(), sa.ForeignKey("commercials.id"), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("pre_committee_date", sa.Date(), nullable=True),
        sa.Column("committee_date", sa.Date(), nullable=True),
        sa.Column("contract_issued_date", sa.Date(), nullable=True),
        sa.Column("signature_completed_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("risk_exit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("limit_expired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("milestones", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("followups", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status_history", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("legacy_history", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("external_id"),
        sa.CheckConstraint("modality IN ('normal','one7')", name="ck_portfolio_clients_modality"),
    )
    op.create_index("ix_portfolio_clients_modality", "portfolio_clients", ["modality"])
    op.create_index("ix_portfolio_clients_name_key", "portfolio_clients", ["name_key"])
    op.create_index("ix_portfolio_clients_commercial_id", "portfolio_clients", ["commercial_id"])
    op.create_index("ix_portfolio_clients_modality_status", "portfolio_clients", ["modality", "status"])

    op.create_table(
        "signature_trackings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("external_id", sa.String(64), nullable=True),
        sa.Column("client_id", sa.UUID(), sa.ForeignKey("portfolio_clients.id"), nullable=True),
        sa.Column("modality", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("company_name", sa.String(300), nullable=False),
        sa.Column("commercial_id", sa.UUID(), sa.ForeignKey("commercials.id"), nullable=True),
        sa.Column("followups", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("auto_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_signature_trackings_client_id", "signature_trackings", ["client_id"])
    op.create_index("ix_signature_trackings_modality", "signature_trackings", ["modality"])
    op.create_table(
        "signature_contracts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tracking_id", sa.UUID(), sa.ForeignKey("signature_trackings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("process_number", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_date", sa.Date(), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.UniqueConstraint("tracking_id", "kind"),
        sa.CheckConstraint("kind IN ('SEC','FIDC')", name="ck_signature_contracts_kind"),
        sa.CheckConstraint("signed_date IS NULL OR issued_date IS NULL OR signed_date >= issued_date", name="ck_signature_contracts_order"),
    )
    op.create_index("ix_signature_contracts_tracking_id", "signature_contracts", ["tracking_id"])
    op.create_table(
        "data_imports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("imported_by_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_data_imports_sha256", "data_imports", ["sha256"])

    op.add_column("registrations", sa.Column("modality", sa.String(16), nullable=False, server_default="normal"))
    op.add_column("registrations", sa.Column("client_id", sa.UUID(), sa.ForeignKey("portfolio_clients.id"), nullable=True))
    op.create_check_constraint("ck_registrations_modality", "registrations", "modality IN ('normal','one7')")
    op.create_index("ix_registrations_modality", "registrations", ["modality"])
    op.create_index("ix_registrations_client_id", "registrations", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_registrations_client_id", table_name="registrations")
    op.drop_index("ix_registrations_modality", table_name="registrations")
    op.drop_constraint("ck_registrations_modality", "registrations")
    op.drop_column("registrations", "client_id")
    op.drop_column("registrations", "modality")
    op.drop_table("data_imports")
    op.drop_table("signature_contracts")
    op.drop_table("signature_trackings")
    op.drop_table("portfolio_clients")
    op.drop_table("commercials")
