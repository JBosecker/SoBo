"use strict";
(() => {
  // Alle Pfade relativ: Die Seite läuft hinter dem Ingress-Präfix von Home Assistant.
  const POLL_MS = 2000;
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------ Hilfen

  class ApiError extends Error {
    constructor(status, body) {
      super((body && (body.error || body.detail)) || `HTTP ${status}`);
      this.status = status;
      this.body = body;
    }
  }

  async function api(method, path, body) {
    const options = { method, headers: {}, cache: "no-store" };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    let data = null;
    if (response.status !== 204) {
      try { data = await response.json(); } catch (e) { data = null; }
    }
    if (!response.ok) throw new ApiError(response.status, data);
    return data;
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  let toastTimer = 0;
  function toast(text) {
    const node = $("toast");
    node.textContent = text;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 3500);
  }

  const store = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* egal */ } },
  };

  function ago(iso) {
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return "gerade eben";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `vor ${minutes} Min.`;
    return `vor ${Math.round(minutes / 60)} Std.`;
  }

  function clock(iso) {
    return new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });
  }

  function errorText(err) {
    const code = err.body && err.body.error;
    return ERRORS[code] || (err.status === 503 ? "Sonos antwortet gerade nicht." : "Das hat nicht geklappt.");
  }

  const ERRORS = {
    no_speaker: "Erst einen Lautsprecher wählen und speichern.",
    unknown_item: "Den Song gibt es nicht mehr in der Warteschlange.",
    unknown_guest: "Diesen Gast gibt es nicht mehr.",
    integration_not_connected: "Die SoBo-Integration ist nicht verbunden.",
    sonos_unavailable: "Sonos antwortet gerade nicht.",
  };

  const STATES = {
    inactive: ["Aus", ""],
    idle: ["Bereit, wartet auf Wünsche", "on"],
    playing_guest: ["Spielt Gastwünsche", "on"],
    playing_fallback: ["Spielt Basis-Playlist", "on"],
    paused: ["Pausiert", ""],
    manual_override: ["Sonos-App hat übernommen", "warn"],
    error: ["Störung", "warn"],
  };

  // ------------------------------------------------------------------ Reiter

  const TABS = ["live", "access", "settings", "log"];
  let activeTab = "live";

  function selectTab(name) {
    activeTab = name;
    for (const tab of TABS) {
      $("tab-" + tab).setAttribute("aria-selected", String(tab === name));
      $("tab-" + tab).tabIndex = tab === name ? 0 : -1;
      $("panel-" + tab).hidden = tab !== name;
    }
    store.set("sobo.tab", name);
    if (name === "settings") loadSonosLists();
    if (name === "log") loadLog();
    if (name === "live") loadGuests();
  }

  // ------------------------------------------------------------------ Status / Live

  let status = null;
  let lastRendered = {};

  function changed(key, value) {
    const json = JSON.stringify(value);
    if (lastRendered[key] === json) return false;
    lastRendered[key] = json;
    return true;
  }

  async function refreshStatus() {
    try {
      status = await api("GET", "api/status");
    } catch (err) {
      showBanner("Keine Verbindung zur SoBo-App.", null);
      return;
    }
    renderTop();
    renderLive();
    renderAccess();
    if (activeTab === "live") loadGuests();
  }

  function renderTop() {
    const [label, tone] = STATES[status.state] || [status.state, ""];
    const pill = $("state-pill");
    pill.textContent = label;
    pill.className = "pill" + (tone ? " " + tone : "");
    $("power").checked = status.active;
    let power = status.active ? "Jukebox an" : "Jukebox aus";
    if (status.active && !status.effectively_active) power = "An, außerhalb des Zeitfensters";
    $("power-label").textContent = power;

    if (status.state === "manual_override") {
      const what = status.override_info ? ` (${status.override_info})` : "";
      showBanner(`In der Sonos-App wurde etwas anderes gestartet${what}. SoBo wartet.`, {
        label: "Wieder übernehmen",
        run: () => act("POST", "api/control/resume", undefined, "SoBo hat wieder übernommen."),
      });
    } else if (status.last_error === "no_speaker" && status.active) {
      showBanner("Kein Lautsprecher gewählt. Ohne Lautsprecher kann SoBo nichts abspielen.", {
        label: "Lautsprecher wählen",
        run: () => selectTab("settings"),
      });
    } else if (status.last_error && status.active) {
      showBanner(`Sonos meldet eine Störung: ${status.last_error}`, null);
    } else if (status.fallback_error && status.active) {
      showBanner(`Die Basis-Playlist lässt sich nicht laden: ${status.fallback_error}`, null);
    } else {
      $("banner").hidden = true;
    }
  }

  let bannerAction = null;
  function showBanner(text, action) {
    $("banner").hidden = false;
    $("banner-text").textContent = text;
    bannerAction = action;
    $("banner-action").hidden = !action;
    if (action) $("banner-action").textContent = action.label;
  }

  function origin(item) {
    if (item.origin === "fallback") return "Aus der Basis-Playlist";
    if (item.submitted_by) return `Wunsch von ${item.submitted_by}`;
    return "";
  }

  function renderLive() {
    const now = status.now_playing;
    $("now-title").textContent = now ? now.title : "Nichts";
    $("now-meta").textContent = now ? [now.artist, origin(now)].filter(Boolean).join(", ") : "";
    const art = $("now-art");
    if (now && now.art && now.art.startsWith("https://")) {
      if (art.getAttribute("src") !== now.art) art.src = now.art;
      art.hidden = false;
    } else {
      art.hidden = true;
    }
    const playback = status.playback;
    const fraction = playback && playback.duration ? Math.min(1, (playback.position || 0) / playback.duration) : 0;
    $("now-bar").style.width = `${Math.round(fraction * 100)}%`;
    const next = status.next;
    $("next-line").textContent = next
      ? `Als Nächstes: ${next.title} von ${next.artist}${origin(next) ? ` (${origin(next)})` : ""}`
      : "Als Nächstes: noch offen";

    const freeze = $("freeze");
    freeze.setAttribute("aria-pressed", String(status.frozen));
    freeze.textContent = status.frozen ? "Warteschlange angehalten" : "Warteschlange anhalten";

    if (changed("queue", status.queue)) renderQueue(status.queue);
    if (changed("history", status.history)) {
      $("history-heading").hidden = status.history.length === 0;
      $("history").replaceChildren(
        ...status.history.slice(0, 8).map((item) => el("li", { text: `${item.title} – ${item.artist}` }))
      );
    }
  }

  function renderQueue(queue) {
    $("queue-empty").hidden = queue.length > 0;
    $("queue-count").textContent = queue.length ? `${queue.length} ${queue.length === 1 ? "Wunsch" : "Wünsche"}` : "";
    $("queue").replaceChildren(
      ...queue.map((item) =>
        el(
          "li",
          { class: "strip" + (item.pinned ? " pinned" : "") },
          el("div", { class: "strip-votes" }, el("b", { text: item.votes }), el("span", { text: item.votes === 1 ? "Stimme" : "Stimmen" })),
          el(
            "div",
            { class: "strip-text" },
            el("span", { class: "strip-title", text: item.title }),
            el("span", { class: "strip-artist", text: item.artist || " " }),
            el("span", { class: "strip-meta", text: [origin(item), ago(item.submitted_at)].filter(Boolean).join(", ") })
          ),
          el(
            "div",
            { class: "strip-actions" },
            el("button", {
              type: "button",
              class: "button",
              "aria-pressed": String(item.pinned),
              text: item.pinned ? "Angepinnt" : "Anpinnen",
              title: "Angepinnte Songs kommen vor allen anderen dran.",
              onclick: () => act("POST", `api/queue/${encodeURIComponent(item.id)}/pin`, { pinned: !item.pinned }),
            }),
            el("button", {
              type: "button",
              class: "button danger",
              text: "Entfernen",
              "aria-label": `${item.title} entfernen`,
              onclick: () => act("POST", `api/queue/${encodeURIComponent(item.id)}/remove`, undefined, "Entfernt."),
            })
          )
        )
      )
    );
  }

  let guestsLoading = false;
  async function loadGuests() {
    if (guestsLoading) return;
    guestsLoading = true;
    try {
      const guests = await api("GET", "api/guests");
      if (!changed("guests", guests)) return;
      $("guests-empty").hidden = guests.length > 0;
      $("guest-count").textContent = guests.length ? String(guests.length) : "";
      $("guests").replaceChildren(
        ...guests.map((guest) =>
          el(
            "li",
            {},
            el(
              "div",
              {},
              el("div", { class: "guest-name" + (guest.blocked ? " blocked" : ""), text: guest.nickname }),
              el("div", {
                class: "guest-meta",
                text: `${guest.suggestions} ${guest.suggestions === 1 ? "Wunsch" : "Wünsche"}, ${guest.votes_left} Stimmen übrig, aktiv ${ago(guest.last_seen)}`,
              })
            ),
            el("button", {
              type: "button",
              class: "button" + (guest.blocked ? "" : " danger"),
              text: guest.blocked ? "Entsperren" : "Sperren",
              "aria-label": `${guest.nickname} ${guest.blocked ? "entsperren" : "sperren"}`,
              onclick: () => act("POST", `api/guests/${encodeURIComponent(guest.id)}/block`, { blocked: !guest.blocked }),
            })
          )
        )
      );
    } catch (err) {
      /* nächster Versuch beim nächsten Abruf */
    } finally {
      guestsLoading = false;
    }
  }

  async function act(method, path, body, success) {
    try {
      await api(method, path, body);
      if (success) toast(success);
    } catch (err) {
      toast(errorText(err));
    }
    lastRendered = {};
    await refreshStatus();
  }

  // ------------------------------------------------------------------ Gastzugang

  function renderAccess() {
    const access = status.guest_access;
    const url = access.url || access.local_url;
    const which = access.url ? "cloud" : "local";
    const qr = $("qr");
    if (url) {
      const src = `api/guest-access/qr.svg?which=${which}&u=${encodeURIComponent(url)}`;
      if (qr.getAttribute("src") !== src) {
        qr.src = src;
        $("print-qr").src = src;
      }
      qr.hidden = false;
      $("qr-missing").hidden = true;
    } else {
      qr.hidden = true;
      $("qr-missing").hidden = false;
      $("qr-missing").textContent = "Noch kein Gast-Link.";
    }
    $("guest-url").textContent = url || "–";
    $("copy-url").disabled = !url;
    $("print").disabled = !url;

    let explain;
    if (!access.integration_connected) {
      explain = "Die SoBo-Integration ist nicht verbunden. Installiere sie über HACS und richte sie in Home Assistant unter Geräte & Dienste ein.";
    } else if (access.url) {
      explain = "Gäste scannen den QR-Code mit der Handykamera. Der Link funktioniert überall, auch ohne euer WLAN, und verrät nichts über deine Home-Assistant-Adresse.";
    } else if (access.local_url) {
      explain = "Nabu Casa ist nicht verbunden. Dieser Link funktioniert nur im eigenen WLAN.";
    } else {
      explain = "Die Integration hat noch keinen Link gemeldet.";
    }
    $("access-explain").textContent = explain;
    $("fact-integration").textContent = access.integration_connected ? "Verbunden" : "Nicht verbunden";
    $("fact-cloud").textContent =
      access.cloud_connected === true ? "Verbunden" : access.cloud_connected === false ? "Nicht verbunden" : "Nicht eingerichtet";
    const rotate = $("rotate");
    rotate.disabled = !access.integration_connected || access.rotation_pending;
    rotate.textContent = access.rotation_pending ? "Wird erneuert …" : "Gastzugang erneuern";
  }

  async function copyUrl() {
    const text = $("guest-url").textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast("Link kopiert.");
    } catch (err) {
      const range = document.createRange();
      range.selectNodeContents($("guest-url"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      toast("Link markiert. Mit Strg/Cmd+C kopieren.");
    }
  }

  function printSheet() {
    const code = settings && settings.guest_access.presence_code;
    $("print-code").hidden = !code;
    $("print-code").textContent = code ? `Code: ${code}` : "";
    window.print();
  }

  // ------------------------------------------------------------------ Einstellungen

  let settings = null;
  const lists = { speakers: null, accounts: null, sources: null, accountsError: null, sourcesError: null };

  const SECTIONS = {
    speaker: {
      title: "Lautsprecher",
      intro: "Auf welchem Sonos läuft die Party? Gäste können den Raum nicht wählen.",
      fields: [
        { path: "speaker.coordinator_uid", label: "Lautsprecher", type: "speaker" },
        { path: "speaker.members", label: "Mitspielende Lautsprecher", type: "members", wide: true },
        { path: "speaker.start_volume", label: "Startlautstärke", type: "number", min: 0, max: 100, nullable: true, help: "Beim Einschalten. Leer lassen, um die Lautstärke nicht zu ändern." },
        { path: "speaker.max_volume", label: "Maximale Lautstärke", type: "number", min: 0, max: 100, help: "Wird höher gedreht, regelt SoBo wieder herunter." },
      ],
    },
    music: {
      title: "Musik",
      fields: [
        { path: "account_id", label: "Apple-Music-Konto", type: "account" },
        { path: "fallback.source_id", label: "Basis-Playlist", type: "source", help: "Läuft, solange keine Wünsche da sind." },
        { path: "fallback.shuffle", label: "Basis-Playlist zufällig abspielen", type: "checkbox" },
      ],
    },
    votes: {
      title: "Stimmen",
      fields: [
        { path: "votes.votes_per_window", label: "Stimmen pro Gast", type: "number", min: 1, max: 100 },
        { path: "votes.window_minutes", label: "Zeitraum in Minuten", type: "number", min: 1, max: 1440, help: "Eine verbrauchte Stimme kommt nach dieser Zeit zurück." },
        { path: "votes.suggestion_costs_vote", label: "Ein Vorschlag kostet eine Stimme", type: "checkbox" },
      ],
    },
    limits: {
      title: "Regeln für Wünsche",
      fields: [
        { path: "limits.suggestions_per_window", label: "Vorschläge pro Gast", type: "number", min: 0, max: 100 },
        { path: "limits.suggestion_window_minutes", label: "Zeitraum für Vorschläge in Minuten", type: "number", min: 1, max: 1440 },
        { path: "limits.max_track_seconds", label: "Maximale Songlänge in Minuten", type: "number", min: 0.5, max: 180, step: 0.5, scale: 60 },
        { path: "limits.track_cooldown_minutes", label: "Sperrzeit für denselben Song in Minuten", type: "number", min: 0, max: 1440 },
        { path: "limits.artist_cooldown_minutes", label: "Sperrzeit für denselben Interpreten in Minuten", type: "number", min: 0, max: 1440, help: "0 schaltet die Sperre aus." },
        { path: "limits.explicit_filter", label: "Songs mit explizitem Inhalt ausschließen", type: "checkbox", help: "Greift nur, wenn Apple Music die Angabe liefert." },
        { path: "limits.blocklist", label: "Sperrliste", type: "lines", wide: true, help: "Ein Eintrag pro Zeile. Passt auf Titel, Interpret oder Album." },
      ],
    },
    schedule: {
      title: "Zeitfenster",
      fields: [
        { path: "schedule.enabled", label: "Nur in einem Zeitfenster für Gäste offen", type: "checkbox" },
        { path: "schedule.start", label: "Beginn", type: "time" },
        { path: "schedule.end", label: "Ende", type: "time", help: "Über Mitternacht geht auch, z. B. 20:00 bis 02:00." },
        { path: "timezone", label: "Zeitzone", type: "text", help: "Zum Beispiel Europe/Berlin." },
      ],
    },
    guest_access: {
      title: "Einstellungen zum Gastzugang",
      fields: [
        { path: "guest_access.presence_code", label: "Anwesenheitscode", type: "text", nullable: true, inputmode: "numeric", help: "4 bis 8 Ziffern, die du auf der Party bekannt gibst. Leer lassen für keinen Code." },
        { path: "guest_access.max_active_guests", label: "Höchstens aktive Gäste", type: "number", min: 1, max: 1000 },
        { path: "guest_access.session_hours", label: "Anmeldung gültig für Stunden", type: "number", min: 1, max: 72 },
        { path: "guest_access.joins_per_minute", label: "Neue Gäste pro Minute", type: "number", min: 1, max: 600, help: "Bremst Massenanmeldungen, falls der Link die Runde macht." },
        { path: "guest_access.long_poll_timeout", label: "Wartezeit für Live-Updates in Sekunden", type: "number", min: 5, max: 60 },
        { path: "guest_access.max_open_long_polls", label: "Gleichzeitige Live-Verbindungen", type: "number", min: 1, max: 2000, help: "Darüber fragen Handys alle paar Sekunden nach." },
        { path: "guest_access.show_covers", label: "Albumcover zeigen", type: "checkbox", help: "Die Handys laden Cover direkt von Apple." },
        { path: "guest_access.unregister_when_inactive", label: "Gast-Link abschalten, solange die Jukebox aus ist", type: "checkbox" },
      ],
    },
  };

  function getPath(obj, path) {
    return path.split(".").reduce((o, key) => (o == null ? undefined : o[key]), obj);
  }

  function setPath(obj, path, value) {
    const keys = path.split(".");
    let target = obj;
    for (const key of keys.slice(0, -1)) target = target[key];
    target[keys[keys.length - 1]] = value;
  }

  function fieldId(path) {
    return "f-" + path.replace(/\./g, "-");
  }

  function options(items, current, empty) {
    const nodes = [];
    if (empty) nodes.push(el("option", { value: "", text: empty, selected: !current }));
    let found = !current;
    for (const item of items) {
      if (item.value === current) found = true;
      nodes.push(el("option", { value: item.value, text: item.label, selected: item.value === current }));
    }
    if (!found) nodes.push(el("option", { value: current, text: `${current} (nicht gefunden)`, selected: true }));
    return nodes;
  }

  function renderField(field) {
    const id = fieldId(field.path);
    const value = getPath(settings, field.path);
    const help = field.help ? el("p", { class: "help", id: id + "-help", text: field.help }) : null;
    const error = el("p", { class: "error", id: id + "-error", hidden: true });
    const describedBy = [help && id + "-help", id + "-error"].filter(Boolean).join(" ");
    const wrap = (cls, ...children) => el("div", { class: "field " + cls + (field.wide ? " wide" : ""), "data-path": field.path }, ...children);

    switch (field.type) {
      case "checkbox":
        return wrap("check", el("input", { type: "checkbox", id, checked: Boolean(value), "aria-describedby": describedBy }), el("label", { for: id, text: field.label }), help, error);
      case "number": {
        const shown = value === null || value === undefined ? "" : field.scale ? value / field.scale : value;
        return wrap("", el("label", { for: id, text: field.label }), el("input", { type: "number", id, value: shown, min: field.min, max: field.max, step: field.step || 1, inputmode: "numeric", "aria-describedby": describedBy }), help, error);
      }
      case "time":
        return wrap("", el("label", { for: id, text: field.label }), el("input", { type: "time", id, value: String(value || "").slice(0, 5), "aria-describedby": describedBy }), help, error);
      case "text":
        return wrap("", el("label", { for: id, text: field.label }), el("input", { type: "text", id, value: value || "", inputmode: field.inputmode, autocomplete: "off", "aria-describedby": describedBy }), help, error);
      case "lines":
        return wrap("", el("label", { for: id, text: field.label }), el("textarea", { id, "aria-describedby": describedBy, text: (value || []).join("\n") }), help, error);
      case "speaker": {
        const speakers = lists.speakers;
        const select = el("select", { id, "aria-describedby": describedBy }, options((speakers || []).map((s) => ({ value: s.uid, label: `${s.name} (${s.ip})` })), value, speakers ? "Bitte wählen" : "Lautsprecher werden gesucht …"));
        const rescan = el("button", { type: "button", class: "button", text: "Erneut suchen", onclick: () => loadSonosLists(true) });
        return wrap("", el("label", { for: id, text: field.label }), el("div", { class: "row" }, select, rescan), help, error);
      }
      case "members": {
        const coordinator = getPath(settings, "speaker.coordinator_uid");
        const others = (lists.speakers || []).filter((s) => s.uid !== coordinator);
        const boxes = others.map((s) =>
          el("label", { class: "row" }, el("input", { type: "checkbox", value: s.uid, checked: (value || []).includes(s.uid) }), s.name)
        );
        return wrap("", el("fieldset", { id }, el("legend", { text: field.label }), boxes.length ? boxes : el("p", { class: "help", text: "Keine weiteren Lautsprecher gefunden." })), help, error);
      }
      case "account": {
        const accounts = lists.accounts || [];
        const hint = lists.accountsError || (lists.accounts && !accounts.length ? "Kein Apple-Music-Konto im Sonos-Haushalt gefunden." : null);
        return wrap("", el("label", { for: id, text: field.label }), el("select", { id, "aria-describedby": describedBy }, options(accounts.map((a) => ({ value: a.account_id, label: a.nickname || `${a.service} ${a.account_id}` })), value, "Bitte wählen")), hint ? el("p", { class: "help", text: hint }) : help, error);
      }
      case "source": {
        const sources = lists.sources || [];
        return wrap("", el("label", { for: id, text: field.label }), el("select", { id, "aria-describedby": describedBy }, options(sources.map((s) => ({ value: s.source_id, label: s.kind === "favorite" ? `${s.name} (Favorit)` : s.name })), value, "Keine")), lists.sourcesError ? el("p", { class: "help", text: lists.sourcesError }) : help, error);
      }
      default:
        throw new Error("Unbekannter Feldtyp " + field.type);
    }
  }

  function readField(field) {
    const node = $(fieldId(field.path));
    switch (field.type) {
      case "checkbox":
        return node.checked;
      case "number": {
        if (node.value.trim() === "") return field.nullable ? null : NaN;
        const number = Number(node.value);
        return field.scale ? Math.round(number * field.scale) : number;
      }
      case "lines":
        return node.value.split("\n").map((s) => s.trim()).filter(Boolean);
      case "members":
        return [...node.querySelectorAll("input:checked")].map((input) => input.value);
      case "text":
      case "time":
        return node.value.trim() === "" && field.nullable ? null : node.value.trim();
      default:
        return node.value === "" ? null : node.value;
    }
  }

  function renderSection(name) {
    const section = SECTIONS[name];
    const form = document.querySelector(`.settings-form[data-section="${name}"]`);
    const status = el("span", { class: "status", role: "status" });
    form.replaceChildren(
      ...[
        el("h2", { text: section.title }),
        section.intro ? el("p", { class: "intro", text: section.intro }) : null,
        el("div", { class: "fields" }, section.fields.map(renderField)),
        el("div", { class: "form-actions" }, el("button", { type: "submit", class: "button primary", text: "Speichern" }), status),
      ].filter(Boolean)
    );
    form.onsubmit = (event) => {
      event.preventDefault();
      saveSection(name, form, status);
    };
    if (name === "speaker") bindCoordinatorChange(form);
  }

  /** Nur einzelne Felder neu aufbauen (z. B. wenn Listen eintreffen) – andere Eingaben bleiben. */
  function refreshFields(name, paths) {
    const form = document.querySelector(`.settings-form[data-section="${name}"]`);
    for (const field of SECTIONS[name].fields) {
      if (!paths.includes(field.path)) continue;
      const current = form.querySelector(`[data-path="${CSS.escape(field.path)}"]`);
      if (current) current.replaceWith(renderField(field));
    }
    if (name === "speaker") bindCoordinatorChange(form);
  }

  function bindCoordinatorChange(form) {
    // Mitspieler-Liste hängt vom gewählten Lautsprecher ab.
    $(fieldId("speaker.coordinator_uid")).addEventListener("change", (event) => {
      const previous = settings;
      settings = structuredClone(settings);
      setPath(settings, "speaker.coordinator_uid", event.target.value || null);
      const fresh = renderField(SECTIONS.speaker.fields[1]);
      settings = previous;
      form.querySelector(`[data-path="speaker.members"]`).replaceWith(fresh);
    });
  }

  function renderSettings() {
    for (const name of Object.keys(SECTIONS)) renderSection(name);
  }

  function clearErrors(form) {
    for (const field of form.querySelectorAll(".field.invalid")) field.classList.remove("invalid");
    for (const error of form.querySelectorAll(".field .error")) {
      error.hidden = true;
      error.textContent = "";
    }
  }

  function showFieldError(form, path, message) {
    const field = form.querySelector(`[data-path="${CSS.escape(path)}"]`);
    if (!field) return false;
    field.classList.add("invalid");
    const error = field.querySelector(".error");
    error.textContent = message;
    error.hidden = false;
    return true;
  }

  function messageFor(field, detail) {
    if (field && field.min !== undefined && field.max !== undefined) {
      return `Bitte einen Wert von ${field.min} bis ${field.max} eingeben.`;
    }
    if (field && field.path === "guest_access.presence_code") return "Bitte 4 bis 8 Ziffern eingeben.";
    return "Dieser Wert passt nicht.";
  }

  async function saveSection(name, form, statusNode) {
    clearErrors(form);
    const draft = structuredClone(settings);
    for (const field of SECTIONS[name].fields) setPath(draft, field.path, readField(field));
    statusNode.textContent = "Speichert …";
    try {
      settings = await api("PUT", "api/settings", draft);
      statusNode.textContent = "Gespeichert.";
      renderSection(name);
      form.querySelector(".status").textContent = "Gespeichert.";
      if (name === "speaker") loadSonosLists(false, true);
      lastRendered = {};
      refreshStatus();
    } catch (err) {
      statusNode.textContent = "";
      if (err.status === 422 && err.body && Array.isArray(err.body.detail)) {
        let shown = false;
        for (const issue of err.body.detail) {
          const path = (issue.loc || []).filter((part) => part !== "body").join(".");
          const field = SECTIONS[name].fields.find((f) => f.path === path);
          shown = showFieldError(form, path, messageFor(field, issue)) || shown;
        }
        statusNode.textContent = shown ? "Bitte die markierten Felder prüfen." : "Die Einstellungen passen nicht zusammen.";
      } else {
        statusNode.textContent = errorText(err);
      }
    }
  }

  let listsLoaded = false;
  async function loadSonosLists(rescan = false, afterSpeakerSave = false) {
    if (listsLoaded && !rescan && !afterSpeakerSave) return;
    listsLoaded = true;
    if (!settings) return;
    const jobs = [];
    const speakerPaths = ["speaker.coordinator_uid", "speaker.members"];
    if (!lists.speakers || rescan) {
      lists.speakers = null;
      refreshFields("speaker", speakerPaths);
      jobs.push(
        api("GET", "api/sonos/speakers")
          .then((speakers) => { lists.speakers = speakers; })
          .catch(() => { lists.speakers = []; toast("Keine Sonos-Lautsprecher gefunden."); })
          .then(() => refreshFields("speaker", speakerPaths))
      );
    }
    jobs.push(
      api("GET", "api/sonos/accounts")
        .then((accounts) => { lists.accounts = accounts; lists.accountsError = null; })
        .catch((err) => { lists.accounts = []; lists.accountsError = errorText(err); }),
      api("GET", "api/sonos/fallback-sources")
        .then((sources) => { lists.sources = sources; lists.sourcesError = null; })
        .catch((err) => { lists.sources = []; lists.sourcesError = errorText(err); })
    );
    await Promise.all(jobs);
    refreshFields("music", ["account_id", "fallback.source_id"]);
  }

  // ------------------------------------------------------------------ Protokoll

  const ACTIONS = {
    settings: "Einstellungen geändert",
    jukebox_on: "Jukebox eingeschaltet",
    jukebox_off: "Jukebox ausgeschaltet",
    freeze: "Warteschlange angehalten",
    unfreeze: "Warteschlange fortgesetzt",
    remove: "Song entfernt",
    pin: "Song angepinnt",
    unpin: "Song losgelöst",
    block: "Gast gesperrt",
    unblock: "Gast entsperrt",
    skip: "Song übersprungen",
    resume_control: "Steuerung übernommen",
    manual_override: "Sonos-App hat übernommen",
    rotate_requested: "Gastzugang-Erneuerung angefordert",
    rotate_guest_access: "Gastzugang erneuert",
  };
  const ACTORS = { integration: "Home Assistant", sonos: "Sonos" };

  async function loadLog() {
    try {
      const entries = await api("GET", "api/audit?limit=200");
      $("log").replaceChildren(
        ...entries.map((entry) =>
          el(
            "tr",
            {},
            el("td", { text: clock(entry.at) }),
            el("td", { text: ACTORS[entry.actor] || entry.actor }),
            el("td", { text: ACTIONS[entry.action] || entry.action }),
            el("td", { text: entry.detail })
          )
        )
      );
    } catch (err) {
      toast(errorText(err));
    }
  }

  // ------------------------------------------------------------------ Start

  async function boot() {
    for (const tab of TABS) $("tab-" + tab).addEventListener("click", () => selectTab(tab));
    document.querySelector(".tabs").addEventListener("keydown", (event) => {
      const index = TABS.indexOf(activeTab);
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        const next = TABS[(index + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
        selectTab(next);
        $("tab-" + next).focus();
      }
    });
    $("banner-action").addEventListener("click", () => bannerAction && bannerAction.run());
    // Cover nicht ladbar: lieber ohne Bild als mit kaputtem Symbol.
    $("now-art").addEventListener("error", () => { $("now-art").hidden = true; });
    $("power").addEventListener("change", (event) =>
      act("POST", "api/jukebox", { active: event.target.checked }, event.target.checked ? "Jukebox eingeschaltet." : "Jukebox ausgeschaltet.")
    );
    $("skip").addEventListener("click", () => act("POST", "api/skip", undefined, "Übersprungen."));
    $("freeze").addEventListener("click", () => act("POST", "api/freeze", { frozen: !status.frozen }));
    $("copy-url").addEventListener("click", copyUrl);
    $("print").addEventListener("click", printSheet);
    $("rotate").addEventListener("click", () => { $("rotate-confirm").hidden = false; $("rotate").hidden = true; });
    $("rotate-no").addEventListener("click", () => { $("rotate-confirm").hidden = true; $("rotate").hidden = false; });
    $("rotate-yes").addEventListener("click", async () => {
      $("rotate-confirm").hidden = true;
      $("rotate").hidden = false;
      await act("POST", "api/guest-access/rotate", undefined, "Gastzugang wird erneuert. Bitte den neuen QR-Code aushängen.");
    });

    try {
      settings = await api("GET", "api/settings");
      renderSettings();
    } catch (err) {
      toast("Einstellungen konnten nicht geladen werden.");
    }
    await refreshStatus();
    const saved = store.get("sobo.tab");
    selectTab(TABS.includes(saved) ? saved : "live");
    setInterval(() => { if (!document.hidden) refreshStatus(); }, POLL_MS);
  }

  boot();
})();
