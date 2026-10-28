from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.evidence import EvidencePage, EvidenceRecord, EvidenceType
from app.services import results

router = APIRouter(tags=["proof"])


@router.get("/projects/{project_id}/evidence", response_model=EvidencePage)
async def list_evidence(
    project_id: UUID,
    user: CurrentUser,
    limit: Limit = 20,
    offset: Offset = 0,
    run_id: UUID | None = None,
    evidence_type: EvidenceType | None = None,
) -> EvidencePage:
    return await results.list_evidence(user.id, project_id, limit, offset, run_id, evidence_type)


@router.get("/evidence/{evidence_id}", response_model=EvidenceRecord)
async def get_evidence(evidence_id: UUID, user: CurrentUser) -> EvidenceRecord:
    return await results.get_evidence(user.id, evidence_id)
