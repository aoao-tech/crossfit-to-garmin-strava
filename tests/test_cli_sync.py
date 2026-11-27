from datetime import date

from click.testing import CliRunner

from arbox_sync import cli
from arbox_sync.arbox_client import ArboxAuthError
from arbox_sync.sync import Outcome


def _patch(monkeypatch, seen, error=None):
    def fake_run(end_day, *, days, garmin, arbox, crossfitey, strava, dry_run):
        if error:
            raise error
        seen.update(end_day=end_day, days=days, dry_run=dry_run)
        from collections import Counter
        return Counter({Outcome.UPDATED: 1, Outcome.NO_TRAINING: days - 1})

    monkeypatch.setattr(cli, "run_sync", fake_run)
    monkeypatch.setattr(cli, "_garmin", lambda: object())
    monkeypatch.setattr(cli, "_arbox", lambda: object())
    monkeypatch.setattr(cli, "_crossfitey", lambda: None)
    monkeypatch.setattr(cli, "_strava", lambda: None)


def test_sync_is_dry_run_by_default(monkeypatch):
    seen = {}
    _patch(monkeypatch, seen)
    result = CliRunner().invoke(cli.main, ["sync", "--date", "2026-11-22"])
    assert result.exit_code == 0, result.output
    assert seen == {"end_day": date(2026, 11, 22), "days": 5, "dry_run": True}
    assert "DRY RUN" in result.output


def test_sync_apply_and_backfill(monkeypatch):
    seen = {}
    _patch(monkeypatch, seen)
    result = CliRunner().invoke(cli.main, ["sync", "--apply", "--backfill", "10", "--date", "2026-11-22"])
    assert result.exit_code == 0, result.output
    assert seen["dry_run"] is False and seen["days"] == 10
    assert "updated=1" in result.output and "no_training=9" in result.output


def test_sync_auth_error_exits_2(monkeypatch):
    _patch(monkeypatch, {}, error=ArboxAuthError("Arbox rejected the saved token."))
    result = CliRunner().invoke(cli.main, ["sync", "--apply"])
    assert result.exit_code == 2
    assert "Arbox rejected" in result.output
