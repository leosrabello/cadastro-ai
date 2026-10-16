"""Add to a server's saved document types the fields new versions read by default, keeping every
change an administrator made. Safe to run more than once.

    docker compose exec api python scripts/add_document_fields.py

Documents already processed get the new fields when they are reprocessed (Reprocessar, on the
document page); new documents get them at once.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import audit  # noqa: E402
from app.config_defaults import DOCUMENT_TYPES  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.settings_store import get_setting, put_setting  # noqa: E402


def main() -> None:
    with session_scope() as db:
        saved = get_setting(db, "document_types")
        added: dict[str, list[str]] = {}
        for key, default in DOCUMENT_TYPES.items():
            if key not in saved:
                continue
            missing = [f for f in default.get("fields", []) if f not in saved[key].get("fields", [])]
            if missing:
                saved[key]["fields"] = [*saved[key].get("fields", []), *missing]
                added[key] = missing
        if not added:
            print("nada a acrescentar")
            return
        put_setting(db, "document_types", saved, None)
        audit.record(db, "settings.updated", actor_label="atualização: campos novos dos documentos", entity_type="setting",
                     entity_id="document_types", details={"fields_added": added})
        for key, fields in added.items():
            print(f"{key}: {', '.join(fields)}")


if __name__ == "__main__":
    main()
