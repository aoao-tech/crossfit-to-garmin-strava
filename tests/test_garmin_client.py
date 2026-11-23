from datetime import date

import pytest

from arbox_sync import config
from arbox_sync.garmin_client import (
    Activity,
    GarminAuthError,
    GarminClient,
    activities_on_date,
    parse_activity,
)


def test_parse_activity_extracts_fields(garmin_raw_activities):
    act = parse_activity(garmin_raw_activities[0])
    assert act == Activity(
        activity_id=90000000001,
        name="Sample City HIIT",
        description="",
        type_key="hiit",
        start_local="2026-11-20 19:05:12",
    )


def test_parse_activity_tolerates_missing_type():
    act = parse_activity({"activityId": 5, "startTimeLocal": "2026-01-01 10:00:00"})
    assert act.type_key == ""
    assert act.name == ""
    assert act.description == ""


def test_activities_on_date_uses_local_start_date(garmin_raw_activities):
    acts = [parse_activity(r) for r in garmin_raw_activities]
    on_20 = activities_on_date(acts, date(2026, 11, 20))
    assert [a.activity_id for a in on_20] == [90000000001, 90000000002]
    # 00:30 local on the 21st belongs to the 21st even though GMT is the 20th
    on_21 = activities_on_date(acts, date(2026, 11, 21))
    assert [a.activity_id for a in on_21] == [90000000003]


class FakeApi:
    def __init__(self, raws=None, fail_login=None):
        self.raws = raws or []
        self.fail_login = fail_login
        self.updates = []
        self.login_calls = []

    def login(self, tokenstore=None):
        self.login_calls.append(tokenstore)
        if self.fail_login:
            raise self.fail_login
        return None, None

    def get_activities_by_date(self, startdate, enddate=None, **_kw):
        return list(self.raws)

    def update_activity(self, activity_id, fields):
        self.updates.append((activity_id, dict(fields)))


def test_list_activities_filters_to_date(garmin_raw_activities):
    client = GarminClient(FakeApi(garmin_raw_activities))
    acts = client.list_activities(date(2026, 11, 21))
    assert [a.activity_id for a in acts] == [90000000003]


def test_update_activity_sends_name_and_description_in_one_call():
    api = FakeApi()
    GarminClient(api).update_activity(42, name="Fran", description="21-15-9")
    assert api.updates == [(42, {"activityName": "Fran", "description": "21-15-9"})]


def test_from_tokens_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(GarminAuthError, match="garmin login"):
        GarminClient.from_tokens(tmp_path / "nope.json", api_factory=FakeApi)


def test_from_tokens_wraps_library_auth_failure(tmp_path):
    token_file = tmp_path / "garmin_tokens.json"
    token_file.write_text("{}", encoding="utf-8")

    def factory():
        return FakeApi(fail_login=RuntimeError("401 from server, token=abc123"))

    with pytest.raises(GarminAuthError) as exc:
        GarminClient.from_tokens(token_file, api_factory=factory)
    # the original message may contain secrets, so it must not leak through
    assert "abc123" not in str(exc.value)
    assert "garmin login" in str(exc.value)


def test_token_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_TOKEN_PATH", str(tmp_path / "t.json"))
    assert config.garmin_token_path() == tmp_path / "t.json"


def test_token_path_default_is_outside_repo(monkeypatch):
    monkeypatch.delenv("GARMIN_TOKEN_PATH", raising=False)
    path = config.garmin_token_path()
    assert path.name == "garmin_tokens.json"
    assert ".garmin-to-arbox" in path.parts
