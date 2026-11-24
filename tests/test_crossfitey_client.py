import json
from datetime import date

from arbox_sync import config
from arbox_sync.crossfitey_client import (
    CrossFitEyClient,
    day_label,
    extract_workouts,
    load_session,
    save_session,
    select_workout,
    session_token,
    week_offset,
    workout_to_wod,
)

DAY = date(2026, 11, 23)

ENDURANCE = {
    "track": "ENDURANCE",
    "title": "Monday, Nov 23",
    "blocks": [{"scheme": "Row", "instructions": "1000m Row"}],
}
CROSSFIT = {
    "track": "CROSSFIT",
    "title": "Monday, Nov 23",
    "blocks": [
        {"scheme": "AMRAP 15", "instructions": "15/12 Cal Row\n15 Wall Balls"},
        {"scheme": "Empty", "instructions": ""},
    ],
}
FLIGHT = f'noise "workout":{json.dumps(ENDURANCE)} more "workout":{json.dumps(CROSSFIT)} end'


# --- parsing the RSC payload ----------------------------------------------

def test_extract_workouts_pulls_each_object():
    workouts = extract_workouts(FLIGHT)
    assert [w["track"] for w in workouts] == ["ENDURANCE", "CROSSFIT"]


def test_extract_workouts_tolerates_no_match():
    assert extract_workouts("nothing to see here") == []


def test_day_label_has_no_leading_zero():
    assert day_label(date(2026, 11, 3)) == "Tuesday, Nov 3"
    assert day_label(DAY) == "Monday, Nov 23"


# --- selecting the right workout ------------------------------------------

def test_select_picks_crossfit_track_for_the_day():
    wod = select_workout(DAY, extract_workouts(FLIGHT))
    assert wod is not None
    assert wod.title == config.FALLBACK_TITLE
    assert "15/12 Cal Row" in wod.text
    assert "Row\n1000m Row" not in wod.text  # endurance track excluded


def test_empty_instruction_blocks_are_dropped():
    wod = select_workout(DAY, extract_workouts(FLIGHT))
    assert "Empty" not in wod.text


def test_select_returns_none_for_a_day_not_in_the_week():
    assert select_workout(date(2026, 11, 24), extract_workouts(FLIGHT)) is None


def test_workout_with_only_empty_blocks_is_none():
    assert workout_to_wod(DAY, {"track": "CROSSFIT", "title": "x", "blocks": [{"instructions": ""}]}) is None


# --- session persistence ---------------------------------------------------

def test_session_roundtrip(tmp_path):
    path = tmp_path / "crossfitey_session.json"
    cookies = {"__Secure-next-auth.session-token": "abc123"}
    saved = save_session(cookies, path)
    assert saved == path
    assert load_session(path) == cookies


def test_env_session_wins_over_file(tmp_path, monkeypatch):
    path = tmp_path / "missing.json"
    monkeypatch.setenv("CROSSFITEY_SESSION", json.dumps({"k": "v"}))
    assert load_session(path) == {"k": "v"}


# --- week offset (Sun..Sat weeks, relative to today) ----------------------

def test_week_offset_same_week_is_zero():
    assert week_offset(date(2026, 11, 23), date(2026, 11, 23)) == 0  # both in week of Sun Nov 22


def test_week_offset_last_week_is_minus_one():
    # Sat Nov 21 (week of Nov 15) seen from Mon Nov 23 (week of Nov 22)
    assert week_offset(date(2026, 11, 21), date(2026, 11, 23)) == -1


def test_week_offset_two_weeks_back():
    assert week_offset(date(2026, 11, 8), date(2026, 11, 23)) == -2


# --- get_wod wiring (no network: stub the fetch) --------------------------

def test_get_wod_fetches_the_days_own_week():
    client = CrossFitEyClient({"session": "x"})
    seen = {}

    def fake_fetch(offset):
        seen["offset"] = offset
        return FLIGHT

    client._fetch_week = fake_fetch  # type: ignore[method-assign]
    # Sat Nov 21 synced on Mon Nov 23 must look one week back, not the current week.
    wod = client.get_wod(date(2026, 11, 21), today=date(2026, 11, 23))
    assert seen["offset"] == -1
    # (FLIGHT is a Nov 23 fixture, so no match for Nov 21 -> None, but the offset is what matters)
    assert wod is None


def test_get_wod_parses_matching_week():
    client = CrossFitEyClient({"session": "x"})
    client._fetch_week = lambda offset: FLIGHT  # type: ignore[method-assign]
    wod = client.get_wod(DAY, today=DAY)
    assert wod is not None and "Wall Balls" in wod.text


# --- session rotation / auto-renewal --------------------------------------

def test_session_token_finds_the_cookie_regardless_of_prefix():
    assert session_token({"__Secure-next-auth.session-token": "abc"}) == "abc"
    assert session_token({"next-auth.session-token": "def"}) == "def"
    assert session_token({"csrf": "x"}) is None


def test_session_unchanged_when_only_an_extra_cookie_is_added():
    client = CrossFitEyClient({"__Secure-next-auth.session-token": "tok"})
    client._session.cookies.set("csrf", "x")
    assert client.session_changed() is False


def test_session_changed_when_the_token_rotates():
    client = CrossFitEyClient({"__Secure-next-auth.session-token": "old"})
    assert client.session_changed() is False
    client._session.cookies.set("__Secure-next-auth.session-token", "new")
    assert client.session_changed() is True
