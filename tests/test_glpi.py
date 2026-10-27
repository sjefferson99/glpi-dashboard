"""The GLPI v1 client against the fake API: login, paging, session expiry, error hygiene."""
import httpx
import pytest

import glpi
from fake_glpi import APP_TOKEN, USER_TOKEN, FakeGlpi
from glpi import Glpi, GlpiError

pytestmark = pytest.mark.anyio


async def test_reads_every_row_with_one_login(fake):
    g = fake.client()
    rows = await g.all("Ticket")
    assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]
    assert fake.calls == ["/initSession", "/Ticket"]
    assert len(fake.sessions) == 1


async def test_pages_until_range_exceeds_total(monkeypatch):
    # Exactly two full pages: the third request gets GLPI's ERROR_RANGE_EXCEED_TOTAL, read as "no more".
    monkeypatch.setattr(glpi, "PAGE", 2)
    fake = FakeGlpi({"Computer": [{"id": i, "name": f"pc{i}"} for i in range(4)]})
    rows = await fake.client().all("Computer")
    assert [r["id"] for r in rows] == [0, 1, 2, 3]
    assert fake.count("Computer") == 3


async def test_short_last_page_stops_without_extra_request(monkeypatch):
    monkeypatch.setattr(glpi, "PAGE", 2)
    fake = FakeGlpi({"Computer": [{"id": i, "name": f"pc{i}"} for i in range(3)]})
    rows = await fake.client().all("Computer")
    assert len(rows) == 3
    assert fake.count("Computer") == 2


async def test_empty_type_is_empty_list():
    fake = FakeGlpi({"Project": []})
    assert await fake.client().all("Project") == []


async def test_asks_for_unexpanded_dropdowns():
    seen = []

    def handler(request):
        if request.url.path.endswith("/initSession"):
            return httpx.Response(200, json={"session_token": "s"})
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    g = Glpi("http://glpi/", APP_TOKEN, USER_TOKEN)
    g.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await g.all("Ticket")
    assert seen == [{"range": "0-499", "expand_dropdowns": "false"}]


async def test_expired_session_logs_in_again_once(fake):
    g = fake.client()
    await g.all("Ticket")
    fake.expire_sessions = 1
    rows = await g.all("Problem")
    assert len(rows) == 2
    assert fake.calls.count("/initSession") == 2


async def test_session_expiring_twice_in_a_row_is_an_error(fake):
    g = fake.client()
    fake.expire_sessions = 2
    with pytest.raises(GlpiError, match="ERROR_SESSION_TOKEN_INVALID"):
        await g.all("Ticket")


async def test_right_missing_is_reported_by_code(fake):
    fake.missing_rights = {"Project"}
    with pytest.raises(GlpiError, match=r"^GET /Project: HTTP 401 ERROR_RIGHT_MISSING$"):
        await fake.client().all("Project")


@pytest.mark.parametrize("app_token,user_token,code", [
    ("wrong", USER_TOKEN, "ERROR_WRONG_APP_TOKEN_PARAMETER"),
    (APP_TOKEN, "wrong", "ERROR_GLPI_LOGIN_USER_TOKEN"),
])
async def test_login_failure_names_the_code_and_never_a_token_or_body(fake, app_token, user_token, code):
    g = Glpi("http://glpi", app_token, user_token)
    g.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    with pytest.raises(GlpiError) as e:
        await g.all("Ticket")
    msg = str(e.value)
    assert msg.startswith("initSession: HTTP ") and msg.endswith(code)
    # The fake's error bodies echo the real tokens: none of that may reach the message.
    assert "SECRET" not in msg and "wrong" not in msg and "token " not in msg


@pytest.mark.parametrize("body", [b"<html>Server error SECRET</html>", b'{"not": "a list"}', b'["no code here"]'])
async def test_non_glpi_error_body_gives_no_code(body):
    def handler(request):
        if request.url.path.endswith("/initSession"):
            return httpx.Response(200, json={"session_token": "s"})
        return httpx.Response(500, content=body)

    g = Glpi("http://glpi", APP_TOKEN, USER_TOKEN)
    g.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GlpiError) as e:
        await g.all("Ticket")
    assert str(e.value) == "GET /Ticket: HTTP 500"


@pytest.mark.parametrize("itemtype", [
    "Ticket/1", "../initSession", "Ticket?x=1", "Glpi\\Asset", "", "Tické",
    "Ticket\n",    # `$` would allow a trailing newline; the check must be a full match
])
async def test_rejects_unsafe_itemtype_without_a_request(fake, itemtype):
    with pytest.raises(GlpiError, match="bad itemtype"):
        await fake.client().all(itemtype)
    assert fake.calls == []


async def test_close_kills_the_session(fake):
    g = fake.client()
    await g.all("Ticket")
    await g.close()
    assert fake.calls[-1] == "/killSession"
    assert fake.sessions == set()


async def test_close_tolerates_glpi_being_down(fake):
    g = fake.client()
    await g.all("Ticket")
    fake.down = True
    await g.close()   # no exception
    assert g.http.is_closed


async def test_close_without_session_makes_no_request(fake):
    g = fake.client()
    await g.close()
    assert fake.calls == []
