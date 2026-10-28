"""Ownership lookups, pagination, and small helpers shared by the services.

Ownership rule (contracts/README.md section 3): a resource the caller does not own is
indistinguishable from a missing one (404). A resource the caller owns but that does not
fit the request (another project or campaign, wrong run type, unfinished run) is 409.
"""

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.schemas.common import ErrorDetail

RowT = TypeVar("RowT")

ARCHIVED = "This project is archived and read-only."


def conflict(field: str, message: str) -> Conflict:
    return Conflict(message, details=[ErrorDetail(field=field, message=message)])


def not_found(what: str, field: str | None = None) -> NotFound:
    message = f"{what} was not found."
    return NotFound(message, details=[ErrorDetail(field=field, message=message)] if field else None)


async def get_project(s: AsyncSession, user_id: UUID, project_id: UUID, *, writable: bool = False) -> m.Project:
    project = await s.get(m.Project, project_id)
    if project is None or project.owner_id != user_id:
        raise not_found("Project")
    if writable and project.status == "archived":
        raise Conflict(ARCHIVED)
    return project


async def get_owned(
    s: AsyncSession, model: type[RowT], row_id: UUID, user_id: UUID, what: str, field: str | None = None
) -> tuple[RowT, m.Project]:
    """Load a project-scoped row and its project, or raise 404 when the caller does not own it."""
    stmt = (
        select(model, m.Project)
        .join(m.Project, m.Project.id == model.project_id)  # type: ignore[attr-defined]
        .where(model.id == row_id, m.Project.owner_id == user_id)  # type: ignore[attr-defined]
    )
    found = (await s.execute(stmt)).first()
    if found is None:
        raise not_found(what, field)
    return found[0], found[1]


def require_writable(project: m.Project) -> None:
    if project.status == "archived":
        raise Conflict(ARCHIVED)


async def paginate(s: AsyncSession, stmt: Select[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    """One page of rows (scalars for single-entity selects, tuples otherwise) and the total count.

    The total comes from `count(*) OVER ()` in the same query, which saves one database round trip.
    A separate count runs only when the page is empty past the first offset.
    """
    single = len(stmt.column_descriptions) == 1
    result = (await s.execute(stmt.add_columns(func.count().over()).limit(limit).offset(offset))).all()
    if result:
        return [row[0] if single else tuple(row[:-1]) for row in result], int(result[0][-1])
    total = 0 if offset == 0 else await s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return [], int(total or 0)


def touch(project: m.Project) -> None:
    project.last_activity_at = utcnow()


def reject_null(field: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message="May not be null.")])


def apply_patch(row: object, changes: dict[str, Any], columns: dict[str, str], required: set[str]) -> None:
    """Copy PATCH fields onto a row. Explicit null is rejected for required fields."""
    for field, value in changes.items():
        if field not in columns:
            continue
        if value is None and field in required:
            raise reject_null(field)
        setattr(row, columns[field], value)
