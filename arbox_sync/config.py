"""Central configuration. Every value can be overridden with an env var."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo(os.getenv("SYNC_TIMEZONE", "Asia/Jerusalem"))

GARMIN_TOKEN_FILENAME = "garmin_tokens.json"
ARBOX_TOKEN_FILENAME = "arbox_token.txt"

ARBOX_API_BASE = os.getenv("ARBOX_API_BASE", "https://apiappv2.arboxapp.com")
ARBOX_APP_HEADERS = {"whitelabel": "Arbox", "version": "15", "referername": "app"}
HTTP_TIMEOUT_SECONDS = 20

# Which Arbox box/location counts as "my home box" when checking registration.
# These ids come from the member app's schedule/betweenDates request; override per box.
ARBOX_BOXES_ID = int(os.getenv("ARBOX_BOXES_ID", "23"))
ARBOX_LOCATIONS_BOX_ID = int(os.getenv("ARBOX_LOCATIONS_BOX_ID", "6"))

# Second WOD source: CrossFit Even Yehuda ("Box WOD" site, NextAuth session login).
# Only consulted when you were NOT registered at Arbox that day (the rare case).
CROSSFITEY_BASE = os.getenv("CROSSFITEY_BASE", "https://crossfitey.fit")
CROSSFITEY_TRACK = os.getenv("CROSSFITEY_TRACK", "CROSSFIT")
CROSSFITEY_SESSION_FILENAME = "crossfitey_session.json"

# Optional extra destination: Strava, through the same calls the strava.com website makes
# (the mobile API requires app attestation). Login is a browser session cookie.
STRAVA_BASE = os.getenv("STRAVA_BASE", "https://www.strava.com")
STRAVA_SESSION_FILENAME = "strava_session.json"
# The Strava "Remember me" login lasts 30 days. This many days before it expires, a run
# exits with an error on purpose, so GitHub emails you while Strava still works.
STRAVA_RENEW_WARN_DAYS = int(os.getenv("STRAVA_RENEW_WARN_DAYS", "3"))

FALLBACK_TITLE = os.getenv("SYNC_FALLBACK_TITLE", "CrossFit WOD")

# Garmin activity types that count as a CrossFit session. No such activity on a day = no training.
TRAINING_TYPE_KEYS = frozenset(
    k.strip() for k in os.getenv("SYNC_ACTIVITY_TYPES", "hiit,indoor_cardio,cardio").split(",") if k.strip()
)
# Endings of the names Garmin gives new activities of those types ("HIIT", "<City> HIIT", "Cardio"...).
DEFAULT_NAME_SUFFIXES = ("hiit", "cardio")
SYNC_MARKER = "[arbox-sync]"
# Runs are every 2 days; 5 days back still covers every day if GitHub drops one scheduled run.
DEFAULT_LOOKBACK_DAYS = int(os.getenv("SYNC_LOOKBACK_DAYS", "5"))


def arbox_token_path() -> Path:
    """Where the Arbox token is cached locally. CI uses the ARBOX_TOKEN env var instead."""
    override = os.getenv("ARBOX_TOKEN_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".garmin-to-arbox" / ARBOX_TOKEN_FILENAME


def garmin_token_path() -> Path:
    """Where Garmin session tokens live. Own folder (not ~/.garminconnect, which other tools use)."""
    override = os.getenv("GARMIN_TOKEN_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".garmin-to-arbox" / GARMIN_TOKEN_FILENAME


def strava_session_path() -> Path:
    """Where the Strava website session cookie is cached. CI uses STRAVA_SESSION_PATH instead."""
    override = os.getenv("STRAVA_SESSION_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".garmin-to-arbox" / STRAVA_SESSION_FILENAME


def crossfitey_session_path() -> Path:
    """Where the CrossFitEY NextAuth session cookie is cached. CI uses CROSSFITEY_SESSION instead."""
    override = os.getenv("CROSSFITEY_SESSION_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".garmin-to-arbox" / CROSSFITEY_SESSION_FILENAME
