"""Engine-Tests gegen den FakeSonosAdapter mit simulierter Zeit (Plan 9, Phase 2)."""

from __future__ import annotations

import json
import random

import pytest

from sobo.clock import ManualClock
from sobo.engine.jukebox import Jukebox
from sobo.engine.limits import RuleViolation
from sobo.engine.models import ItemState, Origin
from sobo.engine.persistence import MemoryRepository
from sobo.engine.settings import FallbackSettings, LimitSettings, VoteSettings
from sobo.engine.state import JukeboxState
from sobo.sonos.adapter import TransportState
from sobo.sonos.fake_adapter import FakeSonosAdapter
from sobo.sonos.worker import SonosWorker

from .conftest import active_settings, make_guest, suggest_title

pytestmark = pytest.mark.anyio


async def apply(jb: Jukebox, **overrides: object) -> None:
    await jb.update_settings(active_settings(**overrides), "admin")


async def finish_current(jb: Jukebox, fake: FakeSonosAdapter, clock: ManualClock) -> None:
    """Spult bis kurz nach dem Ende des laufenden Titels und lässt die Engine reagieren."""
    status = fake.get_status()
    assert status.duration is not None and status.position is not None
    clock.advance(status.duration - status.position + 1)
    await jb.tick()


# --------------------------------------------------------------------------- Grundzustände


