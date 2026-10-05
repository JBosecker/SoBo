# Frontend

- `guest/` – guest page (HTML, CSS, JS without a framework). `scripts/build_guest_page.py`
  combines it into **one** file with CSP hashes:
  `custom_components/sobo/guest_page.html`. Rebuild after changes; CI checks this.
  Texts live in `I18N` in `guest/app.js` (English default, German translation);
  the HTML contains the English texts with `data-i18n` keys.
- The admin UI is served by the app itself:
  `sobo/backend/src/sobo/static/admin/` (no build step, same i18n approach).
