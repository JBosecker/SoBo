"""Browser tests of the guest page (Playwright + Chromium) against the real guest API (plan 9)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Browser, Page, expect, sync_playwright

from .guest_harness import Harness, create_harness, serve

pytestmark = pytest.mark.browser

# Collect Content Security Policy violations (runs before the page scripts).
CSP_RECORDER = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__csp.push(e.violatedDirective + ' ' + e.blockedURI);
});
"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        try:
            instance = p.chromium.launch()
        except Exception as err:  # browser not installed
            pytest.skip(f"Chromium not available: {err}")
        yield instance
        instance.close()


@pytest.fixture
def harness() -> Iterator[tuple[Harness, str]]:
    h = create_harness()
    with serve(h) as url:
        yield h, url


def open_page(browser: Browser, url: str, locale: str = "en-US") -> Page:
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, locale=locale
    )
    context.add_init_script(CSP_RECORDER)
    # The cover CDN is unreachable in tests → do not even send the requests.
    context.route("https://**/*", lambda route: route.abort())
    page = context.new_page()
    page.goto(url)
    return page


def join(page: Page, name: str) -> None:
    page.fill("#join-name", name)
    page.click("#join-form button[type=submit]")
    expect(page.locator("#view-main")).to_be_visible()


def guest_call(h: Harness, **payload: Any) -> dict[str, Any]:
    status, body = h.run(h.service.handle(json.dumps(payload).encode()))
    assert status == 200, body
    return body


def other_guest_suggests(h: Harness, name: str, query: str) -> None:
    session = guest_call(h, action="join", nickname=name)["session"]
    hit = guest_call(h, action="search", session=session, q=query)["results"][0]
    guest_call(h, action="suggest", session=session, result=hit["id"])


def test_join_search_suggest_and_live_update(
    browser: Browser, harness: tuple[Harness, str]
) -> None:
    h, url = harness
    page = open_page(browser, url)
    join(page, "Mia")
    expect(page.locator("#me-line")).to_contain_text("Mia, you have 5 votes left")

    page.fill("#search", "comet")
    page.locator("#results-list li", has_text="Slow Comet").locator("button").click()
    expect(page.locator("#toast")).to_contain_text("Suggested")

    # Another guest requests something → it appears without reloading (long polling).
    other_guest_suggests(h, "Tom", "lemonade")
    other_guest_suggests(h, "Ida", "velvet")
    strip = page.locator("#queue-list li", has_text="Velvet Engine")
    expect(strip).to_be_visible(timeout=8000)

    strip.locator("button").click()
    expect(strip.locator(".vote.on")).to_be_visible()
    expect(strip.locator(".count")).to_have_text("2")
    assert page.evaluate("window.__csp") == []


def test_own_suggestion_is_marked(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    other_guest_suggests(h, "Tom", "neon")  # plays right away
    page = open_page(browser, url)
    join(page, "Mia")
    page.fill("#search", "copper")
    page.locator("#results-list li", has_text="Copper Sky").locator("button").click()
    page.fill("#search", "salt")
    page.locator("#results-list li", has_text="Salt & Static").locator("button").click()
    mine = page.locator("#queue-list li.mine")
    expect(mine.first).to_contain_text("Your request")


def test_xss_in_nickname_is_rendered_as_text(
    browser: Browser, harness: tuple[Harness, str]
) -> None:
    _, url = harness
    page = open_page(browser, url)
    join(page, "<img src=x onerror=alert(1)>")
    expect(page.locator("#me-line")).to_contain_text("<img src=x")
    assert page.locator("#me-line img").count() == 0


def test_inactive_jukebox(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    h.run(h.jukebox.set_active(False, "test"))
    page = open_page(browser, url)
    page.fill("#join-name", "Mia")
    page.click("text=Join in")
    expect(page.locator("#view-off")).to_be_visible()


def test_switching_off_and_on_reaches_waiting_page(
    browser: Browser, harness: tuple[Harness, str]
) -> None:
    h, url = harness
    page = open_page(browser, url)
    join(page, "Mia")
    h.run(h.jukebox.set_active(False, "test"))
    expect(page.locator("#view-off")).to_be_visible(timeout=8000)
    h.run(h.jukebox.set_active(True, "test"))
    expect(page.locator("#view-main")).to_be_visible(timeout=8000)


def test_rotation_sends_guest_back_to_join(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_page(browser, url)
    join(page, "Mia")
    assert page.evaluate("localStorage.getItem('sobo.session')")
    h.run(h.jukebox.rotate_sessions("test"))
    h.service.reset()  # ends open long polls like a real rotation
    expect(page.locator("#view-join")).to_be_visible(timeout=8000)
    assert page.evaluate("localStorage.getItem('sobo.session')") is None


def test_session_survives_reload(browser: Browser, harness: tuple[Harness, str]) -> None:
    _, url = harness
    page = open_page(browser, url)
    join(page, "Mia")
    page.reload()
    expect(page.locator("#view-main")).to_be_visible()
    expect(page.locator("#me-line")).to_contain_text("Mia")


def test_falls_back_to_polling_when_relay_drops_long_polls(
    browser: Browser, harness: tuple[Harness, str]
) -> None:
    h, url = harness
    h.faults.fail_wait = True
    page = open_page(browser, url)
    join(page, "Mia")
    # Three aborted long polls, then normal polling ("state")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        actions = list(h.faults.actions)
        after_join = actions[actions.index("join") + 1 :]
        if after_join.count("wait") >= 3 and "state" in after_join[after_join.index("wait") :]:
            break
        time.sleep(0.2)
    else:
        pytest.fail(f"No fallback to polling: {h.faults.actions}")
    # The update still arrives
    other_guest_suggests(h, "Tom", "lemonade")
    # The first guest request displaces the base track and then shows up under "After that:".
    expect(page.locator("#view-main")).to_contain_text("Lemonade Protocol", timeout=15000)


def test_pauses_while_hidden(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_page(browser, url)
    join(page, "Mia")
    page.evaluate(
        "Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});"
        "document.dispatchEvent(new Event('visibilitychange'));"
    )
    time.sleep(0.5)
    count = len(h.faults.actions)
    time.sleep(2)
    assert len(h.faults.actions) == count, "No requests may run in the background"
    other_guest_suggests(h, "Tom", "lemonade")
    page.evaluate(
        "Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});"
        "document.dispatchEvent(new Event('visibilitychange'));"
    )
    # Returning triggers an immediate "state"
    expect(page.locator("#view-main")).to_contain_text("Lemonade Protocol", timeout=3000)
    assert h.faults.actions[count] == "state"


def test_vote_for_a_party_playlist_song(browser: Browser, harness: tuple[Harness, str]) -> None:
    _, url = harness
    page = open_page(browser, url)
    join(page, "Mia")
    playlist = page.locator("#playlist-list li.fallback")
    expect(playlist.first).to_be_visible(timeout=8000)
    expect(page.locator("#playlist-title")).to_have_text("Then from the party playlist")
    title = playlist.nth(1).locator(".row-title").inner_text()
    playlist.nth(1).locator("button").click()
    voted = page.locator("#queue-list li", has_text=title)
    expect(voted.locator(".vote.on")).to_be_visible()
    expect(voted.locator(".count")).to_have_text("1")
    expect(page.locator("#me-line")).to_contain_text("4 votes left")


def test_german_localization(browser: Browser, harness: tuple[Harness, str]) -> None:
    _, url = harness
    page = open_page(browser, url, locale="de-DE")
    expect(page.locator("html")).to_have_attribute("lang", "de")
    expect(page.locator(".join-title")).to_have_text("Was soll als Nächstes laufen?")
    page.fill("#join-name", "Mia")
    page.click("text=Mitmachen")
    expect(page.locator("#me-line")).to_contain_text("Mia, du hast noch 5 Stimmen")
    expect(page.locator("#search")).to_have_attribute("placeholder", "Song oder Interpret suchen")
    page.fill("#search", "comet")
    page.locator("#results-list li", has_text="Slow Comet").locator("button").click()
    expect(page.locator("#toast")).to_contain_text("Vorgeschlagen")
    assert page.evaluate("window.__csp") == []


def test_english_is_the_default(browser: Browser, harness: tuple[Harness, str]) -> None:
    _, url = harness
    page = open_page(browser, url, locale="ja-JP")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator(".join-title")).to_have_text("What should play next?")


def test_page_is_self_contained() -> None:
    from .guest_harness import PAGE

    html = PAGE.read_text(encoding="utf-8")
    assert len(html.encode()) < 50 * 1024
    assert "default-src 'none'" in html
    assert 'name="referrer" content="no-referrer"' in html
    for forbidden in ("<script src", "<link", "http://", "innerHTML", "@import"):
        assert forbidden not in html, forbidden
