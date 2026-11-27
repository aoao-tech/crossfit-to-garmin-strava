# Arbox member API: notes

Reverse-engineered from the Arbox Android app (v7.2.7) traffic on 2026-11-22.
Unofficial: Arbox does not document or support this API. Full spec: [arbox-openapi.yaml](arbox-openapi.yaml)
(generated with mitmproxy2swagger from a sanitized capture; all example values are synthetic).

Base URL: `https://apiappv2.arboxapp.com`

## Headers the app sends on every request

| Header | Value | Notes |
|---|---|---|
| `content-type` | `application/json` | |
| `accesstoken` | JWT from login | the auth header (no `Authorization: Bearer`) |
| `refreshtoken` | refresh token from login | sent alongside, purpose unclear |
| `whitelabel` | `Arbox` | app constant |
| `version` | `15` | app API version constant |
| `referername` | `app` | app constant |

## Login

`POST /api/v2/user/login`

```json
{ "email": "member@example.com", "password": "..." }
```

Response `data` includes `token` (JWT, the access token), `refreshToken`, plus the member's id and name.

- **Password login works**, so no emailed code is needed once the account has a password.
- Observed lifetimes (decoded `exp` claims): the access token's `exp` was about **3 years** after login;
  the refresh token's `exp` was about the login time itself. In practice the access token is what matters.
- No refresh call was seen in the capture. If a request returns 401, log in again.

## Workout (WOD) for a date

`POST /api/v2/logbook/workouts`

```json
{ "date": "2026-11-22" }
```

- Works for past dates and for future dates the box already published (the next day was available).
- Response `data` is nested three levels: `data[group][section][item]`. Each item is one section of the
  day's workout:

| Field | Meaning | Example |
|---|---|---|
| `name` | the date | `2026-11-22` |
| `box_sections.name` | section title | `Strength`, `Metcon`, `ACCESSORY WORK` |
| `workout_type.name` | scoring type | `AMRAP`, `RFT`, `General` |
| `box_categories.name` | class category | `CrossFit` |
| `comment` | **the section's full text** (multi-line) | `12 DB PUSH PRESS\n14 TOES TO BAR...` |

- A day with no programming is expected to return an empty `data` list (not yet observed).

## How the sync will use it

- **Title:** the WOD has no single "name" field, so the chosen rule (WOD name, else fallback) gives
  "CrossFit WOD". Open proposal: append the Metcon's `workout_type.name` (for example "CrossFit WOD - AMRAP").
- **Description:** every section as `SECTION NAME` followed by its `comment`, in API order.

## Arbox: class booking for a day (box detection)

`POST /api/v2/schedule/betweenDates` (same headers as above)

```json
{ "from": "2026-11-25", "to": "2026-11-25", "locations_box_id": 6, "boxes_id": 23 }
```

- Returns `data`: one item per class at that box and location on those dates.
- Each class has `user_booked`: a booking id when **you** booked it, `null` otherwise. Any class with
  `user_booked` set means you trained at this box that day.
- `boxes_id` / `locations_box_id` come from `GET /api/v2/boxes/locations` (a member can belong to
  several boxes; use your home box).

## Second box: "Box WOD" site (NextAuth)

- Login: `GET /api/auth/csrf` → `POST /api/auth/callback/credentials` (form: `csrfToken`, `email`,
  `password`, `json=true`) → session cookie (`…next-auth.session-token`, about 90 days).
- WOD: `GET /week?offset=N` with header `RSC: 1` (0 = this week, -1 = last week). The response is a
  React Server Components stream; each day's workout is an embedded `"workout":{...}` JSON object with
  `track`, `title` ("Monday, Nov 23") and `blocks[].instructions`.

## Strava: the website's own calls

The Strava app requires Google Play Integrity attestation (`401 attestation_required`), so it can't be
used from a script. The strava.com website works with a plain session:

- Login: the browser's **"Remember me"** cookies `strava_remember_id` + `strava_remember_token`. The
  token is a JWT whose `exp` claim is 30 days after login; Strava does not extend it. Sending only these
  two cookies is enough to open a fresh session.
- `GET /athlete/training` — HTML page; `<meta name="csrf-token" content="...">` is needed for the calls below.
- `GET /athlete/training_activities?new_activity_only=false&page=N` — headers `x-requested-with:
  XMLHttpRequest`, `x-csrf-token`. JSON `{models, page, perPage: 20, total}`, newest first. Each model has
  `id`, `name`, `description`, `sport_type`, `start_time` (UTC, e.g. `2026-11-25T16:40:02+0000`, the same
  instant as Garmin's start), and more.
- `PUT /athlete/training_activities/{id}` — same headers plus `content-type: application/json`; body is
  the activity model with the new `name` / `description`. Returns 200.
