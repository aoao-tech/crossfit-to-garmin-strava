import base64
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from arbox_sync import cli
from arbox_sync import strava_client as strava_mod
from arbox_sync.sync import StravaOutcome


def token_expiring_in(days: float) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())

    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{part({'alg': 'HS256'})}.{part({'exp': exp})}.sig"


class FakeClient:
    def __init__(self, days_left=20, changed=False):
        self.cookies = {"strava_remember_id": "1", "strava_remember_token": token_expiring_in(days_left)}
        self.changed = changed

    def session_changed(self):
        return self.changed

    def current_cookies(self):
        return self.cookies


# --- strava login ------------------------------------------------------------

def test_login_rejects_a_header_without_remember_cookies(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_SESSION_PATH", str(tmp_path / "s.json"))
    result = CliRunner().invoke(cli.main, ["strava", "login"], input="_strava4_session=abc\n")
    assert result.exit_code == 2
    assert "Remember me" in result.output
    assert not (tmp_path / "s.json").exists()


def test_login_keeps_only_remember_cookies_and_shows_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_SESSION_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(strava_mod.StravaClient, "check", lambda self: 20)
    header = f"_strava4_session=abc; strava_remember_id=1; strava_remember_token={token_expiring_in(30)}"
    result = CliRunner().invoke(cli.main, ["strava", "login"], input=header + "\n")
    assert result.exit_code == 0, result.output
    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert set(saved) == {"strava_remember_id", "strava_remember_token"}
    assert "Valid until" in result.output
    assert "abc" not in result.output  # never echoes cookie values


# --- after a sync: expired / renew-soon exits ----------------------------------

def test_followup_ok_when_login_has_time_left():
    assert cli._strava_followup(FakeClient(days_left=20), Counter()) == 0


def test_followup_exits_when_login_expired():
    counts = Counter({StravaOutcome.AUTH_FAILED: 1})
    assert cli._strava_followup(FakeClient(), counts) == cli.EXIT_AUTH


def test_followup_warns_before_expiry_so_github_emails():
    assert cli._strava_followup(FakeClient(days_left=2), Counter()) == cli.EXIT_RENEW


def test_followup_saves_a_renewed_login(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_SESSION_PATH", str(tmp_path / "s.json"))
    assert cli._strava_followup(FakeClient(changed=True), Counter()) == 0
    assert (tmp_path / "s.json").exists()


def test_no_strava_means_no_followup():
    assert cli._strava_followup(None, Counter({StravaOutcome.AUTH_FAILED: 1})) == 0
