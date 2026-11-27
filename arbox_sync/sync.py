"""Sync logic: Garmin decides whether there was training, Arbox only fills in the WOD.

Rules (pure functions, tested without network):
- No HIIT/cardio activity on a day means no training: Arbox is not contacted.
- More than one training activity on a day: change nothing, report AMBIGUOUS.
- An activity already carrying the sync marker, or one the user renamed or described by hand,
  is never touched (idempotent, never overwrites manual edits).
- The day's WOD is resolved once and written to every destination (Garmin, and Strava when
  set up). Each destination applies the rules above on its own, so a day already done on
  Garmin can still be filled in on Strava, and a Strava problem never stops the Garmin sync.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from arbox_sync import config
from arbox_sync.arbox_client import ArboxAuthError, Wod
from arbox_sync.garmin_client import Activity
from arbox_sync.strava_client import StravaAuthError, find_match

logger = logging.getLogger(__name__)


class Outcome(str, Enum):
    NO_TRAINING = "no_training"
    AMBIGUOUS = "ambiguous"
    MATCH = "match"
    SKIPPED = "skipped"
    NO_WOD = "no_wod"
    WOULD_UPDATE = "would_update"
    UPDATED = "updated"


class StravaOutcome(str, Enum):
    NOT_FOUND = "strava_not_found"  # Strava hasn't received this activity yet; a later run catches it
    SKIPPED = "strava_skipped"
    NO_WOD = "strava_no_wod"
    WOULD_UPDATE = "strava_would_update"
    UPDATED = "strava_updated"
    ERROR = "strava_error"
    AUTH_FAILED = "strava_auth_failed"


@dataclass(frozen=True)
class Update:
    activity_id: int
    name: str
    description: str


def select_activity(activities: tuple[Activity, ...]) -> tuple[Activity | None, Outcome]:
    training = [a for a in activities if a.type_key in config.TRAINING_TYPE_KEYS]
    if not training:
        return None, Outcome.NO_TRAINING
    if len(training) > 1:
        return None, Outcome.AMBIGUOUS
    return training[0], Outcome.MATCH


def is_default_name(name: str) -> bool:
    return name.strip().lower().endswith(config.DEFAULT_NAME_SUFFIXES)


def is_untouched_text(name: str, description: str) -> bool:
    """Still exactly as the watch/app created it: default name and no description."""
    return not description.strip() and is_default_name(name)


def is_untouched(activity: Activity) -> bool:
    return is_untouched_text(activity.name, activity.description)


def build_update(activity: Activity, wod: Wod) -> Update | None:
    if config.SYNC_MARKER in activity.description or not is_untouched(activity):
        return None
    description = f"{wod.text}\n\n{config.SYNC_MARKER}"
    return Update(activity.activity_id, wod.title, description)


def resolve_wod(day: date, arbox: Any, crossfitey: Any) -> Wod | None:
    """Pick the right box's WOD for a training day.

    Arbox-first: if there is no second source, use Arbox (unchanged behaviour).
    Otherwise check whether you booked a class at Arbox that day. Booked means
    Arbox (the common case); not booked means the rare Even Yehuda case, so the
    CrossFitEY source is consulted only then. If the registration check itself
    fails, we assume Arbox (the home box).
    """
    if crossfitey is None:
        return arbox.get_wod(day)
    try:
        registered = arbox.is_registered(day)
    except (ArboxAuthError, RuntimeError) as exc:
        logger.debug("%s: registration check failed (%s); assuming Arbox", day, type(exc).__name__)
        registered = True
    if registered:
        logger.debug("%s: booked at Arbox -> Arbox WOD", day)
        return arbox.get_wod(day)
    logger.debug("%s: not booked at Arbox -> trying Even Yehuda WOD", day)
    return crossfitey.get_wod(day)


class WodResolver:
    """Resolves each day's WOD at most once per run, shared by all destinations."""

    def __init__(self, arbox: Any, crossfitey: Any) -> None:
        self._arbox, self._crossfitey = arbox, crossfitey
        self._cache: dict[date, Wod | None] = {}

    def get(self, day: date) -> Wod | None:
        if day not in self._cache:
            self._cache[day] = resolve_wod(day, self._arbox, self._crossfitey)
        return self._cache[day]


