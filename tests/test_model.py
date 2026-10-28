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
    for t in snap["summary"] + snap["quality"] + [t for g in snap["in_flight"]["groups"] for t in g["tiles"]]:
        yield t["count"], t["key"]
    for a in snap["health"]["areas"]:
        yield a["incidents"], a["incidents_list"]
        yield a["problems"], a["problems_list"]
    for c in snap["health"]["cis"]:
        for part in ("incidents", "problems", "changes"):
            yield c[part], c[part + "_list"]
    for r in snap["health"]["recurring"]:
        yield r["open"], r["open_list"]
    for p in snap["lists"]["projects"]["rows"]:
        yield p["open"], p["open_list"]
        yield p["total"], p["total_list"]
    yield snap["risks"]["total"], snap["risks"]["list"]
    for g in snap["risks"]["priorities"] + snap["risks"]["kinds"] + snap["risks"]["cells"]:
        yield g["count"], g["list"]


def _length(lst):
    return len(lst["rows"]) if "rows" in lst else len(lst["refs"])


def test_every_count_is_the_length_of_its_list(snap):
    pairs = list(_counts(snap))
    assert len(pairs) > 40
    for count, key in pairs:
        assert count == _length(snap["lists"][key]), key


def test_table_lists_say_which_columns_to_show(snap):
    tables = {k: lst["kind"] for k, lst in snap["lists"].items() if "rows" in lst}
    assert tables == {"projects": "projects"}


def test_every_listed_record_is_sent_and_nothing_else(snap):
    used = {k for lst in snap["lists"].values() for k in lst.get("refs", ())}
    assert set(snap["records"]) == used
    # Closed and cancelled records nobody lists aren't sent.
    assert "Problem:2" not in snap["records"] and "Change:5" not in snap["records"]


def test_internal_fields_are_not_sent(snap):
    for r in snap["records"].values():
        assert not [f for f in r if f.startswith("_")]


def test_lists_have_no_duplicates(snap):
    for key, lst in snap["lists"].items():
        if "refs" in lst:
            assert len(lst["refs"]) == len(set(lst["refs"])), key


# --- summary --------------------------------------------------------------------------------------------------

def test_summary_counts(snap):
    counts = {t["key"]: t["count"] for t in snap["summary"]}
    assert counts == {"open-incidents": 3, "open-requests": 1, "open-problems": 1,
                      "open-changes": 3, "high-priority": 2}


def test_summary_lists(snap):
    assert set(refs(snap, "open-changes")) == {"Change:1", "Change:2", "Change:4"}   # not Applied C3
    assert set(refs(snap, "high-priority")) == {"Ticket:1", "Change:1"}


# --- record quality -------------------------------------------------------------------------------------------

def test_quality_counts(snap):
    counts = {t["key"]: t["count"] for t in snap["quality"]}
    assert counts == {"no-category": 2, "no-ci": 2, "unassigned": 4, "stale": 2,
                      "orphan-problems": 0, "no-approval": 0, "empty-plan": 1}


def test_every_tile_has_a_colour_kind(snap):
    tiles = snap["summary"] + snap["quality"] + [t for g in snap["in_flight"]["groups"] for t in g["tiles"]]
    kinds = {"incident", "request", "problem", "change", "project", "issue"}
    assert all(t["kind"] in kinds for t in tiles)
    by_key = {t["key"]: t["kind"] for t in tiles}
    assert (by_key["open-incidents"], by_key["open-problems"], by_key["open-changes"]) == (
        "incident", "problem", "change")
    assert (by_key["requests-new"], by_key["orphan-problems"], by_key["awaiting-approval"], by_key["projects"]) == (
        "request", "problem", "change", "project")
    # A group's tiles share its colour.
    for g in snap["in_flight"]["groups"]:
        assert {t["kind"] for t in g["tiles"]} == {g["kind"]}


def test_quality_tiles_have_a_short_label_a_title_and_the_full_rule(snap):
    t = {t["key"]: t for t in snap["quality"]}["no-ci"]
    assert t["label"] == "No CI"
    assert snap["lists"]["no-ci"]["title"] == t["title"] == "Open incidents, problems and changes without a CI"
    assert "Requests are left out" in t["detail"]
    assert all(len(t["label"]) <= 20 and t["detail"] for t in snap["quality"])


