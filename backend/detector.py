"""Small, deterministic detector. All comparisons use Asia/Kolkata hour starts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo
import csv
import io
import math
import re

IST = ZoneInfo("Asia/Kolkata")
MIN_HISTORY = 7
LOOKBACK_DAYS = 28
MIN_DURATION = 3
MAX_ROWS = 100_000
MAX_BYTES = 8 * 1024 * 1024
FIELDS = ["building_id", "timestamp", "consumption_liters"]
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})$")


class CSVError(ValueError):
    pass


@dataclass(frozen=True)
class Reading:
    building_id: str
    timestamp: datetime
    liters: float


def parse_csv(content: bytes) -> list[Reading]:
    if len(content) > MAX_BYTES:
        raise CSVError("The CSV exceeds 8 MB. Upload a smaller file.")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVError("Save your CSV with UTF-8 encoding and try again.") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
    result, seen = [], set()
    try:
        if reader.fieldnames != FIELDS:
            raise CSVError("Expected exactly these columns in order: " + ",".join(FIELDS))
        for row in reader:
            line = reader.line_num
            if len(result) >= MAX_ROWS:
                raise CSVError("The CSV exceeds 100,000 readings. Upload a smaller file.")
            if None in row or any(value is None for value in row.values()):
                raise CSVError(f"Line {line}: expected exactly three values.")
            building = row["building_id"].strip()
            if not building or len(building) > 80 or not building.isprintable():
                raise CSVError(f"Line {line}: building_id must contain 1–80 printable characters.")
            raw_time = row["timestamp"].strip()
            if not TIMESTAMP.fullmatch(raw_time):
                raise CSVError(f"Line {line}: use an ISO timestamp with an explicit timezone, e.g. 2026-09-29T01:00:00+05:30.")
            try:
                # datetime accepts out-of-range offset minutes by normalizing them; reject those.
                if raw_time[-1] != "Z" and (int(raw_time[-5:-3]) > 23 or int(raw_time[-2:]) > 59):
                    raise ValueError
                timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(IST)
                if not 1901 <= timestamp.year <= 9998:
                    raise ValueError
            except (ValueError, OverflowError) as exc:
                raise CSVError(f"Line {line}: invalid timestamp '{raw_time}'. Use a real date with a valid timezone offset (years 1901–9998).") from exc
            if timestamp.minute or timestamp.second or timestamp.microsecond:
                raise CSVError(f"Line {line}: each reading must start on a whole hour in Asia/Kolkata.")
            try:
                liters = float(row["consumption_liters"])
                if not math.isfinite(liters) or liters < 0:
                    raise ValueError
            except ValueError as exc:
                raise CSVError(f"Line {line}: consumption_liters must be a finite, non-negative number.") from exc
            # Also keep totals finite for adversarial or accidental scientific-notation values.
            if liters > 1_000_000_000:
                raise CSVError(f"Line {line}: consumption exceeds the supported limit of 1,000,000,000 liters per hour.")
            key = (building, timestamp)
            if key in seen:
                raise CSVError(f"Line {line}: duplicate building/timestamp for '{building}' at {timestamp.isoformat()} (including equivalent timezone offsets).")
            seen.add(key)
            result.append(Reading(building, timestamp, liters))
    except csv.Error as exc:
        raise CSVError(f"Line {reader.line_num}: malformed CSV. Check quotes and commas.") from exc
    if not result:
        raise CSVError("The CSV contains no readings. Add at least one data row below the header.")
    return sorted(result, key=lambda reading: (reading.building_id, reading.timestamp))


def parse_cutoff(value: str) -> datetime:
    """An explicit instant, not an implied server-local time."""
    try:
        if not TIMESTAMP.fullmatch(value):
            raise ValueError
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)
        if not 1901 <= result.year <= 9998:
            raise ValueError
        return result
    except (ValueError, OverflowError) as exc:
        raise CSVError("Use a valid ISO timestamp with an explicit timezone offset, e.g. 2026-09-30T06:00:00+05:30.") from exc


def analyze(readings: list[Reading], source: str = "upload", cutoff: datetime | None = None) -> dict:
    if cutoff is not None:
        if cutoff.tzinfo is None:
            raise CSVError("Evaluation cutoff requires an explicit timezone offset.")
        readings = [r for r in readings if r.timestamp + timedelta(hours=1) <= cutoff]
    if not readings:
        return {"source": source, "timezone": "Asia/Kolkata", "reading_count": 0,
                "building_count": 0, "buildings": [], "period_start": None, "period_end": None}
    groups = defaultdict(list)
    for reading in readings:
        groups[reading.building_id].append(reading)
    buildings = [analyze_building(name, rows) for name, rows in sorted(groups.items())]
    return {"source": source, "timezone": "Asia/Kolkata", "reading_count": len(readings),
            "building_count": len(buildings), "buildings": buildings,
            "period_start": min(r.timestamp for r in readings).isoformat(),
            "period_end": (max(r.timestamp for r in readings) + timedelta(hours=1)).isoformat()}


def analyze_building(name: str, rows: list[Reading]) -> dict:
    rows = sorted(rows, key=lambda r: r.timestamp)
    # Latest night whose 06:00 boundary has passed according to this building's data.
    last_end = rows[-1].timestamp + timedelta(hours=1)
    start = last_end.replace(hour=0, minute=0, second=0, microsecond=0)
    if last_end.hour < 6:
        start -= timedelta(days=1)
    history = defaultdict(list)
    by_time = {r.timestamp: r.liters for r in rows}
    for row in rows:
        if start - timedelta(days=LOOKBACK_DAYS) <= row.timestamp < start:
            history[row.timestamp.hour].append(row.liters)
    points = []
    for hour in range(24):
        samples = history[hour]
        baseline = median(samples) if len(samples) >= MIN_HISTORY else None
        threshold = max(2 * baseline, baseline + 50) if baseline is not None and hour < 6 else None
        timestamp = start + timedelta(hours=hour)
        observed = by_time.get(timestamp)
        points.append({"timestamp": timestamp.isoformat(), "hour": hour, "liters": observed,
                       "baseline": baseline, "threshold": threshold, "history_count": len(samples),
                       "unusual": observed is not None and threshold is not None and observed > threshold})
    overnight = points[:6]
    runs, current = [], []
    for point in overnight:
        if point["unusual"]:
            current.append(point)
        else:
            if len(current) >= MIN_DURATION:
                runs.append(current)
            current = []
    if len(current) >= MIN_DURATION:
        runs.append(current)
    alerts = []
    for run in runs:
        alerts.append({"title": "Possible water loss", "start": run[0]["timestamp"],
                       "end": (datetime.fromisoformat(run[-1]["timestamp"]) + timedelta(hours=1)).isoformat(),
                       "duration_hours": len(run), "observed_liters": round(sum(p["liters"] for p in run), 2),
                       "baseline_liters": round(sum(p["baseline"] for p in run), 2),
                       "threshold_liters": round(sum(p["threshold"] for p in run), 2),
                       "hours": run})
    missing = sum(p["liters"] is None for p in overnight)
    insufficient = sum(p["baseline"] is None for p in overnight)
    status = ("possible_loss" if alerts else "insufficient_history" if insufficient else
              "incomplete_data" if missing else "no_pattern")
    return {"building_id": name, "reading_count": len(rows), "status": status,
            "evaluation_start": start.isoformat(), "evaluation_end": (start + timedelta(hours=6)).isoformat(),
            "missing_hours": missing, "insufficient_history_hours": insufficient,
            "overnight_liters": round(sum(p["liters"] for p in overnight if p["liters"] is not None), 2),
            "baseline_liters": round(sum(p["baseline"] for p in overnight), 2) if not insufficient else None,
            "points": points, "alerts": alerts}
