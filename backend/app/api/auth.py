from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, ratelimit
from app.api.serializers import user_full
from app.config import get_settings
from app.db import get_db
from app.deps import ANY_ROLE, Principal, client_ip
from app.errors import ApiError
from app.models import User, UserSession, utcnow
from app.security import hash_password, issue_token, password_problems, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    email = body.email.strip().lower()
    ratelimit.hit(f"login-ip:{ip}", limit=20, window_seconds=300)
    ratelimit.hit(f"login-email:{email}", limit=8, window_seconds=300)

    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or user is None or not user.is_active:
        audit.record(db, "auth.login_failed", actor_label=email, entity_type="user", entity_id=user.id if user else None, ip=ip)
        db.commit()
        raise ApiError(401, "invalid_credentials", "E-mail ou senha incorretos.")

    session = UserSession(
        user_id=user.id,
        expires_at=utcnow() + timedelta(hours=get_settings().session_hours),
        client=(request.headers.get("user-agent") or "")[:200],
        ip=ip,
    )
    db.add(session)
    db.flush()
    user.last_login_at = utcnow()
    token, expires_in = issue_token(user.id, session.id, user.role)
    audit.record(db, "auth.login", actor=user, entity_type="user", entity_id=user.id, ip=ip)
    db.commit()
    return {"token": token, "expires_in": expires_in, "user": user_full(user)}


@router.post("/logout")
def logout(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    session = db.get(UserSession, p.session.id)
    session.revoked_at = utcnow()
    audit.record(db, "auth.logout", actor=p.user, entity_type="user", entity_id=p.user.id, ip=p.ip)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(ANY_ROLE)):
    return user_full(p.user)


@router.post("/password")
def change_password(body: PasswordIn, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    user = db.get(User, p.user.id)
    if not verify_password(user.password_hash, body.current_password):
        raise ApiError(400, "invalid_credentials", "A senha atual está incorreta.")
    problems = password_problems(body.new_password)
    if problems:
        raise ApiError(422, "weak_password", " ".join(problems))
    user.password_hash = hash_password(body.new_password)
    for s in db.execute(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.id != p.session.id)).scalars():
        s.revoked_at = utcnow()
    audit.record(db, "auth.password_changed", actor=user, entity_type="user", entity_id=user.id, ip=p.ip)
    db.commit()
    return {"ok": True}
