"""Economic groups (grupos econômicos): companies and people under common control. The analyst sets
the group; the system suggests members from what the documents show: another company with the same
CNPJ root (head office and branches), or a partner or administrator in common."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.api.registrations import get_registration
from app.api.serializers import iso, registration_row
from app.db import get_db
from app.deps import ANY_ROLE, OPERATORS, Principal
from app.errors import ApiError
from app.models import Document, EconomicGroup, ExtractedField, RegStatus, Registration, utcnow
from app.portfolio import clean_name, name_key

router = APIRouter(prefix="/api", tags=["groups"])

PEOPLE_FIELDS = ("socios", "administradores", "responsaveis_assinatura", "nome")


class GroupIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    registration_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class GroupPatch(BaseModel):
    name: str = Field(min_length=2, max_length=200)


def group_out(g: EconomicGroup, members: int) -> dict:
    return {"id": str(g.id), "name": g.name, "members": members, "created_at": iso(g.created_at)}


@router.get("/groups")
def list_groups(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Registration.group_id, func.count()).where(Registration.group_id.is_not(None)).group_by(Registration.group_id)).all())
    groups = db.execute(select(EconomicGroup).order_by(EconomicGroup.name)).scalars().all()
    return {"items": [group_out(g, counts.get(g.id, 0)) for g in groups]}


@router.post("/groups", status_code=201)
def create_group(body: GroupIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    name = clean_name(body.name).upper()
    if db.execute(select(EconomicGroup).where(EconomicGroup.name_key == name_key(name))).scalar_one_or_none():
        raise ApiError(409, "duplicate", "Já existe um grupo com esse nome.")
    g = EconomicGroup(name=name, name_key=name_key(name), created_at=utcnow())
    db.add(g)
    db.flush()
    for rid in body.registration_ids:
        get_registration(db, rid).group = g
    audit.record(db, "group.created", actor=p.user, entity_type="group", entity_id=g.id,
                 details={"name": g.name, "registrations": [str(r) for r in body.registration_ids]}, ip=p.ip)
    db.commit()
    return group_out(g, len(body.registration_ids))


@router.patch("/groups/{gid}")
def rename_group(gid: uuid.UUID, body: GroupPatch, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    g = db.get(EconomicGroup, gid)
    if g is None:
        raise ApiError(404, "not_found", "Grupo não encontrado.")
    name = clean_name(body.name).upper()
    other = db.execute(select(EconomicGroup).where(EconomicGroup.name_key == name_key(name), EconomicGroup.id != g.id)).scalar_one_or_none()
    if other:
        raise ApiError(409, "duplicate", "Já existe um grupo com esse nome.")
    before = g.name
    g.name, g.name_key = name, name_key(name)
    audit.record(db, "group.renamed", actor=p.user, entity_type="group", entity_id=g.id, details={"from": before, "to": g.name}, ip=p.ip)
    db.commit()
    members = db.execute(select(func.count()).select_from(Registration).where(Registration.group_id == g.id)).scalar_one()
    return group_out(g, members)


@router.delete("/groups/{gid}", status_code=204)
def delete_group(gid: uuid.UUID, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    """Removes the grouping only; the registrations stay, without a group."""
    g = db.get(EconomicGroup, gid)
    if g is None:
        raise ApiError(404, "not_found", "Grupo não encontrado.")
    db.execute(update(Registration).where(Registration.group_id == g.id).values(group_id=None))
    audit.record(db, "group.deleted", actor=p.user, entity_type="group", entity_id=g.id, details={"name": g.name}, ip=p.ip)
    db.delete(g)
    db.commit()


def _people(db: Session, reg_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, str]]:
    """Per registration: {name key: name as printed} of every partner, administrator or holder read
    from its documents (and the registration's own name, for individuals)."""
    out: dict[uuid.UUID, dict[str, str]] = {rid: {} for rid in reg_ids}
    rows = db.execute(
        select(Document.registration_id, ExtractedField.name, ExtractedField.value)
        .join(ExtractedField, ExtractedField.document_id == Document.id)
        .where(Document.registration_id.in_(reg_ids), ExtractedField.name.in_(PEOPLE_FIELDS), ExtractedField.value.is_not(None))
    ).all()
    for rid, field, value in rows:
        if field == "nome" and value:
            parts = [value]
        else:
            parts = [x.strip() for x in str(value).replace(" e ", ";").replace(" ou ", ";").split(";")]
        for part in parts:
            key = name_key(part)
            if len(key.split()) >= 2:  # a single word is not enough to say it is the same person
                out[rid].setdefault(key, part.strip().upper())
    return out


@router.get("/registrations/{rid}/group-suggestions")
def group_suggestions(rid: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    others = db.execute(select(Registration).where(Registration.id != reg.id, Registration.status != RegStatus.REJECTED,
                                                   Registration.anonymized_at.is_(None))).scalars().all()
    people = _people(db, [reg.id, *[o.id for o in others]])
    mine = people[reg.id]
    if reg.tax_id and len(reg.tax_id) == 11:
        mine.setdefault(name_key(reg.subject_name), reg.subject_name)
    out = []
    for o in others:
        if reg.group_id and o.group_id == reg.group_id:
            continue
        reasons = []
        if reg.tax_id and o.tax_id and len(reg.tax_id) == 14 and len(o.tax_id) == 14 and reg.tax_id[:8] == o.tax_id[:8]:
            reasons.append("mesma raiz de CNPJ (matriz e filial)")
        theirs = dict(people[o.id])
        if o.tax_id and len(o.tax_id) == 11:
            theirs.setdefault(name_key(o.subject_name), o.subject_name)
        common = sorted(set(mine) & set(theirs))
        if common:
            names = ", ".join(mine[k] for k in common[:3])
            reasons.append(f"{'pessoa' if len(common) == 1 else 'pessoas'} em comum: {names}")
        if reasons:
            out.append({"registration": registration_row(o), "reasons": reasons})
    out.sort(key=lambda x: (0 if any("CNPJ" in r for r in x["reasons"]) else 1, x["registration"]["subject_name"]))
    return {"items": out[:20]}
