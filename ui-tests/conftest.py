"""Serves the real app with uvicorn on a free port, fed by the fake GLPI, for Playwright (headless Chromium).

The server and fake live for the whole session; the `dashboard` fixture resets the fake and
re-reads it before each test, so tests don't depend on each other.
"""
import httpx
import pytest

from fake_glpi import FakeGlpi, dataset
from live_app import serve


@pytest.fixture(scope="session")
def fake_glpi():
    return FakeGlpi()


@pytest.fixture(scope="session")
def base_url(fake_glpi):
    with serve(fake_glpi) as url:
        yield url


@pytest.fixture
def dashboard(base_url, fake_glpi):
    """A fresh snapshot of the default dataset; tests may change `fake_glpi` and click Refresh now."""
    fake_glpi.data = dataset()
    fake_glpi.down = False
    fake_glpi.missing_rights = set()
    r = httpx.post(base_url + "/api/refresh", timeout=10)
    assert r.status_code == 200 and r.json()["error"] is None
    return fake_glpi


@pytest.fixture
def console_errors(page):
    """Console errors and CSP violations seen by the page."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors
