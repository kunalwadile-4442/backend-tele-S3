"""Add explicit public access per file."""
from alembic import op
import sqlalchemy as sa

revision = "0003_public_file_access"
down_revision = "0002_api_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "files",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("files", "is_public", server_default=None)


def downgrade():
    op.drop_column("files", "is_public")
