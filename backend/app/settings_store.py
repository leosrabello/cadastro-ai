import copy
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config_defaults import DEFAULTS
from app.models import AppSetting, utcnow


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        return copy.deepcopy(DEFAULTS[key])
    value = row.value
    # stored as {"v": ...} so lists and scalars round-trip through JSONB uniformly
    return value["v"] if isinstance(value, dict) and "v" in value else value


def all_settings(db: Session) -> dict[str, Any]:
    return {key: get_setting(db, key) for key in DEFAULTS}


def put_setting(db: Session, key: str, value: Any, user_id: uuid.UUID | None) -> AppSetting:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value={"v": value}, version=1, updated_by_id=user_id)
        db.add(row)
    else:
        row.value = {"v": value}
        row.version += 1
        row.updated_by_id = user_id
        row.updated_at = utcnow()
    return row


def seed_defaults(db: Session) -> None:
    for key, value in DEFAULTS.items():
        if db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value={"v": copy.deepcopy(value)}, version=1))
