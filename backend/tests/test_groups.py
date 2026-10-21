"""Commercial chosen at creation, and economic groups with suggestions from the documents."""

from datetime import date

from tests import synthetic as syn
from tests.conftest import new_registration, upload


def test_registration_gets_the_commercial_chosen_at_creation(client, analyst):
    com = client.post("/api/portfolio/commercials", json={"name": "Gabriel"}, headers=analyst).json()
    r = client.post("/api/registrations", json={"kind": "PF", "subject_name": "MARIA DA SILVA", "modality": "normal", "commercial_id": com["id"]}, headers=analyst)
    assert r.status_code == 201 and r.json()["commercial"]["name"] == "Gabriel"
    reg = r.json()
    rep = client.get(f"/api/registrations/{reg['id']}/report", headers=analyst).json()
    assert rep["analysis"]["comercial"] == "Gabriel"
    other = client.post("/api/portfolio/commercials", json={"name": "Moacir"}, headers=analyst).json()
    r = client.patch(f"/api/registrations/{reg['id']}", json={"commercial_id": other["id"]}, headers=analyst)
    assert r.json()["commercial"]["name"] == "Moacir"
    assert client.post("/api/registrations", json={"kind": "PF", "subject_name": "JOAO", "modality": "normal",
                                                   "commercial_id": "00000000-0000-0000-0000-000000000000"}, headers=analyst).status_code == 422


def test_economic_group_suggestions_from_cnpj_root_and_shared_partner(client, analyst):
    root = syn.make_cnpj(31)
    digits = "".join(ch for ch in root if ch.isdigit())
    branch = digits[:8] + "0002" + digits[12:]  # same root, other establishment (check digits are not verified here)
    a = new_registration(client, analyst, "ALFA PLASTICOS LTDA", root, kind="PJ")
    b = client.post("/api/registrations", json={"kind": "PJ", "subject_name": "ALFA PLASTICOS FILIAL", "modality": "normal"}, headers=analyst).json()
    from app.db import session_scope
    from app.models import Registration
    with session_scope() as db:
        db.get(Registration, b["id"]).tax_id = branch
    c = new_registration(client, analyst, "BETA EMBALAGENS LTDA", syn.make_cnpj(32), kind="PJ")
    upload(client, analyst, a["id"], "contrato-a.pdf", syn.contrato_social_pdf("ALFA PLASTICOS LTDA", root, ["CARLOS EDUARDO NUNES", "LUCIA NUNES"], date(2015, 1, 5)))
    upload(client, analyst, c["id"], "contrato-c.pdf", syn.contrato_social_pdf("BETA EMBALAGENS LTDA", syn.make_cnpj(32), ["CARLOS EDUARDO NUNES", "PEDRO ALVES"], date(2018, 3, 1)))

    s = client.get(f"/api/registrations/{a['id']}/group-suggestions", headers=analyst).json()["items"]
    by_name = {x["registration"]["subject_name"]: x["reasons"] for x in s}
    assert any("CNPJ" in r for r in by_name["ALFA PLASTICOS FILIAL"])
    assert any("CARLOS EDUARDO NUNES" in r for r in by_name["BETA EMBALAGENS LTDA"])

    g = client.post("/api/groups", json={"name": "grupo nunes", "registration_ids": [a["id"], c["id"]]}, headers=analyst)
    assert g.status_code == 201 and g.json()["name"] == "GRUPO NUNES" and g.json()["members"] == 2
    gid = g.json()["id"]
    assert client.post("/api/groups", json={"name": "Grupo Nunes"}, headers=analyst).status_code == 409
    r = client.patch(f"/api/registrations/{b['id']}", json={"group_id": gid}, headers=analyst)
    assert r.json()["group"]["name"] == "GRUPO NUNES"
    members = client.get(f"/api/registrations?group_id={gid}", headers=analyst).json()["items"]
    assert {m["subject_name"] for m in members} == {"ALFA PLASTICOS LTDA", "BETA EMBALAGENS LTDA", "ALFA PLASTICOS FILIAL"}
    assert client.get(f"/api/registrations/{a['id']}/group-suggestions", headers=analyst).json()["items"] == []  # all in the group already
    assert client.get("/api/groups", headers=analyst).json()["items"][0]["members"] == 3
    loose = new_registration(client, analyst, "AAA SEM GRUPO LTDA", syn.make_cnpj(33), kind="PJ")
    listed = client.get("/api/registrations?grouped=true&sort=name&direction=asc", headers=analyst).json()["items"]
    assert [x["group"]["name"] if x["group"] else None for x in listed][-1] is None and listed[-1]["id"] == loose["id"]

    assert client.delete(f"/api/groups/{gid}", headers=analyst).status_code == 204
    assert client.get(f"/api/registrations/{a['id']}", headers=analyst).json()["group"] is None
