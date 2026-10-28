"""The Record explorer as a user sees it: the treemap, its groupings and colours, picking, zooming, links and safety.

The fake dataset's 9 open records are 3 incidents, 1 request, 1 problem and 4 changes; with closed ones, 12.
"""
import re

import pytest
from playwright.sync_api import Page, expect

XSS = '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>'


def open_explorer(page: Page, path="/"):
    page.goto(path)
    expect(page.locator("#updated")).to_contain_text("Updated")
    page.get_by_role("tab", name="Record explorer").click()
    expect(page.locator("#treemap a").first).to_be_visible()


def box(page: Page, name):
    """A treemap box by its path, e.g. "Change › Medium"."""
    label = re.compile(rf"^{re.escape(name)}: \d+ records? - show list$")
    return page.locator("#treemap").get_by_role("link", name=label)


def pick(page: Page, name):
    """Clicks a box where a user would: its top-left corner, which is never under a child box."""
    box(page, name).click(position={"x": 4, "y": 4})


def shown_refs(page: Page):
    return page.locator("#explore-rows .chip").all_inner_texts()


def choose(page: Page, tier1, tier2="", tier3="", colour=None):
    page.locator("#explore-tier-1").select_option(tier1)
    page.locator("#explore-tier-2").select_option(tier2)
    page.locator("#explore-tier-3").select_option(tier3)
    if colour:
        page.locator("#explore-colour").select_option(colour)


def test_explorer_shows_open_records_by_type_then_priority_then_area(page: Page, dashboard, console_errors):
    open_explorer(page)
    expect(page).to_have_url(re.compile(r"#explore=kind,priority,area&colour=kind$"))
    for name, n in (("Change", 4), ("Incident", 3), ("Request", 1), ("Problem", 1)):
        expect(box(page, name)).to_have_attribute("aria-label", f"{name}: {n} record{'s' * (n > 1)} - show list")
    expect(box(page, "Change › Medium › Network")).to_be_visible()
    expect(page.locator("#explore-title")).to_have_text("All records")
    expect(page.locator("#explore-count")).to_have_text("9 records (open only) - each opens in GLPI")
    expect(page.locator("#explore-rows tbody tr")).to_have_count(9)
    assert console_errors == []


def test_boxes_are_sized_by_their_number_of_records(page: Page, dashboard):
    open_explorer(page)
    size = {n: box(page, n).bounding_box() for n in ("Change", "Incident")}
    area = {n: b["width"] * b["height"] for n, b in size.items()}
    assert area["Change"] / area["Incident"] == pytest.approx(4 / 3, rel=0.05)


def test_include_closed_adds_the_closed_records(page: Page, dashboard):
    open_explorer(page)
    page.locator("#explore-closed").check()
    expect(page.locator("#explore-count")).to_have_text("12 records - each opens in GLPI")
    expect(box(page, "Change")).to_have_attribute("aria-label", "Change: 5 records - show list")
    expect(page).to_have_url(re.compile("&closed=1"))


def test_picking_a_box_lists_exactly_its_records(page: Page, dashboard):
    open_explorer(page)
    pick(page, "Change")
    expect(page.locator("#explore-title")).to_have_text("Change")
    expect(page.locator("#explore-count")).to_have_text("4 records (open only) - each opens in GLPI")
    assert sorted(shown_refs(page)) == ["Change #1", "Change #2", "Change #3", "Change #4"]
    expect(box(page, "Change")).to_have_attribute("aria-current", "true")
    box(page, "Incident › High › Security").click()
    expect(page.locator("#explore-title")).to_have_text("Incident › High › Security")
    assert shown_refs(page) == ["Incident #1"]


def test_every_box_count_matches_its_list(page: Page, dashboard):
    open_explorer(page)
    page.locator("#explore-closed").check()
    labels = page.locator("#treemap a").evaluate_all("as => as.map(a => a.getAttribute('aria-label'))")
    assert len(labels) > 12
    for label in labels:
        name, n = re.fullmatch(r"(.+): (\d+) records? - show list", label).groups()
        pick(page, name)
        expect(page.locator("#explore-title")).to_have_text(name)
        expect(page.locator("#explore-rows tbody tr")).to_have_count(int(n))


