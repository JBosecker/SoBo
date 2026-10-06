"use strict";
(() => {
  // All paths are relative: the page runs behind Home Assistant's ingress prefix.
  const POLL_MS = 2000;
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------ texts (en is the default, de is a translation)

  const I18N = {
    en: {
      locale: "en-GB",
      power_on: "Jukebox on",
      power_off: "Jukebox off",
      power_outside_window: "On, outside the time window",
      power_hint: "Turns the jukebox on or off for guests.",
      tabs_label: "Sections",
      tab_live: "Live",
      tab_access: "Guest access",
      tab_settings: "Settings",
      tab_log: "Log",
      now_heading: "Now playing",
      nothing: "Nothing",
      skip: "Skip",
      freeze: "Freeze queue",
      frozen: "Queue frozen",
      queue_heading: "Queue",
      queue_empty: "No requests yet. If a base playlist is set, it fills the gaps.",
      guests_heading: "Guests",
      guests_empty: "Nobody has joined yet.",
      history_heading: "Recently played",
      qr_alt: "QR code for guest access",
      access_heading: "How guests get in",
      copy_link: "Copy link",
      print_qr: "Print QR code",
      fact_integration: "Integration",
      rotate: "Renew guest access",
      rotating: "Renewing …",
      rotate_warning: "The old QR code stops working and every guest has to join again.",
      rotate_yes: "Renew",
      cancel: "Cancel",
      log_time: "Time",
      log_who: "Who",
      log_what: "What",
      log_details: "Details",
      print_title: "Request a song!",
      print_steps: "Scan with your phone camera, enter a name, search for a song and suggest it.",
      print_code: "Code: {code}",
      just_now: "just now",
      minutes_ago: "{n} min ago",
      hours_ago: "{n} h ago",
      sonos_unavailable: "Sonos is not responding right now.",
      failed: "That did not work.",
      reason: "(Reason: {reason})",
      no_connection: "No connection to the SoBo app.",
      override: "Something else was started in the Sonos app{what}. SoBo is waiting.",
      take_over: "Take over again",
      took_over: "SoBo is back in control.",
      no_speaker_banner: "No speaker selected. Without a speaker SoBo cannot play anything.",
      choose_speaker: "Choose speaker",
      music_auth: "Apple Music rejects the sign-in stored in your Sonos system, so searching and playing requests fail. In the Sonos app, open Apple Music in the service settings and sign in again (or remove and re-add the service); SoBo picks up the new sign-in automatically.",
      sonos_error: "Sonos reports a problem: {error}",
      fallback_error: "The base playlist cannot be loaded: {error}",
      from_fallback: "From the base playlist",
      requested_by: "Requested by {name}",
      voted_from_playlist: "From the base playlist, voted up by guests",
      next_line: "Up next: {title} by {artist}{origin}",
      next_open: "Up next: chosen by the votes shortly before this song ends",
      requests_one: "{n} request",
      requests_other: "{n} requests",
      songs_one: "{n} song",
      songs_other: "{n} songs",
      votes_n_one: "{n} vote",
      votes_n_other: "{n} votes",
      fallback_heading: "Then from the base playlist",
      votes_one: "vote",
      votes_other: "votes",
      pinned: "Pinned",
      pin: "Pin",
      pin_help: "Pinned songs play before all others.",
      remove: "Remove",
      remove_label: "Remove {title}",
      removed: "Removed.",
      guest_meta: "{requests}, {votes} votes left, active {ago}",
      block: "Block",
      unblock: "Unblock",
      block_label: "Block {name}",
      unblock_label: "Unblock {name}",
      no_link: "No guest link yet.",
      explain_no_integration: "The SoBo integration is not connected. Install it via HACS and set it up in Home Assistant under Devices & services.",
      explain_cloud: "Guests scan the QR code with their phone camera. The link works everywhere, even without your Wi-Fi, and reveals nothing about your Home Assistant address.",
      explain_local: "Nabu Casa is not connected. This link only works on your own Wi-Fi.",
      explain_none: "The integration has not reported a link yet.",
      connected: "Connected",
      not_connected: "Not connected",
      not_set_up: "Not set up",
      link_copied: "Link copied.",
      link_selected: "Link selected. Press Ctrl/Cmd+C to copy.",
      please_choose: "Please choose",
      searching_speakers: "Looking for speakers …",
      search_again: "Search again",
      not_found: "{value} (not found)",
      no_other_speakers: "No other speakers found.",
      no_apple_account: "No Apple Music account found in the Sonos household.",
      favorite: "{name} (favourite)",
      loading_playlists: "Loading playlists …",
      no_playlists: "No playlists found in this account's library.",
      none: "None",
      save: "Save",
      saving: "Saving …",
      saved: "Saved.",
      range_error: "Please enter a value from {min} to {max}.",
      code_error: "Please enter 4 to 8 digits.",
      value_error: "This value does not fit.",
      check_fields: "Please check the marked fields.",
      settings_conflict: "The settings do not fit together.",
      no_speakers_found: "No Sonos speakers found.",
      jukebox_turned_on: "Jukebox turned on.",
      jukebox_turned_off: "Jukebox turned off.",
      skipped: "Skipped.",
      rotation_started: "Guest access is being renewed. Please put up the new QR code.",
      settings_load_failed: "Settings could not be loaded.",
      errors: {
        no_speaker: "Choose and save a speaker first.",
        unknown_item: "This song is no longer in the queue.",
        unknown_guest: "This guest no longer exists.",
        integration_not_connected: "The SoBo integration is not connected.",
        sonos_unavailable: "Sonos is not responding right now.",
      },
      states: {
        inactive: "Off",
        idle: "Ready, waiting for requests",
        playing_guest: "Playing guest requests",
        playing_fallback: "Playing base playlist",
        paused: "Paused",
        manual_override: "Sonos app took over",
        error: "Problem",
      },
      sections: {
        speaker: ["Speaker", "Which Sonos is the party on? Guests cannot choose the room."],
        music: ["Music"],
        votes: ["Votes"],
        limits: ["Rules for requests"],
        schedule: ["Time window"],
        guest_access: ["Guest access settings"],
      },
      fields: {
        "speaker.coordinator_uid": ["Speaker"],
        "speaker.members": ["Grouped speakers"],
        "speaker.start_volume": ["Start volume", "Applied when turning on. Leave empty to keep the volume."],
        "speaker.max_volume": ["Maximum volume", "If someone turns it up further, SoBo turns it down again."],
        account_id: ["Apple Music account"],
        "fallback.source_id": ["Base playlist", "A playlist from the Apple Music library of the chosen account. Plays while there are no requests."],
        "fallback.shuffle": ["Shuffle the base playlist"],
        "fallback.preview_count": ["Base playlist songs shown in the queue", "0 shows all songs of the playlist. Guests can vote for each of them."],
        "votes.votes_per_window": ["Votes per guest"],
        "votes.window_minutes": ["Period in minutes", "A used vote comes back after this time."],
        "votes.suggestion_costs_vote": ["A suggestion costs a vote"],
        "votes.lock_next_seconds": ["Fix the next song this many seconds before the end", "Until then, votes still decide which song comes next."],
        "limits.suggestions_per_window": ["Suggestions per guest"],
        "limits.suggestion_window_minutes": ["Suggestion period in minutes"],
        "limits.max_track_seconds": ["Maximum song length in minutes"],
        "limits.track_cooldown_minutes": ["Cooldown for the same song in minutes"],
        "limits.artist_cooldown_minutes": ["Cooldown for the same artist in minutes", "0 turns the cooldown off."],
        "limits.explicit_filter": ["Exclude songs with explicit content", "Only works if Apple Music provides the information."],
        "limits.blocklist": ["Blocklist", "One entry per line. Matches title, artist or album."],
        "schedule.enabled": ["Only open for guests within a time window"],
        "schedule.start": ["Start"],
        "schedule.end": ["End", "Crossing midnight works too, e.g. 20:00 to 02:00."],
        timezone: ["Time zone", "For example Europe/Berlin."],
        "guest_access.presence_code": ["Presence code", "4 to 8 digits you announce at the party. Leave empty for no code."],
        "guest_access.max_active_guests": ["Maximum active guests"],
        "guest_access.session_hours": ["Sign-in valid for hours"],
        "guest_access.joins_per_minute": ["New guests per minute", "Slows down mass sign-ups if the link gets around."],
        "guest_access.long_poll_timeout": ["Wait time for live updates in seconds"],
        "guest_access.max_open_long_polls": ["Simultaneous live connections", "Beyond this, phones ask every few seconds instead."],
        "guest_access.show_covers": ["Show album covers", "Phones load covers directly from Apple."],
        "guest_access.unregister_when_inactive": ["Turn the guest link off while the jukebox is off"],
      },
      actions: {
        settings: "Settings changed",
        jukebox_on: "Jukebox turned on",
        jukebox_off: "Jukebox turned off",
        freeze: "Queue frozen",
        unfreeze: "Queue resumed",
        remove: "Song removed",
        pin: "Song pinned",
        unpin: "Song unpinned",
        block: "Guest blocked",
        unblock: "Guest unblocked",
        skip: "Song skipped",
        resume_control: "Control taken back",
        manual_override: "Sonos app took over",
        rotate_requested: "Guest access renewal requested",
        rotate_guest_access: "Guest access renewed",
      },
    },
    de: {
      locale: "de-DE",
      power_on: "Jukebox an",
      power_off: "Jukebox aus",
      power_outside_window: "An, außerhalb des Zeitfensters",
      power_hint: "Schaltet die Jukebox für Gäste an oder aus.",
      tabs_label: "Bereiche",
      tab_live: "Live",
      tab_access: "Gastzugang",
      tab_settings: "Einstellungen",
      tab_log: "Protokoll",
      now_heading: "Läuft gerade",
      nothing: "Nichts",
      skip: "Überspringen",
      freeze: "Warteschlange anhalten",
      frozen: "Warteschlange angehalten",
      queue_heading: "Warteschlange",
      queue_empty: "Noch keine Wünsche. Läuft die Basis-Playlist, füllt sie die Pausen.",
      guests_heading: "Gäste",
      guests_empty: "Noch niemand dabei.",
      history_heading: "Zuletzt gespielt",
      qr_alt: "QR-Code für den Gastzugang",
      access_heading: "So kommen Gäste rein",
      copy_link: "Link kopieren",
      print_qr: "QR-Code drucken",
      fact_integration: "Integration",
      rotate: "Gastzugang erneuern",
      rotating: "Wird erneuert …",
      rotate_warning: "Der alte QR-Code funktioniert danach nicht mehr, und alle Gäste müssen neu beitreten.",
      rotate_yes: "Erneuern",
      cancel: "Abbrechen",
      log_time: "Zeit",
      log_who: "Wer",
      log_what: "Was",
      log_details: "Details",
      print_title: "Wünsch dir einen Song!",
      print_steps: "Mit der Handykamera scannen, Namen eingeben, Song suchen und vorschlagen.",
      print_code: "Code: {code}",
      just_now: "gerade eben",
      minutes_ago: "vor {n} Min.",
      hours_ago: "vor {n} Std.",
      sonos_unavailable: "Sonos antwortet gerade nicht.",
      failed: "Das hat nicht geklappt.",
      reason: "(Grund: {reason})",
      no_connection: "Keine Verbindung zur SoBo-App.",
      override: "In der Sonos-App wurde etwas anderes gestartet{what}. SoBo wartet.",
      take_over: "Wieder übernehmen",
      took_over: "SoBo hat wieder übernommen.",
      no_speaker_banner: "Kein Lautsprecher gewählt. Ohne Lautsprecher kann SoBo nichts abspielen.",
      choose_speaker: "Lautsprecher wählen",
      music_auth: "Apple Music lehnt die im Sonos-System gespeicherte Anmeldung ab, deshalb schlagen Suche und Wünsche fehl. Öffne in der Sonos-App Apple Music in den Diensteinstellungen und melde dich neu an (oder entferne den Dienst und füge ihn wieder hinzu); SoBo übernimmt die neue Anmeldung automatisch.",
      sonos_error: "Sonos meldet eine Störung: {error}",
      fallback_error: "Die Basis-Playlist lässt sich nicht laden: {error}",
      from_fallback: "Aus der Basis-Playlist",
      requested_by: "Wunsch von {name}",
      voted_from_playlist: "Aus der Basis-Playlist, von Gästen hochgestimmt",
      next_line: "Als Nächstes: {title} von {artist}{origin}",
      next_open: "Als Nächstes: entscheiden die Stimmen kurz vor Ende dieses Songs",
      requests_one: "{n} Wunsch",
      requests_other: "{n} Wünsche",
      songs_one: "{n} Song",
      songs_other: "{n} Songs",
      votes_n_one: "{n} Stimme",
      votes_n_other: "{n} Stimmen",
      fallback_heading: "Danach aus der Basis-Playlist",
      votes_one: "Stimme",
      votes_other: "Stimmen",
      pinned: "Angepinnt",
      pin: "Anpinnen",
      pin_help: "Angepinnte Songs kommen vor allen anderen dran.",
      remove: "Entfernen",
      remove_label: "{title} entfernen",
      removed: "Entfernt.",
      guest_meta: "{requests}, {votes} Stimmen übrig, aktiv {ago}",
      block: "Sperren",
      unblock: "Entsperren",
      block_label: "{name} sperren",
      unblock_label: "{name} entsperren",
      no_link: "Noch kein Gast-Link.",
      explain_no_integration: "Die SoBo-Integration ist nicht verbunden. Installiere sie über HACS und richte sie in Home Assistant unter Geräte & Dienste ein.",
      explain_cloud: "Gäste scannen den QR-Code mit der Handykamera. Der Link funktioniert überall, auch ohne euer WLAN, und verrät nichts über deine Home-Assistant-Adresse.",
      explain_local: "Nabu Casa ist nicht verbunden. Dieser Link funktioniert nur im eigenen WLAN.",
      explain_none: "Die Integration hat noch keinen Link gemeldet.",
      connected: "Verbunden",
      not_connected: "Nicht verbunden",
      not_set_up: "Nicht eingerichtet",
      link_copied: "Link kopiert.",
      link_selected: "Link markiert. Mit Strg/Cmd+C kopieren.",
      please_choose: "Bitte wählen",
      searching_speakers: "Lautsprecher werden gesucht …",
      search_again: "Erneut suchen",
      not_found: "{value} (nicht gefunden)",
      no_other_speakers: "Keine weiteren Lautsprecher gefunden.",
      no_apple_account: "Kein Apple-Music-Konto im Sonos-Haushalt gefunden.",
      favorite: "{name} (Favorit)",
      loading_playlists: "Playlists werden geladen …",
      no_playlists: "In der Mediathek dieses Kontos gibt es keine Playlists.",
      none: "Keine",
      save: "Speichern",
      saving: "Speichert …",
      saved: "Gespeichert.",
      range_error: "Bitte einen Wert von {min} bis {max} eingeben.",
      code_error: "Bitte 4 bis 8 Ziffern eingeben.",
      value_error: "Dieser Wert passt nicht.",
      check_fields: "Bitte die markierten Felder prüfen.",
      settings_conflict: "Die Einstellungen passen nicht zusammen.",
      no_speakers_found: "Keine Sonos-Lautsprecher gefunden.",
      jukebox_turned_on: "Jukebox eingeschaltet.",
      jukebox_turned_off: "Jukebox ausgeschaltet.",
      skipped: "Übersprungen.",
      rotation_started: "Gastzugang wird erneuert. Bitte den neuen QR-Code aushängen.",
      settings_load_failed: "Einstellungen konnten nicht geladen werden.",
      errors: {
        no_speaker: "Erst einen Lautsprecher wählen und speichern.",
        unknown_item: "Den Song gibt es nicht mehr in der Warteschlange.",
        unknown_guest: "Diesen Gast gibt es nicht mehr.",
        integration_not_connected: "Die SoBo-Integration ist nicht verbunden.",
        sonos_unavailable: "Sonos antwortet gerade nicht.",
      },
      states: {
        inactive: "Aus",
        idle: "Bereit, wartet auf Wünsche",
        playing_guest: "Spielt Gastwünsche",
        playing_fallback: "Spielt Basis-Playlist",
        paused: "Pausiert",
        manual_override: "Sonos-App hat übernommen",
        error: "Störung",
      },
      sections: {
        speaker: ["Lautsprecher", "Auf welchem Sonos läuft die Party? Gäste können den Raum nicht wählen."],
        music: ["Musik"],
        votes: ["Stimmen"],
        limits: ["Regeln für Wünsche"],
        schedule: ["Zeitfenster"],
        guest_access: ["Einstellungen zum Gastzugang"],
      },
      fields: {
        "speaker.coordinator_uid": ["Lautsprecher"],
        "speaker.members": ["Mitspielende Lautsprecher"],
        "speaker.start_volume": ["Startlautstärke", "Beim Einschalten. Leer lassen, um die Lautstärke nicht zu ändern."],
        "speaker.max_volume": ["Maximale Lautstärke", "Wird höher gedreht, regelt SoBo wieder herunter."],
        account_id: ["Apple-Music-Konto"],
        "fallback.source_id": ["Basis-Playlist", "Eine Playlist aus der Apple-Music-Mediathek des gewählten Kontos. Läuft, solange keine Wünsche da sind."],
        "fallback.shuffle": ["Basis-Playlist zufällig abspielen"],
        "fallback.preview_count": ["Songs der Basis-Playlist in der Warteschlange", "0 zeigt alle Songs der Playlist. Gäste können für jeden davon abstimmen."],
        "votes.votes_per_window": ["Stimmen pro Gast"],
        "votes.window_minutes": ["Zeitraum in Minuten", "Eine verbrauchte Stimme kommt nach dieser Zeit zurück."],
        "votes.suggestion_costs_vote": ["Ein Vorschlag kostet eine Stimme"],
        "votes.lock_next_seconds": ["Nächsten Song so viele Sekunden vor Ende festlegen", "Bis dahin entscheiden die Stimmen, welcher Song als Nächstes kommt."],
        "limits.suggestions_per_window": ["Vorschläge pro Gast"],
        "limits.suggestion_window_minutes": ["Zeitraum für Vorschläge in Minuten"],
        "limits.max_track_seconds": ["Maximale Songlänge in Minuten"],
        "limits.track_cooldown_minutes": ["Sperrzeit für denselben Song in Minuten"],
        "limits.artist_cooldown_minutes": ["Sperrzeit für denselben Interpreten in Minuten", "0 schaltet die Sperre aus."],
        "limits.explicit_filter": ["Songs mit explizitem Inhalt ausschließen", "Greift nur, wenn Apple Music die Angabe liefert."],
        "limits.blocklist": ["Sperrliste", "Ein Eintrag pro Zeile. Passt auf Titel, Interpret oder Album."],
        "schedule.enabled": ["Nur in einem Zeitfenster für Gäste offen"],
        "schedule.start": ["Beginn"],
        "schedule.end": ["Ende", "Über Mitternacht geht auch, z. B. 20:00 bis 02:00."],
        timezone: ["Zeitzone", "Zum Beispiel Europe/Berlin."],
        "guest_access.presence_code": ["Anwesenheitscode", "4 bis 8 Ziffern, die du auf der Party bekannt gibst. Leer lassen für keinen Code."],
        "guest_access.max_active_guests": ["Höchstens aktive Gäste"],
        "guest_access.session_hours": ["Anmeldung gültig für Stunden"],
        "guest_access.joins_per_minute": ["Neue Gäste pro Minute", "Bremst Massenanmeldungen, falls der Link die Runde macht."],
        "guest_access.long_poll_timeout": ["Wartezeit für Live-Updates in Sekunden"],
        "guest_access.max_open_long_polls": ["Gleichzeitige Live-Verbindungen", "Darüber fragen Handys alle paar Sekunden nach."],
        "guest_access.show_covers": ["Albumcover zeigen", "Die Handys laden Cover direkt von Apple."],
        "guest_access.unregister_when_inactive": ["Gast-Link abschalten, solange die Jukebox aus ist"],
      },
      actions: {
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
      },
    },
  };

  /** Pick the first supported language from the browser preferences (fallback: English). */
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

  /** Plural helper: uses `<key>_one` / `<key>_other`. */
  function tn(key, n, vars) {
    return t(`${key}_${n === 1 ? "one" : "other"}`, Object.assign({ n }, vars));
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

  // ------------------------------------------------------------------ helpers

  class ApiError extends Error {
    constructor(status, body) {
      super((body && (body.error || body.detail)) || `HTTP ${status}`);
      this.status = status;
      this.body = body;
    }
  }

  async function api(method, path, body) {
    // The custom header protects state-changing requests against CSRF (see admin.py).
    const options = { method, headers: { "X-SoBo-Request": "1" }, cache: "no-store" };
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
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* ignore */ } },
  };

  function ago(iso) {
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return t("just_now");
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return t("minutes_ago", { n: minutes });
    return t("hours_ago", { n: Math.round(minutes / 60) });
  }

  function clock(iso) {
    return new Date(iso).toLocaleString(TEXT.locale, { dateStyle: "short", timeStyle: "medium" });
  }

  /** Error text plus the technical reason from the app, for hints below a field. */
  function errorWithReason(err) {
    const reason = err.body && typeof err.body.detail === "string" ? err.body.detail : "";
    return reason ? `${errorText(err)} ${t("reason", { reason })}` : errorText(err);
  }

  function errorText(err) {
    const code = err.body && err.body.error;
    return TEXT.errors[code] || (err.status === 503 ? t("sonos_unavailable") : t("failed"));
  }

  const STATE_TONES = {
    inactive: "",
    idle: "on",
    playing_guest: "on",
    playing_fallback: "on",
    paused: "",
    manual_override: "warn",
    error: "warn",
  };

  // ------------------------------------------------------------------ tabs

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

  // ------------------------------------------------------------------ status / live

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
      showBanner(t("no_connection"), null);
      return;
    }
    renderTop();
    renderLive();
    renderAccess();
    if (activeTab === "live") loadGuests();
  }

  function renderTop() {
    const label = TEXT.states[status.state] || status.state;
    const tone = STATE_TONES[status.state] || "";
    const pill = $("state-pill");
    pill.textContent = label;
    pill.className = "pill" + (tone ? " " + tone : "");
    $("power").checked = status.active;
    let power = status.active ? t("power_on") : t("power_off");
    if (status.active && !status.effectively_active) power = t("power_outside_window");
    $("power-label").textContent = power;

    if (status.state === "manual_override") {
      const what = status.override_info ? ` (${status.override_info})` : "";
      showBanner(t("override", { what }), {
        label: t("take_over"),
        run: () => act("POST", "api/control/resume", undefined, t("took_over")),
      });
    } else if (status.service_error === "music_auth") {
      showBanner(t("music_auth"), null);
    } else if (status.last_error === "no_speaker" && status.active) {
      showBanner(t("no_speaker_banner"), {
        label: t("choose_speaker"),
        run: () => selectTab("settings"),
      });
    } else if (status.last_error && status.active) {
      showBanner(t("sonos_error", { error: status.last_error }), null);
    } else if (status.fallback_error && status.active) {
      showBanner(t("fallback_error", { error: status.fallback_error }), null);
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
    if (item.origin === "fallback") return t("from_fallback");
    if (item.submitted_by) return t("requested_by", { name: item.submitted_by });
    if (item.origin === "guest" && !item.submitted_by_id) return t("voted_from_playlist");
    return "";
  }

  function renderLive() {
    const now = status.now_playing;
    $("now-title").textContent = now ? now.title : t("nothing");
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
      ? t("next_line", { title: next.title, artist: next.artist, origin: origin(next) ? ` (${origin(next)})` : "" })
      : t("next_open");

    const freeze = $("freeze");
    freeze.setAttribute("aria-pressed", String(status.frozen));
    freeze.textContent = status.frozen ? t("frozen") : t("freeze");

    if (changed("queue", [status.queue, status.fallback_upcoming])) {
      renderQueue(status.queue, status.fallback_upcoming || []);
    }
    if (changed("history", status.history)) {
      $("history-heading").hidden = status.history.length === 0;
      $("history").replaceChildren(
        ...status.history.slice(0, 8).map((item) => el("li", { text: `${item.title} – ${item.artist}` }))
      );
    }
  }

  function cover(art) {
    const box = el("div", { class: "art", "aria-hidden": "true" });
    if (art && art.startsWith("https://")) {
      const img = el("img", { alt: "", loading: "lazy", decoding: "async", src: art });
      img.addEventListener("error", () => img.remove());
      box.append(img);
    }
    return box;
  }

  function rowText(title, sub, meta) {
    return el(
      "div",
      { class: "row-text" },
      el("span", { class: "row-title", text: title }),
      el("span", { class: "row-sub", text: sub || " " }),
      meta ? el("span", { class: "row-meta", text: meta }) : null
    );
  }

  function renderQueue(queue, upcoming) {
    $("queue-empty").hidden = queue.length > 0;
    $("queue-count").textContent = queue.length ? tn("requests", queue.length) : "";
    $("queue").replaceChildren(
      ...queue.map((item) =>
        el(
          "li",
          { class: "track" + (item.pinned ? " pinned" : "") },
          cover(item.art),
          rowText(
            item.title,
            item.artist,
            [item.pinned ? t("pinned") : "", origin(item), ago(item.submitted_at)].filter(Boolean).join(" · ")
          ),
          el(
            "span",
            { class: "votes", title: tn("votes_n", item.votes) },
            el("span", { class: "arrow", "aria-hidden": "true", text: "▲" }),
            el("span", { class: "count", text: item.votes }),
            el("span", { class: "visually-hidden", text: t(item.votes === 1 ? "votes_one" : "votes_other") })
          ),
          el(
            "div",
            { class: "row-actions" },
            el("button", {
              type: "button",
              class: "button",
              "aria-pressed": String(item.pinned),
              text: item.pinned ? t("pinned") : t("pin"),
              title: t("pin_help"),
              onclick: () => act("POST", `api/queue/${encodeURIComponent(item.id)}/pin`, { pinned: !item.pinned }),
            }),
            el("button", {
              type: "button",
              class: "button danger",
              text: t("remove"),
              "aria-label": t("remove_label", { title: item.title }),
              onclick: () => act("POST", `api/queue/${encodeURIComponent(item.id)}/remove`, undefined, t("removed")),
            })
          )
        )
      )
    );
    // Base playlist: plays once the requests are through; guests can vote it up.
    $("fallback-head").hidden = upcoming.length === 0;
    $("fallback-count").textContent = upcoming.length ? tn("songs", upcoming.length) : "";
    $("fallback-queue").replaceChildren(
      ...upcoming.map((track) => el("li", { class: "track fallback" }, cover(track.art), rowText(track.title, track.artist)))
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
                text: t("guest_meta", {
                  requests: tn("requests", guest.suggestions),
                  votes: guest.votes_left,
                  ago: ago(guest.last_seen),
                }),
              })
            ),
            el("button", {
              type: "button",
              class: "button" + (guest.blocked ? "" : " danger"),
              text: guest.blocked ? t("unblock") : t("block"),
              "aria-label": t(guest.blocked ? "unblock_label" : "block_label", { name: guest.nickname }),
              onclick: () => act("POST", `api/guests/${encodeURIComponent(guest.id)}/block`, { blocked: !guest.blocked }),
            })
          )
        )
      );
    } catch (err) {
      /* try again on the next poll */
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

  // ------------------------------------------------------------------ guest access

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
      $("qr-missing").textContent = t("no_link");
    }
    $("guest-url").textContent = url || "–";
    $("copy-url").disabled = !url;
    $("print").disabled = !url;

    let explain;
    if (!access.integration_connected) explain = t("explain_no_integration");
    else if (access.url) explain = t("explain_cloud");
    else if (access.local_url) explain = t("explain_local");
    else explain = t("explain_none");
    $("access-explain").textContent = explain;
    $("fact-integration").textContent = access.integration_connected ? t("connected") : t("not_connected");
    $("fact-cloud").textContent =
      access.cloud_connected === true ? t("connected") : access.cloud_connected === false ? t("not_connected") : t("not_set_up");
    const rotate = $("rotate");
    rotate.disabled = !access.integration_connected || access.rotation_pending;
    rotate.textContent = access.rotation_pending ? t("rotating") : t("rotate");
  }

  async function copyUrl() {
    const text = $("guest-url").textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast(t("link_copied"));
    } catch (err) {
      const range = document.createRange();
      range.selectNodeContents($("guest-url"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      toast(t("link_selected"));
    }
  }

  function printSheet() {
    const code = settings && settings.guest_access.presence_code;
    $("print-code").hidden = !code;
    $("print-code").textContent = code ? t("print_code", { code }) : "";
    window.print();
  }

  // ------------------------------------------------------------------ settings

  let settings = null;
  const lists = { speakers: null, accounts: null, sources: null, accountsError: null, sourcesError: null };

  // Labels and help texts come from I18N[...].fields / .sections.
  const SECTIONS = {
    speaker: [
      { path: "speaker.coordinator_uid", type: "speaker" },
      { path: "speaker.members", type: "members", wide: true },
      { path: "speaker.start_volume", type: "number", min: 0, max: 100, nullable: true },
      { path: "speaker.max_volume", type: "number", min: 0, max: 100 },
    ],
    music: [
      { path: "account_id", type: "account" },
      { path: "fallback.source_id", type: "source" },
      { path: "fallback.shuffle", type: "checkbox" },
      { path: "fallback.preview_count", type: "number", min: 0, max: 500 },
    ],
    votes: [
      { path: "votes.votes_per_window", type: "number", min: 1, max: 100 },
      { path: "votes.window_minutes", type: "number", min: 1, max: 1440 },
      { path: "votes.suggestion_costs_vote", type: "checkbox" },
      { path: "votes.lock_next_seconds", type: "number", min: 5, max: 600 },
    ],
    limits: [
      { path: "limits.suggestions_per_window", type: "number", min: 0, max: 100 },
      { path: "limits.suggestion_window_minutes", type: "number", min: 1, max: 1440 },
      { path: "limits.max_track_seconds", type: "number", min: 0.5, max: 180, step: 0.5, scale: 60 },
      { path: "limits.track_cooldown_minutes", type: "number", min: 0, max: 1440 },
      { path: "limits.artist_cooldown_minutes", type: "number", min: 0, max: 1440 },
      { path: "limits.explicit_filter", type: "checkbox" },
      { path: "limits.blocklist", type: "lines", wide: true },
    ],
    schedule: [
      { path: "schedule.enabled", type: "checkbox" },
      { path: "schedule.start", type: "time" },
      { path: "schedule.end", type: "time" },
      { path: "timezone", type: "text" },
    ],
    guest_access: [
      { path: "guest_access.presence_code", type: "text", nullable: true, inputmode: "numeric" },
      { path: "guest_access.max_active_guests", type: "number", min: 1, max: 1000 },
      { path: "guest_access.session_hours", type: "number", min: 1, max: 72 },
      { path: "guest_access.joins_per_minute", type: "number", min: 1, max: 600 },
      { path: "guest_access.long_poll_timeout", type: "number", min: 5, max: 60 },
      { path: "guest_access.max_open_long_polls", type: "number", min: 1, max: 2000 },
      { path: "guest_access.show_covers", type: "checkbox" },
      { path: "guest_access.unregister_when_inactive", type: "checkbox" },
    ],
  };

  function fieldText(field) {
    const [label, help] = TEXT.fields[field.path] || I18N.en.fields[field.path] || [field.path];
    return { label, help };
  }

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
    if (!found) nodes.push(el("option", { value: current, text: t("not_found", { value: current }), selected: true }));
    return nodes;
  }

  function renderField(field) {
    const id = fieldId(field.path);
    const value = getPath(settings, field.path);
    const { label, help: helpText } = fieldText(field);
    const help = helpText ? el("p", { class: "help", id: id + "-help", text: helpText }) : null;
    const error = el("p", { class: "error", id: id + "-error", hidden: true });
    const describedBy = [help && id + "-help", id + "-error"].filter(Boolean).join(" ");
    const wrap = (cls, ...children) => el("div", { class: "field " + cls + (field.wide ? " wide" : ""), "data-path": field.path }, ...children);

    switch (field.type) {
      case "checkbox":
        return wrap("check", el("input", { type: "checkbox", id, checked: Boolean(value), "aria-describedby": describedBy }), el("label", { for: id, text: label }), help, error);
      case "number": {
        const shown = value === null || value === undefined ? "" : field.scale ? value / field.scale : value;
        return wrap("", el("label", { for: id, text: label }), el("input", { type: "number", id, value: shown, min: field.min, max: field.max, step: field.step || 1, inputmode: "numeric", "aria-describedby": describedBy }), help, error);
      }
      case "time":
        return wrap("", el("label", { for: id, text: label }), el("input", { type: "time", id, value: String(value || "").slice(0, 5), "aria-describedby": describedBy }), help, error);
      case "text":
        return wrap("", el("label", { for: id, text: label }), el("input", { type: "text", id, value: value || "", inputmode: field.inputmode, autocomplete: "off", "aria-describedby": describedBy }), help, error);
      case "lines":
        return wrap("", el("label", { for: id, text: label }), el("textarea", { id, "aria-describedby": describedBy, text: (value || []).join("\n") }), help, error);
      case "speaker": {
        const speakers = lists.speakers;
        const select = el("select", { id, "aria-describedby": describedBy }, options((speakers || []).map((s) => ({ value: s.uid, label: `${s.name} (${s.ip})` })), value, speakers ? t("please_choose") : t("searching_speakers")));
        const rescan = el("button", { type: "button", class: "button", text: t("search_again"), onclick: () => loadSonosLists(true) });
        return wrap("", el("label", { for: id, text: label }), el("div", { class: "row" }, select, rescan), help, error);
      }
      case "members": {
        const coordinator = getPath(settings, "speaker.coordinator_uid");
        const others = (lists.speakers || []).filter((s) => s.uid !== coordinator);
        const boxes = others.map((s) =>
          el("label", { class: "row" }, el("input", { type: "checkbox", value: s.uid, checked: (value || []).includes(s.uid) }), s.name)
        );
        return wrap("", el("fieldset", { id }, el("legend", { text: label }), boxes.length ? boxes : el("p", { class: "help", text: t("no_other_speakers") })), help, error);
      }
      case "account": {
        const accounts = lists.accounts || [];
        const hint = lists.accountsError || (lists.accounts && !accounts.length ? t("no_apple_account") : null);
        return wrap("", el("label", { for: id, text: label }), el("select", { id, "aria-describedby": describedBy }, options(accounts.map((a) => ({ value: a.account_id, label: a.nickname || `${a.service} ${a.account_id}` })), value, t("please_choose"))), hint ? el("p", { class: "help", text: hint }) : help, error);
      }
      case "source": {
        const sources = lists.sources || [];
        const empty = lists.sources ? t("none") : t("loading_playlists");
        const hint = lists.sourcesError || (lists.sources && !sources.length ? t("no_playlists") : null);
        return wrap("", el("label", { for: id, text: label }), el("select", { id, "aria-describedby": describedBy }, options(sources.map((s) => ({ value: s.source_id, label: s.kind === "favorite" ? t("favorite", { name: s.name }) : s.name })), value, empty)), hint ? el("p", { class: "help", text: hint }) : help, error);
      }
      default:
        throw new Error("Unknown field type " + field.type);
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
    const [title, intro] = TEXT.sections[name];
    const form = document.querySelector(`.settings-form[data-section="${name}"]`);
    const status = el("span", { class: "status", role: "status" });
    form.replaceChildren(
      ...[
        el("h2", { text: title }),
        intro ? el("p", { class: "intro", text: intro }) : null,
        el("div", { class: "fields" }, SECTIONS[name].map(renderField)),
        el("div", { class: "form-actions" }, el("button", { type: "submit", class: "button primary", text: t("save") }), status),
      ].filter(Boolean)
    );
    form.onsubmit = (event) => {
      event.preventDefault();
      saveSection(name, form, status);
    };
    if (name === "speaker") bindCoordinatorChange(form);
    if (name === "music") bindAccountChange();
  }

  /** Rebuild individual fields only (e.g. when lists arrive) – other inputs stay as they are. */
  function refreshFields(name, paths) {
    const form = document.querySelector(`.settings-form[data-section="${name}"]`);
    for (const field of SECTIONS[name]) {
      if (!paths.includes(field.path)) continue;
      const current = form.querySelector(`[data-path="${CSS.escape(field.path)}"]`);
      if (current) current.replaceWith(renderField(field));
    }
    if (name === "speaker") bindCoordinatorChange(form);
    if (name === "music") bindAccountChange();
  }

  function bindCoordinatorChange(form) {
    // The list of grouped speakers depends on the chosen speaker.
    $(fieldId("speaker.coordinator_uid")).addEventListener("change", (event) => {
      const previous = settings;
      settings = structuredClone(settings);
      setPath(settings, "speaker.coordinator_uid", event.target.value || null);
      const fresh = renderField(SECTIONS.speaker[1]);
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

  function messageFor(field) {
    if (field && field.min !== undefined && field.max !== undefined) {
      return t("range_error", { min: field.min, max: field.max });
    }
    if (field && field.path === "guest_access.presence_code") return t("code_error");
    return t("value_error");
  }

  async function saveSection(name, form, statusNode) {
    clearErrors(form);
    const draft = structuredClone(settings);
    for (const field of SECTIONS[name]) setPath(draft, field.path, readField(field));
    statusNode.textContent = t("saving");
    try {
      settings = await api("PUT", "api/settings", draft);
      statusNode.textContent = t("saved");
      renderSection(name);
      form.querySelector(".status").textContent = t("saved");
      if (name === "speaker") loadSonosLists(false, true);
      lastRendered = {};
      refreshStatus();
    } catch (err) {
      statusNode.textContent = "";
      if (err.status === 422 && err.body && Array.isArray(err.body.detail)) {
        let shown = false;
        for (const issue of err.body.detail) {
          const path = (issue.loc || []).filter((part) => part !== "body").join(".");
          const field = SECTIONS[name].find((f) => f.path === path);
          shown = showFieldError(form, path, messageFor(field)) || shown;
        }
        statusNode.textContent = shown ? t("check_fields") : t("settings_conflict");
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
          .catch(() => { lists.speakers = []; toast(t("no_speakers_found")); })
          .then(() => refreshFields("speaker", speakerPaths))
      );
    }
    jobs.push(
      api("GET", "api/sonos/accounts")
        .then((accounts) => { lists.accounts = accounts; lists.accountsError = null; })
        .catch((err) => { lists.accounts = []; lists.accountsError = errorWithReason(err); }),
      loadSources(settings.account_id)
    );
    await Promise.all(jobs);
    refreshFields("music", ["account_id"]);
  }

  /** Base playlist candidates: the playlists of the given Apple Music account. */
  let sourcesRequest = 0;
  async function loadSources(accountId) {
    const request = ++sourcesRequest;
    lists.sources = null;
    lists.sourcesError = null;
    refreshFields("music", ["fallback.source_id"]);
    const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
    try {
      const sources = await api("GET", `api/sonos/fallback-sources${query}`);
      if (request !== sourcesRequest) return;
      lists.sources = sources;
    } catch (err) {
      if (request !== sourcesRequest) return;
      lists.sources = [];
      lists.sourcesError = errorWithReason(err);
    }
    refreshFields("music", ["fallback.source_id"]);
  }

  function bindAccountChange() {
    const select = $(fieldId("account_id"));
    // Property instead of addEventListener: fields are re-rendered, never doubled.
    if (select) select.onchange = (event) => loadSources(event.target.value || null);
  }

  // ------------------------------------------------------------------ log

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
            el("td", { text: TEXT.actions[entry.action] || entry.action }),
            el("td", { text: entry.detail })
          )
        )
      );
    } catch (err) {
      toast(errorText(err));
    }
  }

  // ------------------------------------------------------------------ start

  async function boot() {
    applyStaticTexts();
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
    // Cover cannot be loaded: better no image than a broken icon.
    $("now-art").addEventListener("error", () => { $("now-art").hidden = true; });
    $("power").addEventListener("change", (event) =>
      act("POST", "api/jukebox", { active: event.target.checked }, event.target.checked ? t("jukebox_turned_on") : t("jukebox_turned_off"))
    );
    $("skip").addEventListener("click", () => act("POST", "api/skip", undefined, t("skipped")));
    $("freeze").addEventListener("click", () => act("POST", "api/freeze", { frozen: !status.frozen }));
    $("copy-url").addEventListener("click", copyUrl);
    $("print").addEventListener("click", printSheet);
    $("rotate").addEventListener("click", () => { $("rotate-confirm").hidden = false; $("rotate").hidden = true; });
    $("rotate-no").addEventListener("click", () => { $("rotate-confirm").hidden = true; $("rotate").hidden = false; });
    $("rotate-yes").addEventListener("click", async () => {
      $("rotate-confirm").hidden = true;
      $("rotate").hidden = false;
      await act("POST", "api/guest-access/rotate", undefined, t("rotation_started"));
    });

    try {
      settings = await api("GET", "api/settings");
      renderSettings();
    } catch (err) {
      toast(t("settings_load_failed"));
    }
    await refreshStatus();
    const saved = store.get("sobo.tab");
    selectTab(TABS.includes(saved) ? saved : "live");
    setInterval(() => { if (!document.hidden) refreshStatus(); }, POLL_MS);
  }

  boot();
})();
