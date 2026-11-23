import json
from datetime import date

from click.testing import CliRunner

from arbox_sync import cli
from arbox_sync.garmin_client import Activity, GarminAuthError

ACTS = (
    Activity(1, "Sample City HIIT", "", "hiit", "2026-11-20 19:05:12"),
    Activity(2, "Sample City Running", "easy", "running", "2026-11-20 07:00:00"),
)


class FakeClient:
    def list_activities(self, day):
        return ACTS if day == date(2026, 11, 20) else ()

    def activity_types(self):
        return [
            {"typeId": 1, "typeKey": "running", "parentTypeId": 17},
            {"typeId": 100001, "typeKey": "hiit", "parentTypeId": 4},
            {"typeId": 13, "typeKey": "strength_training", "parentTypeId": 4},
        ]


def _patch_client(monkeypatch, client=None, error=None):
    def fake_from_tokens(_path, **_kw):
        if error:
            raise error
        return client or FakeClient()

    monkeypatch.setattr(cli.GarminClient, "from_tokens", staticmethod(fake_from_tokens))


def test_activities_prints_json_for_date(monkeypatch):
    _patch_client(monkeypatch)
    result = CliRunner().invoke(cli.main, ["garmin", "activities", "--date", "2026-11-20"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [a["type_key"] for a in data] == ["hiit", "running"]
    assert data[0]["has_description"] is False


def test_types_filters_by_substring(monkeypatch):
    _patch_client(monkeypatch)
    result = CliRunner().invoke(cli.main, ["garmin", "types", "--filter", "strength"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{"typeId": 13, "typeKey": "strength_training", "parentTypeId": 4}]


def test_check_prints_only_counts(monkeypatch):
    _patch_client(monkeypatch)
    result = CliRunner().invoke(cli.main, ["garmin", "check", "--days", "3", "--date", "2026-11-21"])
    assert result.exit_code == 0, result.output
    assert "Garmin OK" in result.output
    assert "2 activities" in result.output
    assert "Sample City" not in result.output  # public CI logs: no names


def test_auth_error_exits_nonzero_with_clear_message(monkeypatch):
    _patch_client(monkeypatch, error=GarminAuthError("Garmin rejected the saved tokens. Run login."))
    result = CliRunner().invoke(cli.main, ["garmin", "check"])
    assert result.exit_code == 2
    assert "Garmin rejected the saved tokens" in result.output


def test_bad_date_is_rejected():
    result = CliRunner().invoke(cli.main, ["garmin", "activities", "--date", "21/11/2026"])
    assert result.exit_code != 0
