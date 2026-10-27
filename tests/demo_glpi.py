"""A realistic demo GLPI dataset, generated from a fixed seed, for the README screenshots.

It's separate from ``fake_glpi.dataset()``, whose exact numbers the tests assert, and it's shaped the same way:
every itemtype the dashboard reads, as GLPI v1 returns it. It holds about 200 tickets, problems and changes
across several areas, with CIs, an impact graph, recurring changes and projects. The repo is public, so every
name is generic: roles and teams rather than people, and ``example.test`` for any domain. Dates are measured
back from ``NOW``; scripts/demo.py stops the app's clock there too, so a screenshot taken today matches one
taken months ago.
"""
import random
from datetime import datetime, timedelta

SEED = 17
NOW = datetime(2026, 10, 27, 9, 30, 0)
TICKETS, PROBLEMS = 140, 16

CATEGORIES = ["Security", "Security > Certificates", "Security > Access", "Network", "Network > Wi-Fi",
              "Network > VPN", "Hosting", "Hosting > Backup", "Hosting > Storage", "Applications",
              "Applications > Email", "Applications > Intranet", "End-user", "End-user > Laptops",
              "End-user > Printing", "Standard change"]

# (itemtype, name, serial, comment)
CIS = [
    ("Appliance", "reverse-proxy", "", "Terminates TLS for every public site"),
    ("Appliance", "intranet", "", "Intranet stack: web front ends and its database"),
    ("Computer", "web1", "SN-WEB-001", "Public web server"),
    ("Computer", "web2", "SN-WEB-002", "Public web server"),
    ("Computer", "web3", "SN-WEB-003", "Intranet web server"),
    ("Computer", "db1", "SN-DB-001", "Primary database server"),
    ("Computer", "db2", "SN-DB-002", "Replica database server"),
    ("Computer", "mail1", "SN-MAIL-001", "Mail relay for example.test"),
    ("Computer", "file1", "SN-FILE-001", "File server: team shares and home folders"),
    ("Computer", "backup1", "SN-BAK-001", "Backup server, nightly jobs to disk then offsite"),
    ("Computer", "dc1", "SN-DC-001", "Directory and sign-in"),
    ("NetworkEquipment", "firewall", "SN-FW-001", "Edge filtering"),
    ("NetworkEquipment", "core-switch", "SN-SW-001", "Core switch, server room"),
    ("NetworkEquipment", "wifi-controller", "SN-WLC-001", "Controller for every access point"),
    ("NetworkEquipment", "vpn-gateway", "SN-VPN-001", "Remote access for staff"),
    ("Peripheral", "printer-floor1", "SN-PRN-001", "Shared printer, floor 1"),
    ("Peripheral", "printer-floor2", "SN-PRN-002", "Shared printer, floor 2"),
]
IMPACT = [("reverse-proxy", "web1"), ("reverse-proxy", "web2"), ("reverse-proxy", "intranet"),
          ("reverse-proxy", "mail1"), ("intranet", "web3"), ("intranet", "db2"), ("web1", "db1"), ("web2", "db1")]

ROOMS = ["Atlas", "Birch", "Cedar", "Delta", "Elm", "Fjord"]
TEAMS = ["finance", "sales", "support", "design", "operations", "legal"]
SHARES = ["Projects", "Finance", "Marketing", "Archive"]
APPS = ["diagramming", "PDF editor", "accounting", "screen recorder"]

