"""documents.rendition_key: the PDF made from a Word or Excel original; longer mime_type

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("rendition_key", sa.String(128), nullable=True))
    # Office content types are longer than 64 characters
    op.alter_column("documents", "mime_type", type_=sa.String(128), existing_type=sa.String(64), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("documents", "mime_type", type_=sa.String(64), existing_type=sa.String(128), existing_nullable=False)
    op.drop_column("documents", "rendition_key")
