"""The FinTrust 2026 checklist: stages, year-specific financials, alternatives, signatures, readers."""

from datetime import date, timedelta

from app.pipeline import financial as fin
from app.pipeline.normalize import parse_money
from app.pipeline.ocr.base import Line, PageText, Word
from tests import synthetic as syn
from tests.conftest import new_registration, today, upload

Y = date.today().year


def page(*texts):
    return [PageText(0, "pdf_text", [Line(t, [Word(t, 0.99, (0, 0, 1, 1), i)]) for i, t in enumerate(texts)])]


def _state(client, h, rid):
    d = client.get(f"/api/registrations/{rid}", headers=h).json()
    return d, {i["id"]: i for i in d["checklist"]["documents"]}


def _codes(findings):
    return {f["code"] for f in findings if f["status"] in ("open", "escalated")}


def test_money_and_identifiers_are_told_apart():
    assert parse_money("13.088.786,00") == 13088786.0
    assert parse_money("R$ 1.744") == 1744.0
    assert parse_money("-R$ 997.712") == -997712.0
    rows = fin.debt_items(page("CPF 942.228.949-15", "CNPJ 78.827.730/0001-58", "SICOOB    R$ 1.000,00    R$ 687.321,22"))
    assert rows[0] == [{"instituicao": "SICOOB", "limite": 1000.0, "tomado": 687321.22}]


def test_revenue_table_reads_month_lines_under_year_columns():
    t = fin.revenue_table(page("MÊS 2026 2025", "JANEIRO R$ 13.088.786 R$ 7.155.224", "FEVEREIRO R$ 11.381.880 R$ 9.724.128", "TOTAL R$ 24.470.666"))
    assert t == {"years": {"2026": {"1": 13088786.0, "2": 11381880.0}, "2025": {"1": 7155224.0, "2": 9724128.0}}}
    assert fin.last_month(t) == "2026-02"


def test_customer_concentration_largest_first():
    rows = fin.concentration(page("GV DO BRASIL    21,68%", "RECICLATRANS    13,22%", "IRA INTERNATIONAL    7,08%"))
    assert [r["cliente"] for r in rows] == ["GV DO BRASIL", "RECICLATRANS", "IRA INTERNATIONAL"]


def _full_analysis_set(c, fresh=True):
    t = today()
    months_now = {m: 1_000_000 + m * 10_000 for m in range(1, max(2, t.month - 1) + 1)}
    return [
        ("certidao.pdf", syn.certidao_simplificada_pdf(c, t - timedelta(days=10))),
        (f"balanco-{Y-2}.pdf", syn.balanco_pdf(c, Y - 2, 40e6, 1.2e6, 8e6, 30e6)),
        (f"balanco-{Y-1}.pdf", syn.balanco_pdf(c, Y - 1, 48e6, -2.7e6, 6.2e6, 36e6)),
        (f"balancete-{Y}.pdf", syn.balancete_pdf(c, Y, 31e6)),
        (f"faturamento-{Y-2}.pdf", syn.faturamento_pdf(c, Y - 2, {m: 3_000_000 + m * 1000 for m in range(1, 13)})),
        (f"faturamento-{Y-1}.pdf", syn.faturamento_pdf(c, Y - 1, {m: 4_000_000 + m * 1000 for m in range(1, 13)})),
        (f"faturamento-{Y}.pdf", syn.faturamento_pdf(c, Y, months_now if fresh else {1: 1e6, 2: 1e6})),
        ("endividamento.pdf", syn.endividamento_pdf(c, t - timedelta(days=15), [("BANCO DO BRASIL", 5e6, 3_476_001.76), ("SICOOB", 1e6, 687_321.22)])),
        ("curva-abc.pdf", syn.curva_abc_pdf(c, t - timedelta(days=5), [("GV DO BRASIL", 21.68), ("RECICLATRANS", 13.22), ("IRA INTERNATIONAL", 7.08)])),
        (f"irpf-{Y-1}.pdf", syn.irpf_pdf(c.partners[0], Y - 1, 4_232_371.0, 24_537.0, 142_302.0)),
        (f"irpf-{Y}.pdf", syn.irpf_pdf(c.partners[0], Y, 4_400_000.0, 20_000.0, 150_000.0)),
        ("visita.pdf", syn.relatorio_visita_pdf(c, t - timedelta(days=3))),
    ]


