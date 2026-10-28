"""The FastAPI app end to end, against the fake GLPI: refresh loop, endpoints, health, headers."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from fake_glpi import dataset


@pytest.fixture
def client(app_state):
    """The app with its lifespan running (background refresh against the fake)."""
    with TestClient(main.app) as c:
        c.post("/api/refresh")    # waits for the startup refresh, or runs one
        yield c


def test_snapshot_before_the_first_refresh_is_503(app_state):
    c = TestClient(main.app)      # no `with`: lifespan doesn't run, so nothing has refreshed
    r = c.get("/api/snapshot")
    assert r.status_code == 503
    assert r.json() == {"error": "first refresh still running"}


def test_snapshot(client):
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["refresh_seconds"] == main.REFRESH_SECONDS
    assert datetime.fromisoformat(body["refreshed_at"])
    assert {t["key"]: t["count"] for t in body["summary"]}["open-incidents"] == 3
    assert body["glpi_url"] == "https://glpi.example.test"


def test_collect_reads_ci_names_for_every_linked_type(client, fake):
    assert fake.count("Computer") == 1 and fake.count("Appliance") == 1
    cis = {c["name"] for c in client.get("/api/snapshot").json()["health"]["cis"]}
    assert cis == {"web1", "db1"}


def test_failed_refresh_keeps_the_last_snapshot(client, fake, monkeypatch):
    before = client.get("/api/snapshot").json()
    fake.down = True
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    r = client.post("/api/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] == "ConnectError: connection refused"
    assert body["summary"] == before["summary"]
    assert body["refreshed_at"] == before["refreshed_at"]


def test_recovery_clears_the_error(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.down = True
    client.post("/api/refresh")
    fake.down = False
    assert client.post("/api/refresh").json()["error"] is None


def test_first_refresh_failing_reports_the_error(app_state, fake):
    fake.down = True
    with TestClient(main.app) as c:
        r = c.post("/api/refresh")
    assert r.status_code == 503
    assert r.json() == {"error": "ConnectError: connection refused"}


def test_missing_rights_are_named_together(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.missing_rights = {"Project", "RecurrentChange"}
    err = client.post("/api/refresh").json()["error"]
    assert err == ("GlpiError: dashboard profile cannot read: RecurrentChange, Project (ERROR_RIGHT_MISSING)")


def test_unreadable_ci_type_shows_ids_instead_of_failing(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.missing_rights = {"Computer"}
    body = client.post("/api/refresh").json()
    assert body["error"] is None
    assert {c["name"] for c in body["health"]["cis"]} == {"Computer #1", "Computer #2"}


def test_unexpected_data_gives_a_generic_error_and_the_loop_survives(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    del fake.data["Ticket"][0]["priority"]          # model.build() raises KeyError
    body = client.post("/api/refresh").json()
    assert body["error"] == "KeyError building the dashboard (see container log)"
    fake.data = dataset()
    assert client.post("/api/refresh").json()["error"] is None


def test_errors_never_carry_tokens(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    for bad in ("app", "user"):
        g = fake.client()
        if bad == "app":
            g.app_token = "wrong"
        else:
            g.user_token = "wrong"
        client.app.state.glpi = g
        err = client.post("/api/refresh").json()["error"]
        assert err.startswith("GlpiError: initSession: HTTP ")
        assert "SECRET" not in err and "wrong" not in err


def test_manual_refresh_is_rate_limited(client, fake):
    reads = fake.count("Ticket")
    at = client.get("/api/snapshot").json()["refreshed_at"]
    r = client.post("/api/refresh")
    assert r.status_code == 200
    assert fake.count("Ticket") == reads
    assert r.json()["refreshed_at"] == at


def test_manual_refresh_rereads_glpi_once_the_data_is_old_enough(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    reads = fake.count("Ticket")
    client.post("/api/refresh")
    assert fake.count("Ticket") == reads + 1


def test_refresh_needs_post(client, fake, monkeypatch):
    # A GET falls through to the static mount (404) and must not re-read GLPI.
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    reads = fake.count("Ticket")
    assert client.get("/api/refresh").status_code == 404
    assert fake.count("Ticket") == reads


# --- /healthz -------------------------------------------------------------------------------------------------

def test_healthz_ok_says_only_ok_and_when(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "refreshed_at"} and r.json()["ok"] is True


def test_healthz_before_any_refresh(app_state):
    r = TestClient(main.app).get("/healthz")
    assert r.status_code == 503 and r.json() == {"ok": False}


def test_healthz_turns_unhealthy_after_three_refreshes_without_data(client, fake, app_state):
    app_state["refreshed_at"] = datetime.now() - timedelta(seconds=3 * main.REFRESH_SECONDS - 5)
    assert client.get("/healthz").status_code == 200
    app_state["refreshed_at"] = datetime.now() - timedelta(seconds=3 * main.REFRESH_SECONDS + 5)
    r = client.get("/healthz")
    assert r.status_code == 503 and r.json() == {"ok": False}


def test_healthz_says_nothing_about_errors(client, fake, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    fake.missing_rights = {"Project"}
    client.post("/api/refresh")
    assert "error" not in client.get("/healthz").text.lower()


# --- page and headers -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/app.js", "/style.css", "/logo.svg"])
def test_static_files_are_served(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/", "/api/snapshot", "/healthz", "/nope"])
def test_security_headers_on_every_response(client, path):
    h = client.get(path).headers
    assert h["Content-Security-Policy"] == ("default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                                            "base-uri 'none'; form-action 'none'")
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Referrer-Policy"] == "no-referrer"
    assert h["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/../main.py", "/%2e%2e/main.py", "/..%2fmain.py", "/static/../glpi.py"])
def test_no_path_traversal_out_of_static(client, path):
    assert client.get(path).status_code == 404


# --- configuration --------------------------------------------------------------------------------------------

def test_name_lists_from_the_environment(monkeypatch):
    monkeypatch.setenv("INTERNET_FACING_ROOTS", " reverse-proxy, ,edge ,")
    assert main._names("INTERNET_FACING_ROOTS") == ["reverse-proxy", "edge"]
    monkeypatch.delenv("INTERNET_FACING_ROOTS")
    assert main._names("INTERNET_FACING_ROOTS") == []


def test_make_client_reads_the_environment(monkeypatch):
    monkeypatch.setenv("GLPI_URL", "http://glpi.internal.test/")
    monkeypatch.setenv("GLPI_APP_TOKEN", "a")
    monkeypatch.setenv("GLPI_USER_TOKEN", "u")
    g = main.make_client()
    assert g.base == "http://glpi.internal.test/apirest.php"
    assert (g.app_token, g.user_token) == ("a", "u")


@pytest.mark.parametrize("raw,expected", [(None, 30), ("", 30), (" 45 ", 45), ("0", 30), ("-5", 30), ("ten", 30),
                                          ("1.5", 30), ("²", 30)])
def test_whole_numbers_fall_back_to_the_default(monkeypatch, caplog, raw, expected):
    if raw is None:
        monkeypatch.delenv("STALE_DAYS", raising=False)
    else:
        monkeypatch.setenv("STALE_DAYS", raw)
    assert main._whole("STALE_DAYS", 30) == expected
    assert ("STALE_DAYS" in caplog.text) == (raw not in (None, "", " 45 "))


@pytest.mark.parametrize("raw,expected", [
    (None, {"Security": 15}),
    ("", {}),
    ("Security:15, Network : 5 ,,", {"Security": 15, "Network": 5}),
    ("Ops: Night:10", {"Ops: Night": 10}),                  # the last colon splits
])
def test_risk_areas_from_the_environment(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("RISK_AREAS", raising=False)
    else:
        monkeypatch.setenv("RISK_AREAS", raw)
    assert main._risk_areas() == expected


def test_bad_risk_areas_are_skipped_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("RISK_AREAS", "Security:15,Network,:5,Hosting:-3,Ops:lots")
    assert main._risk_areas() == {"Security": 15}
    for bad in ("'Network'", "':5'", "'Hosting:-3'", "'Ops:lots'"):
        assert bad in caplog.text


@pytest.mark.parametrize("raw,expected", [(None, "en-GB"), ("", "en-GB"), ("en-US", "en-US"), ("de", "de"),
                                          ("zh-Hant-TW", "zh-Hant-TW"), ('en"><script>', "en-GB"),
                                          ("en_GB", "en-GB"), ("e", "en-GB")])
def test_locale_must_be_a_language_tag(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LOCALE", raising=False)
    else:
        monkeypatch.setenv("LOCALE", raw)
    assert main._locale() == expected


def test_refresh_uses_the_site_settings(client, monkeypatch):
    monkeypatch.setattr(main, "MANUAL_MIN_SECONDS", 0)
    monkeypatch.setattr(main, "RISK_AREAS", {})
    monkeypatch.setattr(main, "STANDARD_CHANGE_AREA", "")
    monkeypatch.setattr(main, "STALE_DAYS", 60)
    body = client.post("/api/refresh").json()
    assert "Change:4" in body["lists"]["risks-all"]["refs"]
    assert body["records"]["Problem:1"]["risk"]["score"] == 53
    assert body["lists"]["stale"]["title"] == "Open records not updated in 60 days"


# --- the page -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_page_has_the_default_title_and_language(client, path):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert '<html lang="en-GB">' in r.text
    assert "<title>Network state</title>" in r.text and 'class="logo">Network state</h1>' in r.text
    assert "{{" not in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_page_title_and_language_are_configurable_and_escaped(client, monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_TITLE", 'Ops & "IT" <script>alert(1)</script> {{LANG}}')
    monkeypatch.setattr(main, "LOCALE", "en-US")
    text = client.get("/").text
    assert '<html lang="en-US">' in text
    assert "<title>Ops &amp; &quot;IT&quot; &lt;script&gt;alert(1)&lt;/script&gt; {{LANG}}</title>" in text
    assert "<script>alert" not in text


def test_page_answers_head(client):
    assert client.head("/").status_code == 200
