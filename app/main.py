"""GLPI dashboard backend: reads GLPI, serves one JSON snapshot and the static page.

A background task rebuilds the snapshot every ``REFRESH_SECONDS``. If a refresh
fails, the last good snapshot stays, flagged with the error, and ``/healthz``
turns unhealthy once the data is more than three refreshes old. Nothing here
writes to GLPI.
"""
import asyncio
import contextlib
import html
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import model
from glpi import Glpi, GlpiError

log = logging.getLogger("glpi-dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _names(var):
    """Returns the comma-separated names in an environment variable, or an empty list."""
    return [s.strip() for s in os.environ.get(var, "").split(",") if s.strip()]


def _whole(var, default):
    """Returns a positive whole number from an environment variable.

    Unset or blank gives ``default``. Anything else that isn't a positive whole number logs a warning and
    gives ``default`` too, so a typo can't stop the app from starting.
    """
    raw = os.environ.get(var, "").strip()
    if not raw:
        return default
    if raw.isdecimal() and int(raw) > 0:
        return int(raw)
    log.warning("%s=%r is not a positive whole number; using %d", var, raw, default)
    return default


def _risk_areas(var="RISK_AREAS"):
    """Returns the risk bonus by area from ``Area:points`` pairs, comma-separated.

    Unset gives ``model.RISK_AREAS``; empty gives no bonus at all. A pair that doesn't parse is skipped with a
    warning. The last ``:`` splits a pair, so an area name may itself hold one.
    """
    raw = os.environ.get(var)
    if raw is None:
        return dict(model.RISK_AREAS)
    out = {}
    for pair in filter(None, (p.strip() for p in raw.split(","))):
        area, _, points = pair.rpartition(":")
        area, points = area.strip(), points.strip()
        if area and points.isdecimal():
            out[area] = int(points)
        else:
            log.warning("%s: skipping %r, expected Area:points", var, pair)
    return out


def _locale(var="LOCALE", default="en-GB"):
    """Returns a language tag (e.g. ``en-US``) for dates and sorting, or ``default`` with a warning if malformed.

    It goes into the page's ``<html lang>``, so only letters, digits and hyphens get through.
    """
    raw = os.environ.get(var, "").strip()
    if not raw:
        return default
    if LANG_TAG.fullmatch(raw):
        return raw
    log.warning("%s=%r is not a language tag like en-GB; using %s", var, raw, default)
    return default


LANG_TAG = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*")

REFRESH_SECONDS = _whole("REFRESH_SECONDS", 300)
GLPI_PUBLIC_URL = os.environ.get("GLPI_PUBLIC_URL", "https://glpi.example.com")
INTERNET_ROOTS = _names("INTERNET_FACING_ROOTS")
INTERNET_EXTRA = _names("INTERNET_FACING_EXTRA")
RISK_AREAS = _risk_areas()
STANDARD_CHANGE_AREA = os.environ.get("STANDARD_CHANGE_AREA", model.STANDARD_CHANGE_AREA).strip()
STALE_DAYS = _whole("STALE_DAYS", model.STALE_DAYS)
DASHBOARD_TITLE = os.environ.get("DASHBOARD_TITLE", "").strip() or "Network state"
LOCALE = _locale()
STATIC = Path(__file__).parent / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

# No ChangeValidation: GLPI only lets a profile see approval requests if it may also create or
# approve them. A change's own global_validation says whether it is waiting for approval.
ITIL = ("Ticket", "Problem", "Change", "ITILCategory", "Item_Ticket", "Item_Problem", "Change_Item",
        "Problem_Ticket", "Change_Problem", "RecurrentChange", "Project", "ProjectState", "Itil_Project",
        "ImpactRelation", "Ticket_User", "Group_Ticket", "Problem_User", "Group_Problem", "Change_User",
        "Change_Group")

# The Refresh now button re-reads GLPI at most this often; quicker clicks get the current snapshot.
MANUAL_MIN_SECONDS = 30

state = {"snapshot": None, "search": None, "explorer": None, "error": None, "refreshed_at": None}
refresh_lock = asyncio.Lock()
unmatched_areas = []      # what check_areas() last warned about


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


def check_areas(categories):
    """Warns about any area in ``RISK_AREAS`` or ``STANDARD_CHANGE_AREA`` that isn't an area in GLPI.

    Names must match a top-level category exactly, case included, so a typo would otherwise just do nothing.
    The warning is logged when the set of unmatched names changes, not at every refresh.

    Args:
        categories: ``ITILCategory`` rows, with ``completename``.
    """
    global unmatched_areas
    configured = set(RISK_AREAS) | ({STANDARD_CHANGE_AREA} if STANDARD_CHANGE_AREA else set())
    unmatched = sorted(configured - model.areas(categories))
    if unmatched and unmatched != unmatched_areas:
        log.warning("no top-level ITIL category in GLPI is named %s (RISK_AREAS / STANDARD_CHANGE_AREA): "
                    "names must match exactly, case included", ", ".join(map(repr, unmatched)))
    unmatched_areas = unmatched


async def refresh(glpi):
    """Rebuilds the snapshot, the search index and the explorer's records from GLPI and clears any recorded error."""
    data = await collect(glpi)
    check_areas(data["ITILCategory"])
    now = datetime.now()
    builder = model.Builder(data, now, GLPI_PUBLIC_URL, INTERNET_ROOTS, INTERNET_EXTRA, risk_areas=RISK_AREAS,
                            standard_change_area=STANDARD_CHANGE_AREA, stale_days=STALE_DAYS)
    snapshot = builder.build()
    index = builder.search_index()
    explorer = builder.explorer()
    # All are built before any is published, so a failure leaves the last set (and its time) together.
    state["snapshot"], state["search"], state["explorer"] = snapshot, index, explorer
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
    """Returns the current snapshot, or 503 before the first successful refresh.

    ``refreshed_at`` has milliseconds: the page compares it to tell refreshes apart, and two can fall in one second.
    """
    if state["snapshot"] is None:
        return JSONResponse({"error": state["error"] or "first refresh still running"}, status_code=503)
    return {**state["snapshot"], "refreshed_at": state["refreshed_at"].isoformat(timespec="milliseconds"),
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


@app.get("/api/search")
def search(q: str = Query("", max_length=model.SEARCH_MAX), closed: bool = False):
    """Searches what the last refresh read, closed records only if asked; 503 before the first refresh.

    No GLPI requests are made, so a search costs GLPI nothing and shows the data as of that refresh. It's a
    plain ``def``, so FastAPI runs the scan in its threadpool rather than holding up the event loop; that's
    safe because a refresh replaces the index whole, never changing one in use.
    """
    if state["search"] is None:
        return JSONResponse({"error": state["error"] or "first refresh still running"}, status_code=503)
    return model.search(state["search"], q, closed)


@app.get("/api/explorer")
async def explorer():
    """Returns every record, closed too, as of the last refresh, for the Record explorer; 503 before the first.

    It's apart from the snapshot because it holds the whole history: the page asks for it only while the
    explorer is showing, and again only when ``refreshed_at`` moves on.
    """
    if state["explorer"] is None:
        return JSONResponse({"error": state["error"] or "first refresh still running"}, status_code=503)
    return {"refreshed_at": state["refreshed_at"].isoformat(timespec="milliseconds"), "records": state["explorer"]}


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


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/index.html", methods=["GET", "HEAD"])
async def index():
    """Serves the page with its title and language filled in.

    They're written into the HTML rather than sent as data, so the CSP needs no inline script and the
    title shows before the first snapshot. The title is escaped; the language is checked by ``_locale()``.
    """
    page = INDEX.replace("{{LANG}}", html.escape(LOCALE)).replace("{{TITLE}}", html.escape(DASHBOARD_TITLE))
    return HTMLResponse(page)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
