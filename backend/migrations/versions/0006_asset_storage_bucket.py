"""Supabase Storage for uploads: the private `assets` bucket and owner-folder policies on storage.objects.

Object keys are `{owner_id}/{asset_id}`. The backend reads and writes with SUPABASE_SECRET_KEY and enforces ownership
itself; the browser never talks to Storage. These policies are defense in depth for the `authenticated` role:
each user may select, insert, and delete only objects in their own folder. A clean no-op where the `storage`
schema or Supabase auth is absent (plain Postgres, SQLite).

Downgrade drops the policies and keeps the bucket and its objects: Supabase refuses direct deletes from storage
tables, and removing uploads belongs to the Storage API, not a schema rollback.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28 23:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUCKET = "assets"
SIZE_LIMIT = 5 * 1024 * 1024  # = the MAX_IMAGE_BYTES default (app/core/config.py)
MIME_TYPES = ("image/png", "image/jpeg", "image/webp")  # = what app/services/assets.py accepts (magic bytes)
OWN_FOLDER = f"bucket_id = '{BUCKET}' AND (storage.foldername(name))[1] = (SELECT auth.uid())::text"
POLICIES = {
    "assets_select_own": f"FOR SELECT TO authenticated USING ({OWN_FOLDER})",
    "assets_insert_own": f"FOR INSERT TO authenticated WITH CHECK ({OWN_FOLDER})",
    "assets_delete_own": f"FOR DELETE TO authenticated USING ({OWN_FOLDER})",
}
STORAGE = (
    "IF to_regclass('storage.buckets') IS NOT NULL AND to_regclass('storage.objects') IS NOT NULL\n"
    "     AND to_regprocedure('storage.foldername(text)') IS NOT NULL AND to_regprocedure('auth.uid()') IS NOT NULL\n"
    "     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN\n"
)


def _supabase(body: str) -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(f"DO $do$\nBEGIN\n  {STORAGE}{body}\n  END IF;\nEND\n$do$;")


def upgrade() -> None:
    mime = ", ".join(f"'{t}'" for t in MIME_TYPES)
    bucket = (  # EXECUTE: nothing names a storage table until the guard has found one
        f"    EXECUTE $b$INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)\n"
        f"      VALUES ('{BUCKET}', '{BUCKET}', false, {SIZE_LIMIT}, ARRAY[{mime}]::text[])\n"
        f"      ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = EXCLUDED.file_size_limit,\n"
        f"        allowed_mime_types = EXCLUDED.allowed_mime_types$b$;"
    )
    policies = "\n".join(
        f"    EXECUTE $p$DROP POLICY IF EXISTS {name} ON storage.objects$p$;\n"
        f"    EXECUTE $p$CREATE POLICY {name} ON storage.objects {rule}$p$;"
        for name, rule in POLICIES.items()
    )
    _supabase(f"{bucket}\n{policies}")


def downgrade() -> None:
    _supabase("\n".join(f"    EXECUTE $p$DROP POLICY IF EXISTS {name} ON storage.objects$p$;" for name in POLICIES))
