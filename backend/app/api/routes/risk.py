from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.adaptations import Adaptation
from app.schemas.risk import RiskFinding, RiskFindingUpdate, RiskScan, RiskScanCreate, RiskScanPage
from app.schemas.runs import RunAccepted
from app.services import insights

router = APIRouter(tags=["risk-radar"])


@router.post("/campaigns/{campaign_id}/risk-scans", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_risk_scan(campaign_id: UUID, body: RiskScanCreate, user: CurrentUser) -> RunAccepted:
    """Scan text and optional images (run_type risk_scan)."""
    return await insights.start_risk_scan(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/risk-scans", response_model=RiskScanPage)
async def list_risk_scans(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> RiskScanPage:
    return await insights.list_risk_scans(user.id, campaign_id, limit, offset)


@router.get("/risk-scans/{scan_id}", response_model=RiskScan)
async def get_risk_scan(scan_id: UUID, user: CurrentUser) -> RiskScan:
    return await insights.get_risk_scan(user.id, scan_id)


@router.patch("/risk-scans/{scan_id}/findings/{finding_id}", response_model=RiskFinding)
async def update_risk_finding(
    scan_id: UUID, finding_id: UUID, body: RiskFindingUpdate, user: CurrentUser
) -> RiskFinding:
    """Review a finding: dismiss, resolve, or reopen it, with an optional note."""
    return await insights.update_risk_finding(user.id, scan_id, finding_id, body)


@router.post(
    "/risk-scans/{scan_id}/findings/{finding_id}/apply", status_code=status.HTTP_201_CREATED, response_model=Adaptation
)
async def apply_risk_alternative(scan_id: UUID, finding_id: UUID, user: CurrentUser) -> Adaptation:
    """Apply the suggested alternative as a new user-edit adaptation; the finding becomes applied.

    409 when the finding has no alternative or the scanned source is custom text.
    """
    return await insights.apply_risk_alternative(user.id, scan_id, finding_id)