# (category, ticket type: 1 incident / 2 request, title, CIs it may be linked to, description)
TICKET_TEMPLATES = [
    ("Network > Wi-Fi", 1, "Wi-Fi drops in meeting room {room}", ["wifi-controller"],
     "Laptops lose the connection every few minutes during calls; wired desks nearby are fine."),
    ("Network > Wi-Fi", 2, "Guest Wi-Fi access for a visitor day", ["wifi-controller"],
     "Twenty visitors next week need guest Wi-Fi for the day."),
    ("Network > VPN", 1, "VPN disconnects after {n} minutes", ["vpn-gateway"],
     "Remote staff are dropped mid-session and must sign in again. Happens on every network they try."),
    ("Network", 1, "Slow network on floor {floor}", ["core-switch"],
     "File copies crawl and video stutters since this morning. Other floors look normal."),
    ("Network", 2, "Patch a network port in room {room}", [], "A new desk in the corner needs a live port."),
    ("Security > Certificates", 1, "Certificate expiring on {ci}", ["web1", "web2", "reverse-proxy", "mail1"],
     "Monitoring warns the certificate expires within 14 days. Renewal didn't run automatically."),
    ("Security > Access", 1, "Account locked out after failed sign-ins", ["dc1"],
     "A member of the {team} team is locked out after repeated failed sign-ins from an unknown address."),
    ("Security > Access", 2, "Access to the {share} share", ["file1"],
     "A new member of the {team} team needs read and write access to the {share} share."),
    ("Security", 1, "Phishing email reported by the {team} team", ["mail1"],
     "Several staff received a fake invoice email with a sign-in link. One person clicked it."),
    ("Hosting > Storage", 1, "{ci} disk nearly full", ["file1", "db1", "backup1"],
     "The data volume is above 90% and growing about 2% a day."),
    ("Hosting > Backup", 1, "Nightly backup failed on {ci}", ["backup1", "db1", "file1"],
     "Last night's backup job ended with errors; the previous good backup is from two nights ago."),
    ("Hosting > Backup", 2, "Restore a deleted folder from the {share} share", ["file1", "backup1"],
     "A folder was deleted by mistake yesterday afternoon. Please restore it from the latest backup."),
    ("Hosting", 1, "High CPU on {ci}", ["web1", "web2", "db1", "db2"],
     "CPU has been above 95% for an hour and page loads have slowed."),
    ("Hosting", 2, "New virtual machine for the {team} team", [],
     "A small Linux VM for a reporting tool, 2 vCPU and 8 GB RAM."),
    ("Applications > Email", 1, "Mail delayed to external recipients", ["mail1"],
     "Outbound mail to example.test addresses is arriving up to an hour late."),
    ("Applications > Email", 2, "Shared mailbox for the {team} team", ["mail1"],
     "A shared mailbox so the {team} team can answer customer queries together."),
    ("Applications > Intranet", 1, "Intranet search returns no results", ["intranet", "web3"],
     "Searching the intranet returns nothing, even for page titles."),
    ("Applications > Intranet", 1, "Intranet page error 500", ["intranet", "web3", "db2"],
     "The team news page shows an internal server error for everyone."),
    ("Applications", 2, "Install the {app} application", [], "Needed for a project starting next month."),
    ("End-user > Laptops", 1, "Laptop won't start", [], "The power light comes on but the screen stays black."),
    ("End-user > Laptops", 2, "New laptop for a new starter in {team}", [],
     "A new starter joins the {team} team on Monday and needs a laptop with the standard build."),
    ("End-user > Printing", 1, "Printer on floor {floor} jams", ["printer-floor1", "printer-floor2"],
     "Paper jams on every second job; the tray has been checked."),
    ("End-user", 1, "Screen flickers on a desk monitor", [], "The monitor flickers every few seconds."),
    ("", 1, "Something's not working", [], "Reported by phone; no details yet."),
]

# (category, title, CIs, description, recurring ticket titles that point at it)
PROBLEM_TEMPLATES = [
    ("Network > Wi-Fi", "Recurring Wi-Fi drops in meeting rooms", ["wifi-controller"],
     "Access points in the meeting rooms reboot under load.", "Wi-Fi drops"),
    ("Network > VPN", "VPN gateway drops sessions under load", ["vpn-gateway"],
     "Sessions drop once more than 200 users connect.", "VPN disconnects"),
    ("Security > Certificates", "Certificate renewals are missed", ["reverse-proxy"],
     "Automatic renewal fails silently for some certificates.", "Certificate expiring"),
    ("Hosting > Backup", "Backup jobs overrun the overnight window", ["backup1"],
     "Jobs that start at 01:00 are still running at 08:00 and fail when users start work.", "Nightly backup"),
    ("Hosting > Storage", "File server runs out of space every month", ["file1"],
     "Growth outpaces the volume; old project data is never archived.", "disk nearly full"),
    ("Applications > Intranet", "Intranet search index corrupts after updates", ["intranet"],
     "The search index has to be rebuilt by hand after each content update.", "Intranet search"),
    ("Applications > Email", "Outbound mail queue backs up at peak", ["mail1"],
     "The relay throttles during the morning peak.", "Mail delayed"),
    ("End-user > Printing", "Floor printers jam with recycled paper", ["printer-floor1", "printer-floor2"],
     "Jams started after the switch to a new paper supplier.", "Printer on floor"),
    ("Hosting", "Web servers saturate CPU during campaigns", ["web1", "web2"],
     "Traffic spikes during marketing campaigns exhaust CPU on both web servers.", "High CPU"),
    ("Security > Access", "Lockouts from an old mobile mail profile", ["dc1"],
     "Old phone profiles keep retrying a changed password.", "Account locked out"),
    ("Network", "Core switch uplink errors", ["core-switch"], "CRC errors on one uplink port.", "Slow network"),
    ("Security", "Phishing emails get past the filter", ["mail1"],
     "Look-alike sender domains aren't caught.", "Phishing email"),
    ("Hosting > Backup", "Restore tests aren't recorded", ["backup1"], "No evidence that restores work.", ""),
    ("End-user > Laptops", "Laptop batteries swelling on one model", [], "Three cases in a month.", ""),
    ("Applications", "Licence renewals arrive too late", [], "Applications stop working at renewal.", ""),
    ("Network > Wi-Fi", "Weak signal at the far end of floor 2", ["wifi-controller"], "No access point there.", ""),
]

