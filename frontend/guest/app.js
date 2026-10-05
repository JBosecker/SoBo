"use strict";
(() => {
  // Die Seite spricht nur mit ihrer eigenen URL (Webhook/Cloudhook), alles per POST.
  const ENDPOINT = location.href.split("#")[0];
  const SESSION_KEY = "sobo.session";
  const RING = 295.3;
  const POLL_INTERVAL = 5000;
  const LONG_POLL_RETRY_AFTER = 3 * 60 * 1000;
  const MIN_WAIT = 5;

  const $ = (id) => document.getElementById(id);
  const views = ["loading", "join", "off", "main"];

  const MESSAGES = {
    too_long: "Der Song ist zu lang für diese Party.",
    explicit: "Songs mit explizitem Inhalt sind heute ausgeschaltet.",
    blocked_content: "Dieser Song ist für heute gesperrt.",
    recently_played: "Der Song lief gerade erst. Versuch es später noch mal.",
    artist_cooldown: "Von diesem Interpreten lief gerade erst etwas.",
    no_votes_left: "Deine Stimmen sind aufgebraucht.",
    no_suggestions_left: "Du hast gerade genug Songs vorgeschlagen.",
    already_voted: "Für diesen Song hast du schon gestimmt.",
    already_next: "Der Song kommt schon als Nächstes.",
    now_playing: "Der Song läuft gerade.",
    locked: "Der Song steht schon fest und kommt als Nächstes.",
    frozen: "Die Warteschlange ist gerade angehalten.",
    blocked: "Du kannst gerade keine Songs vorschlagen oder abstimmen.",
    too_many_guests: "Die Party ist voll. Versuch es gleich noch mal.",
    busy: "Gerade ist viel los. Versuch es gleich noch mal.",
    slow_down: "Etwas langsamer, bitte. Versuch es gleich noch mal.",
    unknown_result: "Die Suche ist abgelaufen. Bitte such noch einmal.",
    unknown_item: "Den Song gibt es nicht mehr in der Warteschlange.",
    sonos_unavailable: "Die Jukebox antwortet gerade nicht.",
    unavailable: "Die Jukebox antwortet gerade nicht.",
    not_configured: "Die Jukebox ist noch nicht fertig eingerichtet.",
    bad_nickname: "Bitte gib einen Namen mit Buchstaben oder Zahlen ein.",
    wrong_code: "Der Code stimmt nicht. Frag den Gastgeber.",
  };
  const BLOCKED_LABEL = {
    too_long: "Zu lang",
    explicit: "Explizit",
    blocked_content: "Gesperrt",
    recently_played: "Lief gerade",
    artist_cooldown: "Später",
  };

  // ------------------------------------------------------------------ Speicher

  const memory = {};
  const store = {
    get(key) {
      try { return localStorage.getItem(key); } catch (e) { return memory[key] || null; }
    },
    set(key, value) {
      try { localStorage.setItem(key, value); } catch (e) { memory[key] = value; }
    },
    del(key) {
      try { localStorage.removeItem(key); } catch (e) { delete memory[key]; }
    },
  };

  // ------------------------------------------------------------------ Zustand

  let session = store.get(SESSION_KEY);
  let state = null;
  let version = 0;
  let receivedAt = 0;
  let searchTimer = 0;
  let searchSeq = 0;
  let toastTimer = 0;

  // ------------------------------------------------------------------ Netzwerk

  class ApiError extends Error {
    constructor(status, code, retryAfter) {
      super(code);
      this.status = status;
      this.code = code;
      this.retryAfter = retryAfter;
    }
  }

  async function api(payload, { signal, timeoutMs = 15000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const onAbort = () => controller.abort();
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
    let response;
    try {
      response = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
        cache: "no-store",
        credentials: "omit",
      });
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
    }
    let body = null;
    try { body = await response.json(); } catch (e) { body = null; }
    if (!body || typeof body !== "object") throw new ApiError(response.status, "network");
    if (!response.ok || body.ok === false) {
      throw new ApiError(response.status, body.error || "network", body.retry_after);
    }
    return body;
  }

  function withSession(payload) {
    return Object.assign({ session }, payload);
  }

  // ------------------------------------------------------------------ Anzeige

  function show(name) {
    for (const v of views) $("view-" + v).hidden = v !== name;
  }

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
  }

  function minutes(seconds) {
    const s = Math.max(0, Math.round(seconds));
    const m = Math.floor(s / 60);
    return m > 0 ? `${m}:${String(s % 60).padStart(2, "0")} Min.` : `${s} Sek.`;
  }

  function messageFor(err) {
    let text = MESSAGES[err.code] || "Das hat nicht geklappt. Versuch es noch mal.";
    if (err.retryAfter && (err.code === "no_votes_left" || err.code === "no_suggestions_left")) {
      text += ` Wieder möglich in ${minutes(err.retryAfter)}`;
    }
    return text;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function strip(track, extraClass) {
    const li = el("li", "strip" + (extraClass ? " " + extraClass : ""));
    const text = el("div", "strip-text");
    text.append(el("span", "strip-title", track.title));
    text.append(el("span", "strip-artist", track.artist || " "));
    li.append(text);
    return li;
  }

  function applyState(next) {
    if (!next) return;
    state = next;
    version = next.version || version;
    receivedAt = Date.now();
    if (!next.active) {
      show("off");
      return;
    }
    show("main");
    renderNow();
    renderQueue();
    renderMe();
  }

  function renderNow() {
    const now = state.now_playing;
    const header = $("now");
    const art = $("now-art");
    header.classList.toggle("playing", Boolean(now) && state.state !== "paused");
    $("now-title").textContent = now ? now.title : "Noch nichts";
    $("now-artist").textContent = now ? now.artist : "Schlag den ersten Song vor.";
    if (now && now.art) {
      if (art.getAttribute("src") !== now.art) art.src = now.art;
      art.hidden = false;
    } else {
      art.hidden = true;
      art.removeAttribute("src");
    }
    const next = state.next;
    $("next-line").hidden = !next;
    $("next-line").textContent = next ? `Danach: ${next.title} von ${next.artist}` : "";
    tickProgress();
  }

  function tickProgress() {
    const now = state && state.now_playing;
    let fraction = 0;
    if (now && now.duration && now.position !== undefined) {
      const running = state.state === "playing_guest" || state.state === "playing_fallback";
      const elapsed = now.position + (running ? (Date.now() - receivedAt) / 1000 : 0);
      fraction = Math.min(1, Math.max(0, elapsed / now.duration));
    }
    $("ring").style.strokeDashoffset = String(RING * (1 - fraction));
  }

  function voteButton(item) {
    const button = el("button", "vote" + (item.voted ? " on" : ""));
    button.type = "button";
    button.append(el("span", "count", String(item.votes)));
    button.append(el("span", "verb", item.voted ? "Gestimmt" : "Dafür"));
    button.setAttribute(
      "aria-label",
      item.voted ? `Du hast für ${item.title} gestimmt` : `Für ${item.title} stimmen`
    );
    button.disabled = Boolean(item.voted);
    button.addEventListener("click", () => vote(item.id, button));
    return button;
  }

  function renderQueue() {
    const list = $("queue-list");
    const items = state.queue || [];
    list.replaceChildren(
      ...items.map((item) => {
        const li = strip(item, [item.mine && "mine", item.pinned && "pinned"].filter(Boolean).join(" "));
        if (item.mine) li.firstChild.append(el("span", "strip-meta", "Dein Wunsch"));
        li.append(voteButton(item));
        return li;
      })
    );
    $("queue-empty").hidden = items.length > 0;
  }

  function renderMe() {
    const me = state.me;
    if (!me) return;
    let line = `${me.nickname}, du hast noch ${me.votes_left} ${me.votes_left === 1 ? "Stimme" : "Stimmen"}.`;
    if (me.votes_left === 0 && me.votes_refill_in) line += ` Die nächste gibt es in ${minutes(me.votes_refill_in)}`;
    if (me.blocked) line = "Du kannst gerade nicht mitmachen.";
    $("me-line").textContent = line;
    const covers = Boolean(state.now_playing && state.now_playing.art) || (state.queue || []).some((q) => q.art);
    $("cover-note").hidden = !covers;
  }

  // ------------------------------------------------------------------ Aktionen

  async function vote(itemId, button) {
    button.disabled = true;
    try {
      const body = await api(withSession({ action: "vote", item: itemId }));
      applyState(body.state);
    } catch (err) {
      handleError(err);
      button.disabled = false;
    }
  }

  async function suggest(resultId, button) {
    button.disabled = true;
    try {
      const body = await api(withSession({ action: "suggest", result: resultId }));
      applyState(body.state);
      closeSearch();
      toast("Vorgeschlagen. Jetzt brauchst du nur noch Stimmen.");
    } catch (err) {
      handleError(err);
      button.disabled = false;
    }
  }

  function handleError(err) {
    if (err.code === "invalid_session") {
      resetSession();
      return;
    }
    if (err.code === "inactive") {
      show("off");
      return;
    }
    toast(messageFor(err));
  }

  function resetSession() {
    session = null;
    store.del(SESSION_KEY);
    show("join");
  }

  // ------------------------------------------------------------------ Suche

  function closeSearch() {
    $("search").value = "";
    $("results").hidden = true;
    $("search-clear").hidden = true;
    $("queue").hidden = false;
    searchSeq++;
  }

  function onSearchInput() {
    const q = $("search").value.trim();
    clearTimeout(searchTimer);
    $("search-clear").hidden = q.length === 0;
    if (q.length < 2) {
      $("results").hidden = true;
      $("queue").hidden = false;
      return;
    }
    searchTimer = setTimeout(() => runSearch(q), 350);
  }

  async function runSearch(q) {
    const seq = ++searchSeq;
    $("results").hidden = false;
    $("queue").hidden = true;
    $("results-note").textContent = "Suche …";
    let body;
    try {
      body = await api(withSession({ action: "search", q }));
    } catch (err) {
      if (seq !== searchSeq) return;
      $("results-note").textContent = "";
      handleError(err);
      return;
    }
    if (seq !== searchSeq) return;
    const results = body.results || [];
    $("results-note").textContent = results.length ? "" : `Nichts gefunden für „${q}“.`;
    $("results-list").replaceChildren(...results.map(resultRow));
  }

  function resultRow(hit) {
    const li = strip(hit);
    if (hit.album) li.firstChild.append(el("span", "strip-meta", hit.album));
    let button;
    if (hit.queued) {
      const queued = (state.queue || []).find((q) => q.id === hit.queued);
      if (queued) {
        // Schon gewünscht: Vorschlag zählt als Stimme, also gleich den Stimm-Button zeigen.
        li.append(voteButton(queued));
        return li;
      }
      button = el("button", "vote blocked", "Schon dabei");
      button.disabled = true;
    } else if (hit.blocked) {
      button = el("button", "vote blocked", BLOCKED_LABEL[hit.blocked] || "Gesperrt");
      button.disabled = true;
      button.title = MESSAGES[hit.blocked] || "";
    } else {
      button = el("button", "vote");
      button.append(el("span", "count", "+"));
      button.append(el("span", "verb", "Wünschen"));
      button.setAttribute("aria-label", `${hit.title} vorschlagen`);
      button.addEventListener("click", () => suggest(hit.id, button));
    }
    button.type = "button";
    li.append(button);
    return li;
  }

  // ------------------------------------------------------------------ Beitreten

  async function join(event) {
    event.preventDefault();
    const nickname = $("join-name").value.trim();
    const code = $("join-code").value.trim();
    const error = $("join-error");
    error.hidden = true;
    if (!nickname) {
      error.textContent = "Bitte gib deinen Namen ein.";
      error.hidden = false;
      return;
    }
    const button = event.target.querySelector("button");
    button.disabled = true;
    try {
      const payload = { action: "join", nickname };
      if (code) payload.code = code;
      const body = await api(payload);
      session = body.session;
      store.set(SESSION_KEY, session);
      applyState(body.state);
      startSync();
    } catch (err) {
      if (err.code === "inactive") {
        show("off");
      } else {
        if (err.code === "wrong_code") $("join-code-row").hidden = false;
        error.textContent = messageFor(err);
        error.hidden = false;
      }
    } finally {
      button.disabled = false;
    }
  }

  // ------------------------------------------------------------------ Live-Aktualisierung
  // Long Polling über den Cloudhook, bei Problemen Rückfall auf normales Polling (Plan 4.4).

  const sync = {
    running: false,
    mode: "long",
    waitSeconds: null, // null = Wartezeit der App
    failures: 0,
    pollingSince: 0,
    controller: null,
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const jitter = (ms) => ms * (0.75 + Math.random() * 0.5);

  function whenVisible() {
    if (!document.hidden) return Promise.resolve();
    return new Promise((resolve) => {
      const onChange = () => {
        if (!document.hidden) {
          document.removeEventListener("visibilitychange", onChange);
          resolve();
        }
      };
      document.addEventListener("visibilitychange", onChange);
    });
  }

  async function refreshState() {
    const body = await api(withSession({ action: "state" }));
    applyState(body.state);
  }

  async function longPollOnce() {
    const payload = withSession({ action: "wait", since: version });
    if (sync.waitSeconds) payload.timeout = sync.waitSeconds;
    const expected = (sync.waitSeconds || 20) * 1000;
    const started = Date.now();
    sync.controller = new AbortController();
    try {
      const body = await api(payload, { signal: sync.controller.signal, timeoutMs: expected + 15000 });
      sync.failures = 0;
      if (body.changed) applyState(body.state);
      else version = Math.max(version, body.version || 0);
      if (body.mode === "poll") switchToPolling();
      else if (body.replaced) await sleep(jitter(5000)); // zweiter Tab mit derselben Session
    } catch (err) {
      if (document.hidden) return; // bewusst abgebrochen
      if (err.code === "invalid_session") throw err;
      if (err.status && err.status < 500 && err.status !== 429) throw err;
      // Netzwerkfehler oder 5xx vor Ablauf der Wartezeit: Relay hält offenbar nicht so lange.
      if (Date.now() - started < expected) {
        sync.waitSeconds = Math.max(MIN_WAIT, Math.floor((sync.waitSeconds || 20) / 2));
      }
      sync.failures += 1;
      if (sync.failures >= 3) switchToPolling();
      else await sleep(jitter(1000 * 2 ** sync.failures));
    } finally {
      sync.controller = null;
    }
  }

  function switchToPolling() {
    sync.mode = "poll";
    sync.pollingSince = Date.now();
    sync.failures = 0;
  }

  async function pollOnce() {
    try {
      await refreshState();
      sync.failures = 0;
    } catch (err) {
      if (err.code === "invalid_session") throw err;
      sync.failures += 1;
    }
    await sleep(jitter(POLL_INTERVAL * Math.min(4, 1 + sync.failures)));
    if (Date.now() - sync.pollingSince > LONG_POLL_RETRY_AFTER) {
      sync.mode = "long";
      sync.failures = 0;
    }
  }

  async function syncLoop() {
    while (sync.running && session) {
      if (document.hidden) {
        await whenVisible();
        try { await refreshState(); } catch (err) { if (err.code === "invalid_session") { resetSession(); break; } }
        continue;
      }
      try {
        if (sync.mode === "long") await longPollOnce();
        else await pollOnce();
      } catch (err) {
        if (err.code === "invalid_session") { resetSession(); break; }
        if (err.code === "inactive") show("off");
        await sleep(jitter(POLL_INTERVAL));
      }
    }
    sync.running = false;
  }

  function startSync() {
    if (sync.running) return;
    sync.running = true;
    syncLoop();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && sync.controller) sync.controller.abort();
  });

  // ------------------------------------------------------------------ Start

  async function boot() {
    $("join-form").addEventListener("submit", join);
    $("search").addEventListener("input", onSearchInput);
    $("search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("search").value.trim();
      if (q.length >= 2) { clearTimeout(searchTimer); runSearch(q); }
    });
    $("search-clear").addEventListener("click", closeSearch);
    // Cover nicht ladbar (offline, blockiert): lieber ohne Bild als mit kaputtem Symbol.
    $("now-art").addEventListener("error", () => { $("now-art").hidden = true; });
    setInterval(() => { if (state) tickProgress(); }, 1000);

    if (!session) {
      show("join");
      return;
    }
    try {
      await refreshState();
      startSync();
    } catch (err) {
      if (err.code === "invalid_session") resetSession();
      else if (err.code === "inactive") show("off");
      else {
        show("join");
        toast(messageFor(err));
      }
    }
  }

  boot();
})();
