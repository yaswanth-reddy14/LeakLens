"""Test fixture only. Never touches the user's data/leaklens.sqlite3 database."""
from pathlib import Path
import sqlite3

from backend.storage import SQLiteStorage

path = Path(__file__).resolve().parents[2] / ".tools" / "e2e.sqlite3"
SQLiteStorage(path)
with sqlite3.connect(path) as db:
    for table in ("events", "incidents", "readings", "metadata"):
        db.execute(f"DELETE FROM {table}")
