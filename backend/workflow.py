"""Incident lifecycle and repair comparisons, independent of the database engine."""
from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import uuid4

from .detector import IST, MIN_HISTORY, Reading, analyze
from .storage import Conflict, Transaction


class WorkflowError(ValueError):
    pass


def instant(value):
    return datetime.fromisoformat(value)


def visible_incidents(incidents, cutoff):
    """Reconstruct status/notes from effective event times; do not reveal future actions."""
    visible = []
    for incident in incidents:
        events = [e for e in incident["events"] if instant(e["effective_at"]) <= cutoff]
        if not events:
            continue
        copy = {**incident, "events": events, "status": events[-1]["status"], "repair_time": None}
        copy["notes"] = [e["note"] for e in events if e["note"]]
        copy["last_alert_end"] = max(e.get("alert_end", incident["first_alert_end"]) for e in events)
        for event in events:
            if event.get("repair_time"):
                copy["repair_time"] = event["repair_time"]
        visible.append(copy)
    return visible


def event(tx, scope, incident, kind, cutoff, note="", **extra):
    value = {"id": str(uuid4()), "kind": kind, "effective_at": cutoff.isoformat(),
             "recorded_at": datetime.now(timezone.utc).isoformat(), "status": incident["status"],
             "note": note, **extra}
    tx.add_event(scope, incident["id"], value)


def latest_cutoff(rows):
    return max((r.timestamp + timedelta(hours=1) for r in rows), default=datetime.now(IST).replace(microsecond=0))


def clean_night_between(rows, repair_time, alert_start):
    # Only observed days can establish recovery. Avoid iterating huge empty date ranges.
    candidates = sorted({r.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                         for r in rows if r.timestamp.hour == 5})
    for day in candidates:
        if day < repair_time or day + timedelta(hours=6) > alert_start:
            continue
        result = analyze(rows, cutoff=day + timedelta(hours=6))["buildings"]
        if result and result[0]["evaluation_start"] == day.isoformat() and result[0]["status"] == "no_pattern":
            return True
    return False


def create_incident(tx: Transaction, scope: str, building_id: str, alert_start: str, cutoff: datetime, note=""):
    rows = tx.readings(scope)
    analysis = analyze(rows, cutoff=cutoff)
    building = next((b for b in analysis["buildings"] if b["building_id"] == building_id), None)
    alert = next((a for a in building["alerts"] if instant(a["start"]) == instant(alert_start)), None) if building else None
    if not alert:
        raise WorkflowError("No qualifying alert exists for that building and start time at this cutoff. Refresh the assessment.")
    incidents = [i for i in tx.incidents(scope) if i["building_id"] == building_id]
    # Replayed old alerts belong to their original episode, even if it is now repaired.
    for incident in incidents:
        if instant(incident["start"]) <= instant(alert["start"]) < instant(incident["last_alert_end"]):
            if cutoff < instant(incident["created_at"]):
                raise Conflict("This alert already has an incident recorded at a later evaluation time. Return to that cutoff to view it.")
            return incident, False
    if incidents:
        previous = incidents[-1]
        if cutoff < instant(previous["events"][-1]["effective_at"]):
            raise Conflict("A later incident event already exists. Return to that cutoff or later before recording new actions.")
        same_episode = previous["status"] != "Repaired" or not clean_night_between(
            [r for r in rows if r.building_id == building_id and r.timestamp + timedelta(hours=1) <= cutoff],
            instant(previous["repair_time"]), instant(alert["start"]))
        if same_episode:
            previous["last_alert_end"] = max(previous["last_alert_end"], alert["end"])
            tx.save_incident(scope, previous)
            event(tx, scope, previous, "Alert linked", cutoff,
                  "Alert linked to the existing episode; a new episode requires repair and a complete normal overnight period.", alert_end=alert["end"])
            return previous, False
    incident = {"id": str(uuid4()), "building_id": building_id, "status": "Open",
                "start": alert["start"], "first_alert_end": alert["end"], "last_alert_end": alert["end"],
                "created_at": cutoff.isoformat(), "repair_time": None, "alert": alert}
    tx.save_incident(scope, incident)
    event(tx, scope, incident, "Incident opened", cutoff, note, alert_end=alert["end"])
    return incident, True


