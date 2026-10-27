# glpi-dashboard

A read-only web page showing the state of your IT service management in [GLPI](https://glpi-project.org/):
what's open, what's at risk, and what's in flight. GLPI is the only source. Monitoring tools that feed GLPI
(through their own integrations) stay the place for real-time data.

## What it shows

- **Summary**: open incidents, requests, problems and changes; High-priority records; records without a
  category.
- **Health at a glance**: open incidents and problems per area (the top level of the ITIL category tree) and
  per linked CI, rated red/amber/green. Red means any High or above. Amber means any incident or Medium
  problem. Anything else is green. The state is always shown as an icon and a word, not colour alone.
- **Ranked risks**: open problems and changes (not Applied, not standard changes) by a score made of
  priority, security area, an internet-facing CI, age, and open incidents on a problem. The weights are
  `RISK_*` in `app/model.py`, and the "Why" column shows each record's breakdown, so they're easy to tune.
- **In flight**: changes awaiting approval, at Accepted/Testing/Qualification, or Applied but not closed;
  projects with progress and linked records; recurring changes by next creation date.

**Every number is a link** (`#list=<key>`) to the list of records behind it, each opening in GLPI. The
number is computed as the length of that list, so the two can't disagree. Lists can be bookmarked.

"Internet-facing" comes from GLPI's impact graph: the CIs impacted by `INTERNET_FACING_ROOTS` (typically your
reverse proxy), plus the CIs named in `INTERNET_FACING_EXTRA` (e.g. the firewall).

## How it works

`app/main.py` (FastAPI) refreshes a snapshot from GLPI every `REFRESH_SECONDS` (300) in the background. It
serves the snapshot at `/api/snapshot`, along with the static page (`app/static/`, no build step).

- **If GLPI is unreachable**, the last snapshot stays, with a banner.
- **`/healthz`** fails once the data is three refreshes old.
- **Refresh now** on the page (`POST /api/refresh`) re-reads GLPI at once, at most every 30 s
  (`MANUAL_MIN_SECONDS`). A click during a running refresh waits for it.

It uses the **GLPI v1 API only** (`app/glpi.py`), because v2 has no endpoints for the links between records
and CIs or projects. A refresh makes about 20 calls.

## GLPI setup

- **A user, e.g. `dashboard`, on the Standard interface.** The Simplified interface hides most rights. Give
  it a read-only profile with these rights:
  - see all tickets, problems and changes, recurring changes and projects;
  - assets (computers, network devices, appliances, clusters, peripherals);
  - dropdowns (ITIL categories, project states);
  - impact analysis.

  Don't give it approval rights. GLPI only shows approval requests to profiles that may create or approve
  them, so "awaiting approval" uses each change's own `global_validation`.
- **That user's API token**, from Remote access keys in the user's settings.
- A missing right shows in the container log as `dashboard profile cannot read: <types>
  (ERROR_RIGHT_MISSING)`.
- **An API client, e.g. `dashboard`** (Setup > General > API): active, with its **app token**. Its IPv4
  range must cover the address GLPI sees for this container, which is usually the Docker network's subnet
  when both run on the same Docker network.

## Configuration

Copy `.env.example` to `.env` and fill it in. Keep `.env` readable only by admins; it holds both tokens.

| Variable | Meaning |
|---|---|
| `GLPI_URL` | GLPI as the container reaches it, e.g. `http://glpi` on a shared Docker network |
| `GLPI_PUBLIC_URL` | GLPI as a browser reaches it; every link on the page points here |
| `GLPI_APP_TOKEN` | The API client's app token |
| `GLPI_USER_TOKEN` | The read-only user's API token |
| `REFRESH_SECONDS` | How often to re-read GLPI (default 300) |
| `INTERNET_FACING_ROOTS` | Comma-separated CI names whose impacted CIs are internet-facing (default none) |
| `INTERNET_FACING_EXTRA` | Further comma-separated CI names that are internet-facing (default none) |

## Running

```bash
docker compose up -d --build
docker compose ps                    # expect (healthy)
docker compose logs | grep -E "refreshed|failed|cannot read|unavailable"   # expect "refreshed: N records"
```

The image is built from `Dockerfile`, which uses a pinned `python:*-slim` base and pinned
`requirements.txt`, and runs `apt-get upgrade` for Debian fixes. **Rebuild (`--build`) after any change.**
The container runs read-only as UID 10001 with all capabilities dropped. It holds no data to back up.

**The page shows internal GLPI data and has no login of its own.** `compose.yml` publishes it on localhost
only. To serve it more widely, put it behind a reverse proxy that authenticates users. `compose.yml` has a
commented Traefik example. Leave `/healthz` unauthenticated if a monitor needs it: it answers only ok and a
time.

**Monitoring:** an HTTP monitor on `/healthz` turns red when GLPI can't be read for three refreshes.

## Tests

The tests need no GLPI and no Docker.

- **`tests/`** (pytest) drives the real GLPI client and app against a fake GLPI v1 API
  (`tests/fake_glpi.py`).
- **`ui-tests/`** runs Playwright in headless Chromium against the app served by uvicorn, with the same
  fake.

```powershell
uv venv --python 3.14 .venv
uv pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m pytest            # unit + API
.venv\Scripts\python.exe -m pytest ui-tests   # browser
```
