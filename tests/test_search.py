"""Search: the index built at refresh, model.search() over it, and GET /api/search."""
import inspect

import pytest
from fastapi.testclient import TestClient

import main
import model
from fake_glpi import EXTRA, NOW, PUBLIC_URL, ROOTS, model_input


def index(data=None):
    b = model.Builder(data or model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA)
    b.build()
    return b.search_index()


@pytest.fixture(scope="module")
def idx():
    return index()


def refs(result):
    return [r["ref"] for r in result["results"]]


# --- the index ----------------------------------------------------------------------------------------------

def test_index_holds_every_record_closed_too_projects_and_cis(idx):
    by_kind = {}
    for e in idx:
        by_kind.setdefault(e["kind"], []).append(e["ref"])
    assert sorted(by_kind) == ["CI", "Change", "Incident", "Problem", "Project", "Request"]
    assert len(by_kind["Incident"]) + len(by_kind["Request"]) == 5
    assert "Incident #4" in by_kind["Incident"]      # closed
    assert "Problem #2" in by_kind["Problem"]        # closed
    assert len(by_kind["Change"]) == 5
    assert by_kind["Project"] == ["Project #1"]
    assert sorted(by_kind["CI"]) == ["Appliance #1", "Computer #1", "Computer #2", "Computer #3"]


def test_ci_templates_are_left_out(idx):
    assert not [e for e in idx if e["name"] == "template-server"]


def test_namespaced_ci_types_show_their_last_part_and_link_to_glpi():
    data = model_input()
    data["cis"]["Glpi\\CustomAsset\\ServerAsset"] = [{"id": 7, "name": "edge1"}]
    e = next(e for e in index(data) if e["name"] == "edge1")
    assert e["ref"] == "ServerAsset #7" and e["category"] == "ServerAsset"
    assert e["url"] == PUBLIC_URL + "/"


def test_descriptions_are_indexed_as_plain_text(idx):
    e = next(e for e in idx if e["ref"] == "Incident #2")
    assert e["_text"] == "Queries time out during the nightly backup job."


# --- model.search() -----------------------------------------------------------------------------------------

def test_search_matches_the_title_ignoring_case(idx):
    assert refs(model.search(idx, "CERTIFICATE")) == [
        "Change #1", "Incident #1", "Problem #1", "Project #1"]


def test_every_word_must_match(idx):
    assert refs(model.search(idx, "certificate renew")) == ["Change #1"]
    assert model.search(idx, "certificate nothing-like-this")["total"] == 0


def test_search_finds_words_in_descriptions_with_a_snippet(idx):
    r = model.search(idx, "backup", closed=True)
    assert refs(r) == ["Incident #2", "Incident #4"]     # the closed record last
    first = r["results"][0]
    assert first["snippet"] == "Queries time out during the nightly backup job."
    assert "_text" not in first and "_hay" not in first and "_tag" not in first


def test_html_in_descriptions_is_not_searched(idx):
    assert model.search(idx, "<b>")["total"] == 0
    assert model.search(idx, "&lt;")["total"] == 0


def test_title_matches_have_no_snippet(idx):
    assert model.search(idx, "db1 slow")["results"][0]["snippet"] == ""


def test_search_covers_category_status_cis_and_serials(idx):
    assert "Incident #1" in refs(model.search(idx, "certificates"))       # category Security > Certificates
    assert refs(model.search(idx, "pending")) == ["Incident #5"]                 # its status
    assert "Incident #1" in refs(model.search(idx, "web1"))               # its linked CI
    assert refs(model.search(idx, "SN-WEB"))[0] == "Computer #1"
    assert refs(model.search(idx, "edge filtering")) == ["Computer #3"]
    assert refs(model.search(idx, "prj1")) == ["Project #1"]              # project code


def test_an_id_finds_that_id_in_every_type(idx):
    r = model.search(idx, "#1")
    assert [e["ref"] for e in r["ids"]] == ["Incident #1", "Problem #1", "Change #1", "Project #1",
                                            "Computer #1", "Appliance #1"]
    assert r["ids"][0]["url"] == PUBLIC_URL + "/front/ticket.form.php?id=1"
    assert r["total"] == 0 and r["results"] == []


