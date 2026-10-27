"""Search as a user sees it: the box above the tabs, the results dialog, refining, closing and XSS safety."""
import re
import time

import pytest
from playwright.sync_api import Page, expect

from fake_glpi import PUBLIC_URL

XSS = '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>'


def open_page(page: Page, path="/"):
    page.goto(path)
    expect(page.locator("#updated")).to_contain_text("Updated")


def box(page: Page):
    """The search box above the tabs."""
    return page.locator("#search")


def dialog(page: Page):
    return page.locator("dialog#list")


def results(page: Page):
    return page.locator("#list-rows tr")


def refs_shown(page: Page):
    return page.locator("#list-rows .chip").all_inner_texts()


def search(page: Page, q):
    """Types a query into the search box, as a user would, and waits for its results."""
    box(page).fill("")
    box(page).press_sequentially(q)
    expect(dialog(page)).to_be_visible()
    expect(page.locator("#list-count")).not_to_have_text("Searching…")


def test_the_search_box_sits_in_the_header_beside_the_update_time(page: Page, dashboard):
    page.set_viewport_size({"width": 1280, "height": 800})
    open_page(page)
    expect(page.locator("header").get_by_label("Search records, projects and CIs")).to_be_visible()
    search_box, updated = box(page).bounding_box(), page.locator("#updated").bounding_box()
    title = page.locator("h1").bounding_box()
    assert search_box["x"] > title["x"] + title["width"] and search_box["x"] + search_box["width"] < updated["x"]
    assert abs((search_box["y"] + search_box["height"]) - (updated["y"] + updated["height"])) < 12   # one row
    tabs = page.get_by_role("tablist").bounding_box()
    assert search_box["y"] + search_box["height"] <= tabs["y"]


def test_both_search_boxes_can_be_cleared_with_an_x(page: Page, dashboard):
    open_page(page)
    expect(box(page)).to_have_attribute("type", "search")
    search(page, "db1")
    inner = page.locator("#list-search")
    expect(inner).to_have_attribute("type", "search")
    b = inner.bounding_box()
    page.mouse.click(b["x"] + b["width"] - 14, b["y"] + b["height"] / 2)     # the box's own clear button
    expect(inner).to_have_value("")
    expect(page.locator("#list-count")).to_have_text("Type at least 2 characters to search.")
    expect(dialog(page)).to_be_visible()


def test_typing_and_pausing_opens_the_results(page: Page, dashboard):
    open_page(page)
    box(page).press_sequentially("certificate")
    expect(dialog(page)).to_be_hidden()                  # nothing until the pause
    expect(dialog(page)).to_be_visible()
    expect(page.locator("#list-title")).to_have_text("Search")
    expect(page.locator("#list-count")).to_have_text("4 matches - each opens in GLPI")
    assert refs_shown(page) == ["Change #1", "Incident #1", "Problem #1", "Project #1"]
    expect(page).to_have_url(re.compile(r"#search=certificate$"))


def test_the_pause_is_about_half_a_second(page: Page, dashboard):
    open_page(page)
    box(page).fill("db1")
    started = time.monotonic()
    expect(dialog(page)).to_be_visible()
    assert time.monotonic() - started >= 0.4


def test_enter_searches_at_once(page: Page, dashboard):
    open_page(page)
    box(page).fill("backup")
    box(page).press("Enter")
    expect(dialog(page)).to_be_visible()
    assert refs_shown(page) == ["Incident #2"]


def test_the_results_have_their_own_box_holding_the_query(page: Page, dashboard):
    open_page(page)
    search(page, "db1")
    inner = dialog(page).get_by_label("Search records, projects and CIs")
    expect(inner).to_have_value("db1")
    expect(inner).to_be_focused()


def test_typing_on_refines_the_results_in_place(page: Page, dashboard):
    open_page(page)
    search(page, "certificate")
    page.keyboard.type(" renew")                         # focus is in the dialog's box
    expect(page.locator("#list-count")).to_have_text("1 match - each opens in GLPI")
    assert refs_shown(page) == ["Change #1"]
    expect(page).to_have_url(re.compile(r"#search=certificate%20renew$"))
    page.go_back()                                       # refining adds no history: Back closes it
    expect(dialog(page)).to_be_hidden()


def test_each_result_opens_in_glpi(page: Page, dashboard):
    open_page(page)
    search(page, "db1 slow")
    row = results(page).first
    for link in row.get_by_role("link").all():
        assert link.get_attribute("target") == "_blank" and link.get_attribute("rel") == "noopener"
    expect(row.get_by_role("link", name="db1 slow")).to_have_attribute(
        "href", PUBLIC_URL + "/front/ticket.form.php?id=2")


