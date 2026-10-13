"""Authentication, authorization on the backend, session revocation, rate limiting, upload screening."""

import io
from datetime import timedelta

import fitz
from PIL import Image

from tests import synthetic as syn
from tests.conftest import PASSWORD, login, make_user, new_registration, today, upload


def test_requests_without_session_are_refused(client):
    for path in ("/api/registrations", "/api/dashboard", "/api/queue", "/api/audit", "/api/settings", "/api/inbox"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"


def test_forged_token_is_refused(client):
    import jwt

    token = jwt.encode({"sub": "00000000-0000-0000-0000-000000000000", "sid": "00000000-0000-0000-0000-000000000000",
                        "exp": 4102444800, "iss": "cadastro-ai"}, "another-secret-" + "y" * 40, algorithm="HS256")
    assert client.get("/api/registrations", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_wrong_password_is_generic_and_audited(client, admin):
    email = make_user("analyst")
    r = client.post("/api/auth/login", json={"email": email, "password": "errada"})
    assert r.status_code == 401 and r.json()["error"]["message"] == "E-mail ou senha incorretos."
    r2 = client.post("/api/auth/login", json={"email": "ninguem@teste.local", "password": "errada"})
    assert r2.json() == r.json()
    events = client.get("/api/audit", params={"action": "auth.login_failed"}, headers=admin).json()
    assert events["total"] == 2


def test_login_is_rate_limited(client):
    email = make_user("analyst")
    codes = [client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code for _ in range(10)]
    assert codes[-1] == 429


def test_roles_are_enforced_by_the_backend(client, analyst, auditor):
    reg = new_registration(client, analyst)
    # auditors read but never change anything
    assert client.get(f"/api/registrations/{reg['id']}", headers=auditor).status_code == 200
    assert client.post("/api/registrations", json={"kind": "PF", "subject_name": "TESTE"}, headers=auditor).status_code == 403
    assert upload(client, auditor, reg["id"], "a.png", b"x").status_code == 403
    # analysts cannot approve, reject, change settings, manage users or read the full audit log
    assert client.post(f"/api/registrations/{reg['id']}/decisions", json={"action": "approve"}, headers=analyst).status_code == 403
    assert client.post(f"/api/registrations/{reg['id']}/decisions", json={"action": "reject", "reason": "motivo suficiente"}, headers=analyst).status_code == 403
    assert client.put("/api/settings/processing", json={}, headers=analyst).status_code == 403
    assert client.get("/api/users", headers=analyst).status_code == 403
    assert client.get("/api/audit", headers=analyst).status_code == 403


def test_deactivating_an_employee_revokes_sessions_immediately(client, admin):
    email = make_user("analyst")
    h = login(client, email)
    assert client.get("/api/registrations", headers=h).status_code == 200
    users = client.get("/api/users", headers=admin).json()["items"]
    uid = next(u["id"] for u in users if u["email"] == email)
    assert client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.get("/api/registrations", headers=h).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_logout_revokes_the_session(client):
    h = login(client, make_user("analyst"))
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_document_access_is_logged(client, analyst, admin):
    p = syn.person(30)
    reg = new_registration(client, analyst, p.name)
    doc_id = upload(client, analyst, reg["id"], "rg.png", syn.rg(p.name, p.cpf, p.rg, p.birth, today()).png()).json()["results"][0]["document"]["id"]
    client.get(f"/api/documents/{doc_id}/pages/0", headers=analyst)
    client.get(f"/api/documents/{doc_id}/file", headers=analyst)
    actions = {e["action"] for e in client.get("/api/audit", params={"registration_id": reg["id"]}, headers=admin).json()["items"]}
    assert {"document.viewed", "document.downloaded", "document.ingested", "document.processed"} <= actions


def test_unsupported_and_disguised_files_are_rejected(client, analyst):
    reg = new_registration(client, analyst)
    gif = b"GIF89a" + b"\x00" * 400
    r = upload(client, analyst, reg["id"], "foto.gif", gif)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_type"
    exe = b"MZ\x90\x00" + b"\x00" * 500
    r = upload(client, analyst, reg["id"], "documento.pdf", exe)
    assert r.json()["error"]["code"] == "unsupported_type"
    png = syn.rg("A", syn.make_cpf(1), "1", today(), today()).png()
    r = upload(client, analyst, reg["id"], "documento.pdf", png)
    assert r.json()["error"]["code"] == "type_mismatch"


def test_corrupted_and_truncated_files_are_rejected(client, analyst):
    reg = new_registration(client, analyst)
    pdf = syn.cartao_cnpj_pdf(syn.make_cnpj(1), "X LTDA", "ATIVA", today())
    r = upload(client, analyst, reg["id"], "cortado.pdf", pdf[: len(pdf) // 3])
    assert r.status_code == 422 and r.json()["error"]["code"] == "corrupted"
    jpeg = syn.rg("A", syn.make_cpf(1), "1", today(), today()).jpeg()
    r = upload(client, analyst, reg["id"], "cortado.jpg", jpeg[:2000])
    assert r.json()["error"]["code"] == "corrupted"
    r = upload(client, analyst, reg["id"], "vazio.png", b"")
    assert r.json()["error"]["code"] in ("empty_file", "unsupported_type")


def test_pdf_with_active_content_is_rejected(client, analyst):
    reg = new_registration(client, analyst)
    doc = fitz.open()
    doc.new_page()
    doc.set_metadata({})
    xref = doc.get_new_xref()
    doc.update_object(xref, "<< /Type /Action /S /JavaScript /JS (app.alert('x')) >>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    data = doc.tobytes()
    r = upload(client, analyst, reg["id"], "macro.pdf", data)
    assert r.status_code == 422 and r.json()["error"]["code"] == "active_content"


def test_tiny_images_are_rejected(client, analyst):
    reg = new_registration(client, analyst)
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "PNG")
    assert upload(client, analyst, reg["id"], "mini.png", buf.getvalue()).json()["error"]["code"] == "too_small"


def test_multi_file_upload_reports_each_file(client, analyst):
    p = syn.person(31)
    reg = new_registration(client, analyst, p.name)
    files = [
        ("files", ("rg.png", syn.rg(p.name, p.cpf, p.rg, p.birth, today() - timedelta(days=10)).png(), "image/png")),
        ("files", ("ruim.gif", b"GIF89a" + b"\x00" * 300, "image/gif")),
    ]
    r = client.post(f"/api/registrations/{reg['id']}/documents", files=files, headers=analyst)
    assert r.status_code == 201
    res = r.json()["results"]
    assert res[0]["ok"] and not res[1]["ok"] and res[1]["error"]["code"] == "unsupported_type"


def test_duplicate_upload_in_same_registration_is_refused(client, analyst):
    p = syn.person(32)
    reg = new_registration(client, analyst, p.name)
    data = syn.rg(p.name, p.cpf, p.rg, p.birth, today()).png()
    assert upload(client, analyst, reg["id"], "rg.png", data).status_code == 201
    r = upload(client, analyst, reg["id"], "rg-copia.png", data)
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate"


def test_settings_cannot_point_watcher_outside_allowed_roots(client, admin):
    cfg = client.get("/api/settings", headers=admin).json()["settings"]["watcher"]
    cfg["folder"] = "/etc"
    r = client.put("/api/settings/watcher", json=cfg, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_folder"


def test_settings_do_not_expose_secrets(client, admin):
    body = client.get("/api/settings", headers=admin).text
    from app.config import get_settings

    s = get_settings()
    assert s.jwt_secret not in body and s.storage_encryption_key not in body


def test_ai_cannot_be_enabled_without_a_server_side_provider(client, admin):
    cfg = client.get("/api/settings", headers=admin).json()["settings"]["processing"]
    cfg["ai_enabled"] = True
    r = client.put("/api/settings/processing", json=cfg, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ai_not_configured"
