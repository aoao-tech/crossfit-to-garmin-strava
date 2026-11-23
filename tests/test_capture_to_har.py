import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from capture_to_har import build_har, find_leaks, scrub, scrub_path  # noqa: E402

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJkYXRhIjoxfQ.c2lnbmF0dXJl"


def _dump():
    login_res = {"data": {"id": 42, "email": "real.person@mail.test", "first_name": "Real", "token": FAKE_JWT,
                          "refreshToken": "abc123secret"}}
    wod_res = {"data": [[[{"id": 7, "box_fk": 55, "name": "2026-11-22", "comment": "REAL GYM WOD",
                           "box_sections": {"id": 3, "name": "Metcon"}, "boxes": {"name": "Real Gym Town"}}]]]}
    headers = {"accesstoken": FAKE_JWT, "refreshtoken": "abc123secret", "content-type": "application/json"}
    return [
        {"event": {"method": "POST", "url": "https://apiappv2.arboxapp.com/api/v2/user/login", "status": 200},
         "outline": {"request": {"headers": headers}, "response": {"headers": {}}},
         "request_body": {"body": json.dumps({"email": "real.person@mail.test", "password": "hunter2"})},
         "response_body": {"body": json.dumps(login_res)}},
        {"event": {"method": "POST", "url": "https://apiappv2.arboxapp.com/api/v2/logbook/workouts", "status": 200},
         "outline": {"request": {"headers": headers}, "response": {"headers": {}}},
         "request_body": {"body": json.dumps({"date": "2026-11-22"})},
         "response_body": {"body": json.dumps(wod_res)}},
        {"event": {"method": "GET", "url": "https://n.clarity.ms/collect", "status": 204},
         "outline": {}, "request_body": {}, "response_body": {}},
    ]


def test_har_contains_no_secrets_or_personal_data():
    text = json.dumps(build_har(_dump()))
    for secret in (FAKE_JWT, "abc123secret", "hunter2", "real.person@mail.test", "REAL GYM WOD", "Real Gym Town"):
        assert secret not in text


def test_har_keeps_only_arbox_api_and_structure():
    har = build_har(_dump())
    urls = [e["request"]["url"] for e in har["log"]["entries"]]
    assert urls == ["https://apiappv2.arboxapp.com/api/v2/user/login",
                    "https://apiappv2.arboxapp.com/api/v2/logbook/workouts"]
    wod = json.loads(har["log"]["entries"][1]["response"]["content"]["text"])
    item = wod["data"][0][0][0]
    assert item["name"] == "2026-11-22"  # dates are kept
    assert item["box_sections"]["name"] == "Sample Name"
    assert item["box_fk"] == 1000


def test_auth_headers_are_dropped():
    headers = build_har(_dump())["log"]["entries"][0]["request"]["headers"]
    assert {h["name"] for h in headers} == {"content-type"}


def test_scrub_does_not_mutate_input():
    original = {"email": "a@b.c", "nested": {"token": "x"}}
    snapshot = json.dumps(original)
    scrub(original)
    assert json.dumps(original) == snapshot


def test_scrub_path_hides_ids():
    assert scrub_path("https://h/api/v2/logbook/leaderBoard/145/330169/23") == \
        "https://h/api/v2/logbook/leaderBoard/1000/1000/1000"


def test_find_leaks_is_case_insensitive():
    assert find_leaks("hello GYM town", ["gym town", "absent"]) == ["gym town"]