def test_closed_records_projects_and_cis_are_found(page: Page, dashboard):
    open_page(page)
    search(page, "outage")
    expect(page.locator("#list-count")).to_have_text("No matches.")
    dialog(page).get_by_label("Include closed").check()
    expect(results(page).first).to_contain_text("Closed")
    page.locator("#list-search").fill("SN-WEB")
    page.keyboard.press("Enter")
    expect(results(page).first.locator(".chip")).to_have_text("Computer #1")
    expect(results(page).first).to_contain_text("web1")


def test_a_description_match_shows_where_it_was_found(page: Page, dashboard):
    open_page(page)
    search(page, "nightly")
    snippet = results(page).first.locator("td.snippet")
    expect(snippet).to_have_text("Queries time out during the nightly backup job.")
    expect(snippet.locator("mark")).to_have_text("nightly")


def test_matching_words_in_titles_are_marked(page: Page, dashboard):
    open_page(page)
    search(page, "renew cert")
    expect(results(page).first.locator("mark")).to_have_text(["Renew", "cert"])


def test_no_matches_and_short_queries_say_so(page: Page, dashboard):
    open_page(page)
    search(page, "zzzz-nothing")
    expect(page.locator("#list-count")).to_have_text("No matches.")
    expect(results(page)).to_have_text(["None"])
    page.locator("#list-search").fill("z")
    page.keyboard.press("Enter")
    expect(page.locator("#list-count")).to_have_text("Type at least 2 characters to search.")


def test_one_character_in_the_top_box_opens_nothing(page: Page, dashboard):
    open_page(page)
    box(page).fill("d")
    box(page).press("Enter")
    page.wait_for_timeout(700)
    expect(dialog(page)).to_be_hidden()


@pytest.mark.parametrize("how", ["escape", "close", "backdrop"])
def test_closing_clears_the_hash_and_keeps_the_query(page: Page, dashboard, how):
    open_page(page)
    search(page, "db1")
    if how == "escape":
        page.keyboard.press("Escape")       # from the dialog's search box: it closes, not just clears
    elif how == "close":
        page.get_by_role("link", name="Close list").click()
    else:
        page.mouse.click(3, 3)
    expect(dialog(page)).to_be_hidden()
    expect(page).not_to_have_url(re.compile("#search="))
    expect(box(page)).to_have_value("db1")


def test_focus_returns_to_the_search_box(page: Page, dashboard):
    open_page(page)
    search(page, "db1")
    page.keyboard.press("Escape")
    expect(box(page)).to_be_focused()


def test_a_bookmarked_search_opens_on_load(page: Page, dashboard):
    open_page(page, "/#search=backup")
    expect(dialog(page)).to_be_visible()
    expect(page.locator("#list-count")).to_have_text("1 match - each opens in GLPI")
    expect(box(page)).to_have_value("backup")
    expect(dialog(page).get_by_label("Include closed")).not_to_be_checked()
    open_page(page, "/#search=backup&closed=1")
    expect(page.locator("#list-count")).to_have_text("2 matches - each opens in GLPI")
    expect(dialog(page).get_by_label("Include closed")).to_be_checked()


# --- Include closed ---------------------------------------------------------------------------------------------

def test_include_closed_is_off_by_default_beside_both_boxes(page: Page, dashboard):
    open_page(page)
    expect(page.locator("header").get_by_label("Include closed")).not_to_be_checked()
    search(page, "backup")
    expect(dialog(page).get_by_label("Include closed")).not_to_be_checked()
    assert refs_shown(page) == ["Incident #2"]


def test_ticking_include_closed_updates_the_results_at_once(page: Page, dashboard):
    open_page(page)
    search(page, "backup")
    dialog(page).get_by_label("Include closed").check()
    expect(page.locator("#list-count")).to_have_text("2 matches - each opens in GLPI")
    assert refs_shown(page) == ["Incident #2", "Incident #4"]
    expect(page).to_have_url(re.compile(r"#search=backup&closed=1$"))
    dialog(page).get_by_label("Include closed").press("Space")          # from the keyboard too
    expect(page.locator("#list-count")).to_have_text("1 match - each opens in GLPI")
    expect(page).to_have_url(re.compile(r"#search=backup$"))


def test_the_two_include_closed_boxes_agree(page: Page, dashboard):
    open_page(page)
    page.locator("header").get_by_label("Include closed").check()
    expect(dialog(page)).to_be_hidden()                                # ticking it alone opens nothing
    search(page, "outage")
    expect(dialog(page).get_by_label("Include closed")).to_be_checked()
    assert refs_shown(page) == ["Incident #4"]
    dialog(page).get_by_label("Include closed").uncheck()
    page.keyboard.press("Escape")
    expect(page.locator("header").get_by_label("Include closed")).not_to_be_checked()