def test_records_link_to_glpi_in_a_new_tab(page: Page, dashboard):
    open_explorer(page)
    pick(page, "Request")
    link = page.locator("#explore-rows").get_by_role("link", name="New user account")
    expect(link).to_have_attribute("href", "https://glpi.example.test/front/ticket.form.php?id=3")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener")


def test_regrouping_and_the_choice_is_remembered(page: Page, dashboard):
    open_explorer(page)
    choose(page, "area", "status")
    expect(page).to_have_url(re.compile(r"#explore=area,status&colour=kind$"))
    expect(box(page, "Network")).to_have_attribute("aria-label", "Network: 3 records - show list")
    # The colour is split out last, so each smallest box is one record type.
    expect(box(page, "Network › Accepted › Change")).to_have_class(re.compile(r"\bkind-change\b"))
    page.goto("/")
    page.get_by_role("tab", name="Record explorer").click()
    expect(page.locator("#explore-tier-1")).to_have_value("area")
    expect(page.locator("#explore-tier-2")).to_have_value("status")
    expect(page.locator("#explore-tier-3")).to_have_value("")


def test_a_grouping_used_above_cant_be_picked_again(page: Page, dashboard):
    open_explorer(page)
    expect(page.locator("#explore-tier-2 option[value=kind]")).to_have_attribute("disabled", "")
    expect(page.locator("#explore-tier-3 option[value=priority]")).to_have_attribute("disabled", "")
    expect(page.locator("#explore-tier-3 option[value=status]")).not_to_have_attribute("disabled", "")
    # Moving the top grouping to one used lower down drops it there.
    page.locator("#explore-tier-1").select_option("priority")
    expect(page).to_have_url(re.compile(r"#explore=priority,area&"))
    expect(page.locator("#explore-tier-2")).to_have_value("area")
    expect(page.locator("#explore-tier-3")).to_have_value("")


def test_nothing_ends_the_groupings_there(page: Page, dashboard):
    open_explorer(page)
    page.locator("#explore-tier-2").select_option("")
    expect(page).to_have_url(re.compile(r"#explore=kind&"))
    expect(page.locator("#explore-tier-3")).to_have_value("")
    expect(box(page, "Change")).to_have_class(re.compile(r"\btm-leaf\b"))


@pytest.mark.parametrize("dim, name, n", [
    ("open", "Open", 9), ("assigned", "Unassigned", 4), ("ci", "No CI", 3), ("opened", "Last week", 5),
    ("year", "2026", 9), ("category", "Security > Certificates", 1), ("cis", "web1", 3), ("cis", "No CI", 3),
    ("family", "Problem #1: Recurring certificate failures", 3), ("family", "Not linked", 6),
])
def test_every_grouping(page: Page, dashboard, dim, name, n):
    open_explorer(page)
    choose(page, dim, colour="none")
    expect(box(page, name)).to_have_attribute("aria-label", f"{name}: {n} record{'s' * (n > 1)} - show list")


def test_colour_by_priority_colours_the_smallest_boxes(page: Page, dashboard):
    open_explorer(page)
    choose(page, "kind", colour="priority")
    expect(box(page, "Change › High")).to_have_class(re.compile(r"\bprio-4\b"))
    expect(box(page, "Change › Low")).to_have_class(re.compile(r"\bprio-2\b"))
    assert (box(page, "Change › High").evaluate("e => getComputedStyle(e).backgroundColor")
            != box(page, "Change › Low").evaluate("e => getComputedStyle(e).backgroundColor"))
    # Colour by nothing: no colour split, so a record type is a single box.
    page.locator("#explore-colour").select_option("none")
    expect(page.locator("#treemap a")).to_have_count(4)


def test_zoom_into_a_group_and_back_out(page: Page, dashboard):
    open_explorer(page)
    pick(page, "Change")
    page.get_by_role("button", name="Zoom in").click()
    expect(page.locator("#explore-crumbs")).to_have_text("All records › Change")
    expect(page.locator("#treemap a")).not_to_have_count(0)
    expect(box(page, "Incident")).to_have_count(0)
    expect(page.locator("#explore-count")).to_have_text("4 records (open only) - each opens in GLPI")
    expect(page.get_by_role("button", name="Zoom in")).to_be_hidden()
    page.locator("#explore-crumbs").get_by_role("link", name="All records").click()
    expect(box(page, "Incident")).to_be_visible()
    expect(page.locator("#explore-crumbs")).to_be_hidden()


