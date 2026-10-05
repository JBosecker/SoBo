"""Property tests (Hypothesis) for ranking and the vote budget (plan phase 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sobo.engine.limits import sliding_budget  # noqa: E402
from sobo.engine.models import Origin, QueueItem  # noqa: E402
from sobo.engine.ranking import ranked  # noqa: E402
from sobo.sonos.fixtures import fake_catalog  # noqa: E402

T0 = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
TRACK = fake_catalog()[0]

item_specs = st.lists(
    st.tuples(st.integers(0, 20), st.booleans(), st.integers(0, 3600)),
    min_size=0,
    max_size=40,
)


def _build(specs: list[tuple[int, bool, int]]) -> list[QueueItem]:
    items = []
    for n, (votes, pinned, offset) in enumerate(specs):
        item = QueueItem(
            f"{n:04d}", TRACK, Origin.GUEST, T0 + timedelta(seconds=offset), pinned=pinned
        )
        item.voters = {f"g{i}" for i in range(votes)}
        items.append(item)
    return items


# The first example can be slow on cold runners (imports); that is not a data problem.
@settings(suppress_health_check=[HealthCheck.too_slow])
@given(item_specs)
def test_ranking_invariants(specs: list[tuple[int, bool, int]]) -> None:
    order = ranked(_build(specs))
    for a, b in pairwise(order):
        # pinned always first
        assert a.pinned or not b.pinned
        if a.pinned == b.pinned:
            # Within the same pin group: more votes first, on a tie older first
            assert a.votes >= b.votes
            if a.votes == b.votes:
                assert a.submitted_at <= b.submitted_at


@given(item_specs)
def test_ranking_is_permutation_invariant(specs: list[tuple[int, bool, int]]) -> None:
    items = _build(specs)
    assert [i.id for i in ranked(items)] == [i.id for i in ranked(reversed(items))]


@given(
    st.lists(st.integers(0, 7200), max_size=50),
    st.integers(1, 20),
    st.integers(1, 120),
)
def test_budget_never_exceeds_limit(offsets: list[int], limit: int, minutes: int) -> None:
    window = timedelta(minutes=minutes)
    now = T0 + timedelta(seconds=7200)
    events = [T0 + timedelta(seconds=o) for o in offsets]
    state = sliding_budget(events, limit, window, now)
    in_window = sum(1 for e in events if e > now - window)
    assert 0 <= state.remaining <= limit
    assert state.remaining == max(0, limit - in_window)
    if state.next_free_in is not None:
        assert 0 <= state.next_free_in <= window.total_seconds()
