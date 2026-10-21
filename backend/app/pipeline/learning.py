"""What the analysts' reviews teach the extraction. Learned from this database, kept in it, and never
sent anywhere: the AI model is not trained on these documents; what changes is how the system uses
the readings it already has.

Two lessons, per document type and field:
- a value the analysts corrected away is not offered again (a heading read as a value, the utility's
  own CEP). A value with digits needs two corrections, and a value an analyst ever kept is never dropped;
- where the rules and the AI disagreed, and the analysts' final value was the AI's reading more often
  than the rules' (at least twice), the AI's reading becomes the field value. The rules' reading stays
  in the disagreement point.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, ExtractedField, Finding

MIN_AI_WINS = 2
RULES_LABEL, AI_LABEL = "Regras (OCR)", "IA"


@dataclass
class Lessons:
    rejected: dict[str, set[str]] = field(default_factory=dict)  # field -> comparable values corrected away
    prefer_ai: set[str] = field(default_factory=set)
    ai_wins: dict[str, int] = field(default_factory=dict)
    rule_wins: dict[str, int] = field(default_factory=dict)


def key(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def lessons(db: Session, doc_type: str | None, normalize) -> Lessons:
    """`normalize(field, text)` turns a reading as printed into the stored form (dates, CPF...)."""
    if not doc_type:
        return Lessons()
    rows = db.execute(
        select(ExtractedField.document_id, ExtractedField.name, ExtractedField.status, ExtractedField.value, ExtractedField.previous_value)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(Document.doc_type == doc_type, ExtractedField.status.in_(("confirmed", "corrected")))
    ).all()
    final: dict[tuple, str] = {}
    kept: dict[str, set[str]] = defaultdict(set)
    away: dict[str, Counter] = defaultdict(Counter)
    for did, name, status, value, previous in rows:
        final[(did, name)] = key(value)
        kept[name].add(key(value))
        if status == "corrected" and previous and key(previous) != key(value):
            away[name][key(previous)] += 1
    rejected = {}
    for name, counts in away.items():
        values = {v for v, n in counts.items() if v and v not in kept[name] and (n >= 2 or not any(c.isdigit() for c in v))}
        if values:
            rejected[name] = values

    ai_wins, rule_wins = Counter(), Counter()
    disagreements = db.execute(
        select(Finding.document_id, Finding.field_name, Finding.evidence)
        .join(Document, Document.id == Finding.document_id)
        .where(Finding.code == "AI_RULE_DISAGREEMENT", Document.doc_type == doc_type)
    ).all()
    for did, name, ev in disagreements:
        settled = final.get((did, name))
        if not settled:
            continue
        read = {e.get("label"): e.get("value") for e in ev or []}
        if read.get(AI_LABEL) and key(normalize(name, read[AI_LABEL])) == settled:
            ai_wins[name] += 1
        elif read.get(RULES_LABEL) and key(normalize(name, read[RULES_LABEL])) == settled:
            rule_wins[name] += 1
    prefer = {n for n, w in ai_wins.items() if w >= MIN_AI_WINS and w > rule_wins[n]}
    return Lessons(rejected, prefer, dict(ai_wins), dict(rule_wins))


def drop_rejected(fields: dict, learned: Lessons) -> tuple[dict, list[str]]:
    dropped = [n for n, fv in fields.items() if fv.source != "ai" and key(fv.value) in learned.rejected.get(n, ())]
    return {n: fv for n, fv in fields.items() if n not in dropped}, dropped


def summary(db: Session, normalize) -> list[dict]:
    """Every lesson in force, for the supervisors' panel. Values themselves are not listed: they can be
    personal data."""
    types = db.execute(
        select(Document.doc_type).join(ExtractedField, ExtractedField.document_id == Document.id)
        .where(Document.doc_type.is_not(None), ExtractedField.status.in_(("confirmed", "corrected"))).distinct()
    ).scalars().all()
    out = []
    for t in sorted(types):
        learned = lessons(db, t, normalize)
        for name in sorted(set(learned.rejected) | learned.prefer_ai):
            out.append({"doc_type": t, "field": name, "rejected_values": len(learned.rejected.get(name, ())),
                        "prefer_ai": name in learned.prefer_ai, "ai_wins": learned.ai_wins.get(name, 0),
                        "rule_wins": learned.rule_wins.get(name, 0)})
    return out
