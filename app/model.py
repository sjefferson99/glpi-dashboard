"""Turns raw GLPI rows into the dashboard's views.

Every number on the page is the length of a named list in ``lists``, and
clicking it shows that list, so a count and the records behind it can never
disagree. Statuses are GLPI's own. Areas are the top level of the ITIL category
tree. The ranked-risk weighting is ``RISK_*`` below. The site-specific settings
(``STANDARD_CHANGE_AREA``, ``STALE_DAYS``, ``RISK_AREAS``) are defaults that
``main.py`` may override from the environment.
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

STANDARD_CHANGE_AREA = "Standard change"   # pre-approved changes: no risk score, no area, no change checks
UNCATEGORISED = "Uncategorised"            # the area of a record with no category

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
RISK_AREAS = {"Security": 15}               # bonus points by area
RISK_INTERNET = 15
RISK_AGE_MAX, RISK_AGE_DAYS = 15, 180
RISK_PER_INCIDENT, RISK_INCIDENTS_MAX = 5, 15

FORM = {"Ticket": "ticket", "Problem": "problem", "Change": "change"}
PLAIN_ITEMTYPE = re.compile(r"[A-Za-z_]+")

# Search: a query needs this many characters; at most SEARCH_LIMIT matches are sent, with the total.
SEARCH_MIN, SEARCH_MAX, SEARCH_LIMIT = 2, 100, 100
SNIPPET_BEFORE, SNIPPET_AFTER = 60, 140
SPACE = re.compile(r"\s+")
ID_WORD = re.compile(r"#([0-9]+)")  # a search word naming an id, e.g. "#12"; ASCII digits only, as the page's


def _date(s):
    """Parses a GLPI ``YYYY-MM-DD HH:MM:SS`` timestamp; ``None`` or empty gives ``None``."""
    return datetime.fromisoformat(s.replace(" ", "T")) if s else None


def _plain(html_text):
    """Returns a GLPI rich-text field as one line of plain text.

    GLPI may return the HTML entity-encoded (``&lt;p&gt;``), so it's decoded before and after
    the tags are dropped; an empty editor leaves ``<p>&nbsp;</p>``.
    """
    text = TAG.sub(" ", html.unescape(html_text or ""))
    return SPACE.sub(" ", html.unescape(text).replace("\xa0", " ")).strip()


def _blank(html_text):
    """Says whether a GLPI rich-text field has no visible text."""
    return not _plain(html_text)


def _pattern(term):
    """Returns the regex a search word matches: the word itself, but an ``#id`` only as a whole number."""
    return re.escape(term) + (r"(?![0-9])" if ID_WORD.fullmatch(term) else "")


def _has(term, text):
    """Says whether lower-cased ``text`` holds a search word: ``#12`` is in ``see #12.`` but not in ``#123``."""
    return re.search(_pattern(term), text) is not None if ID_WORD.fullmatch(term) else term in text


def _snippet(text, terms):
    """Returns the part of ``text`` around the first of ``terms`` found in it, or ``""`` if none is."""
    found = [m.start() for t in terms if (m := re.search(_pattern(t), text, re.IGNORECASE))]
    if not found:
        return ""
    at = min(found)
    start, end = max(at - SNIPPET_BEFORE, 0), min(at + SNIPPET_AFTER, len(text))
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _area(category):
    """Returns the area of an ITIL category's full name: its top level, or ``UNCATEGORISED`` for none."""
    return category.split(" > ")[0] if category else UNCATEGORISED


