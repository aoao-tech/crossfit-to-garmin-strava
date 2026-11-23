import json
from datetime import date

from click.testing import CliRunner

from arbox_sync import cli
from arbox_sync.arbox_client import ArboxAuthError, Section, Wod

WOD = Wod(date(2026, 11, 22), "CrossFit WOD", (Section("Metcon", "12 SAMPLE PUSH PRESS", "AMRAP"),))


class FakeArbox:
    def __init__(self, wod=WOD, error=None):
        self.wod, self.error = wod, error

    def get_wod(self, day):
        if self.error:
            raise self.error
        return self.wod if day == date(2026, 11, 22) else None


def _patch(monkeypatch, client):
    monkeypatch.setattr(cli, "_arbox", lambda: client)


def test_wod_prints_title_and_text(monkeypatch):
    _patch(monkeypatch, FakeArbox())
    result = CliRunner().invoke(cli.main, ["arbox", "wod", "--date", "2026-11-22"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == {"date": "2026-11-22", "title": "CrossFit WOD", "text": "Metcon\n12 SAMPLE PUSH PRESS"}


def test_wod_empty_day_prints_empty_object(monkeypatch):
    _patch(monkeypatch, FakeArbox())
    result = CliRunner().invoke(cli.main, ["arbox", "wod", "--date", "2026-11-20"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {}


def test_wod_auth_error_exits_2(monkeypatch):
    _patch(monkeypatch, FakeArbox(error=ArboxAuthError("Arbox rejected the saved token. Run arbox login")))
    result = CliRunner().invoke(cli.main, ["arbox", "wod", "--date", "2026-11-22"])
    assert result.exit_code == 2
    assert "Arbox rejected" in result.output


def test_login_saves_token_without_echoing_it(monkeypatch, tmp_path):
    monkeypatch.setenv("ARBOX_TOKEN_PATH", str(tmp_path / "tok.txt"))
    monkeypatch.setattr(cli.ArboxClient, "login", staticmethod(lambda email, pw: "secret-token-xyz"))
    result = CliRunner().invoke(cli.main, ["arbox", "login"], input="a@b.c\npw\n")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "tok.txt").read_text(encoding="utf-8") == "secret-token-xyz"
    assert "secret-token-xyz" not in result.output
