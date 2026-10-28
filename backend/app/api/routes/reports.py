from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.reports import Report, ReportCreate, ReportPage
from app.services import reports

router = APIRouter(tags=["proof"])


@router.post("/projects/{project_id}/reports", status_code=status.HTTP_201_CREATED, response_model=Report)
async def create_report(project_id: UUID, body: ReportCreate, user: CurrentUser) -> Report:
    """Assemble and persist a report snapshot from stored results (deterministic, synchronous)."""
    return await reports.create_report(user.id, project_id, body)


@router.get("/projects/{project_id}/reports", response_model=ReportPage)
async def list_reports(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, campaign_id: UUID | None = None
) -> ReportPage:
    return await reports.list_reports(user.id, project_id, limit, offset, campaign_id)


@router.get("/reports/{report_id}", response_model=Report)
async def get_report(report_id: UUID, user: CurrentUser) -> Report:
    return await reports.get_report(user.id, report_id)


@router.get(
    "/reports/{report_id}/export",
    response_class=Response,
    responses={
        200: {
            "description": "Report download (Content-Disposition: attachment).",
            "content": {
                "text/markdown": {"schema": {"type": "string"}},
                "application/json": {"schema": {"$ref": "#/components/schemas/Report"}},
            },
        }
    },
)
async def export_report(
    report_id: UUID,
    user: CurrentUser,
    fmt: Annotated[Literal["markdown", "json"], Query(alias="format")] = "markdown",
) -> Response:
    """Export preserves synthetic-data disclosures, evidence labels, and limitations."""
    content, media_type, filename = reports.export(await reports.get_report(user.id, report_id), fmt)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