def test_double_click_zooms_into_a_group(page: Page, dashboard):
    open_explorer(page)
    box(page, "Change").dblclick(position={"x": 4, "y": 4})
    expect(page.locator("#explore-crumbs")).to_have_text("All records › Change")


def test_a_shared_link_opens_the_explorer_at_that_view(page: Page, dashboard):
    page.goto("/#explore=area&colour=priority&closed=1&sel=Network")
    expect(page.get_by_role("tab", name="Record explorer")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#explore-title")).to_have_text("Network")
    expect(page.locator("#explore-count")).to_have_text("6 records - each opens in GLPI")
    expect(page.locator("#explore-closed")).to_be_checked()
    expect(page.locator("#explore-tier-1")).to_have_value("area")


def test_a_bad_link_falls_back_to_the_defaults(page: Page, dashboard, console_errors):
    page.goto("/#explore=nope,__proto__&colour=pink&sel=%E0%A4%A&zoom=Gone")
    expect(page.locator("#treemap a").first).to_be_visible()
    expect(page.locator("#explore-tier-1")).to_have_value("kind")
    expect(page.locator("#explore-title")).to_have_text("All records")
    expect(page.locator("#explore-crumbs")).to_be_hidden()
    assert console_errors == []


def test_back_goes_back_through_what_was_picked(page: Page, dashboard):
    open_explorer(page)
    pick(page, "Change")
    pick(page, "Incident")
    expect(page.locator("#explore-title")).to_have_text("Incident")
    page.go_back()
    expect(page.locator("#explore-title")).to_have_text("Change")
    page.go_back()
    expect(page.locator("#explore-title")).to_have_text("All records")


def test_leaving_the_tab_clears_the_explorer_from_the_address(page: Page, dashboard):
    open_explorer(page)
    page.get_by_role("tab", name="Summary").click()
    expect(page).not_to_have_url(re.compile("#explore"))


def test_boxes_work_from_the_keyboard_and_keep_focus(page: Page, dashboard):
    open_explorer(page)
    box(page, "Change").focus()
    expect(page.locator("#treemap-caption")).to_have_text(re.compile(r"^Change: 4 records, 44\.4% of 9$"))
    page.keyboard.press("Enter")
    expect(page.locator("#explore-title")).to_have_text("Change")
    expect(box(page, "Change")).to_be_focused()
    assert box(page, "Change").evaluate("e => getComputedStyle(e).outlineStyle") == "solid"


def test_the_groups_table_holds_the_same_counts(page: Page, dashboard):
    open_explorer(page)
    page.get_by_text("The same groups as a table").click()
    table = page.locator("#explore-table")
    expect(table.locator("tbody th").first).to_have_text("Change")
    labels = table.locator("tbody a").evaluate_all("as => as.map(a => a.getAttribute('aria-label'))")
    in_map = page.locator("#treemap a").evaluate_all("as => as.map(a => a.getAttribute('aria-label'))")
    assert sorted(labels) == sorted(in_map)
    table.get_by_role("link", name="Change › Medium: 2 records - show list").click()
    expect(page.locator("#explore-title")).to_have_text("Change › Medium")


def test_glpi_text_is_shown_as_text_never_html(page: Page, dashboard, console_errors):
    dashboard.data["Ticket"][2]["name"] = "T " + XSS
    dashboard.data["ITILCategory"][2]["completename"] = "Network " + XSS
    open_explorer(page)
    page.locator("#refresh").click()
    expect(page.locator("#treemap")).to_contain_text("Network " + XSS)
    labels = page.locator("#treemap a").evaluate_all("as => as.map(a => a.getAttribute('aria-label'))")
    assert f"Change › Medium › Network {XSS}: 1 record - show list" in labels
    pick(page, "Request")
    expect(page.locator("#explore-rows")).to_contain_text("T " + XSS)
    page.get_by_text("The same groups as a table").click()
    expect(page.locator("#explore-table")).to_contain_text("Network " + XSS)
    assert page.locator("main img, main script").count() == 0
    assert page.evaluate("window.__xss") is None


def test_a_refresh_redraws_with_the_new_records(page: Page, dashboard):
    open_explorer(page)
    dashboard.data["Problem"].append({**dashboard.data["Problem"][0], "id": 3, "name": "Another problem"})
    page.locator("#refresh").click()
    expect(box(page, "Problem")).to_have_attribute("aria-label", "Problem: 2 records - show list")


def test_explorer_failing_to_load_says_so_and_keeps_the_page(page: Page, dashboard):
    page.route("**/api/explorer", lambda route: route.fulfill(status=500, json={"error": "boom"}))
    page.goto("/")
    page.get_by_role("tab", name="Record explorer").click()
    expect(page.locator("#explore-error")).to_have_text("Could not load the records for the explorer: boom")
    expect(page.locator("#explore-error")).to_have_attribute("role", "alert")
    page.get_by_role("tab", name="Summary").click()
    expect(page.locator("#summary .tile").first).to_be_visible()


def test_a_later_failure_keeps_the_last_records(page: Page, dashboard):
    open_explorer(page)
    page.route("**/api/explorer", lambda route: route.fulfill(status=500, json={"error": "boom"}))
    dashboard.data["Problem"].append({**dashboard.data["Problem"][0], "id": 3})
    page.locator("#refresh").click()
    expect(page.locator("#explore-error")).to_contain_text("showing the last ones read")
    expect(box(page, "Problem")).to_have_attribute("aria-label", "Problem: 1 record - show list")


def test_records_are_fetched_only_while_the_explorer_shows(page: Page, dashboard):
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/explorer" in r.url else None)
    page.goto("/")
    expect(page.locator("#updated")).to_contain_text("Updated")
    page.wait_for_timeout(300)
    assert asked == []
    page.get_by_role("tab", name="Record explorer").click()
    expect(page.locator("#treemap a").first).to_be_visible()
    page.get_by_role("tab", name="Summary").click()
    page.get_by_role("tab", name="Record explorer").click()
    expect(page.locator("#treemap a").first).to_be_visible()
    assert len(asked) == 1                    # the same refresh isn't fetched twice


def _rgb(css):
    if css.startswith("color(srgb"):
        return [float(v) for v in css[len("color(srgb"):].strip(" )").split()[:3]]
    return [int(v) / 255 for v in re.findall(r"[\d.]+", css)[:3]]


def _lum(css):
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in _rgb(css)]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("colour", ["kind", "priority", "open"])
def test_box_labels_meet_wcag_aa(page: Page, dashboard, scheme, colour):
    page.emulate_media(color_scheme=scheme)
    open_explorer(page)
    page.locator("#explore-closed").check()
    choose(page, "kind", "area", colour=colour)
    pairs = page.locator("#treemap .tm-leaf, #treemap .tm-group > .tm-label").evaluate_all(
        "es => es.map(e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor])")
    assert len(pairs) >= 8
    for fg, bg in pairs:
        hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5, (fg, bg)


