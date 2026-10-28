"""Trend Watch: snapshots of finished discovery runs and a deterministic diff of two snapshots (no model call).

Two snapshots are two observations, not a trend line. Implications are labeled hypotheses.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.evidence import EntityRef
from app.schemas.trends import (
    Implication,
    ObservationChange,
    Snapshot,
    SnapshotCreate,
    SnapshotPage,
    TrendComparison,
    TrendComparisonCreate,
    TrendComparisonPage,
    TrendComparisonSummary,
)
from app.services.common import conflict, get_owned, get_project, paginate, touch
from app.services.runs import usable_run

MAX_IMPLICATIONS = 10
LIMITATIONS = [
    "Compares two stored discovery results. Differences can come from source data, fixtures, or matching changes, "
    "not only cultural change.",
    "Two snapshots are not a trend line; no statistical significance is implied.",
]


def to_snapshot(row: m.Snapshot) -> Snapshot:
    return Snapshot.model_validate(row, from_attributes=True)


async def create_snapshot(user_id: UUID, project_id: UUID, body: SnapshotCreate) -> Snapshot:
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        run = await usable_run(s, user_id, body.discovery_run_id, "market_discovery", project.id, "discovery_run_id")
        request, stored = run.inputs["request"], run.result or {}
        row = m.Snapshot(
            id=uuid4(), project_id=project.id, campaign_id=run.campaign_id, discovery_run_id=run.id, label=body.label,
            market=request["market"], product_category=request["product_category"],
            reference_terms=request["reference_terms"], captured_at=run.completed_at or run.created_at, mode=run.mode,
            reference_count=len(stored.get("references", [])), evidence_count=len(stored.get("evidence_ids", [])),
            created_at=utcnow(),
        )
        s.add(row)
        touch(project)
    return to_snapshot(row)


async def list_snapshots(user_id: UUID, project_id: UUID, limit: int, offset: int, campaign_id: UUID | None) -> SnapshotPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.Snapshot).where(m.Snapshot.project_id == project_id)
        if campaign_id is not None:
            stmt = stmt.where(m.Snapshot.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.Snapshot.captured_at.desc(), m.Snapshot.id), limit, offset)
    return SnapshotPage(items=[to_snapshot(r) for r in rows], limit=limit, offset=offset, total=total)


def _key(reference: dict[str, Any]) -> str:
    return reference.get("entity_id") or reference["query_term"]


def _numeric(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def diff_references(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[ObservationChange]:
    """Match references on entity id (else query term) and report what changed, in a stable order."""
    old, new = {_key(r): r for r in before}, {_key(r): r for r in after}
    changes: list[ObservationChange] = []
    for key in [*old, *(k for k in new if k not in old)]:
        a, b = old.get(key), new.get(key)
        ref = b or a
        assert ref is not None
        entity = EntityRef(entity_id=ref.get("entity_id"), name=ref["name"], entity_type=ref.get("entity_type")) if ref.get("name") else None
        common = {"reference_key": key, "entity": entity, "evidence_ids_before": a["evidence_ids"] if a else [],
                  "evidence_ids_after": b["evidence_ids"] if b else []}
        if a is None or b is None:
            changes.append(ObservationChange(kind="added" if a is None else "removed", attribute=None, before=None,
                                             after=None, delta=None, **common))
            continue
        found = False
        if a["match_status"] != b["match_status"]:
            changes.append(ObservationChange(kind="status_changed", attribute="match_status", before=a["match_status"],
                                             after=b["match_status"], delta=None, **common))
            found = True
        values_a = {attr["key"]: attr.get("value") for attr in a.get("attributes", [])}
        values_b = {attr["key"]: attr.get("value") for attr in b.get("attributes", [])}
        for attr in [*values_a, *(k for k in values_b if k not in values_a)]:
            va, vb = values_a.get(attr), values_b.get(attr)
            if va != vb:
                delta = round(vb - va, 6) if _numeric(va) and _numeric(vb) else None
                changes.append(ObservationChange(kind="attribute_changed", attribute=attr, before=_text(va),
                                                 after=_text(vb), delta=delta, **common))
                found = True
        if not found:
            changes.append(ObservationChange(kind="unchanged", attribute=None, before=None, after=None, delta=None, **common))
    return changes


def implications_for(changes: list[ObservationChange]) -> list[Implication]:
    out: list[Implication] = []
    for change in changes:
        label = change.entity.name if change.entity else change.reference_key
        text = {
            "added": f"'{label}' appears only in the newer snapshot; check that it is relevant before acting on it.",
            "removed": f"'{label}' no longer appears; this may reflect a data or matching change, not a cultural shift.",
            "status_changed": f"The match for '{label}' changed from {change.before} to {change.after}; review it "
                              "before relying on it.",
            "attribute_changed": f"'{change.attribute}' for '{label}' changed"
                                 + (f" by {change.delta} in the source's own units" if change.delta is not None else "")
                                 + "; one change does not establish a trend.",
        }.get(change.kind)
        if text:
            out.append(Implication(text=text, based_on=[change.reference_key]))
    return out[:MAX_IMPLICATIONS]


async def _workflows(s: AsyncSession, run: m.AgentRun) -> set[str]:
    ids = [UUID(str(i)) for i in (run.result or {}).get("evidence_ids", [])]
    if not ids:
        return set()
    stmt = select(m.EvidenceRecord.source_workflow).where(
        m.EvidenceRecord.project_id == run.project_id, m.EvidenceRecord.id.in_(ids)
    )
    return {w for w in (await s.execute(stmt)).scalars() if w}


async def create_trend_comparison(user_id: UUID, project_id: UUID, body: TrendComparisonCreate) -> TrendComparison:
    if body.base_snapshot_id == body.target_snapshot_id:
        raise conflict("target_snapshot_id", "Choose two different snapshots.")
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        snapshots, runs = [], []
        for field, snapshot_id in (("base_snapshot_id", body.base_snapshot_id), ("target_snapshot_id", body.target_snapshot_id)):
            row, _ = await get_owned(s, m.Snapshot, snapshot_id, user_id, "Snapshot", field)
            if row.project_id != project.id:
                raise conflict(field, "The snapshot belongs to another project.")
            snapshots.append(row)
            runs.append(await s.get(m.AgentRun, row.discovery_run_id))
        base, target = snapshots
        notes = []
        if base.market["country_code"] != target.market["country_code"]:
            notes.append(f"Markets differ ({base.market['display_name']} vs {target.market['display_name']}).")
        terms_a = {t.casefold() for t in base.reference_terms}
        terms_b = {t.casefold() for t in target.reference_terms}
        if terms_a != terms_b:
            notes.append(f"Reference terms differ: only in base {sorted(terms_a - terms_b)}; only in target {sorted(terms_b - terms_a)}.")
        workflows_a, workflows_b = await _workflows(s, runs[0]), await _workflows(s, runs[1])
        if workflows_a != workflows_b:
            notes.append(f"Qloo workflows differ: base used {sorted(workflows_a)}, target used {sorted(workflows_b)}.")
        if base.mode != target.mode:
            notes.append("One snapshot holds demo fixture data and the other live data.")
        changes = diff_references(
            (runs[0].result or {}).get("references", []), (runs[1].result or {}).get("references", [])
        )
        demo = "demo" in (base.mode, target.mode)
        comparison = TrendComparison(
            id=uuid4(), project_id=project.id, base_snapshot_id=base.id, target_snapshot_id=target.id,
            comparable=not notes, change_count=sum(c.kind != "unchanged" for c in changes), created_at=utcnow(),
            base=to_snapshot(base), target=to_snapshot(target), comparability_notes=notes, changes=changes,
            implications=implications_for(changes),
            limitations=LIMITATIONS + (["Demo fixture data: unchanged fixtures produce no changes."] if demo else []),
        )
        s.add(m.TrendComparison(
            id=comparison.id, project_id=project.id, base_snapshot_id=base.id, target_snapshot_id=target.id,
            comparable=comparison.comparable, change_count=comparison.change_count,
            content=comparison.model_dump(mode="json"), created_at=comparison.created_at,
        ))
        touch(project)
    return comparison


async def list_trend_comparisons(user_id: UUID, project_id: UUID, limit: int, offset: int) -> TrendComparisonPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.TrendComparison).where(m.TrendComparison.project_id == project_id)
        rows, total = await paginate(s, stmt.order_by(m.TrendComparison.created_at.desc(), m.TrendComparison.id), limit, offset)
    items = [TrendComparisonSummary.model_validate(r, from_attributes=True) for r in rows]
    return TrendComparisonPage(items=items, limit=limit, offset=offset, total=total)


async def get_trend_comparison(user_id: UUID, comparison_id: UUID) -> TrendComparison:
    async with read_session() as s:
        row, _ = await get_owned(s, m.TrendComparison, comparison_id, user_id, "Trend comparison")
    return TrendComparison.model_validate(row.content)