# --- the data searched, and Refresh now -------------------------------------------------------------------------

def test_the_results_say_which_refresh_they_search(page: Page, dashboard):
    open_page(page)
    search(page, "db1")
    data = page.locator("#search-data")
    expect(data).to_be_visible()
    when = page.locator("#updated").inner_text().removeprefix("Updated ").split(" (")[0]
    expect(data).to_contain_text(f"Searching the data read from GLPI at {when}.")
    page.keyboard.press("Escape")
    page.get_by_role("link", name=re.compile(r"^Open incidents: \d+$")).click()
    expect(data).to_be_hidden()


def test_refresh_now_in_the_results_re_reads_glpi_and_searches_again(page: Page, dashboard):
    open_page(page)
    search(page, "db1 slow")
    assert refs_shown(page) == ["Incident #2"]
    dashboard.data["Ticket"][1]["name"] = "db1 slow again"
    dashboard.data["Change"][2]["name"] = "db1 slow fix"
    button = dialog(page).get_by_role("button", name="Refresh now")
    button.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#list-count")).to_have_text("2 matches - each opens in GLPI")
    expect(results(page).first).to_contain_text("db1 slow again")
    expect(button).to_be_enabled()
    expect(button).to_be_focused()
    expect(dialog(page)).to_be_visible()


def test_a_failed_refresh_in_the_results_says_so_there(page: Page, dashboard):
    open_page(page)
    search(page, "db1")
    dashboard.down = True
    dialog(page).get_by_role("button", name="Refresh now").click()
    expect(page.locator("#search-data")).to_contain_text("the last refresh failed")
    expect(results(page).first).to_contain_text("db1")       # the last data is still searched


def test_a_malformed_search_hash_is_ignored(page: Page, dashboard, console_errors):
    open_page(page, "/#search=%E0%A4%A")
    expect(dialog(page)).to_be_hidden()
    assert console_errors == []


def test_a_list_after_a_search_has_no_search_box(page: Page, dashboard):
    open_page(page)
    search(page, "db1")
    page.keyboard.press("Escape")
    page.get_by_role("link", name=re.compile(r"^Open incidents: \d+$")).click()
    expect(page.locator("#list-title")).to_have_text("Open incidents")
    expect(page.locator("#list-search")).to_be_hidden()


def test_results_sort_and_page_like_other_lists(page: Page, dashboard):
    d = dashboard.data
    for i in range(12):
        d["Ticket"].append({**d["Ticket"][1], "id": 100 + i, "name": f"Search filler {i:02}"})
    open_page(page)
    page.locator("#refresh").click()
    expect(page.locator("#refresh")).to_be_enabled()
    search(page, "filler")
    expect(results(page)).to_have_count(10)
    expect(page.locator("#list-count")).to_have_text("12 matches - each opens in GLPI")
    page.get_by_role("button", name="Show all 12").click()
    expect(results(page)).to_have_count(12)
    page.get_by_role("button", name="Title").click()
    assert page.locator("#list-rows tr td:nth-child(2)").all_inner_texts()[0] == "Search filler 00"


def test_each_result_fits_on_one_line_on_a_wide_screen(page: Page, dashboard):
    page.set_viewport_size({"width": 1600, "height": 900})
    open_page(page)
    search(page, "certificate")
    line = results(page).first.locator(".chip").bounding_box()["height"]
    for row in results(page).all():
        assert row.locator("td").first.bounding_box()["height"] < 2.5 * line + 16


def test_a_failed_search_says_so_in_the_dialog(page: Page, dashboard):
    open_page(page)
    page.route("**/api/search*", lambda route: route.fulfill(status=503, json={"error": "first refresh still running"}))
    search(page, "db1")
    expect(page.locator("#list-count")).to_have_text("Search failed: first refresh still running")


def test_the_search_box_has_a_visible_focus_outline(page: Page, dashboard):
    open_page(page)
    box(page).focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    assert box(page).evaluate("e => getComputedStyle(e).outlineStyle") == "solid"


def test_search_text_is_shown_as_text_never_html(page: Page, dashboard, console_errors):
    d = dashboard.data
    d["Ticket"][1]["name"] = "db1 " + XSS
    # Encoded twice, the payload survives tag stripping and reaches the snippet as text.
    d["Ticket"][1]["content"] = "payload " + XSS.replace("<", "&amp;lt;").replace(">", "&amp;gt;")
    d["Computer"][1]["comment"] = "db1 " + XSS
    open_page(page)
    page.locator("#refresh").click()
    expect(page.locator("#refresh")).to_be_enabled()
    search(page, "db1 onerror")
    expect(page.locator("#list-rows")).to_contain_text("db1 " + XSS)
    page.keyboard.press("Escape")
    search(page, "payload")
    expect(page.locator("#list-rows td.snippet")).to_have_text("payload " + XSS)
    assert page.locator("dialog img, dialog script, main img, main script").count() == 0
    assert page.evaluate("window.__xss") is None
    assert console_errors == []


