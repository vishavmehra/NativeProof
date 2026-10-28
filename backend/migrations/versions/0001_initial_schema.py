"""Initial schema (docs/06_DATABASE_SCHEMA.md).

Projects, brand kits, campaigns and content versions, studies, runs, evidence, synthetic
responses, adaptations, evaluations, reports, and the Qloo cache.

Revision ID: 0001
Revises:
Create Date: 2026-10-25 15:10:05.241553
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table('projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('objective', sa.String(), nullable=True),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('target_markets', JSON, nullable=False),
    sa.Column('last_activity_at', UTCDateTime(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f('ck_projects_mode')),
    sa.CheckConstraint("status IN ('active', 'archived')", name=op.f('ck_projects_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects'))
    )
    op.create_index('ix_projects_owner_id_last_activity_at', 'projects', ['owner_id', 'last_activity_at'], unique=False)

    op.create_table('qloo_cache',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('cache_key', sa.String(), nullable=False),
    sa.Column('workflow_name', sa.String(), nullable=False),
    sa.Column('request_hash', sa.String(), nullable=False),
    sa.Column('response_data', JSON, nullable=False),
    sa.Column('response_hash', sa.String(), nullable=True),
    sa.Column('retrieval_mode', sa.String(), nullable=False),
    sa.Column('retrieved_at', UTCDateTime(), nullable=False),
    sa.Column('expires_at', UTCDateTime(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("retrieval_mode = 'live'", name=op.f('ck_qloo_cache_retrieval_mode')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_qloo_cache')),
    sa.UniqueConstraint('cache_key', name=op.f('uq_qloo_cache_cache_key'))
    )
    op.create_index('ix_qloo_cache_expires_at', 'qloo_cache', ['expires_at'], unique=False)

    op.create_table('brand_kits',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('voice', JSON, nullable=False),
    sa.Column('target_audience', sa.String(), nullable=True),
    sa.Column('preferred_terms', JSON, nullable=False),
    sa.Column('prohibited_terms', JSON, nullable=False),
    sa.Column('protected_terms', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_brand_kits_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brand_kits')),
    sa.UniqueConstraint('project_id', name=op.f('uq_brand_kits_project_id'))
    )
    op.create_table('campaigns',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('campaign_type', sa.String(), nullable=False),
    sa.Column('objective', sa.String(), nullable=True),
    sa.Column('target_markets', JSON, nullable=False),
    sa.Column('evaluation_criteria', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_campaigns_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campaigns')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_campaigns_id_project_id'))
    )
    op.create_index('ix_campaigns_project_id_updated_at', 'campaigns', ['project_id', 'updated_at'], unique=False)

    op.create_table('campaign_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('content', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint('version_number >= 1', name=op.f('ck_campaign_versions_version_number')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_campaign_versions_campaign_id_campaigns')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campaign_versions')),
    sa.UniqueConstraint('campaign_id', 'version_number', name=op.f('uq_campaign_versions_campaign_id_version_number')),
    sa.UniqueConstraint('id', 'campaign_id', name=op.f('uq_campaign_versions_id_campaign_id'))
    )
    op.create_table('studies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('market', JSON, nullable=False),
    sa.Column('research_questions', JSON, nullable=False),
    sa.Column('dimensions', JSON, nullable=False),
    sa.Column('segments', JSON, nullable=False),
    sa.Column('simulation_config', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_studies_campaign_id_campaigns')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_studies')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_studies_id_project_id'))
    )
    op.create_index('ix_studies_campaign_id_created_at', 'studies', ['campaign_id', 'created_at'], unique=False)
    op.create_index('ix_studies_project_id_created_at', 'studies', ['project_id', 'created_at'], unique=False)

    op.create_table('agent_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=True),
    sa.Column('study_id', sa.Uuid(), nullable=True),
    sa.Column('run_type', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('progress', JSON, nullable=True),
    sa.Column('inputs', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('result_ref', JSON, nullable=True),
    sa.Column('error', JSON, nullable=True),
    sa.Column('steps', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('started_at', UTCDateTime(), nullable=True),
    sa.Column('completed_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f('ck_agent_runs_mode')),
    sa.CheckConstraint("run_type IN ('market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation')", name=op.f('ck_agent_runs_run_type')),
    sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')", name=op.f('ck_agent_runs_status')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_agent_runs_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_agent_runs_project_id_projects')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_agent_runs_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_runs')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_agent_runs_id_project_id'))
    )
    op.create_index('ix_agent_runs_project_id_created_at', 'agent_runs', ['project_id', 'created_at'], unique=False)
    op.create_index('ix_agent_runs_status', 'agent_runs', ['status'], unique=False)
    op.create_index('ix_agent_runs_study_id_created_at', 'agent_runs', ['study_id', 'created_at'], unique=False)

    op.create_table('reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('content', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('completed', 'partial')", name=op.f('ck_reports_status')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_reports_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_reports_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')),
    sa.UniqueConstraint('campaign_id', 'version_number', name=op.f('uq_reports_campaign_id_version_number'))
    )
    op.create_index('ix_reports_project_id_created_at', 'reports', ['project_id', 'created_at'], unique=False)

    op.create_table('adaptations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('source_content_version_id', sa.Uuid(), nullable=False),
    sa.Column('parent_adaptation_id', sa.Uuid(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('origin', sa.String(), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('market', JSON, nullable=False),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('strategy', sa.String(), nullable=False),
    sa.Column('content', JSON, nullable=False),
    sa.Column('changes', JSON, nullable=False),
    sa.Column('checks', JSON, nullable=False),
    sa.Column('warnings', JSON, nullable=False),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('context', JSON, nullable=False),
    sa.Column('evidence_ids', JSON, nullable=False),
    sa.Column('protected_terms', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("origin IN ('generated', 'user_edit')", name=op.f('ck_adaptations_origin')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_adaptations_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['parent_adaptation_id'], ['adaptations.id'], name=op.f('fk_adaptations_parent_adaptation_id_adaptations')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_adaptations_run_id_agent_runs')),
    sa.ForeignKeyConstraint(['source_content_version_id', 'campaign_id'], ['campaign_versions.id', 'campaign_versions.campaign_id'], name=op.f('fk_adaptations_source_content_version_id_campaign_versions')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_adaptations_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_adaptations'))
    )
    op.create_index('ix_adaptations_campaign_id_created_at', 'adaptations', ['campaign_id', 'created_at'], unique=False)
    op.create_index('ix_adaptations_run_id', 'adaptations', ['run_id'], unique=False)

    op.create_table('evaluations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('source_content_version_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('market', JSON, nullable=False),
    sa.Column('criteria', JSON, nullable=False),
    sa.Column('results', JSON, nullable=False),
    sa.Column('recommendation', JSON, nullable=True),
    sa.Column('comparability', JSON, nullable=False),
    sa.Column('scoring_version', sa.String(), nullable=False),
    sa.Column('scoring_definition', JSON, nullable=False),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('evidence_ids', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_evaluations_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_evaluations_run_id_agent_runs')),
    sa.ForeignKeyConstraint(['source_content_version_id', 'campaign_id'], ['campaign_versions.id', 'campaign_versions.campaign_id'], name=op.f('fk_evaluations_source_content_version_id_campaign_versions')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_evaluations_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluations'))
    )
    op.create_index('ix_evaluations_campaign_id_created_at', 'evaluations', ['campaign_id', 'created_at'], unique=False)

    op.create_table('evidence_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('source_run_id', sa.Uuid(), nullable=True),
    sa.Column('evidence_type', sa.String(), nullable=False),
    sa.Column('claim_type', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('summary', sa.String(), nullable=False),
    sa.Column('source_provider', sa.String(), nullable=False),
    sa.Column('source_workflow', sa.String(), nullable=True),
    sa.Column('source_reference', sa.String(), nullable=True),
    sa.Column('subject', JSON, nullable=True),
    sa.Column('related_entity', JSON, nullable=True),
    sa.Column('attributes', JSON, nullable=False),
    sa.Column('method', sa.String(), nullable=False),
    sa.Column('retrieval_mode', sa.String(), nullable=False),
    sa.Column('is_live_data', sa.Boolean(), nullable=False),
    sa.Column('retrieved_at', UTCDateTime(), nullable=True),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('provenance', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("NOT (is_live_data AND retrieval_mode NOT IN ('live', 'cached'))", name=op.f('ck_evidence_records_live_flag')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_evidence_records_project_id_projects')),
    sa.ForeignKeyConstraint(['source_run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_evidence_records_source_run_id_agent_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence_records'))
    )
    op.create_index('ix_evidence_records_project_id_created_at', 'evidence_records', ['project_id', 'created_at'], unique=False)
    op.create_index('ix_evidence_records_project_id_evidence_type', 'evidence_records', ['project_id', 'evidence_type'], unique=False)
    op.create_index('ix_evidence_records_source_run_id', 'evidence_records', ['source_run_id'], unique=False)

    op.create_table('synthetic_responses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('segment_label', sa.String(), nullable=False),
    sa.Column('sentiment', sa.String(), nullable=False),
    sa.Column('payload', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_synthetic_responses_run_id_agent_runs')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_synthetic_responses_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_synthetic_responses'))
    )
    op.create_index('ix_synthetic_responses_run_id_position', 'synthetic_responses', ['run_id', 'position'], unique=False)


def downgrade() -> None:
    op.drop_table('synthetic_responses')
    op.drop_table('evidence_records')
    op.drop_table('evaluations')
    op.drop_table('adaptations')
    op.drop_table('reports')
    op.drop_table('agent_runs')
    op.drop_table('studies')
    op.drop_table('campaign_versions')
    op.drop_table('campaigns')
    op.drop_table('brand_kits')
    op.drop_table('qloo_cache')
    op.drop_table('projects')