def areas(categories):
    """Returns every area records can have: each top-level ITIL category, plus ``UNCATEGORISED``.

    Args:
        categories: ``ITILCategory`` rows, with ``completename``.
    """
    return {_area(c.get("completename") or "") for c in categories} | {UNCATEGORISED}


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
    """Builds one snapshot; see ``build()`` for the arguments.

    ``risk_areas``, ``standard_change_area`` and ``stale_days`` default to the module's settings.
    """

    def __init__(self, data, now, glpi_url, internet_roots, internet_extra, risk_areas=None,
                 standard_change_area=STANDARD_CHANGE_AREA, stale_days=STALE_DAYS):
        self.d = data
        self.now = now
        self.url = glpi_url.rstrip("/")
        self.lists = {}
        self.records = {}
        cats = {c["id"]: c for c in data["ITILCategory"]}
        self.category = {i: c["completename"] for i, c in cats.items()}
        self.ci_names = {(t, r["id"]): r["name"] for t, rows in data["cis"].items() for r in rows}
        self.internet = self._internet_facing(internet_roots, internet_extra)
        self.risk_areas = RISK_AREAS if risk_areas is None else risk_areas
        self.standard = standard_change_area
        self.stale_days = stale_days

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

    def add_list(self, key, title, keys, kind=None):
        """Registers a drill-down list. Every count on the page must come from here.

        Args:
            key: The list's id, used in ``#list=<key>`` links.
            title: The heading shown above the list.
            keys: Record keys; duplicates are dropped.
            kind: Which columns the page shows. ``"risks"`` keeps ``keys`` in the order given (risk score);
                the default lists records by priority, then age.

        Returns:
            The number of records in the list, which is the count to show.
        """
        keys = list(dict.fromkeys(keys))
        if kind != "risks":
            keys.sort(key=lambda k: (-self.records[k]["priority"], -self.records[k]["age_days"]))
        self.lists[key] = {"title": title, "refs": keys, **({"kind": kind} if kind else {})}
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
                    "category": category, "area": _area(category),
                    "date": opened.date().isoformat(), "age_days": max((self.now - opened).days, 0),
                    "updated": updated.date().isoformat() if updated else None,
                    "url": f"{self.url}/front/{FORM[itemtype]}.form.php?id={r['id']}",
                    "cis": [{"name": self.ci_names.get(k, f"{k[0]} #{k[1]}"), "url": self.ci_url(*k),
                             "internet": k in self.internet} for k in cis],
                    "_ci_keys": cis,
                    "_assigned": r["id"] in assigned,
                    "_idle_days": max((self.now - (updated or opened)).days, 0),
                    "_text": _plain(r.get("content")),
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
        changes = [k for k in self.open_of("Change") if R[k]["area"] != self.standard]
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
            ("stale", "issue", f"Stale ({self.stale_days} d)", f"Open records not updated in {self.stale_days} days",
             f"Open records with no update in the last {self.stale_days} days.",
             [k for k in everything if R[k]["_idle_days"] > self.stale_days]),
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
            c.split(" > ")[0] for c in self.category.values()} - {self.standard})
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
        """Scores open problems and changes (not Applied, not standard changes) and groups them for the chart.

        Each scored record gets ``risk``: its ``rank``, ``score`` and the breakdown in ``why``. Every group is a
        list in score order, so a chart segment opens the same ranking, filtered.

        Returns:
            The ``total`` and its ``list`` (``risks-all``), plus ``priorities`` (highest first) and ``kinds``
            (problems, then changes) as groups, and ``cells``, one per priority and kind. Each has a ``count``
            and its ``list``; empty ones are left out.
        """
        R = self.records
        open_incidents = set(self.open_of("Incident"))
        incidents_of = {}
        for row in self.d["Problem_Ticket"]:
            if f"Ticket:{row['tickets_id']}" in open_incidents:
                incidents_of.setdefault(row["problems_id"], []).append(row["tickets_id"])
        cands = [k for k in self.open_of("Problem")] + [
            k for k in self.open_of("Change")
            if R[k]["status_id"] != CHANGE_APPLIED and R[k]["area"] != self.standard]
        scored = []
        for k in cands:
            r = R[k]
            why = [f"priority {r['priority_name']} +{RISK_PRIORITY.get(r['priority'], 0)}"]
            score = RISK_PRIORITY.get(r["priority"], 0)
            area_bonus = self.risk_areas.get(r["area"], 0)
            if area_bonus:
                score += area_bonus
                why.append(f"{r['area'].lower()} +{area_bonus}")
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
        ranked = [s["key"] for s in scored]
        for rank, s in enumerate(scored, 1):
            R[s["key"]]["risk"] = {"rank": rank, "score": s["score"], "why": s["why"]}

        def group(key, title, keys, **fields):
            return {**fields, "count": self.add_list(key, title, keys, "risks"), "list": key}

        # Groups come from the records themselves, so the segments always add up to the total.
        names = {R[k]["priority"]: R[k]["priority_name"] for k in ranked}
        kinds_present = [kind for kind in ("Problem", "Change") if any(R[k]["kind"] == kind for k in ranked)]
        priorities, kinds, cells = [], [], []
        for p in sorted(names, reverse=True):
            keys = [k for k in ranked if R[k]["priority"] == p]
            priorities.append(group(f"risks-p{p}", f"Risks at {names[p]} priority", keys,
                                    priority=p, name=names[p]))
            for kind in kinds_present:
                sel = [k for k in keys if R[k]["kind"] == kind]
                if sel:
                    cells.append(group(f"risks-p{p}-{kind.lower()}", f"Risks: {kind.lower()}s at {names[p]} priority",
                                       sel, priority=p, kind=kind))
        for kind in kinds_present:
            kinds.append(group(f"risks-{kind.lower()}", f"Risks: {kind.lower()}s",
                               [k for k in ranked if R[k]["kind"] == kind], kind=kind))
        total = self.add_list("risks-all", "All open problems and changes, by risk score", ranked, "risks")
        return {"total": total, "list": "risks-all", "priorities": priorities, "kinds": kinds, "cells": cells}

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

    def explorer(self):
        """Returns every ticket, problem and change, closed too, as the Record explorer groups and lists them.

        Call it after ``build()``. The page groups these rows itself, so a box's size and the list it opens are
        the same rows and can't disagree. They come in the drill-down lists' order: priority, then age.

        Returns:
            One row per record: the fields the explorer groups by and shows, plus ``assigned`` (someone or some
            group is assigned), ``cis`` (the names of its linked CIs) and ``family`` (see ``families()``).
        """
        fields = ("key", "kind", "ref", "status", "open", "priority", "priority_name", "category", "area", "date",
                  "updated", "age_days", "url")
        family = self.families()
        rows = sorted(self.records.values(), key=lambda r: (-r["priority"], -r["age_days"]))
        return [{**{f: r[f] for f in fields}, "name": r["name"] or "", "assigned": r["_assigned"],
                 "cis": [c["name"] for c in r["cis"]], "family": family.get(r["key"], "")} for r in rows]

    def families(self):
        """Names each set of records joined by problem-ticket and change-problem links, after its lead record.

        A record is in one family at most, so grouping by family counts each once. The lead is the family's
        lowest-numbered problem, else its lowest-numbered change.

        Returns:
            The family's name, e.g. ``"Problem #1: Disk full"``, by record key; unlinked records are left out.
        """
        parent = {}

        def find(k):
            while parent.setdefault(k, k) != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        links = [(f"Problem:{r['problems_id']}", f"Ticket:{r['tickets_id']}") for r in self.d["Problem_Ticket"]]
        links += [(f"Change:{r['changes_id']}", f"Problem:{r['problems_id']}") for r in self.d["Change_Problem"]]
        for a, b in links:
            if a in self.records and b in self.records:     # a link to a deleted record joins nothing
                parent[find(a)] = find(b)
        members = {}
        for k in parent:
            members.setdefault(find(k), []).append(self.records[k])
        rank = {"Problem": 0, "Change": 1, "Ticket": 2}
        out = {}
        for recs in members.values():
            lead = min(recs, key=lambda r: (rank[r["itemtype"]], r["id"]))
            name = f"{lead['ref']}: {lead['name']}" if lead["name"] else lead["ref"]
            for r in recs:
                out[r["key"]] = name
        return out

    def search_index(self):
        """Returns everything a search looks through: each ticket, problem and change (closed too), project and CI.

        Call it after ``build()``. Only CIs of the types ``main.collect()`` read are included: those linked to a
        record or in the impact graph.

        Returns:
            Entries as ``search()`` shows them, each with ``_hay``, the lower-cased text searched; ``_text``, the
            description as plain text, for snippets; and ``_id``, its GLPI id, which an ``#id`` search finds.
        """
        def entry(fields, text, *more):
            hay = " ".join([fields["ref"], fields["name"], fields["category"], fields["status"], *more, text])
            return {**fields, "_hay": hay.lower(), "_text": text, "_id": int(fields["ref"].rsplit("#", 1)[-1])}

        out = []
        for r in self.records.values():
            fields = {f: r[f] for f in ("kind", "ref", "name", "status", "category", "date", "updated", "open", "url")}
            out.append(entry({**fields, "name": r["name"] or ""}, r["_text"], *(c["name"] for c in r["cis"])))
        states = {s["id"]: s["name"] for s in self.d["ProjectState"]}
        for p in self.d["Project"]:
            date, updated = _date(p.get("date")), _date(p.get("date_mod"))
            out.append(entry({"kind": "Project", "ref": f"Project #{p['id']}", "name": p["name"] or "",
                              "status": states.get(p["projectstates_id"], ""), "category": p.get("code") or "",
                              "date": date.date().isoformat() if date else None,
                              "updated": updated.date().isoformat() if updated else None, "open": None,
                              "url": f"{self.url}/front/project.form.php?id={p['id']}"}, _plain(p.get("content"))))
        for itemtype, rows in self.d["cis"].items():
            label = itemtype.rsplit("\\", 1)[-1]    # GLPI 11 custom assets are namespaced
            for c in rows:
                if c.get("is_template"):
                    continue
                updated = _date(c.get("date_mod"))
                out.append(entry({"kind": "CI", "ref": f"{label} #{c['id']}", "name": c.get("name") or "",
                                  "status": "", "category": label, "date": None,
                                  "updated": updated.date().isoformat() if updated else None, "open": None,
                                  "url": self.ci_url(itemtype, c["id"])}, _plain(c.get("comment")),
                                 str(c.get("serial") or ""), str(c.get("otherserial") or "")))
        return out


