import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app import errors
from app.api import admin, auth, documents, groups, operations, portfolio, registrations, report
from app.config import get_settings
from app.db import session_scope
from app.models import Role, User
from app.security import hash_password, password_problems
from app.settings_store import seed_defaults

log = logging.getLogger("cadastro_ai")


def bootstrap() -> None:
    """Seed operational defaults, and the first administrator if none exists."""
    s = get_settings()
    with session_scope() as db:
        seed_defaults(db)
        has_admin = db.execute(select(func.count(User.id)).where(User.role == Role.ADMIN)).scalar_one()
        if not has_admin and s.bootstrap_admin_email and s.bootstrap_admin_password:
            problems = password_problems(s.bootstrap_admin_password)
            if problems:
                raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD is too weak: " + " ".join(problems))
            db.add(User(email=s.bootstrap_admin_email.lower(), name="Administrador", role=Role.ADMIN,
                        password_hash=hash_password(s.bootstrap_admin_password)))
            log.warning("created bootstrap administrator %s — change the password after first login", s.bootstrap_admin_email)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Cadastro AI",
        version=s.pipeline_version,
        docs_url=None if s.is_production else "/api/docs",
        openapi_url=None if s.is_production else "/api/openapi.json",
    )
    errors.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/") and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    for module in (auth, registrations, documents, operations, admin, report, portfolio, groups):
        app.include_router(module.router)

    @app.on_event("startup")
    def _startup() -> None:
        bootstrap()

    return app


app = create_app()
