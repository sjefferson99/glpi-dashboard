"""Serves the real app with uvicorn on a free port, its GLPI client pointed at a FakeGlpi.

Shared by ui-tests/conftest.py and scripts/demo.py, so the browser sees the app exactly as it ships. It needs only
requirements.txt: the demo runs without the test dependencies.
"""
import asyncio
import contextlib
import socket
import threading
import time
from datetime import datetime
from unittest import mock

import uvicorn

import main
from fake_glpi import EXTRA, PUBLIC_URL, ROOTS


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def frozen(at):
    """A ``datetime`` class whose ``now()`` is always ``at``; patch it over ``main.datetime`` to stop the clock."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return at
    return Frozen


@contextlib.contextmanager
def serve(fake, port=0, now=None):
    """Runs the app in a background thread for the duration of the ``with`` block.

    The app gets its own empty state and refresh lock while it runs, and ``main`` is put back as it was after.

    Args:
        fake: The ``FakeGlpi`` the app reads; change its ``data`` and POST ``/api/refresh`` to re-read it.
        port: The port to listen on; 0 picks a free one.
        now: If given, the app's clock stops at this time, so "Updated" and every age stay the same.

    Yields:
        The app's base URL, e.g. ``http://127.0.0.1:50123``.

    Raises:
        RuntimeError: uvicorn stopped while starting (e.g. the port is in use) or didn't start within 15 seconds.
    """
    port = port or _free_port()
    patches = {"make_client": fake.client, "GLPI_PUBLIC_URL": PUBLIC_URL, "INTERNET_ROOTS": ROOTS,
               "INTERNET_EXTRA": EXTRA,
               "MANUAL_MIN_SECONDS": 0,       # every Refresh now re-reads the fake
               "state": {"snapshot": None, "search": None, "explorer": None, "error": None, "refreshed_at": None},
               "refresh_lock": asyncio.Lock(), **({"datetime": frozen(now)} if now else {})}
    with contextlib.ExitStack() as stack:
        for name, value in patches.items():
            stack.enter_context(mock.patch.object(main, name, value))
        # The lifespan stores its GLPI client on the one shared app and closes it on the way out, so an
        # app already being served elsewhere (the UI tests' own server) gets its client back afterwards.
        if hasattr(main.app.state, "glpi"):
            stack.callback(setattr, main.app.state, "glpi", main.app.state.glpi)
        server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive():
                    raise RuntimeError(f"uvicorn stopped while starting: is port {port} in use?")
                if time.monotonic() > deadline:
                    raise RuntimeError("uvicorn did not start within 15 seconds")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(10)
