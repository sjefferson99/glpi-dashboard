"""Turns raw GLPI rows into the dashboard's views.

Every number on the page is the length of a named list in ``lists``, and
clicking it shows that list, so a count and the records behind it can never
disagree. Statuses are GLPI's own. Areas are the top level of the ITIL category
tree. The ranked-risk weighting is ``RISK_*`` below.
"""
import html
import re
from datetime import datetime, timedelta

TICKET_STATUS = {1: "New", 10: "Approval", 2: "Processing (assigned)", 3: "Processing (planned)",
                 4: "Pending", 5: "Solved", 6: "Closed"}
PROBLEM_STATUS = {1: "New", 7: "Accepted", 2: "Processing (assigned)", 3: "Processing (planned)",
                  4: "Pending", 5: "Solved", 8: "Under observation", 6: "Closed"}
CHANGE_STATUS = {1: "New", 9: "Evaluation", 10: "Approval", 7: "Accepted", 4: "Pending", 11: "Testing",
                 12: "Qualification", 5: "Applied", 8: "Review", 6: "Closed", 14: "Cancelled",
                 13: "Refused"}
PRIORITY = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high", 6: "Major"}

TICKET_DONE = {5, 6}
PROBLEM_DONE = {5, 6}
CHANGE_DONE = {6, 13, 14}
CHANGE_APPLIED = 5
CHANGE_WORKING = (7, 11, 12)      # Accepted, Testing, Qualification
VALIDATION_WAITING = 2           # Change.global_validation: 1 none, 2 waiting, 3 accepted, 4 refused

STANDARD_CHANGE_AREA = "Standard change"
SECURITY_AREA = "Security"

# Record quality: what the GLPI working rules expect every open record to have.
STALE_DAYS = 30
VALIDATION_NONE = 1
CHANGE_NEW = 1
CHANGE_PLAN_FIELDS = {"impactcontent": "Impacts", "rolloutplancontent": "Deployment plan",
                      "backoutplancontent": "Backup plan", "checklistcontent": "Checklist"}
ACTOR_ASSIGNED = 2                         # actor link type: 1 requester, 2 assigned, 3 observer
ACTORS = {"Ticket": (("Ticket_User", "tickets_id"), ("Group_Ticket", "tickets_id")),
          "Problem": (("Problem_User", "problems_id"), ("Group_Problem", "problems_id")),
          "Change": (("Change_User", "changes_id"), ("Change_Group", "changes_id"))}
TAG = re.compile(r"<[^>]*>")

# Ranked risks: points per priority, plus flat bonuses, plus age (linear to RISK_AGE_DAYS).
RISK_PRIORITY = {1: 0, 2: 10, 3: 25, 4: 45, 5: 70, 6: 90}
RISK_SECURITY = 15
RISK_INTERNET = 15
RISK_AGE_MAX, RISK_AGE_DAYS = 15, 180
RISK_PER_INCIDENT, RISK_INCIDENTS_MAX = 5, 15
RISK_TOP = 20

FORM = {"Ticket": "ticket", "Problem": "problem", "Change": "change"}
PLAIN_ITEMTYPE = re.compile(r"[A-Za-z_]+")


def _date(s):
    """Parses a GLPI ``YYYY-MM-DD HH:MM:SS`` timestamp; ``None`` or empty gives ``None``."""
    return datetime.fromisoformat(s.replace(" ", "T")) if s else None


def _blank(html_text):
    """Says whether a GLPI rich-text field has no visible text.

    GLPI may return the HTML entity-encoded (``&lt;p&gt;``), so it's decoded before and after
    the tags are dropped; an empty editor leaves ``<p>&nbsp;</p>``.
    """
    text = TAG.sub("", html.unescape(html_text or ""))
    return not html.unescape(text).replace("\xa0", " ").strip()


def _rag(items):
    """Rates a set of open incidents and problems red, amber or green.

    Args:
        items: Records with ``kind`` and ``priority``.

    Returns:
        ``"red"`` if any is High or above, ``"amber"`` if any is an incident or a Medium
        problem, else ``"green"``.
    """
    if any(r["priority"] >= 4 for r in items):
        return "red"
    if any(r["kind"] == "Incident" or r["priority"] == 3 for r in items):
        return "amber"
    return "green"


