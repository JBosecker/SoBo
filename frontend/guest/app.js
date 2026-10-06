"use strict";
(() => {
  // The page only talks to its own URL (webhook/cloudhook), everything via POST.
  const ENDPOINT = location.href.split("#")[0];
  const SESSION_KEY = "sobo.session";
  const RING = 295.3;
  const POLL_INTERVAL = 5000;
  const LONG_POLL_RETRY_AFTER = 3 * 60 * 1000;
  const MIN_WAIT = 5;

  const $ = (id) => document.getElementById(id);
  const views = ["loading", "join", "off", "main"];

  // ------------------------------------------------------------------ texts (en is the default, de is a translation)

  const I18N = {
    en: {
      connecting: "Connecting to the jukebox …",
      join_title: "What should play next?",
      join_intro: "Find songs, suggest them and vote for other guests' picks.",
      join_name: "Your name at the party",
      join_code: "Code from the host",
      join_button: "Join in",
      off_title: "The jukebox is off right now.",
      off_text: "As soon as the host turns it on, things continue here.",
      now_label: "Now playing",
      nothing_yet: "Nothing yet",
      first_song: "Suggest the first song.",
      next_line: "After that: {title} by {artist}",
      search_label: "Search for a song or artist",
      done: "Done",
      results_label: "Search results",
      queue_label: "Queue",
      queue_title: "Requested next",
      queue_empty: "No requests yet. Search for a song above and suggest it.",
      cover_note: "Covers are loaded directly from Apple.",
      minutes: "{m}:{s} min",
      seconds: "{s} s",
      failed: "That did not work. Please try again.",
      possible_again: " Possible again in {time}.",
      voted_label: "You voted for {title}",
      vote_label: "Vote for {title}",
      your_request: "Your request",
      pinned: "Pinned by the host",
      vote_hint: "Tap ▲ to vote for a song. The most votes play first.",
      playlist_title: "Then from the party playlist",
      me_one: "{name}, you have {n} vote left.",
      me_other: "{name}, you have {n} votes left.",
      next_vote: " The next one comes in {time}.",
      me_blocked: "You cannot take part right now.",
      suggested: "Suggested. Now all you need is votes.",
      searching: "Searching …",
      no_results: "Nothing found for “{q}”.",
      already_in: "Already in",
      blocked_default: "Blocked",
      request: "Request",
      suggest_label: "Suggest {title}",
      enter_name: "Please enter your name.",
      messages: {
        too_long: "This song is too long for this party.",
        explicit: "Songs with explicit content are turned off today.",
        blocked_content: "This song is blocked today.",
        recently_played: "This song has just played. Try again later.",
        artist_cooldown: "Something by this artist has just played.",
        no_votes_left: "You have used up your votes.",
        no_suggestions_left: "You have suggested enough songs for now.",
        already_voted: "You have already voted for this song.",
        already_next: "This song is already coming up next.",
        now_playing: "This song is playing right now.",
        locked: "This song is already fixed and plays next.",
        frozen: "The queue is frozen right now.",
        blocked: "You cannot suggest or vote for songs right now.",
        too_many_guests: "The party is full. Try again in a moment.",
        busy: "It's busy right now. Try again in a moment.",
        slow_down: "A bit slower, please. Try again in a moment.",
        unknown_result: "The search has expired. Please search again.",
        unknown_item: "This song is no longer in the queue.",
        sonos_unavailable: "The jukebox is not responding right now.",
        unavailable: "The jukebox is not responding right now.",
        not_configured: "The jukebox is not fully set up yet.",
        bad_nickname: "Please enter a name with letters or numbers.",
        wrong_code: "The code is wrong. Ask the host.",
      },
      blocked_labels: {
        too_long: "Too long",
        explicit: "Explicit",
        blocked_content: "Blocked",
        recently_played: "Just played",
        artist_cooldown: "Later",
      },
    },
    de: {
      connecting: "Verbinde mit der Jukebox …",
      join_title: "Was soll als Nächstes laufen?",
      join_intro: "Such dir Songs aus, schlag sie vor und stimm für die anderer Gäste ab.",
      join_name: "Dein Name auf der Party",
      join_code: "Code vom Gastgeber",
      join_button: "Mitmachen",
      off_title: "Die Jukebox ist gerade aus.",
      off_text: "Sobald der Gastgeber sie einschaltet, geht es hier weiter.",
      now_label: "Läuft gerade",
      nothing_yet: "Noch nichts",
      first_song: "Schlag den ersten Song vor.",
      next_line: "Danach: {title} von {artist}",
      search_label: "Song oder Interpret suchen",
      done: "Fertig",
      results_label: "Suchergebnisse",
      queue_label: "Warteschlange",
      queue_title: "Als Nächstes gewünscht",
      queue_empty: "Noch keine Wünsche. Such oben nach einem Song und schlag ihn vor.",
      cover_note: "Cover werden direkt von Apple geladen.",
      minutes: "{m}:{s} Min.",
      seconds: "{s} Sek.",
      failed: "Das hat nicht geklappt. Versuch es noch mal.",
      possible_again: " Wieder möglich in {time}",
      voted_label: "Du hast für {title} gestimmt",
      vote_label: "Für {title} stimmen",
      your_request: "Dein Wunsch",
      pinned: "Vom Gastgeber angepinnt",
      vote_hint: "Tippe auf ▲, um für einen Song zu stimmen. Die meisten Stimmen laufen zuerst.",
      playlist_title: "Danach aus der Party-Playlist",
      me_one: "{name}, du hast noch {n} Stimme.",
      me_other: "{name}, du hast noch {n} Stimmen.",
      next_vote: " Die nächste gibt es in {time}",
      me_blocked: "Du kannst gerade nicht mitmachen.",
      suggested: "Vorgeschlagen. Jetzt brauchst du nur noch Stimmen.",
      searching: "Suche …",
      no_results: "Nichts gefunden für „{q}“.",
      already_in: "Schon dabei",
      blocked_default: "Gesperrt",
      request: "Wünschen",
      suggest_label: "{title} vorschlagen",
      enter_name: "Bitte gib deinen Namen ein.",
      messages: {
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
      },
      blocked_labels: {
        too_long: "Zu lang",
        explicit: "Explizit",
        blocked_content: "Gesperrt",
        recently_played: "Lief gerade",
        artist_cooldown: "Später",
      },
    },
  };

  /** First supported language from the phone's preferences (fallback: English). */
  function pickLanguage() {
    const wanted = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || "en"];
    for (const tag of wanted) {
      const base = String(tag).toLowerCase().split("-")[0];
      if (I18N[base]) return base;
    }
    return "en";
  }

  const LANG = pickLanguage();
  const TEXT = I18N[LANG];
  const MESSAGES = TEXT.messages;
  const BLOCKED_LABEL = TEXT.blocked_labels;

  /** Translate `key`, filling `{placeholders}` from `vars`. */
  function t(key, vars) {
    const template = TEXT[key] !== undefined ? TEXT[key] : I18N.en[key];
    if (template === undefined) return key;
    return String(template).replace(/\{(\w+)\}/g, (match, name) => (vars && vars[name] !== undefined ? String(vars[name]) : match));
  }

  function applyStaticTexts() {
    document.documentElement.lang = LANG;
    for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
    for (const node of document.querySelectorAll("[data-i18n-attr]")) {
      for (const pair of node.dataset.i18nAttr.split(";")) {
        const [attr, key] = pair.split(":");
        node.setAttribute(attr, t(key));
      }
    }
  }

  // ------------------------------------------------------------------ storage

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

  // ------------------------------------------------------------------ state

  let session = store.get(SESSION_KEY);
  let state = null;
  let version = 0;
  let receivedAt = 0;
  let searchTimer = 0;
  let searchSeq = 0;
  let toastTimer = 0;

  // ------------------------------------------------------------------ network

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

  // ------------------------------------------------------------------ rendering

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
    return m > 0 ? t("minutes", { m, s: String(s % 60).padStart(2, "0") }) : t("seconds", { s });
  }

  function messageFor(err) {
    let text = MESSAGES[err.code] || t("failed");
    if (err.retryAfter && (err.code === "no_votes_left" || err.code === "no_suggestions_left")) {
      text += t("possible_again", { time: minutes(err.retryAfter) });
    }
    return text;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  /** One row like in Apple Music: cover, title, artist (+ optional tag), action on the right. */
  function row(track, extraClass, tag) {
    const li = el("li", "row" + (extraClass ? " " + extraClass : ""));
    const art = el("div", "art");
    if (track.art) {
      const img = document.createElement("img");
      img.alt = "";
      img.loading = "lazy";
      img.src = track.art;
      img.addEventListener("error", () => img.remove());
      art.append(img);
    }
    li.append(art);
    const text = el("div", "row-text");
    text.append(el("span", "row-title", track.title));
    const sub = el("span", "row-sub");
    if (tag) sub.append(el("span", "tag", tag));
    sub.append(document.createTextNode(track.artist || ""));
    text.append(sub);
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
    $("now-title").textContent = now ? now.title : t("nothing_yet");
    $("now-artist").textContent = now ? now.artist : t("first_song");
    if (now && now.art) {
      if (art.getAttribute("src") !== now.art) art.src = now.art;
      art.hidden = false;
    } else {
      art.hidden = true;
      art.removeAttribute("src");
    }
    const next = state.next;
    $("next-line").hidden = !next;
    $("next-line").textContent = next ? t("next_line", { title: next.title, artist: next.artist }) : "";
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
    button.append(el("span", "arrow", "▲"));
    button.append(el("span", "count", String(item.votes)));
    button.setAttribute(
      "aria-label",
      t(item.voted ? "voted_label" : "vote_label", { title: item.title })
    );
    button.disabled = Boolean(item.voted);
    button.addEventListener("click", () => vote(item.id, button));
    return button;
  }

  function renderQueue() {
    const items = state.queue || [];
    const requests = items.filter((item) => !item.fallback);
    const playlist = items.filter((item) => item.fallback);
    $("queue-list").replaceChildren(
      ...requests.map((item) => {
        const tag = item.mine ? t("your_request") : item.pinned ? t("pinned") : null;
        const li = row(item, [item.mine && "mine", item.pinned && "pinned"].filter(Boolean).join(" "), tag);
        li.append(voteButton(item));
        return li;
      })
    );
    // Base playlist: plays once the requests are through. A vote makes it a request.
    $("playlist-list").replaceChildren(
      ...playlist.map((item) => {
        const li = row(item, "fallback");
        li.append(voteButton(item));
        return li;
      })
    );
    $("playlist-title").hidden = playlist.length === 0;
    $("queue-empty").hidden = requests.length > 0;
  }

  function renderMe() {
    const me = state.me;
    if (!me) return;
    let line = t(me.votes_left === 1 ? "me_one" : "me_other", { name: me.nickname, n: me.votes_left });
    if (me.votes_left === 0 && me.votes_refill_in) line += t("next_vote", { time: minutes(me.votes_refill_in) });
    if (me.blocked) line = t("me_blocked");
    $("me-line").textContent = line;
    const covers = Boolean(state.now_playing && state.now_playing.art) || (state.queue || []).some((q) => q.art);
    $("cover-note").hidden = !covers;
  }

  // ------------------------------------------------------------------ actions

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
      toast(t("suggested"));
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

  // ------------------------------------------------------------------ search

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
    $("results-note").textContent = t("searching");
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
    $("results-note").textContent = results.length ? "" : t("no_results", { q });
    $("results-list").replaceChildren(...results.map(resultRow));
  }

  function resultRow(hit) {
    const li = row(hit, "", null);
    if (hit.album) li.querySelector(".row-sub").append(document.createTextNode(` · ${hit.album}`));
    let button;
    if (hit.queued) {
      const queued = (state.queue || []).find((q) => q.id === hit.queued);
      if (queued) {
        // Already requested: suggesting counts as a vote, so show the vote button right away.
        li.append(voteButton(queued));
        return li;
      }
      button = el("button", "vote blocked", t("already_in"));
      button.disabled = true;
    } else if (hit.blocked) {
      button = el("button", "vote blocked", BLOCKED_LABEL[hit.blocked] || t("blocked_default"));
      button.disabled = true;
      button.title = MESSAGES[hit.blocked] || "";
    } else {
      button = el("button", "vote add");
      button.append(el("span", "arrow", "+"));
      button.append(el("span", "count", t("request")));
      button.setAttribute("aria-label", t("suggest_label", { title: hit.title }));
      button.addEventListener("click", () => suggest(hit.id, button));
    }
    button.type = "button";
    li.append(button);
    return li;
  }

  // ------------------------------------------------------------------ join

  async function join(event) {
    event.preventDefault();
    const nickname = $("join-name").value.trim();
    const code = $("join-code").value.trim();
    const error = $("join-error");
    error.hidden = true;
    if (!nickname) {
      error.textContent = t("enter_name");
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

  // ------------------------------------------------------------------ live updates
  // Long polling through the cloudhook, falling back to normal polling on problems (plan 4.4).

  const sync = {
    running: false,
    mode: "long",
    waitSeconds: null, // null = the app's wait time
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
      else if (body.replaced) await sleep(jitter(5000)); // second tab with the same session
    } catch (err) {
      if (document.hidden) return; // aborted on purpose
      if (err.code === "invalid_session") throw err;
      if (err.status && err.status < 500 && err.status !== 429) throw err;
      // Network error or 5xx before the wait time ran out: the relay apparently does not hold that long.
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

  // ------------------------------------------------------------------ start

  async function boot() {
    applyStaticTexts();
    $("join-form").addEventListener("submit", join);
    $("search").addEventListener("input", onSearchInput);
    $("search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("search").value.trim();
      if (q.length >= 2) { clearTimeout(searchTimer); runSearch(q); }
    });
    $("search-clear").addEventListener("click", closeSearch);
    // Cover cannot be loaded (offline, blocked): better no image than a broken icon.
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