# (category, title, CIs, description, problem it fixes or "")
CHANGE_TEMPLATES = [
    ("Network > Wi-Fi", "Replace meeting room access points", ["wifi-controller"],
     "Swap the six meeting room access points for the current model.", "Recurring Wi-Fi drops"),
    ("Network > VPN", "Add a second VPN gateway", ["vpn-gateway"], "Load-balance remote access.", "VPN gateway"),
    ("Security > Certificates", "Automate certificate renewal on the reverse proxy", ["reverse-proxy"],
     "Move every public certificate to automatic renewal with alerts.", "Certificate renewals"),
    ("Security > Certificates", "Renew the wildcard certificate", ["reverse-proxy", "web1", "web2"],
     "Install the renewed wildcard certificate for example.test.", ""),
    ("Hosting > Backup", "Move backups to faster storage", ["backup1"], "New disk shelf for backup1.", "Backup jobs"),
    ("Hosting > Storage", "Archive old project data from file1", ["file1"],
     "Move projects untouched for three years to archive storage.", "File server"),
    ("Applications > Intranet", "Upgrade the intranet to the current release", ["intranet", "web3", "db2"],
     "Fixes the search index bug.", "Intranet search"),
    ("Applications > Email", "Raise the mail relay's send limits", ["mail1"], "Agreed with the provider.",
     "Outbound mail"),
    ("Hosting", "Add a third public web server", ["web1", "web2"], "Scale out ahead of the next campaign.",
     "Web servers"),
    ("Security > Access", "Enforce MFA for remote access", ["vpn-gateway", "dc1"],
     "Require a second factor for every VPN sign-in.", ""),
    ("Network", "Replace the faulty core switch uplink", ["core-switch"], "New optic and cable.", "Core switch"),
    ("Security", "Tighten mail filtering for look-alike domains", ["mail1"], "New filter rules.", "Phishing"),
    ("Hosting", "Retire the old reporting server", [], "Its reports moved to the new VM.", ""),
    ("End-user > Printing", "Switch floor printers to the old paper supplier", ["printer-floor1"], "",
     "Floor printers"),
    ("Network > Wi-Fi", "Add an access point at the end of floor 2", ["wifi-controller"], "", "Weak signal"),
    ("Hosting > Storage", "Expand the database volume on db1", ["db1"], "Add 500 GB.", ""),
    ("Applications", "Upgrade the accounting application", [], "Vendor's yearly release.", ""),
    ("Network", "Firmware update for the firewall", ["firewall"], "Vendor security release.", ""),
    ("Security > Access", "Remove accounts of people who have left", ["dc1"], "Quarterly clean-up.", ""),
    ("Hosting", "Patch db2 to the current minor version", ["db2"], "", ""),
]

# (name, periodicity, days between, category, CIs, how many to make, active)
RECURRING = [
    ("Monthly patching", "1MONTH", 30, "Standard change", ["web1", "web2", "web3", "db1", "db2", "mail1"], 12, 1),
    ("Weekly restore test", "1WEEK", 7, "Standard change", ["backup1", "file1"], 8, 1),
    ("Quarterly firewall rule review", "3MONTH", 91, "Security", ["firewall"], 4, 1),
    ("Yearly access review", "1YEAR", 365, "Security > Access", ["dc1"], 1, 0),
]