def test_full_analysis_stage_is_ready_without_formalization(client, analyst, supervisor):
    c = syn.company(600)
    reg = new_registration(client, analyst, c.razao, c.cnpj, kind="PJ")
    for name, data in _full_analysis_set(c):
        r = upload(client, analyst, reg["id"], name, data)
        assert r.status_code == 201, (name, r.text)
    d, items = _state(client, analyst, reg["id"])
    analysis = {k: v for k, v in items.items() if v["stage"] == "analise"}
    assert all(v["state"] == "ok" for v in analysis.values()), {k: (v["state"], v["state_note"]) for k, v in analysis.items() if v["state"] != "ok"}
    assert items[f"balanco_anterior"]["label"] == f"Balanço patrimonial e DRE {Y-1}"
    assert items["identidade_socios"]["state"] == "missing" and not items["identidade_socios"]["blocking"]
    assert d["checklist"]["stage"] == "analise"
    assert d["ready_for_decision"], [f["title"] for f in d["findings"] if f["status"] == "open"]

    # committee approval, then formalization documents arrive on the approved registration
    assert client.post(f"/api/registrations/{reg['id']}/decisions", json={"action": "approve", "reason": "Aprovado em comitê"}, headers=supervisor).status_code == 201
    p = c.partners[0]
    r = upload(client, analyst, reg["id"], "rg-socio.png", syn.rg(p.name, p.cpf, p.rg, p.birth, today() - timedelta(days=400)).png())
    assert r.status_code == 201
    d, items = _state(client, analyst, reg["id"])
    assert d["status"] == "approved" and d["checklist"]["stage"] == "formalizacao"
    assert items["identidade_socios"]["state"] == "ok" and items["identidade_socios"]["blocking"]
    assert items["endereco"]["state"] == "missing" and items["casamento"]["state"] == "optional"

    # required information is filled on the registration, not uploaded
    client.patch(f"/api/registrations/{reg['id']}", json={"reference_fields": {"dados_bancarios": "Banco 001 ag 1234 cc 5678-9"}}, headers=analyst)
    d, _ = _state(client, analyst, reg["id"])
    info = {i["id"]: i["state"] for i in d["checklist"]["info"]}
    assert info == {"dados_bancarios": "ok", "responsavel_financeiro": "missing"}


def test_financials_are_read(client, analyst):
    c = syn.company(610)
    reg = new_registration(client, analyst, c.razao, c.cnpj, kind="PJ")
    ids = {}
    for name, data in _full_analysis_set(c):
        ids[name] = upload(client, analyst, reg["id"], name, data).json()["results"][0]["document"]["id"]
    def fields(name):
        return {f["name"]: f["value"] for f in client.get(f"/api/documents/{ids[name]}", headers=analyst).json()["fields"]}
    b = fields(f"balanco-{Y-1}.pdf")
    assert b["exercicio"] == str(Y - 1) and b["lucro_liquido"] == "-R$ 2.700.000,00" and b["receita_liquida"] == "R$ 48.000.000,00"
    assert b["crc_contador"].startswith("CRC PR")
    f = fields(f"faturamento-{Y-1}.pdf")
    assert f["faturamento_total"] == "R$ 48.078.000,00" and f["periodo_fim"] == f"{Y-1}-12-31"
    e = fields("endividamento.pdf")
    assert e["endividamento_total"] == "R$ 4.163.322,98"
    i = fields(f"irpf-{Y-1}.pdf")
    assert i["patrimonio_declarado"] == "R$ 4.232.371,00" and i["cpf"] == c.partners[0].cpf


def test_year_mismatch_is_explained(client, analyst):
    c = syn.company(620)
    reg = new_registration(client, analyst, c.razao, c.cnpj, kind="PJ")
    upload(client, analyst, reg["id"], "balanco-antigo.pdf", syn.balanco_pdf(c, Y - 3, 1e6, 1e5, 1e6, 2e6))
    _, items = _state(client, analyst, reg["id"])
    assert items["balanco_anterior"]["state"] == "missing"
    assert items["balanco_anterior"]["state_note"] == f"recebido de outro ano: {Y-3}"


def test_sa_alternative_needs_both_documents(client, analyst):
    c = syn.company(630)
    reg = new_registration(client, analyst, "INDUSTRIA EXEMPLO S.A.", c.cnpj, kind="PJ")
    estatuto = syn.text_pdf(["ESTATUTO SOCIAL", "SOCIEDADE ANONIMA", f"CNPJ: {c.cnpj}", "ASSEMBLEIA GERAL", "ACOES ORDINARIAS"])
    upload(client, analyst, reg["id"], "estatuto.pdf", estatuto)
    _, items = _state(client, analyst, reg["id"])
    assert items["societario"]["state"] == "missing"
    ata = syn.text_pdf(["ATA DA ASSEMBLEIA GERAL EXTRAORDINARIA", "ELEICAO DA DIRETORIA", "MANDATO DE 3 ANOS", f"CNPJ: {c.cnpj}"])
    upload(client, analyst, reg["id"], "ata.pdf", ata)
    _, items = _state(client, analyst, reg["id"])
    assert items["societario"]["state"] == "ok" and items["societario"]["received"] == 2


