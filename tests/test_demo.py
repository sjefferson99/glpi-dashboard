"""The demo dataset behind the README screenshots: repeatable, realistic enough to fill every view, and generic."""
import importlib.util
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from demo_glpi import NOW as DEMO_NOW, demo_dataset
from live_app import frozen

NOW = datetime(2026, 10, 27, 12, 0, 0)
HOSTNAME = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b")
LINKS = {"Item_Ticket": ("Ticket", "tickets_id"), "Item_Problem": ("Problem", "problems_id"),
         "Change_Item": ("Change", "changes_id")}
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "demo.py"


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


def test_a_frozen_clock_stops_the_apps_time_at_the_datasets_date(app_state, fake, monkeypatch):
    """scripts/demo.py serves this way, so "Updated" and every age read the same in shots taken months apart."""
    monkeypatch.setattr(main, "datetime", frozen(DEMO_NOW))
    fake.data = demo_dataset()
    with TestClient(main.app) as c:
        snap = c.post("/api/refresh").json()
        health = c.get("/healthz").json()
    assert snap["refreshed_at"] == DEMO_NOW.isoformat(timespec="milliseconds")
    assert health == {"ok": True, "refreshed_at": DEMO_NOW.isoformat(timespec="seconds")}


def test_no_record_is_updated_before_it_was_opened():
    d = demo_dataset()
    assert [(t, r["id"]) for t in ("Ticket", "Problem", "Change") for r in d[t] if r["date_mod"] < r["date"]] == []


def _demo_script():
    spec = importlib.util.spec_from_file_location("demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("status", "body", "message"), [
    (503, {"error": "ValueError building the dashboard (see container log)"},
     "refresh failed: ValueError building the dashboard (see container log)"),
    (200, {"error": "GlpiError: ERROR_RIGHT_MISSING"}, "refresh failed: GlpiError: ERROR_RIGHT_MISSING"),
    (502, None, "refresh failed: HTTP 502"),
])
def test_the_demo_exits_with_the_apps_error_when_the_refresh_fails(status, body, message):
    """A failed first refresh is a 503 with the error in its body, which the demo shows rather than a traceback."""
    demo = _demo_script()
    reply = (lambda request: httpx.Response(status, json=body)) if body else (lambda request: httpx.Response(status))
    with httpx.Client(transport=httpx.MockTransport(reply)) as client, pytest.raises(SystemExit) as exit_:
        demo.refresh(client, "http://demo")
    assert str(exit_.value) == message


def test_the_demo_refresh_passes_when_the_app_has_read_the_data():
    demo = _demo_script()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"error": None}))) as client:
        demo.refresh(client, "http://demo")


def test_serving_the_demo_needs_no_test_dependencies():
    """With pytest and Playwright blocked, the demo script and its server helper still load."""
    code = ("import sys, importlib.util; sys.modules['pytest'] = sys.modules['playwright'] = None; "
            f"spec = importlib.util.spec_from_file_location('demo', {str(SCRIPT)!r}); "
            "spec.loader.exec_module(importlib.util.module_from_spec(spec))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
