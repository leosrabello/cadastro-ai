from app.models import DocStatus, Document, Finding, FindingStatus
from app.pipeline.findings import FindingDraft, evidence

BLOCKING_SEVERITIES = {"high", "critical"}


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


def build(profile: dict, docs: list[Document], open_findings: list[Finding], type_labels: dict) -> tuple[dict, list[FindingDraft], bool]:
    """Checklist of outstanding requirements, completeness findings, and whether a decision can be made."""
    active = [d for d in docs if d.status != DocStatus.PURGED]
    items = []
    drafts: list[FindingDraft] = []

    for req in profile.get("required", []):
        candidates = [d for d in active if d.doc_type in req["any_of"]]
        states = [(_doc_state(d), d) for d in candidates]
        ok = [d for s, d in states if s == "ok"]
        if ok:
            state, doc = "ok", ok[0]
        elif states:
            order = ["needs_review", "processing", "expired", "too_old", "invalid", "failed"]
            state, doc = sorted(states, key=lambda sd: order.index(sd[0]) if sd[0] in order else 99)[0]
        else:
            unclassified = [d for d in active if d.doc_type is None and d.status == DocStatus.PROCESSED]
            state, doc = ("unclassified" if unclassified else "missing"), None
        items.append({
            "id": req["id"],
            "label": req["label"],
            "accepted_types": [type_labels.get(t, t) for t in req["any_of"]],
            "state": state,
            "document_id": str(doc.id) if doc else None,
            "document_name": doc.original_filename if doc else None,
        })
        if state in ("missing", "unclassified"):
            drafts.append(FindingDraft(
                code="REQUIRED_DOCUMENT_MISSING", category="completeness", severity="medium", key=req["id"],
                title=f"Falta: {req['label']}",
                explanation=f"O perfil exige {req['label'].lower()} ({', '.join(type_labels.get(t, t) for t in req['any_of'])})."
                + (" Há documento recebido sem tipo identificado; classifique-o manualmente se for este." if state == "unclassified" else ""),
                recommended_action="Solicite o documento ao cliente ou classifique um documento já recebido.",
                rule_id=f"completeness.{req['id']}",
            ))

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
                            "value": found[1].value if found else None,
                            "document_id": str(found[0].id) if found else None})
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
    blocking = [f for f in review if f.severity in BLOCKING_SEVERITIES]
    docs_ok = all(i["state"] == "ok" for i in items)
    fields_ok = all(i["state"] == "ok" for i in field_items)
    processing = any(d.status in (DocStatus.QUEUED, DocStatus.PROCESSING) for d in active)
    ready = docs_ok and fields_ok and not blocking and not processing

    checklist = {
        "documents": items,
        "fields": field_items,
        "open_findings": len(review),
        "blocking_findings": len(blocking),
        "processing": processing,
        "ready_for_decision": ready,
    }
    return checklist, drafts, ready
