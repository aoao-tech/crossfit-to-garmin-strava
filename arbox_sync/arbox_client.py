"""Arbox member API client: token auth and the workout (WOD) for a date.

See api/API_NOTES.md for how these endpoints were discovered.
Tokens and passwords never appear in exception messages or logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

from arbox_sync import config

RELOGIN_HINT = "Run `python -m arbox_sync arbox login` on your own computer and update the ARBOX_TOKEN secret."


class ArboxAuthError(Exception):
    """Arbox token missing, expired or rejected, or login credentials wrong."""


@dataclass(frozen=True)
class Section:
    title: str
    body: str
    workout_type: str


@dataclass(frozen=True)
class Wod:
    date: date
    title: str
    sections: tuple[Section, ...]

    @property
    def text(self) -> str:
        return format_text(self.sections)


def format_text(sections: tuple[Section, ...]) -> str:
    blocks = [f"{s.title}\n{s.body.rstrip()}" if s.title else s.body.rstrip() for s in sections]
    return "\n\n".join(blocks).strip()


def _name(obj: Any) -> str:
    return str((obj or {}).get("name") or "").strip() if isinstance(obj, dict) else ""


def _iter_items(data: Any):
    """The API nests items three levels deep: data[group][section][item]."""
    for group in data or []:
        for section in group or []:
            yield from (item for item in section or [] if isinstance(item, dict))


def parse_workouts(day: date, data: Any) -> Wod | None:
    sections = tuple(
        Section(title=_name(item.get("box_sections")), body=str(item.get("comment") or ""),
                workout_type=_name(item.get("workout_type")))
        for item in _iter_items(data)
        if str(item.get("comment") or "").strip()
    )
    if not sections:
        return None
    return Wod(date=day, title=config.FALLBACK_TITLE, sections=sections)


def registration_found(classes: Any) -> bool:
    """True if any class in the day's schedule has a booking for the current user."""
    return any(
        bool(item.get("user_booked"))
        for item in (classes or [])
        if isinstance(item, dict)
    )


def load_token(path: Path | None = None) -> str:
    """ARBOX_TOKEN env var (CI) wins over the local token file."""
    env = os.getenv("ARBOX_TOKEN", "").strip()
    if env:
        return env
    token_file = Path(path or config.arbox_token_path())
    if token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise ArboxAuthError(f"No Arbox token found. {RELOGIN_HINT}")


def save_token(token: str, path: Path | None = None) -> Path:
    token_file = Path(path or config.arbox_token_path())
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return token_file


class ArboxClient:
    def __init__(self, token: str, session: Any = None) -> None:
        self._token = token
        self._session = session or requests.Session()

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {**config.ARBOX_APP_HEADERS, "content-type": "application/json", "accesstoken": self._token}
        resp = self._session.post(f"{config.ARBOX_API_BASE}{path}", json=body, headers=headers,
                                  timeout=config.HTTP_TIMEOUT_SECONDS)
        if resp.status_code in (401, 403):
            raise ArboxAuthError(f"Arbox rejected the saved token (HTTP {resp.status_code}). {RELOGIN_HINT}")
        if resp.status_code != 200:
            raise RuntimeError(f"Arbox request {path} failed with HTTP {resp.status_code}")
        return resp.json()

    def get_wod(self, day: date) -> Wod | None:
        payload = self._post("/api/v2/logbook/workouts", {"date": day.isoformat()})
        return parse_workouts(day, (payload or {}).get("data"))

    def is_registered(self, day: date) -> bool:
        """True when you booked a class at your home Arbox box on `day`.

        Reads the schedule for that day and checks the per-class `user_booked`
        field (a booking id when you registered, null when you did not).
        """
        payload = self._post(
            "/api/v2/schedule/betweenDates",
            {
                "from": day.isoformat(),
                "to": day.isoformat(),
                "locations_box_id": config.ARBOX_LOCATIONS_BOX_ID,
                "boxes_id": config.ARBOX_BOXES_ID,
            },
        )
        return registration_found((payload or {}).get("data"))

    @staticmethod
    def login(email: str, password: str, session: Any = None) -> str:
        """Exchange email+password for a token. The password is not stored anywhere."""
        http = session or requests.Session()
        headers = {**config.ARBOX_APP_HEADERS, "content-type": "application/json"}
        resp = http.post(f"{config.ARBOX_API_BASE}/api/v2/user/login", json={"email": email, "password": password},
                         headers=headers, timeout=config.HTTP_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise ArboxAuthError(f"Arbox login failed (HTTP {resp.status_code}). Check email and password.")
        token = ((resp.json() or {}).get("data") or {}).get("token")
        if not token:
            raise ArboxAuthError("Arbox login returned no token.")
        return str(token)
