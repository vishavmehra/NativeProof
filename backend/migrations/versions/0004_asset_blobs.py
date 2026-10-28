"""Asset bytes in the database (ASSET_STORAGE_BACKEND=database) for hosts with an ephemeral disk.

asset_blobs is owner-scoped through (asset_id, project_id) -> assets. On Postgres it gets RLS with a SELECT-only
policy for the owner, like the other user tables; there is no write policy, so the Data API cannot write.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = (
    "CREATE POLICY asset_blobs_select_own ON asset_blobs FOR SELECT TO authenticated "
    "USING (project_id IN (SELECT id FROM projects WHERE owner_id = (SELECT auth.uid())))"
)


def upgrade() -> None:
    op.create_table(
        "asset_blobs",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id", "project_id"], ["assets.id", "assets.project_id"],
                                name=op.f("fk_asset_blobs_asset_id_assets")),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_asset_blobs")),
    )
    if op.get_context().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE asset_blobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $do$\nBEGIN\n"
        "  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace\n"
        "             WHERE n.nspname = 'auth' AND p.proname = 'uid')\n"
        "     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN\n"
        f"    EXECUTE $p${POLICY}$p$;\n"
        "  END IF;\nEND\n$do$;"
    )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS asset_blobs_select_own ON asset_blobs")
    op.drop_table("asset_blobs")
