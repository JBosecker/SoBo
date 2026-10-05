"""Locust scenario for SoBo (plan 9): about 100 guests, all with an open long poll.

Each simulated guest behaves like the guest page: join, keep exactly one `wait` open,
search now and then, suggest a song and vote for others.

Two targets:

* ``SOBO_TARGET=internal`` (default): straight to the app's internal API
  (``--host http://127.0.0.1:8738``, ``SOBO_SECRET`` = content of ``/data/secret``).
  Best with the Sonos simulation (``scripts/dev-run.sh``).
* ``SOBO_TARGET=webhook``: through Home Assistant, i.e. the integration's webhook or
  the Nabu Casa cloudhook (``--host https://hooks.nabu.casa/<id>``). This measures
  the relay limits from plan 10 (hold time, parallel requests).

Example::

    pip install locust
    SOBO_SECRET=$(cat sobo/backend/.data/secret) \\
      locust -f sobo/backend/loadtest/locustfile.py --host http://127.0.0.1:8738 \\
      --users 100 --spawn-rate 10 --run-time 5m --headless
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

from locust import HttpUser, between, events, task

TARGET = os.environ.get("SOBO_TARGET", "internal")
SECRET = os.environ.get("SOBO_SECRET", "")
WAIT_SECONDS = int(os.environ.get("SOBO_WAIT", "20"))
QUERIES = ["comet", "neon", "velvet", "copper", "salt", "lemon", "sky", "night", "on", "the"]


class Guest(HttpUser):
    wait_time = between(5, 20)

    def on_start(self) -> None:
        self.path = "/internal/guest" if TARGET == "internal" else ""
        self.headers = {"Content-Type": "application/json"}
        if TARGET == "internal":
            self.headers["X-SoBo-Secret"] = SECRET
        self.session: str | None = None
        self.version = 0
        self.queue: list[dict[str, Any]] = []
        self.polling = False
        self.next_wait = 0.0
        body = self.action("join", name="join", nickname=f"Load {random.randint(1, 99999)}")
        if body and body.get("ok"):
            self.session = body["session"]
            self.remember(body.get("state"))

    def action(self, action: str, name: str, **payload: Any) -> dict[str, Any] | None:
        if action != "join":
            if self.session is None:
                return None
            payload["session"] = self.session
        with self.client.post(
            self.path,
            json={"action": action, **payload},
            headers=self.headers,
            name=name,
            catch_response=True,
            timeout=WAIT_SECONDS + 15,
        ) as response:
            try:
                body = response.json()
            except ValueError:
                response.failure(f"no JSON (HTTP {response.status_code})")
                return None
            # Rule violations and rate limits are expected answers, not failures.
            if response.status_code >= 500 and body.get("error") != "sonos_unavailable":
                response.failure(f"HTTP {response.status_code}: {body}")
            elif body.get("error") == "invalid_session":
                self.session = None
                response.failure("session lost")
            else:
                response.success()
            return dict(body)

    def remember(self, state: dict[str, Any] | None) -> None:
        if state:
            self.version = max(self.version, int(state.get("version", 0)))
            self.queue = list(state.get("queue", []))

    @task(6)
    def wait(self) -> None:
        """Long poll like the guest page (one open `wait`, fallback to polling)."""
        if time.monotonic() < self.next_wait:
            return
        if self.polling:
            body = self.action("state", name="state (polling)")
            self.remember(body.get("state") if body else None)
            self.next_wait = time.monotonic() + 5
            return
        body = self.action("wait", name="wait", since=self.version, timeout=WAIT_SECONDS)
        if not body:
            return
        if body.get("mode") == "poll":
            self.polling = True
        if body.get("changed"):
            self.remember(body.get("state"))
        else:
            self.version = max(self.version, int(body.get("version", 0)))

    @task(2)
    def search_and_suggest(self) -> None:
        body = self.action("search", name="search", q=random.choice(QUERIES))
        results = (body or {}).get("results") or []
        candidates = [r for r in results if not r.get("blocked") and not r.get("queued")]
        if candidates and random.random() < 0.5:
            hit = random.choice(candidates)
            body = self.action("suggest", name="suggest", result=hit["id"])
            self.remember((body or {}).get("state"))

    @task(3)
    def vote(self) -> None:
        options = [item for item in self.queue if not item.get("voted") and not item.get("mine")]
        if options:
            body = self.action("vote", name="vote", item=random.choice(options)["id"])
            self.remember((body or {}).get("state"))


@events.test_start.add_listener
def check_config(environment: Any, **_: Any) -> None:
    if TARGET == "internal" and not SECRET:
        raise SystemExit("Set SOBO_SECRET (content of /data/secret) for SOBO_TARGET=internal")
