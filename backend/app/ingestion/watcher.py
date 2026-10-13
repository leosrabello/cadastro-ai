"""Shared-folder intake service.

Runs as its own process on the server (never inside the desktop app), polls the configured
folder, and hands each completed file to the same ingest() used by desktop uploads.

Polling rather than filesystem events is deliberate: inotify/ReadDirectoryChangesW do not
report reliably over SMB/CIFS mounts, and a poll survives reconnects without re-arming.

Safety rules:
- a file is taken only after its size and mtime have been unchanged for `stable_seconds`,
  it can be opened for reading, and its format trailer is present (no partial copies);
- temporary and hidden files are ignored;
- every file is hashed: content already ingested is never ingested twice, whatever its name;
- an advisory lock in PostgreSQL guarantees one active watcher even if two are started;
- the folder being unreachable is reported in watcher_status and retried with backoff.
"""

import fnmatch
import logging
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory
from app.ingestion.service import DuplicateDocument, RegistrationClosed, ingest, sha256_hex
from app.ingestion.validation import RejectedFile
from app.models import IngestRecord, RegStatus, Registration, WatcherStatus, utcnow
from app.pipeline.normalize import valid_cnpj, valid_cpf
from app.settings_store import get_setting

log = logging.getLogger("watcher")

DONE_DIRS = {"_processados", "_falhas", "_duplicados"}
WATCHER_LOCK = 74_221_002
INCOMPLETE_GIVE_UP_SECONDS = 600


@dataclass
class Candidate:
    size: int
    mtime: float
    stable_since: float
    first_seen: float


class FolderUnavailable(Exception):
    pass


def allowed_folder(path: str) -> Path:
    folder = Path(path).resolve()
    roots = get_settings().allowed_watch_roots
    if not any(folder == r or r in folder.parents for r in roots):
        raise FolderUnavailable(f"pasta fora das raízes permitidas ({', '.join(map(str, roots))})")
    return folder


def looks_complete(data: bytes) -> bool:
    tail = data[-2048:]
    if data.startswith(b"%PDF-"):
        return b"%%EOF" in tail
    if data.startswith(b"\xff\xd8\xff"):
        return data.rstrip(b"\x00").endswith(b"\xff\xd9")
    if data.startswith(b"\x89PNG"):
        return b"IEND" in data[-16:]
    return True  # unknown types are complete as far as we can tell; screening rejects them


