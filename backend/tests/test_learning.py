"""The extraction learns from the analysts' reviews, inside this database."""

from datetime import timedelta

from app.pipeline import ai
from tests import synthetic as syn
from tests.conftest import new_registration, today, upload
from tests.test_failures import FakeAi, _analysis, _enable_ai


def _rg(client, h, seed, issuer="SSP/SP"):
    p = syn.person(seed)
    reg = new_registration(client, h, p.name, p.cpf)
    r = upload(client, h, reg["id"], "rg.png", syn.rg(p.name, p.cpf, p.rg, p.birth, today() - timedelta(days=40), issuer=issuer).png())
    did = r.json()["results"][0]["document"]["id"]
    return did, {f["name"]: f for f in client.get(f"/api/documents/{did}", headers=h).json()["fields"]}


def _correct(client, h, did, name, value):
    r = client.patch(f"/api/documents/{did}/fields/{name}", headers=h, json={"action": "correct", "value": value, "reason": "conforme o original"})
    assert r.status_code == 200, r.text


def test_value_corrected_away_is_not_offered_again(client, analyst):
    did, fields = _rg(client, analyst, 90, issuer="SSP/XX")
    assert fields["orgao_expedidor"]["value"]
    wrong = fields["orgao_expedidor"]["value"]
    _correct(client, analyst, did, "orgao_expedidor", "IIRGD/SP")
    _, again = _rg(client, analyst, 91, issuer="SSP/XX")
    assert "orgao_expedidor" not in again or again["orgao_expedidor"]["value"] != wrong
    _, kept = _rg(client, analyst, 92, issuer="SSP/SP")
    assert kept["orgao_expedidor"]["value"]


def test_ai_reading_preferred_where_analysts_sided_with_it(client, analyst):
    _enable_ai()
    for seed, uf in ((93, "RJ"), (94, "MG")):
        ai.set_provider(FakeAi(_analysis(fields=[{"name": "orgao_expedidor", "value": f"IIRGD/{uf}", "page": 0, "evidence_text": ""}])))
        did, fields = _rg(client, analyst, seed, issuer=f"SSP/{uf}")
        assert fields["orgao_expedidor"]["source"] != "ai"
        _correct(client, analyst, did, "orgao_expedidor", f"IIRGD/{uf}")
    ai.set_provider(FakeAi(_analysis(fields=[{"name": "orgao_expedidor", "value": "IIRGD/PR", "page": 0, "evidence_text": ""}])))
    _, fields = _rg(client, analyst, 95, issuer="SSP/PR")
    assert fields["orgao_expedidor"]["value"] == "IIRGD/PR" and fields["orgao_expedidor"]["source"] == "ai"
