"""Deterministic synthetic building-night benchmark; no production threshold tuning."""
import argparse
import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from .detector import IST, Reading, analyze

FAMILIES = ("normal_morning_peak", "sustained_overnight_increase", "gradual_small_increase",
            "missing_readings", "legitimate_overnight_consumption")
CANDIDATES = (100, 150, 200, 250)


def scenarios(split):
    if split not in ("tuning", "evaluation"):
        raise ValueError("Unknown split")
    count, seed = (8, 1100) if split == "tuning" else (20, 9200)
    for family_index, family in enumerate(FAMILIES):
        for repeat in range(count):
            scenario_seed = seed + family_index * 100 + repeat
            rng = random.Random(scenario_seed)
            start = datetime(2026, 1 if split == "tuning" else 3, 1, tzinfo=IST)
            night = start + timedelta(days=28)
            base = (30, 70, 110, 150)[repeat % 4]
            positive = family in (FAMILIES[1], FAMILIES[2]) or family == FAMILIES[3] and repeat % 2 == 0
            onset = night + timedelta(hours=1) if family == FAMILIES[1] else night
            if family == FAMILIES[2]:
                onset = night - timedelta(days=7)
            rows = []
            for index in range(29 * 24):
                stamp = start + timedelta(hours=index)
                day, hour = index // 24, stamp.hour
                liters = (base if hour < 6 else 400 if hour < 10 else 160) + rng.uniform(-4, 4)
                # A gradual +5 L/day rise starts seven days before the evaluated night.
                # It is labeled undesirable water loss by the generator, not inferred from consumption.
                if family == FAMILIES[2] and day >= 21 and hour < 6:
                    liters += (day - 20) * 5
                if day == 28:
                    if family == FAMILIES[0] and 6 <= hour < 10:
                        liters += 350
                    if family == FAMILIES[1] and 1 <= hour <= 4:
                        liters += 180
                    if family == FAMILIES[3] and hour < 6:
                        if hour in (2, 4, 5):
                            continue
                        if positive:
                            liters += 180
                    # Half are a scheduled one-off overnight use that meters alone cannot identify.
                    if family == FAMILIES[4] and repeat % 2 == 0 and hour < 6:
                        liters += 180
                rows.append(Reading("Synthetic hostel", stamp, round(liters, 2)))
            yield {"id": f"{split}-{family}-{repeat:02d}", "seed": scenario_seed,
                   "family": family, "rows": rows, "night": night, "positive": positive,
                   "onset": onset, "label_note": "Generator-assigned cause; not a confirmed real leak"}


def prediction(case, method, cutoff, fixed_threshold=150):
    # Current detector also filters internally. Filtering here explicitly guarantees a fair comparator.
    visible = [r for r in case["rows"] if r.timestamp + timedelta(hours=1) <= cutoff]
    analysis = analyze(visible, source="simulated", cutoff=cutoff)
    building = analysis["buildings"][0] if analysis["buildings"] else None
    if not building or building["evaluation_start"] != case["night"].isoformat():
        return False, "not_yet_eligible"
    if method == "historical":
        return bool(building["alerts"]), building["status"]
    if method != "fixed":
        raise ValueError("Unknown method")
    run = 0
    for point in building["points"][:6]:
        run = run + 1 if point["liters"] is not None and point["liters"] > fixed_threshold else 0
        if run >= 3:
            return True, "possible_loss"
    return False, "incomplete_data" if building["missing_hours"] else "no_pattern"


def metrics(records):
    counts = Counter(r["outcome"] for r in records)
    tp, fp, fn = (counts[k] for k in ("TP", "FP", "FN"))
    delays = [r["delay_hours"] for r in records if r["delay_hours"] is not None]
    return {"scenarios": len(records), **{k: counts[k] for k in ("TP", "FP", "TN", "FN")},
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "mean_delay_hours": mean(delays) if delays else None,
            "delay_samples": len(delays),
            "incomplete_or_insufficient": sum(r["status"] in ("incomplete_data", "insufficient_history") for r in records)}


def score(cases, method, threshold):
    records = []
    for case in cases:
        # 07:00 includes the 06:00 daytime reading, allowing assessment of nights missing 05:00.
        final = case["night"] + timedelta(hours=7)
        detected, status = prediction(case, method, final, threshold)
        outcome = ("TP" if case["positive"] else "FP") if detected else ("FN" if case["positive"] else "TN")
        delay = None
        # Night-level matching cannot establish first detection of an episode that
        # already began in the historical window. Leave that delay undefined.
        if outcome == "TP" and case["onset"] >= case["night"]:
            for hour in range(1, 8):
                cutoff = case["night"] + timedelta(hours=hour)
                if prediction(case, method, cutoff, threshold)[0]:
                    delay = (cutoff - case["onset"]).total_seconds() / 3600
                    break
        records.append({"id": case["id"], "seed": case["seed"], "family": case["family"],
                        "positive": case["positive"], "outcome": outcome, "status": status,
                        "delay_hours": delay, "evaluation_cutoff": final.isoformat()})
    return {"summary": metrics(records), "families": {f: metrics([r for r in records if r["family"] == f]) for f in FAMILIES},
            "records": records}


def run():
    tuning = list(scenarios("tuning"))
    candidates = {threshold: score(tuning, "fixed", threshold)["summary"] for threshold in CANDIDATES}
    threshold = max(CANDIDATES, key=lambda t: (candidates[t]["f1"] or 0, -t))
    # The evaluation split is created only AFTER the comparator threshold is frozen.
    evaluation = list(scenarios("evaluation"))
    return {"version": 1, "fixed_threshold_liters_per_hour": threshold,
            "tuning_scenarios": len(tuning), "tuning_candidates": candidates,
            "evaluation_scenarios": len(evaluation),
            "historical": score(evaluation, "historical", threshold), "fixed": score(evaluation, "fixed", threshold)}


