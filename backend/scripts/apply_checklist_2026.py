"""Make the FinTrust document checklist (2026, v2.1) the standard on an existing server.

    docker compose exec api python scripts/apply_checklist_2026.py

Adds the new document types, replaces the requirement profiles with the checklist, records both
changes in the audit trail, and re-analyses open registrations so their checklists follow.
New installations get the same defaults automatically (app/config_defaults.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import audit  # noqa: E402
from app.config_defaults import DOCUMENT_TYPES, REQUIREMENT_PROFILES  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import RegStatus, Registration  # noqa: E402
from app.pipeline.orchestrator import analyze_registration  # noqa: E402
from app.settings_store import get_setting, put_setting  # noqa: E402

LABEL = "migração: checklist FinTrust 2026 v2.1"


def main() -> None:
    with session_scope() as db:
        types_before = get_setting(db, "document_types")
        types_after = {**types_before, **DOCUMENT_TYPES}
        put_setting(db, "document_types", types_after, None)
        audit.record(db, "settings.updated", actor_label=LABEL, entity_type="setting", entity_id="document_types",
                     details={"added": sorted(set(DOCUMENT_TYPES) - set(types_before)), "updated": sorted(set(DOCUMENT_TYPES) & set(types_before))})
        profiles_before = get_setting(db, "requirement_profiles")
        put_setting(db, "requirement_profiles", REQUIREMENT_PROFILES, None)
        audit.record(db, "settings.updated", actor_label=LABEL, entity_type="setting", entity_id="requirement_profiles",
                     details={"before": profiles_before, "after": REQUIREMENT_PROFILES})
    with session_scope() as db:
        regs = db.execute(select(Registration).where(Registration.status != RegStatus.REJECTED)).scalars().all()
        for reg in regs:
            analyze_registration(db, reg.id)
        print(f"document types: {len(DOCUMENT_TYPES)} · profiles: {', '.join(REQUIREMENT_PROFILES)} · registrations re-analysed: {len(regs)}")


if __name__ == "__main__":
    main()
