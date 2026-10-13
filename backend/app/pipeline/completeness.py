"""The checklist of a registration, from its requirement profile.

A requirement is satisfied by one of its options (each option is a set of document types that
must all be present and in order: a Limitada's consolidated contract, or an S/A's bylaws plus the
board election minutes). Requirements may refer to a fiscal year relative to the current one
(year_offset), may belong to a stage (análise before the credit committee, formalização after),
and may be optional ("se aplicável"). Required information (bank details, a contact) comes from
the registration's reference fields, not from documents.
"""

from datetime import date

from app.models import DocStatus, Document, Finding, FindingStatus
from app.pipeline.findings import FindingDraft, evidence

BLOCKING_SEVERITIES = {"high", "critical"}
STATE_ORDER = ["ok", "needs_review", "processing", "expired", "too_old", "invalid", "failed", "unclassified", "missing"]


def _doc_state(doc: Document) -> str:
    if doc.status in (DocStatus.QUEUED, DocStatus.PROCESSING):
        return "processing"
    if doc.status == DocStatus.FAILED:
        return "failed"
    v = (doc.validity or {}).get("state")
    if v in ("expired", "too_old", "invalid"):
        return v
    if v in ("unknown", "contradictory"):
        return "needs_review"
    return "ok"


def _field(doc: Document, name: str) -> str | None:
    return next((f.value for f in doc.fields if f.name == name and f.value), None)


def _best(states: list[tuple[str, Document]]) -> tuple[str, Document | None]:
    if not states:
        return "missing", None
    return sorted(states, key=lambda sd: STATE_ORDER.index(sd[0]) if sd[0] in STATE_ORDER else 99)[0]


def _evaluate(req: dict, active: list[Document], year: int | None) -> tuple[str, list[Document], str | None]:
    """State of one requirement, the documents that count for it, and a note."""
    options = req.get("options") or [[t] for t in req.get("any_of", [])]
    best_state, best_docs, note = "missing", [], None
    for option in options:
        per_type = []
        for t in option:
            cands = [d for d in active if d.doc_type == t]
            if year is not None:
                with_year = [d for d in cands if _field(d, "exercicio") == str(year)]
                unknown = [d for d in cands if _field(d, "exercicio") is None and d.status == DocStatus.PROCESSED]
                other = sorted({_field(d, "exercicio") for d in cands if _field(d, "exercicio") not in (None, str(year))})
                if with_year:
                    cands = with_year
                elif unknown:
                    per_type.append(("needs_review", unknown, "ano do documento não identificado"))
                    continue
                else:
                    per_type.append(("missing", [], f"recebido de outro ano: {', '.join(other)}" if other else None))
                    continue
            if not cands:
                per_type.append(("missing", [], None))
                continue
            state, doc = _best([(_doc_state(d), d) for d in cands])
            per_type.append((state, [d for d in cands if _doc_state(d) == "ok"] or [doc], None))
        worst = max(per_type, key=lambda x: STATE_ORDER.index(x[0]) if x[0] in STATE_ORDER else 99)
        if STATE_ORDER.index(worst[0]) < STATE_ORDER.index(best_state) or (worst[0] == best_state and not best_docs):
            best_state = worst[0]
            best_docs = [d for _s, ds, _n in per_type for d in ds]
            note = next((n for _s, _d, n in per_type if n), None)
    if best_state == "missing" and any(d.doc_type is None and d.status == DocStatus.PROCESSED for d in active):
        best_state = "unclassified"
    return best_state, best_docs, note


def current_stage(profile: dict, decided_approved: bool) -> str | None:
    stages = profile.get("stages") or []
    if not stages:
        return None
    if decided_approved and len(stages) > 1:
        return stages[1]["id"]
    return stages[0]["id"]


