"""Review-queue priority from explicit, configured rules. Every point awarded carries its reason."""

from datetime import timedelta

from app.models import Document, DocStatus, Finding, FindingStatus, Registration, utcnow


def compute(reg: Registration, docs: list[Document], findings: list[Finding], checklist: dict, rules: list[dict]) -> tuple[int, list[dict]]:
    open_f = [f for f in findings if f.status in FindingStatus.OPEN_STATES]
    facts = {
        "processing_failed": any(d.status == DocStatus.FAILED for d in docs),
        "critical_finding": any(f.severity == "critical" for f in open_f),
        "escalated_finding": any(f.status == FindingStatus.ESCALATED for f in open_f),
        "high_finding": any(f.severity == "high" for f in open_f),
        "expired_document": any((d.validity or {}).get("state") in ("expired", "too_old") for d in docs),
        "missing_mandatory": any(i["state"] in ("missing", "unclassified") and i.get("blocking", True) for i in checklist.get("documents", [])),
        "ready_for_decision": bool(checklist.get("ready_for_decision")),
    }
    score, reasons = 0, []
    for rule in rules:
        rid = rule["id"]
        hit = facts.get(rid, False)
        if rid == "waiting_over_days":
            hit = reg.created_at is not None and utcnow() - reg.created_at > timedelta(days=rule.get("days", 2))
        if hit:
            score += int(rule["points"])
            reasons.append({"rule": rid, "label": rule["label"], "points": int(rule["points"])})
    return score, reasons
