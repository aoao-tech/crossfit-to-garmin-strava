"""Sync logic: Garmin decides whether there was training, Arbox only fills in the WOD.

Rules (pure functions, tested without network):
- No HIIT/cardio activity on a day means no training: Arbox is not contacted.
- More than one training activity on a day: change nothing, report AMBIGUOUS.
- An activity already carrying the sync marker, or one the user renamed or described by hand,
  is never touched (idempotent, never overwrites manual edits).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

from arbox_sync import config
from arbox_sync.arbox_client import ArboxAuthError, Wod
from arbox_sync.garmin_client import Activity

logger = logging.getLogger(__name__)


class Outcome(str, Enum):
    NO_TRAINING = "no_training"
    AMBIGUOUS = "ambiguous"
    MATCH = "match"
    SKIPPED = "skipped"
    NO_WOD = "no_wod"
    WOULD_UPDATE = "would_update"
    UPDATED = "updated"


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


def is_untouched(activity: Activity) -> bool:
    return not activity.description.strip() and is_default_name(activity.name)


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


def sync_day(day: date, garmin: Any, arbox: Any, crossfitey: Any = None, *, dry_run: bool) -> Outcome:
    activity, outcome = select_activity(tuple(garmin.list_activities(day)))
    if activity is None:
        logger.debug("%s: %s", day, outcome.value)
        return outcome
    if config.SYNC_MARKER in activity.description or not is_untouched(activity):
        logger.debug("%s: activity already synced or edited by hand", day)
        return Outcome.SKIPPED
    wod = resolve_wod(day, arbox, crossfitey)
    if wod is None:
        logger.debug("%s: training found but no WOD available for that day", day)
        return Outcome.NO_WOD
    update = build_update(activity, wod)
    if dry_run:
        logger.debug("%s: would set title %r and a %d-char description", day, update.name, len(update.description))
        return Outcome.WOULD_UPDATE
    garmin.update_activity(update.activity_id, name=update.name, description=update.description)
    return Outcome.UPDATED


def run_sync(end_day: date, *, days: int, garmin: Any, arbox: Any, crossfitey: Any = None,
             dry_run: bool) -> Counter:
    """Process `days` days ending at `end_day` (inclusive), oldest first."""
    counts: Counter = Counter()
    for offset in range(days - 1, -1, -1):
        outcome = sync_day(end_day - timedelta(days=offset), garmin, arbox, crossfitey, dry_run=dry_run)
        counts[outcome] += 1
        if outcome == Outcome.AMBIGUOUS:
            logger.warning("A day had more than one HIIT/cardio activity; left it unchanged.")
    return counts
