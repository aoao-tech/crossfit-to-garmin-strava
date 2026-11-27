from datetime import date, datetime

from arbox_sync import config
from arbox_sync.arbox_client import Section, Wod
from arbox_sync.garmin_client import Activity
from arbox_sync.strava_client import StravaActivity, StravaAuthError
from arbox_sync.sync import Outcome, StravaOutcome, WodResolver, run_sync, sync_strava_day

DAY = date(2026, 11, 25)
WOD = Wod(DAY, "CrossFit WOD", (Section("Metcon", "BOX WOD TEXT", "AMRAP"),))
START = "2026-11-25 18:40:02"


def garmin_act(name="HIIT", desc="", start=START):
    return Activity(1, name, desc, "hiit", start)


def strava_act(name="Evening HIIT", desc="", start=datetime(2026, 11, 25, 18, 40, 2)):
    return StravaActivity("99", name, desc, start, raw={})


class FakeStrava:
    def __init__(self, acts=(), raises=None):
        self.acts, self.raises, self.updates = list(acts), raises, []

    def activities_on(self, day):
        if self.raises:
            raise self.raises
        return self.acts

    def update_activity(self, act, *, name, description):
        self.updates.append((act.activity_id, name, description))


class FakeArbox:
    def __init__(self, wod=WOD):
        self.wod, self.calls = wod, 0

    def get_wod(self, day):
        self.calls += 1
        return self.wod


class FakeGarmin:
    def __init__(self, acts):
        self.acts, self.updates = acts, []

    def list_activities(self, day):
        return self.acts.get(day, ())

    def update_activity(self, activity_id, *, name, description):
        self.updates.append((activity_id, name, description))


def resolver(wod=WOD):
    return WodResolver(FakeArbox(wod), None)


# --- one day on Strava ------------------------------------------------------

def test_no_garmin_training_means_strava_is_not_touched():
    strava = FakeStrava([strava_act()])
    assert sync_strava_day(DAY, (), strava, resolver(), dry_run=False) is None
    assert strava.updates == []


def test_no_matching_strava_activity_yet():
    strava = FakeStrava([])
    assert sync_strava_day(DAY, (garmin_act(),), strava, resolver(), dry_run=False) == StravaOutcome.NOT_FOUND


def test_default_strava_activity_gets_the_wod():
    strava = FakeStrava([strava_act()])
    assert sync_strava_day(DAY, (garmin_act(),), strava, resolver(), dry_run=False) == StravaOutcome.UPDATED
    assert strava.updates == [("99", "CrossFit WOD", "Metcon\nBOX WOD TEXT\n\n" + config.SYNC_MARKER)]


def test_strava_written_even_when_garmin_was_already_synced():
    strava = FakeStrava([strava_act()])
    synced_garmin = garmin_act(name="CrossFit WOD", desc="x\n\n" + config.SYNC_MARKER)
    assert sync_strava_day(DAY, (synced_garmin,), strava, resolver(), dry_run=False) == StravaOutcome.UPDATED


def test_hand_edited_strava_activity_is_left_alone():
    strava = FakeStrava([strava_act(desc="felt great")])
    assert sync_strava_day(DAY, (garmin_act(),), strava, resolver(), dry_run=False) == StravaOutcome.SKIPPED
    assert strava.updates == []


def test_already_synced_strava_activity_is_skipped():
    strava = FakeStrava([strava_act(name="CrossFit WOD", desc="w\n\n" + config.SYNC_MARKER)])
    assert sync_strava_day(DAY, (garmin_act(),), strava, resolver(), dry_run=False) == StravaOutcome.SKIPPED


def test_strava_dry_run_never_writes():
    strava = FakeStrava([strava_act()])
    assert sync_strava_day(DAY, (garmin_act(),), strava, resolver(), dry_run=True) == StravaOutcome.WOULD_UPDATE
    assert strava.updates == []


def test_strava_no_wod():
    strava = FakeStrava([strava_act()])
    assert sync_strava_day(DAY, (garmin_act(),), strava, resolver(wod=None), dry_run=False) == StravaOutcome.NO_WOD


# --- the full run -------------------------------------------------------------

def test_run_sync_writes_both_and_resolves_the_wod_once():
    garmin, strava, arbox = FakeGarmin({DAY: (garmin_act(),)}), FakeStrava([strava_act()]), FakeArbox()
    counts = run_sync(DAY, days=1, garmin=garmin, arbox=arbox, strava=strava, dry_run=False)
    assert counts[Outcome.UPDATED] == 1 and counts[StravaOutcome.UPDATED] == 1
    assert arbox.calls == 1


def test_strava_login_failure_does_not_stop_garmin():
    garmin = FakeGarmin({DAY: (garmin_act(),)})
    strava = FakeStrava(raises=StravaAuthError("expired"))
    counts = run_sync(DAY, days=2, garmin=garmin, arbox=FakeArbox(), strava=strava, dry_run=False)
    assert counts[Outcome.UPDATED] == 1
    assert counts[StravaOutcome.AUTH_FAILED] == 1


def test_strava_network_error_is_counted_and_garmin_continues():
    garmin = FakeGarmin({DAY: (garmin_act(),)})
    strava = FakeStrava(raises=RuntimeError("boom"))
    counts = run_sync(DAY, days=1, garmin=garmin, arbox=FakeArbox(), strava=strava, dry_run=False)
    assert counts[Outcome.UPDATED] == 1 and counts[StravaOutcome.ERROR] == 1
