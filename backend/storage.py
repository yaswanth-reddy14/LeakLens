"""SQLite is confined to this adapter. Services depend on the small protocols below."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import ContextManager, Protocol
import json
import sqlite3

from .detector import Reading


class Conflict(ValueError):
    pass


class SessionExpired(ValueError):
    pass


class CapacityExceeded(ValueError):
    pass


class Transaction(Protocol):
    def readings(self, scope: str) -> list[Reading]: ...
    def source(self, scope: str) -> str: ...
    def add_readings(self, scope: str, rows: list[Reading], simulated: bool = False) -> dict: ...
    def incidents(self, scope: str) -> list[dict]: ...
    def save_incident(self, scope: str, incident: dict) -> None: ...
    def add_event(self, scope: str, incident_id: str, event: dict) -> None: ...
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str) -> None: ...
    def reset_replay(self) -> None: ...


class Storage(Protocol):
    def transaction(self) -> ContextManager[Transaction]: ...


class SQLiteStorage:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS readings (
                    scope TEXT NOT NULL, building TEXT NOT NULL, timestamp TEXT NOT NULL,
                    liters REAL NOT NULL, simulated INTEGER NOT NULL,
                    PRIMARY KEY(scope, building, timestamp)
                );
                CREATE TABLE IF NOT EXISTS incidents (
                    scope TEXT NOT NULL, id TEXT NOT NULL, building TEXT NOT NULL,
                    status TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(scope, id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_incident
                    ON incidents(scope, building) WHERE status != 'Repaired';
                CREATE TABLE IF NOT EXISTS events (
                    scope TEXT NOT NULL, incident_id TEXT NOT NULL, id TEXT NOT NULL,
                    document TEXT NOT NULL, PRIMARY KEY(scope, id),
                    FOREIGN KEY(scope, incident_id) REFERENCES incidents(scope, id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            # Serialize check-and-write operations, including incident deduplication.
            db.execute("BEGIN IMMEDIATE")
            yield SQLiteTransaction(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


class SQLiteTransaction:
    def __init__(self, db):
        self.db = db

    def readings(self, scope):
        return [Reading(r["building"], datetime.fromisoformat(r["timestamp"]), r["liters"])
                for r in self.db.execute("SELECT * FROM readings WHERE scope=? ORDER BY building,timestamp", (scope,))]

    def source(self, scope):
        real = self.db.execute("SELECT 1 FROM readings WHERE scope=? AND simulated=0 LIMIT 1", (scope,)).fetchone()
        return "upload" if real or scope == "uploads" and not self.readings(scope) else "simulated"

    def add_readings(self, scope, rows, simulated=False):
        inserted = repeated = 0
        for row in rows:
            key = (scope, row.building_id, row.timestamp.isoformat())
            existing = self.db.execute("SELECT liters FROM readings WHERE scope=? AND building=? AND timestamp=?", key).fetchone()
            if existing:
                if existing["liters"] != row.liters:
                    raise Conflict(f"Conflicting reading for {row.building_id} at {row.timestamp.isoformat()}: stored {existing['liters']:g} L, uploaded {row.liters:g} L. Entire upload rejected; existing readings are unchanged.")
                repeated += 1
            else:
                self.db.execute("INSERT INTO readings VALUES (?,?,?,?,?)", (*key, row.liters, int(simulated)))
                inserted += 1
        return {"inserted": inserted, "repeated": repeated}

    def incidents(self, scope):
        result = []
        for row in self.db.execute("SELECT document FROM incidents WHERE scope=? ORDER BY rowid", (scope,)):
            incident = json.loads(row["document"])
            incident["events"] = [json.loads(e["document"]) for e in self.db.execute(
                "SELECT document FROM events WHERE scope=? AND incident_id=? ORDER BY rowid", (scope, incident["id"]))]
            result.append(incident)
        return result

    def save_incident(self, scope, incident):
        document = {k: v for k, v in incident.items() if k not in ("events", "verification")}
        self.db.execute("""INSERT INTO incidents VALUES (?,?,?,?,?) ON CONFLICT(scope,id)
            DO UPDATE SET status=excluded.status, document=excluded.document""",
            (scope, incident["id"], incident["building_id"], incident["status"], json.dumps(document)))

    def add_event(self, scope, incident_id, event):
        self.db.execute("INSERT INTO events VALUES (?,?,?,?)", (scope, incident_id, event["id"], json.dumps(event)))

    def get_meta(self, key):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key, value):
        self.db.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def reset_replay(self):
        # Deliberately no general 'delete workspace' operation in the public interface.
        self.db.execute("DELETE FROM incidents WHERE scope='replay'")
        self.db.execute("DELETE FROM readings WHERE scope='replay'")
        self.db.execute("DELETE FROM metadata WHERE key='replay_stage'")
