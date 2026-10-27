"""GLPI dashboard backend: reads GLPI, serves one JSON snapshot and the static page.

A background task rebuilds the snapshot every ``REFRESH_SECONDS``. If a refresh
fails, the last good snapshot stays, flagged with the error, and ``/healthz``
turns unhealthy once the data is more than three refreshes old. Nothing here
writes to GLPI.
"""
import asyncio
import contextlib
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import model
from glpi import Glpi, GlpiError

log = logging.getLogger("glpi-dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _names(var):
    """Returns the comma-separated names in an environment variable, or an empty list."""
    return [s.strip() for s in os.environ.get(var, "").split(",") if s.strip()]


REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "300"))
GLPI_PUBLIC_URL = os.environ.get("GLPI_PUBLIC_URL", "https://glpi.example.com")
INTERNET_ROOTS = _names("INTERNET_FACING_ROOTS")
INTERNET_EXTRA = _names("INTERNET_FACING_EXTRA")
STATIC = Path(__file__).parent / "static"

# No ChangeValidation: GLPI only lets a profile see approval requests if it may also create or
# approve them. A change's own global_validation says whether it is waiting for approval.
ITIL = ("Ticket", "Problem", "Change", "ITILCategory", "Item_Ticket", "Item_Problem", "Change_Item",
        "Problem_Ticket", "Change_Problem", "RecurrentChange", "Project", "ProjectState", "Itil_Project",
        "ImpactRelation", "Ticket_User", "Group_Ticket", "Problem_User", "Group_Problem", "Change_User",
        "Change_Group")

# The Refresh now button re-reads GLPI at most this often; quicker clicks get the current snapshot.
MANUAL_MIN_SECONDS = 30

state = {"snapshot": None, "error": None, "refreshed_at": None}
refresh_lock = asyncio.Lock()


def make_client():
    """Returns a GLPI client configured from the environment."""
    return Glpi(os.environ.get("GLPI_URL", "http://glpi"),
                os.environ["GLPI_APP_TOKEN"], os.environ["GLPI_USER_TOKEN"])


async def collect(glpi):
    """Reads everything the dashboard needs from GLPI.

    Every ITIL list is read before failing, so a single error names all the types the
    profile can't read. CI names are then read for each type that appears in a link
    or the impact graph.

    Args:
        glpi: A ``Glpi`` client.

    Returns:
        A dict of rows by itemtype, plus ``"cis"``: CI rows by CI itemtype.

    Raises:
        GlpiError: An ITIL list couldn't be read.
    """
    data, missing = {}, []
    for t in ITIL:
        try:
            data[t] = await glpi.all(t)
        except GlpiError as e:
            if "ERROR_RIGHT_MISSING" not in str(e):
                raise
            missing.append(t)
    if missing:
        raise GlpiError(f"dashboard profile cannot read: {', '.join(missing)} (ERROR_RIGHT_MISSING)")
    linked = {r["itemtype"] for t in ("Item_Ticket", "Item_Problem", "Change_Item") for r in data[t]}
    linked |= {r[f] for r in data["ImpactRelation"] for f in ("itemtype_source", "itemtype_impacted")}
    data["cis"] = {}
    for itemtype in sorted(linked):
        try:
            data["cis"][itemtype] = await glpi.all(itemtype)
        except GlpiError as e:
            # A CI type the profile can't read shows as "Type #id" rather than failing the refresh.
            log.warning("CI names unavailable for %s: %s", itemtype, e)
            data["cis"][itemtype] = []
    return data


async def refresh(glpi):
    """Rebuilds the snapshot from GLPI and clears any recorded error."""
    data = await collect(glpi)
    now = datetime.now()
    state["snapshot"] = model.build(data, now, GLPI_PUBLIC_URL, INTERNET_ROOTS, INTERNET_EXTRA)
    state["refreshed_at"] = now
    state["error"] = None
    log.info("refreshed: %d records", len(state["snapshot"]["records"]))


async def refresh_once(glpi):
    """Runs one refresh at a time (timer or button), never raising.

    A failure keeps the last snapshot and records the error for the page.
    """
    async with refresh_lock:
        try:
            await refresh(glpi)
        except (GlpiError, httpx.HTTPError) as e:
            state["error"] = f"{type(e).__name__}: {e}"
            log.error("refresh failed: %s", state["error"])
        except Exception as e:  # noqa: BLE001 - unexpected GLPI data must not end the loop for good
            state["error"] = f"{type(e).__name__} building the dashboard (see container log)"
            log.exception("refresh failed")


async def refresh_loop(glpi):
    """Refreshes now, then every ``REFRESH_SECONDS``, until cancelled."""
    while True:
        await refresh_once(glpi)
        await asyncio.sleep(REFRESH_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app):
    """Starts the refresh loop with the app and stops it, and the GLPI session, on shutdown."""
    glpi = make_client()
    app.state.glpi = glpi
    task = asyncio.create_task(refresh_loop(glpi))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await glpi.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request, call_next):
    """Adds a strict CSP and related headers to every response."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/snapshot")
async def snapshot():
    """Returns the current snapshot, or 503 before the first successful refresh."""
    if state["snapshot"] is None:
        return JSONResponse({"error": state["error"] or "first refresh still running"}, status_code=503)
    return {**state["snapshot"], "refreshed_at": state["refreshed_at"].isoformat(timespec="seconds"),
            "refresh_seconds": REFRESH_SECONDS, "error": state["error"]}


@app.post("/api/refresh")
async def manual_refresh():
    """Refresh now: waits for a refresh already running, else re-reads GLPI unless the data is very fresh."""
    if refresh_lock.locked():
        async with refresh_lock:
            pass
    else:
        at = state["refreshed_at"]
        if at is None or (datetime.now() - at).total_seconds() >= MANUAL_MIN_SECONDS:
            await refresh_once(app.state.glpi)
    return await snapshot()


@app.get("/healthz")
async def healthz():
    """Says whether the data is recent: 200 if refreshed within three intervals, else 503.

    Meant to be reachable without authentication by a monitor, so it says nothing
    beyond ok and when.
    """
    at = state["refreshed_at"]
    if at is None or (datetime.now() - at).total_seconds() > 3 * REFRESH_SECONDS:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True, "refreshed_at": at.isoformat(timespec="seconds")}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