def test_an_id_is_found_closed_or_not(idx):
    r = model.search(idx, "#4")
    assert [(e["ref"], e["open"]) for e in r["ids"]] == [("Incident #4", False), ("Change #4", True)]


def test_records_mentioning_an_id_are_text_matches_below_it():
    data = model_input()
    data["Ticket"][1]["name"] = "Follow-up to #1"                       # T2 mentions #1 in its title
    data["Change"][2]["content"] = "<p>Reverts the fix in #1.</p>"      # C3 in its description
    data["Change"][3]["content"] = "<p>Needs #12 first.</p>"            # C4 names #12, not #1
    r = model.search(index(data), "#1")
    assert "Incident #2" not in [e["ref"] for e in r["ids"]]
    assert refs(r) == ["Incident #2", "Change #3"]                      # the title match first
    assert r["total"] == 2
    assert r["results"][0]["snippet"] == "" and r["results"][1]["snippet"] == "Reverts the fix in #1."


def test_an_id_mention_snippet_skips_a_longer_number():
    assert model._snippet("x" * 200 + " #123 and #12", ["#12"]) == "…" + "x" * 50 + " #123 and #12"
    assert model._snippet("only #123", ["#12"]) == ""


def test_several_ids_and_words_combine():
    data = model_input()
    data["Change"][2]["content"] = "<p>Follows #1 and #4 on db1.</p>"
    r = model.search(index(data), "#1 #4 db1")
    assert {e["ref"] for e in r["ids"]} == {"Incident #1", "Problem #1", "Change #1", "Project #1", "Computer #1",
                                           "Appliance #1", "Incident #4", "Change #4"}
    assert refs(r) == ["Change #3"]                                     # needs every word, ids included


def test_only_a_hash_and_digits_is_an_id(idx):
    for q in ("#x1", "1#", "##1", "#1a", "1"):
        assert model.search(idx, q)["ids"] == []


def test_title_matches_rank_above_other_matches(idx):
    # "db1" is in T2's title, and in C3's title; T2 also links to db1, as do C3 and the CI itself.
    r = refs(model.search(idx, "db1"))
    assert set(r[:3]) == {"Incident #2", "Change #3", "Computer #2"}


def test_closed_records_are_left_out_unless_asked_for(idx):
    assert model.search(idx, "outage")["total"] == 0
    assert refs(model.search(idx, "backup")) == ["Incident #2"]
    network = model.search(idx, "network")["results"]
    assert network and all(x["open"] is not False for x in network)
    assert {x["ref"] for x in network} == {"Incident #2", "Change #2", "Change #3"}


def test_projects_and_cis_are_found_either_way(idx):
    for closed in (False, True):
        assert refs(model.search(idx, "prj1", closed)) == ["Project #1"]
        assert refs(model.search(idx, "edge filtering", closed)) == ["Computer #3"]


def test_closed_records_rank_last(idx):
    r = model.search(idx, "outage", closed=True)
    assert refs(r) == ["Incident #4"] and r["results"][0]["open"] is False
    flags = [x["open"] for x in model.search(idx, "network", closed=True)["results"]]
    assert False in flags and flags == sorted(flags, key=lambda o: o is False)


def test_short_or_blank_queries_match_nothing(idx):
    for q in ("", " ", "a", " a "):
        assert model.search(idx, q) == {"query": q, "ids": [], "total": 0, "results": []}


def test_results_are_capped_but_the_total_is_not(idx):
    r = model.search(idx, "certificate", limit=2)
    assert len(r["results"]) == 2 and r["total"] == 4


def test_regex_characters_are_plain_text(idx):
    assert model.search(idx, ".*")["total"] == 0
    assert model.search(idx, "(db1")["total"] == 0


def test_snippet_is_cut_around_the_match():
    text = "x" * 300 + " needle " + "y" * 300
    s = model._snippet(text, ["needle"])
    assert s.startswith("…") and s.endswith("…") and "needle" in s
    assert len(s) <= model.SNIPPET_BEFORE + model.SNIPPET_AFTER + 2


# --- GET /api/search ----------------------------------------------------------------------------------------

