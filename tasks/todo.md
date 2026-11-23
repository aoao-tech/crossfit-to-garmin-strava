# Arbox -> Garmin WOD sync - progress

Plan: see project plan (GitHub Actions, every 2 days, python-garminconnect 0.3.20, Python 3.12).

## Phase 1 - Capture and document Arbox API (done 2026-11-22: HTTP Toolkit MCP dump -> tools/capture_to_har.py -> mitmproxy2swagger)
- [x] Repo scaffold + .gitignore
- [x] Capture guide (docs/CAPTURE_GUIDE.md)
- [ ] User: emulator + APK install + HTTP Toolkit
- [ ] User: capture login, today's WOD, past days; export HAR to captures/raw/
- [ ] Sanitize HAR -> captures/clean.har (local only, never committed) (tools/sanitize_har.py + tests)
- [ ] mitmproxy2swagger pass 1, curate paths, pass 2 with examples
- [ ] API_NOTES.md
- [ ] Review with user

## Phase 2 - Arbox client (done 2026-11-22: token auth, arbox login / arbox wod, ARBOX_TOKEN secret set)
## Phase 3 - Garmin client (CI smoke test early)
- [x] garminconnect 0.3.20 wrapper: token login, list by local date, update name+description
- [x] CLI: garmin login / activities / types / check
- [x] garmin-smoke workflow (manual, read-only, token write-back)
- [x] garmin login done (no MFA). HIIT type_key = "hiit", default name = "HIIT"
- [x] GARMIN_TOKENS secret set; smoke run passed from GitHub Actions (2026-11-21)
- [x] SECRETS_PAT set (2026-11-21)
- [ ] After 2026-11-22 21:40 Israel time (access token expiry): run garmin-smoke and confirm "Saved refreshed tokens"
## Phase 4 - Sync logic (built 2026-11-22: Garmin-first, dry-run verified on 10 real days; real write not yet tested)
## Phase 5 - GitHub Actions schedule (done 2026-11-22: sync.yml every 2 days, cloud dry run passed)
