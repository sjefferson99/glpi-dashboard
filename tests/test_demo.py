"""The demo dataset behind the README screenshots: repeatable, realistic enough to fill every view, and generic."""
import re
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from demo_glpi import NOW as DEMO_NOW, demo_dataset
from fake_glpi import FakeGlpi
from live_app import serve

NOW = datetime(2026, 10, 27, 12, 0, 0)
HOSTNAME = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b")
LINKS = {"Item_Ticket": ("Ticket", "tickets_id"), "Item_Problem": ("Problem", "problems_id"),
         "Change_Item": ("Change", "changes_id")}


@pytest.fixture
def demo(app_state, fake):
    """The app, refreshed from the demo dataset through the fake GLPI and the real client."""
    fake.data = demo_dataset(now=NOW)
    with TestClient(main.app) as c:
        c.post("/api/refresh")
        yield c


def _strings(value):
    """Every string in a nested structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_the_same_seed_gives_the_same_data():
    assert demo_dataset(now=NOW) == demo_dataset(now=NOW)
    assert demo_dataset(seed=1, now=NOW) != demo_dataset(now=NOW)


def test_dates_are_measured_back_from_now():
    later = datetime(2027, 3, 1, 12, 0, 0)
    tickets = demo_dataset(now=later)["Ticket"]
    assert max(t["date"] for t in tickets) <= later.strftime("%Y-%m-%d %H:%M:%S")
    assert max(t["date"] for t in tickets) > "2027-02"


def test_size_is_like_a_real_instance():
    d = demo_dataset(now=NOW)
    assert 100 <= len(d["Ticket"]) + len(d["Problem"]) + len(d["Change"]) <= 250
    assert {t["type"] for t in d["Ticket"]} == {1, 2}
    assert len({r["itilcategories_id"] for r in d["Ticket"]}) >= 10


def test_every_link_points_at_a_record_and_a_ci_that_exist():
    d = demo_dataset(now=NOW)
    for table, (itemtype, field) in LINKS.items():
        ids = {r["id"] for r in d[itemtype]}
        for row in d[table]:
            assert row[field] in ids
            assert row["items_id"] in {c["id"] for c in d[row["itemtype"]]}
    for row in d["Problem_Ticket"]:
        assert row["problems_id"] in {p["id"] for p in d["Problem"]}
        assert row["tickets_id"] in {t["id"] for t in d["Ticket"]}
    for row in d["ImpactRelation"]:
        for side in ("source", "impacted"):
            assert row[f"items_id_{side}"] in {c["id"] for c in d[row[f"itemtype_{side}"]]}
    for table in (*LINKS, "Ticket_User", "Group_Ticket", "Itil_Project", "Problem_Ticket", "Change_Problem"):
        ids = [r["id"] for r in d[table]]
        assert len(ids) == len(set(ids)), table


def test_nothing_site_specific():
    """Only example.test for a domain, and no addresses: the screenshots go in a public repo."""
    text = "\n".join(_strings(demo_dataset(now=NOW))).lower()
    assert set(HOSTNAME.findall(text)) <= {"example.test"}
    assert "@" not in text
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)


def test_every_view_has_something_in_it(demo):
    snap = demo.get("/api/snapshot").json()
    assert snap["error"] is None
    assert all(t["count"] for t in snap["summary"])
    assert sum(t["count"] > 0 for t in snap["quality"]) >= 5
    assert {"red", "amber"} <= {a["rag"] for a in snap["health"]["areas"]}
    assert len(snap["health"]["cis"]) >= 5
    assert any(c["internet"] for c in snap["health"]["cis"])
    assert len(snap["health"]["recurring"]) == 3 and all(r["open"] for r in snap["health"]["recurring"])
    for group in snap["in_flight"]["groups"]:
        assert any(t["count"] for t in group["tiles"]), group["title"]
    assert snap["lists"]["projects"]["rows"] and len(snap["risks"]["kinds"]) == 2
    assert snap["risks"]["total"] >= 10


def test_the_explorer_and_search_have_history_to_show(demo):
    records = demo.get("/api/explorer").json()["records"]
    assert len(records) >= 150 and sum(not r["open"] for r in records) > 100
    assert len({r["date"][:4] for r in records}) >= 2
    found = demo.get("/api/search", params={"q": "vpn", "closed": "true"}).json()
    assert {r["kind"] for r in found["results"]} >= {"Incident", "Problem", "Change", "CI"}
    assert any(r.get("snippet") for r in found["results"])


def test_the_demo_server_stops_the_apps_clock_at_the_datasets_date():
    """scripts/demo.py serves this way, so "Updated" and every age read the same in shots taken months apart."""
    with serve(FakeGlpi(demo_dataset()), now=DEMO_NOW) as url:
        snap = httpx.post(url + "/api/refresh", timeout=10).json()
        assert snap["refreshed_at"] == DEMO_NOW.isoformat(timespec="milliseconds")
        assert httpx.get(url + "/healthz").json() == {"ok": True, "refreshed_at": DEMO_NOW.isoformat(timespec="seconds")}
    assert main.datetime is datetime         # put back afterwards