async def test_inactive_does_nothing(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    await apply(jukebox, active=False)
    await jukebox.tick()
    assert jukebox.state == JukeboxState.INACTIVE
    assert "play_now" not in fake.calls


async def test_idle_without_fallback_and_queue(jukebox: Jukebox) -> None:
    await jukebox.tick()
    assert jukebox.state == JukeboxState.IDLE


async def test_missing_speaker_is_error(jukebox: Jukebox) -> None:
    settings = active_settings()
    settings.speaker.coordinator_uid = None
    await jukebox.update_settings(settings, "admin")
    await jukebox.tick()
    assert jukebox.state == JukeboxState.ERROR
    assert jukebox.last_error == "no_speaker"


async def test_fallback_plays_when_queue_empty(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    await apply(jukebox, fallback=FallbackSettings(source_id="fake_playlist:party", shuffle=False))
    await jukebox.tick()
    assert jukebox.state == JukeboxState.PLAYING_FALLBACK
    assert fake.queue[0].title == "Neon Harbor"
    assert fake.queue[1].title == "Paper Satellites"
    assert jukebox.queue.next_item is not None
    assert jukebox.queue.next_item.origin == Origin.FALLBACK


async def test_guest_suggestion_starts_playback(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    await jukebox.tick()
    guest = make_guest(jukebox)
    item = await suggest_title(jukebox, guest, "Slow Comet")
    assert jukebox.wakeup.is_set()
    await jukebox.tick()
    assert jukebox.state == JukeboxState.PLAYING_GUEST
    assert item.state == ItemState.PLAYING
    assert fake.get_status().current_key == item.track.item_id


# --------------------------------------------------------------------------- Ranking & Lookahead


async def test_ranking_picks_most_votes_when_next_is_chosen(
    jukebox: Jukebox, fake: FakeSonosAdapter
) -> None:
    a, b, c = (make_guest(jukebox, n) for n in "ABC")
    await suggest_title(jukebox, a, "Slow Comet")
    await jukebox.tick()
    # Kein weiterer Tick zwischen den Vorschlägen: beide warten gleichzeitig.
    low = await suggest_title(jukebox, a, "Velvet Engine")
    high = await suggest_title(jukebox, b, "Copper Sky")
    await jukebox.vote(c, high.id)
    await jukebox.tick()
    assert jukebox.queue.next_item is high
    assert low.state == ItemState.QUEUED
    # Fixiert: weitere Votes für `low` ändern den nächsten Titel nicht mehr.
    d, e = make_guest(jukebox, "D"), make_guest(jukebox, "E")
    await jukebox.vote(d, low.id)
    await jukebox.vote(e, low.id)
    await jukebox.tick()
    assert jukebox.queue.next_item is high
    with pytest.raises(RuleViolation) as err:
        await jukebox.vote(d, high.id)
    assert err.value.code == "locked"


async def test_transition_to_next_and_refill(
    jukebox: Jukebox, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    g = make_guest(jukebox)
    first = await suggest_title(jukebox, g, "Slow Comet")
    second = await suggest_title(jukebox, g, "Gravity Lessons")
    await jukebox.tick()
    assert first.state == ItemState.PLAYING and second.state == ItemState.NEXT
    third = await suggest_title(jukebox, g, "Sunday Static")
    await finish_current(jukebox, fake, clock)
    assert first.state == ItemState.PLAYED
    assert second.state == ItemState.PLAYING
    assert third.state == ItemState.NEXT
    assert [t.item_id for t in fake.queue[fake.index :]] == [
        second.track.item_id,
        third.track.item_id,
    ]


async def test_queue_runs_out_then_new_suggestion_restarts(
    jukebox: Jukebox, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    g = make_guest(jukebox)
    first = await suggest_title(jukebox, g, "Slow Comet")
    await jukebox.tick()
    await finish_current(jukebox, fake, clock)
    assert first.state == ItemState.PLAYED
    assert jukebox.state == JukeboxState.IDLE
    second = await suggest_title(jukebox, g, "Copper Sky")
    await jukebox.tick()
    assert second.state == ItemState.PLAYING
    assert fake.get_status().transport == TransportState.PLAYING


async def test_guest_track_preempts_fallback_next(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    await apply(jukebox, fallback=FallbackSettings(source_id="fake_playlist:party", shuffle=False))
    await jukebox.tick()
    fallback_next = jukebox.queue.next_item
    assert fallback_next is not None and fallback_next.origin == Origin.FALLBACK
    g = make_guest(jukebox)
    item = await suggest_title(jukebox, g, "Copper Sky")
    await jukebox.tick()
    assert jukebox.queue.next_item is item
    assert fallback_next.state == ItemState.REMOVED
    assert fake.queue[-1].item_id == item.track.item_id


async def test_unavailable_track_is_skipped(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    g, h = make_guest(jukebox, "G"), make_guest(jukebox, "H")
    await suggest_title(jukebox, g, "Slow Comet")
    await jukebox.tick()
    broken = await suggest_title(jukebox, g, "Copper Sky")
    await jukebox.vote(h, broken.id)
    ok = await suggest_title(jukebox, h, "Velvet Engine")
    fake.unavailable_ids.add(broken.track.item_id)
    await jukebox.tick()
    assert broken.state == ItemState.REMOVED
    assert broken.removed_reason == "unavailable"
    assert jukebox.queue.next_item is ok


# --------------------------------------------------------------------------- Regeln


async def test_vote_budget_sliding_window(jukebox: Jukebox, clock: ManualClock) -> None:
    await apply(
        jukebox,
        votes=VoteSettings(votes_per_window=2, window_minutes=10, suggestion_costs_vote=False),
        limits=LimitSettings(suggestions_per_window=10),
    )
    proposer = make_guest(jukebox, "P")
    voter = make_guest(jukebox, "V")
    items = [
        await suggest_title(jukebox, proposer, title)
        for title in ("Slow Comet", "Copper Sky", "Velvet Engine")
    ]
    await jukebox.vote(voter, items[0].id)
    clock.advance(60)
    await jukebox.vote(voter, items[1].id)
    with pytest.raises(RuleViolation) as err:
        await jukebox.vote(voter, items[2].id)
    assert err.value.code == "no_votes_left"
    assert err.value.retry_after == pytest.approx(540)
    clock.advance(541)
    await jukebox.vote(voter, items[2].id)
    assert items[2].votes == 2


async def test_suggestion_costs_vote(jukebox: Jukebox) -> None:
    await apply(jukebox, votes=VoteSettings(votes_per_window=1, suggestion_costs_vote=True))
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, g, "Copper Sky")
    assert err.value.code == "no_votes_left"


async def test_suggestion_limit(jukebox: Jukebox) -> None:
    await apply(
        jukebox,
        limits=LimitSettings(suggestions_per_window=1),
        votes=VoteSettings(votes_per_window=10),
    )
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, g, "Copper Sky")
    assert err.value.code == "no_suggestions_left"


async def test_duplicate_suggestion_counts_as_vote(jukebox: Jukebox) -> None:
    a, b = make_guest(jukebox, "A"), make_guest(jukebox, "B")
    first = await suggest_title(jukebox, a, "Slow Comet")
    again = await suggest_title(jukebox, b, "Slow Comet")
    assert again is first
    assert first.votes == 2
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, b, "Slow Comet")
    assert err.value.code == "already_voted"


async def test_suggesting_playing_track_is_rejected(jukebox: Jukebox) -> None:
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    await jukebox.tick()
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, make_guest(jukebox, "X"), "Slow Comet")
    assert err.value.code == "now_playing"


@pytest.mark.parametrize(
    ("limits", "title", "code"),
    [
        (LimitSettings(max_track_seconds=600), "Ten Minute Epic", "too_long"),
        (LimitSettings(explicit_filter=True), "Garden of Amps", "explicit"),
        (LimitSettings(blocklist=["koto fuzz"]), "Velvet Engine", "blocked_content"),
        (LimitSettings(blocklist=["song:1000010"]), "Slow Comet", "blocked_content"),
    ],
)
async def test_content_rules(
    jukebox: Jukebox, limits: LimitSettings, title: str, code: str
) -> None:
    await apply(jukebox, limits=limits)
    g = make_guest(jukebox)
    hits = await jukebox.search(g, title)
    hit = next(h for h in hits if h.track.title == title)
    assert hit.blocked == code
    with pytest.raises(RuleViolation) as err:
        await jukebox.suggest(g, hit.opaque_id)
    assert err.value.code == code


async def test_explicit_filter_ignores_unknown_flag(jukebox: Jukebox) -> None:
    await apply(jukebox, limits=LimitSettings(explicit_filter=True))
    item = await suggest_title(jukebox, make_guest(jukebox), "Copper Sky")  # explicit=None
    assert item.state == ItemState.QUEUED


async def test_recently_played_cooldown(
    jukebox: Jukebox, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    await apply(
        jukebox, limits=LimitSettings(track_cooldown_minutes=60, artist_cooldown_minutes=10)
    )
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    await jukebox.tick()
    await finish_current(jukebox, fake, clock)
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, make_guest(jukebox, "Y"), "Slow Comet")
    assert err.value.code == "recently_played"
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, make_guest(jukebox, "Z"), "Gravity Lessons")
    assert err.value.code == "artist_cooldown"
    clock.advance(11 * 60)
    await suggest_title(jukebox, make_guest(jukebox, "Q"), "Gravity Lessons")
    clock.advance(60 * 60)
    await suggest_title(jukebox, make_guest(jukebox, "R"), "Slow Comet")


async def test_blocked_guest_and_frozen_queue(jukebox: Jukebox) -> None:
    g = make_guest(jukebox)
    await jukebox.block_guest(g.id, True, "admin")
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, g, "Slow Comet")
    assert err.value.code == "blocked"
    other = make_guest(jukebox, "O")
    await jukebox.set_frozen(True, "admin")
    with pytest.raises(RuleViolation) as err:
        await suggest_title(jukebox, other, "Slow Comet")
    assert err.value.code == "frozen"


async def test_unknown_result_id(jukebox: Jukebox) -> None:
    with pytest.raises(RuleViolation) as err:
        await jukebox.suggest(make_guest(jukebox), "nicht-vorhanden")
    assert err.value.code == "unknown_result"


async def test_inactive_rejects_join(jukebox: Jukebox) -> None:
    await apply(jukebox, active=False)
    with pytest.raises(RuleViolation) as err:
        make_guest(jukebox)
    assert err.value.code == "inactive"


async def test_presence_code_and_guest_limit(jukebox: Jukebox) -> None:
    settings = active_settings()
    settings.guest_access.presence_code = "4711"
    settings.guest_access.max_active_guests = 1
    await jukebox.update_settings(settings, "admin")
    with pytest.raises(RuleViolation) as err:
        jukebox.join("A", "h1", "0000")
    assert err.value.code == "wrong_code"
    jukebox.join("A", "h1", "4711")
    with pytest.raises(RuleViolation) as err:
        jukebox.join("B", "h2", "4711")
    assert err.value.code == "too_many_guests"


# --------------------------------------------------------------------------- Admin & Eingriffe


async def test_manual_override_and_resume(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    waiting = await suggest_title(jukebox, g, "Copper Sky")
    await jukebox.tick()
    fake.external_play(fake.catalog[-2])
    await jukebox.tick()
    assert jukebox.state == JukeboxState.MANUAL_OVERRIDE
    assert jukebox.override_info == "Office Party – Overtime Anthem"
    assert "manual_override" in [e.action for e in jukebox.repo.recent_audit(5)]
    await jukebox.tick()  # bleibt im Override, greift nicht ein
    assert fake.queue[0].title == "Overtime Anthem"
    await jukebox.resume_control("admin")
    await jukebox.tick()
    assert waiting.state == ItemState.PLAYING
    assert jukebox.state == JukeboxState.PLAYING_GUEST


async def test_pause_detected(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    await suggest_title(jukebox, make_guest(jukebox), "Slow Comet")
    await jukebox.tick()
    fake.pause()
    await jukebox.tick()
    assert jukebox.state == JukeboxState.PAUSED
    fake.resume()
    await jukebox.tick()
    assert jukebox.state == JukeboxState.PLAYING_GUEST


async def test_max_volume_enforced(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    fake.volume = 90
    await jukebox.tick()
    assert fake.volume == 60


async def test_start_volume_applied_once(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    settings = active_settings()
    settings.speaker.start_volume = 25
    await jukebox.update_settings(settings, "admin")
    await jukebox.tick()
    assert fake.volume == 25
    fake.volume = 40
    await jukebox.tick()
    assert fake.volume == 40


async def test_admin_removes_next(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    nxt = await suggest_title(jukebox, g, "Copper Sky")
    later = await suggest_title(jukebox, g, "Velvet Engine")
    await jukebox.tick()
    assert jukebox.queue.next_item is nxt
    await jukebox.remove_item(nxt.id, "admin")
    await jukebox.tick()
    assert nxt.state == ItemState.REMOVED
    assert jukebox.queue.next_item is later
    assert fake.queue[-1].item_id == later.track.item_id


async def test_admin_pin(jukebox: Jukebox) -> None:
    a, b = make_guest(jukebox, "A"), make_guest(jukebox, "B")
    await suggest_title(jukebox, a, "Slow Comet")
    await jukebox.tick()
    popular = await suggest_title(jukebox, a, "Copper Sky")
    await jukebox.vote(b, popular.id)
    pinned = await suggest_title(jukebox, b, "Velvet Engine")
    await jukebox.pin_item(pinned.id, True, "admin")
    assert jukebox.queue.waiting()[0] is pinned


async def test_skip(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    g = make_guest(jukebox)
    first = await suggest_title(jukebox, g, "Slow Comet")
    second = await suggest_title(jukebox, g, "Copper Sky")
    await jukebox.tick()
    await jukebox.skip("admin")
    await jukebox.tick()
    assert first.state == ItemState.PLAYED
    assert second.state == ItemState.PLAYING


async def test_deactivate_clears_next(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    g = make_guest(jukebox)
    await suggest_title(jukebox, g, "Slow Comet")
    nxt = await suggest_title(jukebox, g, "Copper Sky")
    await jukebox.tick()
    await jukebox.set_active(False, "admin")
    await jukebox.tick()
    assert jukebox.state == JukeboxState.INACTIVE
    assert nxt.state == ItemState.QUEUED
    assert len(fake.queue) == 1


async def test_rotate_sessions(jukebox: Jukebox) -> None:
    g = make_guest(jukebox)
    assert jukebox.guest_for_token(g.token_hash) is g
    await jukebox.rotate_sessions("admin")
    assert jukebox.guest_for_token(g.token_hash) is None


async def test_session_expires(jukebox: Jukebox, clock: ManualClock) -> None:
    g = make_guest(jukebox)
    clock.advance(12 * 3600 + 1)
    assert jukebox.guest_for_token(g.token_hash) is None


async def test_sonos_error_sets_error_state(jukebox: Jukebox, fake: FakeSonosAdapter) -> None:
    fake.fail_calls.add("get_status")
    await jukebox.tick()
    assert jukebox.state == JukeboxState.ERROR
    assert jukebox.last_error
    fake.fail_calls.clear()
    await jukebox.tick()
    assert jukebox.state == JukeboxState.IDLE
    assert jukebox.last_error is None


# --------------------------------------------------------------------------- Persistenz & Ansichten


async def test_reload_restores_queue_and_votes(
    jukebox: Jukebox, repo: MemoryRepository, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    a, b = make_guest(jukebox, "A"), make_guest(jukebox, "B")
    await suggest_title(jukebox, a, "Slow Comet")
    await jukebox.tick()
    queued = await suggest_title(jukebox, a, "Copper Sky")
    await jukebox.vote(b, queued.id)
    await jukebox.tick()

    restarted = Jukebox(SonosWorker(fake), repo, clock, rng=random.Random(1))
    restored = restarted.queue.get(queued.id)
    assert restored is not None
    assert restored.voters == {a.id, b.id}
    assert restored.state == ItemState.QUEUED  # NEXT wird nach Neustart neu bestimmt
    assert restarted.guest_for_token(a.token_hash) is not None
    await restarted.tick()
    assert restarted.queue.playing is not None
    assert restarted.queue.playing.track.title == "Slow Comet"
    assert restarted.queue.next_item is restored
    restarted.worker.shutdown()


async def test_guest_view_is_small(jukebox: Jukebox) -> None:
    settings = active_settings(
        limits=LimitSettings(suggestions_per_window=100),
        votes=VoteSettings(votes_per_window=100),
    )
    await jukebox.update_settings(settings, "admin")
    g = make_guest(jukebox, "Sehr-langer-Spitzname")
    for track in jukebox.adapter.catalog:  # type: ignore[attr-defined]
        if track.duration and track.duration <= 600:
            await suggest_title(jukebox, g, track.title)
    await jukebox.tick()
    view = jukebox.guest_view(g)
    assert len(view["queue"]) == 30
    assert view["queue"][0]["mine"] is True
    assert len(json.dumps(view).encode()) < 10_000
    assert "id" not in view["now_playing"]


async def test_admin_view_contains_nicknames(jukebox: Jukebox) -> None:
    g = make_guest(jukebox, "Mia")
    await suggest_title(jukebox, g, "Slow Comet")
    view = jukebox.admin_view()
    assert view["queue"][0]["submitted_by"] == "Mia"
    assert jukebox.admin_guests()[0]["suggestions"] == 1


async def test_transient_stop_right_after_start_is_ignored(
    jukebox: Jukebox, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    item = await suggest_title(jukebox, make_guest(jukebox), "Slow Comet")
    await jukebox.tick()
    fake.transport = TransportState.STOPPED  # kurzer Übergang wie bei echtem Sonos
    clock.advance(1)
    await jukebox.tick()
    assert item.state == ItemState.PLAYING
    assert jukebox.state == JukeboxState.PAUSED
    fake.transport = TransportState.PLAYING
    await jukebox.tick()
    assert jukebox.state == JukeboxState.PLAYING_GUEST


async def test_empty_status_during_transition_is_not_override(
    jukebox: Jukebox, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    item = await suggest_title(jukebox, make_guest(jukebox), "Slow Comet")
    await jukebox.tick()
    fake.queue.clear()
    fake.transport = TransportState.TRANSITIONING
    await jukebox.tick()
    assert jukebox.state != JukeboxState.MANUAL_OVERRIDE
    assert item.state == ItemState.PLAYING


async def test_broken_fallback_is_retried_with_delay(
    jukebox: Jukebox, fake: FakeSonosAdapter, clock: ManualClock
) -> None:
    fake.fail_calls.add("fallback_tracks")
    await apply(jukebox, fallback=FallbackSettings(source_id="fake_playlist:party"))
    await jukebox.tick()
    await jukebox.tick()
    assert fake.calls.count("fallback_tracks") == 1
    assert jukebox.fallback_error
    fake.fail_calls.clear()
    clock.advance(61)
    await jukebox.tick()
    assert fake.calls.count("fallback_tracks") == 2
    assert jukebox.fallback_error is None
    assert jukebox.state == JukeboxState.PLAYING_FALLBACK
