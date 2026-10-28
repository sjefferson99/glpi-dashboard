"""The page as a user sees it: tiles, drill-down lists, refresh, errors, keyboard use and XSS safety."""
import colorsys
import re

import httpx
import pytest
from playwright.sync_api import Page, expect

import main
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


def open_all_risks(page: Page):
    """Opens the full ranked list from the risk table's All / All number."""
    show_tab(page, "Risk analysis")
    page.locator("#risks tfoot td").last.get_by_role("link").click()


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
    show_tab(page, "Risk analysis")
    expect(page.locator("#risks .seg")).to_have_count(5)            # High, Medium; then the 3 non-empty cells
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
    open_all_risks(page)
    expect(page.locator("#list-title")).to_have_text("All open problems and changes, by risk score")
    rows = page.locator("#list-rows tr")
    expect(rows.locator("td:first-child")).to_have_text(["1", "2", "3"])
    expect(rows.nth(0)).to_contain_text("Change #1")
    expect(rows.nth(0).locator("td").nth(5)).to_have_text("75")
    expect(rows.nth(1).locator(".why")).to_contain_text("1 open incident(s) +5")


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
    for name in ("Summary", "In flight", "Recurring changes", "CMDB", "Risk analysis"):
        show_tab(page, name)
        # Chart segments have no visible number; test_risk_segments_drill_into_their_records covers them.
        links = page.locator("main [role=tabpanel]:not([hidden]) a[href^='#list=']:not(svg a)")
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
    expect(page.locator("#refresh")).to_have_accessible_name("Refresh now")
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


# --- site settings --------------------------------------------------------------------------------------------

