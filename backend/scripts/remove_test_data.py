"""Remove test data from a server: registrations created by the old demo seed or by hand while testing,
their documents (stored files included) and the synthetic files dropped in the monitored folder.

    docker compose exec api python scripts/remove_test_data.py                      # preview only
    docker compose exec api python scripts/remove_test_data.py --codes CAD-2026-000011 --apply

What counts as test data, found automatically:
  - a registration with a synthetic document: the test generator prints
    "DOCUMENTO SINTÉTICO — SEM VALOR — GERADO PARA TESTES" on every page it makes;
  - a registration created by the bootstrap administrator with one of the names the old demo seed used;
  - an inbox document (no registration) with the synthetic banner.
Registrations made by hand while testing cannot be told apart from real ones by any rule, so they are
removed only when named with --codes after someone checked them.

Users are never deleted (the audit trail refers to them); the old demo accounts are deactivated.
Audit events are append-only and stay; each removal adds one more event saying what was removed and why.
Take a backup first: pg_dump of the database and a copy of STORAGE_DIR.
"""

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import delete, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import audit  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Document,
    ExtractedField,
    Finding,
    IngestRecord,
    ProcessingJob,
    Registration,
    User,
)
from app.retention import delete_registration  # noqa: E402
from app.storage import StorageUnavailable, get_store  # noqa: E402

SYNTHETIC_MARK = "%SINT%TIC%SEM VALOR%"
DEMO_SEED_NAMES = {
    "MARIA APARECIDA DOS SANTOS SILVA", "JOSE CARLOS PEREIRA LIMA", "FERNANDA OLIVEIRA COSTA", "RICARDO ALVES MOREIRA",
    "LUCIANA FERREIRA DIAS", "BRUNO HENRIQUE SOUZA", "PADARIA BOM GRAO LTDA", "TATIANE GOMES DE ALMEIDA",
    "RECICLAGEM VALE VERDE LTDA",
}
DEMO_USERS = {"ana.analista@cadastro.local", "sergio.supervisor@cadastro.local", "aud.auditoria@cadastro.local"}
DEMO_FOLDER_FILES = {"arquivo-errado.pdf", "digitalizacao_0042.png"}


def find(db, codes: set[str]):
    admin_email = (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "").lower()
    admin = db.execute(select(User).where(User.email == admin_email)).scalar_one_or_none() if admin_email else None
    synthetic_regs = set(db.execute(select(Document.registration_id).where(Document.registration_id.is_not(None), Document.ocr_text.ilike(SYNTHETIC_MARK))).scalars())
    found: dict = {}
    for reg in db.execute(select(Registration).order_by(Registration.code)).scalars():
        why = []
        if reg.id in synthetic_regs:
            why.append("documento sintético do gerador de testes")
        if admin and reg.created_by_id == admin.id and reg.subject_name in DEMO_SEED_NAMES:
            why.append("nome da seed de demonstração, criado pelo administrador inicial")
        if reg.code in codes:
            why.append("indicado com --codes")
        if why:
            found[reg] = why
    missing = codes - {r.code for r in found}
    inbox = db.execute(select(Document).where(Document.registration_id.is_(None), Document.ocr_text.ilike(SYNTHETIC_MARK))).scalars().all()
    return found, sorted(missing), inbox


def remove_documents(db, docs: list[Document]) -> int:
    store = get_store()
    ids = [d.id for d in docs]
    if not ids:
        return 0
    for d in docs:
        for key in (d.storage_key, d.rendition_key):
            if not key:
                continue
            try:
                store.delete(key)
            except StorageUnavailable as exc:
                raise SystemExit(f"armazenamento indisponível, nada foi removido: {exc}")
    db.execute(update(Document).where(Document.duplicate_of_id.in_(ids)).values(duplicate_of_id=None))
    db.execute(delete(ExtractedField).where(ExtractedField.document_id.in_(ids)))
    db.execute(delete(Finding).where(Finding.document_id.in_(ids)))
    db.execute(delete(ProcessingJob).where(ProcessingJob.document_id.in_(ids)))
    db.execute(delete(IngestRecord).where(IngestRecord.document_id.in_(ids)))
    db.execute(delete(Document).where(Document.id.in_(ids)))
    return len(ids)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codes", nargs="*", default=[], help="códigos de cadastros de teste conferidos por uma pessoa")
    ap.add_argument("--apply", action="store_true", help="remove de fato; sem isto, só mostra o que seria removido")
    args = ap.parse_args()

    with session_scope() as db:
        found, missing, inbox = find(db, set(args.codes))
        if missing:
            sys.exit(f"códigos inexistentes: {', '.join(missing)}; nada foi removido")
        print("Cadastros de teste:")
        for reg, why in found.items():
            docs = db.execute(select(Document).where(Document.registration_id == reg.id)).scalars().all()
            print(f"  {reg.code}  {reg.subject_name[:40]:40}  {len(docs)} doc(s)  [{'; '.join(why)}]")
        print(f"Documentos sintéticos na caixa de entrada: {len(inbox)}")
        demo_users = db.execute(select(User).where(User.email.in_(DEMO_USERS), User.is_active.is_(True))).scalars().all()
        print(f"Contas de demonstração a desativar: {', '.join(u.email for u in demo_users) or 'nenhuma'}")
        if not args.apply:
            print("\nPrévia apenas. Rode de novo com --apply para remover.")
            return

        n_docs = remove_documents(db, list(inbox))
        db.execute(delete(IngestRecord).where(IngestRecord.document_id.is_(None), IngestRecord.source_ref.in_(DEMO_FOLDER_FILES)))
        for reg, why in found.items():
            n_docs += delete_registration(db, reg, "dados de teste: " + "; ".join(why), actor_label="limpeza de dados de teste")
        for u in demo_users:
            u.is_active = False
            audit.record(db, "user.deactivated", actor_label="limpeza de dados de teste", entity_type="user", entity_id=u.id,
                         details={"email": u.email, "reason": "conta de demonstração"})
        db.flush()
        print(f"\nRemovidos: {len(found)} cadastro(s), {n_docs} documento(s). Contas desativadas: {len(demo_users)}.")


if __name__ == "__main__":
    main()
