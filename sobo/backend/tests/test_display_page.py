"""Browser tests of the party display (Playwright + Chromium) against the real guest API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Browser, Page, expect, sync_playwright

from sobo.engine.settings import GuestAccessSettings

from .guest_harness import DISPLAY_PAGE, Harness, create_harness, serve

pytestmark = pytest.mark.browser

CSP_RECORDER = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__csp.push(e.violatedDirective + ' ' + e.blockedURI);
});
"""
TV = {"width": 1280, "height": 720}


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
        h.guest_access.local_url = url
        yield h, url


def open_display(
    browser: Browser,
    url: str,
    locale: str = "en-US",
    viewport: dict[str, int] = TV,
) -> Page:
    context = browser.new_context(viewport=viewport, locale=locale)
    context.add_init_script(CSP_RECORDER)
    context.route("https://**/*", lambda route: route.abort())
    page = context.new_page()
    page.goto(url)
    return page


def display_url(h: Harness, url: str) -> str:
    return h.display_key.url(url)


def guest_suggests(h: Harness, name: str, query: str) -> None:
    def call(**payload: Any) -> dict[str, Any]:
        status, body = h.run(h.service.handle(json.dumps(payload).encode()))
        assert status == 200, body
        return body

    session = call(action="join", nickname=name)["session"]
    hit = call(action="search", session=session, q=query)["results"][0]
    call(action="suggest", session=session, result=hit["id"])


def test_shows_song_queue_and_qr_code_live(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_display(browser, display_url(h, url))
    expect(page.locator("#view-main")).to_be_visible()
    expect(page.locator("#now-title")).not_to_have_text("Nothing yet", timeout=8000)
    expect(page.locator("#join")).to_be_visible()
    expect(page.locator("#join-title")).to_have_text("Request a song!")
    # The QR code is drawn onto the canvas (white quiet zone, dark modules).
    dark = page.evaluate(
        """() => {
          const c = document.getElementById('qr');
          const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let n = 0;
          for (let i = 0; i < data.length; i += 4) if (data[i] < 128) n++;
          return n;
        }"""
    )
    assert dark > 100
    guest_suggests(h, "Tom", "comet")
    row = page.locator("#queue-list li", has_text="Slow Comet")
    expect(row).to_have_count(1, timeout=8000)
    expect(row.locator(".votes .count")).to_have_text("1")
    # Nicknames stay on the phones.
    expect(page.locator("body")).not_to_contain_text("Tom")
    assert page.evaluate("window.__csp") == []


def test_presence_code_and_poster_texts(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    settings = h.jukebox.settings.model_copy(deep=True)
    settings.guest_access = GuestAccessSettings(long_poll_timeout=5, presence_code="4711")
    settings.poster.title = "Your song, please"
    settings.poster.text = "Scan me"
    h.run(h.jukebox.update_settings(settings, "test"))
    page = open_display(browser, display_url(h, url))
    expect(page.locator("#join-code")).to_have_text("Code: 4711")
    expect(page.locator("#join-title")).to_have_text("Your song, please")
    expect(page.locator("#join-text")).to_have_text("Scan me")


@pytest.mark.parametrize("fragment", ["", "#key=wrong-wrong-wrong-wrong-wrong-wrong-wrong"])
def test_without_a_valid_key(browser: Browser, harness: tuple[Harness, str], fragment: str) -> None:
    _, url = harness
    page = open_display(browser, f"{url}?view=display{fragment}")
    expect(page.locator("#view-denied")).to_be_visible()
    expect(page.locator("#view-main")).to_be_hidden()


def test_renewed_key_closes_open_displays(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_display(browser, display_url(h, url))
    expect(page.locator("#view-main")).to_be_visible()
    h.display_key.renew()
    h.service.end_display_polls()
    expect(page.locator("#view-denied")).to_be_visible(timeout=8000)


def test_new_link_in_the_same_tab_uses_the_new_key(
    browser: Browser, harness: tuple[Harness, str]
) -> None:
    h, url = harness
    page = open_display(browser, display_url(h, url))
    expect(page.locator("#view-main")).to_be_visible()
    h.display_key.renew()
    h.service.end_display_polls()
    expect(page.locator("#view-denied")).to_be_visible(timeout=8000)
    # Only the fragment differs: the browser does not reload on its own.
    page.goto(display_url(h, url))
    expect(page.locator("#view-main")).to_be_visible(timeout=8000)


def test_off_and_back_on_by_itself(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_display(browser, display_url(h, url))
    expect(page.locator("#view-main")).to_be_visible()
    h.run(h.jukebox.set_active(False, "test"))
    expect(page.locator("#view-off")).to_be_visible(timeout=8000)
    h.run(h.jukebox.set_active(True, "test"))
    expect(page.locator("#view-main")).to_be_visible(timeout=8000)


def test_portrait_tablet(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_display(browser, display_url(h, url), viewport={"width": 768, "height": 1024})
    expect(page.locator("#join")).to_be_visible()
    now = page.locator("#now").bounding_box()
    join = page.locator("#join").bounding_box()
    assert now is not None and join is not None
    assert join["y"] > now["y"] + now["height"] - 1  # stacked below now playing
    # Nothing sticks out: the page itself never scrolls.
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_german_localization(browser: Browser, harness: tuple[Harness, str]) -> None:
    h, url = harness
    page = open_display(browser, display_url(h, url), locale="de-DE")
    expect(page.locator("html")).to_have_attribute("lang", "de")
    expect(page.locator("#join-title")).to_have_text("Wünsch dir einen Song!")
    expect(page.locator("#queue-title")).to_have_text("Demnächst")


def test_page_is_self_contained() -> None:
    html = DISPLAY_PAGE.read_text(encoding="utf-8")
    assert len(html.encode()) < 50 * 1024
    assert "default-src 'none'" in html
    assert 'name="referrer" content="no-referrer"' in html
    for forbidden in ("<script src", "<link", "http://", "innerHTML", "@import"):
        assert forbidden not in html, forbidden
