"""The Record explorer's records: Builder.explorer() on the fake dataset, and GET /api/explorer.

The dataset has 12 records: 9 open (T1 T2 T3 T5, P1, C1-C4) and 3 closed (T4 solved, P2 closed, C5 cancelled).
"""
import pytest
from fastapi.testclient import TestClient

import main
import model
from fake_glpi import EXTRA, NOW, PUBLIC_URL, ROOTS, model_input


def rows(data=None):
    builder = model.Builder(data or model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA)
    builder.build()
    return builder.explorer()


@pytest.fixture(scope="module")
def recs():
    return {r["key"]: r for r in rows()}


def test_every_record_is_there_closed_too(recs):
    assert len(recs) == 12
    assert {k for k, r in recs.items() if not r["open"]} == {"Ticket:4", "Problem:2", "Change:5"}


def test_rows_carry_what_the_explorer_groups_by_and_shows(recs):
    t1 = recs["Ticket:1"]
    assert t1 == {"key": "Ticket:1", "kind": "Incident", "ref": "Incident #1", "name": "Certificate expired on web1",
                  "status": "Processing (assigned)", "open": True, "priority": 4, "priority_name": "High",
                  "category": "Security > Certificates", "area": "Security", "date": "2026-10-17",
                  "updated": "2026-10-22", "age_days": 10, "url": PUBLIC_URL + "/front/ticket.form.php?id=1",
                  "assigned": True, "cis": ["web1"], "family": "Problem #1: Recurring certificate failures"}
    t3 = recs["Ticket:3"]
    assert (t3["kind"], t3["area"], t3["category"]) == ("Request", "Uncategorised", "")
    assert (recs["Ticket:2"]["assigned"], recs["Ticket:2"]["cis"]) == (False, ["db1"])   # a requester isn't assigned
    assert recs["Change:2"]["assigned"] is True                                          # a group is
    assert recs["Change:4"]["cis"] == []


def test_no_internal_fields_or_descriptions_leak(recs):
    for r in recs.values():
        assert not any(f.startswith("_") for f in r)
        assert "content" not in r


def test_records_joined_by_links_are_one_family_named_after_its_problem(recs):
    # P1 is linked to incidents T1 and T4 (closed), and C1 to P1.
    family = {k for k, r in recs.items() if r["family"]}
    assert family == {"Problem:1", "Ticket:1", "Ticket:4", "Change:1"}
    assert {recs[k]["family"] for k in family} == {"Problem #1: Recurring certificate failures"}
    assert recs["Ticket:2"]["family"] == ""


def test_families_are_kept_apart_and_a_change_leads_one_without_a_problem():
    data = model_input()
    data["Problem_Ticket"].append({"id": 3, "problems_id": 2, "tickets_id": 2})
    data["Change_Problem"].append({"id": 2, "changes_id": 3, "problems_id": 2})
    data["Change_Problem"].append({"id": 3, "changes_id": 9, "problems_id": 1})     # a deleted change
    recs = {r["key"]: r for r in rows(data)}
    assert recs["Ticket:2"]["family"] == recs["Change:3"]["family"] == "Problem #2: Closed problem"
    assert recs["Ticket:1"]["family"] == "Problem #1: Recurring certificate failures"
    data = model_input()
    data["Problem_Ticket"], data["Change_Problem"] = [], []
    builder = model.Builder(data, NOW, PUBLIC_URL, ROOTS, EXTRA)
    builder.build()
    builder.d["Problem_Ticket"] = [{"id": 1, "problems_id": 1, "tickets_id": 1}]
    builder.records["Problem:1"]["name"] = ""
    assert builder.families()["Ticket:1"] == "Problem #1"     # a lead with no title is named by its reference


def test_a_link_between_two_unknown_records_joins_nothing():
    data = model_input()
    data["Problem_Ticket"].append({"id": 3, "problems_id": 8, "tickets_id": 9})
    assert {r["family"] for r in rows(data)} == {"", "Problem #1: Recurring certificate failures"}


def test_rows_come_by_priority_then_age():
    out = rows()
    order = [(r["priority"], r["age_days"]) for r in out]
    assert order == sorted(order, key=lambda o: (-o[0], -o[1]))
    assert out[0]["key"] == "Ticket:4"           # Very high


def test_a_blank_title_is_an_empty_string():
    data = model_input()
    data["Ticket"][0]["name"] = None
    assert {r["key"]: r for r in rows(data)}["Ticket:1"]["name"] == ""


@pytest.fixture
def client(app_state):
    with TestClient(main.app) as c:
        c.post("/api/refresh")
        yield c


def test_explorer_before_the_first_refresh_is_503(app_state):
    r = TestClient(main.app).get("/api/explorer")
    assert r.status_code == 503
    assert r.json() == {"error": "first refresh still running"}


def test_explorer_endpoint(client):
    r = client.get("/api/explorer")
    assert r.status_code == 200
    body = r.json()
    assert len(body["records"]) == 12
    assert body["refreshed_at"] == client.get("/api/snapshot").json()["refreshed_at"]


def test_a_failed_refresh_keeps_the_last_records(client, fake, monkeypatch):
    before = client.get("/api/explorer").json()
    fake.down = True
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    assert client.post("/api/refresh").json()["error"]
    assert client.get("/api/explorer").json() == before


def test_a_refresh_brings_new_records(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.data["Ticket"].append({**fake.data["Ticket"][0], "id": 6, "name": "Brand new"})
    client.post("/api/refresh")
    assert "Ticket:6" in {r["key"] for r in client.get("/api/explorer").json()["records"]}


def test_explorer_sends_the_security_headers(client):
    r = client.get("/api/explorer")
    assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert r.headers["Cache-Control"] == "no-store"


def test_explorer_carries_no_tokens(client):
    body = client.get("/api/explorer").text
    assert "SECRET" not in body
