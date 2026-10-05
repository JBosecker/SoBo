"""Browser tests of the admin UI against the real admin app (plan phase 3)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("fastapi")

from playwright.sync_api import Browser, Page, expect, sync_playwright

from sobo.engine.settings import FallbackSettings, JukeboxSettings, SpeakerSettings
from sobo.sonos.fixtures import FAKE_ACCOUNT_ID

from .admin_harness import CLOUD_URL, AdminHarness, create_admin_harness, serve

pytestmark = pytest.mark.browser

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
        except Exception as err:
            pytest.skip(f"Chromium not available: {err}")
        yield instance
        instance.close()


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[tuple[AdminHarness, str]]:
    h = create_admin_harness(tmp_path)
    with serve(h) as url:
        yield h, url


def open_admin(browser: Browser, url: str, tab: str = "live", locale: str = "en-US") -> Page:
    context = browser.new_context(viewport={"width": 1180, "height": 900}, locale=locale)
    context.add_init_script(CSP_RECORDER)
    context.add_init_script(f"localStorage.setItem('sobo.tab', '{tab}')")
    context.route("https://**/*", lambda route: route.abort())
    page = context.new_page()
    page.goto(url)
    return page


def configure(h: AdminHarness, active: bool = True) -> None:
    settings = JukeboxSettings(
        active=active,
        account_id=FAKE_ACCOUNT_ID,
        speaker=SpeakerSettings(coordinator_uid="RINCON_FAKE_LIVING"),
        fallback=FallbackSettings(source_id="fake_playlist:party", shuffle=False),
        timezone="UTC",
    )
    h.run(h.ctx.jukebox.update_settings(settings, "test"))


def guest_wishes(h: AdminHarness, name: str, *queries: str) -> None:
    svc = h.ctx.guest_service

    def call(**payload: object) -> dict[str, object]:
        status, body = h.run(svc.handle(json.dumps(payload).encode()))
        assert status == 200, body
        return body

    session = call(action="join", nickname=name)["session"]
    for query in queries:
        hit = call(action="search", session=session, q=query)["results"][0]  # type: ignore[index]
        call(action="suggest", session=session, result=hit["id"])  # type: ignore[index]


def test_setup_through_forms(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    page = open_admin(browser, url, "settings")
    expect(page.locator("#state-pill")).to_have_text("Off")
    # Without a speaker: a hint instead of the account list
    expect(page.locator("form[data-section=music]")).to_contain_text(
        "Choose and save a speaker first."
    )
    page.select_option("#f-speaker-coordinator_uid", "RINCON_FAKE_LIVING")
    expect(page.locator("#f-speaker-members")).to_contain_text("Kitchen")
    expect(page.locator("#f-speaker-members")).not_to_contain_text("Living Room")
    page.locator("form[data-section=speaker] button[type=submit]").click()
    expect(page.locator("form[data-section=speaker] .status")).to_have_text("Saved.")

    page.wait_for_selector("#f-account_id option[value='fake-apple-1']", state="attached")
    page.select_option("#f-account_id", "fake-apple-1")
    page.select_option("#f-fallback-source_id", "fake_playlist:party")
    page.locator("form[data-section=music] button[type=submit]").click()
    expect(page.locator("form[data-section=music] .status")).to_have_text("Saved.")

    page.click(".power")
    expect(page.locator("#power-label")).to_have_text("Jukebox on")
    expect(page.locator("#state-pill")).to_have_text("Playing base playlist", timeout=8000)
    saved = h.ctx.jukebox.settings
    assert saved.speaker.coordinator_uid == "RINCON_FAKE_LIVING"
    assert saved.account_id == FAKE_ACCOUNT_ID
    assert saved.fallback.source_id == "fake_playlist:party"
    assert page.evaluate("window.__csp") == []


def test_field_errors_from_api(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    configure(h, active=False)
    page = open_admin(browser, url, "settings")
    page.fill("#f-speaker-max_volume", "150")
    page.locator("form[data-section=speaker] button[type=submit]").click()
    field = page.locator("[data-path='speaker.max_volume']")
    expect(field.locator(".error")).to_have_text("Please enter a value from 0 to 100.")
    expect(field).to_have_class(re.compile(r"\binvalid\b"))
    assert h.ctx.jukebox.settings.speaker.max_volume == 60

    page.click("#tab-access")
    page.fill("#f-guest_access-presence_code", "12a")
    page.locator("form[data-section=guest_access] button[type=submit]").click()
    expect(page.locator("[data-path='guest_access.presence_code'] .error")).to_have_text(
        "Please enter 4 to 8 digits."
    )
    page.fill("#f-guest_access-presence_code", "4711")
    page.locator("form[data-section=guest_access] button[type=submit]").click()
    expect(page.locator("form[data-section=guest_access] .status")).to_have_text("Saved.")
    assert h.ctx.jukebox.settings.guest_access.presence_code == "4711"


def test_minutes_are_converted(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    page = open_admin(browser, url, "settings")
    expect(page.locator("#f-limits-max_track_seconds")).to_have_value("10")
    page.fill("#f-limits-max_track_seconds", "7.5")
    page.fill("#f-limits-blocklist", "Koto Fuzz\n\n  song:1  \n")
    page.locator("form[data-section=limits] button[type=submit]").click()
    expect(page.locator("form[data-section=limits] .status")).to_have_text("Saved.")
    limits = h.ctx.jukebox.settings.limits
    assert limits.max_track_seconds == 450
    assert limits.blocklist == ["Koto Fuzz", "song:1"]


def test_live_moderation(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    configure(h)
    guest_wishes(h, "Mia", "comet", "copper")
    guest_wishes(h, "Tom", "velvet")
    page = open_admin(browser, url)
    queue = page.locator("#queue li")
    # The next song is only fixed shortly before the end: all three are still open.
    expect(queue).to_have_count(3, timeout=8000)
    expect(page.locator("#next-line")).to_contain_text("chosen by the votes")
    expect(queue.first).to_contain_text("Requested by Mia")

    strip = queue.filter(has_text="Velvet Engine")
    strip.get_by_role("button", name="Pin").click()
    expect(strip.get_by_role("button", name="Pinned")).to_be_visible()
    expect(queue.first).to_contain_text("Velvet Engine")

    queue.filter(has_text="Copper Sky").get_by_role("button", name="Remove Copper Sky").click()
    expect(queue).to_have_count(2)
    expect(page.locator("#toast")).to_have_text("Removed.")

    tom = page.locator("#guests li", has_text="Tom")
    tom.get_by_role("button", name="Block Tom").click()
    expect(tom.get_by_role("button", name="Unblock Tom")).to_be_visible()
    assert next(g for g in h.ctx.jukebox.guests.values() if g.nickname == "Tom").blocked

    page.click("#freeze")
    expect(page.locator("#freeze")).to_have_attribute("aria-pressed", "true")
    assert h.ctx.jukebox.frozen

    # Skipping fixes the next song first: the pinned one wins.
    page.click("#skip")
    expect(page.locator("#now-title")).to_have_text("Velvet Engine", timeout=8000)
    page.click("#tab-log")
    expect(page.locator("#log")).to_contain_text("Song skipped")
    expect(page.locator("#log")).to_contain_text("Guest blocked")


def test_manual_override_banner(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    configure(h)
    page = open_admin(browser, url)
    expect(page.locator("#state-pill")).to_have_text("Playing base playlist", timeout=8000)
    h.adapter.external_play(h.adapter.catalog[-2])
    banner = page.locator("#banner")
    expect(banner).to_contain_text("Overtime Anthem", timeout=8000)
    page.get_by_role("button", name="Take over again").click()
    expect(page.locator("#state-pill")).to_have_text("Playing base playlist", timeout=8000)
    expect(banner).to_be_hidden()


def test_guest_access_and_rotation(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    page = open_admin(browser, url, "access")
    expect(page.locator("#guest-url")).to_have_text(CLOUD_URL)
    expect(page.locator("#fact-cloud")).to_have_text("Connected")
    qr = page.locator("#qr")
    expect(qr).to_be_visible()
    assert page.evaluate("document.getElementById('qr').naturalWidth") > 0
    old_src = qr.get_attribute("src")

    page.click("#rotate")
    expect(page.locator("#rotate-confirm")).to_contain_text("every guest has to join again")
    page.click("#rotate-no")
    expect(page.locator("#rotate-confirm")).to_be_hidden()
    assert h.ctx.rotation_requested == 0

    page.click("#rotate")
    page.click("#rotate-yes")
    expect(page.locator("#guest-url")).to_have_text(f"{CLOUD_URL}-1", timeout=8000)
    assert qr.get_attribute("src") != old_src

    # The print view only shows the poster sheet
    page.emulate_media(media="print")
    expect(page.locator(".print-sheet")).to_be_visible()
    expect(page.locator(".topbar")).to_be_hidden()


def test_without_integration(browser: Browser, tmp_path: Path) -> None:
    h = create_admin_harness(tmp_path, integration=False)
    with serve(h) as url:
        page = open_admin(browser, url, "access")
        expect(page.locator("#access-explain")).to_contain_text("integration is not connected")
        expect(page.locator("#rotate")).to_be_disabled()
        expect(page.locator("#print")).to_be_disabled()
        expect(page.locator("#qr-missing")).to_have_text("No guest link yet.")


def test_german_localization(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    configure(h)
    guest_wishes(h, "Mia", "comet", "copper")
    page = open_admin(browser, url, locale="de-DE")
    expect(page.locator("html")).to_have_attribute("lang", "de")
    expect(page.locator("#tab-access")).to_have_text("Gastzugang")
    expect(page.locator("#state-pill")).to_have_text(re.compile(r"^Spielt "), timeout=8000)
    expect(page.locator("#queue li").first).to_contain_text("Wunsch von Mia")
    expect(page.get_by_role("button", name="Copper Sky entfernen")).to_be_visible()
    page.click("#tab-settings")
    expect(page.locator("form[data-section=speaker] h2")).to_have_text("Lautsprecher")
    expect(page.locator("label[for=f-speaker-max_volume]")).to_have_text("Maximale Lautstärke")
    page.fill("#f-speaker-max_volume", "150")
    page.locator("form[data-section=speaker] button[type=submit]").click()
    expect(page.locator("[data-path='speaker.max_volume'] .error")).to_have_text(
        "Bitte einen Wert von 0 bis 100 eingeben."
    )
    assert page.evaluate("window.__csp") == []


def test_unsupported_language_falls_back_to_english(
    browser: Browser, harness: tuple[AdminHarness, str]
) -> None:
    _, url = harness
    page = open_admin(browser, url, locale="fr-FR")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("#tab-access")).to_have_text("Guest access")
    expect(page.locator("#state-pill")).to_have_text("Off")


def test_sonos_list_errors_show_the_reason(
    browser: Browser, harness: tuple[AdminHarness, str]
) -> None:
    h, url = harness
    configure(h, active=False)
    h.adapter.fail_calls.add("get_accounts")
    page = open_admin(browser, url, "settings")
    expect(page.locator("form[data-section=music]")).to_contain_text(
        "Sonos is not responding right now. (Reason: simulated failure in get_accounts)"
    )


def test_music_sign_in_banner(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    configure(h)
    h.ctx.jukebox.service_error = "music_auth"
    page = open_admin(browser, url)
    expect(page.locator("#banner")).to_contain_text("sign in again", timeout=8000)
    page_de = open_admin(browser, url, locale="de-DE")
    expect(page_de.locator("#banner")).to_contain_text("melde dich neu an", timeout=8000)
