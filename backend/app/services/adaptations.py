"""User edits of adaptations (POST /adaptations/{id}/revisions): a new adaptation, no model call.

Only the deterministic constraint checks (contracts/README.md section 8) are rerun.
"""

from uuid import UUID, uuid4

from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.schemas.adaptations import Adaptation, AdaptationChecks, AdaptationRevisionCreate, ContentChange
from app.schemas.campaigns import CampaignContent
from app.schemas.common import RiskFlag
from app.services.common import get_owned, require_writable, touch
from app.services.results import to_adaptations
from app.services.runs import brand_of, merge_terms

USER_EDIT_LIMITATION = (
    "User edit: written by a person, not reviewed by a model or a native speaker. Only the deterministic "
    "protected- and prohibited-term checks were rerun, and no change is linked to evidence."
)
CONTENT_FIELDS = ("headline", "body", "call_to_action")


def revision_changes(parent: m.Adaptation, revised: CampaignContent, note: str | None) -> list[dict]:
    """One user_edit entry per field the person changed, from the parent's text to the new text.

    The model's earlier changes stay on the parent adaptation (parent_adaptation_id).
    """
    before = CampaignContent.model_validate(parent.content)
    reason = "Edited by a person in this revision." + (f" Note: {note}" if note else "")
    return [
        ContentChange(field=field, original=getattr(before, field), adapted=getattr(revised, field), reason=reason,
                      reasoning_type="user_edit", evidence_ids=[]).model_dump(mode="json")
        for field in CONTENT_FIELDS
        if getattr(revised, field) != getattr(before, field)
    ]


def _text(content: CampaignContent) -> str:
    return " ".join(part for part in (content.headline, content.body, content.call_to_action) if part).casefold()


def constraint_checks(
    source: CampaignContent, adapted: CampaignContent, protected_terms: list[str], prohibited_terms: list[str]
) -> AdaptationChecks:
    """Case-insensitive term checks. A protected term present in the source must survive in the adaptation."""
    source_text, adapted_text = _text(source), _text(adapted)
    missing = [t for t in protected_terms if t.casefold() in source_text and t.casefold() not in adapted_text]
    return AdaptationChecks(
        protected_terms_preserved=not missing,
        missing_protected_terms=missing,
        prohibited_terms_found=[t for t in prohibited_terms if t.casefold() in adapted_text],
        brand_voice_reviewed=False,
        cultural_risk_reviewed=False,
    )


def deterministic_warnings(checks: AdaptationChecks) -> list[RiskFlag]:
    return [
        RiskFlag(severity="high", category="constraint_violation", source="deterministic_check",
                 description=f"Protected term '{term}' from the source is missing.")
        for term in checks.missing_protected_terms
    ] + [
        RiskFlag(severity="high", category="constraint_violation", source="deterministic_check",
                 description=f"Prohibited term '{term}' is present.")
        for term in checks.prohibited_terms_found
    ]


async def create_revision(user_id: UUID, adaptation_id: UUID, body: AdaptationRevisionCreate) -> Adaptation:
    async with session() as s, s.begin():
        parent, project = await get_owned(s, m.Adaptation, adaptation_id, user_id, "Adaptation")
        require_writable(project)
        version = await s.get(m.CampaignVersion, parent.source_content_version_id)
        assert version is not None
        source = CampaignContent.model_validate(version.content)
        brand = await brand_of(s, project.id)
        protected = merge_terms(brand.protected_terms, parent.protected_terms)
        checks = constraint_checks(source, body.content, protected, brand.prohibited_terms)
        changes = revision_changes(parent, body.content, body.note)
        warnings = deterministic_warnings(checks)
        row = m.Adaptation(
            id=uuid4(), project_id=project.id, campaign_id=parent.campaign_id, study_id=parent.study_id, run_id=None,
            source_content_version_id=parent.source_content_version_id, parent_adaptation_id=parent.id, position=0,
            origin="user_edit", mode=project.mode, market=parent.market, label=f"{parent.label} (edited)",
            strategy=body.note or f"User edit of '{parent.label}'.", content=body.content.model_dump(mode="json"),
            changes=changes, checks=checks.model_dump(mode="json"), warnings=[w.model_dump(mode="json") for w in warnings],
            limitations=[USER_EDIT_LIMITATION],
            context={**parent.context, "grounded": False, "rehearsal_informed": False},
            evidence_ids=[], protected_terms=protected, created_at=utcnow(),
        )
        s.add(row)
        touch(project)
        await s.flush()
        return (await to_adaptations(s, [row]))[0]
