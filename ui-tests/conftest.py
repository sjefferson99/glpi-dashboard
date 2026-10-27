"""Serves the real app with uvicorn on a free port, fed by the fake GLPI, for Playwright (headless Chromium).

The server and fake live for the whole session; the `dashboard` fixture resets the fake and
re-reads it before each test, so tests don't depend on each other.
"""
import socket
import threading
import time

import httpx
import pytest
import uvicorn

import main
from fake_glpi import EXTRA, PUBLIC_URL, ROOTS, FakeGlpi, dataset


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def fake_glpi():
    return FakeGlpi()


@pytest.fixture(scope="session")
def base_url(fake_glpi):
    mp = pytest.MonkeyPatch()
    mp.setattr(main, "make_client", fake_glpi.client)
    mp.setattr(main, "GLPI_PUBLIC_URL", PUBLIC_URL)
    mp.setattr(main, "INTERNET_ROOTS", ROOTS)
    mp.setattr(main, "INTERNET_EXTRA", EXTRA)
    mp.setattr(main, "MANUAL_MIN_SECONDS", 0)    # every Refresh now re-reads the fake
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield url
    server.should_exit = True
    thread.join(10)
    mp.undo()


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
