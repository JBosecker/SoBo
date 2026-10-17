# Frontend

- `guest/` – guest page (HTML, CSS, JS without a framework). `scripts/build_guest_page.py`
  combines it into **one** file with CSP hashes:
  `custom_components/sobo/guest_page.html`. Rebuild after changes; CI checks this.
  Texts live in `I18N` in `guest/app.js` (English default, German translation);
  the HTML contains the English texts with `data-i18n` keys.
- `display/` – party display for a TV or tablet, built the same way into
  `custom_components/sobo/display_page.html`. The integration serves it for
  `?view=display` on the guest link; the key comes from the URL fragment (`#key=…`)
  and is sent in the POST body (`action: "display"`).
- The admin UI is served by the app itself:
  `sobo/backend/src/sobo/static/admin/` (no build step, same i18n approach).
