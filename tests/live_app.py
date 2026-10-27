"""Serves the real app with uvicorn on a free port, its GLPI client pointed at a FakeGlpi.

Shared by ui-tests/conftest.py and scripts/demo.py, so the browser sees the app exactly as it ships.
"""
import contextlib
import socket
import threading
import time
from datetime import datetime

import pytest
import uvicorn

import main
from fake_glpi import EXTRA, PUBLIC_URL, ROOTS


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _frozen(at):
    """A ``datetime`` class whose ``now()`` is always ``at``."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return at
    return Frozen


@contextlib.contextmanager
def serve(fake, port=0, now=None):
    """Runs the app in a background thread for the duration of the ``with`` block.

    Args:
        fake: The ``FakeGlpi`` the app reads; change its ``data`` and POST ``/api/refresh`` to re-read it.
        port: The port to listen on; 0 picks a free one.
        now: If given, the app's clock stops at this time, so "Updated" and every age stay the same.

    Yields:
        The app's base URL, e.g. ``http://127.0.0.1:50123``.

    Raises:
        RuntimeError: uvicorn didn't start within 15 seconds.
    """
    mp = pytest.MonkeyPatch()
    if now:
        mp.setattr(main, "datetime", _frozen(now))
    mp.setattr(main, "make_client", fake.client)
    mp.setattr(main, "GLPI_PUBLIC_URL", PUBLIC_URL)
    mp.setattr(main, "INTERNET_ROOTS", ROOTS)
    mp.setattr(main, "INTERNET_EXTRA", EXTRA)
    mp.setattr(main, "MANUAL_MIN_SECONDS", 0)    # every Refresh now re-reads the fake
    port = port or _free_port()
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
        mp.undo()
