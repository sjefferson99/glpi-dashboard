"""model.build() on the fake dataset. The expected numbers are worked out by hand from fake_glpi.dataset():

open incidents T1 T2 T5, request T3, problem P1; changes C1 (approval) C2 (accepted) C3 (applied)
C4 (standard change); web1 is internet-facing via reverse-proxy, firewall via the extras.
"""
from datetime import timedelta

import pytest

import model
from fake_glpi import EXTRA, NOW, PUBLIC_URL, ROOTS, dataset, model_input


def build(data=None, now=NOW):
    return model.build(data or model_input(), now, PUBLIC_URL, ROOTS, EXTRA)


@pytest.fixture(scope="module")
def snap():
    return build()


def refs(snap, key):
    return snap["lists"][key]["refs"]


# --- the invariant: a count is the length of its list --------------------------------------------------------

def _counts(snap):
    """Every (count, list key) pair the page shows."""
    for t in snap["summary"] + snap["in_flight"]["tiles"]:
        yield t["count"], t["key"]
    for a in snap["health"]["areas"]:
        yield a["incidents"], a["incidents_list"]
        yield a["problems"], a["problems_list"]
    for c in snap["health"]["cis"]:
        for part in ("incidents", "problems", "changes"):
            yield c[part], c[part + "_list"]
    for p in snap["in_flight"]["projects"]:
        yield p["open"], p["open_list"]
        yield p["total"], p["total_list"]
    yield snap["risks"]["total"], snap["risks"]["list"]


def test_every_count_is_the_length_of_its_list(snap):
    pairs = list(_counts(snap))
    assert len(pairs) > 20
    for count, key in pairs:
        assert count == len(refs(snap, key)), key


def test_every_listed_record_is_sent_and_nothing_else(snap):
    used = {k for lst in snap["lists"].values() for k in lst["refs"]}
    assert set(snap["records"]) == used
    # Closed and cancelled records nobody lists aren't sent.
    assert "Problem:2" not in snap["records"] and "Change:5" not in snap["records"]


def test_internal_fields_are_not_sent(snap):
    for r in snap["records"].values():
        assert not [f for f in r if f.startswith("_")]


def test_lists_have_no_duplicates(snap):
    for key, lst in snap["lists"].items():
        assert len(lst["refs"]) == len(set(lst["refs"])), key


# --- summary --------------------------------------------------------------------------------------------------

def test_summary_counts(snap):
    counts = {t["key"]: t["count"] for t in snap["summary"]}
    assert counts == {"open-incidents": 3, "open-requests": 1, "open-problems": 1,
                      "open-changes": 3, "high-priority": 2, "no-category": 2}


def test_summary_lists(snap):
    assert set(refs(snap, "open-changes")) == {"Change:1", "Change:2", "Change:4"}   # not Applied C3
    assert set(refs(snap, "high-priority")) == {"Ticket:1", "Change:1"}
    assert set(refs(snap, "no-category")) == {"Ticket:3", "Ticket:5"}


def test_lists_sort_by_priority_then_age(snap):
    # T1 High, T5 Medium, T2 Low.
    assert refs(snap, "open-incidents") == ["Ticket:1", "Ticket:5", "Ticket:2"]


# --- records --------------------------------------------------------------------------------------------------

def test_record_fields(snap):
    r = snap["records"]["Ticket:1"]
    assert r["kind"] == "Incident" and r["ref"] == "Incident #1"
    assert r["status"] == "Processing (assigned)" and r["open"] is True
    assert r["priority_name"] == "High"
    assert r["category"] == "Security > Certificates" and r["area"] == "Security"
    assert r["age_days"] == 10 and r["date"] == (NOW - timedelta(days=10)).date().isoformat()
    assert r["url"] == f"{PUBLIC_URL}/front/ticket.form.php?id=1"
    assert r["cis"] == [{"name": "web1", "url": f"{PUBLIC_URL}/front/computer.form.php?id=1", "internet": True}]


def test_request_is_a_ticket_of_type_2(snap):
    assert snap["records"]["Ticket:3"]["kind"] == "Request"
    assert snap["records"]["Ticket:3"]["area"] == "Uncategorised"


