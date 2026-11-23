from datetime import date

from arbox_sync import config
from arbox_sync.arbox_client import ArboxAuthError, Section, Wod, registration_found
from arbox_sync.garmin_client import Activity
from arbox_sync.sync import Outcome, resolve_wod, sync_day

DAY = date(2026, 11, 23)
ARBOX_WOD = Wod(DAY, "CrossFit WOD", (Section("Metcon", "ARBOX HOME BOX WOD", "AMRAP"),))
EY_WOD = Wod(DAY, "CrossFit WOD", (Section("Metcon", "EVEN YEHUDA WOD", "AMRAP"),))


# --- the Arbox registration signal ----------------------------------------

def test_registration_found_true_when_user_booked():
    assert registration_found([{"user_booked": 12345}])


def test_registration_found_false_when_not_booked():
    assert not registration_found([{"user_booked": None}, {"user_booked": 0}])


def test_registration_found_handles_empty_and_junk():
    assert not registration_found([])
    assert not registration_found(None)
    assert not registration_found(["not a dict"])


# --- fakes -----------------------------------------------------------------

class FakeArbox:
    def __init__(self, wod=ARBOX_WOD, registered=True, raises=None):
        self.wod, self.registered, self.raises = wod, registered, raises
        self.get_calls, self.reg_calls = [], []

    def get_wod(self, day):
        self.get_calls.append(day)
        return self.wod

    def is_registered(self, day):
        self.reg_calls.append(day)
        if self.raises:
            raise self.raises
        return self.registered


class FakeEy:
    def __init__(self, wod=EY_WOD):
        self.wod, self.calls = wod, []

    def get_wod(self, day):
        self.calls.append(day)
        return self.wod


# --- resolve_wod: which box wins ------------------------------------------

def test_no_second_source_uses_arbox():
    arbox = FakeArbox()
    assert resolve_wod(DAY, arbox, None) is ARBOX_WOD
    assert arbox.reg_calls == []  # registration is not even checked


def test_booked_at_arbox_uses_arbox_and_skips_ey():
    arbox, ey = FakeArbox(registered=True), FakeEy()
    assert resolve_wod(DAY, arbox, ey) is ARBOX_WOD
    assert ey.calls == []


def test_not_booked_at_arbox_uses_even_yehuda():
    arbox, ey = FakeArbox(registered=False), FakeEy()
    assert resolve_wod(DAY, arbox, ey) is EY_WOD
    assert arbox.get_calls == []  # Arbox WOD not fetched for an EY day


def test_registration_check_failure_falls_back_to_arbox():
    arbox, ey = FakeArbox(raises=ArboxAuthError("boom")), FakeEy()
    assert resolve_wod(DAY, arbox, ey) is ARBOX_WOD
    assert ey.calls == []


# --- end to end through sync_day ------------------------------------------

def _act(desc=""):
    return Activity(1, "HIIT", desc, "hiit", "2026-11-23 18:00:00")


class FakeGarmin:
    def __init__(self, acts):
        self.acts, self.updates = acts, []

    def list_activities(self, day):
        return self.acts.get(day, ())

    def update_activity(self, activity_id, *, name, description):
        self.updates.append((activity_id, name, description))


def test_sync_day_writes_even_yehuda_wod_when_not_booked_at_arbox():
    garmin = FakeGarmin({DAY: (_act(),)})
    arbox, ey = FakeArbox(registered=False), FakeEy()
    assert sync_day(DAY, garmin, arbox, ey, dry_run=False) == Outcome.UPDATED
    assert garmin.updates[0][2].startswith("Metcon\nEVEN YEHUDA WOD")


def test_sync_day_writes_arbox_wod_when_booked():
    garmin = FakeGarmin({DAY: (_act(),)})
    arbox, ey = FakeArbox(registered=True), FakeEy()
    assert sync_day(DAY, garmin, arbox, ey, dry_run=False) == Outcome.UPDATED
    assert "ARBOX HOME BOX WOD" in garmin.updates[0][2]
    assert ey.calls == []