def test_quality_lists(snap):
    assert set(refs(snap, "no-category")) == {"Ticket:3", "Ticket:5"}
    # Request T3 has no CI either, but requests needn't have one.
    assert set(refs(snap, "no-ci")) == {"Ticket:5", "Change:4"}
    # T2 has only a requester; T5 and C2 are assigned to a group.
    assert set(refs(snap, "unassigned")) == {"Ticket:2", "Ticket:3", "Change:3", "Change:4"}
    # Last updated 45 and 100 days ago; C3 was updated 10 days ago.
    assert set(refs(snap, "stale")) == {"Problem:1", "Change:2"}
    # C2's Backup plan is an empty editor, entity-encoded; standard change C4 has no plan and isn't listed.
    assert refs(snap, "empty-plan") == ["Change:2"]


def test_stale_falls_back_to_the_opening_date():
    data = model_input()
    data["Ticket"][0].update(date_mod=None)          # T1, opened 10 days ago
    data["Ticket"][1].update(date_mod=None, date=(NOW - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S"))
    stale = set(refs(build(data), "stale"))
    assert "Ticket:2" in stale and "Ticket:1" not in stale


def test_stale_days_is_configurable():
    snap = model.build(model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA, stale_days=60)
    assert refs(snap, "stale") == ["Change:2"]            # P1, last updated 45 days ago, no longer counts
    tile = next(t for t in snap["quality"] if t["key"] == "stale")
    assert (tile["label"], tile["title"]) == ("Stale (60 d)", "Open records not updated in 60 days")


def test_orphan_problem_has_no_incident_and_no_change():
    data = model_input()
    data["Problem"] += [{**data["Problem"][0], "id": 3}, {**data["Problem"][0], "id": 4},
                        {**data["Problem"][0], "id": 5}]
    data["Problem_Ticket"].append({"id": 3, "problems_id": 3, "tickets_id": 3})   # linked to a request
    data["Change_Problem"].append({"id": 2, "changes_id": 2, "problems_id": 4})   # preventive: a change only
    assert refs(build(data), "orphan-problems") == ["Problem:5"]


def test_no_approval_counts_only_non_standard_changes_in_new():
    data = model_input()
    for c in data["Change"]:
        c["global_validation"] = 1
    data["Change"][0]["status"] = 1                  # C1 back in New
    # C2 (Accepted) and C3 (Applied) are past New; C4 is in New but a standard change; C5 is cancelled.
    assert refs(build(data), "no-approval") == ["Change:1"]


def test_no_approval_ignores_a_change_in_new_awaiting_approval():
    data = model_input()
    data["Change"][0]["status"] = 1                  # C1 in New, approval already requested (2)
    assert refs(build(data), "no-approval") == []


def test_unassigned_ignores_requesters_and_observers():
    data = model_input()
    data["Ticket_User"] = [{"id": 1, "tickets_id": 1, "users_id": 2, "type": 3}]
    data["Group_Ticket"] = [{"id": 1, "tickets_id": 5, "groups_id": 1, "type": 1}]
    assert {"Ticket:1", "Ticket:5"} <= set(refs(build(data), "unassigned"))


@pytest.mark.parametrize("value,blank", [
    (None, True), ("", True), ("   ", True), ("<p></p>", True), ("<p>&nbsp;</p>", True),
    ("&lt;p&gt;&amp;nbsp;&lt;/p&gt;", True), ("&#60;p&#62;&#60;/p&#62;", True), ("<p><br></p>", True),
    ("<p>x</p>", False), ("&lt;p&gt;Roll back&lt;/p&gt;", False), ("plain text", False), ("0", False),
])
def test_blank_rich_text(value, blank):
    assert model._blank(value) is blank


def test_quality_text_is_safe_with_markup_in_plan_fields():
    data = model_input()
    data["Change"][0]["impactcontent"] = '<img src=x onerror="alert(1)">'    # a tag and no text: blank
    assert "Change:1" in refs(build(data), "empty-plan")


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
    assert r["updated"] == (NOW - timedelta(days=5)).date().isoformat()
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


def test_missing_last_update_gives_none():
    data = model_input()
    data["Ticket"][0]["date_mod"] = None
    del data["Ticket"][1]["date_mod"]
    snap = build(data)
    assert snap["records"]["Ticket:1"]["updated"] is None
    assert snap["records"]["Ticket:2"]["updated"] is None


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


def test_standard_change_area_is_configurable():
    snap = model.build(model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA, standard_change_area="Network")
    # "Standard change" is now an ordinary area. Network still shows: an area with an open incident always does.
    assert {a["area"] for a in snap["health"]["areas"]} >= {"Standard change", "Network"}
    # C2 (Network) is now a standard change: no risk score, no plan check. C4 is an ordinary change in New.
    assert set(refs(snap, "risks-all")) == {"Change:1", "Problem:1", "Change:4"}
    assert refs(snap, "empty-plan") == ["Change:4"]
    assert refs(snap, "no-approval") == ["Change:4"]


def test_no_standard_change_area_checks_every_change():
    snap = model.build(model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA, standard_change_area="")
    assert "Standard change" in {a["area"] for a in snap["health"]["areas"]}
    assert "Change:4" in refs(snap, "risks-all")
    assert set(refs(snap, "empty-plan")) == {"Change:2", "Change:4"}


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

def _risks(snap):
    """(key, risk) for every ranked record, in rank order."""
    return [(k, snap["records"][k]["risk"]) for k in refs(snap, "risks-all")]


def test_risk_scores_and_order(snap):
    # C1: High 45 + security 15 + internet 15 + age 5 d rounds to 0          = 75
    # P1: Medium 25 + security 15 + internet 15 + age 90/180*15 = 8 + 1 incident 5 = 68
    # C2: Medium 25 + internet (firewall, an extra) 15 + age capped at 15   = 55
    assert [(k, r["rank"], r["score"]) for k, r in _risks(snap)] == [
        ("Change:1", 1, 75), ("Problem:1", 2, 68), ("Change:2", 3, 55)]
    assert snap["risks"]["total"] == 3
    assert snap["lists"]["risks-all"]["kind"] == "risks"


def test_risk_explains_each_point(snap):
    why = {k: r["why"] for k, r in _risks(snap)}
    assert why["Problem:1"] == ["priority Medium +25", "security +15", "internet-facing (web1) +15",
                                "age 90 d +8", "1 open incident(s) +5"]
    assert why["Change:2"] == ["priority Medium +25", "internet-facing (firewall) +15", "age 200 d +15"]


def test_risks_skip_applied_and_standard_changes(snap):
    keys = set(refs(snap, "risks-all"))
    assert "Change:3" not in keys and "Change:4" not in keys
    assert "risk" not in snap["records"]["Change:3"]


def test_risk_areas_are_configurable():
    snap = model.build(model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA, risk_areas={"Network": 20})
    # C2 (Network): 25 + 20 + internet 15 + age 15 = 75. C1 and P1 lose their security 15: 60 and 53.
    assert [(k, r["score"]) for k, r in _risks(snap)] == [("Change:2", 75), ("Change:1", 60), ("Problem:1", 53)]
    assert snap["records"]["Change:2"]["risk"]["why"] == [
        "priority Medium +25", "network +20", "internet-facing (firewall) +15", "age 200 d +15"]


def test_no_risk_areas_gives_no_area_bonus():
    snap = model.build(model_input(), NOW, PUBLIC_URL, ROOTS, EXTRA, risk_areas={})
    assert [(k, r["score"]) for k, r in _risks(snap)] == [("Change:1", 60), ("Change:2", 55), ("Problem:1", 53)]
    assert not any("security" in w for _, r in _risks(snap) for w in r["why"])


def test_incident_bonus_is_capped():
    data = model_input()
    for i in range(10, 20):
        data["Ticket"].append({**data["Ticket"][1], "id": i})
        data["Problem_Ticket"].append({"id": i, "problems_id": 1, "tickets_id": i})
    p1 = build(data)["records"]["Problem:1"]["risk"]
    assert p1["why"][-1] == f"11 open incident(s) +{model.RISK_INCIDENTS_MAX}"


def test_risks_group_by_priority_and_kind(snap):
    risks = snap["risks"]
    assert [(p["priority"], p["name"], p["count"]) for p in risks["priorities"]] == [(4, "High", 1), (3, "Medium", 2)]
    assert [(k["kind"], k["count"]) for k in risks["kinds"]] == [("Problem", 1), ("Change", 2)]
    # Empty cells (High problems) are left out.
    assert [(c["priority"], c["kind"], c["count"]) for c in risks["cells"]] == [
        (4, "Change", 1), (3, "Problem", 1), (3, "Change", 1)]
    assert refs(snap, "risks-p3") == ["Problem:1", "Change:2"]        # score order, not priority then age
    assert refs(snap, "risks-change") == ["Change:1", "Change:2"]
    assert refs(snap, "risks-p3-change") == ["Change:2"]
    assert snap["lists"]["risks-p3-problem"]["title"] == "Risks: problems at Medium priority"


def test_risk_groups_each_add_up_to_the_total(snap):
    risks = snap["risks"]
    for groups in (risks["priorities"], risks["kinds"], risks["cells"]):
        assert sum(g["count"] for g in groups) == risks["total"]
        assert sorted(k for g in groups for k in refs(snap, g["list"])) == sorted(refs(snap, "risks-all"))


def test_risk_groups_use_the_priorities_present():
    data = model_input()
    data["Problem"][0]["priority"] = 9                    # not one GLPI defines
    risks = build(data)["risks"]
    assert [(p["priority"], p["name"]) for p in risks["priorities"]] == [(9, "?"), (4, "High"), (3, "Medium")]
    assert sum(p["count"] for p in risks["priorities"]) == risks["total"]


# --- in flight ------------------------------------------------------------------------------------------------

def flight(snap, group):
    [g] = [g for g in snap["in_flight"]["groups"] if g["title"] == group]
    return {t["key"]: t["count"] for t in g["tiles"]}


def test_in_flight_groups(snap):
    assert [g["title"] for g in snap["in_flight"]["groups"]] == [
        "Incidents", "Requests", "Problems", "Changes", "Projects"]


def test_in_flight_tickets_and_problems_by_status(snap):
    # Incidents T1 assigned, T2 new, T5 pending (T4 closed); request T3 new; problem P1 accepted.
    assert flight(snap, "Incidents") == {"incidents-new": 1, "incidents-approval": 0,
                                         "incidents-processing-assigned": 1, "incidents-processing-planned": 0,
                                         "incidents-pending": 1}
    assert flight(snap, "Requests")["requests-new"] == 1
    assert sum(flight(snap, "Requests").values()) == 1
    assert flight(snap, "Problems") == {"problems-new": 0, "problems-accepted": 1,
                                        "problems-processing-assigned": 0, "problems-processing-planned": 0,
                                        "problems-pending": 0, "problems-under-observation": 0}
    assert refs(snap, "incidents-pending") == ["Ticket:5"]


def test_in_flight_tiles_have_a_short_label_and_a_full_title(snap):
    tiles = {t["key"]: t for g in snap["in_flight"]["groups"] for t in g["tiles"]}
    assert (tiles["incidents-pending"]["label"], tiles["incidents-pending"]["title"]) == (
        "Pending", "Incidents: Pending")
    assert snap["lists"]["incidents-pending"]["title"] == "Incidents: Pending"


def test_in_flight_changes(snap):
    assert flight(snap, "Changes") == {"awaiting-approval": 1, "changes-accepted": 1, "changes-testing": 0,
                                       "changes-qualification": 0, "changes-applied": 1}
    assert refs(snap, "awaiting-approval") == ["Change:1"]
    assert refs(snap, "changes-applied") == ["Change:3"]


def test_in_flight_projects_tile(snap):
    assert flight(snap, "Projects") == {"projects": 1}


def test_awaiting_approval_uses_global_validation_not_status():
    data = model_input()
    data["Change"][1]["global_validation"] = 2    # C2, status Accepted, still waiting on an approver
    data["Change"][2]["global_validation"] = 2    # C3 Applied: not "awaiting" any more
    assert set(refs(build(data), "awaiting-approval")) == {"Change:1", "Change:2"}


def test_recurring_changes(snap):
    rec = snap["health"]["recurring"]
    assert [(r["name"], r["next_creation"], r["due"]) for r in rec] == [
        ("Monthly patching", "2026-11-01", "2026-11-03"),   # due = next creation + create_before (2 d)
        ("Unscheduled review", None, None),                 # no date sorts last
    ]                                                       # inactive "Retired check" is left out
    assert rec[0]["url"] == f"{PUBLIC_URL}/front/recurrentchange.form.php?id=1"


def test_recurring_changes_count_open_changes_by_title(snap):
    rec = {r["name"]: r for r in snap["health"]["recurring"]}
    assert refs(snap, rec["Monthly patching"]["open_list"]) == ["Change:4"]
    assert rec["Unscheduled review"]["open"] == 0


def test_recurring_change_match_ignores_case_and_prefers_the_longest_name():
    data = model_input()
    data["RecurrentChange"].append({"id": 4, "name": "Monthly patching web", "is_active": 1})
    data["Change"] += [
        {**data["Change"][3], "id": 6, "name": "MONTHLY PATCHING - November"},
        {**data["Change"][3], "id": 7, "name": "Monthly patching web - November"},
        {**data["Change"][3], "id": 8, "name": "Monthly patching", "status": 6},        # closed
        {**data["Change"][3], "id": 9, "name": "Retired check 1"},                      # inactive
        {**data["Change"][3], "id": 10, "name": None},
    ]
    snap = build(data)
    rec = {r["name"]: r for r in snap["health"]["recurring"]}
    assert set(refs(snap, rec["Monthly patching"]["open_list"])) == {"Change:4", "Change:6"}
    assert refs(snap, rec["Monthly patching web"]["open_list"]) == ["Change:7"]
    assert "Retired check" not in rec


def test_recurring_change_with_a_blank_name_matches_nothing():
    data = model_input()
    data["RecurrentChange"].append({"id": 4, "name": "  ", "is_active": 1})
    assert [r["name"] for r in build(data)["health"]["recurring"]] == ["Monthly patching", "Unscheduled review"]


def test_projects(snap):
    [p] = snap["lists"]["projects"]["rows"]
    assert (p["name"], p["code"], p["state"], p["percent_done"]) == ("Certificate automation", "PRJ1", "Processing", 40)
    assert (p["open"], p["total"]) == (2, 3)          # the link to a missing Change #99 is ignored
    assert set(refs(snap, p["total_list"])) == {"Change:1", "Problem:1", "Ticket:4"}


# --- edge cases -----------------------------------------------------------------------------------------------

def test_empty_glpi():
    empty = {t: [] for t in dataset() if t not in ("Computer", "Appliance")}
    snap = build({**empty, "cis": {}})
    assert all(t["count"] == 0 for t in snap["summary"])
    assert snap["health"] == {"areas": [], "cis": [], "recurring": []}
    assert snap["risks"] == {"total": 0, "list": "risks-all", "priorities": [], "kinds": [], "cells": []}
    assert snap["records"] == {}


def test_area_names_make_safe_list_keys():
    data = model_input()
    data["ITILCategory"].append({"id": 6, "completename": "Backup & Restore"})
    data["Ticket"][1]["itilcategories_id"] = 6
    keys = {a["incidents_list"] for a in build(data)["health"]["areas"]}
    assert "area-backup-restore-incidents" in keys


def test_areas_are_the_top_level_categories_and_uncategorised():
    assert model.areas(dataset()["ITILCategory"]) == {"Security", "Network", "Standard change", "Hosting",
                                                       "Uncategorised"}
    assert model.areas([]) == {"Uncategorised"}
