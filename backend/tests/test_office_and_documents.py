"""Word and Excel uploads, long PDFs, scanner metadata, clause readings of the articles of
association, and analysts deleting documents."""

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path

import fitz
import pytest

from app.db import session_scope
from app.models import Document
from app.pipeline.rendering import clean_text
from tests.conftest import new_registration, upload

CONTRACT = [
    "NONA ALTERAÇÃO E CONSOLIDAÇÃO DO CONTRATO SOCIAL DA WEMOOV TECNOLOGIA LTDA",
    "CNPJ 11.222.333/0001-81",
    "Sócio: DIVALDO GARCIA PINTO, brasileiro, casado, empresário.",
    "Sócio: PEDRO HENRIQUE JORGE GARCIA, brasileiro, solteiro, administrador.",
    "CLÁUSULA SEXTA. A administração da sociedade caberá aos sócios DIVALDO GARCIA PINTO e PEDRO HENRIQUE JORGE GARCIA, "
    "com os poderes e atribuições de representação ativa e passiva e uso do nome empresarial, sempre em conjunto.",
    "CLÁUSULA SÉTIMA. Os sócios resolvem consolidar o contrato social, que passa a vigorar com a seguinte redação.",
]


def docx(paragraphs: list[str], macro: bool = False) -> bytes:
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")
        if macro:
            z.writestr("word/vbaProject.bin", b"\x00" * 64)
    return buf.getvalue()


def xlsx_from_csv(rows: list[str]) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "faturamento.csv"
        src.write_text("\n".join(rows), encoding="utf-8")
        subprocess.run(["soffice", "--headless", f"-env:UserInstallation=file://{tmp}/p", "--convert-to", "xlsx", "--outdir", tmp, str(src)],
                       capture_output=True, timeout=120, check=True, env={"HOME": tmp, "PATH": "/usr/bin:/bin"})
        return (Path(tmp) / "faturamento.xlsx").read_bytes()


def _doc(client, h, r):
    assert r.status_code == 201, r.text
    return client.get(f"/api/documents/{r.json()['results'][0]['document']['id']}", headers=h).json()


def test_word_articles_are_read_with_who_signs_and_how(client, analyst):
    reg = new_registration(client, analyst, "WEMOOV TECNOLOGIA LTDA", kind="PJ")
    d = _doc(client, analyst, upload(client, analyst, reg["id"], "contrato.docx", docx(CONTRACT)))
    assert d["status"] == "processed" and d["mime_type"].endswith("wordprocessingml.document")
    assert d["doc_type"] == "contrato_social" and d["page_count"] >= 1
    f = {x["name"]: x for x in d["fields"]}
    assert f["administradores"]["value"] == "DIVALDO GARCIA PINTO; PEDRO HENRIQUE JORGE GARCIA"
    assert f["responsaveis_assinatura"]["value"] == f["administradores"]["value"]
    assert f["forma_assinatura"]["value"] == "Conjunta"
    assert f["consolidado"]["value"] == "Sim"
    assert client.get(f"/api/documents/{d['id']}/pages/0", headers=analyst).headers["content-type"] == "image/png"
    assert client.get(f"/api/documents/{d['id']}/file", headers=analyst).content[:2] == b"PK"  # the original, as received


def test_excel_upload_is_accepted_and_read(client, analyst):
    reg = new_registration(client, analyst, "WEMOOV TECNOLOGIA LTDA", kind="PJ")
    data = xlsx_from_csv(["RELACAO DE FATURAMENTO MENSAL 2025", "MES,2025", "JANEIRO,\"1.234.567,89\"", "FEVEREIRO,\"1.111.111,11\""])
    d = _doc(client, analyst, upload(client, analyst, reg["id"], "faturamento.xlsx", data))
    assert d["status"] == "processed" and d["mime_type"].endswith("spreadsheetml.sheet")
    assert d["doc_type"] == "faturamento"


@pytest.mark.parametrize("name,data,code", [
    ("macro.docx", docx(["texto"], macro=True), "active_content"),
    ("antigo.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "_VBA_PROJECT".encode("utf-16-le") + b"\x00" * 512, "active_content"),
    ("senha.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 512, "encrypted"),
    ("contrato.pdf", docx(CONTRACT), "type_mismatch"),
])
def test_unsafe_or_disguised_office_files_are_refused(client, analyst, name, data, code):
    reg = new_registration(client, analyst)
    r = upload(client, analyst, reg["id"], name, data)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["error"]["code"] == code, r.text


def test_long_contracts_are_accepted(client, analyst):
    pdf = fitz.open()
    for i in range(23):
        page = pdf.new_page()
        page.insert_text((60, 80), f"ALTERACAO CONTRATUAL - PAGINA {i + 1}", fontsize=12)
    reg = new_registration(client, analyst, "WEMOOV TECNOLOGIA LTDA", kind="PJ")
    d = _doc(client, analyst, upload(client, analyst, reg["id"], "9a-alteracao.pdf", pdf.tobytes()))
    assert d["page_count"] == 23 and d["status"] == "processed"
    assert d["job"]["metrics"]["ocr_skipped_text_pages"] == 23  # born-digital pages are not OCR'd again


def test_scanner_metadata_with_stray_bytes_is_stored():
    assert clean_text("Adobe PSL 1.1e for Canon\udcc0\x00") == "Adobe PSL 1.1e for Canon?"


def test_analyst_deletes_a_document_sent_by_mistake(client, analyst, supervisor, admin):
    from tests import synthetic as syn
    from tests.conftest import today

    p = syn.person(61)
    reg = new_registration(client, analyst, p.name, p.cpf)
    d = _doc(client, analyst, upload(client, analyst, reg["id"], "rg.png", syn.rg(p.name, p.cpf, p.rg, p.birth, today()).png()))
    with session_scope() as db:
        key = db.get(Document, d["id"]).storage_key
    assert client.post(f"/api/documents/{d['id']}/delete", json={"reason": "x"}, headers=analyst).status_code == 422
    r = client.post(f"/api/documents/{d['id']}/delete", json={"reason": "Enviado no cadastro errado"}, headers=analyst)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/documents/{d['id']}", headers=analyst).status_code == 404
    with session_scope() as db:
        assert db.get(Document, d["id"]) is None
    from app.storage import get_store
    with pytest.raises(Exception):
        get_store().get(key)
    detail = client.get(f"/api/registrations/{reg['id']}", headers=analyst).json()
    assert detail["documents"] == [] and any(i["state"] == "missing" for i in detail["checklist"]["documents"])
    ev = next(e for e in client.get(f"/api/audit?registration_id={reg['id']}", headers=admin).json()["items"] if e["action"] == "document.deleted")
    assert ev["details"]["reason"] == "Enviado no cadastro errado" and "rg.png" not in str(ev["details"])
