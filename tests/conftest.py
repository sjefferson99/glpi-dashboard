import asyncio

import pytest

import main
from fake_glpi import EXTRA, PUBLIC_URL, ROOTS, FakeGlpi


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake():
    return FakeGlpi()


@pytest.fixture
def app_state(monkeypatch, fake):
    """main.py with its GLPI client pointed at the fake, and its module state reset."""
    monkeypatch.setattr(main, "make_client", fake.client)
    monkeypatch.setattr(main, "GLPI_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setattr(main, "INTERNET_ROOTS", ROOTS)
    monkeypatch.setattr(main, "INTERNET_EXTRA", EXTRA)
    monkeypatch.setattr(main, "refresh_lock", asyncio.Lock())
    monkeypatch.setattr(main, "state", {"snapshot": None, "search": None, "error": None, "refreshed_at": None})
    return main.state
