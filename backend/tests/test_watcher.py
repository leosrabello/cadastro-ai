"""Shared-folder intake: completion detection, duplicates, permissions, outages, association."""

import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import session_scope
from app.ingestion.watcher import FolderUnavailable, FolderWatcher
from app.models import Document, IngestRecord, WatcherStatus
from app.settings_store import get_setting, put_setting
from tests import synthetic as syn
from tests.conftest import new_registration, today


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def folder():
    root = get_settings().allowed_watch_roots[0] / "entrada"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    with session_scope() as db:
        cfg = get_setting(db, "watcher")
        cfg.update(enabled=True, folder=str(root), stable_seconds=5)
        put_setting(db, "watcher", cfg, None)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def watcher():
    clock = Clock()
    queued = []
    w = FolderWatcher(clock=clock, enqueue=queued.append)
    w.clock_ref, w.queued = clock, queued
    return w


def scan(w):
    with session_scope() as db:
        return w.scan_once(db)


def settle(w):
    """First pass sees the file, second pass (after the stability window) takes it."""
    first = scan(w)
    w.clock_ref.advance(6)
    return first, scan(w)


def _rg_png(seed=60):
    p = syn.person(seed)
    return p, syn.rg(p.name, p.cpf, p.rg, p.birth, today() - timedelta(days=30)).png()


def test_file_is_taken_only_after_it_stops_changing(folder, watcher):
    _, data = _rg_png()
    (folder / "rg.png").write_bytes(data)
    s1 = scan(watcher)
    assert s1["waiting"] == 1 and s1["ingested"] == 0
    watcher.clock_ref.advance(2)
    assert scan(watcher)["ingested"] == 0  # still inside the stability window
    watcher.clock_ref.advance(4)
    assert scan(watcher)["ingested"] == 1
    assert len(watcher.queued) == 1
    assert not (folder / "rg.png").exists()
    assert list((folder / "_processados").rglob("rg.png"))


def test_partial_copy_waits_until_complete(folder, watcher):
    pdf = syn.cartao_cnpj_pdf(syn.make_cnpj(3), "EMPRESA X LTDA", "ATIVA", today())
    target = folder / "cartao.pdf"
    target.write_bytes(pdf[: len(pdf) // 2])  # copy in progress
    first, second = settle(watcher)
    assert second["ingested"] == 0 and second["waiting"] == 1
    target.write_bytes(pdf)  # copy finished
    first, second = settle(watcher)
    assert second["ingested"] == 1


def test_temporary_and_hidden_files_are_ignored(folder, watcher):
    _, data = _rg_png()
    for name in ("~$rascunho.png", "download.crdownload", ".oculto.png", "copia.tmp"):
        (folder / name).write_bytes(data)
    _, second = settle(watcher)
    assert second["seen"] == 0


def test_same_content_is_never_ingested_twice(folder, watcher):
    _, data = _rg_png()
    (folder / "a.png").write_bytes(data)
    settle(watcher)
    (folder / "b-renomeado.png").write_bytes(data)
    _, second = settle(watcher)
    assert second["duplicates"] == 1 and second["ingested"] == 0
    assert list((folder / "_duplicados").glob("b-renomeado.png"))
    with session_scope() as db:
        assert db.query(Document).count() == 1


def test_rejected_files_are_moved_with_a_reason(folder, watcher):
    (folder / "virus.pdf").write_bytes(b"MZ" + b"\x00" * 600)
    _, second = settle(watcher)
    assert second["rejected"] == 1
    reason = folder / "_falhas" / "virus.pdf.motivo.txt"
    assert reason.exists() and "Formato" in reason.read_text(encoding="utf-8")
    with session_scope() as db:
        assert db.query(IngestRecord).filter_by(status="rejected").count() == 1


def test_permission_error_is_recorded_and_not_retried_until_file_changes(folder, watcher):
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    _, data = _rg_png()
    f = folder / "bloqueado.png"
    f.write_bytes(data)
    f.chmod(0)
    _, second = settle(watcher)
    assert second["failed"] == 1
    with session_scope() as db:
        rec = db.query(IngestRecord).filter_by(status="failed").one()
        assert "permissão" in rec.detail
    watcher.clock_ref.advance(10)
    assert scan(watcher)["failed"] == 0  # unchanged file is not hammered
    f.chmod(0o644)
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
    _, second = settle(watcher)
    assert second["ingested"] == 1


def test_unreachable_folder_is_reported_and_recovers(folder, watcher):
    hidden = folder.with_name("entrada-offline")
    folder.rename(hidden)  # the share drops
    with pytest.raises(FolderUnavailable):
        scan(watcher)
    with session_scope() as db:
        st = db.get(WatcherStatus, 1)
        assert st.reachable is False and st.last_error
    hidden.rename(folder)  # the share comes back
    _, data = _rg_png()
    (folder / "rg.png").write_bytes(data)
    settle(watcher)
    with session_scope() as db:
        assert db.get(WatcherStatus, 1).reachable is True
        assert db.query(Document).count() == 1


def test_association_by_code_in_folder_or_filename(client, analyst, folder, watcher):
    p, data = _rg_png(61)
    reg = new_registration(client, analyst, p.name, p.cpf)
    sub = folder / reg["code"]
    sub.mkdir()
    (sub / "rg.png").write_bytes(data)
    p2, data2 = _rg_png(62)
    reg2 = new_registration(client, analyst, p2.name, p2.cpf)
    (folder / f"{reg2['code']}_rg.png").write_bytes(data2)
    p3, data3 = _rg_png(63)
    (folder / "sem-codigo.png").write_bytes(data3)
    settle(watcher)
    with session_scope() as db:
        docs = {d.original_filename + str(d.registration_id): d for d in db.query(Document).all()}
        by_reg = {str(d.registration_id): d for d in docs.values()}
        assert reg["id"] in by_reg and reg2["id"] in by_reg
        assert any(d.registration_id is None for d in docs.values())
        note = db.query(IngestRecord).filter(IngestRecord.source_ref == "sem-codigo.png").one().detail
        assert "associação manual" in note


def test_unassigned_document_shows_in_inbox_with_suggestion(client, analyst, folder, watcher):
    p, data = _rg_png(64)
    reg = new_registration(client, analyst, p.name, p.cpf)
    (folder / "scan0001.png").write_bytes(data)
    settle(watcher)
    from app.worker import execute

    for doc_id in watcher.queued:
        execute(doc_id, can_retry=False)
    inbox = client.get("/api/inbox", headers=analyst).json()
    item = inbox["documents"][0]
    assert item["suggested_registration"]["id"] == reg["id"]
    r = client.post(f"/api/documents/{item['id']}/associate", json={"registration_id": reg["id"]}, headers=analyst)
    assert r.status_code == 200
    assert client.get("/api/inbox", headers=analyst).json()["documents"] == []


def test_disabled_watcher_does_nothing(folder, watcher):
    with session_scope() as db:
        cfg = get_setting(db, "watcher")
        cfg["enabled"] = False
        put_setting(db, "watcher", cfg, None)
    _, data = _rg_png()
    (folder / "rg.png").write_bytes(data)
    _, second = settle(watcher)
    assert second["seen"] == 0 and Path(folder / "rg.png").exists()
