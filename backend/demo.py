"""Reproducible simulated data; run: python -m backend.demo."""
from datetime import datetime, timedelta
from pathlib import Path
import csv
import io
import random

from .detector import IST, FIELDS


def make_demo(anomaly: bool = True) -> bytes:
    rng = random.Random(42)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(FIELDS)
    start = datetime(2026, 9, 1, tzinfo=IST)
    for building, scale in [("Hostel A", 1.0), ("Hostel B", 1.2), ("Hostel C", 0.85)]:
        for day in range(29):
            for hour in range(24):
                base = 45 if hour < 6 else 360 if 6 <= hour <= 9 else 245 if 18 <= hour <= 21 else 145
                liters = max(0, base * scale + rng.uniform(-7, 7))
                if anomaly and building == "Hostel B" and day == 28 and 1 <= hour <= 4:
                    liters += 160
                writer.writerow([building, (start + timedelta(days=day, hours=hour)).isoformat(), round(liters, 2)])
    return output.getvalue().encode("utf-8")


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "examples"
    target.mkdir(exist_ok=True)
    (target / "simulated-possible-water-loss.csv").write_bytes(make_demo())
    (target / "simulated-normal.csv").write_bytes(make_demo(False))
    print("Generated two simulated CSVs (2,088 readings each; seed 42).")