def test_title_is_configurable_and_shown_as_text(page: Page, dashboard, console_errors, monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_TITLE", "Ops board " + XSS)
    open_page(page)
    expect(page).to_have_title("Ops board " + XSS)
    expect(page.get_by_role("heading", level=1)).to_have_text("Ops board " + XSS)
    assert page.locator("header script, header img:not(.logo)").count() == 0
    assert page.evaluate("window.__xss") is None
    assert console_errors == []


def test_locale_sets_the_date_format(page: Page, dashboard, console_errors, monkeypatch):
    open_page(page)
    expect(page.locator("#updated")).to_have_text(re.compile(r"^Updated \d{1,2} [A-Z][a-z]{2} \d{4}"))   # en-GB
    monkeypatch.setattr(main, "LOCALE", "en-US")
    open_page(page)
    expect(page.locator("html")).to_have_attribute("lang", "en-US")
    expect(page.locator("#updated")).to_have_text(re.compile(r"^Updated [A-Z][a-z]{2} \d{1,2}, \d{4}"))
    assert console_errors == []


def test_unreadable_locale_falls_back_to_en_gb(page: Page, dashboard, console_errors, monkeypatch):
    monkeypatch.setattr(main, "LOCALE", "not a locale!")        # _locale() stops this; the page copes anyway
    open_page(page)
    expect(page.locator("#updated")).to_have_text(re.compile(r"^Updated \d{1,2} [A-Z][a-z]{2} \d{4}"))
    assert console_errors == []


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
    open_all_risks(page)
    expect(page.locator("#list-rows")).to_contain_text("C " + XSS)
    expect(page.locator("#list-rows")).to_contain_text("Security " + XSS)
    page.keyboard.press("Escape")
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
    expect(tabs).to_have_text(["Summary", "In flight", "Recurring changes", "CMDB", "Risk analysis",
                                   "Record explorer"])
    expect(tabs.first).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_have_count(1)     # hidden panels aren't exposed
    expect(page.get_by_role("tabpanel")).to_contain_text("Health at a glance")
    expect(page.get_by_role("tabpanel")).to_contain_text("Record quality")


def test_clicking_a_tab_shows_only_its_panel(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    expect(page.get_by_role("tab", name="CMDB")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tab", name="Summary")).to_have_attribute("aria-selected", "false")
    expect(page.locator("#panel-cmdb")).to_be_visible()
    expect(page.locator("#panel-summary")).to_be_hidden()


def test_tabs_work_from_the_keyboard(page: Page, dashboard):
    open_page(page)
    page.get_by_role("tab", name="Summary").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name="In flight")).to_be_focused()
    expect(page.locator("#panel-flight")).to_be_visible()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")                       # wraps round to the last tab
    expect(page.get_by_role("tab", name="Record explorer")).to_be_focused()
    page.keyboard.press("Home")
    expect(page.get_by_role("tab", name="Summary")).to_be_focused()
    page.keyboard.press("End")
    expect(page.locator("#panel-explorer")).to_be_visible()
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
    show_tab(page, "CMDB")
    page.locator("#cis tbody tr").first.get_by_role("link", name="1 - show list").first.click()
    expect(page.locator("#list-title")).to_have_text("web1: open incidents")
    page.keyboard.press("Escape")
    expect_closed(page)
    expect(page.locator("#panel-cmdb")).to_be_visible()


def test_a_saved_tab_that_no_longer_exists_falls_back_to_summary(page: Page, dashboard):
    open_page(page)
    page.evaluate("localStorage.setItem('tab', 'tab-gone')")      # e.g. a tab a later version removed
    open_page(page)
    expect(page.get_by_role("tab", name="Summary")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#panel-summary")).to_be_visible()


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
    open_all_risks(page)
    dialog(page).get_by_role("button", name="Score", exact=True).click()
    expect(page.locator("#list-rows tr td:nth-child(6)")).to_have_text(["55", "68", "75"])


def test_sort_survives_a_refresh(page: Page, dashboard):
    open_page(page)
    show_tab(page, "CMDB")
    page.locator("#cis").get_by_role("button", name="CI", exact=True).click()
    page.locator("#refresh").click()
    expect(page.locator("#refresh")).to_have_accessible_name("Refresh now")
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


# --- risks chart ------------------------------------------------------------------------------------------------

def segment(page: Page, name):
    return page.locator("#risks svg").get_by_role("link", name=f"{name} - show list", exact=True)


def point_in_segment(page: Page, name):
    """A point well inside a segment, as a user would aim: a ring segment's bounding-box centre is often not on it."""
    page.locator("#risks svg").scroll_into_view_if_needed()
    x, y = segment(page, name).locator("path").evaluate("""(path) => {
      const svg = path.ownerSVGElement, box = path.getBBox(), pt = svg.createSVGPoint();
      const inside = (x, y) => [[0, 0], [5, 0], [-5, 0], [0, 5], [0, -5]]
        .every(([dx, dy]) => { pt.x = x + dx; pt.y = y + dy; return path.isPointInFill(pt); });
      for (let y = box.y; y <= box.y + box.height; y += 2) {
        for (let x = box.x; x <= box.x + box.width; x += 2) {
          if (!inside(x, y)) continue;
          pt.x = x; pt.y = y;
          const p = pt.matrixTransform(svg.getScreenCTM());
          return [p.x, p.y];
        }
      }
      throw new Error('no point inside the segment');
    }""")
    return x, y


def click_segment(page: Page, name):
    page.mouse.click(*point_in_segment(page, name))


def open_risks(page: Page):
    open_page(page)
    show_tab(page, "Risk analysis")


def test_risks_have_their_own_tab(page: Page, dashboard):
    open_risks(page)
    expect(page.locator("#panel-risks h2")).to_have_text(["Risks"])
    expect(page.locator("#panel-summary")).to_be_hidden()
    expect(page.locator("#panel-risks").get_by_role("link", name=re.compile("ranked"))).to_have_count(0)


def test_risk_chart_rings_are_priority_then_record_type(page: Page, dashboard):
    open_risks(page)
    svg = page.locator("#risks svg")
    expect(svg).to_have_attribute("aria-label", "Risks by priority, then record type")
    expect(svg.get_by_role("link")).to_have_count(5)
    for name in ("High priority: 1", "Medium priority: 2", "Changes at High priority: 1",
                 "Problems at Medium priority: 1", "Changes at Medium priority: 1"):
        expect(segment(page, name)).to_have_count(1)
    expect(page.locator("#risks .centre-n")).to_have_text("3")
    expect(page.locator("#risks .centre-label")).to_have_text("open risks")


def test_risk_segments_drill_into_their_records(page: Page, dashboard):
    open_risks(page)
    click_segment(page, "Medium priority: 2")
    expect(page).to_have_url(re.compile(r"#list=risks-p3$"))
    expect(page.locator("#list-title")).to_have_text("Risks at Medium priority")
    rows = page.locator("#list-rows tr")
    # Highest score first, each with its overall rank.
    expect(rows.locator("td:first-child")).to_have_text(["2", "3"])
    expect(rows.nth(0)).to_contain_text("Problem #1")
    expect(rows.nth(1)).to_contain_text("Change #2")
    page.keyboard.press("Escape")
    expect_closed(page)
    click_segment(page, "Problems at Medium priority: 1")
    expect(page.locator("#list-title")).to_have_text("Risks: problems at Medium priority")
    expect(page.locator("#list-rows tr")).to_have_count(1)


def test_every_risk_segment_count_matches_its_rows(page: Page, dashboard):
    open_risks(page)
    for inner in ("Priority", "Record type"):
        page.locator(".toggle").get_by_role("button", name=inner).click()
        links = page.locator("#risks svg a")
        expect(links).to_have_count(5)
        for i in range(links.count()):
            label = links.nth(i).get_attribute("aria-label")
            expected = int(re.search(r": (\d+) - show list$", label)[1])
            click_segment(page, label.removesuffix(" - show list"))
            expect(dialog(page)).to_be_visible()
            expect(page.locator("#list-count")).to_have_text(re.compile(rf"^{expected} "))
            expect(page.locator("#list-rows tr")).to_have_count(expected)
            page.keyboard.press("Escape")
            expect_closed(page)


def test_record_type_toggle_swaps_the_rings_and_is_remembered(page: Page, dashboard):
    open_risks(page)
    toggle = page.get_by_role("group", name="Inner ring")
    expect(toggle.get_by_role("button", name="Priority")).to_have_attribute("aria-pressed", "true")
    toggle.get_by_role("button", name="Record type").click()
    expect(toggle.get_by_role("button", name="Record type")).to_have_attribute("aria-pressed", "true")
    expect(toggle.get_by_role("button", name="Priority")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#risks svg")).to_have_attribute("aria-label", "Risks by record type, then priority")
    expect(segment(page, "Problems: 1")).to_have_count(1)
    expect(segment(page, "Changes: 2")).to_have_count(1)
    # The outer ring is now coloured by priority.
    expect(segment(page, "Changes at High priority: 1").locator("path")).to_have_class(re.compile(r"\bprio-4\b"))
    open_risks(page)
    expect(toggle.get_by_role("button", name="Record type")).to_have_attribute("aria-pressed", "true")
    expect(segment(page, "Changes: 2")).to_have_count(1)


def _fill(locator):
    return locator.evaluate("e => getComputedStyle(e).fill")


def test_colours_toggle_switches_priority_colours_and_is_remembered(page: Page, dashboard):
    open_risks(page)
    colours = page.get_by_role("group", name="Priority colours")
    expect(colours.get_by_role("button", name="Traffic light")).to_have_attribute("aria-pressed", "true")
    high = segment(page, "High priority: 1").locator("path")
    swatch = page.locator("#risks tbody th .swatch").first
    traffic = _fill(high)
    assert swatch.evaluate("e => getComputedStyle(e).backgroundColor") == traffic
    colours.get_by_role("button", name="Heat").click()
    expect(colours.get_by_role("button", name="Heat")).to_have_attribute("aria-pressed", "true")
    expect(colours.get_by_role("button", name="Traffic light")).to_have_attribute("aria-pressed", "false")
    heat = _fill(high)
    assert heat != traffic
    assert swatch.evaluate("e => getComputedStyle(e).backgroundColor") == heat     # the table follows
    # Record types keep their own colours either way.
    assert _fill(segment(page, "Problems at Medium priority: 1").locator("path")) == page.locator(
        "#risks thead .swatch.kind-problem").evaluate("e => getComputedStyle(e).backgroundColor")
    open_risks(page)
    expect(colours.get_by_role("button", name="Heat")).to_have_attribute("aria-pressed", "true")
    assert _fill(segment(page, "High priority: 1").locator("path")) == heat


def test_hovering_a_segment_shows_its_count_and_name(page: Page, dashboard):
    open_risks(page)
    caption = page.locator("#risks .risk-caption")
    expect(caption).to_have_text("Pick a segment to list its records.")
    page.mouse.move(*point_in_segment(page, "Medium priority: 2"))
    expect(page.locator("#risks .centre-n")).to_have_text("2")
    expect(caption).to_have_text("Medium priority: 2 of 3")
    page.mouse.move(0, 0)
    expect(page.locator("#risks .centre-n")).to_have_text("3")


def test_risk_segments_work_from_the_keyboard(page: Page, dashboard):
    open_risks(page)
    page.get_by_role("button", name="Heat").focus()
    page.keyboard.press("Tab")                               # the first segment
    first = page.locator("#risks svg a").first
    expect(first).to_be_focused()
    expect(page.locator("#risks .risk-caption")).to_have_text("High priority: 1 of 3")
    assert first.locator("path").evaluate("e => getComputedStyle(e).strokeWidth") == "3px"
    page.keyboard.press("Enter")
    expect(page.locator("#list-title")).to_have_text("Risks at High priority")


def test_risk_table_holds_the_same_counts_as_the_chart(page: Page, dashboard):
    open_risks(page)
    table = page.locator("#risks table")
    expect(table.locator("thead th")).to_have_text(["Priority", "Problems", "Changes", "All"])
    expect(table.locator("tbody tr")).to_have_text([re.compile(r"High\s*0\s*1\s*1"), re.compile(r"Medium\s*1\s*1\s*2")])
    expect(table.locator("tfoot tr")).to_have_text(re.compile(r"All\s*1\s*2\s*3"))
    expect(table.locator("tbody tr").first.locator(".zero")).to_have_text("0")   # no list behind an empty cell
    table.get_by_role("link", name="2 - show list").first.click()
    expect(page.locator("#list-title")).to_have_text("Risks at Medium priority")


def test_chart_and_table_are_the_same_height(page: Page, dashboard):
    page.set_viewport_size({"width": 1100, "height": 900})
    open_risks(page)
    chart = page.locator("#risks .risk-chart").bounding_box()
    table = page.locator("#risks table").bounding_box()
    assert abs(chart["y"] - table["y"]) < 1
    assert abs(chart["height"] - table["height"]) < 2


def test_risk_chart_redraws_only_when_the_data_changes(page: Page, dashboard, base_url):
    page.clock.install()
    open_risks(page)
    focused = segment(page, "Medium priority: 2")
    focused.focus()
    # New data elsewhere, picked up by the 60 s poll: the page redraws, but the chart (and its focus) stays.
    dashboard.data["Ticket"].append({**dashboard.data["Ticket"][1], "id": 50})
    assert httpx.post(base_url + "/api/refresh", timeout=10).status_code == 200
    page.clock.run_for(61_000)
    expect(page.locator("#summary .value").first).to_have_text("4")     # Open incidents, on the hidden Summary tab
    expect(focused).to_be_focused()
    dashboard.data["Problem"][0]["priority"] = 5
    page.locator("#refresh").click()
    expect(segment(page, "Very high priority: 1")).to_have_count(1)
    expect(segment(page, "Medium priority: 1")).to_have_count(1)


def test_no_open_risks(page: Page, dashboard):
    dashboard.data["Problem"] = []
    dashboard.data["Change"] = []
    open_risks(page)
    page.locator("#refresh").click()
    expect(page.locator("#risks")).to_have_text("No open risks.")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_heat_gets_deeper_with_priority_and_both_styles_have_six_colours(page: Page, dashboard, scheme):
    page.emulate_media(color_scheme=scheme)
    open_risks(page)
    read = """(wrap) => [1, 2, 3, 4, 5, 6].map((p) => {
      const box = document.createElement('div');
      if (wrap) box.className = wrap;
      const e = document.createElement('span');
      e.className = 'swatch prio-' + p;
      box.append(e);
      document.body.append(box);
      const c = getComputedStyle(e).backgroundColor;
      box.remove();
      return c.match(/\\d+/g).slice(0, 3).map(Number);
    })"""
    traffic, heat = page.evaluate(read, ""), page.evaluate(read, "colours-heat")
    lum = [colorsys.rgb_to_hls(*(v / 255 for v in rgb))[1] for rgb in heat]
    # Higher priority stands out more from the surface: darker in light mode, lighter in dark.
    assert lum == sorted(lum, reverse=scheme == "light")
    assert len(set(map(tuple, heat))) == 6 and len(set(map(tuple, traffic))) == 6
    # Traffic light: Very low is green, Major is red.
    r, g, _ = traffic[0]
    assert g > r
    r, g, _ = traffic[5]
    assert r > g


# --- header ---------------------------------------------------------------------------------------------------

def test_header_puts_updated_and_refresh_right_on_the_titles_baseline(page: Page, dashboard):
    page.set_viewport_size({"width": 1100, "height": 800})
    open_page(page)
    title = page.locator("h1").bounding_box()
    meta = page.locator(".top .meta").bounding_box()
    assert meta["x"] > title["x"] + title["width"]                   # to the right of the title
    top = page.locator(".top").bounding_box()
    assert abs((meta["x"] + meta["width"]) - (top["x"] + top["width"] - 16)) < 2   # right-aligned, inside the padding
    assert abs((meta["y"] + meta["height"]) - (title["y"] + title["height"])) < 2     # bottoms line up
    assert float(page.locator(".top .meta").evaluate("e => parseFloat(getComputedStyle(e).fontSize)")) < 14


def test_refresh_is_an_icon_button_with_a_name(page: Page, dashboard):
    open_page(page)
    btn = page.get_by_role("button", name="Refresh now")
    expect(btn).to_have_attribute("title", "Refresh now")
    expect(btn).to_have_text(re.compile(r"^\s*$"))                     # no visible words, just the icon
    expect(btn.locator("svg")).to_have_attribute("aria-hidden", "true")


def test_refresh_says_it_is_busy_and_spins_while_it_runs(page: Page, dashboard):
    open_page(page)
    release = []
    page.route("**/api/refresh", lambda route: release.append(route))
    page.get_by_role("button", name="Refresh now").click()
    busy = page.locator("#refresh")
    expect(busy).to_have_accessible_name("Refreshing…")
    expect(busy).to_be_disabled()
    assert busy.locator("svg").evaluate("e => getComputedStyle(e).animationName") == "spin"
    release[0].continue_()
    expect(busy).to_have_accessible_name("Refresh now")
    expect(busy).to_be_enabled()


def test_refresh_icon_holds_still_for_reduced_motion(page: Page, dashboard):
    page.emulate_media(reduced_motion="reduce")
    open_page(page)
    page.route("**/api/refresh", lambda route: None)                 # never answers: stays busy
    page.locator("#refresh").click()
    expect(page.locator("#refresh")).to_be_disabled()
    assert page.locator("#refresh svg").evaluate("e => getComputedStyle(e).animationName") == "none"
