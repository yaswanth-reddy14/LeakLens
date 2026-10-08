from datetime import timedelta
from backend.evaluate import metrics, prediction, scenarios
from backend.detector import Reading


def test_evaluation_splits_are_reproducible_and_disjoint():
    tuning, evaluation = list(scenarios("tuning")), list(scenarios("evaluation"))
    assert len(tuning) == 40 and len(evaluation) == 100
    assert {c["seed"] for c in tuning}.isdisjoint(c["seed"] for c in evaluation)
    assert evaluation == list(scenarios("evaluation"))
    assert sum(c["positive"] for c in evaluation) == 50


def test_evaluation_never_uses_future_intervals():
    case = next(c for c in scenarios("evaluation") if c["family"] == "sustained_overnight_increase")
    cutoff = case["night"] + timedelta(hours=6)
    for method in ("historical", "fixed"):
        before = prediction(case, method, cutoff)
        poisoned = {**case, "rows": case["rows"] + [Reading("Synthetic hostel", cutoff + timedelta(days=40), 99999)]}
        assert prediction(poisoned, method, cutoff) == before
        assert not prediction(case, method, case["night"] + timedelta(hours=4))[0]


def test_missing_readings_break_runs_and_metrics_handle_undefined():
    case = next(c for c in scenarios("evaluation") if c["family"] == "missing_readings" and c["positive"])
    for method in ("historical", "fixed"):
        assert prediction(case, method, case["night"] + timedelta(hours=7)) == (False, "incomplete_data")
    assert metrics([])["precision"] is None
    assert metrics([])["recall"] is None
    assert metrics([])["mean_delay_hours"] is None