def build(profile: dict, docs: list[Document], open_findings: list, type_labels: dict,
          reference_fields: dict | None = None, today: date | None = None, approved: bool = False) -> tuple[dict, list[FindingDraft], bool]:
    """Checklist, completeness findings for the stage in progress, and whether the decision can be made."""
    today = today or date.today()
    active = [d for d in docs if d.status != DocStatus.PURGED]
    stages = profile.get("stages") or []
    stage_now = current_stage(profile, approved)
    decision_stages = {s["id"] for s in stages if s.get("blocks_decision")} or {None}
    items, drafts = [], []

    for req in profile.get("required", []):
        stage = req.get("stage")
        year = today.year + req["year_offset"] if "year_offset" in req else None
        label = req["label"].replace("{ano}", str(year)) if year else req["label"]
        state, used, note = _evaluate(req, active, year)
        mandatory = req.get("required", True)
        blocking = mandatory and (stage == stage_now or stage is None)
        if not mandatory and state == "missing":
            state = "optional"
        options = req.get("options") or [[t] for t in req.get("any_of", [])]
        items.append({
            "id": req["id"],
            "label": label,
            "group": req.get("group"),
            "stage": stage,
            "note": req.get("note"),
            "year": year,
            "required": mandatory,
            "blocking": blocking,
            "per_partner": bool(req.get("per_partner")),
            "accepted_types": [" + ".join(type_labels.get(t, t) for t in opt) for opt in options],
            "state": state,
            "state_note": note,
            "received": len(used),
            "document_id": str(used[0].id) if used else None,
            "document_name": used[0].original_filename if used else None,
            "documents": [{"id": str(d.id), "name": d.original_filename} for d in used[:6]],
        })
        if blocking and state in ("missing", "unclassified"):
            drafts.append(FindingDraft(
                code="REQUIRED_DOCUMENT_MISSING", category="completeness", severity="medium", key=req["id"],
                title=f"Falta: {label}",
                explanation=f"O perfil exige {label[0].lower() + label[1:]}"
                + (f" ({req['note']})" if req.get("note") else "") + "."
                + (f" Observação: {note}." if note else "")
                + (" Há documento recebido sem tipo identificado; classifique-o manualmente se for este." if state == "unclassified" else ""),
                recommended_action="Solicite o documento ao cliente ou classifique um documento já recebido.",
                rule_id=f"completeness.{req['id']}",
            ))

    info_items = []
    refs = reference_fields or {}
    for info in profile.get("required_info", []):
        value = (refs.get(info["id"]) or "").strip()
        stage = info.get("stage")
        info_items.append({
            "id": info["id"], "label": info["label"], "hint": info.get("hint"), "group": info.get("group"), "stage": stage,
            "state": "ok" if value else "missing", "value": value or None,
            "blocking": stage == stage_now or stage is None,
        })

    field_items = []
    for rf in profile.get("required_fields", []):
        found = None
        for d in active:
            if d.doc_type in rf["in_any_of"]:
                f = next((x for x in d.fields if x.name == rf["field"] and x.value and x.valid is not False), None)
                if f:
                    found = (d, f)
                    break
        field_items.append({"field": rf["field"], "label": rf["label"], "state": "ok" if found else "missing",
                            "value": found[1].value if found else None, "document_id": str(found[0].id) if found else None})
        if not found and any(d.doc_type in rf["in_any_of"] and d.status == DocStatus.PROCESSED for d in active):
            drafts.append(FindingDraft(
                code="REQUIRED_FIELD_MISSING", category="completeness", severity="medium", key=rf["field"], field_name=rf["field"],
                title=f"Campo não lido: {rf['label']}",
                explanation=f"{rf['label']} não foi lido com segurança em nenhum documento aceito.",
                recommended_action="Preencha o campo a partir do original ou peça uma cópia legível.",
                evidence=[evidence("Documentos aceitos", ", ".join(type_labels.get(t, t) for t in rf["in_any_of"]))],
                rule_id=f"completeness.field.{rf['field']}",
            ))

    review = [f for f in open_findings if f.status in FindingStatus.OPEN_STATES]
    blocking_findings = [f for f in review if f.severity in BLOCKING_SEVERITIES]
    processing = any(d.status in (DocStatus.QUEUED, DocStatus.PROCESSING) for d in active)
    decision_items = [i for i in items if i["required"] and (i["stage"] in decision_stages)]
    docs_ok = all(i["state"] == "ok" for i in decision_items)
    info_ok = all(i["state"] == "ok" for i in info_items if i["stage"] in decision_stages)
    fields_ok = all(i["state"] == "ok" for i in field_items)
    ready = docs_ok and info_ok and fields_ok and not blocking_findings and not processing

    stage_summary = []
    for s in stages:
        its = [i for i in items if i["stage"] == s["id"] and i["required"]] + [i for i in info_items if i["stage"] == s["id"]]
        stage_summary.append({"id": s["id"], "label": s["label"], "note": s.get("note"), "current": s["id"] == stage_now,
                              "done": sum(1 for i in its if i["state"] == "ok"), "total": len(its)})

    checklist = {
        "documents": items,
        "info": info_items,
        "fields": field_items,
        "stages": stage_summary,
        "stage": stage_now,
        "open_findings": len(review),
        "blocking_findings": len(blocking_findings),
        "processing": processing,
        "ready_for_decision": ready,
    }
    return checklist, drafts, ready
