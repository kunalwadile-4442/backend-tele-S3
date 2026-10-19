"""Initial user, workspace, and file tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("email", sa.String(320), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("workspaces", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_table("files", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("filename", sa.String(255), nullable=False), sa.Column("mime_type", sa.String(255), nullable=False), sa.Column("size", sa.BigInteger(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("provider_ref", sa.String(255), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("workspace_id", "sha256", name="uq_file_workspace_checksum"))
    op.create_index("ix_files_workspace_id", "files", ["workspace_id"])
    op.create_index("ix_files_uploaded_by", "files", ["uploaded_by"])

def downgrade():
    op.drop_table("files"); op.drop_table("workspaces"); op.drop_index("ix_users_email", table_name="users"); op.drop_table("users")
