"""Guided scenario: the same domain functions as user-driven incidents."""
from datetime import datetime, timedelta
import random

from .demo import make_demo
from .detector import IST, Reading, parse_csv
from .storage import Conflict
from .workflow import create_incident, change_incident, snapshot

STAGES = [
    ("Normal operation", "2026-09-29T00:00:00+05:30"),
    ("Detectable overnight anomaly", "2026-09-30T00:00:00+05:30"),
    ("Investigation", "2026-09-30T12:00:00+05:30"),
    ("Repair recorded", "2026-10-01T12:00:00+05:30"),
    ("Post-repair monitoring", "2026-10-05T06:00:00+05:30"),
]


def replay_readings():
    rows = parse_csv(make_demo())
    rng = random.Random(91)
    for building, scale in [("Hostel A", 1), ("Hostel B", 1.2), ("Hostel C", .85)]:
        for index in range(5 * 24 + 6):
            timestamp = datetime(2026, 9, 30, tzinfo=IST) + timedelta(hours=index)
            hour = timestamp.hour
            base = 45 if hour < 6 else 360 if 6 <= hour <= 9 else 245 if 18 <= hour <= 21 else 145
            liters = base * scale + rng.uniform(-7, 7)
            if building == "Hostel B":
                if timestamp < datetime(2026, 10, 1, 12, tzinfo=IST) and 1 <= hour <= 4:
                    liters += 160
                elif timestamp >= datetime(2026, 10, 1, 12, tzinfo=IST) and hour < 6:
                    liters = 32 + rng.uniform(-3, 3)
            rows.append(Reading(building, timestamp, round(liters, 2)))
    return rows


def replay_snapshot(tx):
    stage = int(tx.get_meta("replay_stage") or "0")
    result = snapshot(tx, "replay", datetime.fromisoformat(STAGES[stage][1]))
    result["replay"] = {"stage": stage, "label": STAGES[stage][0], "stage_count": len(STAGES)}
    return result


def start_replay(tx):
    if tx.get_meta("replay_stage") is None:
        tx.add_readings("replay", replay_readings(), simulated=True)
        tx.set_meta("replay_stage", "0")
    return replay_snapshot(tx)


def advance_replay(tx, expected_stage):
    start_replay(tx)
    current = int(tx.get_meta("replay_stage"))
    if expected_stage < current:
        return replay_snapshot(tx)
    if expected_stage != current or current == len(STAGES) - 1:
        raise Conflict("The replay is already at its latest stage. Reset the replay to start again.")
    stage = current + 1
    cutoff = datetime.fromisoformat(STAGES[stage][1])
    analysis = snapshot(tx, "replay", cutoff)["analysis"]
    if stage == 1:
        building = next(b for b in analysis["buildings"] if b["building_id"] == "Hostel B")
        create_incident(tx, "replay", "Hostel B", building["alerts"][0]["start"], cutoff,
                        "Simulated: overnight pattern flagged for inspection.")
    elif stage in (2, 3):
        incident = tx.incidents("replay")[0]
        if stage == 2 and incident["status"] == "Open":
            change_incident(tx, "replay", incident["id"], cutoff, "Investigating", "Simulated: inspecting taps and the tank overflow.")
        elif stage == 3:
            if incident["status"] == "Open":
                change_incident(tx, "replay", incident["id"], cutoff, "Investigating", "Simulated inspection.")
            if incident["status"] != "Repaired":
                change_incident(tx, "replay", incident["id"], cutoff, "Repaired", "Simulated: faulty valve replaced; monitoring still required.", cutoff)
    tx.set_meta("replay_stage", str(stage))
    return replay_snapshot(tx)
