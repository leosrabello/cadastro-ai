"""registrations.commercial_id (the commercial responsible, chosen at creation) and economic groups

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "economic_groups",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.String(200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("registrations", sa.Column("commercial_id", sa.UUID(), sa.ForeignKey("commercials.id"), nullable=True))
    op.add_column("registrations", sa.Column("group_id", sa.UUID(), sa.ForeignKey("economic_groups.id"), nullable=True))
    op.create_index("ix_registrations_commercial_id", "registrations", ["commercial_id"])
    op.create_index("ix_registrations_group_id", "registrations", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_registrations_group_id", table_name="registrations")
    op.drop_index("ix_registrations_commercial_id", table_name="registrations")
    op.drop_column("registrations", "group_id")
    op.drop_column("registrations", "commercial_id")
    op.drop_table("economic_groups")
