"""Population studies, social simulation, and follow-ups (contract v3, README section 14).

Adds populations, participants, population_studies, interviews, social_simulations, social_posts,
group_questions, follow_ups, and agent_runs.cancel_requested_at; widens the run_type check; drops
transcripts (speech-to-text removed; downgrade restores it). On Postgres, the new tables get SELECT-only
owner policies like the others.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 17:39:38.335491
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema_up() -> None:
    op.create_table('populations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('regions', JSON, nullable=False),
    sa.Column('groups', JSON, nullable=False),
    sa.Column('construction', JSON, nullable=False),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint('size >= 1', name=op.f('ck_populations_size')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_populations_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_populations')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_populations_id_project_id'))
    )
    op.create_index('ix_populations_project_id_created_at', 'populations', ['project_id', 'created_at'], unique=False)

    op.create_table('participants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('population_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.String(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('region_code', sa.String(), nullable=False),
    sa.Column('region', JSON, nullable=False),
    sa.Column('interests', JSON, nullable=False),
    sa.Column('traits', JSON, nullable=False),
    sa.Column('evidence_ids', JSON, nullable=False),
    sa.ForeignKeyConstraint(['population_id', 'project_id'], ['populations.id', 'populations.project_id'], name=op.f('fk_participants_population_id_populations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_participants')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_participants_id_project_id')),
    sa.UniqueConstraint('population_id', 'ordinal', name=op.f('uq_participants_population_id_ordinal'))
    )
    op.create_index('ix_participants_population_id_group_id', 'participants', ['population_id', 'group_id'], unique=False)
    op.create_index('ix_participants_population_id_region_code', 'participants', ['population_id', 'region_code'], unique=False)

    op.create_table('population_studies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('study_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('population_id', sa.Uuid(), nullable=True),
    sa.Column('content_version_id', sa.Uuid(), nullable=False),
    sa.Column('requested_participants', sa.Integer(), nullable=False),
    sa.Column('interview_depth', sa.String(), nullable=False),
    sa.Column('seed', sa.Integer(), nullable=False),
    sa.Column('checkpoint', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("interview_depth IN ('brief', 'standard', 'deep')", name=op.f('ck_population_studies_interview_depth')),
    sa.ForeignKeyConstraint(['content_version_id', 'campaign_id'], ['campaign_versions.id', 'campaign_versions.campaign_id'], name=op.f('fk_population_studies_content_version_id_campaign_versions')),
    sa.ForeignKeyConstraint(['id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_population_studies_id_agent_runs')),
    sa.ForeignKeyConstraint(['population_id', 'project_id'], ['populations.id', 'populations.project_id'], name=op.f('fk_population_studies_population_id_populations')),
    sa.ForeignKeyConstraint(['study_id', 'project_id'], ['studies.id', 'studies.project_id'], name=op.f('fk_population_studies_study_id_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_population_studies')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_population_studies_id_project_id'))
    )
    op.create_index('ix_population_studies_study_id_created_at', 'population_studies', ['study_id', 'created_at'], unique=False)

    op.create_table('group_questions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('population_study_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.String(), nullable=False),
    sa.Column('question', sa.String(), nullable=False),
    sa.Column('sample_size', sa.Integer(), nullable=False),
    sa.Column('stance', JSON, nullable=False),
    sa.Column('summary', sa.String(), nullable=False),
    sa.Column('sample_note', sa.String(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['population_study_id', 'project_id'], ['population_studies.id', 'population_studies.project_id'], name=op.f('fk_group_questions_population_study_id_population_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_group_questions')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_group_questions_id_project_id'))
    )
    op.create_index('ix_group_questions_population_study_id_group_id', 'group_questions', ['population_study_id', 'group_id'], unique=False)

    op.create_table('interviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('batch_index', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.String(), nullable=False),
    sa.Column('region_code', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('reaction', sa.String(), nullable=True),
    sa.Column('payload', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('completed', 'failed')", name=op.f('ck_interviews_status')),
    sa.ForeignKeyConstraint(['participant_id', 'project_id'], ['participants.id', 'participants.project_id'], name=op.f('fk_interviews_participant_id_participants')),
    sa.ForeignKeyConstraint(['run_id', 'project_id'], ['population_studies.id', 'population_studies.project_id'], name=op.f('fk_interviews_run_id_population_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interviews')),
    sa.UniqueConstraint('run_id', 'participant_id', name=op.f('uq_interviews_run_id_participant_id'))
    )
    op.create_index('ix_interviews_run_id_group_id', 'interviews', ['run_id', 'group_id'], unique=False)
    op.create_index('ix_interviews_run_id_reaction', 'interviews', ['run_id', 'reaction'], unique=False)
    op.create_index('ix_interviews_run_id_region_code', 'interviews', ['run_id', 'region_code'], unique=False)

    op.create_table('social_simulations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('population_study_id', sa.Uuid(), nullable=False),
    sa.Column('rounds_requested', sa.Integer(), nullable=False),
    sa.Column('active_share', sa.Double(), nullable=False),
    sa.Column('feed_size', sa.Integer(), nullable=False),
    sa.Column('seed', sa.Integer(), nullable=False),
    sa.Column('checkpoint', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint('rounds_requested BETWEEN 1 AND 5', name=op.f('ck_social_simulations_rounds_requested')),
    sa.ForeignKeyConstraint(['id', 'project_id'], ['agent_runs.id', 'agent_runs.project_id'], name=op.f('fk_social_simulations_id_agent_runs')),
    sa.ForeignKeyConstraint(['population_study_id', 'project_id'], ['population_studies.id', 'population_studies.project_id'], name=op.f('fk_social_simulations_population_study_id_population_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_social_simulations')),
    sa.UniqueConstraint('id', 'project_id', name=op.f('uq_social_simulations_id_project_id'))
    )
    op.create_index('ix_social_simulations_population_study_id_created_at', 'social_simulations', ['population_study_id', 'created_at'], unique=False)

    op.create_table('follow_ups',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('population_study_id', sa.Uuid(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.String(), nullable=False),
    sa.Column('group_question_id', sa.Uuid(), nullable=True),
    sa.Column('question', sa.String(), nullable=False),
    sa.Column('answer', sa.String(), nullable=False),
    sa.Column('stance', sa.String(), nullable=True),
    sa.Column('memory_refs', JSON, nullable=False),
    sa.Column('model_id', sa.String(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['group_question_id', 'project_id'], ['group_questions.id', 'group_questions.project_id'], name=op.f('fk_follow_ups_group_question_id_group_questions')),
    sa.ForeignKeyConstraint(['participant_id', 'project_id'], ['participants.id', 'participants.project_id'], name=op.f('fk_follow_ups_participant_id_participants')),
    sa.ForeignKeyConstraint(['population_study_id', 'project_id'], ['population_studies.id', 'population_studies.project_id'], name=op.f('fk_follow_ups_population_study_id_population_studies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_follow_ups'))
    )
    op.create_index('ix_follow_ups_population_study_id_participant_id', 'follow_ups', ['population_study_id', 'participant_id'], unique=False)

    op.create_table('social_posts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('simulation_id', sa.Uuid(), nullable=False),
    sa.Column('round_index', sa.Integer(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('parent_post_id', sa.Uuid(), nullable=True),
    sa.Column('text', sa.String(), nullable=True),
    sa.Column('stance', sa.String(), nullable=False),
    sa.Column('previous_stance', sa.String(), nullable=True),
    sa.Column('reason', sa.String(), nullable=True),
    sa.Column('seen_post_ids', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("action IN ('post', 'comment', 'share', 'ignore')", name=op.f('ck_social_posts_action')),
    sa.CheckConstraint('round_index BETWEEN 1 AND 5', name=op.f('ck_social_posts_round_index')),
    sa.ForeignKeyConstraint(['parent_post_id'], ['social_posts.id'], name=op.f('fk_social_posts_parent_post_id_social_posts')),
    sa.ForeignKeyConstraint(['participant_id', 'project_id'], ['participants.id', 'participants.project_id'], name=op.f('fk_social_posts_participant_id_participants')),
    sa.ForeignKeyConstraint(['simulation_id', 'project_id'], ['social_simulations.id', 'social_simulations.project_id'], name=op.f('fk_social_posts_simulation_id_social_simulations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_social_posts'))
    )
    op.create_index('ix_social_posts_simulation_id_group_id', 'social_posts', ['simulation_id', 'group_id'], unique=False)
    op.create_index('ix_social_posts_simulation_id_round_index', 'social_posts', ['simulation_id', 'round_index'], unique=False)
    op.execute("DROP TABLE IF EXISTS transcripts")  # speech-to-text was removed
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cancel_requested_at', UTCDateTime(), nullable=True))



def _schema_down() -> None:
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.drop_column('cancel_requested_at')

    op.create_table('transcripts',  # as migration 0003 created it (dialect-neutral types)
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
    op.drop_table('social_posts')
    op.drop_table('follow_ups')
    op.drop_table('social_simulations')
    op.drop_table('interviews')
    op.drop_table('group_questions')
    op.drop_table('population_studies')
    op.drop_table('participants')
    op.drop_table('populations')


V4_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison'"
)
V5_RUN_TYPES = V4_RUN_TYPES + ", 'population_study', 'social_simulation'"
NEW_TABLES = (
    "populations", "participants", "population_studies", "interviews", "social_simulations", "social_posts",
    "group_questions", "follow_ups",
)
OWNED_PROJECTS = "(SELECT id FROM projects WHERE owner_id = (SELECT auth.uid()))"
SUPABASE = (
    "IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace\n"
    "             WHERE n.nspname = 'auth' AND p.proname = 'uid')\n"
    "     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN\n"
)


def _run_types(values: str) -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_agent_runs_run_type"), type_="check")
        batch_op.create_check_constraint("run_type", f"run_type IN ({values})")


def _policies(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    creates = "\n".join(
        f"    EXECUTE $p$CREATE POLICY {table}_select_own ON {table} FOR SELECT TO authenticated "
        f"USING (project_id IN {OWNED_PROJECTS})$p$;"
        for table in tables
    )
    op.execute(f"DO $do$\nBEGIN\n  {SUPABASE}{creates}\n  END IF;\nEND\n$do$;")


def upgrade() -> None:
    _schema_up()
    _run_types(V5_RUN_TYPES)
    if op.get_context().dialect.name == "postgresql":
        _policies(NEW_TABLES)


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        for table in NEW_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_select_own ON {table}")
    op.execute("DELETE FROM agent_runs WHERE run_type IN ('population_study', 'social_simulation')")
    _run_types(V4_RUN_TYPES)
    _schema_down()  # drops the new tables and recreates transcripts
    if op.get_context().dialect.name == "postgresql":
        _policies(("transcripts",))