def test_missing_signature_and_stale_revenue_and_old_debt(client, analyst):
    c = syn.company(640)
    reg = new_registration(client, analyst, c.razao, c.cnpj, kind="PJ")
    r1 = upload(client, analyst, reg["id"], "fat.pdf", syn.faturamento_pdf(c, Y, {1: 1e6, 2: 1e6}, signed=False))
    r2 = upload(client, analyst, reg["id"], "end.pdf", syn.endividamento_pdf(c, today() - timedelta(days=120), [("BANCO X", 1e6, 5e5)]))
    f1 = client.get(f"/api/documents/{r1.json()['results'][0]['document']['id']}", headers=analyst).json()
    f2 = client.get(f"/api/documents/{r2.json()['results'][0]['document']['id']}", headers=analyst).json()
    assert "SIGNATURE_NOT_FOUND" in _codes(f1["findings"])
    if today().month > 4:  # Jan–Feb of the current year is more than two months old from May on
        assert "REVENUE_OUTDATED" in _codes(f1["findings"])
    assert "DOC_TOO_OLD" in _codes(f2["findings"])


def test_person_outside_partners_is_flagged_for_companies(client, analyst):
    c = syn.company(650)
    reg = new_registration(client, analyst, c.razao, c.cnpj, kind="PJ")
    upload(client, analyst, reg["id"], "certidao.pdf", syn.certidao_simplificada_pdf(c, today()))
    stranger = syn.person(9999, "ROBERTO ESTRANHO NUNES")
    upload(client, analyst, reg["id"], "rg.png", syn.rg(stranger.name, stranger.cpf, stranger.rg, stranger.birth, today() - timedelta(days=100)).png())
    p = c.partners[1]
    upload(client, analyst, reg["id"], "rg2.png", syn.rg(p.name, p.cpf, p.rg, p.birth, today() - timedelta(days=100)).png())
    d, _ = _state(client, analyst, reg["id"])
    flagged = [f for f in d["findings"] if f["code"] == "PERSON_NOT_IN_PARTNERS" and f["status"] == "open"]
    assert len(flagged) == 1 and "ROBERTO" in flagged[0]["explanation"]
    assert not any(f["code"] == "NAME_MISMATCH_DOCUMENTS" for f in d["findings"])


def test_report_brings_the_case_together(client, analyst, auditor):
    c = syn.company(660)
    reg = new_registration(client, analyst, c.razao, c.cnpj, kind="PJ")
    for name, data in _full_analysis_set(c):
        upload(client, analyst, reg["id"], name, data)
    client.patch(f"/api/registrations/{reg['id']}", json={"reference_fields": {"parecer": "Empresa sólida.", "recomendacao": "Recomendado com ressalvas", "limite_total": "R$ 1.500.000,00"}}, headers=analyst)
    r = client.get(f"/api/registrations/{reg['id']}/report", headers=auditor)
    assert r.status_code == 200
    rep = r.json()
    assert rep["revenue"]["summary"]["year"] == str(Y) and rep["revenue"]["summary"]["previous_total"] == 48_078_000.0
    assert rep["debt"]["total"] == 4_163_322.98 and rep["debt"]["items"][0]["instituicao"] == "BANCO DO BRASIL"
    assert rep["customers"]["top3_share"] == 41.98
    names = {p["nome"] for p in rep["partners"]}
    assert {c.partners[0].name, c.partners[1].name} <= names
    sid = next(p for p in rep["partners"] if p["nome"] == c.partners[0].name)
    assert [x["exercicio"] for x in sid["irpf"]] == [str(Y - 1), str(Y)] and sid["cpf"] == c.partners[0].cpf
    assert [s["exercicio"] for s in rep["statements"]] == [str(Y - 2), str(Y - 1)]
    assert rep["analysis"]["recomendacao"] == "Recomendado com ressalvas"
    assert rep["images"]["visit_document_id"]
    photo = client.get(f"/api/documents/{rep['images']['visit_document_id']}/photo", headers=auditor)
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
