"""Strava client using the strava.com website calls: list activities, edit name/description.

Strava's mobile API requires Google Play Integrity attestation, so it can't be used from a
script. The website works with a normal session cookie: you paste your browser's Cookie
header once (`strava login`) and only that session is kept, never a password.

Calls (see api/API_NOTES.md):
- GET  /athlete/training                        HTML page; its <meta name="csrf-token"> is needed for writes
- GET  /athlete/training_activities?page=N      JSON {models: [...]}, newest first, 20 per page
- PUT  /athlete/training_activities/{id}        JSON body = the activity model with new name/description
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from arbox_sync import config

RELOGIN_HINT = (
    "Run `python -m arbox_sync strava login` on your own computer "
    "and update the STRAVA_SESSION secret."
)
MAX_PAGES = 5
START_TOLERANCE = timedelta(minutes=2)
REMEMBER_PREFIX = "strava_remember"  # strava_remember_id + strava_remember_token ("Remember me")
_USER_AGENT = "crossfit-to-garmin-strava"
_CSRF_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')


class StravaAuthError(Exception):
    """Strava session missing, expired or rejected."""


@dataclass(frozen=True, eq=False)
class StravaActivity:
    activity_id: str
    name: str
    description: str
    start_local: datetime  # naive, in config.TIMEZONE (same clock as Garmin's startTimeLocal)
    raw: dict = field(repr=False)


def parse_cookie_header(raw: str) -> dict[str, str]:
    """Turn a pasted 'Cookie:' header (with or without the prefix) into a dict.

    Split by hand: some sites' cookies (e.g. consent banners) contain characters that make
    the stdlib cookie parser silently drop everything after them.
    """
    text = raw.strip()
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:"):].strip()
    pairs = (part.strip().partition("=") for part in text.split(";"))
    return {name: value for name, _, value in pairs if name}


def remember_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Only the long-lived "Remember me" cookies. They let a script open a fresh session on
    every run, so the short-lived browser session cookie is never stored."""
    return {k: v for k, v in cookies.items() if k.startswith(REMEMBER_PREFIX)}


def session_expiry(cookies: dict[str, str]) -> datetime | None:
    """When the remember token stops working: the `exp` claim inside it (a signed JWT)."""
    token = cookies.get(f"{REMEMBER_PREFIX}_token", "")
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (ValueError, KeyError, TypeError):
        return None


def renewal_due(expiry: datetime | None, now: datetime, warn_days: int) -> bool:
    """True when the login expires within `warn_days` (time to log in again)."""
    return expiry is not None and expiry - now <= timedelta(days=warn_days)


def parse_activity(model: dict) -> StravaActivity | None:
    try:
        start = datetime.strptime(str(model["start_time"]), "%Y-%m-%dT%H:%M:%S%z")
    except (KeyError, ValueError):
        return None
    local = start.astimezone(config.TIMEZONE).replace(tzinfo=None)
    return StravaActivity(str(model.get("id")), str(model.get("name") or ""),
                          str(model.get("description") or ""), local, raw=model)


def find_match(activities: list[StravaActivity], garmin_start: datetime) -> StravaActivity | None:
    """The Strava activity that started at the same moment as the Garmin one (Strava imports it)."""
    close = [a for a in activities if abs(a.start_local - garmin_start) <= START_TOLERANCE]
    return min(close, key=lambda a: abs(a.start_local - garmin_start)) if close else None


def load_session(path: Path | None = None) -> dict[str, str]:
    """STRAVA_SESSION env var (CI) wins over the local session file."""
    env = os.getenv("STRAVA_SESSION", "").strip()
    if env:
        return json.loads(env)
    session_file = Path(path or config.strava_session_path())
    if session_file.is_file():
        text = session_file.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
    raise StravaAuthError(f"No Strava session found. {RELOGIN_HINT}")


def save_session(cookies: dict[str, str], path: Path | None = None) -> Path:
    session_file = Path(path or config.strava_session_path())
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(cookies), encoding="utf-8")
    try:
        session_file.chmod(0o600)
    except OSError:
        pass
    return session_file


class StravaClient:
    def __init__(self, cookies: dict[str, str], session: Any = None) -> None:
        self._http = session or requests.Session()
        self._http.headers["user-agent"] = _USER_AGENT
        for name, value in cookies.items():
            self._http.cookies.set(name, value, domain=".strava.com", path="/")
        self._csrf: str | None = None
        self._initial = remember_cookies(cookies)

    def current_cookies(self) -> dict[str, str]:
        """The remember cookies as they are now (Strava may have issued new ones)."""
        jar = self._http.cookies
        pairs = jar.items() if isinstance(jar, dict) else ((c.name, c.value) for c in jar)
        return remember_cookies(dict(pairs))

    def session_changed(self) -> bool:
        return self.current_cookies() != self._initial

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            return getattr(self._http, method)(url, timeout=config.HTTP_TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as exc:  # no library detail: it may echo request data
            raise RuntimeError(f"Strava request failed ({type(exc).__name__})") from None

    def _csrf_token(self) -> str:
        if self._csrf is None:
            resp = self._call("get", f"{config.STRAVA_BASE}/athlete/training")
            if "/login" in resp.url or resp.status_code in (401, 403):
                raise StravaAuthError(f"Strava session expired or rejected. {RELOGIN_HINT}")
            match = _CSRF_RE.search(resp.text or "")
            if resp.status_code != 200 or not match:
                raise RuntimeError(f"Strava training page failed (HTTP {resp.status_code})")
            self._csrf = match.group(1)
        return self._csrf

    def _headers(self) -> dict[str, str]:
        return {"x-csrf-token": self._csrf_token(), "x-requested-with": "XMLHttpRequest",
                "accept": "application/json", "origin": config.STRAVA_BASE,
                "referer": f"{config.STRAVA_BASE}/athlete/training"}

    def _page(self, page: int) -> list[dict]:
        resp = self._call("get", f"{config.STRAVA_BASE}/athlete/training_activities",
                          params={"new_activity_only": "false", "page": page}, headers=self._headers())
        if resp.status_code in (401, 403):
            raise StravaAuthError(f"Strava session expired or rejected. {RELOGIN_HINT}")
        if resp.status_code != 200:
            raise RuntimeError(f"Strava activity list failed (HTTP {resp.status_code})")
        return list((resp.json() or {}).get("models") or [])

    def activities_on(self, day: date) -> list[StravaActivity]:
        """Activities that started on `day` (local time). Pages back until past that day."""
        found: list[StravaActivity] = []
        for page in range(1, MAX_PAGES + 1):
            acts = [a for a in map(parse_activity, self._page(page)) if a is not None]
            found += [a for a in acts if a.start_local.date() == day]
            if not acts or acts[-1].start_local.date() < day:
                break
        return found

    def update_activity(self, activity: StravaActivity, *, name: str, description: str) -> None:
        body = {**activity.raw, "name": name, "description": description}
        resp = self._call("put", f"{config.STRAVA_BASE}/athlete/training_activities/{activity.activity_id}",
                          data=json.dumps(body), headers={**self._headers(), "content-type": "application/json"})
        if resp.status_code in (401, 403):
            raise StravaAuthError(f"Strava session expired or rejected. {RELOGIN_HINT}")
        if resp.status_code != 200:
            raise RuntimeError(f"Strava update failed (HTTP {resp.status_code})")

    def check(self) -> int:
        """Confirm the session works; returns how many activities are on the first page."""
        return len(self._page(1))