def test_a_record_with_two_cis_is_in_both_boxes_and_the_note_says_so(page: Page, dashboard):
    dashboard.data["Item_Ticket"].append({"id": 3, "itemtype": "Computer", "items_id": 2, "tickets_id": 1})
    open_explorer(page)
    page.locator("#refresh").click()
    expect(page.locator("#explore-note")).to_be_hidden()
    choose(page, "cis", colour="none")
    expect(page.locator("#explore-note")).to_be_visible()
    pick(page, "web1")
    assert "Incident #1" in shown_refs(page)
    pick(page, "db1")
    assert "Incident #1" in shown_refs(page)
    # Picking nothing lists each record once, however many boxes it's in.
    page.go_back()
    page.go_back()
    expect(page.locator("#explore-count")).to_have_text("9 records (open only) - each opens in GLPI")


def test_group_headers_are_solid_bands_not_the_group_colour(page: Page, dashboard):
    open_explorer(page)
    group = box(page, "Change")
    head = group.locator(".tm-label")
    assert head.evaluate("e => getComputedStyle(e).backgroundColor") != group.evaluate(
        "e => getComputedStyle(e).backgroundColor")


def test_long_titles_stay_on_one_line_with_the_whole_title_on_hover(page: Page, dashboard):
    long = "A very long title " * 12
    dashboard.data["Ticket"][0]["name"] = long
    open_explorer(page)
    page.locator("#refresh").click()
    link = page.locator("#explore-rows").get_by_role("link", name=long.strip())
    expect(link).to_have_attribute("title", long)
    cell = link.locator("xpath=..")
    assert cell.evaluate("e => e.scrollWidth > e.clientWidth")        # cut, not wrapped
    assert cell.evaluate("e => getComputedStyle(e).textOverflow") == "ellipsis"
    row_heights = page.locator("#explore-rows tbody tr").evaluate_all("rs => rs.map(r => r.offsetHeight)")
    assert max(row_heights) < 2 * min(row_heights)


