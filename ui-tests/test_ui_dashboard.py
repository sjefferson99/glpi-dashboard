"""The page as a user sees it: tiles, drill-down lists, refresh, errors, keyboard use and XSS safety."""
import re

from playwright.sync_api import Page, expect

from fake_glpi import PUBLIC_URL


def open_page(page: Page, path="/"):
    page.goto(path)
    expect(page.locator("#updated")).to_contain_text("Updated")


def tile(page: Page, title):
    return page.locator("a.tile", has=page.locator(".label", has_text=re.compile(f"^{re.escape(title)}$")))


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
    expect(tile(page, "Changes awaiting approval").locator(".value")).to_have_text("1")
    expect(page.locator("#areas .card")).to_have_count(4)
    expect(page.locator("#risks tbody tr")).to_have_count(3)
    expect(page.locator("#projects tbody tr")).to_have_count(1)
    expect(page.locator("#recurring tbody tr")).to_have_count(2)
    expect(page.locator("#error")).to_be_hidden()
    expect(page.locator("#glpi-link")).to_have_attribute("href", PUBLIC_URL + "/")
    # Nothing blocked by the CSP, no script errors.
    assert console_errors == []


def test_zero_tiles_are_marked(page: Page, dashboard):
    open_page(page)
    expect(tile(page, "Changes at Testing")).to_have_class(re.compile(r"\bzero\b"))
    expect(tile(page, "Open incidents")).not_to_have_class(re.compile(r"\bzero\b"))


def test_risks_are_ranked_with_reasons(page: Page, dashboard):
    open_page(page)
    rows = page.locator("#risks tbody tr")
    expect(rows.nth(0)).to_contain_text("Change #1")
    expect(rows.nth(0).locator("td").nth(4)).to_have_text("75")
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
    page.locator("#cis-box summary").click()
    expect(page.locator("#cis-count")).to_have_text("2")
    web1 = page.locator("#cis tbody tr").first
    expect(web1).to_contain_text("web1")
    expect(web1.locator(".net")).to_have_text("internet")


def test_glpi_links_open_in_a_new_tab(page: Page, dashboard):
    open_page(page)
    link = page.locator("#projects tbody a").first
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
    page.locator("#cis-box summary").click()
    links = page.locator("main a[href^='#list=']")
    n = links.count()
    assert n > 20
    for i in range(n):
        link = links.nth(i)
        if not link.is_visible():
            continue
        expected = int(re.search(r"\d+", link.inner_text())[0])
        link.click()
        expect(dialog(page)).to_be_visible()   # rows from the previous list stay in the DOM until it opens
        expect(page.locator("#list-rows tr")).to_have_count(max(expected, 1))   # an empty list shows "None"
        if expected == 0:
            expect(page.locator("#list-rows")).to_have_text("None")
        page.keyboard.press("Escape")
        expect_closed(page)


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
    expect(page.locator("#risks")).to_contain_text("C " + XSS)
    page.locator("#cis-box summary").click()
    tile(page, "Open incidents").click()
    expect(page.locator("#list-rows")).to_contain_text("T " + XSS)
    assert page.locator("main img, dialog img, main script, dialog script").count() == 0
    assert page.evaluate("window.__xss") is None


def test_only_http_links_are_followed(page: Page, dashboard):
    open_page(page)
    # safeUrl() guards every GLPI link; check it directly, since the backend never builds such a URL itself.
    for bad in ("javascript:alert(1)", "data:text/html,<script>1</script>", "vbscript:x", "not a url"):
        assert page.evaluate("u => safeUrl(u)", bad) == "#"
    assert page.evaluate("u => safeUrl(u)", "https://glpi.example.test/x") == "https://glpi.example.test/x"