def change_incident(tx: Transaction, scope: str, incident_id: str, cutoff: datetime,
                    status: str | None = None, note: str = "", repair_time: datetime | None = None):
    incident = next((i for i in tx.incidents(scope) if i["id"] == incident_id), None)
    if incident is None:
        raise WorkflowError("Incident not found in this workspace.")
    if cutoff < instant(incident["events"][-1]["effective_at"]):
        raise Conflict("Actions cannot precede the incident's latest event. Advance the evaluation cutoff first.")
    if status:
        expected = {"Open": "Investigating", "Investigating": "Repaired"}.get(incident["status"])
        if status != expected:
            raise WorkflowError("Invalid transition. Use Open → Investigating → Repaired; repaired incidents cannot be reopened.")
        if status == "Repaired":
            assessment = analyze(tx.readings(scope), cutoff=cutoff)
            building = next((b for b in assessment["buildings"] if b["building_id"] == incident["building_id"]), None)
            alert_end = max([incident["last_alert_end"]] + [a["end"] for a in building["alerts"]]) if building else incident["last_alert_end"]
            lower = max(instant(incident["created_at"]), instant(alert_end), instant(incident["events"][-1]["effective_at"]))
            if repair_time is None or not lower <= repair_time <= cutoff:
                raise WorkflowError("Repair time must be at or after the latest incident event and observed alert end, and no later than the evaluation cutoff.")
            incident["repair_time"] = repair_time.isoformat()
            incident["last_alert_end"] = alert_end
        elif repair_time:
            raise WorkflowError("A repair time is only valid when recording Repaired.")
        incident["status"] = status
    elif repair_time:
        raise WorkflowError("A repair time is only valid when recording Repaired.")
    elif not note.strip():
        raise WorkflowError("Enter a note or choose the next status.")
    tx.save_incident(scope, incident)
    event(tx, scope, incident, f"Marked {status}" if status else "Note added", cutoff, note.strip(), repair_time=incident["repair_time"], alert_end=incident["last_alert_end"])
    return incident


def verify_repair(rows: list[Reading], incident: dict, incidents: list[dict], cutoff: datetime):
    if incident["status"] != "Repaired" or not incident["repair_time"]:
        return None
    repair = instant(incident["repair_time"])
    start = repair.replace(hour=0, minute=0, second=0, microsecond=0)
    if start < repair:
        start += timedelta(days=1)
    end = start + timedelta(days=3)
    reference_end = instant(incident["start"]).replace(hour=0, minute=0, second=0, microsecond=0)
    reference_start = reference_end - timedelta(days=28)
    known = [i for i in incidents if i["building_id"] == incident["building_id"]]

    def affected(timestamp):
        for other in known:
            interval_end = max(instant(other["repair_time"]), instant(other["last_alert_end"])) if other["repair_time"] else cutoff
            if timestamp < interval_end and timestamp + timedelta(hours=1) > instant(other["start"]):
                return True
        return False

    available = {r.timestamp: r.liters for r in rows if r.building_id == incident["building_id"] and r.timestamp + timedelta(hours=1) <= cutoff}
    counts, baselines = {}, {}
    excluded = 0
    for hour in range(6):
        samples = []
        for timestamp, liters in available.items():
            if reference_start <= timestamp < reference_end and timestamp.hour == hour:
                if affected(timestamp):
                    excluded += 1
                else:
                    samples.append(liters)
        counts[str(hour)] = len(samples)
        baselines[hour] = median(samples) if len(samples) >= MIN_HISTORY else None
    targets = [start + timedelta(days=d, hours=h) for d in range(3) for h in range(6)]
    elapsed = [t for t in targets if t + timedelta(hours=1) <= cutoff]
    observed = [t for t in elapsed if t in available]
    paired = [t for t in observed if baselines[t.hour] is not None and not affected(t)]
    total = sum(available[t] for t in paired)
    expected = sum(baselines[t.hour] for t in paired)
    ready = len(paired) == 18
    difference = expected - total if ready else None
    return {"status": "Compared" if ready else "Awaiting data", "window_start": start.isoformat(),
            "window_end": end.isoformat(), "reference_start": reference_start.isoformat(), "reference_end": reference_end.isoformat(),
            "target_hours": 18, "elapsed_hours": len(elapsed), "observed_hours": len(observed),
            "matched_hours": len(paired), "missing_hours": len(elapsed) - len(observed), "pending_hours": 18 - len(elapsed),
            "incident_excluded_hours": sum(affected(t) for t in observed),
            "unsupported_history_hours": sum(baselines[t.hour] is None and not affected(t) for t in observed),
            "coverage_percent": round(len(paired) / 18 * 100, 1), "baseline_samples": counts, "excluded_reference_hours": excluded,
            "observed_liters": round(total, 2) if paired else None, "expected_liters": round(expected, 2) if paired else None,
            "difference_liters": round(difference, 2) if ready else None,
            "percentage_difference": round(difference / expected * 100, 2) if ready and expected > 0 else None,
            "method": "Same-building, same-hour median over the 28 days before the incident's first night; at least 7 clean samples per hour. Known incident intervals are excluded. Compare only matched, completed 00:00–06:00 hours over the first 3 full nights after repair. Positive difference means lower consumption; negative means an increase. No missing-hour extrapolation."}


def snapshot(tx: Transaction, scope: str, cutoff: datetime | None = None):
    rows = tx.readings(scope)
    cutoff = cutoff or latest_cutoff(rows)
    incidents = visible_incidents(tx.incidents(scope), cutoff)
    for incident in incidents:
        incident["verification"] = verify_repair(rows, incident, incidents, cutoff)
    return {"scope": scope, "cutoff": cutoff.isoformat(), "analysis": analyze(rows, tx.source(scope), cutoff), "incidents": incidents}
