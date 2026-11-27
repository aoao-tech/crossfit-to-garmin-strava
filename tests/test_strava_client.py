import json
from datetime import date, datetime

import pytest

import base64
from datetime import timezone

from arbox_sync.strava_client import (
    StravaAuthError,
    StravaClient,
    find_match,
    load_session,
    parse_activity,
    parse_cookie_header,
    remember_cookies,
    renewal_due,
    save_session,
    session_expiry,
)


def fake_token(exp: int) -> str:
    """A JWT-shaped token with an exp claim (not a real Strava token)."""
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{part({'alg': 'HS256'})}.{part({'exp': exp})}.sig"

PAGE_HTML = '<html><head><meta name="csrf-token" content="CSRF123"></head></html>'


def model(i, start_time, name="Evening HIIT", description=""):
    return {"id": i, "name": name, "description": description, "start_time": start_time,
            "sport_type": "HighIntensityIntervalTraining", "visibility": "followers_only"}


class FakeResponse:
    def __init__(self, status=200, url="https://www.strava.com/athlete/training", text="", payload=None):
        self.status_code, self.url, self.text, self._payload = status, url, text, payload

    def json(self):
        return self._payload


class FakeHttp:
    """Stands in for requests.Session: serves the training page, list pages, and records PUTs."""

    def __init__(self, pages=None, login_redirect=False, put_status=200):
        self.headers, self.cookies = {}, _Jar()
        self.pages = pages or {}
        self.login_redirect = login_redirect
        self.put_status = put_status
        self.list_calls, self.puts = [], []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        if url.endswith("/athlete/training"):
            if self.login_redirect:
                return FakeResponse(url="https://www.strava.com/login")
            return FakeResponse(text=PAGE_HTML)
        page = int((params or {}).get("page", 1))
        self.list_calls.append(page)
        return FakeResponse(payload={"models": self.pages.get(page, []), "page": page, "perPage": 20})

    def put(self, url, data=None, headers=None, timeout=None):
        self.puts.append((url, json.loads(data), headers))
        return FakeResponse(status=self.put_status)


class _Jar(dict):
    def set(self, name, value, **_kw):
        self[name] = value


# --- parsing ---------------------------------------------------------------

def test_parse_cookie_header_accepts_plain_and_prefixed():
    assert parse_cookie_header("a=1; b=2") == {"a": "1", "b": "2"}
    assert parse_cookie_header("cookie: a=1; b=2") == {"a": "1", "b": "2"}


def test_parse_activity_converts_utc_to_local_time():
    act = parse_activity(model(7, "2026-11-25T16:40:02+0000"))
    assert act.activity_id == "7"
    assert act.start_local == datetime(2026, 11, 25, 18, 40, 2)  # Israel, winter (UTC+2)


def test_find_match_uses_start_time_within_two_minutes():
    acts = [parse_activity(model(1, "2026-11-25T16:40:02+0000")),
            parse_activity(model(2, "2026-11-25T04:45:23+0000"))]
    assert find_match(acts, datetime(2026, 11, 25, 18, 41, 0)).activity_id == "1"
    assert find_match(acts, datetime(2026, 11, 25, 18, 45, 0)) is None


# --- session persistence ---------------------------------------------------

def test_session_roundtrip(tmp_path):
    path = tmp_path / "strava_session.json"
    save_session({"_strava4_session": "abc"}, path)
    assert load_session(path) == {"_strava4_session": "abc"}


def test_env_session_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_SESSION", json.dumps({"k": "v"}))
    assert load_session(tmp_path / "missing.json") == {"k": "v"}


def test_missing_session_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("STRAVA_SESSION", raising=False)
    with pytest.raises(StravaAuthError):
        load_session(tmp_path / "missing.json")


# --- client ------------------------------------------------------------------

def test_expired_session_raises_auth_error():
    client = StravaClient({"s": "x"}, session=FakeHttp(login_redirect=True))
    with pytest.raises(StravaAuthError):
        client.activities_on(date(2026, 11, 25))