def search(index, query, closed=False, limit=SEARCH_LIMIT):
    """Finds the entries with an id the query names, and apart from those, the entries holding every word.

    A word like ``#12`` names an id. GLPI ids are unique only within a type, so every entry with that id is an
    id match, whatever its type, closed or not: asking for an id is asking for that record.

    Text matching is by substring, ignoring case, over the reference, title, category, status, linked CI names
    (and a CI's serial and inventory numbers) and description, except that an ``#id`` word matches only that
    whole number, so ``#12`` finds records that mention ``#12`` but not ``#123``. Entries whose title has every
    word come first, then anything but a closed record, each most recently updated first.

    Args:
        index: Entries from ``Builder.search_index()``.
        query: What was typed. Shorter than ``SEARCH_MIN`` once trimmed, it matches nothing.
        closed: Include closed records in the text matches. Projects and CIs are always included.
        limit: The most text matches to return.

    Returns:
        ``query``; ``ids``, the id matches, in the index's order; the ``total`` number of text matches; and the
        first ``limit`` of them as ``results``. A text match whose title lacks a word has a ``snippet`` of its
        description around the first word found there.
    """
    # lower(), not casefold(): the snippet (re.IGNORECASE) and the page's highlighting (toLowerCase) match the same
    # way, so a hit always comes back with its words shown. casefold() would match "strasse" to "Straße" unseen.
    terms = query.lower().split()
    if len(query.strip()) < SEARCH_MIN:
        return {"query": query, "ids": [], "total": 0, "results": []}
    wanted = {int(m[1]) for t in terms if (m := ID_WORD.fullmatch(t))}
    hits = [e for e in index if e["_id"] not in wanted and (closed or e["open"] is not False)
            and all(_has(t, e["_hay"]) for t in terms)]
    hits.sort(key=lambda e: e["updated"] or e["date"] or "", reverse=True)
    hits.sort(key=lambda e: (not all(_has(t, e["name"].lower()) for t in terms), e["open"] is False))

    def shown(e):
        missing = [t for t in terms if not _has(t, e["name"].lower())]
        return {**{f: v for f, v in e.items() if not f.startswith("_")},
                "snippet": _snippet(e["_text"], missing) if missing else ""}

    return {"query": query, "ids": [{**shown(e), "snippet": ""} for e in index if e["_id"] in wanted],
            "total": len(hits), "results": [shown(e) for e in hits[:limit]]}


def build(data, now, glpi_url, internet_roots=(), internet_extra=(), **settings):
    """Builds the dashboard snapshot from GLPI rows.

    Args:
        data: Rows by itemtype as ``main.collect()`` returns them, with ``"cis"`` holding CI rows by type.
        now: The time ages are measured from.
        glpi_url: GLPI's address as a browser reaches it; every link points here.
        internet_roots: CI names whose impacted CIs count as internet-facing (e.g. a reverse proxy).
        internet_extra: Further CI names that count as internet-facing.
        **settings: ``risk_areas`` (bonus points by area, default ``RISK_AREAS``), ``standard_change_area``
            (``""`` for none) and ``stale_days``, as ``Builder`` takes them.

    Returns:
        A JSON-ready dict: ``summary``, ``quality``, ``health``, ``risks``, ``in_flight``, ``lists``, ``records``
        and ``glpi_url``.
    """
    return Builder(data, now, glpi_url, internet_roots, internet_extra, **settings).build()