class FolderWatcher:
    def __init__(self, clock=time.monotonic, enqueue=None):
        self.clock = clock
        self.candidates: dict[str, Candidate] = {}
        self.failed: dict[str, float] = {}  # path -> mtime at failure; retried only if the file changes
        if enqueue is None:
            from app.worker import enqueue as default_enqueue

            enqueue = default_enqueue
        self.enqueue = enqueue

    # ---------- one polling pass ----------
    def scan_once(self, db: Session) -> dict:
        cfg = get_setting(db, "watcher")
        summary = {"seen": 0, "ingested": 0, "duplicates": 0, "rejected": 0, "failed": 0, "waiting": 0}
        if not cfg.get("enabled") or not get_setting(db, "integrations").get("shared_folder", True):
            self._status(db, cfg.get("folder"), False, "monitoramento desativado nas configurações", 0)
            return summary
        try:
            folder = allowed_folder(cfg["folder"])
            if not folder.is_dir():
                raise FolderUnavailable("pasta não encontrada ou rede indisponível")
            files = list(self._list(folder, cfg.get("ignore_patterns", [])))
        except (OSError, FolderUnavailable) as exc:
            self._status(db, cfg.get("folder"), False, str(exc), len(self.candidates))
            raise FolderUnavailable(str(exc)) from exc

        now = self.clock()
        present = set()
        for path, st in files:
            key = str(path)
            present.add(key)
            summary["seen"] += 1
            if key in self.failed and self.failed[key] == st.st_mtime:
                continue
            c = self.candidates.get(key)
            if c is None or c.size != st.st_size or c.mtime != st.st_mtime:
                self.candidates[key] = Candidate(st.st_size, st.st_mtime, now, c.first_seen if c else now)
                summary["waiting"] += 1
                continue
            if now - c.stable_since < cfg.get("stable_seconds", 8) or st.st_size == 0:
                summary["waiting"] += 1
                continue
            outcome = self._take(db, folder, path, cfg, c, now)
            if outcome == "waiting":
                summary["waiting"] += 1
            else:
                summary[outcome] += 1
                self.candidates.pop(key, None)
        for gone in set(self.candidates) - present:
            self.candidates.pop(gone, None)
        self._status(db, str(folder), True, None, summary["waiting"], summary["ingested"])
        return summary

    def _list(self, folder: Path, patterns: list[str]):
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in DONE_DIRS and not d.startswith(".")]
            for name in names:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    continue
                path = Path(root) / name
                try:
                    st = path.stat()
                except FileNotFoundError:
                    continue
                if path.is_file():
                    yield path, st

    # ---------- one file ----------
    def _take(self, db: Session, folder: Path, path: Path, cfg: dict, cand: Candidate, now: float) -> str:
        rel = str(path.relative_to(folder))
        try:
            data = path.read_bytes()
        except PermissionError as exc:
            self._fail(db, path, rel, cand, f"sem permissão de leitura para a conta do serviço: {exc}")
            return "failed"
        except OSError as exc:
            # locked by the copying process (Windows sharing violation) or the share dropped: try later
            log.info("not readable yet %s: %s", rel, exc)
            return "waiting"

        if not looks_complete(data):
            if now - cand.first_seen > INCOMPLETE_GIVE_UP_SECONDS:
                self._fail(db, path, rel, cand, "cópia incompleta: o arquivo não terminou de ser transferido em 10 minutos")
                self._move(folder, path, "_falhas", "Arquivo incompleto ou corrompido.")
                return "failed"
            return "waiting"

        sha = sha256_hex(data)
        prior = db.execute(select(IngestRecord).where(IngestRecord.sha256 == sha, IngestRecord.status == "ingested").limit(1)).scalar_one_or_none()
        if prior is not None:
            self._record(db, rel, sha, len(data), "duplicate", f"conteúdo idêntico já recebido como {prior.source_ref}", prior.document_id)
            db.commit()
            if cfg.get("after_ingest", "move") == "move":
                self._move(folder, path, "_duplicados", f"Conteúdo idêntico a {prior.source_ref}.")
            return "duplicates"

        registration, note = self._associate(db, rel, cfg.get("association", {}))
        try:
            result = ingest(db, data=data, filename=path.name, source="shared_folder", source_ref=rel, registration=registration)
        except RejectedFile as exc:
            db.rollback()
            self._record(db, rel, sha, len(data), "rejected", exc.message, None)
            db.commit()
            self._move(folder, path, "_falhas", exc.message)
            return "rejected"
        except (DuplicateDocument, RegistrationClosed) as exc:
            db.rollback()
            msg = "documento já existe neste cadastro" if isinstance(exc, DuplicateDocument) else "cadastro já decidido"
            self._record(db, rel, sha, len(data), "duplicate" if isinstance(exc, DuplicateDocument) else "rejected", msg, None)
            db.commit()
            self._move(folder, path, "_duplicados" if isinstance(exc, DuplicateDocument) else "_falhas", msg)
            return "duplicates" if isinstance(exc, DuplicateDocument) else "rejected"
        except Exception as exc:  # storage down etc.: leave the file, retry next pass
            db.rollback()
            log.warning("ingest failed for %s, will retry: %s", rel, exc)
            return "waiting"

        self._record(db, rel, sha, len(data), "ingested", note, result.document.id)
        db.commit()
        self.enqueue(result.document.id)
        if cfg.get("after_ingest", "move") == "move":
            self._move(folder, path, f"_processados/{datetime.now().strftime('%Y-%m-%d')}", None)
        return "ingested"

    def _associate(self, db: Session, rel: str, rules: dict) -> tuple[Registration | None, str | None]:
        pattern = rules.get("registration_code_pattern")
        parts = Path(rel).parts
        haystacks = [parts[-1]]
        if rules.get("use_parent_folder", True) and len(parts) > 1:
            haystacks.insert(0, parts[0])
        if pattern:
            for h in haystacks:
                m = re.search(pattern, h, re.I)
                if m:
                    code = (m.group(1) if m.groups() else m.group(0)).upper()
                    reg = db.execute(select(Registration).where(Registration.code == code)).scalar_one_or_none()
                    if reg is None:
                        return None, f"código {code} não encontrado; aguardando associação manual"
                    if reg.status in RegStatus.FINAL:
                        return None, f"{code} já decidido; aguardando associação manual"
                    return reg, f"associado pelo código {code}"
        if rules.get("match_tax_id_in_filename", True):
            for h in haystacks:
                for d in re.findall(r"(?<!\d)(\d{14}|\d{11})(?!\d)", re.sub(r"[.\-/]", "", h)):
                    if (len(d) == 11 and valid_cpf(d)) or (len(d) == 14 and valid_cnpj(d)):
                        regs = db.execute(select(Registration).where(Registration.tax_id == d, Registration.status.notin_(RegStatus.FINAL))).scalars().all()
                        if len(regs) == 1:
                            return regs[0], "associado pelo CPF/CNPJ no nome do arquivo"
                        if len(regs) > 1:
                            return None, "mais de um cadastro com este CPF/CNPJ; aguardando associação manual"
        return None, "sem regra de associação aplicável; aguardando associação manual"

    def _record(self, db, rel, sha, size, status, detail, document_id):
        existing = db.execute(select(IngestRecord).where(IngestRecord.source == "shared_folder", IngestRecord.source_ref == rel, IngestRecord.sha256 == sha)).scalar_one_or_none()
        if existing:
            existing.status, existing.detail, existing.document_id = status, detail, document_id or existing.document_id
            return
        db.add(IngestRecord(source="shared_folder", source_ref=rel, sha256=sha, size_bytes=size, status=status, detail=detail, document_id=document_id))

    def _fail(self, db, path: Path, rel: str, cand: Candidate, message: str):
        self.failed[str(path)] = cand.mtime
        self._record(db, rel, "-" * 64, cand.size, "failed", message, None)
        db.commit()
        log.warning("%s: %s", rel, message)

    def _move(self, folder: Path, path: Path, sub: str, reason: str | None):
        target_dir = folder / sub
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name
            n = 1
            while target.exists():
                target = target_dir / f"{path.stem} ({n}){path.suffix}"
                n += 1
            shutil.move(str(path), str(target))
            if reason:
                target.with_name(target.name + ".motivo.txt").write_text(reason + "\n", encoding="utf-8")
        except OSError as exc:
            # cannot move (read-only share): the ingest record and hash still prevent reprocessing
            log.warning("could not move %s to %s: %s", path, sub, exc)

    def _status(self, db: Session, folder, reachable: bool, error: str | None, pending: int, ingested: int = 0):
        row = db.get(WatcherStatus, 1) or WatcherStatus(id=1)
        row.folder, row.reachable, row.last_error, row.pending_files = folder, reachable, error, pending
        row.last_scan_at = utcnow()
        row.ingested_total = (row.ingested_total or 0) + ingested
        db.add(row)
        db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))

    factory = session_factory()
    lock_conn = factory().connection()
    while not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": WATCHER_LOCK}).scalar():
        log.info("another watcher holds the lock; standing by")
        time.sleep(15)
        if stop["flag"]:
            return

    watcher = FolderWatcher()
    backoff = 0
    log.info("watcher started")
    while not stop["flag"]:
        interval = 10
        with factory() as db:
            try:
                interval = int(get_setting(db, "watcher").get("scan_interval_seconds", 10))
                summary = watcher.scan_once(db)
                if any(summary[k] for k in ("ingested", "duplicates", "rejected", "failed")):
                    log.info("scan: %s", summary)
                backoff = 0
            except FolderUnavailable as exc:
                backoff = min(backoff + 1, 6)
                log.warning("folder unavailable (%s); retry in %ss", exc, interval * 2 ** backoff)
            except Exception:
                log.exception("scan failed")
                backoff = min(backoff + 1, 6)
        time.sleep(interval * (2 ** backoff if backoff else 1))
    log.info("watcher stopped")


if __name__ == "__main__":
    main()