@pytest.mark.parametrize("width, wide", [(1900, True), (1000, False)])
def test_only_the_explorer_grows_on_a_wide_window(page: Page, dashboard, width, wide):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/")
    expect(page.locator("#updated")).to_contain_text("Updated")
    summary = page.locator("#panel-summary").bounding_box()
    header = page.locator("header.top").bounding_box()
    tabs = page.locator(".tabs").bounding_box()
    open_explorer(page)
    explorer = page.locator("#panel-explorer").bounding_box()
    assert page.locator("header.top").bounding_box() == header
    assert page.locator(".tabs").bounding_box() == tabs
    if wide:
        assert summary["width"] == pytest.approx(1168, abs=1)
        assert explorer["width"] == pytest.approx(0.9 * width, abs=2)
        # Centred on the page, and inside the window: no sideways scroll.
        assert explorer["x"] + explorer["width"] / 2 == pytest.approx(summary["x"] + summary["width"] / 2, abs=2)
        assert page.evaluate("document.documentElement.scrollWidth") <= width
    else:
        assert explorer["width"] == pytest.approx(summary["width"], abs=1)


def test_a_failing_explorer_is_asked_again_only_at_the_next_poll(page: Page, dashboard):
    asked = []

    def fail(route):
        asked.append(1)
        route.fulfill(status=500, json={"error": "boom"})

    page.route("**/api/explorer", fail)
    page.clock.install()
    page.goto("/")
    expect(page.locator("#updated")).to_contain_text("Updated")
    page.get_by_role("tab", name="Record explorer").click()
    expect(page.locator("#explore-error")).to_be_visible()
    page.wait_for_timeout(500)
    assert len(asked) == 1
    page.clock.run_for(60_000)                 # the next poll
    expect(page.locator("#updated")).to_contain_text("Updated")
    page.wait_for_timeout(500)
    assert len(asked) == 2


@pytest.mark.parametrize("link, opened", [("#list=open-incidents", "#list-title"), ("#search=backup", "#list-search")])
def test_a_list_or_search_link_opens_when_the_explorer_was_the_last_tab(page: Page, dashboard, link, opened):
    open_explorer(page)
    page.goto("about:blank")
    page.goto("/" + link)
    expect(page.locator("dialog#list")).to_be_visible()
    expect(page.locator(opened)).to_be_visible()
    expect(page).to_have_url(re.compile(re.escape(link) + "$"))
    expect(page.get_by_role("tab", name="Record explorer")).to_have_attribute("aria-selected", "true")


@pytest.mark.parametrize("system, choice", [("light", "Dark"), ("dark", "Light")])
def test_box_labels_meet_wcag_aa_after_picking_a_theme(page: Page, dashboard, system, choice):
    """The box text is picked for the colours it was drawn on, so picking a theme draws the boxes again."""
    page.emulate_media(color_scheme=system)
    open_explorer(page)
    page.locator("#explore-closed").check()
    choose(page, "kind", "area", colour="priority")
    page.get_by_role("button", name=f"{choice} theme").click()
    pairs = page.locator("#treemap .tm-leaf, #treemap .tm-group > .tm-label").evaluate_all(
        "es => es.map(e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor])")
    assert len(pairs) >= 8
    for fg, bg in pairs:
        hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5, (fg, bg)
