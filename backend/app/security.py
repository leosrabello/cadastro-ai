import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings
from app.models import utcnow

_hasher = PasswordHasher()
ALGORITHM = "HS256"
# Verifying against a fixed hash for unknown users keeps login timing uniform.
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("A senha precisa ter pelo menos 12 caracteres.")
    if password.lower() == password or password.upper() == password:
        problems.append("Use letras maiúsculas e minúsculas.")
    if not any(c.isdigit() for c in password):
        problems.append("Inclua pelo menos um número.")
    return problems


def issue_token(user_id: uuid.UUID, session_id: uuid.UUID, role: str) -> tuple[str, int]:
    settings = get_settings()
    lifetime = timedelta(hours=settings.session_hours)
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": "cadastro-ai",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), int(lifetime.total_seconds())


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[ALGORITHM],
        issuer="cadastro-ai",
        options={"require": ["sub", "sid", "exp"]},
    )
