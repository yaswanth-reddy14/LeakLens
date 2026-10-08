from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.detector import IST, Reading, analyze, parse_cutoff
from backend.main import app
from backend.replay import start_replay, advance_replay
from backend.storage import Conflict, SQLiteStorage
from backend.workflow import (WorkflowError, change_incident, create_incident, snapshot,
                              verify_repair, visible_incidents)


def at(day, hour=0):
    return datetime(2026, 9, day, hour, tzinfo=IST)


def readings(post=20, base=40):
    return [Reading("A", at(day, hour),
                    180 if day in (15, 16) and hour < 6 else post if day >= 17 and hour < 6 else base)
            for day in range(1, 21) for hour in range(24)]


@pytest.fixture
def store(tmp_path):
    return SQLiteStorage(tmp_path / "workflow.sqlite3")


def open_example(tx):
    return create_incident(tx, "uploads", "A", at(15).isoformat(), at(15, 6), "Initial check")[0]


def repaired(tx):
    incident = open_example(tx)
    change_incident(tx, "uploads", incident["id"], at(15, 12), "Investigating", "Inspection begun")
    change_incident(tx, "uploads", incident["id"], at(16, 12), "Repaired", "Valve repaired", at(16, 12))
    return incident["id"]


def test_persistence_reconnect_readings_incidents_and_events(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        incident_id = repaired(tx)
    reopened = SQLiteStorage(store.path)
    with reopened.transaction() as tx:
        result = snapshot(tx, "uploads", at(20))
        assert len(tx.readings("uploads")) == 480
        assert result["incidents"][0]["id"] == incident_id
        assert result["incidents"][0]["status"] == "Repaired"
        assert [e["note"] for e in result["incidents"][0]["events"]] == ["Initial check", "Inspection begun", "Valve repaired"]


def test_repeat_upload_is_idempotent_and_conflict_rolls_back_entire_batch(store):
    rows = readings()
    with store.transaction() as tx:
        assert tx.add_readings("uploads", rows) == {"inserted": 480, "repeated": 0}
    with store.transaction() as tx:
        assert tx.add_readings("uploads", rows) == {"inserted": 0, "repeated": 480}
    with pytest.raises(Conflict, match="Entire upload rejected"):
        with store.transaction() as tx:
            tx.add_readings("uploads", [Reading("New", at(1), 1), Reading("A", at(1), 99)])
    with store.transaction() as tx:
        assert tx.readings("uploads") == rows


def test_cutoff_excludes_incomplete_hours_future_buildings_and_future_baseline():
    cutoff = at(15, 6) - timedelta(minutes=1)
    rows = readings()
    visible = [r for r in rows if r.timestamp + timedelta(hours=1) <= cutoff]
    future = Reading("Future hostel", at(25), 99999)
    assert analyze(rows + [future], cutoff=cutoff) == analyze(visible)
    assert analyze(rows, cutoff=at(1))["buildings"] == []
    result = analyze(rows, cutoff=at(15, 6))["buildings"][0]
    assert result["points"][6]["liters"] is None
    assert result["points"][0]["baseline"] == 40
    assert result["points"][0]["history_count"] == 14
    assert result["alerts"][0]["duration_hours"] == 6


def test_same_alert_and_consecutive_nights_link_to_one_incident(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        original = open_example(tx)
        repeated, created = create_incident(tx, "uploads", "A", at(15).isoformat(), at(15, 6))
        assert not created and repeated["id"] == original["id"]
        next_night, created = create_incident(tx, "uploads", "A", at(16).isoformat(), at(16, 6))
        assert not created and next_night["id"] == original["id"]
        assert len(tx.incidents("uploads")) == 1
        assert len(tx.incidents("uploads")[0]["events"]) == 2


def test_concurrent_create_is_atomic(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
    def create():
        with store.transaction() as tx:
            return open_example(tx)["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: create(), range(2)))
    assert len(set(ids)) == 1


@pytest.mark.parametrize("status,cutoff,repair", [
    ("Repaired", at(15, 12), at(15, 12)),
    ("Open", at(15, 12), None),
    ("Investigating", at(15, 5), None),
    ("Investigating", at(15, 12), at(15, 12)),
])
def test_invalid_initial_transitions(store, status, cutoff, repair):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        incident = open_example(tx)
        with pytest.raises((WorkflowError, Conflict)):
            change_incident(tx, "uploads", incident["id"], cutoff, status, repair_time=repair)
        assert tx.incidents("uploads")[0]["status"] == "Open"


@pytest.mark.parametrize("repair", [at(15), at(15, 11), at(15, 18), at(17), None])
def test_invalid_repair_time(store, repair):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        incident = open_example(tx)
        change_incident(tx, "uploads", incident["id"], at(15, 12), "Investigating")
        with pytest.raises(WorkflowError, match="Repair time"):
            change_incident(tx, "uploads", incident["id"], at(16, 12), "Repaired", repair_time=repair)


@pytest.mark.parametrize("post,difference,percent", [(20, 360, 50), (40, 0, 0), (60, -360, -50)])
def test_reduction_no_change_and_increase(store, post, difference, percent):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings(post))
        repaired(tx)
        v = snapshot(tx, "uploads", at(20))["incidents"][0]["verification"]
        assert v["status"] == "Compared"
        assert v["observed_liters"] == post * 18
        assert v["expected_liters"] == 720
        assert v["difference_liters"] == difference
        assert v["percentage_difference"] == percent
        assert v["coverage_percent"] == 100


def test_post_repair_missing_hour_no_zero_fill_or_extrapolation(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", [r for r in readings() if r.timestamp != at(18, 2)])
        repaired(tx)
        v = snapshot(tx, "uploads", at(20))["incidents"][0]["verification"]
        assert v["status"] == "Awaiting data"
        assert v["matched_hours"] == 17
        assert v["missing_hours"] == 1
        assert v["observed_liters"] == 340
        assert v["expected_liters"] == 680
        assert v["difference_liters"] is None


def test_repaired_status_and_future_events_do_not_leak_into_history(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        repaired(tx)
        before = snapshot(tx, "uploads", at(15, 6))["incidents"][0]
        assert before["status"] == "Open" and before["repair_time"] is None
        assert before["verification"] is None and len(before["events"]) == 1
        after = snapshot(tx, "uploads", at(16, 12))["incidents"][0]
        assert after["status"] == "Repaired"
        assert after["verification"]["status"] == "Awaiting data"
        assert after["verification"]["observed_hours"] == 0
        assert after["verification"]["observed_liters"] is None


def test_future_incident_is_not_revealed_by_recreating_its_alert(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        create_incident(tx, "uploads", "A", at(15).isoformat(), at(15, 12))
        assert snapshot(tx, "uploads", at(15, 6))["incidents"] == []
        with pytest.raises(Conflict, match="later evaluation time"):
            open_example(tx)


def test_later_known_incident_invalidates_overlapping_post_repair_comparison(store):
    rows = [Reading(r.building_id, r.timestamp, 180) if r.timestamp.day == 18 and r.timestamp.hour < 6 else r for r in readings()]
    with store.transaction() as tx:
        tx.add_readings("uploads", rows)
        repaired(tx)
        create_incident(tx, "uploads", "A", at(18).isoformat(), at(18, 6))
        v = snapshot(tx, "uploads", at(20))["incidents"][0]["verification"]
        assert v["status"] == "Awaiting data"
        assert v["matched_hours"] == 6
        assert v["observed_hours"] == 18
        assert v["incident_excluded_hours"] == 12
        assert v["difference_liters"] is None


def test_known_incident_periods_excluded_from_reference(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        repaired(tx)
        incidents = visible_incidents(tx.incidents("uploads"), at(20))
        older = {"building_id": "A", "start": at(1).isoformat(), "repair_time": at(9).isoformat(), "last_alert_end": at(8, 6).isoformat()}
        v = verify_repair(tx.readings("uploads"), incidents[0], incidents + [older], at(20))
        assert v["excluded_reference_hours"] == 48
        assert v["baseline_samples"]["0"] == 6
        assert v["status"] == "Awaiting data"
        assert v["matched_hours"] == 0


def test_zero_baseline_percentage_is_undefined(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings(post=0, base=0))
        repaired(tx)
        v = snapshot(tx, "uploads", at(20))["incidents"][0]["verification"]
        assert v["status"] == "Compared"
        assert v["difference_liters"] == 0
        assert v["percentage_difference"] is None


def test_recurrence_requires_a_clean_night_after_repair(store):
    rows = [Reading(r.building_id, r.timestamp, 180) if r.timestamp.day == 18 and r.timestamp.hour < 6 else r for r in readings()]
    with store.transaction() as tx:
        tx.add_readings("uploads", rows)
        first = repaired(tx)
        second, created = create_incident(tx, "uploads", "A", at(18).isoformat(), at(18, 6))
        assert created and second["id"] != first
        assert len(tx.incidents("uploads")) == 2


def test_continued_high_consumption_after_recorded_repair_is_same_episode(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings(post=180))
        first = repaired(tx)
        second, created = create_incident(tx, "uploads", "A", at(17).isoformat(), at(17, 6))
        assert not created and first == second["id"]
        assert second["status"] == "Repaired"


def test_replay_reset_preserves_uploaded_readings_and_maintenance(store):
    with store.transaction() as tx:
        tx.add_readings("uploads", readings())
        repaired(tx)
        before = snapshot(tx, "uploads", at(20))
        start_replay(tx)
        first = advance_replay(tx, 0)
        retried = advance_replay(tx, 0)
        assert first == retried
        for stage in (1, 2, 3):
            result = advance_replay(tx, stage)
        assert result["incidents"][0]["verification"]["status"] == "Compared"
        assert result["incidents"][0]["verification"]["difference_liters"] > 0
        tx.reset_replay()
        restarted = start_replay(tx)
        assert restarted["replay"]["stage"] == 0
        assert restarted["incidents"] == []
        assert snapshot(tx, "uploads", at(20)) == before


def test_http_persistence_conflict_and_cutoff_validation():
    content = b"building_id,timestamp,consumption_liters\nA,2026-09-01T00:00:00+05:30,40"
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post("/api/analyze", files={"file": ("data.csv", content)})
            assert response.status_code == 200 and response.json()["reading_count"] == 1
        conflict = client.post("/api/analyze", files={"file": ("data.csv", content.replace(b",40", b",99"))})
        assert conflict.status_code == 409
        assert "stored 40 L" in conflict.json()["detail"]
        assert client.get("/api/workspace", params={"cutoff": "2026-09-01T01:00:00"}).status_code == 422
    with TestClient(app) as restarted:
        assert restarted.get("/api/workspace").json()["analysis"]["reading_count"] == 1


def test_empty_workspace_cutoff_can_be_reloaded():
    with TestClient(app) as client:
        saved = client.get("/api/workspace").json()
        restored = client.get("/api/workspace", params={"cutoff": saved["cutoff"]})
        assert restored.status_code == 200
        assert restored.json() == saved


def test_replay_api_blocks_future_cutoffs_and_reload_does_not_mutate():
    with TestClient(app) as client:
        start = client.post("/api/replay/start").json()
        assert start["analysis"]["period_end"] == "2026-09-29T00:00:00+05:30"
        future = client.get("/api/workspace", params={"scope": "replay", "cutoff": "2026-10-05T06:00:00+05:30"})
        assert future.status_code == 422
        advanced = client.post("/api/replay/advance", json={"expected_stage": 0}).json()
        for _ in range(2):
            loaded = client.get("/api/workspace", params={"scope": "replay"}).json()
            assert loaded == advanced
        assert len(loaded["incidents"]) == 1


@pytest.mark.parametrize("value", ["bad", "2026-01-01T00:00:00", "2026-01-01T00:00:00+05:99"])
def test_cutoff_requires_valid_explicit_offset(value):
    with pytest.raises(ValueError):
        parse_cutoff(value)