def test_unknown_status_and_priority_are_shown_raw():
    data = model_input()
    data["Ticket"][0].update(status=99, priority=9)
    r = build(data)["records"]["Ticket:1"]
    assert r["status"] == "99" and r["priority_name"] == "?"


def test_future_or_missing_date_gives_age_zero():
    data = model_input()
    data["Ticket"][0]["date"] = "2027-01-01 00:00:00"
    data["Ticket"][1]["date"] = None
    snap = build(data)
    assert snap["records"]["Ticket:1"]["age_days"] == 0
    assert snap["records"]["Ticket:2"]["age_days"] == 0


def test_ci_without_a_readable_name_shows_type_and_id():
    data = model_input()
    data["cis"]["Computer"] = []    # main.collect() leaves an unreadable CI type empty
    r = build(data)["records"]["Ticket:2"]
    assert r["cis"][0]["name"] == "Computer #2"


def test_namespaced_ci_type_links_to_glpi_itself():
    b = model.Builder(model_input(), NOW, PUBLIC_URL + "/", [], [])
    assert b.ci_url("Glpi\\CustomAsset\\Thing", 3) == PUBLIC_URL + "/"
    assert b.ci_url("NetworkEquipment", "7") == f"{PUBLIC_URL}/front/networkequipment.form.php?id=7"
    assert b.ci_url("Computer\n", 1) == PUBLIC_URL + "/"     # not a plain type: no broken form link


def test_glpi_text_is_passed_through_untouched():
    # Escaping is the page's job (textContent); the model must not mangle or drop text.
    data = model_input()
    data["Ticket"][0]["name"] = '<img src=x onerror="alert(1)"> & co'
    assert build(data)["records"]["Ticket:1"]["name"] == '<img src=x onerror="alert(1)"> & co'


# --- health ---------------------------------------------------------------------------------------------------

def test_areas_with_rag(snap):
    areas = {a["area"]: (a["rag"], a["incidents"], a["problems"]) for a in snap["health"]["areas"]}
    assert areas == {
        "Hosting": ("green", 0, 0),          # a category with nothing open still shows
        "Network": ("amber", 1, 0),          # Low incident: any incident is amber
        "Security": ("red", 1, 1),           # High incident
        "Uncategorised": ("amber", 1, 0),
    }
    assert [a["area"] for a in snap["health"]["areas"]] == sorted(areas)


def test_standard_change_is_not_an_area(snap):
    assert "Standard change" not in {a["area"] for a in snap["health"]["areas"]}


@pytest.mark.parametrize("items,expected", [
    ([], "green"),
    ([{"kind": "Problem", "priority": 2}], "green"),
    ([{"kind": "Problem", "priority": 3}], "amber"),
    ([{"kind": "Incident", "priority": 1}], "amber"),
    ([{"kind": "Problem", "priority": 4}], "red"),
    ([{"kind": "Incident", "priority": 2}, {"kind": "Problem", "priority": 6}], "red"),
])
def test_rag_rules(items, expected):
    assert model._rag(items) == expected


def test_cis_with_open_issues(snap):
    cis = snap["health"]["cis"]
    # firewall has only a change, so it isn't listed; red sorts before amber.
    assert [(c["name"], c["rag"], c["internet"]) for c in cis] == [("web1", "red", True), ("db1", "amber", False)]
    web1 = cis[0]
    assert (web1["incidents"], web1["problems"], web1["changes"]) == (1, 1, 1)
    # db1's only change is Applied, which doesn't count as open work.
    assert cis[1]["changes"] == 0


# --- risks ----------------------------------------------------------------------------------------------------

def test_risk_scores_and_order(snap):
    top = [(s["key"], s["score"]) for s in snap["risks"]["top"]]
    # C1: High 45 + security 15 + internet 15 + age 5 d rounds to 0          = 75
    # P1: Medium 25 + security 15 + internet 15 + age 90/180*15 = 8 + 1 incident 5 = 68
    # C2: Medium 25 + internet (firewall, an extra) 15 + age capped at 15   = 55
    assert top == [("Change:1", 75), ("Problem:1", 68), ("Change:2", 55)]
    assert snap["risks"]["total"] == 3


