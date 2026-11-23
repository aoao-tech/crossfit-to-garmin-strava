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
