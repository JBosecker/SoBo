"""Browser-Tests der Admin-Oberfläche gegen die echte Admin-App (Plan Phase 3)."""

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
            pytest.skip(f"Chromium nicht verfügbar: {err}")
        yield instance
        instance.close()


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[tuple[AdminHarness, str]]:
    h = create_admin_harness(tmp_path)
    with serve(h) as url:
        yield h, url


def open_admin(browser: Browser, url: str, tab: str = "live") -> Page:
    context = browser.new_context(viewport={"width": 1180, "height": 900})
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
    expect(page.locator("#state-pill")).to_have_text("Aus")
    # Ohne Lautsprecher: Hinweis statt Kontenliste
    expect(page.locator("form[data-section=music]")).to_contain_text(
        "Erst einen Lautsprecher wählen und speichern."
    )
    page.select_option("#f-speaker-coordinator_uid", "RINCON_FAKE_LIVING")
    expect(page.locator("#f-speaker-members")).to_contain_text("Küche")
    expect(page.locator("#f-speaker-members")).not_to_contain_text("Wohnzimmer")
    page.locator("form[data-section=speaker] button[type=submit]").click()
    expect(page.locator("form[data-section=speaker] .status")).to_have_text("Gespeichert.")

    page.wait_for_selector("#f-account_id option[value='fake-apple-1']", state="attached")
    page.select_option("#f-account_id", "fake-apple-1")
    page.select_option("#f-fallback-source_id", "fake_playlist:party")
    page.locator("form[data-section=music] button[type=submit]").click()
    expect(page.locator("form[data-section=music] .status")).to_have_text("Gespeichert.")

    page.click(".power")
    expect(page.locator("#power-label")).to_have_text("Jukebox an")
    expect(page.locator("#state-pill")).to_have_text("Spielt Basis-Playlist", timeout=8000)
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
    expect(field.locator(".error")).to_have_text("Bitte einen Wert von 0 bis 100 eingeben.")
    expect(field).to_have_class(re.compile(r"\binvalid\b"))
    assert h.ctx.jukebox.settings.speaker.max_volume == 60

    page.click("#tab-access")
    page.fill("#f-guest_access-presence_code", "12a")
    page.locator("form[data-section=guest_access] button[type=submit]").click()
    expect(page.locator("[data-path='guest_access.presence_code'] .error")).to_have_text(
        "Bitte 4 bis 8 Ziffern eingeben."
    )
    page.fill("#f-guest_access-presence_code", "4711")
    page.locator("form[data-section=guest_access] button[type=submit]").click()
    expect(page.locator("form[data-section=guest_access] .status")).to_have_text("Gespeichert.")
    assert h.ctx.jukebox.settings.guest_access.presence_code == "4711"


def test_minutes_are_converted(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    page = open_admin(browser, url, "settings")
    expect(page.locator("#f-limits-max_track_seconds")).to_have_value("10")
    page.fill("#f-limits-max_track_seconds", "7.5")
    page.fill("#f-limits-blocklist", "Koto Fuzz\n\n  song:1  \n")
    page.locator("form[data-section=limits] button[type=submit]").click()
    expect(page.locator("form[data-section=limits] .status")).to_have_text("Gespeichert.")
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
    expect(queue).to_have_count(2, timeout=8000)  # einer davon ist schon „als Nächstes“
    expect(page.locator("#next-line")).to_contain_text("Wunsch von Mia")

    strip = queue.filter(has_text="Velvet Engine")
    strip.get_by_role("button", name="Anpinnen").click()
    expect(strip.get_by_role("button", name="Angepinnt")).to_be_visible()
    expect(queue.first).to_contain_text("Velvet Engine")

    queue.filter(has_text="Copper Sky").get_by_role("button", name="Copper Sky entfernen").click()
    expect(queue).to_have_count(1)
    expect(page.locator("#toast")).to_have_text("Entfernt.")

    tom = page.locator("#guests li", has_text="Tom")
    tom.get_by_role("button", name="Tom sperren").click()
    expect(tom.get_by_role("button", name="Tom entsperren")).to_be_visible()
    assert next(g for g in h.ctx.jukebox.guests.values() if g.nickname == "Tom").blocked

    page.click("#freeze")
    expect(page.locator("#freeze")).to_have_attribute("aria-pressed", "true")
    assert h.ctx.jukebox.frozen

    page.click("#skip")
    expect(page.locator("#now-title")).to_have_text("Slow Comet", timeout=8000)
    page.click("#tab-log")
    expect(page.locator("#log")).to_contain_text("Song übersprungen")
    expect(page.locator("#log")).to_contain_text("Gast gesperrt")


def test_manual_override_banner(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    configure(h)
    page = open_admin(browser, url)
    expect(page.locator("#state-pill")).to_have_text("Spielt Basis-Playlist", timeout=8000)
    h.adapter.external_play(h.adapter.catalog[-2])
    banner = page.locator("#banner")
    expect(banner).to_contain_text("Overtime Anthem", timeout=8000)
    page.get_by_role("button", name="Wieder übernehmen").click()
    expect(page.locator("#state-pill")).to_have_text("Spielt Basis-Playlist", timeout=8000)
    expect(banner).to_be_hidden()


def test_guest_access_and_rotation(browser: Browser, harness: tuple[AdminHarness, str]) -> None:
    h, url = harness
    page = open_admin(browser, url, "access")
    expect(page.locator("#guest-url")).to_have_text(CLOUD_URL)
    expect(page.locator("#fact-cloud")).to_have_text("Verbunden")
    qr = page.locator("#qr")
    expect(qr).to_be_visible()
    assert page.evaluate("document.getElementById('qr').naturalWidth") > 0
    old_src = qr.get_attribute("src")

    page.click("#rotate")
    expect(page.locator("#rotate-confirm")).to_contain_text("alle Gäste müssen neu beitreten")
    page.click("#rotate-no")
    expect(page.locator("#rotate-confirm")).to_be_hidden()
    assert h.ctx.rotation_requested == 0

    page.click("#rotate")
    page.click("#rotate-yes")
    expect(page.locator("#guest-url")).to_have_text(f"{CLOUD_URL}-1", timeout=8000)
    assert qr.get_attribute("src") != old_src

    # Druckansicht zeigt nur das Aushängeblatt
    page.emulate_media(media="print")
    expect(page.locator(".print-sheet")).to_be_visible()
    expect(page.locator(".topbar")).to_be_hidden()


def test_without_integration(browser: Browser, tmp_path: Path) -> None:
    h = create_admin_harness(tmp_path, integration=False)
    with serve(h) as url:
        page = open_admin(browser, url, "access")
        expect(page.locator("#access-explain")).to_contain_text("Integration ist nicht verbunden")
        expect(page.locator("#rotate")).to_be_disabled()
        expect(page.locator("#print")).to_be_disabled()
        expect(page.locator("#qr-missing")).to_have_text("Noch kein Gast-Link.")
