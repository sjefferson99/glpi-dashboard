"""A fake GLPI v1 API and a small, fixed GLPI dataset, shared by tests/ and ui-tests/.

FakeGlpi.handler is an httpx.MockTransport handler, so tests drive the real Glpi
client (session, paging, error codes) without a GLPI. The dataset is chosen so
every view has something in it; test_model.py documents the numbers it yields.
"""
import json
import re
from datetime import datetime, timedelta

import httpx

from glpi import Glpi

NOW = datetime(2026, 10, 27, 12, 0, 0)
APP_TOKEN = "app-token-SECRET"
USER_TOKEN = "user-token-SECRET"
PUBLIC_URL = "https://glpi.example.test"
ROOTS = ["reverse-proxy"]
EXTRA = ["firewall"]


def _d(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _itil(id_, name, status, priority, cat, days, **extra):
    return {"id": id_, "name": name, "status": status, "priority": priority, "urgency": priority,
            "impact": priority, "itilcategories_id": cat, "date": _d(days), **extra}


def dataset():
    """Every itemtype the dashboard reads, as GLPI v1 returns it (unexpanded dropdowns)."""
    return {
        "ITILCategory": [
            {"id": 1, "completename": "Security"},
            {"id": 2, "completename": "Security > Certificates"},
            {"id": 3, "completename": "Network"},
            {"id": 4, "completename": "Standard change"},
            {"id": 5, "completename": "Hosting"},
        ],
        "Ticket": [
            _itil(1, "Certificate expired on web1", 2, 4, 2, 10, type=1),
            _itil(2, "db1 slow", 1, 2, 3, 3, type=1),
            _itil(3, "New user account", 1, 3, 0, 1, type=2),
            _itil(4, "Old outage", 6, 5, 3, 100, type=1),
            _itil(5, "Uncategorised blip", 4, 3, 0, 2, type=1),
        ],
        "Problem": [
            _itil(1, "Recurring certificate failures", 7, 3, 1, 90),
            _itil(2, "Closed problem", 6, 4, 3, 30),
        ],
        "Change": [
            _itil(1, "Renew wildcard certificate", 10, 4, 1, 5, global_validation=2),
            _itil(2, "Firewall rule review", 7, 3, 3, 200, global_validation=3),
            _itil(3, "Patch db1", 5, 2, 3, 20, global_validation=3),
            _itil(4, "Monthly patching", 1, 3, 4, 4, global_validation=1),
            _itil(5, "Cancelled change", 14, 3, 3, 50, global_validation=1),
        ],
        "Item_Ticket": [
            {"id": 1, "itemtype": "Computer", "items_id": 1, "tickets_id": 1},
            {"id": 2, "itemtype": "Computer", "items_id": 2, "tickets_id": 2},
        ],
        "Item_Problem": [{"id": 1, "itemtype": "Computer", "items_id": 1, "problems_id": 1}],
        "Change_Item": [
            {"id": 1, "itemtype": "Computer", "items_id": 1, "changes_id": 1},
            {"id": 2, "itemtype": "Computer", "items_id": 3, "changes_id": 2},
            {"id": 3, "itemtype": "Computer", "items_id": 2, "changes_id": 3},
        ],
        "Problem_Ticket": [
            {"id": 1, "problems_id": 1, "tickets_id": 1},
            {"id": 2, "problems_id": 1, "tickets_id": 4},
        ],
        "RecurrentChange": [
            {"id": 1, "name": "Monthly patching", "is_active": 1, "periodicity": "1MONTH",
             "next_creation_date": "2026-11-01 00:00:00", "create_before": 2 * 86400},
            {"id": 2, "name": "Retired check", "is_active": 0, "periodicity": "1WEEK",
             "next_creation_date": "2026-10-30 00:00:00", "create_before": 0},
            {"id": 3, "name": "Unscheduled review", "is_active": 1, "periodicity": "",
             "next_creation_date": None, "create_before": None},
        ],
        "Project": [{"id": 1, "name": "Certificate automation", "code": "PRJ1",
                     "projectstates_id": 2, "percent_done": 40}],
        "ProjectState": [{"id": 2, "name": "Processing"}],
        "Itil_Project": [
            {"id": 1, "itemtype": "Change", "items_id": 1, "projects_id": 1},
            {"id": 2, "itemtype": "Problem", "items_id": 1, "projects_id": 1},
            {"id": 3, "itemtype": "Ticket", "items_id": 4, "projects_id": 1},
            {"id": 4, "itemtype": "Change", "items_id": 99, "projects_id": 1},
        ],
        "ImpactRelation": [{"id": 1, "itemtype_source": "Appliance", "items_id_source": 1,
                            "itemtype_impacted": "Computer", "items_id_impacted": 1}],
        "Computer": [{"id": 1, "name": "web1"}, {"id": 2, "name": "db1"}, {"id": 3, "name": "firewall"}],
        "Appliance": [{"id": 1, "name": "reverse-proxy"}],
    }


def model_input(ds=None):
    """The dict main.collect() hands to model.build(): ITIL lists plus 'cis' by CI type."""
    ds = ds or dataset()
    cis = {t: ds.pop(t) for t in ("Computer", "Appliance")}
    return {**ds, "cis": cis}


def _err(status, code, detail="detail"):
    return httpx.Response(status, json=[code, detail])


class FakeGlpi:
    """In-memory GLPI v1. Tweak the attributes to simulate failures; `calls` records every path."""

    def __init__(self, data=None):
        self.data = data if data is not None else dataset()
        self.missing_rights = set()   # itemtypes answered with ERROR_RIGHT_MISSING
        self.down = False             # every request fails to connect
        self.expire_sessions = 0      # next N data requests answer ERROR_SESSION_TOKEN_INVALID
        self.sessions = set()
        self.calls = []
        self._n = 0

    def handler(self, request):
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path.removeprefix("/apirest.php")
        self.calls.append(path)
        if request.headers.get("App-Token") != APP_TOKEN:
            return _err(400, "ERROR_WRONG_APP_TOKEN_PARAMETER", f"bad token {APP_TOKEN}")
        if path == "/initSession":
            if request.headers.get("Authorization") != "user_token " + USER_TOKEN:
                return _err(401, "ERROR_GLPI_LOGIN_USER_TOKEN", f"secret {USER_TOKEN}")
            self._n += 1
            token = f"session-{self._n}"
            self.sessions.add(token)
            return httpx.Response(200, json={"session_token": token})
        session = request.headers.get("Session-Token")
        if session not in self.sessions:
            return _err(401, "ERROR_SESSION_TOKEN_INVALID")
        if path == "/killSession":
            self.sessions.discard(session)
            return httpx.Response(200, json=True)
        if self.expire_sessions:
            self.expire_sessions -= 1
            self.sessions.discard(session)
            return _err(401, "ERROR_SESSION_TOKEN_INVALID")
        itemtype = path.lstrip("/")
        if itemtype in self.missing_rights:
            return _err(401, "ERROR_RIGHT_MISSING", "You don't have permission")
        if itemtype not in self.data:
            return _err(400, "ERROR_RESOURCE_NOT_FOUND_NOR_COMMONDBTM")
        rows = self.data[itemtype]
        m = re.fullmatch(r"(\d+)-(\d+)", request.url.params.get("range", "0-49"))
        start, end = int(m[1]), int(m[2])
        if rows and start >= len(rows):
            return _err(400, "ERROR_RANGE_EXCEED_TOTAL", "Provided range exceed total count of data")
        page = rows[start:end + 1]
        status = 206 if end + 1 < len(rows) else 200
        return httpx.Response(status, content=json.dumps(page), headers={"Content-Type": "application/json"})

    def client(self):
        """A real Glpi client whose HTTP goes to this fake."""
        g = Glpi("http://glpi", APP_TOKEN, USER_TOKEN)
        g.http = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return g

    def count(self, itemtype):
        return self.calls.count("/" + itemtype)
