"""The page as a user sees it: tiles, drill-down lists, refresh, errors, keyboard use and XSS safety."""
import colorsys
import re

import pytest
from playwright.sync_api import Page, expect

from fake_glpi import PUBLIC_URL

PAGE = 10   # rows a table shows before "Show more"


def open_page(page: Page, path="/"):
    page.goto(path)
    expect(page.locator("#updated")).to_contain_text("Updated")


def tile(page: Page, title):
    """A stat tile by its full title, which names the link (the tile may show a shorter label)."""
    return page.get_by_role("link", name=re.compile(rf"^{re.escape(title)}: \d+$"))


def show_tab(page: Page, name):
    page.get_by_role("tab", name=name, exact=True).click()


def dialog(page: Page):
    return page.locator("dialog#list")


def expect_closed(page: Page):
    # The dialog's close event clears the hash a moment after it hides.
    expect(dialog(page)).to_be_hidden()
    expect(page).not_to_have_url(re.compile("#list="))


# --- rendering ------------------------------------------------------------------------------------------------

def test_page_renders_every_section(page: Page, dashboard, console_errors):
    open_page(page)
    expect(page).to_have_title("Network state")
    expect(tile(page, "Open incidents").locator(".value")).to_have_text("3")
    expect(tile(page, "Open changes (not yet Applied)").locator(".value")).to_have_text("3")
    expect(tile(page, "Open incidents, problems and changes without a CI").locator(".value")).to_have_text("2")
    expect(page.locator("#quality .tile")).to_have_count(7)
    expect(page.locator("#areas .card")).to_have_count(4)
    show_tab(page, "In flight")
    expect(tile(page, "Changes awaiting approval").locator(".value")).to_have_text("1")
    expect(tile(page, "Projects").locator(".value")).to_have_text("1")
    show_tab(page, "Recurring changes")
    expect(page.locator("#recurring-cards .card")).to_have_count(2)
    expect(page.locator("#recurring tbody tr")).to_have_count(2)
    show_tab(page, "CMDB")
    expect(page.locator("#cis tbody tr")).to_have_count(2)
    show_tab(page, "Risks")
    expect(page.locator("#risks tbody tr")).to_have_count(3)
    expect(page.locator("#error")).to_be_hidden()
    expect(page.locator("#glpi-link")).to_have_attribute("href", PUBLIC_URL + "/")
    # Nothing blocked by the CSP, no script errors.
    assert console_errors == []


def test_zero_tiles_are_marked(page: Page, dashboard):
    open_page(page)
    zero = tile(page, "Open problems linked to no incident and no change")
    expect(zero).to_have_class(re.compile(r"\bzero\b"))
    expect(tile(page, "Open incidents")).not_to_have_class(re.compile(r"\bzero\b"))
    # Dimmed: no fill, a dashed border, and the number in the secondary text colour.
    assert zero.evaluate("e => getComputedStyle(e).borderStyle") == "dashed"
    assert tile(page, "Open incidents").evaluate("e => getComputedStyle(e).borderStyle") == "solid"
    show_tab(page, "In flight")
    expect(tile(page, "Changes at Testing")).to_have_class(re.compile(r"\bzero\b"))


def test_risks_are_ranked_with_reasons(page: Page, dashboard):
    open_page(page)
    show_tab(page, "Risks")
    rows = page.locator("#risks tbody tr")
    expect(rows.nth(0)).to_contain_text("Change #1")
    expect(rows.nth(0).locator("td").nth(5)).to_have_text("75")
    expect(rows.nth(1).locator(".why")).to_contain_text("1 open incident(s) +5")
    expect(page.locator("#risks-all span")).to_have_text("3")


def test_rag_is_shown_as_icon_and_word_not_colour_alone(page: Page, dashboard):
    open_page(page)
    security = page.locator("#areas .card", has=page.locator("h3", has_text="Security"))
    expect(security.locator(".rag")).to_have_text("■ Act")
    expect(security.locator(".rag-icon")).to_have_attribute("aria-hidden", "true")
    hosting = page.locator("#areas .card", has=page.locator("h3", has_text="Hosting"))
    expect(hosting.locator(".rag")).to_have_text("● OK")


