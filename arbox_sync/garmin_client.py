"""Thin wrapper over python-garminconnect: token login, list and update activities.

Secrets policy: library exception messages can contain tokens or account
details, so they are never re-raised as-is. Only the exception class name
is surfaced.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RELOGIN_HINT = "Run `python -m arbox_sync garmin login` on your own computer and update the GARMIN_TOKENS secret."


class GarminAuthError(Exception):
    """Garmin tokens are missing, expired or rejected."""


@dataclass(frozen=True)
class Activity:
    activity_id: int
    name: str
    description: str
    type_key: str
    start_local: str  # "YYYY-MM-DD HH:MM:SS" in the activity's local time

    @property
    def local_date(self) -> str:
        return self.start_local[:10]


def parse_activity(raw: dict[str, Any]) -> Activity:
    activity_type = raw.get("activityType") or {}
    return Activity(
        activity_id=int(raw["activityId"]),
        name=raw.get("activityName") or "",
        description=raw.get("description") or "",
        type_key=activity_type.get("typeKey") or "",
        start_local=raw.get("startTimeLocal") or "",
    )


def activities_on_date(activities: Iterable[Activity], day: date) -> tuple[Activity, ...]:
    wanted = day.isoformat()
    return tuple(a for a in activities if a.local_date == wanted)


def _default_api_factory(**kwargs: Any) -> Any:
    from garminconnect import Garmin

    return Garmin(**kwargs)


class GarminClient:
    def __init__(self, api: Any) -> None:
        self._api = api

    @classmethod
    def from_tokens(cls, token_path: Path, api_factory: Callable[..., Any] = _default_api_factory) -> GarminClient:
        """Log in from saved tokens only. Never uses a password.

        The library refreshes the tokens if needed and rewrites token_path.
        """
        if not Path(token_path).is_file():
            raise GarminAuthError(f"No Garmin tokens found. {RELOGIN_HINT}")
        api = api_factory()
        try:
            api.login(tokenstore=str(token_path))
        except Exception as exc:  # library raises many types; never echo the message
            raise GarminAuthError(
                f"Garmin rejected the saved tokens ({type(exc).__name__}). {RELOGIN_HINT}"
            ) from None
        return cls(api)

    def list_activities(self, day: date) -> tuple[Activity, ...]:
        raws = self._api.get_activities_by_date(day.isoformat(), day.isoformat())
        return activities_on_date((parse_activity(r) for r in raws), day)

    def update_activity(self, activity_id: int, *, name: str, description: str) -> None:
        self._api.update_activity(activity_id, {"activityName": name, "description": description})

    def activity_types(self) -> list[dict[str, Any]]:
        return list(self._api.get_activity_types())


def interactive_login(
    email: str,
    password: str,
    token_path: Path,
    ask_code: Callable[[], str],
    api_factory: Callable[..., Any] = _default_api_factory,
) -> bool:
    """Full SSO login (run once at home). Returns True if MFA was required.

    The password is only passed to the library in memory. Only tokens are saved.
    """
    api = api_factory(email=email, password=password, return_on_mfa=True)
    status, state = api.login()
    needed_mfa = status == "needs_mfa"
    if needed_mfa:
        api.resume_login(state, ask_code().strip())
    token_path = Path(token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    api.client.dump(str(token_path))
    return needed_mfa
