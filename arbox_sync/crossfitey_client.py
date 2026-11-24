"""CrossFit Even Yehuda ("Box WOD") client: NextAuth session login and the WOD for a date.

This is the second WOD source. The sync consults it only when you were *not*
registered at Arbox that day (the rare case). The site serves the current week
only, so `get_wod` returns a WOD for dates in the current week and None otherwise.

Passwords are never stored; only the NextAuth session cookie is kept (it lasts
about 90 days). Tokens and passwords never appear in exception messages or logs.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from arbox_sync import config
from arbox_sync.arbox_client import Section, Wod

RELOGIN_HINT = (
    "Run `python -m arbox_sync crossfitey login` on your own computer "
    "and update the CROSSFITEY_SESSION secret."
)
_USER_AGENT = "garmin-to-arbox"


class CrossFitEyAuthError(Exception):
    """CrossFitEY session missing, expired or rejected, or login credentials wrong."""


def extract_workouts(flight: str) -> list[dict]:
    """Pull every ``"workout":{...}`` object out of a Next.js RSC/flight payload.

    The page embeds each day's workout as a JSON object inside the server-component
    stream; we balance braces (ignoring strings) to slice each one out and parse it.
    """
    out: list[dict] = []
    key = '"workout":'
    i = flight.find(key)
    while i != -1:
        start = i + len(key)
        depth = 0
        in_str = False
        esc = False
        j = start
        while j < len(flight):
            c = flight[j]
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = not in_str
            elif not in_str:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
            j += 1
        try:
            out.append(json.loads(flight[start:j]))
        except json.JSONDecodeError:
            pass
        i = flight.find(key, j)
    return out


def day_label(day: date) -> str:
    """The title the site gives a day, e.g. 'Monday, Nov 23' (no leading zero)."""
    return f"{day:%A}, {day:%b} {day.day}"


def _week_start(d: date) -> date:
    """The Sunday that begins the site's week containing `d` (weeks run Sun..Sat)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def week_offset(day: date, today: date) -> int:
    """How many weeks back `day` is from `today`, as the site's ?offset= param.

    0 is this week, -1 last week, and so on. The site serves one week per request,
    so the WOD for any past day is still reachable at its own week's offset.
    """
    return (_week_start(day) - _week_start(today)).days // 7


def workout_to_wod(day: date, workout: dict) -> Wod | None:
    sections = tuple(
        Section(
            title=str(block.get("scheme") or ""),
            body=str(block.get("instructions") or ""),
            workout_type=str(workout.get("track") or ""),
        )
        for block in (workout.get("blocks") or [])
        if str(block.get("instructions") or "").strip()
    )
    if not sections:
        return None
    return Wod(date=day, title=config.FALLBACK_TITLE, sections=sections)


def select_workout(day: date, workouts: list[dict]) -> Wod | None:
    """Pick the CrossFit-track workout whose title matches `day`."""
    label = day_label(day)
    for workout in workouts:
        if str(workout.get("track") or "") != config.CROSSFITEY_TRACK:
            continue
        if str(workout.get("title") or "").strip() != label:
            continue
        return workout_to_wod(day, workout)
    return None


def login(email: str, password: str, session: Any = None) -> dict[str, str]:
    """Log in via NextAuth credentials and return the session cookies.

    The password is used only for this exchange and is never stored.
    """
    http = session or requests.Session()
    http.headers["user-agent"] = _USER_AGENT
    base = config.CROSSFITEY_BASE
    try:
        csrf = http.get(f"{base}/api/auth/csrf", timeout=config.HTTP_TIMEOUT_SECONDS).json()["csrfToken"]
        http.post(
            f"{base}/api/auth/callback/credentials",
            data={
                "csrfToken": csrf,
                "email": email,
                "password": password,
                "callbackUrl": f"{base}/",
                "json": "true",
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        who = http.get(f"{base}/api/auth/session", timeout=config.HTTP_TIMEOUT_SECONDS).json()
    except requests.RequestException as exc:  # never leak library detail that may hold input
        raise CrossFitEyAuthError(f"CrossFitEY login failed ({type(exc).__name__}).") from None
    if not (isinstance(who, dict) and who.get("user")):
        raise CrossFitEyAuthError("CrossFitEY login failed. Check email and password.")
    return requests.utils.dict_from_cookiejar(http.cookies)


def load_session(path: Path | None = None) -> dict[str, str]:
    """CROSSFITEY_SESSION env var (CI) wins over the local session file."""
    env = os.getenv("CROSSFITEY_SESSION", "").strip()
    if env:
        return json.loads(env)
    session_file = Path(path or config.crossfitey_session_path())
    if session_file.is_file():
        text = session_file.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
    raise CrossFitEyAuthError(f"No CrossFitEY session found. {RELOGIN_HINT}")


def session_token(cookies: dict[str, str]) -> str | None:
    """The NextAuth session-token value, whatever cookie prefix the site uses."""
    for name, value in cookies.items():
        if name.endswith("session-token"):
            return value
    return None


def save_session(cookies: dict[str, str], path: Path | None = None) -> Path:
    session_file = Path(path or config.crossfitey_session_path())
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(cookies), encoding="utf-8")
    try:
        session_file.chmod(0o600)
    except OSError:
        pass
    return session_file


class CrossFitEyClient:
    def __init__(self, cookies: dict[str, str], session: Any = None) -> None:
        self._session = session or requests.Session()
        self._session.headers["user-agent"] = _USER_AGENT
        self._session.cookies.update(cookies)
        self._initial_token = session_token(cookies)

    def _fetch_week(self, offset: int) -> str:
        resp = self._session.get(
            f"{config.CROSSFITEY_BASE}/week",
            params={"offset": offset},
            headers={"RSC": "1"},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        if resp.status_code in (401, 403) or "/login" in resp.url:
            raise CrossFitEyAuthError(f"CrossFitEY rejected the saved session. {RELOGIN_HINT}")
        if resp.status_code != 200:
            raise RuntimeError(f"CrossFitEY /week failed with HTTP {resp.status_code}")
        return resp.text

    def get_wod(self, day: date, today: date | None = None) -> Wod | None:
        """The CrossFit WOD for `day`, fetching that day's own week by offset."""
        today = today or datetime.now(config.TIMEZONE).date()
        offset = week_offset(day, today)
        return select_workout(day, extract_workouts(self._fetch_week(offset)))

    def current_cookies(self) -> dict[str, str]:
        return requests.utils.dict_from_cookiejar(self._session.cookies)

    def session_changed(self) -> bool:
        """True if the server rotated the session token since login (needs saving back)."""
        return session_token(self.current_cookies()) != self._initial_token
