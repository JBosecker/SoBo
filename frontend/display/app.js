"use strict";
(() => {
  // Same URL as the guest page (webhook/cloudhook) with ?view=display; everything via POST.
  const ENDPOINT = location.href.split("#")[0];
  // The key lives in the fragment: browsers never send it, so the relay and HA never see it.
  const KEY = new URLSearchParams(location.hash.slice(1)).get("key") || "";
  const POLL_INTERVAL = 5000;
  const DENIED_RETRY = 30000;
  const LONG_POLL_RETRY_AFTER = 3 * 60 * 1000;
  const MIN_WAIT = 5;
  const IDLE_AFTER = 4000;

  const $ = (id) => document.getElementById(id);
  const views = ["loading", "denied", "off", "main"];

  // ------------------------------------------------------------------ texts (en is the default, de is a translation)

  const I18N = {
    en: {
      connecting: "Connecting to the jukebox …",
      denied_title: "This display link does not work (any more).",
      denied_text: "Open the party display again from the SoBo page in Home Assistant (Guest access).",
      off_title: "The jukebox is off right now.",
      off_text: "This screen comes back by itself as soon as the party starts.",
      now_label: "Now playing",
      paused_label: "Paused",
      nothing_yet: "Nothing yet",
      first_song: "Scan the code and request the first song.",
      queue_title: "Coming up",
      queue_empty: "No requests yet. Scan the code and suggest the first song!",
      frozen: "Queue paused",
      next_pill: "Up next",
      from_playlist: "From the party playlist",
      pinned: "Pinned by the host",
      votes_label: "{n} votes",
      join_title: "Request a song!",
      join_text: "Scan with your phone camera, enter a name, search for a song and suggest it.",
      code_label: "Code: ",
      qr_label: "QR code for the guest page",
      fullscreen: "Full screen",
    },
    de: {
      connecting: "Verbinde mit der Jukebox …",
      denied_title: "Dieser Display-Link funktioniert nicht (mehr).",
      denied_text: "Öffne das Party-Display noch einmal über die SoBo-Seite in Home Assistant (Gastzugang).",
      off_title: "Die Jukebox ist gerade aus.",
      off_text: "Dieser Bildschirm kommt von selbst zurück, sobald die Party beginnt.",
      now_label: "Läuft gerade",
      paused_label: "Pausiert",
      nothing_yet: "Noch nichts",
      first_song: "Scanne den Code und wünsch dir den ersten Song.",
      queue_title: "Demnächst",
      queue_empty: "Noch keine Wünsche. Scanne den Code und schlag den ersten Song vor!",
      frozen: "Warteschlange angehalten",
      next_pill: "Als Nächstes",
      from_playlist: "Aus der Party-Playlist",
      pinned: "Vom Gastgeber angepinnt",
      votes_label: "{n} Stimmen",
      join_title: "Wünsch dir einen Song!",
      join_text: "Mit der Handykamera scannen, Namen eingeben, Song suchen und vorschlagen.",
      code_label: "Code: ",
      qr_label: "QR-Code für die Gästeseite",
      fullscreen: "Vollbild",
    },
  };

  /** First supported language from the browser's preferences (fallback: English). */
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

  // ------------------------------------------------------------------ state

  let state = null;
  let version = 0;
  let epoch = null; // changes when the app restarts (its version counter starts at 0 again)
  let receivedAt = 0;
  let qrRows = "";
  let brokenArt = ""; // cover that failed to load: do not show it again on every update

  // ------------------------------------------------------------------ network

  class ApiError extends Error {
    constructor(status, code) {
      super(code);
      this.status = status;
      this.code = code;
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
        body: JSON.stringify(Object.assign({ action: "display", key: KEY }, payload)),
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
    if (!response.ok || body.ok === false) throw new ApiError(response.status, body.error || "network");
    return body;
  }

  // ------------------------------------------------------------------ rendering

  function show(name) {
    for (const v of views) $("view-" + v).hidden = v !== name;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function applyState(next) {
    if (!next) return;
    // Answers can arrive out of order: never replace a newer state with an older one.
    if (state && next.epoch === epoch && (next.version || 0) < version) return;
    state = next;
    epoch = next.epoch || null;
    version = next.version || 0;
    receivedAt = Date.now();
    if (!next.active) {
      show("off");
      return;
    }
    show("main");
    renderNow();
    renderQueue();
    renderJoin();
  }

  function renderNow() {
    const now = state.now_playing;
    const art = $("now-art");
    $("now-label").textContent = t(now && state.state === "paused" ? "paused_label" : "now_label");
    $("now-title").textContent = now ? now.title : t("nothing_yet");
    $("now-artist").textContent = now ? now.artist : t("first_song");
    if (now && now.art && now.art !== brokenArt) {
      if (art.getAttribute("src") !== now.art) art.src = now.art;
      art.hidden = false;
    } else {
      art.hidden = true;
      art.removeAttribute("src");
    }
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
    $("now-bar").style.width = (fraction * 100).toFixed(2) + "%";
  }

  function row(track, rank, extraClass, note) {
    const li = el("li", "row" + (extraClass ? " " + extraClass : ""));
    li.append(el("span", "rank", rank));
    const art = el("div", "art");
    if (track.art) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = track.art;
      img.addEventListener("error", () => img.remove());
      art.append(img);
    }
    li.append(art);
    const text = el("div", "row-text");
    text.append(el("span", "row-title", track.title));
    text.append(el("span", "row-sub", track.artist || ""));
    if (note) text.append(el("span", "row-note", note));
    li.append(text);
    return li;
  }

  function votes(item) {
    const badge = el("span", "votes");
    badge.append(el("span", "arrow", "▲"));
    badge.append(el("span", "count", String(item.votes || 0)));
    badge.setAttribute("aria-label", t("votes_label", { n: item.votes || 0 }));
    return badge;
  }

  function renderQueue() {
    const rows = [];
    const next = state.next;
    if (next) {
      const li = row(next, "", "next", next.fallback ? t("from_playlist") : null);
      li.append(el("span", "pill next-pill", t("next_pill")));
      rows.push(li);
    }
    (state.queue || []).forEach((item, index) => {
      const note = item.pinned ? t("pinned") : item.fallback ? t("from_playlist") : null;
      const li = row(item, String(index + 1), item.fallback ? "fallback" : "", note);
      li.append(votes(item));
      rows.push(li);
    });
    $("queue-list").replaceChildren(...rows);
    $("queue-empty").hidden = rows.length > 0;
    $("frozen").hidden = !state.frozen;
  }

  function renderJoin() {
    const join = state.join;
    $("join").hidden = !join;
    $("view-main").classList.toggle("no-join", !join);
    if (!join) return;
    $("join-title").textContent = join.title || t("join_title");
    $("join-text").textContent = join.text || t("join_text");
    const code = $("join-code");
    code.hidden = !join.code;
    if (join.code) code.replaceChildren(el("span", "", t("code_label")), el("span", "code", join.code));
    const rows = (join.qr || []).join("\n");
    if (rows !== qrRows) {
      qrRows = rows;
      drawQr();
    }
  }

  /** Draw the QR code from the modules SoBo sends (rows of "1"/"0"); the white card is the quiet zone. */
  function drawQr() {
    const canvas = $("qr");
    const rows = qrRows ? qrRows.split("\n") : [];
    const size = rows.length;
    if (!size) return;
    const pixels = Math.max(size, Math.round(canvas.clientWidth * (window.devicePixelRatio || 1)));
    const scale = Math.max(1, Math.floor(pixels / size));
    canvas.width = canvas.height = size * scale;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#000";
    rows.forEach((line, y) => {
      for (let x = 0; x < size; x++) if (line[x] === "1") ctx.fillRect(x * scale, y * scale, scale, scale);
    });
  }

  // ------------------------------------------------------------------ live updates
  // Long polling through the cloudhook, falling back to normal polling on problems (plan 4.4).

  const sync = { mode: "long", waitSeconds: null, failures: 0, pollingSince: 0, controller: null };

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
    const body = await api({});
    applyState(body.state);
  }

  async function longPollOnce() {
    const payload = { since: version };
    if (epoch) payload.epoch = epoch;
    if (sync.waitSeconds) payload.timeout = sync.waitSeconds;
    const expected = (sync.waitSeconds || 20) * 1000;
    const started = Date.now();
    sync.controller = new AbortController();
    try {
      const body = await api(payload, { signal: sync.controller.signal, timeoutMs: expected + 15000 });
      sync.failures = 0;
      if (body.changed) {
        applyState(body.state);
        await sleep(1000); // a screen needs no more than one update per second
      } else {
        version = Math.max(version, body.version || 0);
      }
      if (body.mode === "poll") switchToPolling();
    } catch (err) {
      if (document.hidden) return; // aborted on purpose
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
      if (err.status && err.status < 500 && err.status !== 429) throw err;
      sync.failures += 1;
    }
    await sleep(jitter(POLL_INTERVAL * Math.min(4, 1 + sync.failures)));
    if (Date.now() - sync.pollingSince > LONG_POLL_RETRY_AFTER) {
      sync.mode = "long";
      sync.failures = 0;
    }
  }

  async function syncLoop() {
    // A screen runs all evening: it never gives up, it only waits longer.
    for (;;) {
      if (document.hidden) {
        await whenVisible();
        version = 0; // answer right away with the current state
        continue;
      }
      try {
        if (state === null || sync.mode === "poll") {
          if (state === null) await refreshState();
          else await pollOnce();
        } else {
          await longPollOnce();
        }
      } catch (err) {
        if (err.code === "display_denied") {
          // Display switched off or a new link: keep asking, it may be switched on again.
          state = null;
          show("denied");
          await sleep(jitter(DENIED_RETRY));
        } else {
          await sleep(jitter(POLL_INTERVAL));
        }
      }
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && sync.controller) sync.controller.abort();
    if (!document.hidden) keepAwake();
  });

  // ------------------------------------------------------------------ screen

  let wakeLock = null;

  /** Keep a tablet from dimming (only over HTTPS, where browsers offer the Wake Lock API). */
  async function keepAwake() {
    if (!("wakeLock" in navigator) || wakeLock) return;
    try {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => { wakeLock = null; });
    } catch (e) {
      wakeLock = null;
    }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  }

  function setupScreen() {
    const button = $("fullscreen");
    const canFullscreen = Boolean(document.fullscreenEnabled);
    const update = () => { button.hidden = !canFullscreen || Boolean(document.fullscreenElement); };
    update();
    document.addEventListener("fullscreenchange", update);
    button.addEventListener("click", () => { toggleFullscreen(); keepAwake(); });
    document.addEventListener("keydown", (event) => {
      if (event.key === "f" || event.key === "F") toggleFullscreen();
    });
    // Hide the cursor and the button when nobody touches the screen.
    let idleTimer = 0;
    const active = () => {
      document.body.classList.remove("idle");
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => document.body.classList.add("idle"), IDLE_AFTER);
    };
    for (const name of ["mousemove", "pointerdown", "keydown"]) document.addEventListener(name, active, { passive: true });
    active();
    window.addEventListener("resize", drawQr);
    keepAwake();
  }

  // ------------------------------------------------------------------ start

  function boot() {
    applyStaticTexts();
    setupScreen();
    $("now-art").addEventListener("error", () => {
      brokenArt = $("now-art").getAttribute("src") || "";
      $("now-art").hidden = true;
    });
    setInterval(() => { if (state && state.active) tickProgress(); }, 1000);
    if (KEY.length < 32) {
      show("denied");
      return;
    }
    syncLoop();
  }

  boot();
})();
