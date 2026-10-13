import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import ratelimit
from app.db import get_db
from app.errors import ApiError
from app.models import Role, User, UserSession, utcnow
from app.security import decode_token

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    session: UserSession
    ip: str | None

    @property
    def role(self) -> str:
        return self.user.role


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if creds is None:
        raise ApiError(401, "unauthenticated", "Sessão ausente. Entre novamente.")
    try:
        claims = decode_token(creds.credentials)
        user_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise ApiError(401, "unauthenticated", "Sessão inválida ou expirada. Entre novamente.")

    session = db.get(UserSession, session_id)
    user = db.get(User, user_id)
    if (
        session is None
        or user is None
        or session.user_id != user.id
        or session.revoked_at is not None
        or session.expires_at <= utcnow()
        or not user.is_active
    ):
        raise ApiError(401, "unauthenticated", "Sessão encerrada. Entre novamente.")

    ratelimit.hit(f"user:{user.id}", limit=900, window_seconds=60)
    return Principal(user=user, session=session, ip=client_ip(request))


def require(*roles: str):
    allowed = set(roles)

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed:
            raise ApiError(403, "forbidden", "Seu perfil não tem permissão para esta ação.")
        return principal

    return _dep


ANY_ROLE = require(*Role.ALL)
OPERATORS = require(Role.ANALYST, Role.SUPERVISOR, Role.ADMIN)
SUPERVISORS = require(Role.SUPERVISOR, Role.ADMIN)
ADMINS = require(Role.ADMIN)
AUDIT_READERS = require(Role.SUPERVISOR, Role.ADMIN, Role.AUDITOR)
