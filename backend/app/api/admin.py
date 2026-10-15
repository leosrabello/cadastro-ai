"""Administration: operational settings and user accounts. Secrets are never readable or writable here."""

import re
import secrets
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api.serializers import user_full
from app.config import get_settings
from app.config_defaults import DEFAULTS
from app.db import get_db
from app.deps import ADMINS, SUPERVISORS, Principal
from app.errors import ApiError
from app.ingestion.watcher import FolderUnavailable, allowed_folder
from app.models import AppSetting, Role, User, UserSession, utcnow
from app.security import hash_password, password_problems
from app.settings_store import all_settings, get_setting, put_setting
from app.storage import get_store

router = APIRouter(prefix="/api", tags=["admin"])


class ValidityRule(BaseModel):
    has_expiry: bool = False
    expiry_field: str | None = None
    grace_days: int = Field(0, ge=0, le=365)
    max_age_days: int | None = Field(None, ge=1, le=36500)
    max_age_from: str | None = None
    max_age_severity: str | None = Field(None, pattern="^(low|medium|high)$")
    required_values: dict[str, list[str]] | None = None
    requires_signatures: list[str] | None = None
    current_year_max_gap_days: int | None = Field(None, ge=1, le=365)
    note: str | None = Field(None, max_length=500)


class DocType(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    keywords: list[str] = Field(min_length=1, max_length=40)
    fields: list[str] = Field(max_length=20)
    validity: ValidityRule


class Requirement(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    label: str = Field(min_length=2, max_length=160)
    any_of: list[str] = Field(default_factory=list)
    options: list[list[str]] | None = None
    stage: str | None = None
    group: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=300)
    year_offset: int | None = Field(None, ge=-10, le=0)
    per_partner: bool = False
    required: bool = True

    @model_validator(mode="after")
    def _some_type(self):
        if not self.any_of and not self.options:
            raise ValueError("informe any_of ou options")
        return self


class Stage(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    label: str = Field(min_length=2, max_length=80)
    blocks_decision: bool = False
    note: str | None = Field(None, max_length=300)


class RequiredInfo(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    label: str = Field(min_length=2, max_length=120)
    hint: str | None = Field(None, max_length=200)
    group: str | None = Field(None, max_length=80)
    stage: str | None = None


class RequiredField(BaseModel):
    field: str
    label: str
    in_any_of: list[str] = Field(min_length=1)


class Profile(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    tax_id_kind: str = Field(pattern="^(cpf|cnpj)$")
    source: str | None = Field(None, max_length=200)
    stages: list[Stage] = Field(default_factory=list)
    required: list[Requirement]
    required_info: list[RequiredInfo] = Field(default_factory=list)
    required_fields: list[RequiredField] = Field(default_factory=list)


class PriorityRule(BaseModel):
    id: str
    label: str = Field(min_length=2, max_length=120)
    points: int = Field(ge=0, le=1000)
    days: int | None = Field(None, ge=1, le=90)


class Processing(BaseModel):
    ai_enabled: bool
    ai_send_images: bool
    compare_text_layer: bool
    duplicate_phash_distance: int = Field(ge=0, le=20)
    auto_assign_by_extracted_id: bool
    min_ocr_confidence: float = Field(ge=0, le=1)


class Association(BaseModel):
    registration_code_pattern: str | None = Field(None, max_length=200)
    use_parent_folder: bool = True
    match_tax_id_in_filename: bool = True


class Watcher(BaseModel):
    enabled: bool
    folder: str = Field(min_length=1, max_length=500)
    scan_interval_seconds: int = Field(ge=2, le=3600)
    stable_seconds: int = Field(ge=2, le=600)
    after_ingest: str = Field(pattern="^(move|leave)$")
    ignore_patterns: list[str] = Field(max_length=40)
    association: Association


class Retention(BaseModel):
    rejected_days: int | None = Field(None, ge=0, le=3650)  # 0 = on rejection
    abandoned_pending_days: int | None = Field(None, ge=30, le=3650)
    approved_note: str | None = None


class Integrations(BaseModel):
    shared_folder: bool
    email_outlook: bool = False
    whatsapp: bool = False


class Approval(BaseModel):
    approve_roles: list[str]
    reject_roles: list[str]
    override_roles: list[str]
    allow_approve_with_open_findings: bool


class Consistency(BaseModel):
    name_match: dict[str, Any]
    tax_id_match: dict[str, Any]
    birth_date_match: dict[str, Any]
    registration_name_match: dict[str, Any]


class ClientStatus(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    label: str = Field(min_length=2, max_length=80)
    outcome: Literal["approved", "denied"] | None = None
    opens_signature: bool = False


class ClientStatuses(BaseModel):
    normal: list[ClientStatus] = Field(min_length=1)
    one7: list[ClientStatus] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self):
        for name in ("normal", "one7"):
            keys = [s.key for s in getattr(self, name)]
            if len(keys) != len(set(keys)):
                raise ValueError(f"status repetido em {name}")
        return self


class Portfolio(BaseModel):
    sla_days: int = Field(7, ge=1, le=365)


VALIDATORS = {
    "document_types": lambda v: {k: DocType.model_validate(x).model_dump(exclude_none=True) for k, x in v.items()},
    "requirement_profiles": lambda v: {k: Profile.model_validate(x).model_dump(exclude_none=True) for k, x in v.items()},
    "priority_rules": lambda v: [PriorityRule.model_validate(x).model_dump(exclude_none=True) for x in v],
    "processing": lambda v: Processing.model_validate(v).model_dump(),
    "watcher": lambda v: Watcher.model_validate(v).model_dump(),
    "retention": lambda v: Retention.model_validate(v).model_dump(),
    "integrations": lambda v: Integrations.model_validate(v).model_dump(),
    "approval": lambda v: Approval.model_validate(v).model_dump(),
    "consistency_rules": lambda v: Consistency.model_validate(v).model_dump(),
    "client_statuses": lambda v: ClientStatuses.model_validate(v).model_dump(exclude_defaults=True),
    "portfolio": lambda v: Portfolio.model_validate(v).model_dump(),
}


@router.get("/settings")
def read_settings(p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    s = get_settings()
    versions = {row.key: {"version": row.version, "updated_at": row.updated_at.isoformat()} for row in db.execute(select(AppSetting)).scalars()}
    return {
        "settings": all_settings(db),
        "versions": versions,
        "system": {
            "ocr_provider": s.ocr_provider,
            "ocr_configured": s.ocr_provider == "tesseract" or bool(s.azure_di_endpoint and s.azure_di_key),
            "ai_provider": s.ai_provider,
            "ai_configured": s.ai_configured,
            "ai_model": s.ai_model,
            "ai_images_allowed_by_server": s.ai_allow_images,
            "storage_healthy": get_store().healthy(),
            "watch_roots": [str(r) for r in s.allowed_watch_roots],
            "max_upload_mb": s.max_upload_mb,
            "pipeline_version": s.pipeline_version,
        },
    }


@router.put("/settings/{key}")
def write_setting(key: str, value: Any = Body(...), p: Principal = Depends(ADMINS), db: Session = Depends(get_db)):
    if key not in DEFAULTS:
        raise ApiError(404, "not_found", "Configuração desconhecida.")
    try:
        clean = VALIDATORS[key](value)
    except (ValidationError, AttributeError, TypeError) as exc:
        details = exc.errors() if isinstance(exc, ValidationError) else str(exc)
        raise ApiError(422, "invalid_setting", "Configuração inválida.", details=details)
    if key == "watcher":
        try:
            allowed_folder(clean["folder"])
        except FolderUnavailable as exc:
            raise ApiError(422, "invalid_folder", str(exc))
        pat = clean["association"].get("registration_code_pattern")
        if pat:
            try:
                re.compile(pat)
            except re.error:
                raise ApiError(422, "invalid_pattern", "Expressão de associação inválida.")
    if key == "processing" and clean["ai_enabled"] and not get_settings().ai_configured:
        raise ApiError(422, "ai_not_configured", "Nenhum provedor de IA está configurado no servidor. Veja docs/configuration.md.")
    if key == "requirement_profiles":
        types = set(get_setting(db, "document_types"))
        for prof in clean.values():
            for req in prof["required"]:
                unknown = (set(req.get("any_of", [])) | {t for opt in req.get("options", []) for t in opt}) - types
                if unknown:
                    raise ApiError(422, "unknown_type", f"Tipos desconhecidos em {req['label']}: {', '.join(sorted(unknown))}")
    before = get_setting(db, key)
    put_setting(db, key, clean, p.user.id)
    audit.record(db, "settings.updated", actor=p.user, entity_type="setting", entity_id=key, details={"before": before, "after": clean}, ip=p.ip)
    db.commit()
    return {"key": key, "value": clean}


def _user_references(db: Session, uid: uuid.UUID) -> int:
    """How many records name this user as their author (registrations, decisions, documents, reviews...)."""
    from app.models import Base

    total = 0
    for table in Base.metadata.sorted_tables:
        if table.name == "user_sessions":
            continue
        for col in table.columns:
            if any(fk.column.table.name == "users" for fk in col.foreign_keys):
                total += db.execute(select(func.count()).select_from(table).where(col == uid)).scalar_one()
    return total


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    name: str = Field(min_length=2, max_length=200)
    role: str
    password: str = Field(min_length=1, max_length=256)


class UserPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(None, max_length=256)


@router.get("/users")
def list_users(p: Principal = Depends(ADMINS), db: Session = Depends(get_db)):
    return {"items": [user_full(u) for u in db.execute(select(User).where(User.deleted_at.is_(None)).order_by(User.name)).scalars()]}


@router.post("/users", status_code=201)
def create_user(body: UserIn, p: Principal = Depends(ADMINS), db: Session = Depends(get_db)):
    if body.role not in Role.ALL:
        raise ApiError(422, "invalid_role", "Perfil inválido.")
    if db.execute(select(User).where(func.lower(User.email) == body.email.lower())).scalar_one_or_none():
        raise ApiError(409, "conflict", "Já existe um usuário com este e-mail.")
    problems = password_problems(body.password)
    if problems:
        raise ApiError(422, "weak_password", " ".join(problems))
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit.record(db, "user.created", actor=p.user, entity_type="user", entity_id=user.id, details={"email": user.email, "role": user.role}, ip=p.ip)
    db.commit()
    return user_full(user)


@router.patch("/users/{uid}")
def update_user(uid: uuid.UUID, body: UserPatch, p: Principal = Depends(ADMINS), db: Session = Depends(get_db)):
    user = db.get(User, uid)
    if user is None:
        raise ApiError(404, "not_found", "Usuário não encontrado.")
    changes: dict[str, Any] = {}
    if body.name is not None:
        user.name = body.name
        changes["name"] = body.name
    if body.role is not None:
        if body.role not in Role.ALL:
            raise ApiError(422, "invalid_role", "Perfil inválido.")
        if user.id == p.user.id and body.role != Role.ADMIN:
            raise ApiError(409, "self_lockout", "Você não pode remover o próprio perfil de administrador.")
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.password:
        problems = password_problems(body.password)
        if problems:
            raise ApiError(422, "weak_password", " ".join(problems))
        user.password_hash = hash_password(body.password)
        changes["password"] = "reset"
    if body.name is not None and not body.name.strip():
        raise ApiError(422, "name_required", "Informe o nome.")
    revoke = False
    if body.is_active is not None and body.is_active != user.is_active:
        if user.id == p.user.id:
            raise ApiError(409, "self_lockout", "Você não pode desativar a própria conta.")
        user.is_active = body.is_active
        user.deactivated_at = None if body.is_active else utcnow()
        changes["is_active"] = body.is_active
        revoke = not body.is_active
    if revoke or "role" in changes or "password" in changes:
        # changing your own password keeps the session you are using; every other one ends
        keep = p.session.id if user.id == p.user.id else None
        for s in db.execute(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))).scalars():
            if s.id != keep:
                s.revoked_at = utcnow()
        changes["sessions_revoked"] = True
    audit.record(db, "user.updated", actor=p.user, entity_type="user", entity_id=user.id, details=changes, ip=p.ip)
    db.commit()
    return user_full(user)


@router.delete("/users/{uid}")
def delete_user(uid: uuid.UUID, p: Principal = Depends(ADMINS), db: Session = Depends(get_db)):
    user = db.get(User, uid)
    if user is None or user.deleted_at is not None:
        raise ApiError(404, "not_found", "Usuário não encontrado.")
    if user.id == p.user.id:
        raise ApiError(409, "self_lockout", "Você não pode excluir a própria conta.")
    if user.role == Role.ADMIN:
        admins = db.execute(select(func.count(User.id)).where(User.role == Role.ADMIN, User.is_active.is_(True), User.deleted_at.is_(None), User.id != user.id)).scalar_one()
        if not admins:
            raise ApiError(409, "last_admin", "É o último administrador ativo; crie outro antes de excluir este.")
    refs = _user_references(db, user.id)
    label = {"name": user.name, "email": user.email, "role": user.role}
    if refs == 0:
        db.execute(UserSession.__table__.delete().where(UserSession.user_id == user.id))
        db.delete(user)
        mode = "removed"
    else:
        # the name stays on what this person did; the account and the e-mail are released
        now = utcnow()
        for s in db.execute(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))).scalars():
            s.revoked_at = now
        user.is_active = False
        user.deactivated_at = user.deactivated_at or now
        user.deleted_at = now
        user.email = f"removido-{user.id.hex[:12]}@{user.email.split('@', 1)[-1]}"[:254]
        user.password_hash = hash_password(secrets.token_urlsafe(32))
        mode = "retired"
    audit.record(db, "user.deleted", actor=p.user, entity_type="user", entity_id=uid, details={**label, "mode": mode, "history_records": refs}, ip=p.ip)
    db.commit()
    return {"deleted": True, "mode": mode, "history_records": refs}
