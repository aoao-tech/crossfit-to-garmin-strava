"""Command line entry point: `python -m arbox_sync ...`."""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta

import click

from arbox_sync import config
from arbox_sync.arbox_client import ArboxAuthError, ArboxClient, load_token, save_token
from arbox_sync.crossfitey_client import (
    CrossFitEyAuthError,
    CrossFitEyClient,
    load_session,
    save_session,
)
from arbox_sync.crossfitey_client import login as crossfitey_do_login
from arbox_sync.garmin_client import GarminAuthError, GarminClient, interactive_login
from arbox_sync.sync import Outcome, run_sync

EXIT_AUTH = 2


def _today() -> date:
    return datetime.now(config.TIMEZONE).date()


def _parse_date(_ctx, _param, value: str | None) -> date:
    if value is None:
        return _today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise click.BadParameter("use YYYY-MM-DD") from None


def _garmin() -> GarminClient:
    try:
        return GarminClient.from_tokens(config.garmin_token_path())
    except GarminAuthError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Debug logging for this tool (local use only).")
def main(verbose: bool) -> None:
    # Keep third-party libraries (Garmin HTTP layer, urllib3) at WARNING so they never
    # print tokens, even with -v. Only this package's own logs go to DEBUG.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("arbox_sync").setLevel(logging.DEBUG if verbose else logging.WARNING)


def _arbox() -> ArboxClient:
    try:
        return ArboxClient(load_token())
    except ArboxAuthError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)


def _crossfitey() -> CrossFitEyClient | None:
    """Build the second WOD source if a session is configured, else None (Arbox-only)."""
    try:
        return CrossFitEyClient(load_session())
    except CrossFitEyAuthError:
        return None


@main.command()
@click.option("--date", "day", callback=_parse_date, help="Last day to process, default today (Asia/Jerusalem).")
@click.option("--backfill", "days", default=config.DEFAULT_LOOKBACK_DAYS, show_default=True,
              help="How many days to process, ending at --date.")
@click.option("--apply", is_flag=True, help="Actually write to Garmin. Without it, nothing is changed.")
def sync(day: date, days: int, apply: bool) -> None:
    """Write each day's Arbox WOD into that day's Garmin HIIT/cardio activity."""
    garmin_client, arbox_client = _garmin(), _arbox()
    crossfitey_client = _crossfitey()
    try:
        counts = run_sync(day, days=days, garmin=garmin_client, arbox=arbox_client,
                          crossfitey=crossfitey_client, dry_run=not apply)
    except (ArboxAuthError, GarminAuthError) as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)
    if crossfitey_client is not None and crossfitey_client.session_changed():
        path = save_session(crossfitey_client.current_cookies())
        click.echo(f"CrossFitEY session refreshed, saved to {path}")
    summary = " ".join(f"{o.value}={counts[o]}" for o in Outcome if counts[o])
    click.echo(f"{'' if apply else 'DRY RUN (use --apply to write): '}{days} days: {summary}")
    if counts[Outcome.AMBIGUOUS]:
        click.echo("WARNING: some days had more than one HIIT/cardio activity and were left unchanged.", err=True)


@main.group()
def arbox() -> None:
    """Arbox commands."""


@arbox.command(name="login")
def arbox_login() -> None:
    """One-time login. Saves the token only, never the password."""
    email = click.prompt("Arbox email")
    password = click.prompt("Arbox password", hide_input=True)
    try:
        token = ArboxClient.login(email, password)
    except ArboxAuthError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)
    path = save_token(token, config.arbox_token_path())
    click.echo(f"Logged in. Token saved to {path}")


@arbox.command()
@click.option("--date", "day", callback=_parse_date, help="YYYY-MM-DD, default today (Asia/Jerusalem).")
def wod(day: date) -> None:
    """Print the WOD for a date as JSON ({} when there is none)."""
    client = _arbox()
    try:
        result = client.get_wod(day)
    except ArboxAuthError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)
    payload = {"date": day.isoformat(), "title": result.title, "text": result.text} if result else {}
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@main.group()
def crossfitey() -> None:
    """CrossFit Even Yehuda commands (second WOD source)."""


@crossfitey.command(name="login")
def crossfitey_login() -> None:
    """One-time login. Saves the session cookie only, never the password."""
    email = click.prompt("CrossFitEY email")
    password = click.prompt("CrossFitEY password", hide_input=True)
    try:
        cookies = crossfitey_do_login(email, password)
    except CrossFitEyAuthError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)
    path = save_session(cookies)
    click.echo(f"Logged in. Session saved to {path}")


@crossfitey.command(name="wod")
@click.option("--date", "day", callback=_parse_date, help="YYYY-MM-DD, default today (Asia/Jerusalem).")
def crossfitey_wod(day: date) -> None:
    """Print the CrossFitEY WOD for a date as JSON ({} when there is none)."""
    client = _crossfitey()
    if client is None:
        click.echo("ERROR: no CrossFitEY session. Run `crossfitey login` first.", err=True)
        sys.exit(EXIT_AUTH)
    try:
        result = client.get_wod(day)
    except CrossFitEyAuthError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_AUTH)
    payload = {"date": day.isoformat(), "title": result.title, "text": result.text} if result else {}
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@main.group()
def garmin() -> None:
    """Garmin Connect commands."""


@garmin.command()
def login() -> None:
    """One-time interactive login. Saves tokens only, never the password."""
    email = click.prompt("Garmin email")
    password = click.prompt("Garmin password", hide_input=True)
    path = config.garmin_token_path()
    try:
        needed_mfa = interactive_login(email, password, path, ask_code=lambda: click.prompt("Garmin MFA code"))
    except Exception as exc:  # never echo library messages, they may hold secrets
        click.echo(f"ERROR: Garmin login failed ({type(exc).__name__}). Check email/password and try again.", err=True)
        sys.exit(EXIT_AUTH)
    click.echo(f"Logged in{' (MFA was required)' if needed_mfa else ' (no MFA)'}. Tokens saved to {path}")


@garmin.command()
@click.option("--date", "day", callback=_parse_date, help="YYYY-MM-DD, default today (Asia/Jerusalem).")
def activities(day: date) -> None:
    """List activities on a local date as JSON (local use: shows names)."""
    rows = [
        {
            "activity_id": a.activity_id,
            "name": a.name,
            "type_key": a.type_key,
            "start_local": a.start_local,
            "has_description": bool(a.description),
        }
        for a in _garmin().list_activities(day)
    ]
    click.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@garmin.command()
@click.option("--filter", "text", default="", help="Substring of the type key, e.g. hiit or strength.")
def types(text: str) -> None:
    """List Garmin activity types (typeId, typeKey, parentTypeId)."""
    wanted = [
        {"typeId": t.get("typeId"), "typeKey": t.get("typeKey"), "parentTypeId": t.get("parentTypeId")}
        for t in _garmin().activity_types()
        if text.lower() in str(t.get("typeKey", "")).lower()
    ]
    click.echo(json.dumps(wanted, indent=2))


@garmin.command()
@click.option("--days", default=7, show_default=True, help="How many days back to count.")
@click.option("--date", "day", callback=_parse_date, help="Last day of the window, default today.")
def check(days: int, day: date) -> None:
    """Read-only health check. Prints counts only (safe for public CI logs)."""
    client = _garmin()
    total = sum(len(client.list_activities(day - timedelta(days=i))) for i in range(days))
    click.echo(f"Garmin OK: {total} activities in the last {days} days.")
