from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.demo import make_demo
from backend.detector import CSVError, IST, Reading, analyze, parse_csv
from backend.main import app


def dataset():
    start = datetime(2026, 9, 1, tzinfo=IST)
    return [Reading("A", start + timedelta(hours=i), 400 if 6 <= i % 24 <= 9 else 40)
            for i in range(15 * 24)]


def latest(rows):
    return analyze(rows)["buildings"][0]


def inject(rows, hours):
    return [Reading(r.building_id, r.timestamp, 180) if r.timestamp.day == 15 and r.timestamp.hour in hours else r for r in rows]


def test_normal_morning_peaks_are_not_alerts():
    result = latest(dataset())
    assert result["status"] == "no_pattern"
    assert result["alerts"] == []
    assert result["points"][7]["liters"] == 400


def test_sustained_overnight_anomaly_has_explanation():
    result = latest(inject(dataset(), [1, 2, 3, 4]))
    alert = result["alerts"][0]
    assert result["status"] == "possible_loss"
    assert alert["duration_hours"] == 4
    assert alert["observed_liters"] == 720
    assert alert["baseline_liters"] == 160
    assert alert["threshold_liters"] == 360
    assert alert["end"].endswith("05:00:00+05:30")


def test_missing_hour_breaks_consecutive_run_and_is_not_zero():
    rows = inject(dataset(), [1, 2, 3, 4])
    result = latest([r for r in rows if not (r.timestamp.day == 15 and r.timestamp.hour == 2)])
    assert result["status"] == "incomplete_data"
    assert result["alerts"] == []
    assert result["points"][2]["liters"] is None
    assert result["missing_hours"] == 1


def test_missing_history_not_zero_filled():
    rows = [r for r in dataset() if not (r.timestamp.day < 10 and r.timestamp.hour == 2)]
    result = latest(rows)
    assert result["status"] == "insufficient_history"
    assert result["points"][2]["baseline"] is None
    assert result["points"][2]["history_count"] == 5


def test_insufficient_history():
    result = latest(dataset()[-3 * 24:])
    assert result["status"] == "insufficient_history"
    assert result["baseline_liters"] is None
    assert result["alerts"] == []


def test_only_prior_days_in_baseline_and_28_day_limit():
    rows = dataset()
    rows += [Reading("A", datetime(2026, 7, 1, hour, tzinfo=IST), 900) for hour in range(6)]
    result = latest(inject(rows, [0, 1, 2, 3, 4, 5]))
    assert result["baseline_liters"] == 240
    assert result["points"][0]["history_count"] == 14


def test_single_spike_and_exact_threshold_are_not_alerts():
    assert latest(inject(dataset(), [2]))["status"] == "no_pattern"
    rows = [Reading(r.building_id, r.timestamp, 90) if r.timestamp.day == 15 and r.timestamp.hour < 6 else r for r in dataset()]
    assert latest(rows)["status"] == "no_pattern"


def test_incomplete_current_night_evaluates_previous_night():
    rows = dataset() + [Reading("A", datetime(2026, 9, 16, 0, tzinfo=IST), 500)]
    assert latest(rows)["evaluation_start"].startswith("2026-09-15")


def test_simulated_scenario_is_reproducible_and_isolated():
    assert make_demo() == make_demo()
    result = analyze(parse_csv(make_demo()))
    assert result["reading_count"] == 2088
    assert [b["status"] for b in result["buildings"]] == ["no_pattern", "possible_loss", "no_pattern"]
    assert all(b["status"] == "no_pattern" for b in analyze(parse_csv(make_demo(False)))["buildings"])


def csv_bytes(row):
    return ("building_id,timestamp,consumption_liters\n" + row).encode()


@pytest.mark.parametrize("row, message", [
    ("A,2026-09-01T00:00:00+05:30,-1", "non-negative"),
    ("A,2026-09-01T00:00:00+05:30,NaN", "finite"),
    ("A,2026-09-01T00:00:00+05:30,inf", "finite"),
    ("A,2026-09-01T00:00:00,5", "explicit timezone"),
    ("A,2026-02-30T00:00:00+05:30,5", "invalid timestamp"),
    ("A,2026-09-01T00:00:00+05:99,5", "invalid timestamp"),
    ("A,2026-09-01T00:30:00+05:30,5", "whole hour"),
    (",2026-09-01T00:00:00+05:30,5", "building_id"),
    ("A,2026-09-01T00:00:00+05:30,5,extra", "three values"),
])
def test_invalid_csv_reports_line(row, message):
    with pytest.raises(CSVError, match=f"Line 2:.*{message}"):
        parse_csv(csv_bytes(row))


def test_duplicate_instants_in_different_timezones():
    with pytest.raises(CSVError, match="Line 3: duplicate"):
        parse_csv(csv_bytes("A,2026-09-01T00:00:00+05:30,5\nA,2026-08-31T18:30:00Z,6"))


def test_utc_is_converted_to_kolkata():
    row = parse_csv(csv_bytes("A,2026-08-31T18:30:00Z,5"))[0]
    assert row.timestamp.hour == 0
    assert row.timestamp.day == 1


def test_http_upload_and_error_and_download():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        response = client.post("/api/analyze", files={"file": ("sample.csv", make_demo(), "text/csv")})
        assert response.status_code == 200
        assert response.json()["source"] == "simulated"
        assert client.get("/api/demo").json() == response.json()
        assert client.get("/api/examples/normal").content == make_demo(False)
        bad = client.post("/api/analyze", files={"file": ("bad.csv", csv_bytes("A,bad,-1"))})
        assert bad.status_code == 422
        assert "Line 2" in bad.json()["detail"]


def test_empty_and_wrong_header():
    for content in [b"", b"building,timestamp,consumption\n", csv_bytes("")]:
        with pytest.raises(CSVError):
            parse_csv(content)


def test_alert_survives_missing_hour_outside_run_with_quality_warning():
    rows = inject(dataset(), [1, 2, 3])
    result = latest([r for r in rows if not (r.timestamp.day == 15 and r.timestamp.hour == 5)])
    assert result["status"] == "possible_loss"
    assert result["alerts"][0]["duration_hours"] == 3
    assert result["missing_hours"] == 1


def test_zero_baseline_has_absolute_floor_and_zero_is_not_missing():
    rows = [Reading(r.building_id, r.timestamp, 0) for r in dataset()]
    result = latest(rows)
    assert result["status"] == "no_pattern"
    assert result["missing_hours"] == 0
    assert result["points"][0]["threshold"] == 50
    assert latest(inject(rows, [1, 2, 3]))["status"] == "possible_loss"


def test_seven_samples_suffice_and_buildings_do_not_share_history():
    rows = dataset()[-8 * 24:]
    assert latest(rows)["status"] == "no_pattern"
    assert latest(rows)["points"][0]["history_count"] == 7
    rows += [Reading("New", r.timestamp, 150) for r in rows[-24:]]
    result = analyze(rows)["buildings"]
    assert result[1]["status"] == "insufficient_history"


def test_oversized_upload_is_rejected():
    from backend.detector import MAX_BYTES
    with TestClient(app) as client:
        response = client.post("/api/analyze", files={"file": ("large.csv", b"x" * (MAX_BYTES + 1))})
        assert response.status_code == 422
        assert "8 MB" in response.json()["detail"]
