"""Row Level Security (Postgres / Supabase only; a no-op on SQLite).

Defense in depth (D-021): the backend enforces ownership itself and connects as the table owner,
which bypasses RLS. These policies protect direct PostgREST access with a user's JWT: a user may
read only rows of projects they own, and nobody may write through PostgREST, because every write
must pass the backend's validation. qloo_cache gets RLS with no policy, so only the backend can
use it. Policies need Supabase's auth.uid(); on plain Postgres RLS is enabled without policies,
which denies every role except the owner.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHILD_TABLES = (
    "brand_kits", "campaigns", "campaign_versions", "studies", "agent_runs", "evidence_records",
    "synthetic_responses", "adaptations", "evaluations", "reports",
)
OWNED_PROJECTS = "(SELECT id FROM projects WHERE owner_id = (SELECT auth.uid()))"


def _policies() -> list[str]:
    statements = ["CREATE POLICY projects_select_own ON projects FOR SELECT TO authenticated "
                  "USING (owner_id = (SELECT auth.uid()))"]
    statements += [f"CREATE POLICY {table}_select_own ON {table} FOR SELECT TO authenticated "
                   f"USING (project_id IN {OWNED_PROJECTS})" for table in CHILD_TABLES]
    return statements


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in ("projects", *CHILD_TABLES, "qloo_cache"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    creates = "\n".join(f"    EXECUTE $p${statement}$p$;" for statement in _policies())
    op.execute(
        "DO $do$\nBEGIN\n"
        "  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace\n"
        "             WHERE n.nspname = 'auth' AND p.proname = 'uid')\n"
        "     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN\n"
        f"{creates}\n"
        "  END IF;\nEND\n$do$;"
    )


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in ("projects", *CHILD_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_select_own ON {table}")
    for table in ("projects", *CHILD_TABLES, "qloo_cache"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
