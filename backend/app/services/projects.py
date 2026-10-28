"""Projects and their brand kit (one per project in the MVP), including the seeded demo project."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.errors import Conflict
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.campaigns import DEFAULT_EVALUATION_CRITERIA
from app.schemas.projects import Brand, BrandUpdate, Project, ProjectCreate, ProjectPage, ProjectSummary, ProjectUpdate
from app.services.common import apply_patch, get_project, paginate

# Seed for POST /projects/demo. Mirrors contracts/fixtures/Project.json and Campaign.json; the
# demo fixtures are written for exactly this brand, campaign copy, and market.
DEMO_MARKET = {"country_code": "JP", "display_name": "Japan"}
DEMO_PROJECT = {
    "name": "Japan Market Launch",
    "description": "Evaluate the autumn launch campaign for Japan.",
    "objective": "Decide whether the autumn campaign needs adaptation before a Japan launch.",
}
DEMO_BRAND = {
    "name": "Northstar",
    "description": "A premium outdoor lifestyle brand",
    "voice": ["confident", "minimal", "adventurous"],
    "target_audience": "Urban professionals who hike on weekends",
    "preferred_terms": ["trail", "craft"],
    "prohibited_terms": ["cheap"],
    "protected_terms": ["Northstar"],
    "positioning": "Premium outdoor gear for people who return to the trail every weekend.",
    "communication_style": "Short, confident sentences. No hype and no superlatives.",
    "audience_preferences": "Craft and minimal design over technical jargon.",
    "approved_examples": [{"text": "Built for the journeys that change you.", "note": "Approved tagline"}],
    "constraints": ["Never promise performance we have not tested."],
}
DEMO_CAMPAIGN = {
    "name": "Autumn Launch Campaign",
    "campaign_type": "advertisement",
    "objective": "Evaluate cultural relevance and clarity",
}
DEMO_CONTENT = {
    "headline": "Find your next great escape",
    "body": "Built for the journeys that change you.",
    "call_to_action": "Explore the collection",
    "reference_terms": ["great escape"],
}
DEMO_STUDY = {  # contracts/fixtures/Study.json
    "name": "Japan Launch Rehearsal",
    "research_questions": [
        "Is the main message clear?",
        "What interpretations could the headline trigger?",
        "Which references might be confusing or inappropriate?",
    ],
    "dimensions": ["clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"],
    "segments": [
        {"label": "Weekend hikers", "description": "Metropolitan professionals who hike one or two weekends a month."},
        {"label": "Design-led urban buyers", "description": "Style-conscious city residents who value minimal design."},
        {"label": "Experienced mountaineers", "description": "Technical climbers who judge gear on performance claims."},
    ],
    "simulation_config": {"response_count": 6, "segment_count": 3, "random_seed": 42},
}

PROJECT_FIELDS = {"name": "name", "description": "description", "objective": "objective", "target_markets": "target_markets"}
BRAND_FIELDS = {
    "brand_name": "name",
    "brand_description": "description",
    "brand_voice": "voice",
    "target_audience": "target_audience",
    "preferred_terms": "preferred_terms",
    "prohibited_terms": "prohibited_terms",
    "protected_terms": "protected_terms",
}
REQUIRED_FIELDS = {"name", "target_markets", "brand_name", "brand_voice", "preferred_terms", "prohibited_terms", "protected_terms"}


BRAND_MEMORY_FIELDS = (
    "name", "description", "positioning", "voice", "communication_style", "target_audience", "audience_preferences",
    "preferred_terms", "prohibited_terms", "protected_terms", "approved_examples", "constraints",
)
DEMO_BRAND_LOCKED = (
    "The demo brand kit is fixed so that the demo fixtures stay truthful. Create a live project to use your own brand."
)


def to_brand(brand: m.BrandKit) -> Brand:
    return Brand.model_validate({"id": brand.id, "updated_at": brand.updated_at} | {
        field: getattr(brand, field) for field in BRAND_MEMORY_FIELDS})


async def get_brand(user_id: UUID, project_id: UUID) -> Brand:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        return to_brand(await _brand(s, project_id))


async def replace_brand(user_id: UUID, project_id: UUID, body: BrandUpdate) -> Brand:
    """Brand Memory is written only here, by people (D-036); full replacement."""
    data = body.model_dump(mode="json")
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        if project.mode == "demo":
            raise Conflict(DEMO_BRAND_LOCKED)
        brand = await _brand(s, project_id)
        for field in BRAND_MEMORY_FIELDS:
            setattr(brand, field, data[field])
        brand.updated_at = project.updated_at = project.last_activity_at = utcnow()
    from app.services.runs import index_project  # approved examples are searchable; best-effort

    await index_project(project_id=project_id)
    return to_brand(brand)


def to_project(project: m.Project, brand: m.BrandKit) -> Project:
    return Project(
        id=project.id,
        name=project.name,
        description=project.description,
        objective=project.objective,
        mode=project.mode,  # type: ignore[arg-type]
        status=project.status,  # type: ignore[arg-type]
        brand=to_brand(brand),
        target_markets=project.target_markets,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


async def _brand(s: Any, project_id: UUID) -> m.BrandKit:
    return (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one()


async def create_project(user_id: UUID, body: ProjectCreate) -> Project:
    data = body.model_dump(mode="json")
    now = utcnow()
    project = m.Project(
        id=uuid4(), owner_id=user_id, mode="live", status="active", name=data["name"], description=data["description"],
        objective=data["objective"], target_markets=data["target_markets"], last_activity_at=now, created_at=now,
        updated_at=now,
    )
    brand = m.BrandKit(
        id=uuid4(), project_id=project.id, name=data["brand_name"], description=data["brand_description"],
        voice=data["brand_voice"], target_audience=data["target_audience"], preferred_terms=data["preferred_terms"],
        prohibited_terms=data["prohibited_terms"], protected_terms=data["protected_terms"], created_at=now,
        updated_at=now,
    )
    async with session() as s, s.begin():
        s.add(project)
        await s.flush()
        s.add(brand)
    return to_project(project, brand)


async def create_demo_project(user_id: UUID) -> Project:
    now = utcnow()
    project = m.Project(
        id=uuid4(), owner_id=user_id, mode="demo", status="active", target_markets=[DEMO_MARKET], last_activity_at=now,
        created_at=now, updated_at=now, **DEMO_PROJECT,
    )
    brand = m.BrandKit(id=uuid4(), project_id=project.id, created_at=now, updated_at=now, **DEMO_BRAND)
    campaign = m.Campaign(
        id=uuid4(), project_id=project.id, target_markets=[DEMO_MARKET],
        evaluation_criteria=DEFAULT_EVALUATION_CRITERIA.model_dump(), created_at=now, updated_at=now, **DEMO_CAMPAIGN,
    )
    version = m.CampaignVersion(
        id=uuid4(), campaign_id=campaign.id, project_id=project.id, version_number=1, content=DEMO_CONTENT,
        created_at=now,
    )
    study = m.Study(
        id=uuid4(), project_id=project.id, campaign_id=campaign.id, market=DEMO_MARKET, created_at=now, updated_at=now,
        **DEMO_STUDY,
    )
    async with session() as s, s.begin():
        s.add(project)
        await s.flush()
        s.add_all([brand, campaign])
        await s.flush()
        s.add_all([version, study])
    return to_project(project, brand)


async def list_projects(user_id: UUID, limit: int, offset: int, include_archived: bool) -> ProjectPage:
    stmt = select(m.Project, m.BrandKit.name).join(m.BrandKit, m.BrandKit.project_id == m.Project.id)
    stmt = stmt.where(m.Project.owner_id == user_id)
    if not include_archived:
        stmt = stmt.where(m.Project.status == "active")
    stmt = stmt.order_by(m.Project.last_activity_at.desc(), m.Project.created_at.desc(), m.Project.id)
    async with read_session() as s:
        rows, total = await paginate(s, stmt, limit, offset)
    items = [
        ProjectSummary(
            id=p.id, name=p.name, description=p.description, mode=p.mode, status=p.status,  # type: ignore[arg-type]
            brand_name=brand_name, target_markets=p.target_markets, last_activity_at=p.last_activity_at,
            created_at=p.created_at, updated_at=p.updated_at,
        )
        for p, brand_name in rows
    ]
    return ProjectPage(items=items, limit=limit, offset=offset, total=total)


async def get_project_detail(user_id: UUID, project_id: UUID) -> Project:
    async with read_session() as s:
        project = await get_project(s, user_id, project_id)
        return to_project(project, await _brand(s, project_id))


async def update_project(user_id: UUID, project_id: UUID, body: ProjectUpdate) -> Project:
    changes = body.model_dump(mode="json", exclude_unset=True)
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        brand = await _brand(s, project_id)
        brand_changes = {k: v for k, v in changes.items() if k in BRAND_FIELDS}
        if project.mode == "demo" and brand_changes:
            raise Conflict(DEMO_BRAND_LOCKED)
        now = utcnow()
        project_changes = {k: v for k, v in changes.items() if k in PROJECT_FIELDS}
        if project_changes:
            apply_patch(project, project_changes, PROJECT_FIELDS, REQUIRED_FIELDS)
            project.updated_at = now
        if brand_changes:
            apply_patch(brand, brand_changes, BRAND_FIELDS, REQUIRED_FIELDS)
            brand.updated_at = now
            project.updated_at = now
        if changes:
            project.last_activity_at = now
    return to_project(project, brand)


async def archive_project(user_id: UUID, project_id: UUID) -> None:
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id)
        if project.status != "archived":
            project.status = "archived"
            project.updated_at = utcnow()