def report(result):
    def fmt(value):
        return "undefined" if value is None else f"{value:.3f}"
    lines = ["# Synthetic evaluation", "", "Generated by `python -m backend.evaluate`. All readings and cause labels are simulated.", "",
             "## Reproduce", "", "```powershell", ".\\.venv\\Scripts\\python.exe -m backend.evaluate", "```", "",
             "This writes `docs/evaluation-results.json` (per-scenario evidence) and this report. No dependency beyond the backend runtime is added.", "",
             "## Protocol fixed before the evaluation run", "",
             "The unit is one building-night in each independently generated scenario. There are 40 tuning scenarios (8 per family, seed base 1100) and 100 held-out evaluation scenarios (20 per family, seed base 9200), in different calendar months. Seeds are disjoint; the same generator families are used, so this is not a distribution-shift test. Each scenario includes 28 prior days and a target night. Baseline levels cycle through 30, 70, 110 and 150 L/hour with seeded ±4 L noise. Morning peaks are 400 L/hour before extra test peaks.", "",
             "LeakLens thresholds are the existing, unchanged heuristic: same-building/hour median from the previous 28 days, at least 7 observations per hour, and 3 consecutive overnight values strictly above both 2× baseline and baseline + 50 L/hour. No parameter was tuned on the held-out set.", "",
             f"The fixed comparator also requires 3 consecutive 00:00–06:00 readings above a single absolute threshold. Candidates {CANDIDATES} L/hour were evaluated ONLY on tuning scenarios; highest F1 wins, with lower threshold breaking ties. Selected threshold: **{result['fixed_threshold_liters_per_hour']} L/hour**. This is a simple but time-aware comparator, not a deliberately all-day alarm.", "",
             "Both methods evaluate at hourly cutoffs and only see completed intervals. Assessments must refer to the target night, never yesterday's alert. Final scoring is at 07:00 so an observed 06:00 interval establishes night completion even if 05:00 is missing. Any qualifying run in the target night counts as one predicted-positive night; multiple alerts do not multiply matches. TP/FP/TN/FN compare this to the generator's night-level cause label. A positive night with incomplete data and no alert counts as FN, not excluded; missing values never become zero.", "",
             "Detection delay is the first eligible hourly cutoff with a matching target-night alert minus the injected onset, only for true positives whose episode begins within the scored night. A sustained increase starts at 01:00, so earliest detection is 06:00 (5 hours), not the third elevated hour. Gradual episodes begin seven days earlier in the historical window: this night-level benchmark does not establish their first episode-level alert, so their delay is undefined even when classified TP. False positives, true negatives and misses also have no delay. Means exclude undefined delays and report their sample count; null is not zero. No wall-clock latency or real-time claim is made.", "",
             "## Actual held-out results", "", "| Method | N | TP | FP | TN | FN | Precision | Recall | F1 | Mean TP delay (h) | Delay samples |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for method in ("historical", "fixed"):
        s = result[method]["summary"]
        lines.append(f"| {method} | {s['scenarios']} | {s['TP']} | {s['FP']} | {s['TN']} | {s['FN']} | {fmt(s['precision'])} | {fmt(s['recall'])} | {fmt(s['f1'])} | {fmt(s['mean_delay_hours'])} | {s['delay_samples']} |")
    lines += ["", "| Family | Method | N | TP | FP | TN | FN | Incomplete/insufficient outcomes |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for family in FAMILIES:
        for method in ("historical", "fixed"):
            s = result[method]["families"][family]
            lines.append(f"| {family} | {method} | {s['scenarios']} | {s['TP']} | {s['FP']} | {s['TN']} | {s['FN']} | {s['incomplete_or_insufficient']} |")
    lines += ["", "## Labels and limitations", "",
              "- Normal morning peak: negative; large scheduled daytime use must not become an overnight alert.",
              "- Sustained overnight increase: positive; +180 L/hour at 01:00–05:00 on the target day.",
              "- Gradual small increase: positive; +5 L/hour per day from day 22, below the existing screening thresholds. Onset predates the target night. Slow losses can be missed and can contaminate the rolling baseline.",
              "- Missing readings: half positive (+180 L/hour overnight), half negative; hours 02:00, 04:00 and 05:00 are absent. Only two elevated consecutive hours remain observable. These are intentional missed-evidence cases, not filled values.",
              "- Legitimate overnight consumption: negative; half steady high use, half one-off +180 L/hour scheduled use. Without operational context, unusual legitimate use is observationally indistinguishable from loss and can produce false positives.",
              "", "Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2TP/(2TP+FP+FN); zero denominators yield null in JSON and undefined here. No confidence intervals or real-world accuracy claims are justified by this constructed set. Scenarios share generator assumptions and do not represent independent field evidence. The comparison evaluates alert screening, not confirmed leaks or water saved. No environmental, financial or annual savings are inferred. Future work requires consented real readings, recorded operational context, independently labeled incidents and a preregistered field evaluation.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result = run()
    (output / "evaluation-results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "EVALUATION.md").write_text(report(result), encoding="utf-8")
    print(json.dumps({"fixed_threshold": result["fixed_threshold_liters_per_hour"],
                      "historical": result["historical"]["summary"], "fixed": result["fixed"]["summary"]}, indent=2))
