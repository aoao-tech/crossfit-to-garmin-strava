from datetime import date

from arbox_sync import config
from arbox_sync.arbox_client import Section, Wod
from arbox_sync.garmin_client import Activity
from arbox_sync.sync import (
    Outcome,
    build_update,
    is_default_name,
    run_sync,
    select_activity,
    sync_day,
)

DAY = date(2026, 11, 22)
WOD = Wod(DAY, "CrossFit WOD", (Section("Metcon", "12 SAMPLE PUSH PRESS", "AMRAP"),))


def act(i=1, name="HIIT", desc="", type_key="hiit", start="2026-11-22 18:00:00"):
    return Activity(i, name, desc, type_key, start)


# --- selection -------------------------------------------------------------

def test_no_training_activity_means_no_training():
    chosen, outcome = select_activity((act(type_key="running", name="Run"),))
    assert chosen is None and outcome == Outcome.NO_TRAINING


def test_single_hiit_is_selected():
    chosen, outcome = select_activity((act(), act(2, type_key="walking", name="Walk")))
    assert chosen.activity_id == 1 and outcome == Outcome.MATCH


def test_cardio_counts_as_training():
    chosen, _ = select_activity((act(type_key="indoor_cardio", name="Cardio"),))
    assert chosen is not None


def test_two_training_activities_is_ambiguous():
    chosen, outcome = select_activity((act(1), act(2)))
    assert chosen is None and outcome == Outcome.AMBIGUOUS


# --- idempotency and manual edits -----------------------------------------

def test_default_names():
    assert is_default_name("HIIT")
    assert is_default_name("Sample City HIIT")
    assert is_default_name("Cardio")
    assert is_default_name("Sample City Indoor Cardio")
    assert not is_default_name("Fran with friends")


def test_build_update_for_untouched_activity():
    update = build_update(act(), WOD)
    assert update.name == "CrossFit WOD"
    assert update.description == "Metcon\n12 SAMPLE PUSH PRESS\n\n" + config.SYNC_MARKER


def test_already_synced_activity_is_skipped():
    assert build_update(act(desc="old\n\n" + config.SYNC_MARKER), WOD) is None


def test_manual_description_is_never_overwritten():
    assert build_update(act(desc="felt great"), WOD) is None


def test_manual_name_is_never_overwritten():
    assert build_update(act(name="Murph day"), WOD) is None


# --- one day, with fakes ---------------------------------------------------

class FakeGarmin:
    def __init__(self, acts):
        self.acts, self.updates = acts, []

    def list_activities(self, day):
        return self.acts.get(day, ())

    def update_activity(self, activity_id, *, name, description):
        self.updates.append((activity_id, name, description))


class FakeArbox:
    def __init__(self, wod=WOD):
        self.wod, self.calls = wod, []

    def get_wod(self, day):
        self.calls.append(day)
        return self.wod


def test_no_training_does_not_call_arbox():
    garmin, arbox = FakeGarmin({DAY: (act(type_key="running", name="Run"),)}), FakeArbox()
    assert sync_day(DAY, garmin, arbox, dry_run=False) == Outcome.NO_TRAINING
    assert arbox.calls == []


def test_ambiguous_day_does_not_call_arbox_or_write():
    garmin, arbox = FakeGarmin({DAY: (act(1), act(2))}), FakeArbox()
    assert sync_day(DAY, garmin, arbox, dry_run=False) == Outcome.AMBIGUOUS
    assert arbox.calls == [] and garmin.updates == []


def test_already_synced_does_not_call_arbox():
    garmin, arbox = FakeGarmin({DAY: (act(desc=config.SYNC_MARKER),)}), FakeArbox()
    assert sync_day(DAY, garmin, arbox, dry_run=False) == Outcome.SKIPPED
    assert arbox.calls == []


def test_match_writes_once():
    garmin, arbox = FakeGarmin({DAY: (act(),)}), FakeArbox()
    assert sync_day(DAY, garmin, arbox, dry_run=False) == Outcome.UPDATED
    assert garmin.updates == [(1, "CrossFit WOD", "Metcon\n12 SAMPLE PUSH PRESS\n\n" + config.SYNC_MARKER)]


def test_dry_run_never_writes():
    garmin = FakeGarmin({DAY: (act(),)})
    assert sync_day(DAY, garmin, FakeArbox(), dry_run=True) == Outcome.WOULD_UPDATE
    assert garmin.updates == []


def test_training_but_no_wod():
    garmin = FakeGarmin({DAY: (act(),)})
    assert sync_day(DAY, garmin, FakeArbox(wod=None), dry_run=False) == Outcome.NO_WOD
    assert garmin.updates == []


# --- window ----------------------------------------------------------------

def test_run_sync_covers_window_and_counts():
    yesterday = date(2026, 11, 21)
    garmin = FakeGarmin({DAY: (act(),), yesterday: ()})
    counts = run_sync(DAY, days=2, garmin=garmin, arbox=FakeArbox(), dry_run=False)
    assert counts[Outcome.UPDATED] == 1
    assert counts[Outcome.NO_TRAINING] == 1