def test_risk_explains_each_point(snap):
    why = {s["key"]: s["why"] for s in snap["risks"]["top"]}
    assert why["Problem:1"] == ["priority Medium +25", "security +15", "internet-facing (web1) +15",
                                "age 90 d +8", "1 open incident(s) +5"]
    assert why["Change:2"] == ["priority Medium +25", "internet-facing (firewall) +15", "age 200 d +15"]


def test_risks_skip_applied_and_standard_changes(snap):
    keys = {s["key"] for s in snap["risks"]["top"]}
    assert "Change:3" not in keys and "Change:4" not in keys


def test_incident_bonus_is_capped():
    data = model_input()
    for i in range(10, 20):
        data["Ticket"].append({**data["Ticket"][1], "id": i})
        data["Problem_Ticket"].append({"id": i, "problems_id": 1, "tickets_id": i})
    p1 = next(s for s in build(data)["risks"]["top"] if s["key"] == "Problem:1")
    assert p1["why"][-1] == f"11 open incident(s) +{model.RISK_INCIDENTS_MAX}"


def test_top_risks_are_capped_but_the_list_has_all():
    data = model_input()
    data["Problem"] = [{**data["Problem"][0], "id": i} for i in range(1, model.RISK_TOP + 6)]
    risks = build(data)["risks"]
    assert len(risks["top"]) == model.RISK_TOP
    assert risks["total"] == model.RISK_TOP + 5 + 2   # + C1, C2


# --- in flight ------------------------------------------------------------------------------------------------

def test_in_flight_tiles(snap):
    tiles = {t["key"]: t["count"] for t in snap["in_flight"]["tiles"]}
    assert tiles == {"awaiting-approval": 1, "changes-accepted": 1, "changes-testing": 0,
                     "changes-qualification": 0, "changes-applied": 1}
    assert refs(snap, "awaiting-approval") == ["Change:1"]
    assert refs(snap, "changes-applied") == ["Change:3"]


def test_awaiting_approval_uses_global_validation_not_status():
    data = model_input()
    data["Change"][1]["global_validation"] = 2    # C2, status Accepted, still waiting on an approver
    data["Change"][2]["global_validation"] = 2    # C3 Applied: not "awaiting" any more
    assert set(refs(build(data), "awaiting-approval")) == {"Change:1", "Change:2"}


def test_recurring_changes(snap):
    rec = snap["in_flight"]["recurring"]
    assert [(r["name"], r["next_creation"], r["due"]) for r in rec] == [
        ("Monthly patching", "2026-11-01", "2026-11-03"),   # due = next creation + create_before (2 d)
        ("Unscheduled review", None, None),                 # no date sorts last
    ]                                                       # inactive "Retired check" is left out
    assert rec[0]["url"] == f"{PUBLIC_URL}/front/recurrentchange.form.php?id=1"


def test_projects(snap):
    [p] = snap["in_flight"]["projects"]
    assert (p["name"], p["code"], p["state"], p["percent_done"]) == ("Certificate automation", "PRJ1", "Processing", 40)
    assert (p["open"], p["total"]) == (2, 3)          # the link to a missing Change #99 is ignored
    assert set(refs(snap, p["total_list"])) == {"Change:1", "Problem:1", "Ticket:4"}


# --- edge cases -----------------------------------------------------------------------------------------------

def test_empty_glpi():
    empty = {t: [] for t in dataset() if t not in ("Computer", "Appliance")}
    snap = build({**empty, "cis": {}})
    assert all(t["count"] == 0 for t in snap["summary"])
    assert snap["health"] == {"areas": [], "cis": []}
    assert snap["risks"]["top"] == [] and snap["records"] == {}


def test_area_names_make_safe_list_keys():
    data = model_input()
    data["ITILCategory"].append({"id": 6, "completename": "Backup & Restore"})
    data["Ticket"][1]["itilcategories_id"] = 6
    keys = {a["incidents_list"] for a in build(data)["health"]["areas"]}
    assert "area-backup-restore-incidents" in keys