def sync_day(day: date, garmin: Any, arbox: Any, crossfitey: Any = None, *, dry_run: bool,
             activities: tuple[Activity, ...] | None = None, wods: WodResolver | None = None) -> Outcome:
    if activities is None:
        activities = tuple(garmin.list_activities(day))
    activity, outcome = select_activity(activities)
    if activity is None:
        logger.debug("%s: %s", day, outcome.value)
        return outcome
    if config.SYNC_MARKER in activity.description or not is_untouched(activity):
        logger.debug("%s: activity already synced or edited by hand", day)
        return Outcome.SKIPPED
    wod = wods.get(day) if wods is not None else resolve_wod(day, arbox, crossfitey)
    if wod is None:
        logger.debug("%s: training found but no WOD available for that day", day)
        return Outcome.NO_WOD
    update = build_update(activity, wod)
    if dry_run:
        logger.debug("%s: would set title %r and a %d-char description", day, update.name, len(update.description))
        return Outcome.WOULD_UPDATE
    garmin.update_activity(update.activity_id, name=update.name, description=update.description)
    return Outcome.UPDATED


def sync_strava_day(day: date, activities: tuple[Activity, ...], strava: Any, wods: WodResolver, *,
                    dry_run: bool) -> StravaOutcome | None:
    """Write the day's WOD onto the Strava copy of the Garmin training activity.

    Returns None when Garmin shows no single training activity (nothing to mirror).
    """
    activity, _ = select_activity(activities)
    if activity is None:
        return None
    match = find_match(strava.activities_on(day), datetime.fromisoformat(activity.start_local))
    if match is None:
        logger.debug("%s: Strava doesn't have this activity yet", day)
        return StravaOutcome.NOT_FOUND
    if config.SYNC_MARKER in match.description or not is_untouched_text(match.name, match.description):
        logger.debug("%s: Strava activity already synced or edited by hand", day)
        return StravaOutcome.SKIPPED
    wod = wods.get(day)
    if wod is None:
        return StravaOutcome.NO_WOD
    if dry_run:
        logger.debug("%s: would update the Strava activity too", day)
        return StravaOutcome.WOULD_UPDATE
    strava.update_activity(match, name=wod.title, description=f"{wod.text}\n\n{config.SYNC_MARKER}")
    return StravaOutcome.UPDATED


def _strava_step(day: date, activities: tuple[Activity, ...], strava: Any, wods: WodResolver,
                 dry_run: bool) -> StravaOutcome | None:
    """Strava for one day, never raising: a Strava problem must not stop the Garmin sync."""
    try:
        return sync_strava_day(day, activities, strava, wods, dry_run=dry_run)
    except StravaAuthError:
        logger.warning("Strava login expired or was rejected; skipping Strava for this run.")
        return StravaOutcome.AUTH_FAILED
    except RuntimeError as exc:
        logger.warning("%s: Strava request failed (%s); will retry next run.", day, exc)
        return StravaOutcome.ERROR


def run_sync(end_day: date, *, days: int, garmin: Any, arbox: Any, crossfitey: Any = None,
             strava: Any = None, dry_run: bool) -> Counter:
    """Process `days` days ending at `end_day` (inclusive), oldest first."""
    counts: Counter = Counter()
    wods = WodResolver(arbox, crossfitey)
    for offset in range(days - 1, -1, -1):
        day = end_day - timedelta(days=offset)
        activities = tuple(garmin.list_activities(day))
        outcome = sync_day(day, garmin, arbox, crossfitey, dry_run=dry_run, activities=activities, wods=wods)
        counts[outcome] += 1
        if outcome == Outcome.AMBIGUOUS:
            logger.warning("A day had more than one HIIT/cardio activity; left it unchanged.")
        if strava is not None:
            strava_outcome = _strava_step(day, activities, strava, wods, dry_run)
            if strava_outcome is not None:
                counts[strava_outcome] += 1
            if strava_outcome == StravaOutcome.AUTH_FAILED:
                strava = None  # don't keep hammering Strava with a dead login
    return counts
