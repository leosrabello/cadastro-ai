"""Modalities (Normal and One7), import of the previous dashboard's backup, portfolio indicators and
signature tracking. The backup below has the same structure as the real export (version 2), with
invented names."""

import json
from datetime import date, timedelta
from pathlib import Path

from app.db import session_scope
from app.models import DataImport, PortfolioClient, Registration, SignatureTracking
from tests.conftest import new_registration

TODAY = date.today()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def ts(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat() + "T12:00:00.000Z"


def normal(cid, nome, comercial, status, entrada, history, **kw):
    base = {
        "id": cid, "nome": nome, "comercial": comercial, "status": status, "dataEntrada": entrada,
        "dataPreComite": "", "dataComite": "", "dataEmissaoContrato": "", "dataConclusaoAssinatura": "",
        "cobrancasAssinatura": [], "observacoes": "", "formalizacao": {"cadastro": False, "homologado": False},
        "contratos": {"emissao": False, "processo": False, "assinado": False}, "anexos": [], "cobrancas": [],
        "saidaRisco": False, "limiteVencido": False,
        "historico": [{"data": history[0]["at"], "usuario": "Analista", "texto": "Cadastro criado"}],
        "statusHistory": history, "createdAt": history[0]["at"],
    }
    base.update(kw)
    return base


def backup() -> dict:
    return {
        "version": 2,
        "exportedAt": ts(0),
        "clients": [
            # approved: 20 days from entry (d40) to apto (d20)
            normal("c_a", "ALFA INDUSTRIA", "Gabriel", "apto_operar", d(40),
                   [{"status": "pasta_nova", "at": ts(40)}, {"status": "aguardando_comite", "at": ts(30)}, {"status": "apto_operar", "at": ts(20)}],
                   dataComite=d(30), formalizacao={"cadastro": True, "homologado": True}),
            normal("c_b", "BETA LOGÍSTICA", "Gabriel", "negada", d(35), [{"status": "pasta_nova", "at": ts(35)}, {"status": "negada", "at": ts(33)}]),
            # stalled for 12 days in the same status: atrasado
            normal("c_c", "GAMA PEÇAS", "João Torezin", "aguardando_documentacao", d(15), [{"status": "aguardando_documentacao", "at": ts(12)}],
                   saidaRisco=True, cobrancas=[{"data": d(5), "retorno": "Cobrei o balancete"}]),
            normal("c_d", "DELTA TRANSPORTES", "Vittra", "custom_1", d(3), [{"status": "custom_1", "at": ts(2)}], limiteVencido=True),
            normal("c_e", "ÉPSILON METAIS", "", "aguardando_assinatura", d(10), [{"status": "aguardando_assinatura", "at": ts(1)}]),
            # same name as c_b: kept, with a warning
            normal("c_f", "BETA LOGISTICA", "gabriel", "pasta_nova", d(2), [{"status": "pasta_nova", "at": ts(2)}]),
            # invalid: bad date, unknown status, repeated id
            normal("c_bad1", "ZETA", "Gabriel", "pasta_nova", "31/02/2026", [{"status": "pasta_nova", "at": ts(1)}]),
            normal("c_bad2", "ETA", "Gabriel", "status_que_nao_existe", d(1), [{"status": "pasta_nova", "at": ts(1)}]),
            normal("c_a", "ALFA REPETIDA", "Gabriel", "pasta_nova", d(1), [{"status": "pasta_nova", "at": ts(1)}]),
        ],
        "one7Clients": [
            {"id": "o_1", "nome": "TETA FILTROS", "comercial": "Moacir", "status": "ag_comite", "dataCadastroONE7": d(20),
             "dataComiteInterno": "", "dataEnvioComite": d(5), "dataComiteONE7": "", "observacoes": "",
             "formalizacao": {"analiseComite": False, "aprovacaoSistema": False}, "cadastro": {"cadastroFormalizacao": False},
             "resultadoComite": "em_analise", "cobrancas": [], "tipoAnalise": "tombamento", "noBloco": True,
             "statusHistory": [{"status": "ag_comite", "at": ts(20)}], "createdAt": ts(20)},
            {"id": "o_2", "nome": "IOTA SANTOS", "comercial": "Gabriel", "status": "apto_operar", "dataCadastroONE7": d(30),
             "dataComiteInterno": "", "dataEnvioComite": d(15), "dataComiteONE7": d(10), "observacoes": "",
             "formalizacao": {"analiseComite": True, "aprovacaoSistema": True}, "cadastro": {"cadastroFormalizacao": True},
             "resultadoComite": "aprovado", "cobrancas": [], "tipoAnalise": "analise_completa", "noBloco": False,
             "statusHistory": [{"status": "apto_operar", "at": ts(10)}], "createdAt": ts(30)},
            # not registered at ONE7 yet: imported as incomplete, not rejected
            {"id": "o_3", "nome": "SIGMA CORREIAS", "comercial": "Ellen", "status": "ag_documentos", "dataCadastroONE7": "",
             "dataComiteInterno": "", "dataEnvioComite": "", "dataComiteONE7": "", "observacoes": "", "resultadoComite": "em_analise",
             "statusHistory": [{"status": "ag_documentos", "at": ts(3)}], "createdAt": ts(3), "tipoAnalise": "", "noBloco": False},
        ],
        "assinaturas": [
            {"id": "s_1", "clientId": "c_a", "empresa": "ALFA INDUSTRIA", "comercial": "Gabriel",
             "contratoSEC": {"numeroProcesso": "", "dataCriacao": "", "dataEmissao": d(25), "dataAssinatura": d(21)},
             "contratoFIDC": {"numeroProcesso": "", "dataCriacao": "", "dataEmissao": d(25), "dataAssinatura": d(19)},
             "cobrancas": [], "createdAt": ts(25)},
            # no clientId: linked by the unique name
            {"id": "s_2", "empresa": "Épsilon Metais", "comercial": "",
             "contratoSEC": {"numeroProcesso": "", "dataCriacao": "", "dataEmissao": d(6), "dataAssinatura": ""},
             "contratoFIDC": {"numeroProcesso": "", "dataCriacao": "", "dataEmissao": "", "dataAssinatura": ""},
             "cobrancas": [{"data": d(2), "retorno": "Reenviei o link"}], "createdAt": ts(6)},
            # invalid: signed before emission
            {"id": "s_3", "empresa": "KAPPA", "comercial": "Vittra",
             "contratoSEC": {"numeroProcesso": "", "dataCriacao": "", "dataEmissao": d(3), "dataAssinatura": d(9)},
             "contratoFIDC": {"numeroProcesso": "", "dataCriacao": "", "dataEmissao": "", "dataAssinatura": ""},
             "cobrancas": [], "createdAt": ts(9)},
        ],
        "customStatuses": [{"key": "custom_1", "label": "Stand By", "color": "#F97316", "bg": "#FEEDDE"}],
        "statusLabels": {"pasta_nova": "Pasta Nova", "custom_1": "Stand By", "reanalise": "Reanálise de limite"},
    }


def as_file(doc: dict, name="backup_cadastros.json"):
    return [("file", (name, json.dumps(doc, ensure_ascii=False).encode(), "application/json"))]


def preview(client, h, doc):
    r = client.post("/api/portfolio/import/preview", files=as_file(doc), headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def do_import(client, h, doc):
    p = preview(client, h, doc)
    r = client.post("/api/portfolio/import", files=as_file(doc), data={"sha256": p["file"]["sha256"]}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def count(model) -> int:
    with session_scope() as db:
        return db.query(model).count()


# ------------------------------------------------------------------ import

def test_preview_validates_and_writes_nothing(client, supervisor):
    p = preview(client, supervisor, backup())
    assert p["clients"] == {"create": 9, "update": 0, "unchanged": 0, "skipped": 0, "rejected": 3}
    assert p["signatures"] == {"create": 2, "update": 0, "unchanged": 0, "skipped": 0, "rejected": 1}
    msgs = [i["message"] for i in p["issues"]]
    assert any("dataEntrada: data inválida" in m for m in msgs)
    assert any("status desconhecido" in m for m in msgs)
    assert any("Id repetido" in m for m in msgs)
    assert any("Mesmo nome de outro registro" in m for m in msgs)
    assert any("assinatura anterior à emissão" in m for m in msgs)
    assert any(m.startswith("Incompleto: sem dataCadastroONE7") for m in msgs)
    assert any("vinculado ao cliente de mesmo nome" in m for m in msgs)
    # "gabriel" and "Gabriel" are the same commercial
    assert p["commercials"]["names"] == ["Ellen", "Gabriel", "João Torezin", "Moacir", "Vittra"]
    assert p["statuses"]["added"] == [{"key": "custom_1", "label": "Stand By"}]
    assert {"key": "reanalise", "from": "Reanálise", "to": "Reanálise de limite"} in p["statuses"]["relabeled"]
    assert count(PortfolioClient) == 0 and count(SignatureTracking) == 0 and count(DataImport) == 0


def test_import_then_reimport_never_duplicates(client, supervisor):
    res = do_import(client, supervisor, backup())
    assert res["clients"]["create"] == 9 and res["signatures"]["create"] == 2
    assert count(PortfolioClient) == 9 and count(SignatureTracking) == 2

    again = do_import(client, supervisor, backup())
    assert again["clients"] == {"create": 0, "update": 0, "unchanged": 9, "skipped": 0, "rejected": 3}
    assert again["signatures"]["unchanged"] == 2
    assert again["file"]["previously_imported_at"]
    assert count(PortfolioClient) == 9 and count(SignatureTracking) == 2 and count(DataImport) == 2

    with session_scope() as db:
        e = db.query(PortfolioClient).filter_by(external_id="c_e").one()
        s2 = db.query(SignatureTracking).filter_by(external_id="s_2").one()
        assert s2.client_id == e.id and e.commercial_id is None
        one7 = db.query(PortfolioClient).filter_by(external_id="o_1").one()
        assert one7.modality == "one7" and one7.extra["tipo_analise"] == "tombamento" and one7.extra["em_triagem"] is True
        assert db.query(Registration).count() == 0  # importing the portfolio never creates registrations


def test_reimport_updates_imported_records_but_keeps_edits_made_here(client, supervisor):
    do_import(client, supervisor, backup())
    with session_scope() as db:
        ids = {c.external_id: str(c.id) for c in db.query(PortfolioClient)}
    r = client.patch(f"/api/portfolio/clients/{ids['c_c']}", json={"notes": "Atualizado no CadastroAI"}, headers=supervisor)
    assert r.status_code == 200, r.text

    newer = backup()
    newer["clients"][2]["observacoes"] = "Texto antigo do painel"  # c_c, edited here: must be kept
    newer["clients"][3]["observacoes"] = "Mudou no painel"  # c_d, untouched here: updated
    res = do_import(client, supervisor, newer)
    assert res["clients"]["update"] == 1 and res["clients"]["skipped"] == 1
    with session_scope() as db:
        assert db.query(PortfolioClient).filter_by(external_id="c_c").one().notes == "Atualizado no CadastroAI"
        assert db.query(PortfolioClient).filter_by(external_id="c_d").one().notes == "Mudou no painel"


def test_invalid_files_are_refused_with_a_clear_message(client, supervisor):
    for content, expected in [
        (b"isto nao e json", "não é um JSON válido"),
        (b"[]", "deve ser um objeto"),
        (b'{"version": 2}', "falta a lista"),
        (b'{"version": 9, "clients": []}', "Versão de backup não suportada"),
        (b'{"clients": [], "assinaturas": {}}', "deve ser uma lista"),
    ]:
        r = client.post("/api/portfolio/import/preview", files=[("file", ("x.json", content, "application/json"))], headers=supervisor)
        assert r.status_code == 422 and expected in r.json()["error"]["message"], (content, r.text)
    assert count(DataImport) == 0


def test_import_requires_the_previewed_file_and_a_supervisor(client, supervisor, analyst):
    doc = backup()
    r = client.post("/api/portfolio/import/preview", files=as_file(doc), headers=analyst)
    assert r.status_code == 403
    r = client.post("/api/portfolio/import", files=as_file(doc), data={"sha256": "0" * 64}, headers=supervisor)
    assert r.status_code == 409
    assert count(PortfolioClient) == 0


# ------------------------------------------------------------------ modalities on registrations

def test_registration_requires_and_keeps_its_modality(client, analyst):
    r = client.post("/api/registrations", json={"kind": "PF", "subject_name": "MARIA DA SILVA"}, headers=analyst)
    assert r.status_code == 422
    r = client.post("/api/registrations", json={"kind": "PF", "subject_name": "MARIA DA SILVA", "modality": "outra"}, headers=analyst)
    assert r.status_code == 422

    n = new_registration(client, analyst, "MARIA DA SILVA", modality="normal")
    o = new_registration(client, analyst, "JOAO DE SOUZA", modality="one7")
    assert n["modality"] == "normal" and o["modality"] == "one7"
    assert client.get(f"/api/registrations/{o['id']}", headers=analyst).json()["modality"] == "one7"

    only = client.get("/api/registrations?modality=one7", headers=analyst).json()
    assert [x["code"] for x in only["items"]] == [o["code"]]
    assert client.get("/api/dashboard?modality=one7", headers=analyst).json()["counts"]["awaiting_review"] == 0
    total = client.get("/api/dashboard", headers=analyst).json()["counts"]
    by_mod = [client.get(f"/api/dashboard?modality={m}", headers=analyst).json()["counts"] for m in ("normal", "one7")]
    for k in ("awaiting_processing", "awaiting_review", "missing_documents", "pending_documents"):
        assert total[k] == by_mod[0][k] + by_mod[1][k], k

    r = client.patch(f"/api/registrations/{n['id']}", json={"modality": "one7"}, headers=analyst)
    assert r.status_code == 200 and r.json()["modality"] == "one7"


def test_registration_links_to_a_client_of_the_same_modality(client, supervisor):
    do_import(client, supervisor, backup())
    with session_scope() as db:
        alfa = str(db.query(PortfolioClient).filter_by(external_id="c_a").one().id)
    r = client.post("/api/registrations", json={"kind": "PJ", "subject_name": "ALFA INDUSTRIA", "modality": "one7", "client_id": alfa}, headers=supervisor)
    assert r.status_code == 422 and r.json()["error"]["code"] == "modality_mismatch"
    reg = new_registration(client, supervisor, "ALFA INDUSTRIA", kind="PJ", modality="normal", client_id=alfa)
    assert reg["client"]["name"] == "ALFA INDUSTRIA" and reg["client"]["commercial"] == "Gabriel"
    rep = client.get(f"/api/registrations/{reg['id']}/report", headers=supervisor).json()
    assert rep["registration"]["modality_label"] == "Normal" and rep["analysis"]["comercial"] == "Gabriel"


def test_existing_registrations_without_modality_become_normal():
    """Migration 0002 adds the column with server_default 'normal'; a row inserted without it gets Normal."""
    from sqlalchemy import text
    from app.db import engine

    with engine().begin() as c:
        c.execute(text("INSERT INTO registrations (id, code, kind, subject_name, reference_fields, status, priority_score, priority_reasons, checklist, "
                       "ready_for_decision, created_at, updated_at, legal_hold) VALUES (gen_random_uuid(), 'CAD-LEGADO', 'PF', 'LEGADO', '{}', "
                       "'awaiting_review', 0, '[]', '{}', false, now(), now(), false)"))
        assert c.execute(text("SELECT modality FROM registrations WHERE code='CAD-LEGADO'")).scalar_one() == "normal"


# ------------------------------------------------------------------ indicators

def test_summary_indicators_follow_the_reference_rules(client, supervisor):
    do_import(client, supervisor, backup())
    s = client.get("/api/portfolio/summary?modality=normal&rows=true", headers=supervisor).json()
    k = s["kpis"]
    assert k["total_clients"] == 6
    assert (k["approved"], k["denied"]) == (1, 1) and k["approval_rate"] == 0.5
    assert k["avg_days_to_approved"] == 20.0
    assert k["risk_exit"] == 1 and k["limit_expired"] == 1
    assert k["overdue"] == 1  # GAMA PEÇAS, 12 days in the same status (SLA 7)
    assert k["top_commercial"] == {"name": "Gabriel", "total": 3}
    gab = next(c for c in s["by_commercial"] if c["name"] == "Gabriel")
    assert (gab["approved"], gab["denied"], gab["in_progress"], gab["approval_rate"]) == (1, 1, 1, 0.5)
    assert next(c for c in s["by_commercial"] if c["id"] is None)["total"] == 1  # Épsilon has no commercial
    assert [x["name"] for x in s["over_sla"]] == ["GAMA PEÇAS"]
    assert {x["key"]: x["count"] for x in s["by_status"]}["custom_1"] == 1
    # signatures: SEC 4 days, FIDC 6 days -> 5; Épsilon SEC waiting 6 days
    assert s["signatures"]["avg_signature_days"] == 5.0
    assert (s["signatures"]["avg_signature_days_sec"], s["signatures"]["avg_signature_days_fidc"]) == (4.0, 6.0)
    assert s["signatures"]["in_process"] == 1 and s["signatures"]["oldest_open_days"] == 6
    alfa = next(r for r in s["rows"] if r["name"] == "ALFA INDUSTRIA")
    assert alfa["situation"] == "concluido" and alfa["total_days"] == 20 and alfa["signature_days"] == 6

    one7 = client.get("/api/portfolio/summary?modality=one7", headers=supervisor).json()["kpis"]
    assert one7["total_clients"] == 3 and one7["approved"] == 1 and one7["avg_days_to_approved"] == 20.0
    both = client.get("/api/portfolio/summary?modality=all", headers=supervisor).json()
    assert both["kpis"]["total_clients"] == 9 and both["modality_label"].startswith("Consolidado")

    f = client.get("/api/portfolio/summary?modality=normal&situation=atrasado", headers=supervisor).json()
    assert f["filtered"] and f["kpis"]["total_clients"] == 1 and f["population"] == 6


# ------------------------------------------------------------------ clients and signatures

def test_reaching_awaiting_signature_opens_the_contracts(client, analyst):
    statuses = client.get("/api/portfolio/catalog", headers=analyst).json()["statuses"]["normal"]
    assert any(s.get("opens_signature") for s in statuses)
    r = client.post("/api/portfolio/clients", json={"modality": "normal", "name": "lambda alimentos", "status": "aguardando_comite", "entry_date": d(5)}, headers=analyst)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["name"] == "LAMBDA ALIMENTOS"
    assert client.get("/api/signatures", headers=analyst).json()["items"] == []
    r = client.patch(f"/api/portfolio/clients/{cid}", json={"status": "aguardando_assinatura"}, headers=analyst)
    assert r.status_code == 200 and [h["status"] for h in r.json()["status_history"]] == ["aguardando_comite", "aguardando_assinatura"]
    items = client.get("/api/signatures", headers=analyst).json()["items"]
    assert len(items) == 1 and items[0]["client"]["id"] == cid and items[0]["auto_created"] and items[0]["state"] == "sem_emissao"
    # leaving the status does not remove it; returning does not duplicate it
    client.patch(f"/api/portfolio/clients/{cid}", json={"status": "aguardando_comite"}, headers=analyst)
    client.patch(f"/api/portfolio/clients/{cid}", json={"status": "aguardando_assinatura"}, headers=analyst)
    assert len(client.get("/api/signatures", headers=analyst).json()["items"]) == 1
    r = client.patch(f"/api/portfolio/clients/{cid}", json={"status": "ag_comite"}, headers=analyst)
    assert r.status_code == 422  # One7 status on a Normal client


def test_signature_check_states_kpis_and_validation(client, analyst, supervisor):
    r = client.post("/api/signatures", json={"company_name": "mu comercio"}, headers=analyst)
    assert r.status_code == 201
    sid = r.json()["id"]
    r = client.patch(f"/api/signatures/{sid}", json={"contracts": {"SEC": {"signed_date": d(1)}}}, headers=analyst)
    assert r.status_code == 422  # signature without emission
    r = client.patch(f"/api/signatures/{sid}", json={"contracts": {"SEC": {"issued_date": d(3), "signed_date": d(5)}}}, headers=analyst)
    assert r.status_code == 422  # signature before emission
    r = client.patch(f"/api/signatures/{sid}", json={"contracts": {"SEC": {"issued_date": d(10), "signed_date": d(3)}, "FIDC": {"issued_date": d(8), "process_number": "PROC-77"}}}, headers=analyst)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["state"] == "aguardando" and row["waiting_days"] == 8
    sec, fidc = row["contracts"]
    assert (sec["kind"], sec["state"], sec["days"]) == ("SEC", "assinado", 7)
    assert (fidc["state"], fidc["process_number"]) == ("aguardando", "PROC-77")
    r = client.patch(f"/api/signatures/{sid}", json={"contracts": {"FIDC": {"signed_date": d(2)}}, "followups": [{"date": d(4), "note": "Cobrei o cliente"}]}, headers=analyst)
    assert r.json()["state"] == "assinado" and len(r.json()["followups"]) == 1
    lst = client.get("/api/signatures?state=assinado", headers=analyst).json()
    assert lst["kpis"]["avg_signature_days"] == 6.5 and lst["kpis"]["signed"] == 2 and lst["kpis"]["followups"] == 1
    assert client.delete(f"/api/signatures/{sid}", headers=analyst).status_code == 204  # analysts remove contracts too
    assert client.get("/api/signatures", headers=analyst).json()["items"] == []


def test_commercials_are_unique_by_name(client, analyst, supervisor):
    assert client.post("/api/portfolio/commercials", json={"name": "Ana Paula"}, headers=analyst).status_code == 201
    assert client.post("/api/portfolio/commercials", json={"name": "ana  paula"}, headers=analyst).status_code == 409
    com = client.get("/api/portfolio/commercials", headers=analyst).json()["items"][0]
    assert client.patch(f"/api/portfolio/commercials/{com['id']}", json={"is_active": False}, headers=analyst).status_code == 403
    r = client.patch(f"/api/portfolio/commercials/{com['id']}", json={"name": "Ana Paula Souza", "is_active": False}, headers=supervisor)
    assert r.json() == {"id": com["id"], "name": "Ana Paula Souza", "is_active": False}


def test_merging_two_spellings_of_a_commercial_survives_reimport(client, supervisor, analyst):
    doc = backup()
    doc["assinaturas"][0]["comercial"] = "Vitra Connect"  # ALFA's contracts under another spelling of Vittra
    doc["clients"][0]["comercial"] = "Vitra Connect"
    do_import(client, supervisor, doc)
    coms = {c["name"]: c for c in client.get("/api/portfolio/commercials", headers=supervisor).json()["items"]}
    src, dst = coms["Vitra Connect"], coms["Vittra"]
    assert (src["clients"], dst["clients"]) == (1, 1)

    assert client.post(f"/api/portfolio/commercials/{src['id']}/merge", json={"into_id": dst["id"]}, headers=analyst).status_code == 403
    r = client.post(f"/api/portfolio/commercials/{src['id']}/merge", json={"into_id": dst["id"]}, headers=supervisor)
    assert r.status_code == 200 and r.json()["clients_moved"] == 1 and r.json()["signatures_moved"] == 1
    coms = {c["name"]: c for c in client.get("/api/portfolio/commercials", headers=supervisor).json()["items"]}
    assert "Vitra Connect" not in coms and coms["Vittra"]["clients"] == 2

    # the old spelling now resolves to Vittra: nothing new, nothing changed, nothing skipped
    again = do_import(client, supervisor, doc)
    assert again["commercials"]["create"] == 0
    assert again["clients"]["unchanged"] == 9 and again["clients"]["skipped"] == 0
    assert again["signatures"]["unchanged"] == 2
    assert client.post("/api/portfolio/commercials", json={"name": "vitra connect"}, headers=analyst).status_code == 409


# ------------------------------------------------------------------ no fictitious data at startup

def test_startup_inserts_no_clients_or_registrations(client):
    with session_scope() as db:
        assert db.query(Registration).count() == 0
        assert db.query(PortfolioClient).count() == 0
        assert db.query(SignatureTracking).count() == 0


def test_demo_seed_scripts_are_gone():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    assert not (scripts / "seed_demo.py").exists() and not (scripts / "seed_company_demo.py").exists()