def test_cis_table_flags_internet_facing(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    expect(page.locator("#cis-count")).to_have_text("2")
    web1 = page.locator("#cis tbody tr").first
    expect(web1).to_contain_text("web1")
    expect(web1.locator(".net")).to_have_text("internet")


def test_glpi_links_open_in_a_new_tab(page: Page, dashboard):
    open_page(page)
    show_tab(page, "In flight")
    tile(page, "Projects").click()
    link = page.locator("#list-rows a").first
    expect(link).to_have_attribute("href", f"{PUBLIC_URL}/front/project.form.php?id=1")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener")


# --- drill-down lists -----------------------------------------------------------------------------------------

def test_clicking_a_number_lists_exactly_those_records(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(dialog(page)).to_be_visible()
    expect(page).to_have_url(re.compile(r"#list=open-incidents$"))
    expect(page.locator("#list-title")).to_have_text("Open incidents")
    expect(page.locator("#list-count")).to_have_text("3 records - each opens in GLPI")
    rows = page.locator("#list-rows tr")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text("Incident #1")
    expect(rows.nth(0).locator("a").first).to_have_attribute("href", f"{PUBLIC_URL}/front/ticket.form.php?id=1")


def test_every_list_link_count_matches_its_rows(page: Page, dashboard):
    open_page(page)
    checked = 0
    for name in ("Summary", "In flight", "Recurring changes", "CMDB", "Risks"):
        show_tab(page, name)
        links = page.locator("main [role=tabpanel]:not([hidden]) a[href^='#list=']")
        for i in range(links.count()):
            link = links.nth(i)
            expected = int(re.search(r"\d+", link.inner_text())[0])
            link.click()
            expect(dialog(page)).to_be_visible()   # rows from the previous list stay in the DOM until it opens
            expect(page.locator("#list-count")).to_have_text(re.compile(rf"^{expected} "))
            expect(page.locator("#list-rows tr")).to_have_count(min(max(expected, 1), PAGE))   # empty shows "None"
            if expected == 0:
                expect(page.locator("#list-rows")).to_have_text("None")
            page.keyboard.press("Escape")
            expect_closed(page)
            checked += 1
    assert checked > 40


def test_closing_clears_the_hash(page: Page, dashboard):
    open_page(page)
    tile(page, "Open problems").click()
    expect(dialog(page)).to_be_visible()
    page.get_by_role("link", name="Close list").click()
    expect_closed(page)


def test_escape_closes_the_list(page: Page, dashboard):
    open_page(page)
    tile(page, "Open requests").click()
    expect(dialog(page)).to_be_visible()
    page.keyboard.press("Escape")
    expect_closed(page)


def test_a_bookmarked_list_opens_on_load(page: Page, dashboard):
    open_page(page, "/#list=awaiting-approval")
    expect(dialog(page)).to_be_visible()
    expect(page.locator("#list-title")).to_have_text("Changes awaiting approval")
    expect(page.locator("#list-rows tr")).to_have_count(1)


def test_back_button_reopens_and_closes_lists(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(dialog(page)).to_be_visible()
    page.evaluate("location.hash = '#list=open-problems'")
    expect(page.locator("#list-title")).to_have_text("Open problems")
    page.go_back()
    expect(page.locator("#list-title")).to_have_text("Open incidents")


def test_unknown_or_malformed_list_keys_are_ignored(page: Page, dashboard, console_errors):
    for frag in ("#list=nope", "#list=%E0%A4%A", "#list=__proto__", "#list=toString"):
        open_page(page, "/" + frag)
        expect(dialog(page)).to_be_hidden()
    assert console_errors == []


# --- keyboard -------------------------------------------------------------------------------------------------

def test_lists_open_from_the_keyboard(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").focus()
    page.keyboard.press("Enter")
    expect(dialog(page)).to_be_visible()
    page.keyboard.press("Escape")
    expect_closed(page)


def test_refresh_button_works_from_the_keyboard(page: Page, dashboard):
    open_page(page)
    reads = dashboard.count("Ticket")
    page.locator("#refresh").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#refresh")).to_have_text("Refresh now")
    expect(page.locator("#refresh")).to_be_enabled()
    assert dashboard.count("Ticket") == reads + 1


def test_focus_is_visible(page: Page, dashboard):
    open_page(page)
    page.keyboard.press("Tab")
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert outline == "solid"


# --- refresh and errors ---------------------------------------------------------------------------------------

def test_refresh_now_shows_new_data(page: Page, dashboard):
    open_page(page)
    dashboard.data["Ticket"].append({**dashboard.data["Ticket"][1], "id": 50, "name": "New incident"})
    page.locator("#refresh").click()
    expect(tile(page, "Open incidents").locator(".value")).to_have_text("4")


def test_glpi_down_keeps_the_data_and_shows_a_banner(page: Page, dashboard):
    open_page(page)
    dashboard.down = True
    page.locator("#refresh").click()
    banner = page.locator("#error")
    expect(banner).to_be_visible()
    expect(banner).to_have_attribute("role", "alert")
    expect(banner).to_contain_text("Last refresh from GLPI failed")
    expect(banner).to_contain_text("ConnectError")
    expect(tile(page, "Open incidents").locator(".value")).to_have_text("3")
    expect(page.locator("#refresh")).to_be_enabled()


def test_banner_clears_when_glpi_is_back(page: Page, dashboard):
    open_page(page)
    dashboard.down = True
    page.locator("#refresh").click()
    expect(page.locator("#error")).to_be_visible()
    dashboard.down = False
    page.locator("#refresh").click()
    expect(page.locator("#error")).to_be_hidden()


def test_backend_unreachable_shows_a_banner(page: Page, dashboard):
    open_page(page)
    page.route("**/api/refresh", lambda route: route.abort())
    page.locator("#refresh").click()
    expect(page.locator("#error")).to_contain_text("Could not load the dashboard data")
    expect(page.locator("#refresh")).to_be_enabled()


# --- XSS ------------------------------------------------------------------------------------------------------

XSS = '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>'


def test_glpi_text_is_shown_as_text_never_html(page: Page, dashboard, console_errors):
    d = dashboard.data
    d["Ticket"][0]["name"] = "T " + XSS
    d["Change"][0]["name"] = "C " + XSS
    d["Computer"][0]["name"] = "web1 " + XSS
    d["ITILCategory"][0]["completename"] = "Security " + XSS
    d["Project"][0]["name"] = "P " + XSS
    d["RecurrentChange"][0]["name"] = "R " + XSS
    d["ProjectState"][0]["name"] = "S " + XSS
    open_page(page)
    page.locator("#refresh").click()
    expect(page.locator("#areas")).to_contain_text("Security " + XSS)
    tile(page, "Open incidents").click()
    expect(page.locator("#list-rows")).to_contain_text("T " + XSS)
    page.keyboard.press("Escape")
    show_tab(page, "In flight")
    tile(page, "Projects").click()
    expect(page.locator("#list-rows")).to_contain_text("S " + XSS)
    page.keyboard.press("Escape")
    show_tab(page, "Recurring changes")
    expect(page.locator("#recurring-cards")).to_contain_text("R " + XSS)
    expect(page.locator("#recurring")).to_contain_text("R " + XSS)
    show_tab(page, "CMDB")
    expect(page.locator("#cis")).to_contain_text("web1 " + XSS)
    show_tab(page, "Risks")
    expect(page.locator("#risks")).to_contain_text("C " + XSS)
    assert page.locator("main img, dialog img, main script, dialog script").count() == 0
    assert page.evaluate("window.__xss") is None


def test_only_http_links_are_followed(page: Page, dashboard):
    open_page(page)
    # safeUrl() guards every GLPI link; check it directly, since the backend never builds such a URL itself.
    for bad in ("javascript:alert(1)", "data:text/html,<script>1</script>", "vbscript:x", "not a url"):
        assert page.evaluate("u => safeUrl(u)", bad) == "#"
    assert page.evaluate("u => safeUrl(u)", "https://glpi.example.test/x") == "https://glpi.example.test/x"


# --- layout and widgets ---------------------------------------------------------------------------------------

def test_tabs_in_order_with_summary_first(page: Page, dashboard):
    open_page(page)
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_text(["Summary", "In flight", "Recurring changes", "CMDB", "Risks"])
    expect(tabs.first).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_have_count(1)     # hidden panels aren't exposed
    expect(page.get_by_role("tabpanel")).to_contain_text("Health at a glance")
    expect(page.get_by_role("tabpanel")).to_contain_text("Record quality")


def test_clicking_a_tab_shows_only_its_panel(page: Page, dashboard):
    open_page(page)
    show_tab(page, "Risks")
    expect(page.get_by_role("tab", name="Risks")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tab", name="Summary")).to_have_attribute("aria-selected", "false")
    expect(page.locator("#panel-risks")).to_be_visible()
    expect(page.locator("#panel-summary")).to_be_hidden()


def test_tabs_work_from_the_keyboard(page: Page, dashboard):
    open_page(page)
    page.get_by_role("tab", name="Summary").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name="In flight")).to_be_focused()
    expect(page.locator("#panel-flight")).to_be_visible()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")                       # wraps round to the last tab
    expect(page.get_by_role("tab", name="Risks")).to_be_focused()
    page.keyboard.press("Home")
    expect(page.get_by_role("tab", name="Summary")).to_be_focused()
    page.keyboard.press("End")
    expect(page.locator("#panel-risks")).to_be_visible()
    # Only the selected tab is in the Tab order.
    expect(page.locator("[role=tab][tabindex='0']")).to_have_count(1)


def test_the_chosen_tab_is_remembered(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    open_page(page)
    expect(page.get_by_role("tab", name="CMDB")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#panel-cmdb")).to_be_visible()


def test_a_list_opens_from_any_tab(page: Page, dashboard):
    open_page(page)
    show_tab(page, "Risks")
    page.locator("#risks-all").click()
    expect(page.locator("#list-title")).to_have_text("All open problems and changes, by risk score")
    page.keyboard.press("Escape")
    expect_closed(page)
    expect(page.locator("#panel-risks")).to_be_visible()


def test_record_quality_tiles(page: Page, dashboard):
    open_page(page)
    expect(page.locator("#quality .label")).to_have_text([
        "No category", "No CI", "Unassigned", "Stale (30 d)", "Orphan problems", "No approval asked",
        "Plan incomplete"])
    tile(page, "Open changes with an empty plan field").click()
    expect(page.locator("#list-title")).to_have_text("Open changes with an empty plan field")
    expect(page.locator("#list-rows tr")).to_have_count(1)
    expect(page.locator("#list-rows")).to_contain_text("Change #2")


def test_quality_tooltip_shows_the_full_rule_after_half_a_second(page: Page, dashboard):
    open_page(page)
    no_ci = tile(page, "Open incidents, problems and changes without a CI")
    tip = page.get_by_role("tooltip", include_hidden=True).filter(has_text="Requests are left out")
    expect(no_ci).to_have_accessible_description(re.compile("Requests are left out"))
    expect(tip).to_be_hidden()
    no_ci.hover()
    page.wait_for_timeout(250)
    expect(tip).to_be_hidden(timeout=1)                    # not yet: the delay is 0.5 s
    expect(tip).to_be_visible(timeout=1500)
    page.mouse.move(1, 1)
    expect(tip).to_be_hidden(timeout=500)                  # hides as soon as the pointer leaves


def test_quality_tooltip_shows_on_keyboard_focus_and_escape_hides_it(page: Page, dashboard):
    open_page(page)
    stale = tile(page, "Open records not updated in 30 days")
    tip = page.locator("#tip-stale")
    stale.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")                             # keyboard focus, so :focus-visible applies
    expect(tip).to_be_visible(timeout=1500)
    expect(tip).to_have_text("Open records with no update in the last 30 days.")
    page.keyboard.press("Escape")
    expect(tip).to_be_hidden(timeout=500)
    expect(stale).to_be_focused()                          # Escape only dismissed the tooltip


def test_summary_tiles_have_no_tooltip(page: Page, dashboard):
    open_page(page)
    expect(page.locator("#summary .tooltip")).to_have_count(0)


def test_in_flight_shows_every_record_kind_by_status(page: Page, dashboard):
    open_page(page)
    show_tab(page, "In flight")
    groups = page.locator("#flight .flight-group h3")
    expect(groups).to_have_text(["Incidents", "Requests", "Problems", "Changes", "Projects"])
    pending = tile(page, "Incidents: Pending")
    expect(pending.locator(".label")).to_have_text("Pending")    # the group heading says which kind
    pending.click()
    expect(page.locator("#list-title")).to_have_text("Incidents: Pending")
    expect(page.locator("#list-rows tr")).to_have_count(1)
    expect(page.locator("#list-rows")).to_contain_text("Incident #5")


def test_recurring_change_widget_lists_its_open_changes(page: Page, dashboard):
    open_page(page)
    show_tab(page, "Recurring changes")
    card = page.locator("#recurring-cards .card", has_text="Monthly patching")
    expect(card).to_contain_text("Next created 2026-11-01")
    expect(card.locator("h3 a")).to_have_attribute("href", f"{PUBLIC_URL}/front/recurrentchange.form.php?id=1")
    card.get_by_role("link", name="1 - show list").click()
    expect(page.locator("#list-title")).to_have_text("Monthly patching: open changes")
    expect(page.locator("#list-rows")).to_contain_text("Change #4")


def test_recurring_tab_without_active_recurring_changes(page: Page, dashboard):
    dashboard.data["RecurrentChange"] = []
    open_page(page)
    page.locator("#refresh").click()
    show_tab(page, "Recurring changes")
    expect(page.locator("#recurring-cards .card")).to_have_count(0)
    expect(page.locator("#recurring tbody")).to_have_text("None")


def test_projects_widget_drills_into_its_records_and_back(page: Page, dashboard):
    open_page(page)
    show_tab(page, "In flight")
    tile(page, "Projects").click()
    expect(page.locator("#list-title")).to_have_text("Projects")
    expect(page.locator("#list-count")).to_have_text("1 project - each opens in GLPI")
    row = page.locator("#list-rows tr").first
    expect(row).to_contain_text("Certificate automation")
    expect(row).to_contain_text("40%")
    row.get_by_role("link", name="3 - show list").click()
    expect(page.locator("#list-title")).to_have_text("Certificate automation: all linked records")
    expect(page.locator("#list-rows tr")).to_have_count(3)
    page.go_back()
    expect(page.locator("#list-title")).to_have_text("Projects")


def test_recurring_schedule_table(page: Page, dashboard):
    open_page(page)
    show_tab(page, "Recurring changes")
    first = page.locator("#recurring tbody tr").first
    expect(first.locator("td")).to_have_text(["Monthly patching", "1MONTH", "2026-11-01", "2026-11-03", "1"])


def test_list_shows_opened_and_updated_dates(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    headers = page.locator("#list thead th")
    names = ["Record", "Title", "Status", "Priority", "Opened", "Updated", "Age", "CIs"]
    expect(headers).to_have_text([re.compile(f"^{n}") for n in names])   # then the sort icon
    first = page.locator("#list-rows tr").first.locator("td")
    expect(first.nth(4)).to_have_text("2026-10-17")
    expect(first.nth(5)).to_have_text("2026-10-22")


# --- sorting --------------------------------------------------------------------------------------------------

def refs_shown(page: Page):
    return page.locator("#list-rows tr td:first-child")


def test_clicking_a_header_sorts_the_list_and_again_reverses_it(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(refs_shown(page)).to_have_text(["Incident #1", "Incident #5", "Incident #2"])    # priority, then age
    age = dialog(page).get_by_role("button", name="Age", exact=True)
    age.click()
    expect(page.locator("#list th[aria-sort='ascending']")).to_have_text("Age▲")
    expect(refs_shown(page)).to_have_text(["Incident #5", "Incident #2", "Incident #1"])    # 2, 3, 10 days
    age.click()
    expect(page.locator("#list th[aria-sort='descending']")).to_have_text("Age▼")
    expect(refs_shown(page)).to_have_text(["Incident #1", "Incident #2", "Incident #5"])
    expect(page.locator("#list th[aria-sort]")).to_have_count(1)


def test_sorting_works_from_the_keyboard_and_keeps_focus(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    title = dialog(page).get_by_role("button", name="Title", exact=True)
    title.focus()
    page.keyboard.press("Enter")
    # "Certificate expired on web1", "db1 slow", "Uncategorised blip"
    expect(refs_shown(page)).to_have_text(["Incident #1", "Incident #2", "Incident #5"])
    expect(title).to_be_focused()


def test_page_tables_sort_too(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    cis = page.locator("#cis tbody tr td:first-child")
    expect(cis).to_have_text(["web1internet", "db1"])
    page.locator("#cis").get_by_role("button", name="CI", exact=True).click()
    expect(cis).to_have_text(["db1", "web1internet"])
    show_tab(page, "Risks")
    page.locator("#risks").get_by_role("button", name="Score", exact=True).click()
    expect(page.locator("#risks tbody tr td:nth-child(6)")).to_have_text(["55", "68", "75"])


def test_sort_survives_a_refresh(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    page.locator("#cis").get_by_role("button", name="CI", exact=True).click()
    page.locator("#refresh").click()
    expect(page.locator("#refresh")).to_have_text("Refresh now")
    expect(page.locator("#cis tbody tr td:first-child")).to_have_text(["db1", "web1internet"])


# --- show more ------------------------------------------------------------------------------------------------

def add_incidents(page: Page, dashboard, n):
    """Adds `n` Low incidents opened earlier in the year, and refreshes the page."""
    base = dashboard.data["Ticket"][1]
    for i in range(n):
        dashboard.data["Ticket"].append({**base, "id": 100 + i, "name": f"Extra {i}",
                                         "date": f"2026-0{1 + i % 9}-1{i % 10} 00:00:00"})
    open_page(page)
    page.locator("#refresh").click()
    expect(tile(page, "Open incidents").locator(".value")).to_have_text(str(3 + n))


def test_long_lists_show_ten_then_more(page: Page, dashboard):
    add_incidents(page, dashboard, 13)
    tile(page, "Open incidents").click()
    expect(page.locator("#list-count")).to_have_text("16 records - each opens in GLPI")
    expect(page.locator("#list-rows tr")).to_have_count(PAGE)
    expect(page.locator("#list tfoot")).to_contain_text("Showing 10 of 16")
    dialog(page).get_by_role("button", name="Show 6 more", exact=True).click()
    expect(page.locator("#list-rows tr")).to_have_count(16)
    expect(page.locator("#list tfoot button")).to_have_text(["Show less"])   # nothing more to show
    # With nothing left to show, focus moves to the first new row.
    expect(page.locator("#list-rows tr").nth(PAGE).locator("a").first).to_be_focused()


def test_show_less_goes_back_to_ten(page: Page, dashboard):
    add_incidents(page, dashboard, 13)
    tile(page, "Open incidents").click()
    expect(dialog(page).get_by_role("button", name="Show less", exact=True)).to_have_count(0)   # not yet expanded
    dialog(page).get_by_role("button", name="Show all 16", exact=True).click()
    dialog(page).get_by_role("button", name="Show less", exact=True).click()
    expect(page.locator("#list-rows tr")).to_have_count(PAGE)
    expect(page.locator("#list tfoot")).to_contain_text("Showing 10 of 16")
    expect(page.locator("#list tfoot button")).to_have_text(["Show 6 more", "Show all 16"])
    expect(dialog(page).get_by_role("button", name="Show 6 more", exact=True)).to_be_focused()


def test_show_less_from_the_keyboard_on_a_page_table(page: Page, dashboard):
    # 13 more CIs with an open incident each, so the hosts and stacks table runs to 15.
    for i in range(13):
        dashboard.data["Computer"].append({"id": 10 + i, "name": f"host{i:02}"})
        dashboard.data["Item_Ticket"].append({"id": 10 + i, "itemtype": "Computer", "items_id": 10 + i,
                                              "tickets_id": 2})
    open_page(page)
    page.locator("#refresh").click()
    show_tab(page, "CMDB")
    expect(page.locator("#cis-count")).to_have_text("15")
    page.locator("#cis").get_by_role("button", name="Show 5 more", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#cis tbody tr")).to_have_count(15)
    page.locator("#cis").get_by_role("button", name="Show less", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#cis tbody tr")).to_have_count(PAGE)


def test_show_more_steps_by_ten_and_show_all_shows_the_rest(page: Page, dashboard):
    add_incidents(page, dashboard, 22)
    tile(page, "Open incidents").click()
    dialog(page).get_by_role("button", name="Show 10 more", exact=True).click()
    expect(page.locator("#list-rows tr")).to_have_count(20)
    expect(dialog(page).get_by_role("button", name="Show 5 more", exact=True)).to_be_focused()
    dialog(page).get_by_role("button", name="Show all 25", exact=True).click()
    expect(page.locator("#list-rows tr")).to_have_count(25)


def test_sorting_covers_the_hidden_rows_too(page: Page, dashboard):
    add_incidents(page, dashboard, 13)
    tile(page, "Open incidents").click()
    expect(refs_shown(page)).to_have_count(PAGE)
    expect(refs_shown(page)).not_to_contain_text(["Incident #2"])    # the newest Low incident sorts last
    dialog(page).get_by_role("button", name="Record", exact=True).click()
    expect(page.locator("#list-rows tr td:first-child")).to_have_text(
        ["Incident #1", "Incident #2", "Incident #5"] + [f"Incident #{100 + i}" for i in range(7)])


def test_reopening_a_list_starts_short_and_unsorted(page: Page, dashboard):
    add_incidents(page, dashboard, 13)
    tile(page, "Open incidents").click()
    dialog(page).get_by_role("button", name="Age", exact=True).click()
    dialog(page).get_by_role("button", name="Show 6 more", exact=True).click()
    page.keyboard.press("Escape")
    expect_closed(page)
    tile(page, "Open incidents").click()
    expect(page.locator("#list-rows tr")).to_have_count(PAGE)
    expect(page.locator("#list th[aria-sort]")).to_have_count(0)


# --- closing by the backdrop ----------------------------------------------------------------------------------

def test_clicking_the_backdrop_closes_the_list(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(dialog(page)).to_be_visible()
    page.mouse.click(3, 3)
    expect_closed(page)


def test_dragging_a_selection_out_of_the_list_keeps_it_open(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(dialog(page)).to_be_visible()
    status = page.locator("#list-rows tr").first.locator("td").nth(2)     # plain text, not a link
    box = status.bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(3, 3, steps=10)                       # release over the backdrop
    page.mouse.up()
    assert page.evaluate("getSelection().toString().length") > 0
    expect(dialog(page)).to_be_visible()
    expect(page).to_have_url(re.compile(r"#list=open-incidents$"))


def test_pressing_on_the_backdrop_and_releasing_inside_keeps_it_open(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(dialog(page)).to_be_visible()
    box = dialog(page).bounding_box()
    page.mouse.move(3, 3)
    page.mouse.down()
    page.mouse.move(box["x"] + 4, box["y"] + 4, steps=5)
    page.mouse.up()
    expect(dialog(page)).to_be_visible()


def test_clicking_inside_the_list_keeps_it_open(page: Page, dashboard):
    open_page(page)
    tile(page, "Open incidents").click()
    expect(dialog(page)).to_be_visible()
    box = dialog(page).bounding_box()
    page.mouse.click(box["x"] + 4, box["y"] + box["height"] - 4)    # the dialog's own padding
    page.locator("#list-count").click()
    expect(dialog(page)).to_be_visible()


# --- kind colours ---------------------------------------------------------------------------------------------

def _rgb(css):
    """Parses a computed colour, "rgb(r, g, b)" or "color(srgb r g b)", into 0-1 floats."""
    if css.startswith("color(srgb"):
        return [float(v) for v in css[len("color(srgb"):].strip(" )").split()[:3]]
    return [int(v) / 255 for v in re.findall(r"[\d.]+", css)[:3]]


def _contrast(fg, bg):
    def lum(c):
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in _rgb(c)]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _style(locator, prop):
    return locator.evaluate(f"e => getComputedStyle(e).{prop}")


def test_each_kind_has_its_own_colour_used_consistently(page: Page, dashboard):
    open_page(page)
    colour = {k: _style(tile(page, t).locator(".value"), "color") for k, t in (
        ("incident", "Open incidents"), ("request", "Open requests"), ("problem", "Open problems"),
        ("change", "Open changes (not yet Applied)"))}
    assert len(set(colour.values())) == 4
    # The same red on the incident tile's edge, a Security incident count, and an incident's reference chip.
    assert _style(tile(page, "Open incidents"), "borderLeftColor") == colour["incident"]
    security = page.locator("#areas .card", has=page.locator("h3", has_text="Security"))
    assert _style(security.locator(".count").first, "color") == colour["incident"]
    assert _style(security.locator(".count").nth(1), "color") == colour["problem"]
    tile(page, "Open incidents").click()
    assert _style(page.locator("#list-rows .chip").first, "color") == colour["incident"]
    page.keyboard.press("Escape")
    show_tab(page, "In flight")
    expect(page.locator(".flight-group.kind-change h3")).to_have_text("Changes")
    assert _style(tile(page, "Changes awaiting approval").locator(".value"), "color") == colour["change"]
    show_tab(page, "CMDB")
    web1 = page.locator("#cis tbody tr").first
    assert _style(web1.locator(".count").nth(1), "color") == colour["problem"]


def _hue(css):
    return colorsys.rgb_to_hls(*_rgb(css))[0] * 360


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_issue_red_and_problem_orange_are_far_apart(page: Page, dashboard, scheme):
    page.emulate_media(color_scheme=scheme)
    open_page(page)
    red = _hue(_style(tile(page, "High priority or above, open").locator(".value"), "color"))
    orange = _hue(_style(tile(page, "Open problems").locator(".value"), "color"))
    gap = min(abs(red - orange), 360 - abs(red - orange))
    assert gap >= 40


def test_incidents_are_blue_and_issue_tiles_red(page: Page, dashboard):
    open_page(page)
    incident = _rgb(_style(tile(page, "Open incidents").locator(".value"), "color"))
    assert incident[2] > incident[0]                       # more blue than red
    for t in ("High priority or above, open", "Open records without a category",
              "Open incidents, problems and changes without a CI", "Open records with no one assigned",
              "Open records not updated in 30 days"):
        r, g, b = _rgb(_style(tile(page, t).locator(".value"), "color"))
        assert r > g and r > b, t
    # A record-quality tile about one kind keeps that kind's colour.
    assert (_style(tile(page, "Open changes with an empty plan field"), "borderLeftColor")
            == _style(tile(page, "Open changes (not yet Applied)"), "borderLeftColor"))


def test_tiles_are_tinted_by_kind_but_zero_tiles_are_not(page: Page, dashboard):
    open_page(page)
    incidents = _style(tile(page, "Open incidents"), "backgroundColor")
    changes = _style(tile(page, "Open changes (not yet Applied)"), "backgroundColor")
    plain = _style(page.locator("#areas .card").first, "backgroundColor")    # an untinted surface
    assert len({incidents, changes, plain}) == 3
    zero = tile(page, "Open problems linked to no incident and no change")
    assert _style(zero, "backgroundColor") == "rgba(0, 0, 0, 0)"


def test_zero_counts_are_plain_not_coloured(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    db1 = page.locator("#cis tbody tr").nth(1)
    zero = db1.locator(".count").nth(1)                     # db1 has no open problems
    expect(zero).to_have_text("0")
    expect(zero).to_have_class(re.compile(r"\bzero\b"))
    assert _style(zero, "color") != _style(page.locator("#cis tbody tr").first.locator(".count").nth(1), "color")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_kind_colours_meet_wcag_aa(page: Page, dashboard, scheme):
    page.emulate_media(color_scheme=scheme)
    open_page(page)
    checked = 0
    for t in ("Open incidents", "Open requests", "Open problems", "Open changes (not yet Applied)",
              "High priority or above, open"):
        value, label = tile(page, t).locator(".value"), tile(page, t).locator(".label")
        assert _contrast(_style(value, "color"), _style(tile(page, t), "backgroundColor")) >= 4.5, t
        assert _contrast(_style(label, "color"), _style(tile(page, t), "backgroundColor")) >= 4.5, t
        tile(page, t).click()
        expect(page.locator("#list-title")).to_have_text(t)
        for i in range(page.locator("#list-rows .chip").count()):
            chip = page.locator("#list-rows .chip").nth(i)
            assert _contrast(_style(chip, "color"), _style(chip, "backgroundColor")) >= 4.5, (t, i)
            checked += 1
        page.keyboard.press("Escape")
        expect_closed(page)
    assert checked >= 8
