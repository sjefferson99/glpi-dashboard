# GLPI Dashboard

A read-only web page showing the state of your IT service management in [GLPI](https://glpi-project.org/):
what's open, what's at risk, and what's in flight. GLPI is the only source. Monitoring tools that feed GLPI
(through their own integrations) stay the place for real-time data.

This project is just my own view of my estate that suits how I work; There is no customisation capability in
the app itself. However, with good categorisation and prioritisation it provides another view on your GLPI
instance. And in the magic world of AI we now live in, forking and adjusting the design to tweak to your
requirements is trivial and a better solution right now than me adding customisation options in directly.

## What it shows

The page has five tabs. The browser remembers the last one you chose.

- **Summary**: open incidents, requests, problems and changes, and High-priority records.
  - **Record quality**: open records missing something the GLPI working rules ask for. That's no category;
    no CI (incidents, problems and changes only, since requests often have none); no technician or group
    assigned; no update in 30 days (`STALE_DAYS`); problems linked to no incident and no change; and, for
    changes other than standard changes, still in New with no approval requested, or an empty Impacts,
    Deployment plan, Backup plan or Checklist. Each tile has a short label; hover or focus it for half a
    second to see the full rule, and press Escape to hide it.
  - **Health at a glance**: open incidents and problems per area (the top level of the ITIL category tree),
    rated red/amber/green. Red means any High or above. Amber means any incident or Medium problem. Anything
    else is green. The state is always shown as an icon and a word, not colour alone.
- **In flight**: open incidents, requests and problems by status; changes awaiting approval, at
  Accepted/Testing/Qualification, or Applied but not closed; and a Projects tile that lists each project
  with its progress and linked records.
- **Recurring changes**: the open changes made by each active recurring change (e.g. monthly patching), and
  the schedule (next creation and due dates). GLPI doesn't link a change back to the recurring change that
  created it, so a change counts if its title starts with the recurring change's name (ignoring case; the
  longest matching name wins).
- **CMDB**: the hosts and stacks (CIs) with open incidents or problems, rated like the areas.
- **Risk analysis**: open problems and changes (not Applied, not standard changes), as a two-ring chart
  beside a table of the same counts. The inner ring splits them by priority, and the outer ring splits each
  priority into problems and changes. **Record type** swaps the rings. **Colours** picks how priority is
  shown: *Traffic light* (green for Very low through to red for Major) or *Heat* (one red, deeper for higher
  priority). The browser remembers both choices. Each segment and each number in the table opens its
  records, ranked by a score made of priority, security area, an internet-facing CI, age and open incidents
  on a problem; the table's All / All opens every one. The weights are `RISK_*` in `app/model.py`, and the
  "Why" column shows each record's breakdown, so they're easy to tune. The table names every priority, so
  colour is never the only cue: six traffic-light steps can't all stay distinct for colour-blind readers.

Each kind of record has its own colour, used the same way everywhere: incidents blue, requests teal, problems
orange, changes green and projects violet. Tiles that flag an issue across kinds (High priority, and record
quality checks such as No CI) are red; one that is about a single kind (e.g. Orphan problems) keeps that
kind's colour. It shows as a tile's light tint,
edge and number, a dot by each In flight group, a tinted reference chip in every list, and the incident, problem and
change counts on area cards and in the CMDB table. The kind is always written out too, so colour is never
the only cue, and every colour meets WCAG AA contrast in both light and dark themes. A tile with nothing in
it is dimmed: no fill, a dashed grey border and a grey number.

**Every number is a link** (`#list=<key>`) to the list behind it, each entry opening in GLPI. The number is
computed as the length of that list, so the two can't disagree. Lists can be bookmarked. Record lists show
when each record was opened and last updated.

Every table sorts by any column: click a header, and click again to reverse. Tables show 10 rows, with
**Show more** and **Show all** below, and **Show less** to go back to 10. Escape, ✕ or a click outside a list closes it.

**Search**: the box at the top right, beside the update time, searches the open tickets, problems and changes,
the projects and the CIs the dashboard read. Tick **Include closed** to search closed records too. It's off by
default, which also keeps searches quicker. Pause typing for half a second, or press Enter, and the results open over
the page. They have their own search box (✕ clears it) and Include closed, to refine them, and say which refresh
they search. Their **Refresh now** button re-reads GLPI and searches again. A result must contain every word typed
(ignoring case), in its title, description, category, status, reference or linked CI names, or for a CI its
serial, inventory number or comment. An exact `#id` comes first, then title matches, then everything but closed
records, most recently updated first. Words found only in the description are shown in context. Up to 100
results are listed, with the total. Searches can be bookmarked (`#search=<words>`, plus `&closed=1`). Only CIs of
the types linked to a record (or in the impact graph) are searched, since those are the ones the dashboard reads.
Followups, tasks and solutions aren't searched: reading them would cost GLPI many more requests. Search shows
description text, which the rest of the page doesn't, so anyone who can open the dashboard can read the
descriptions.

"Internet-facing" comes from GLPI's impact graph: the CIs impacted by `INTERNET_FACING_ROOTS` (typically your
reverse proxy), plus the CIs named in `INTERNET_FACING_EXTRA` (e.g. the firewall).

## How it works

`app/main.py` (FastAPI) refreshes a snapshot from GLPI every `REFRESH_SECONDS` (300) in the background. It
serves the snapshot at `/api/snapshot`, along with the static page (`app/static/`, no build step).
Each refresh also keeps a search index in memory, and `/api/search?q=<words>` (with `&closed=true` for closed records too) searches that, so a search
makes no GLPI requests and shows the data as of the last refresh.

- **If GLPI is unreachable**, the last snapshot stays, with a banner.
- **`/healthz`** fails once the data is three refreshes old.
- **Refresh now** (the circular-arrows button at the top right, beside the update time; `POST /api/refresh`)
  re-reads GLPI at once, at most every 30 s
  (`MANUAL_MIN_SECONDS`). A click during a running refresh waits for it.

It uses the **GLPI v1 API only** (`app/glpi.py`), because v2 has no endpoints for the links between records
and CIs or projects. A refresh makes about 30 calls.

## GLPI setup

- **A user, e.g. `dashboard`, on the Standard interface.** The Simplified interface hides most rights. Give
  it a read-only profile with these rights:
  - see all tickets, problems and changes (including who and which group they're assigned to), recurring
    changes and projects;
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

The image is published to GHCR as `ghcr.io/sjefferson99/glpi-dashboard`. Put `compose.yml` and your `.env`
in one folder, then:

```bash
docker compose pull && docker compose up -d
docker compose ps                    # expect (healthy)
docker compose logs | grep -E "refreshed|failed|cannot read|unavailable"   # expect "refreshed: N records"
```

To upgrade, run the same `pull && up -d`.

| Tag | Built from |
|---|---|
| `latest` | The latest commit on `main`, or the latest release |
| `X.Y.Z`, `X.Y` | A release tag `vX.Y.Z` |
| `sha-<commit>` | One exact commit |

Pin `X.Y.Z` or `sha-*` in `compose.yml` to control when upgrades happen.

To build from a checkout instead: `docker compose -f compose.yml -f compose.dev.yml up -d --build`.

The image uses a pinned `python:*-slim` base and pinned `requirements.txt`, and runs `apt-get upgrade` for
Debian fixes. CI (`.github/workflows/container.yml`) runs both test suites before building. A PR only
builds the image; a push to `main` or a `v*.*.*` tag publishes it. The container runs read-only as UID
10001 with all capabilities dropped. It holds no data to back up.

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
