# SoBo – Releasing

## How a release works

1. Versions agree everywhere (checked by `tests/test_app_config.py` and again by the
   release workflow): `sobo/config.yaml` (`version`), `custom_components/sobo/manifest.json`,
   `sobo/backend/pyproject.toml` and a `## <version>` entry in `sobo/CHANGELOG.md`.
2. Create a GitHub release with the tag `<version>` (e.g. `0.1.0`, a leading `v` is
   accepted) on `main`. Paste the changelog entry as release notes.
3. The workflow `.github/workflows/release.yml` then
   - builds `ghcr.io/jbosecker/amd64-sobo` and `ghcr.io/jbosecker/aarch64-sobo` on native
     runners, pushes them with the tags `<version>` and `latest` and signs them with Cosign
     (keyless, GitHub OIDC),
   - combines them into the multi-arch image `ghcr.io/jbosecker/sobo` (the `image` in
     `sobo/config.yaml`), signs it and verifies the signature.
   A tag that already exists in GHCR is not pushed again (`skip-existing`): bump the version.
4. Home Assistant offers the update to everyone who added the repository; HACS shows the
   new integration release.

After a release, set the next development version only together with the next release
(the Supervisor pulls `ghcr.io/jbosecker/sobo:<version>`, so `config.yaml` on `main` must
always point to an existing image).

## First release (one-time steps, by the repository owner)

- [ ] Make the repository public (Settings → General → Danger Zone). HACS and the
      Supervisor download files without authentication.
- [ ] Repository description and topics (e.g. `home-assistant`, `hacs`, `sonos`,
      `jukebox`, `home-assistant-addon`); HACS validates that they exist.
- [ ] Publish the release `0.1.0` (see above) and wait for the workflow.
- [ ] GHCR packages `sobo`, `amd64-sobo`, `aarch64-sobo`: Package settings → visibility
      **Public** (packages created from a private repository start as private) and
      "Connect repository" if they are not linked yet.
- [ ] CI job `hacs` runs once the repository is public; it should be green.
- [ ] Optional: submit the integration to the HACS default store and the app repository
      to the community list later, after the real test.

## Installing (for users)

- App: Settings → Apps → app store (formerly add-on store) → ⋮ → Repositories → add
  `https://github.com/JBosecker/SoBo`, then install **SoBo**.
- Integration: HACS → ⋮ → Custom repositories → `https://github.com/JBosecker/SoBo`,
  category *Integration*, install **SoBo**, restart Home Assistant. The app announces
  itself; confirm the discovered SoBo under Settings → Devices & services.

## Local development of the app

With `image` set, the Supervisor pulls the published image instead of building the
folder. To test local changes in the devcontainer, remove the `image` line from the copy
of `sobo/config.yaml` you install there (do not commit that change).

## First real test (after 0.1.0)

Not part of the implementation plan, but needed before recommending SoBo to others
(plan section 10). Suggested order:

1. Install app and integration, choose speaker, account and base playlist.
2. Guest flow on two phones over mobile data (cloudhook): join, search, suggest, vote,
   rotation, presence code, jukebox off/on.
3. Sonos app interaction: start something else → `manual_override` banner → take over again.
4. Cloudhook limits with Locust (`sobo/backend/loadtest/locustfile.py`,
   `SOBO_TARGET=webhook`, host = cloudhook URL): wait time 10/20/30 s, 50–100 users;
   check for aborted long polls and the fallback to polling, then set the default
   `long_poll_timeout` accordingly.
5. AppArmor on HAOS: the app log and the host log (`ha host logs | grep DENIED`) must
   stay free of denials for the SoBo profile.
6. Note results and any changed defaults in `docs/STATUS.md`.
