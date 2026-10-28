from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.schemas.common import CountryCode
from app.schemas.evidence import EvidenceType
from app.schemas.graph import EvidenceGraph
from app.services import graph

router = APIRouter(tags=["evidence-graph"])


@router.get("/projects/{project_id}/evidence-graph", response_model=EvidenceGraph)
async def get_evidence_graph(
    project_id: UUID,
    user: CurrentUser,
    campaign_id: UUID | None = None,
    region: CountryCode | None = None,
    evidence_type: EvidenceType | None = None,
    population_study_id: UUID | None = None,
    limit: Annotated[int, Query(ge=10, le=500, description="Maximum nodes; truncated=true when exceeded.")] = 200,
) -> EvidenceGraph:
    return await graph.evidence_graph(
        user.id, project_id, campaign_id, limit, region=region, evidence_type=evidence_type,
        population_study_id=population_study_id,
    )