@pytest.fixture
def client(app_state):
    with TestClient(main.app) as c:
        c.post("/api/refresh")
        yield c


def test_search_endpoint(client):
    r = client.get("/api/search", params={"q": "backup"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "backup" and body["total"] == 1
    assert body["results"][0]["url"] == PUBLIC_URL + "/front/ticket.form.php?id=2"


def test_search_endpoint_returns_id_matches_apart(client):
    body = client.get("/api/search", params={"q": "#4"}).json()
    assert [e["ref"] for e in body["ids"]] == ["Incident #4", "Change #4"]
    assert body["total"] == 0
    assert client.get("/api/search", params={"q": "backup"}).json()["ids"] == []


def test_closed_is_off_unless_asked_for(client):
    assert client.get("/api/search", params={"q": "outage"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "outage", "closed": "true"}).json()["total"] == 1
    assert client.get("/api/search", params={"q": "outage", "closed": "false"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "outage", "closed": "maybe"}).status_code == 422


def test_search_makes_no_glpi_requests(client, fake):
    before = len(fake.calls)
    for q in ("certificate", "db1", "backup"):
        client.get("/api/search", params={"q": q})
    assert len(fake.calls) == before


def test_search_before_the_first_refresh_is_503(app_state):
    r = TestClient(main.app).get("/api/search", params={"q": "db1"})
    assert r.status_code == 503 and r.json() == {"error": "first refresh still running"}


def test_overlong_queries_are_refused(client):
    assert client.get("/api/search", params={"q": "x" * (model.SEARCH_MAX + 1)}).status_code == 422
    assert client.get("/api/search", params={"q": "x" * model.SEARCH_MAX}).status_code == 200


def test_a_failed_refresh_keeps_the_last_index(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.down = True
    client.post("/api/refresh")
    assert client.get("/api/search", params={"q": "backup"}).json()["total"] == 1


def test_search_shows_new_data_after_a_refresh(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.data["Ticket"][0]["name"] = "Disk replaced"
    client.post("/api/refresh")
    assert refs(client.get("/api/search", params={"q": "disk replaced"}).json()) == ["Incident #1"]


def test_search_has_the_security_headers(client):
    r = client.get("/api/search", params={"q": "db1"})
    assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert r.headers["Cache-Control"] == "no-store"


# --- review fixes -------------------------------------------------------------------------------------------

def test_matching_and_snippets_agree_on_case(idx):
    data = model_input()
    data["Ticket"][1]["content"] = "Straße 5 cabling"
    ix = index(data)
    # casefold() would match "strasse" here, with no snippet to show why.
    assert model.search(ix, "strasse")["total"] == 0
    hit = model.search(ix, "STRAßE")["results"][0]
    assert hit["ref"] == "Incident #2" and hit["snippet"] == "Straße 5 cabling"


def test_a_failed_index_build_keeps_the_last_snapshot_and_index_together(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    before = client.get("/api/snapshot").json()
    fake.data["Ticket"][1]["name"] = "Renamed ticket"

    def boom(self):
        raise KeyError("id")
    monkeypatch.setattr(model.Builder, "search_index", boom)
    after = client.post("/api/refresh").json()
    assert after["error"] == "KeyError building the dashboard (see container log)"
    assert after["refreshed_at"] == before["refreshed_at"]
    assert after["records"] == before["records"]
    assert refs(client.get("/api/search", params={"q": "db1 slow"}).json()) == ["Incident #2"]


def test_search_runs_off_the_event_loop():
    # A plain def runs in FastAPI's threadpool, so a long scan doesn't hold up /healthz or the refresh loop.
    assert not inspect.iscoroutinefunction(main.search)


@pytest.mark.parametrize("text", [None, "", "<p>&nbsp;</p>", "&lt;p&gt;&amp;nbsp;&lt;/p&gt;", "<p> </p>\n"])
def test_blank_fields_are_blank(text):
    assert model._blank(text)


@pytest.mark.parametrize("text", ["<p>Written</p>", "&lt;p&gt;x&lt;/p&gt;", "0"])
def test_written_fields_are_not_blank(text):
    assert not model._blank(text)
