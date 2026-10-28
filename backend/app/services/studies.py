"""Studies: rehearsal configurations for one campaign (D-005)."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.studies import Study, StudyCreate, StudyPage
from app.services.common import conflict, get_owned, get_project, paginate, touch


def to_study(study: m.Study, latest_rehearsal_run_id: UUID | None) -> Study:
    return Study(
        id=study.id, project_id=study.project_id, campaign_id=study.campaign_id, name=study.name,
        market=study.market, research_questions=study.research_questions,  # type: ignore[arg-type]
        dimensions=study.dimensions, segments=study.segments,  # type: ignore[arg-type]
        simulation_config=study.simulation_config,  # type: ignore[arg-type]
        latest_rehearsal_run_id=latest_rehearsal_run_id, created_at=study.created_at, updated_at=study.updated_at,
    )


async def latest_rehearsals(s: AsyncSession, study_ids: list[UUID]) -> dict[UUID, UUID]:
    stmt = (
        select(m.AgentRun.study_id, m.AgentRun.id)
        .where(m.AgentRun.study_id.in_(study_ids), m.AgentRun.run_type == "campaign_rehearsal")
        .order_by(m.AgentRun.created_at)
    )
    return {study_id: run_id for study_id, run_id in (await s.execute(stmt)).all()}  # newest wins


async def create_study(user_id: UUID, project_id: UUID, body: StudyCreate) -> Study:
    data = body.model_dump(mode="json")
    now = utcnow()
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        if project.mode == "demo":
            raise Conflict("Demo projects use the seeded study. Create a live project to design your own.")
        campaign, _ = await get_owned(s, m.Campaign, body.campaign_id, user_id, "Campaign", "campaign_id")
        if campaign.project_id != project.id:
            raise conflict("campaign_id", "The campaign belongs to another project.")
        study = m.Study(
            id=uuid4(), project_id=project.id, campaign_id=campaign.id, name=data["name"], market=data["market"],
            research_questions=data["research_questions"], dimensions=data["dimensions"], segments=data["segments"],
            simulation_config=data["simulation_config"], created_at=now, updated_at=now,
        )
        s.add(study)
        touch(project)
    return to_study(study, None)


async def list_studies(user_id: UUID, project_id: UUID, limit: int, offset: int, campaign_id: UUID | None) -> StudyPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.Study).where(m.Study.project_id == project_id)
        if campaign_id is not None:
            stmt = stmt.where(m.Study.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.Study.created_at.desc(), m.Study.id), limit, offset)
        latest = await latest_rehearsals(s, [study.id for study in rows])
    return StudyPage(items=[to_study(st, latest.get(st.id)) for st in rows], limit=limit, offset=offset, total=total)


async def get_study(user_id: UUID, study_id: UUID) -> Study:
    async with read_session() as s:
        study, _ = await get_owned(s, m.Study, study_id, user_id, "Study")
        latest = await latest_rehearsals(s, [study.id])
    return to_study(study, latest.get(study.id))