def test_activities_on_returns_only_that_local_day():
    http = FakeHttp(pages={1: [model(1, "2026-11-26T15:44:51+0000"), model(2, "2026-11-25T16:40:02+0000"),
                              model(3, "2026-11-23T16:32:24+0000")]})
    acts = StravaClient({"s": "x"}, session=http).activities_on(date(2026, 11, 25))
    assert [a.activity_id for a in acts] == ["2"]
    assert http.list_calls == [1]  # page 1 already reaches past the day; no more paging


def test_activities_on_pages_back_when_needed():
    http = FakeHttp(pages={1: [model(1, "2026-11-26T15:44:51+0000")],
                           2: [model(2, "2026-11-20T16:00:00+0000"), model(3, "2026-11-19T16:00:00+0000")]})
    acts = StravaClient({"s": "x"}, session=http).activities_on(date(2026, 11, 20))
    assert [a.activity_id for a in acts] == ["2"]
    assert http.list_calls == [1, 2]


def test_update_activity_puts_full_model_with_new_text():
    http = FakeHttp(pages={1: [model(5, "2026-11-25T16:40:02+0000")]})
    client = StravaClient({"s": "x"}, session=http)
    act = client.activities_on(date(2026, 11, 25))[0]
    client.update_activity(act, name="CrossFit WOD", description="WOD\n\n[arbox-sync]")
    url, body, headers = http.puts[0]
    assert url.endswith("/athlete/training_activities/5")
    assert body["name"] == "CrossFit WOD" and body["description"] == "WOD\n\n[arbox-sync]"
    assert body["visibility"] == "followers_only"  # other fields are sent back unchanged
    assert headers["x-csrf-token"] == "CSRF123"


def test_update_activity_failure_raises():
    http = FakeHttp(pages={1: [model(5, "2026-11-25T16:40:02+0000")]}, put_status=422)
    client = StravaClient({"s": "x"}, session=http)
    act = client.activities_on(date(2026, 11, 25))[0]
    with pytest.raises(RuntimeError):
        client.update_activity(act, name="x", description="y")


# --- monthly login: remember cookies, expiry, renewal ------------------------

def test_only_remember_cookies_are_kept():
    cookies = {"_strava4_session": "s", "strava_remember_id": "1", "strava_remember_token": "t", "CookieConsent": "c"}
    assert remember_cookies(cookies) == {"strava_remember_id": "1", "strava_remember_token": "t"}


def test_session_expiry_reads_the_token_exp_claim():
    exp = int(datetime(2026, 12, 27, 14, 22, tzinfo=timezone.utc).timestamp())
    assert session_expiry({"strava_remember_token": fake_token(exp)}) == datetime(2026, 12, 27, 14, 22, tzinfo=timezone.utc)


def test_session_expiry_is_none_for_garbage():
    assert session_expiry({}) is None
    assert session_expiry({"strava_remember_token": "not-a-jwt"}) is None


def test_renewal_due_inside_the_warning_window():
    expiry = datetime(2026, 12, 27, tzinfo=timezone.utc)
    assert renewal_due(expiry, datetime(2026, 12, 25, tzinfo=timezone.utc), warn_days=3)
    assert not renewal_due(expiry, datetime(2026, 12, 1, tzinfo=timezone.utc), warn_days=3)
    assert not renewal_due(None, datetime(2026, 12, 25, tzinfo=timezone.utc), warn_days=3)


def test_session_changed_only_when_a_remember_cookie_changes():
    http = FakeHttp()
    client = StravaClient({"strava_remember_id": "1", "strava_remember_token": "old"}, session=http)
    http.cookies.set("_strava4_session", "new-every-run")  # the short session cookie doesn't count
    assert client.session_changed() is False
    http.cookies.set("strava_remember_token", "renewed")
    assert client.session_changed() is True
    assert client.current_cookies() == {"strava_remember_id": "1", "strava_remember_token": "renewed"}