def _rgb(css):
    if css.startswith("color(srgb"):
        return [float(v) for v in css[len("color(srgb"):].strip(" )").split()[:3]]
    return [int(v) / 255 for v in re.findall(r"[\d.]+", css)[:3]]


def _contrast(fg, bg):
    def lum(c):
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in _rgb(c)]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg, bg):
    """A colour with alpha ("rgba(...)" or "color(srgb r g b / a)") over an opaque one."""
    nums = [float(v) for v in re.findall(r"[\d.]+", fg)]
    if fg.startswith("color(srgb"):
        rgb, a = nums[:3], nums[3] if len(nums) > 3 else 1.0
    else:
        rgb, a = [v / 255 for v in nums[:3]], nums[3] if len(nums) > 3 else 1.0
    base = _rgb(bg)
    out = [a * c + (1 - a) * b for c, b in zip(rgb, base)]
    return "color(srgb " + " ".join(f"{v:.4f}" for v in out) + ")"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_marks_and_ci_chips_meet_wcag_aa(page: Page, dashboard, scheme):
    page.emulate_media(color_scheme=scheme)
    open_page(page)
    search(page, "web1")
    surface = page.locator("#list-rows").evaluate("e => getComputedStyle(e.closest('table')).backgroundColor")
    mark = page.locator("#list-rows mark").first
    style = mark.evaluate("e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]")
    assert _contrast(style[0], _blend(style[1], surface)) >= 4.5
    chip = page.locator("#list-rows .chip", has_text="Computer #1")
    colours = chip.evaluate("e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]")
    assert _contrast(colours[0], colours[1]) >= 4.5


# --- review fixes -------------------------------------------------------------------------------------------------

def test_a_slow_search_never_draws_over_a_list_opened_after_it(page: Page, dashboard):
    open_page(page)
    held = []
    page.route("**/api/search*", lambda route: held.append(route))
    box(page).fill("db1")
    box(page).press("Enter")
    expect(dialog(page)).to_be_visible()
    expect(page.locator("#list-count")).to_have_text("Searching…")
    page.keyboard.press("Escape")
    page.get_by_role("link", name=re.compile(r"^Open incidents: \d+$")).click()
    expect(page.locator("#list-title")).to_have_text("Open incidents")
    held[0].continue_()
    page.wait_for_timeout(500)
    expect(page.locator("#list-count")).to_have_text("3 records - each opens in GLPI")
    expect(dialog(page).locator("thead th").last).to_have_text(re.compile("^CIs"))


def test_a_failed_search_clears_the_last_results(page: Page, dashboard):
    open_page(page)
    search(page, "backup")
    assert refs_shown(page) == ["Incident #2"]
    page.route("**/api/search*", lambda route: route.fulfill(status=503, json={"error": "down"}))
    page.locator("#list-search").fill("certificate")
    page.keyboard.press("Enter")
    expect(page.locator("#list-count")).to_have_text("Search failed: down")
    expect(results(page)).to_have_text(["None"])


def test_a_long_search_link_is_cut_to_fit(page: Page, dashboard):
    open_page(page, "/#search=" + "a" * 120)
    expect(page.locator("#list-count")).to_have_text("No matches.")
    expect(page.locator("#list-search")).to_have_value("a" * 100)


def test_a_word_inside_a_longer_one_still_marks_the_longer(page: Page, dashboard):
    open_page(page, "/#search=db%20db1")
    expect(page.locator("#list-count")).to_contain_text("match")
    expect(results(page).first.get_by_role("link", name="db1 slow").locator("mark")).to_have_text(["db1"])


def test_the_results_stay_put_as_they_grow_and_shrink(page: Page, dashboard):
    page.set_viewport_size({"width": 1280, "height": 800})
    open_page(page)
    search(page, "certificate")
    top = dialog(page).bounding_box()["y"]
    assert top == 48
    page.locator("#list-search").fill("")
    expect(page.locator("#list-count")).to_have_text("Type at least 2 characters to search.")
    assert dialog(page).bounding_box()["y"] == top
    page.keyboard.press("Escape")
    page.get_by_role("link", name=re.compile(r"^Open incidents: \d+$")).click()
    expect(page.locator("#list-title")).to_have_text("Open incidents")
    assert dialog(page).bounding_box()["y"] > top          # ordinary lists stay centred