class Builder:
    """Builds one snapshot; see ``build()`` for the arguments."""

    def __init__(self, data, now, glpi_url, internet_roots, internet_extra):
        self.d = data
        self.now = now
        self.url = glpi_url.rstrip("/")
        self.lists = {}
        self.records = {}
        cats = {c["id"]: c for c in data["ITILCategory"]}
        self.category = {i: c["completename"] for i, c in cats.items()}
        self.ci_names = {(t, r["id"]): r["name"] for t, rows in data["cis"].items() for r in rows}
        self.internet = self._internet_facing(internet_roots, internet_extra)

    # --- helpers -----------------------------------------------------------------

    def _internet_facing(self, roots, extra):
        """Returns the internet-facing CI keys.

        These are the root CIs (e.g. a reverse proxy), everything they impact in GLPI's
        impact graph, and the named extras.
        """
        by_name = {}
        for key, name in self.ci_names.items():
            by_name.setdefault(name, []).append(key)
        root_keys = {k for n in roots for k in by_name.get(n, [])}
        out = set(root_keys) | {k for n in extra for k in by_name.get(n, [])}
        for rel in self.d["ImpactRelation"]:
            if (rel["itemtype_source"], rel["items_id_source"]) in root_keys:
                out.add((rel["itemtype_impacted"], rel["items_id_impacted"]))
        return out

    def ci_url(self, itemtype, items_id):
        """Returns the GLPI page for a CI.

        Namespaced types (GLPI 11 custom assets) have no ``/front/<type>.form.php``
        page, so they link to GLPI itself.
        """
        if not PLAIN_ITEMTYPE.fullmatch(itemtype):
            return self.url + "/"
        return f"{self.url}/front/{itemtype.lower()}.form.php?id={int(items_id)}"

    def _cis(self, rows, id_field):
        """Maps record id to its linked ``(itemtype, items_id)`` CI keys."""
        out = {}
        for r in rows:
            key = (r["itemtype"], r["items_id"])
            out.setdefault(r[id_field], []).append(key)
        return out

    def add_list(self, key, title, keys):
        """Registers a drill-down list. Every count on the page must come from here.

        Args:
            key: The list's id, used in ``#list=<key>`` links.
            title: The heading shown above the list.
            keys: Record keys; duplicates are dropped.

        Returns:
            The number of records in the list, which is the count to show.
        """
        keys = list(dict.fromkeys(keys))
        keys.sort(key=lambda k: (-self.records[k]["priority"], -self.records[k]["age_days"]))
        self.lists[key] = {"title": title, "refs": keys}
        return len(keys)

    def add_table(self, key, title, kind, rows):
        """Registers a drill-down list of non-record rows, such as projects.

        Args:
            key: The list's id, used in ``#list=<key>`` links.
            title: The heading shown above the list.
            kind: Which columns the page shows, e.g. ``"projects"``.
            rows: The rows, in the order to show them.

        Returns:
            The number of rows, which is the count to show.
        """
        self.lists[key] = {"title": title, "kind": kind, "rows": rows}
        return len(rows)

    # --- records -----------------------------------------------------------------

    def build_records(self):
        """Turns every ticket, problem and change into a record keyed ``Itemtype:id``."""
        links = {"Ticket": self._cis(self.d["Item_Ticket"], "tickets_id"),
                 "Problem": self._cis(self.d["Item_Problem"], "problems_id"),
                 "Change": self._cis(self.d["Change_Item"], "changes_id")}
        done = {"Ticket": TICKET_DONE, "Problem": PROBLEM_DONE, "Change": CHANGE_DONE}
        status = {"Ticket": TICKET_STATUS, "Problem": PROBLEM_STATUS, "Change": CHANGE_STATUS}
        for itemtype in ("Ticket", "Problem", "Change"):
            assigned = {row[id_field] for table, id_field in ACTORS[itemtype] for row in self.d[table]
                        if row.get("type") == ACTOR_ASSIGNED}
            for r in self.d[itemtype]:
                if itemtype == "Ticket":
                    kind = "Incident" if r.get("type") == 1 else "Request"
                else:
                    kind = itemtype
                category = self.category.get(r["itilcategories_id"], "")
                opened = _date(r["date"]) or self.now
                updated = _date(r.get("date_mod"))
                cis = links[itemtype].get(r["id"], [])
                key = f"{itemtype}:{r['id']}"
                self.records[key] = {
                    "key": key, "itemtype": itemtype, "kind": kind, "id": r["id"],
                    "ref": f"{kind} #{r['id']}", "name": r["name"],
                    "status": status[itemtype].get(r["status"], str(r["status"])),
                    "status_id": r["status"], "open": r["status"] not in done[itemtype],
                    "priority": r["priority"], "priority_name": PRIORITY.get(r["priority"], "?"),
                    "urgency": r["urgency"], "impact": r["impact"],
                    "category": category, "area": category.split(" > ")[0] if category else "Uncategorised",
                    "date": opened.date().isoformat(), "age_days": max((self.now - opened).days, 0),
                    "updated": updated.date().isoformat() if updated else None,
                    "url": f"{self.url}/front/{FORM[itemtype]}.form.php?id={r['id']}",
                    "cis": [{"name": self.ci_names.get(k, f"{k[0]} #{k[1]}"), "url": self.ci_url(*k),
                             "internet": k in self.internet} for k in cis],
                    "_ci_keys": cis,
                    "_assigned": r["id"] in assigned,
                    "_idle_days": max((self.now - (updated or opened)).days, 0),
                    "_empty_plan": [label for f, label in CHANGE_PLAN_FIELDS.items() if _blank(r.get(f))]
                    if itemtype == "Change" else [],
                }

    def open_of(self, *kinds):
        """Returns the keys of open records of the given kinds (Incident, Request, Problem, Change)."""
        return [k for k, r in self.records.items() if r["open"] and r["kind"] in kinds]

    # --- views -------------------------------------------------------------------

    def summary(self):
        """Returns the summary tiles: open records by kind and high priority."""
        R = self.records
        changes = [k for k in self.open_of("Change") if R[k]["status_id"] != CHANGE_APPLIED]
        everything = self.open_of("Incident", "Request", "Problem", "Change")
        tiles = [
            ("open-incidents", "incident", "Open incidents", self.open_of("Incident")),
            ("open-requests", "request", "Open requests", self.open_of("Request")),
            ("open-problems", "problem", "Open problems", self.open_of("Problem")),
            ("open-changes", "change", "Open changes (not yet Applied)", changes),
            ("high-priority", "issue", "High priority or above, open",
             [k for k in everything if R[k]["priority"] >= 4]),
        ]
        return [{"key": key, "kind": kind, "title": title, "count": self.add_list(key, title, keys)}
                for key, kind, title, keys in tiles]

    def quality(self):
        """Returns the record-quality tiles: open records missing what the GLPI working rules ask for.

        Each tile has a short ``label``, a ``title`` for its list, and the full rule in ``detail``.
        Requests often have no CI, so only incidents, problems and changes need one. The change
        checks skip standard changes, which need no approval or plan. Only changes still in New
        are checked for an approval request, since older changes predate the rule.
        """
        R = self.records
        everything = self.open_of("Incident", "Request", "Problem", "Change")
        linked_problems = ({row["problems_id"] for row in self.d["Problem_Ticket"]}
                           | {row["problems_id"] for row in self.d["Change_Problem"]})
        changes = [k for k in self.open_of("Change") if R[k]["area"] != STANDARD_CHANGE_AREA]
        validation = {c["id"]: c.get("global_validation") for c in self.d["Change"]}
        tiles = [
            ("no-category", "issue", "No category", "Open records without a category",
             "Open incidents, requests, problems and changes with no ITIL category.",
             [k for k in everything if not R[k]["category"]]),
            ("no-ci", "issue", "No CI", "Open incidents, problems and changes without a CI",
             "Open incidents, problems and changes not linked to any CI. Requests are left out: they often have none.",
             [k for k in self.open_of("Incident", "Problem", "Change") if not R[k]["_ci_keys"]]),
            ("unassigned", "issue", "Unassigned", "Open records with no one assigned",
             "Open records with no technician or group assigned. Requesters and observers don't count.",
             [k for k in everything if not R[k]["_assigned"]]),
            ("stale", "issue", f"Stale ({STALE_DAYS} d)", f"Open records not updated in {STALE_DAYS} days",
             f"Open records with no update in the last {STALE_DAYS} days.",
             [k for k in everything if R[k]["_idle_days"] > STALE_DAYS]),
            ("orphan-problems", "problem", "Orphan problems", "Open problems linked to no incident and no change",
             "Open problems not linked to any incident or change.",
             [k for k in self.open_of("Problem") if R[k]["id"] not in linked_problems]),
            ("no-approval", "change", "No approval asked", "Changes in New with no approval requested",
             "Changes in New, other than standard changes, with no approval requested.",
             [k for k in changes if R[k]["status_id"] == CHANGE_NEW
              and validation.get(R[k]["id"]) == VALIDATION_NONE]),
            ("empty-plan", "change", "Plan incomplete", "Open changes with an empty plan field",
             "Open changes, other than standard changes, with an empty Impacts, Deployment plan, Backup plan "
             "or Checklist.",
             [k for k in changes if R[k]["_empty_plan"]]),
        ]
        return [{"key": key, "kind": kind, "label": label, "title": title, "detail": detail,
                 "count": self.add_list(key, title, keys)}
                for key, kind, label, title, detail, keys in tiles]

    def health(self):
        """Returns open incidents and problems per area and per CI, each rated red/amber/green."""
        R = self.records
        items = self.open_of("Incident", "Problem")
        areas = sorted({R[k]["area"] for k in items} | {
            c.split(" > ")[0] for c in self.category.values()} - {STANDARD_CHANGE_AREA})
        out_areas = []
        for area in areas:
            mine = [k for k in items if R[k]["area"] == area]
            inc = [k for k in mine if R[k]["kind"] == "Incident"]
            prob = [k for k in mine if R[k]["kind"] == "Problem"]
            slug = area.lower().replace(" & ", "-").replace(" ", "-")
            out_areas.append({
                "area": area, "rag": _rag([R[k] for k in mine]),
                "incidents": self.add_list(f"area-{slug}-incidents", f"{area}: open incidents", inc),
                "incidents_list": f"area-{slug}-incidents",
                "problems": self.add_list(f"area-{slug}-problems", f"{area}: open problems", prob),
                "problems_list": f"area-{slug}-problems",
            })
        changes = [k for k in self.open_of("Change") if R[k]["status_id"] != CHANGE_APPLIED]
        by_ci = {}
        for k in items + changes:
            for ci in R[k]["_ci_keys"]:
                by_ci.setdefault(ci, []).append(k)
        out_cis = []
        for ci, keys in by_ci.items():
            issues = [k for k in keys if R[k]["kind"] in ("Incident", "Problem")]
            if not issues:
                continue
            name = self.ci_names.get(ci, f"{ci[0]} #{ci[1]}")
            slug = f"ci-{ci[0]}-{ci[1]}"
            row = {"name": name, "url": self.ci_url(*ci), "internet": ci in self.internet,
                   "rag": _rag([R[k] for k in issues])}
            for part, kinds in (("incidents", ("Incident",)), ("problems", ("Problem",)), ("changes", ("Change",))):
                sel = [k for k in keys if R[k]["kind"] in kinds]
                row[part] = self.add_list(f"{slug}-{part}", f"{name}: open {part}", sel)
                row[part + "_list"] = f"{slug}-{part}"
            out_cis.append(row)
        order = {"red": 0, "amber": 1, "green": 2}
        out_cis.sort(key=lambda r: (order[r["rag"]], -(r["incidents"] + r["problems"]), r["name"]))
        return {"areas": out_areas, "cis": out_cis}

    def risks(self):
        """Scores open problems and changes (not Applied, not standard changes).

        Returns:
            The top ``RISK_TOP`` with each score's breakdown in ``why``, the total, and the
            ``risks-all`` list in score order (registered directly, since ``add_list`` sorts by priority).
        """
        R = self.records
        open_incidents = set(self.open_of("Incident"))
        incidents_of = {}
        for row in self.d["Problem_Ticket"]:
            if f"Ticket:{row['tickets_id']}" in open_incidents:
                incidents_of.setdefault(row["problems_id"], []).append(row["tickets_id"])
        cands = [k for k in self.open_of("Problem")] + [
            k for k in self.open_of("Change")
            if R[k]["status_id"] != CHANGE_APPLIED and R[k]["area"] != STANDARD_CHANGE_AREA]
        scored = []
        for k in cands:
            r = R[k]
            why = [f"priority {r['priority_name']} +{RISK_PRIORITY.get(r['priority'], 0)}"]
            score = RISK_PRIORITY.get(r["priority"], 0)
            if r["area"] == SECURITY_AREA:
                score += RISK_SECURITY
                why.append(f"security +{RISK_SECURITY}")
            facing = [c["name"] for c in r["cis"] if c["internet"]]
            if facing:
                score += RISK_INTERNET
                why.append(f"internet-facing ({', '.join(facing[:3])}) +{RISK_INTERNET}")
            age = round(min(r["age_days"], RISK_AGE_DAYS) / RISK_AGE_DAYS * RISK_AGE_MAX)
            if age:
                score += age
                why.append(f"age {r['age_days']} d +{age}")
            if r["itemtype"] == "Problem" and incidents_of.get(r["id"]):
                n = len(incidents_of[r["id"]])
                bonus = min(n * RISK_PER_INCIDENT, RISK_INCIDENTS_MAX)
                score += bonus
                why.append(f"{n} open incident(s) +{bonus}")
            scored.append({"key": k, "score": score, "why": why})
        scored.sort(key=lambda s: (-s["score"], -R[s["key"]]["age_days"]))
        self.lists["risks-all"] = {"title": "All open problems and changes, by risk score",
                                   "refs": [s["key"] for s in scored]}
        return {"top": scored[:RISK_TOP], "total": len(scored), "list": "risks-all"}

    def recurring(self):
        """Returns the active recurring changes, each with the open changes made from it.

        GLPI v1 doesn't link a change back to the recurring change that created it, so a change
        belongs to the recurring change its title starts with (ignoring case), the longest name
        winning if several match.
        """
        R = self.records
        active = [rc for rc in self.d["RecurrentChange"] if rc.get("is_active") and (rc.get("name") or "").strip()]
        longest_first = sorted(active, key=lambda rc: -len(rc["name"].strip()))
        made_by = {rc["id"]: [] for rc in active}
        for k in self.open_of("Change"):
            title = (R[k]["name"] or "").casefold()
            rc = next((rc for rc in longest_first if title.startswith(rc["name"].strip().casefold())), None)
            if rc:
                made_by[rc["id"]].append(k)
        out = []
        for rc in active:
            nxt = _date(rc.get("next_creation_date"))
            due = nxt + timedelta(seconds=int(rc.get("create_before") or 0)) if nxt else None
            key = f"recurring-{rc['id']}-open"
            out.append({"name": rc["name"], "periodicity": rc.get("periodicity") or "",
                        "next_creation": nxt.date().isoformat() if nxt else None,
                        "due": due.date().isoformat() if due else None,
                        "url": f"{self.url}/front/recurrentchange.form.php?id={rc['id']}",
                        "open": self.add_list(key, f"{rc['name']}: open changes", made_by[rc["id"]]),
                        "open_list": key})
        out.sort(key=lambda r: r["next_creation"] or "9999")
        return out

    def _status_tiles(self, kind, label, statuses, done):
        """Returns one tile per open status of a kind, keyed ``<label>-<status>``."""
        R = self.records
        tiles = []
        for sid, name in statuses.items():
            if sid in done:
                continue
            key = f"{label.lower()}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
            title = f"{label}: {name}"
            keys = [k for k in self.open_of(kind) if R[k]["status_id"] == sid]
            tiles.append({"key": key, "kind": kind.lower(), "title": title, "label": name,
                          "count": self.add_list(key, title, keys)})
        return tiles

    def in_flight(self):
        """Returns the in-flight tiles in groups: each record kind by status, then projects."""
        R = self.records
        groups = [{"title": label, "kind": kind.lower(), "tiles": self._status_tiles(kind, label, statuses, done)}
                  for kind, label, statuses, done in (("Incident", "Incidents", TICKET_STATUS, TICKET_DONE),
                                                      ("Request", "Requests", TICKET_STATUS, TICKET_DONE),
                                                      ("Problem", "Problems", PROBLEM_STATUS, PROBLEM_DONE))]

        waiting = {c["id"] for c in self.d["Change"] if c.get("global_validation") == VALIDATION_WAITING}
        approval = [k for k in self.open_of("Change") if R[k]["id"] in waiting
                    and R[k]["status_id"] != CHANGE_APPLIED]
        tiles = [{"key": "awaiting-approval", "kind": "change", "title": "Changes awaiting approval",
                  "label": "Awaiting approval",
                  "count": self.add_list("awaiting-approval", "Changes awaiting approval", approval)}]
        for sid in CHANGE_WORKING + (CHANGE_APPLIED,):
            name = CHANGE_STATUS[sid]
            title = "Changes Applied - to close" if sid == CHANGE_APPLIED else f"Changes at {name}"
            label = "Applied - to close" if sid == CHANGE_APPLIED else name
            key = f"changes-{name.lower()}"
            keys = [k for k in self.open_of("Change") if R[k]["status_id"] == sid]
            tiles.append({"key": key, "kind": "change", "title": title, "label": label,
                          "count": self.add_list(key, title, keys)})
        groups.append({"title": "Changes", "kind": "change", "tiles": tiles})

        states = {s["id"]: s["name"] for s in self.d["ProjectState"]}
        linked = {}
        for row in self.d["Itil_Project"]:
            key = f"{row['itemtype']}:{row['items_id']}"
            if key in R:
                linked.setdefault(row["projects_id"], []).append(key)
        projects = []
        for p in self.d["Project"]:
            keys = linked.get(p["id"], [])
            title = p["name"]
            projects.append({
                "name": title, "code": p.get("code") or "", "state": states.get(p["projectstates_id"], ""),
                "percent_done": p.get("percent_done") or 0,
                "url": f"{self.url}/front/project.form.php?id={p['id']}",
                "open": self.add_list(f"project-{p['id']}-open", f"{title}: open linked records",
                                      [k for k in keys if R[k]["open"]]),
                "open_list": f"project-{p['id']}-open",
                "total": self.add_list(f"project-{p['id']}-all", f"{title}: all linked records", keys),
                "total_list": f"project-{p['id']}-all",
            })
        projects.sort(key=lambda p: p["name"])
        groups.append({"title": "Projects", "kind": "project", "tiles": [
            {"key": "projects", "kind": "project", "title": "Projects", "label": "Projects",
             "count": self.add_table("projects", "Projects", "projects", projects)}]})
        return {"groups": groups}

    def build(self):
        """Builds every view; only records some list refers to are sent."""
        self.build_records()
        view = {"summary": self.summary(), "quality": self.quality(),
                "health": {**self.health(), "recurring": self.recurring()},
                "risks": self.risks(), "in_flight": self.in_flight()}
        used = {k for lst in self.lists.values() for k in lst.get("refs", ())}
        records = {k: {f: v for f, v in r.items() if not f.startswith("_")}
                   for k, r in self.records.items() if k in used}
        return {**view, "lists": self.lists, "records": records, "glpi_url": self.url}


def build(data, now, glpi_url, internet_roots=(), internet_extra=()):
    """Builds the dashboard snapshot from GLPI rows.

    Args:
        data: Rows by itemtype as ``main.collect()`` returns them, with ``"cis"`` holding CI rows by type.
        now: The time ages are measured from.
        glpi_url: GLPI's address as a browser reaches it; every link points here.
        internet_roots: CI names whose impacted CIs count as internet-facing (e.g. a reverse proxy).
        internet_extra: Further CI names that count as internet-facing.

    Returns:
        A JSON-ready dict: ``summary``, ``quality``, ``health``, ``risks``, ``in_flight``, ``lists``, ``records``
        and ``glpi_url``.
    """
    return Builder(data, now, glpi_url, internet_roots, internet_extra).build()