PROJECTS = [("Wi-Fi refresh", "PRJ-WIFI", 2, 60, ["Network > Wi-Fi"]),
            ("Certificate automation", "PRJ-CERT", 2, 35, ["Security > Certificates"]),
            ("Backup storage migration", "PRJ-BAK", 1, 10, ["Hosting > Backup"]),
            ("Intranet upgrade", "PRJ-INTRA", 3, 100, ["Applications > Intranet"])]
PROJECT_STATES = [{"id": 1, "name": "New"}, {"id": 2, "name": "Processing"}, {"id": 3, "name": "Closed"}]

PRIORITIES = [1, 2, 3, 4, 5, 6]
PRIORITY_WEIGHTS = [8, 28, 48, 11, 4, 1]
PLAN = ("impactcontent", "rolloutplancontent", "backoutplancontent", "checklistcontent")


class _Demo:
    """Builds the dataset; records get their ids once they're sorted by date, then the links are written."""

    def __init__(self, seed, now):
        self.rng = random.Random(seed)
        self.now = now
        self.cat_id = {name: i for i, name in enumerate(CATEGORIES, 1)}
        self.ci_key = {}
        self.cis = {}
        for itemtype, name, serial, comment in CIS:
            rows = self.cis.setdefault(itemtype, [])
            rows.append({"id": len(rows) + 1, "name": name, "serial": serial, "comment": comment,
                         "date_mod": self._d(self.rng.randint(5, 300))})
            self.ci_key[name] = (itemtype, len(rows))

    def _d(self, days):
        """A GLPI timestamp ``days`` (a float) before now, at a working-hours time."""
        t = self.now - timedelta(days=days)
        t = t.replace(hour=self.rng.randint(8, 17), minute=self.rng.randint(0, 59), second=self.rng.randint(0, 59))
        return min(t, self.now).strftime("%Y-%m-%d %H:%M:%S")

    def _fill(self, *texts):
        """Fills templates' placeholders with generic names, the same ones in each (a title and its description)."""
        r = self.rng
        names = {"room": r.choice(ROOMS), "team": r.choice(TEAMS), "share": r.choice(SHARES), "app": r.choice(APPS),
                 "floor": r.randint(1, 3), "n": r.choice([5, 10, 20, 30]), "ci": "{ci}"}
        return [t.format(**names) for t in texts]

    def _age(self, scale, cap=700):
        """Days since opened: mostly recent, with a long tail of history."""
        return min(int(self.rng.expovariate(1 / scale)), cap)

    def _record(self, cat, title, cis, text, age, open_statuses, done_statuses, open_chance):
        """One ITIL record (no id yet), open or done with a likelihood that falls with age."""
        r = self.rng
        ci_names = [r.choice(cis)] if cis else []
        title = title.replace("{ci}", ci_names[0] if ci_names else "a server")
        is_open = r.random() < open_chance(age)
        status = r.choice(open_statuses) if is_open else r.choice(done_statuses)
        if is_open:
            idle = r.uniform(31, age) if age > 45 and r.random() < 0.25 else r.uniform(0, min(age, 12))
        else:
            idle = max(age - r.uniform(0, min(age, 20)), 0)
        priority = r.choices(PRIORITIES, PRIORITY_WEIGHTS)[0]
        # GLPI returns rich text entity-encoded on some installs and plain HTML on others.
        content = f"<p>{text}</p>" if r.random() < 0.5 else f"&lt;p&gt;{text}&lt;/p&gt;"
        # Each timestamp gets its own time of day, so on the day it was opened an update could come out earlier.
        opened = self._d(age)
        updated = max(self._d(idle), opened)
        return {"name": title, "status": status, "priority": priority, "urgency": priority, "impact": priority,
                "itilcategories_id": self.cat_id.get(cat, 0), "date": opened, "date_mod": updated,
                "content": content, "_age": age, "_open": is_open, "_cis": ci_names,
                "_assigned": not is_open or r.random() < 0.85, "_cat": cat}

    def tickets(self):
        """Incidents and requests from ``TICKET_TEMPLATES``; most of the recent ones are open."""
        out = []
        for _ in range(TICKETS):
            cat, kind, title, cis, text = self.rng.choice(TICKET_TEMPLATES)
            title, text = self._fill(title, text)
            rec = self._record(cat, title, cis, text, self._age(150),
                               [1, 1, 2, 2, 3, 4], [5, 6, 6, 6], lambda a: 0.7 if a < 10 else 0.35 if a < 45 else 0.05)
            rec["type"] = kind
            if kind == 2:
                rec["_cis"] = rec["_cis"] if self.rng.random() < 0.3 else []
            elif rec["_cis"] and self.rng.random() < 0.1:
                rec["_cis"] = []
            out.append(rec)
        return out

    def problems(self):
        """One problem per ``PROBLEM_TEMPLATES`` entry, with its CIs and the ticket titles it explains."""
        out = []
        for cat, title, cis, text, match in PROBLEM_TEMPLATES:
            rec = self._record(cat, title, cis, text, self._age(200, 600) + 5,
                               [1, 7, 2, 3, 4, 8], [5, 6], lambda a: 0.5)
            rec["_cis"], rec["_match"] = list(cis), match
            out.append(rec)
        return out

    def changes(self):
        """The ``CHANGE_TEMPLATES`` changes and those made by each recurring change, with approval and plans."""
        out = []
        for cat, title, cis, text, fixes in CHANGE_TEMPLATES:
            rec = self._record(cat, title, cis, text or "See the plan.", self._age(120, 500),
                               [1, 9, 10, 10, 7, 11, 12, 5, 8], [6, 6, 14, 13], lambda a: 0.75 if a < 60 else 0.2)
            rec["_cis"], rec["_fixes"] = list(cis), fixes
            out.append(rec)
        for name, periodicity, every, cat, cis, count, _active in RECURRING:
            for i in range(count):
                age = i * every + self.rng.randint(0, 2)
                opened = self.now - timedelta(days=age)
                when = {"1MONTH": f"{opened:%B %Y}", "1WEEK": f"week {opened:%V} {opened:%G}",
                        "3MONTH": f"Q{(opened.month - 1) // 3 + 1} {opened.year}"}.get(periodicity, str(opened.year))
                # The latest one is open, the one before it may still be, and the rest are closed.
                chance = 1.0 if i == 0 else 0.5 if i == 1 else 0.0
                rec = self._record(cat, f"{name} - {when}", cis, f"Scheduled: {name.lower()}.", age,
                                   [1, 7, 11], [6], lambda a, c=chance: c)
                rec["_cis"], rec["_fixes"] = list(cis), ""
                rec["priority"] = rec["urgency"] = rec["impact"] = 3 if cat == "Security" else 2
                out.append(rec)
        for rec in out:
            st = rec["status"]
            standard = rec["_cat"] == "Standard change"
            rec["global_validation"] = (2 if st == 10 else 4 if st == 13 else 3 if st in (7, 11, 12, 5, 8, 6)
                                        else self.rng.choice([1, 1, 2]))
            empty = None if standard else (self.rng.choice(PLAN) if rec["_open"] and self.rng.random() < 0.3 else "")
            for f in PLAN:
                rec[f] = "" if standard or f == empty else "<p>Written and reviewed.</p>"
            if empty and self.rng.random() < 0.5:
                rec[empty] = "&lt;p&gt;&amp;nbsp;&lt;/p&gt;"     # an emptied editor, as GLPI encodes it
        return out

    @staticmethod
    def _number(rows):
        """Gives records ids in the order they were opened, as GLPI would."""
        rows.sort(key=lambda r: r["date"])
        for i, r in enumerate(rows, 1):
            r["id"] = i

    def build(self):
        """Every itemtype but the CIs: the records, numbered by date, and the links between them."""
        tickets, problems, changes = self.tickets(), self.problems(), self.changes()
        for rows in (tickets, problems, changes):
            self._number(rows)
        d = {"ITILCategory": [{"id": i, "completename": c} for c, i in self.cat_id.items()],
             "ProjectState": PROJECT_STATES}

        def links(table, field, rows):
            d[table] = [{"id": n, "itemtype": t, "items_id": i, field: r["id"]}
                        for n, (r, (t, i)) in enumerate(((r, self.ci_key[c]) for r in rows for c in r["_cis"]), 1)]

        links("Item_Ticket", "tickets_id", tickets)
        links("Item_Problem", "problems_id", problems)
        links("Change_Item", "changes_id", changes)

        pt, cp = [], []
        for p in problems:
            if p["_match"]:
                matched = [t for t in tickets if p["_match"].casefold() in t["name"].casefold()]
                pt += [(p["id"], t["id"]) for t in matched]
        for c in changes:
            p = next((p for p in problems if c["_fixes"] and p["name"].startswith(c["_fixes"])), None)
            if p:
                cp.append((c["id"], p["id"]))
        d["Problem_Ticket"] = [{"id": n, "problems_id": p, "tickets_id": t} for n, (p, t) in enumerate(pt, 1)]
        d["Change_Problem"] = [{"id": n, "changes_id": c, "problems_id": p} for n, (c, p) in enumerate(cp, 1)]

        # Who's assigned: a technician (user) for most, a group for the rest. Users and groups are just ids.
        for rows, user_t, group_t, field in ((tickets, "Ticket_User", "Group_Ticket", "tickets_id"),
                                             (problems, "Problem_User", "Group_Problem", "problems_id"),
                                             (changes, "Change_User", "Change_Group", "changes_id")):
            users, groups = [], []
            for r in rows:
                # The requester, which doesn't make a record assigned.
                users.append({field: r["id"], "users_id": self.rng.randint(10, 30), "type": 1})
                if not r["_assigned"]:
                    continue
                if self.rng.random() < 0.7:
                    users.append({field: r["id"], "users_id": self.rng.randint(2, 6), "type": 2})
                else:
                    groups.append({field: r["id"], "groups_id": self.rng.randint(1, 3), "type": 2})
            for target in (users, groups):
                for n, row in enumerate(target, 1):
                    row["id"] = n
            d[user_t], d[group_t] = users, groups

        d["RecurrentChange"] = []
        for n, (name, periodicity, every, _, _, _, active) in enumerate(RECURRING, 1):
            last = max((c for c in changes if c["name"].startswith(name)), key=lambda c: c["date"])
            nxt = datetime.fromisoformat(last["date"]).replace(hour=6, minute=0, second=0) + timedelta(days=every)
            while nxt < self.now:
                nxt += timedelta(days=every)
            d["RecurrentChange"].append({"id": n, "name": name, "is_active": active, "periodicity": periodicity,
                                         "next_creation_date": nxt.strftime("%Y-%m-%d %H:%M:%S"),
                                         "create_before": 2 * 86400 if every > 7 else 86400})

        d["Project"], d["Itil_Project"] = [], []
        for n, (name, code, state, done, cats) in enumerate(PROJECTS, 1):
            d["Project"].append({"id": n, "name": name, "code": code, "projectstates_id": state,
                                 "percent_done": done, "date": self._d(200 - 40 * n),
                                 "date_mod": self._d(n * 3), "content": f"<p>{name}, run by the IT team.</p>"})
            for itemtype, rows in (("Problem", problems), ("Change", changes)):
                d["Itil_Project"] += [{"itemtype": itemtype, "items_id": r["id"], "projects_id": n}
                                      for r in rows if r["_cat"] in cats]
        for n, row in enumerate(d["Itil_Project"], 1):
            row["id"] = n

        d["ImpactRelation"] = [
            {"id": n, "itemtype_source": self.ci_key[a][0], "items_id_source": self.ci_key[a][1],
             "itemtype_impacted": self.ci_key[b][0], "items_id_impacted": self.ci_key[b][1]}
            for n, (a, b) in enumerate(IMPACT, 1)]
        for table, rows in (("Ticket", tickets), ("Problem", problems), ("Change", changes)):
            d[table] = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        return d


def demo_dataset(seed=SEED, now=NOW):
    """Every itemtype the dashboard reads, as GLPI v1 returns it, plus the CIs by type.

    Args:
        seed: The random seed; the same seed and ``now`` give the same data.
        now: The time the dates are measured back from.

    Returns:
        A dict of rows by itemtype, in the shape ``fake_glpi.FakeGlpi`` serves.
    """
    demo = _Demo(seed, now)
    return {**demo.build(), **demo.cis}
