import json
from datetime import date
from pathlib import Path

import pytest

from arbox_sync import config
from arbox_sync.arbox_client import (
    ArboxAuthError,
    ArboxClient,
    Section,
    format_text,
    load_token,
    parse_workouts,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "arbox_workouts.json").read_text(encoding="utf-8"))
DAY = date(2026, 11, 22)


def test_parse_workouts_builds_sections_in_order():
    wod = parse_workouts(DAY, FIXTURE["data"])
    assert [s.title for s in wod.sections] == ["ACCESSORY WORK", "Strength", "Metcon"]
    assert wod.sections[2].workout_type == "AMRAP"
    assert wod.date == DAY


def test_title_falls_back_when_wod_has_no_name():
    assert parse_workouts(DAY, FIXTURE["data"]).title == config.FALLBACK_TITLE


def test_text_lists_every_section_with_its_body():
    text = parse_workouts(DAY, FIXTURE["data"]).text
    assert text.startswith("ACCESSORY WORK\n3 SETS")
    assert "\n\nStrength\n5-5-4-3-2" in text
    assert text.endswith("SCORE: ROUNDS + REPS")


def test_empty_day_returns_none():
    assert parse_workouts(DAY, []) is None
    assert parse_workouts(DAY, [[[]]]) is None


def test_sections_without_text_are_skipped():
    data = [[[{"comment": "", "box_sections": {"name": "Empty"}}], [{"comment": "RUN", "box_sections": None}]]]
    wod = parse_workouts(DAY, data)
    assert [s.title for s in wod.sections] == [""]
    assert format_text(wod.sections) == "RUN"


def test_format_text_strips_trailing_whitespace():
    assert format_text((Section("A", "x  \n", ""),)) == "A\nx"


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, status=200, payload=None):
        self.status, self.payload = status, payload if payload is not None else FIXTURE
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return FakeResponse(self.status, self.payload)


def test_get_wod_posts_date_with_token_header():
    session = FakeSession()
    wod = ArboxClient("tok-123", session=session).get_wod(DAY)
    url, body, headers = session.calls[0]
    assert url.endswith("/api/v2/logbook/workouts")
    assert body == {"date": "2026-11-22"}
    assert headers["accesstoken"] == "tok-123"
    assert wod.sections[0].title == "ACCESSORY WORK"


@pytest.mark.parametrize("status", [401, 403])
def test_get_wod_auth_failure_is_clear_and_hides_token(status):
    with pytest.raises(ArboxAuthError) as exc:
        ArboxClient("tok-secret", session=FakeSession(status=status, payload={})).get_wod(DAY)
    assert "tok-secret" not in str(exc.value)
    assert "arbox login" in str(exc.value)


def test_get_wod_other_error_raises_runtime_error():
    with pytest.raises(RuntimeError, match="500"):
        ArboxClient("t", session=FakeSession(status=500, payload={})).get_wod(DAY)


def test_login_returns_token_and_never_keeps_password():
    session = FakeSession(payload={"data": {"token": "new-token", "email": "x"}})
    assert ArboxClient.login("a@b.c", "pw", session=session) == "new-token"
    _, body, headers = session.calls[0]
    assert body == {"email": "a@b.c", "password": "pw"}
    assert "accesstoken" not in headers


def test_login_bad_credentials_raises_auth_error():
    with pytest.raises(ArboxAuthError):
        ArboxClient.login("a@b.c", "bad", session=FakeSession(status=401, payload={}))


def test_load_token_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARBOX_TOKEN", " env-tok \n")
    assert load_token(tmp_path / "missing.txt") == "env-tok"


def test_load_token_reads_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ARBOX_TOKEN", raising=False)
    f = tmp_path / "t.txt"
    f.write_text("file-tok\n", encoding="utf-8")
    assert load_token(f) == "file-tok"


def test_load_token_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("ARBOX_TOKEN", raising=False)
    with pytest.raises(ArboxAuthError, match="arbox login"):
        load_token(tmp_path / "missing.txt")
