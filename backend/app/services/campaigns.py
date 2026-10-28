"""Campaigns and their immutable content versions (D-006)."""

from collections import defaultdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.campaigns import Campaign, CampaignCreate, CampaignPage, CampaignUpdate, ContentVersion
from app.services.common import apply_patch, get_owned, get_project, paginate, reject_null, require_writable, touch

FIELDS = {
    "name": "name",
    "objective": "objective",
    "target_markets": "target_markets",
    "evaluation_criteria": "evaluation_criteria",
}
REQUIRED = {"name", "target_markets", "evaluation_criteria"}
DEMO_CONTENT_LOCKED = (
    "Demo campaign content is fixed so that the demo fixtures stay truthful. Create a live project to edit copy."
)


def to_version(version: m.CampaignVersion) -> ContentVersion:
    return ContentVersion(
        id=version.id, campaign_id=version.campaign_id, version_number=version.version_number,
        content=version.content, created_at=version.created_at,  # type: ignore[arg-type]
    )


def to_campaign(campaign: m.Campaign, versions: list[m.CampaignVersion]) -> Campaign:
    ordered = sorted(versions, key=lambda v: v.version_number, reverse=True)
    return Campaign(
        id=campaign.id, project_id=campaign.project_id, name=campaign.name,
        campaign_type=campaign.campaign_type,  # type: ignore[arg-type]
        objective=campaign.objective, target_markets=campaign.target_markets,  # type: ignore[arg-type]
        evaluation_criteria=campaign.evaluation_criteria,  # type: ignore[arg-type]
        current_version=to_version(ordered[0]), versions=[to_version(v) for v in ordered],
        created_at=campaign.created_at, updated_at=campaign.updated_at,
    )


async def versions_of(s: AsyncSession, campaign_ids: list[UUID]) -> dict[UUID, list[m.CampaignVersion]]:
    rows = (await s.execute(select(m.CampaignVersion).where(m.CampaignVersion.campaign_id.in_(campaign_ids)))).scalars()
    grouped: dict[UUID, list[m.CampaignVersion]] = defaultdict(list)
    for row in rows:
        grouped[row.campaign_id].append(row)
    return grouped


async def current_version(s: AsyncSession, campaign_id: UUID) -> m.CampaignVersion:
    stmt = select(m.CampaignVersion).where(m.CampaignVersion.campaign_id == campaign_id)
    return (await s.execute(stmt.order_by(m.CampaignVersion.version_number.desc()).limit(1))).scalar_one()


async def create_campaign(user_id: UUID, project_id: UUID, body: CampaignCreate) -> Campaign:
    data = body.model_dump(mode="json")
    now = utcnow()
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        if project.mode == "demo":
            raise Conflict("Demo projects contain only the seeded campaign. Create a live project to research your own.")
        campaign = m.Campaign(
            id=uuid4(), project_id=project.id, name=data["name"], campaign_type=data["campaign_type"],
            objective=data["objective"], target_markets=data["target_markets"],
            evaluation_criteria=data["evaluation_criteria"], created_at=now, updated_at=now,
        )
        version = m.CampaignVersion(
            id=uuid4(), campaign_id=campaign.id, project_id=project.id, version_number=1,
            content=data["original_content"], created_at=now,
        )
        s.add(campaign)
        await s.flush()
        s.add(version)
        touch(project)
    return to_campaign(campaign, [version])


async def list_campaigns(user_id: UUID, project_id: UUID, limit: int, offset: int) -> CampaignPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.Campaign).where(m.Campaign.project_id == project_id)
        rows, total = await paginate(s, stmt.order_by(m.Campaign.created_at.desc(), m.Campaign.id), limit, offset)
        versions = await versions_of(s, [c.id for c in rows])
    return CampaignPage(items=[to_campaign(c, versions[c.id]) for c in rows], limit=limit, offset=offset, total=total)


async def get_campaign(user_id: UUID, campaign_id: UUID) -> Campaign:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        versions = await versions_of(s, [campaign.id])
    return to_campaign(campaign, versions[campaign.id])


async def update_campaign(user_id: UUID, campaign_id: UUID, body: CampaignUpdate) -> Campaign:
    changes = body.model_dump(mode="json", exclude_unset=True)
    now = utcnow()
    async with session() as s, s.begin():
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        if "original_content" in changes:
            content = changes["original_content"]
            if content is None:
                raise reject_null("original_content")
            latest = await current_version(s, campaign.id)
            if content != latest.content:  # unchanged copy is a no-op, not a new version
                if project.mode == "demo":
                    raise Conflict(DEMO_CONTENT_LOCKED)
                s.add(
                    m.CampaignVersion(
                        id=uuid4(), campaign_id=campaign.id, project_id=campaign.project_id,
                        version_number=latest.version_number + 1, content=content, created_at=now,
                    )
                )
        apply_patch(campaign, changes, FIELDS, REQUIRED)
        if changes:
            campaign.updated_at = now
            touch(project)
        await s.flush()
        versions = await versions_of(s, [campaign.id])
    return to_campaign(campaign, versions[campaign.id])
