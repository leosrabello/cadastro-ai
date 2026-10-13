"""Add one synthetic company (FIDC) case with the full analysis set to a development server.

    docker compose exec api python scripts/seed_company_demo.py
"""

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import synthetic as syn  # noqa: E402

API = os.environ.get("SEED_API", "http://localhost:8000")


def main() -> None:
    if os.environ.get("APP_ENV") == "production":
        sys.exit("refusing to seed a production server")
    c = httpx.Client(base_url=API, timeout=120)
    tok = c.post("/api/auth/login", json={"email": os.environ["BOOTSTRAP_ADMIN_EMAIL"], "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"]}).raise_for_status().json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    t, y = date.today(), date.today().year
    co = syn.company(700)
    reg = c.post("/api/registrations", json={"kind": "PJ", "subject_name": co.razao, "tax_id": co.cnpj}, headers=h).raise_for_status().json()
    prev = {m: v for m, v in zip(range(1, 13), [7.16e6, 9.72e6, 8.35e6, 8.16e6, 6.89e6, 6.76e6, 9.91e6, 8.76e6, 7.97e6, 10.43e6, 9.44e6, 9.82e6])}
    cur = {m: v for m, v in zip(range(1, t.month), [13.09e6, 11.38e6, 15.91e6, 22.39e6, 14.2e6, 12.8e6, 16.1e6, 15.4e6, 14.9e6, 15.2e6, 14.4e6])}
    files = [
        ("certidao-simplificada.pdf", syn.certidao_simplificada_pdf(co, t - timedelta(days=12))),
        (f"balanco-dre-{y-2}.pdf", syn.balanco_pdf(co, y - 2, 41.2e6, 1.9e6, 12.4e6, 40.1e6)),
        (f"balanco-dre-{y-1}.pdf", syn.balanco_pdf(co, y - 1, 47.2e6, -2.7e6, 9.7e6, 61.2e6)),
        (f"balancete-{y}.pdf", syn.balancete_pdf(co, y, sum(cur.values()))),
        (f"faturamento-{y-2}.pdf", syn.faturamento_pdf(co, y - 2, {m: v * 0.82 for m, v in prev.items()})),
        (f"faturamento-{y-1}.pdf", syn.faturamento_pdf(co, y - 1, prev)),
        (f"faturamento-{y}.pdf", syn.faturamento_pdf(co, y, cur)),
        ("endividamento.pdf", syn.endividamento_pdf(co, t - timedelta(days=20), [
            ("BRADESCO", 14_000_000, 11_859_291.65), ("BANCO DO BRASIL", 7_000_000, 5_990_872.29), ("SICOOB", 7_500_000, 6_798_196.09),
            ("ITAU", 7_000_000, 5_844_648.97), ("CREDIFOZ", 4_000_000, 3_476_001.76), ("SP CAPITAL", 2_000_000, 1_844_020.18),
            ("SAFRA", 1_000_000, 687_321.22), ("SICREDI", 1_000_000, 607_167.55)])),
        ("curva-abc.pdf", syn.curva_abc_pdf(co, t - timedelta(days=8), [("GV DO BRASIL", 21.68), ("RECICLATRANS", 13.22), ("IRA INTERNATIONAL", 7.08), ("METALURGICA SUL", 5.4), ("PAPELAO ITAJAI", 4.9)])),
        (f"irpf-{y-1}-sidnei.pdf", syn.irpf_pdf(co.partners[0], y - 1, 4_012_000.0, 31_200.0, 128_000.0)),
        (f"irpf-{y}-sidnei.pdf", syn.irpf_pdf(co.partners[0], y, 4_232_371.0, 24_537.0, 142_302.0)),
        (f"irpf-{y}-jaqueline.pdf", syn.irpf_pdf(co.partners[1], y, 2_935_099.0, 1_651_951.0, 60_000.0)),
        ("relatorio-visita.pdf", syn.relatorio_visita_pdf(co, t - timedelta(days=6))),
    ]
    for name, data in files:
        r = c.post(f"/api/registrations/{reg['id']}/documents", files=[("files", (name, data))], headers=h)
        print(f"  {reg['code']} {name}: {r.status_code}")
    c.patch(f"/api/registrations/{reg['id']}", json={"reference_fields": {
        "comercial": "Edelmar Gonçalves", "regiao": "Santa Catarina", "recomendacao": "Recomendado com ressalvas",
        "limite_total": "R$ 1.500.000,00", "taxa": "1,85% a.m.",
        "parecer": "Empresa com mais de 40 anos no segmento de reciclagem, estrutura própria e frota consolidada. Faturamento em forte expansão no ano, com concentração relevante nos três maiores clientes. Endividamento elevado frente à média mensal; recomendo limite global reduzido e acompanhamento próximo dos indicadores."}}, headers=h)
    for _ in range(60):
        if c.get("/api/dashboard", headers=h).json()["counts"]["documents_in_flight"] == 0:
            break
        time.sleep(2)
    print("registration:", reg["code"], reg["id"])


if __name__ == "__main__":
    main()
