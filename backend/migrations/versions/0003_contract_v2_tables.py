"""Contract v2 tables (docs/06 section 6): Brand Memory columns, Cultural DNA, market comparisons,
snapshots and trend comparisons, arenas, risk scans and findings, assets, transcripts, and embeddings.
Also widens the agent_runs run_type check and, on Postgres only, adds the v2 RLS policies.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26 00:48:36.712572
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _create_tables() -> None:
    op.create_table('assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('content_type', sa.String(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(), nullable=False),
    sa.Column('storage_name', sa.String(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('image', 'audio')", name=op.f('ck_assets_kind')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_assets_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assets')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_assets_id_project_id')),
    sa.UniqueConstraint('storage_name', name=op.f('uq_assets_storage_name'))
    )
    op.create_index('ix_assets_project_id_created_at', 'assets', ['project_id', 'created_at'], unique=False)

    op.create_table('embeddings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('source_kind', sa.String(), nullable=False),
    sa.Column('source_id', sa.String(), nullable=False),
    sa.Column('text', sa.String(), nullable=False),
    sa.Column('metadata', JSON, nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('dims', sa.Integer(), nullable=False),
    sa.Column('config_version', sa.String(), nullable=False),
    sa.Column('vector', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_embeddings_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_embeddings')),
    sa.UniqueConstraint('project_id', 'source_kind', 'source_id', 'model', 'config_version', name=op.f('uq_embeddings_project_id_source_kind_source_id_model_config_version'))
    )
    op.create_index('ix_embeddings_project_id_model_dims', 'embeddings', ['project_id', 'model', 'dims'], unique=False)

    op.create_table('transcripts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('text', sa.String(), nullable=False),
    sa.Column('approved_text', sa.String(), nullable=True),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('model_id', sa.String(), nullable=False),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('unreviewed', 'approved')", name=op.f('ck_transcripts_status')),
    sa.ForeignKeyConstraint(['asset_id', 'project_id'], ['assets.id', 'assets.project_id'], name=op.f('fk_transcripts_asset_id_assets')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcripts'))
    )
    op.create_table('arenas',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('variants', JSON, nullable=False),
    sa.Column('criteria', JSON, nullable=False),
    sa.Column('preferred_variant_id', sa.String(), nullable=True),
    sa.Column('result', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_arenas_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_arenas_run_id_agent_runs')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_arenas_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arenas'))
    )
    op.create_index('ix_arenas_campaign_id_created_at', 'arenas', ['campaign_id', 'created_at'], unique=False)

    op.create_table('cultural_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('lineage_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('subject', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('markets', JSON, nullable=False),
    sa.Column('notes', sa.String(), nullable=True),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('brand_name', sa.String(), nullable=False),
    sa.Column('source_discovery_run_ids', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_cultural_profiles_version')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_cultural_profiles_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_cultural_profiles_run_id_agent_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cultural_profiles')),
    sa.UniqueConstraint('lineage_id', 'version', name=op.f('uq_cultural_profiles_lineage_id_version'))
    )
    op.create_index('ix_cultural_profiles_project_id_created_at', 'cultural_profiles', ['project_id', 'created_at'], unique=False)

    op.create_table('market_comparisons',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('markets', JSON, nullable=False),
    sa.Column('product_category', sa.String(), nullable=False),
    sa.Column('research_question', sa.String(), nullable=False),
    sa.Column('reference_terms', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_market_comparisons_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_market_comparisons_run_id_agent_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_comparisons'))
    )
    op.create_index('ix_market_comparisons_project_id_created_at', 'market_comparisons', ['project_id', 'created_at'], unique=False)

    op.create_table('risk_scans',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('market', JSON, nullable=False),
    sa.Column('source_kind', sa.String(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=True),
    sa.Column('content', JSON, nullable=False),
    sa.Column('asset_ids', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("source_kind IN ('content_version', 'adaptation', 'custom')", name=op.f('ck_risk_scans_source_kind')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_risk_scans_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_risk_scans_run_id_agent_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_scans')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_risk_scans_id_project_id'))
    )
    op.create_index('ix_risk_scans_campaign_id_created_at', 'risk_scans', ['campaign_id', 'created_at'], unique=False)

    op.create_table('snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=True),
    sa.Column('discovery_run_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('market', JSON, nullable=False),
    sa.Column('product_category', sa.String(), nullable=False),
    sa.Column('reference_terms', JSON, nullable=False),
    sa.Column('captured_at', UTCDateTime(), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('reference_count', sa.Integer(), nullable=False),
    sa.Column('evidence_count', sa.Integer(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['discovery_run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_snapshots_discovery_run_id_agent_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_snapshots')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_snapshots_id_project_id'))
    )
    op.create_index('ix_snapshots_project_id_created_at', 'snapshots', ['project_id', 'created_at'], unique=False)

    op.create_table('risk_findings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('scan_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('payload', JSON, nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('status_note', sa.String(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('open', 'dismissed', 'resolved', 'applied')", name=op.f('ck_risk_findings_status')),
    sa.ForeignKeyConstraint(['scan_id', 'project_id'], ['risk_scans.id', 'risk_scans.project_id'], name=op.f('fk_risk_findings_scan_id_risk_scans')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_findings'))
    )
    op.create_index('ix_risk_findings_scan_id_position', 'risk_findings', ['scan_id', 'position'], unique=False)

    op.create_table('trend_comparisons',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('base_snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('target_snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('comparable', sa.Boolean(), nullable=False),
    sa.Column('change_count', sa.Integer(), nullable=False),
    sa.Column('content', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['base_snapshot_id', 'project_id'], ['snapshots.id', 'snapshots.project_id'], name=op.f('fk_trend_comparisons_base_snapshot_id_snapshots')),
    sa.ForeignKeyConstraint(['target_snapshot_id', 'project_id'], ['snapshots.id', 'snapshots.project_id'], name=op.f('fk_trend_comparisons_target_snapshot_id_snapshots')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trend_comparisons'))
    )
    op.create_index('ix_trend_comparisons_project_id_created_at', 'trend_comparisons', ['project_id', 'created_at'], unique=False)

    with op.batch_alter_table('brand_kits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('positioning', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('communication_style', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('audience_preferences', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('approved_examples', JSON, nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column('constraints', JSON, nullable=False, server_default=sa.text("'[]'")))



def _drop_tables() -> None:
    with op.batch_alter_table('brand_kits', schema=None) as batch_op:
        batch_op.drop_column('constraints')
        batch_op.drop_column('approved_examples')
        batch_op.drop_column('audience_preferences')
        batch_op.drop_column('communication_style')
        batch_op.drop_column('positioning')

    op.drop_table('trend_comparisons')
    op.drop_table('risk_findings')
    op.drop_table('snapshots')
    op.drop_table('risk_scans')
    op.drop_table('market_comparisons')
    op.drop_table('cultural_profiles')
    op.drop_table('arenas')
    op.drop_table('transcripts')
    op.drop_table('embeddings')
    op.drop_table('assets')


V1_RUN_TYPES = "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation'"
V2_RUN_TYPES = V1_RUN_TYPES + ", 'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison'"
# Project-scoped v2 tables users may read through PostgREST; embeddings stay backend-only like qloo_cache.
READABLE = (
    "cultural_profiles", "market_comparisons", "snapshots", "trend_comparisons", "arenas", "risk_scans",
    "risk_findings", "assets", "transcripts",
)
OWNED_PROJECTS = "(SELECT id FROM projects WHERE owner_id = (SELECT auth.uid()))"


def _run_types(values: str) -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_agent_runs_run_type"), type_="check")
        batch_op.create_check_constraint("run_type", f"run_type IN ({values})")


def upgrade() -> None:
    _create_tables()
    _run_types(V2_RUN_TYPES)
    if op.get_context().dialect.name != "postgresql":
        return
    for table in (*READABLE, "embeddings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    creates = "\n".join(
        f"    EXECUTE $p$CREATE POLICY {table}_select_own ON {table} FOR SELECT TO authenticated "
        f"USING (project_id IN {OWNED_PROJECTS})$p$;"
        for table in READABLE
    )
    op.execute(
        "DO $do$\nBEGIN\n"
        "  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace\n"
        "             WHERE n.nspname = 'auth' AND p.proname = 'uid')\n"
        "     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN\n"
        f"{creates}\n"
        "  END IF;\nEND\n$do$;"
    )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        for table in READABLE:
            op.execute(f"DROP POLICY IF EXISTS {table}_select_own ON {table}")
    op.execute("DELETE FROM agent_runs WHERE run_type NOT IN (" + V1_RUN_TYPES + ")")
    _run_types(V1_RUN_TYPES)
    _drop_tables()
