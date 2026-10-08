"""Bounded, single-item session snapshots. One conditional PutItem is the commit.

No multi-batch partial writes, table scans, SQLite files, or process-local state.
This deliberately trades scale/efficiency for a small, sound hackathon adapter.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import secrets
import time
import zlib

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .detector import Reading
from .storage import CapacityExceeded, Conflict, SessionExpired

MAX_UPLOAD_BYTES = 512 * 1024
MAX_UPLOAD_ROWS = 3000
MAX_SESSION_READINGS = 12000
MAX_SESSION_BUILDINGS = 12
MAX_SESSION_EVENTS = 300
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024  # Leaves ample room below DynamoDB's 400 KiB item limit.
SESSION_SECONDS = 24 * 60 * 60
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def dynamodb_client():
    # Credentials come only from the normal AWS SDK chain / Lambda execution role.
    return boto3.client("dynamodb", config=Config(connect_timeout=2, read_timeout=4,
                                                 retries={"mode": "standard", "total_max_attempts": 2}))


def empty_document():
    return {"schema": 1, "scopes": {}, "metadata": {}}


def encode_document(document):
    scopes = document["scopes"].values()
    if sum(len(s["readings"]) for s in scopes) > MAX_SESSION_READINGS:
        raise CapacityExceeded("Session limit: 12,000 total readings across uploads and demos. No changes were saved.")
    if len({r[0] for s in document["scopes"].values() for r in s["readings"]}) > MAX_SESSION_BUILDINGS:
        raise CapacityExceeded("Session limit: 12 buildings. No changes were saved.")
    if sum(len(s["events"]) for s in document["scopes"].values()) > MAX_SESSION_EVENTS:
        raise CapacityExceeded("Session limit: 300 maintenance events. No changes were saved.")
    raw = json.dumps(document, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise CapacityExceeded("Session document exceeds 2 MiB. No changes were saved.")
    packed = zlib.compress(raw)
    if len(packed) > MAX_PAYLOAD_BYTES:
        raise CapacityExceeded("Session exceeds the 256 KiB compressed storage limit. No changes were saved.")
    return packed


def decode_document(packed):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(packed, MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES or not decoder.eof or decoder.unused_data:
        raise RuntimeError("Invalid stored session document")
    document = json.loads(raw)
    if document.get("schema") != 1:
        raise RuntimeError("Unsupported stored session schema")
    return document


def session_key(token):
    if not TOKEN_PATTERN.fullmatch(token):
        raise SessionExpired("Session missing or expired. Start a new demo session to continue.")
    return "SESSION#" + hashlib.sha256(token.encode("ascii")).hexdigest()


def issue_session(table_name, client=None, now=None):
    client = client or dynamodb_client()
    now = int(time.time()) if now is None else now
    token = secrets.token_urlsafe(32)
    expires = now + SESSION_SECONDS
    client.put_item(TableName=table_name, Item={
        "pk": {"S": session_key(token)}, "revision": {"N": "0"},
        "expires_at": {"N": str(expires)}, "payload": {"B": encode_document(empty_document())},
    }, ConditionExpression="attribute_not_exists(pk)")
    return {"token": token, "expires_at": expires}


class DynamoDBStorage:
    def __init__(self, table_name, token, client=None, clock=time.time):
        self.table_name = table_name
        self.key = session_key(token)  # Never retain or log the bearer credential itself.
        self.client = client or dynamodb_client()
        self.clock = clock

    @contextmanager
    def transaction(self):
        result = self.client.get_item(TableName=self.table_name, Key={"pk": {"S": self.key}}, ConsistentRead=True)
        item = result.get("Item")
        if not item or int(item["expires_at"]["N"]) <= self.clock():
            raise SessionExpired("Session missing or expired. Start a new demo session to continue.")
        original = decode_document(item["payload"]["B"])
        tx = SnapshotTransaction(deepcopy(original))
        yield tx
        if int(item["expires_at"]["N"]) <= self.clock():
            raise SessionExpired("Session expired during this request. No changes were saved.")
        if tx.document == original:
            return
        packed = encode_document(tx.document)  # All size checks precede the only write.
        revision = int(item["revision"]["N"])
        try:
            self.client.put_item(TableName=self.table_name, Item={
                "pk": {"S": self.key}, "revision": {"N": str(revision + 1)},
                "expires_at": item["expires_at"], "payload": {"B": packed},
            }, ConditionExpression="revision = :revision AND expires_at > :now",
                ExpressionAttributeValues={":revision": {"N": str(revision)}, ":now": {"N": str(int(self.clock()))}})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict("This session changed in another request, or expired. Refresh the workspace before retrying; no partial changes were saved.") from None
            raise


class SnapshotTransaction:
    def __init__(self, document):
        self.document = document

    def scope(self, scope):
        return self.document["scopes"].get(scope, {"readings": [], "incidents": {}, "events": []})

    def mutable_scope(self, scope):
        return self.document["scopes"].setdefault(scope, {"readings": [], "incidents": {}, "events": []})

    def readings(self, scope):
        return sorted([Reading(r[0], datetime.fromisoformat(r[1]), r[2]) for r in self.scope(scope)["readings"]],
                      key=lambda r: (r.building_id, r.timestamp))

    def source(self, scope):
        rows = self.scope(scope)["readings"]
        return "upload" if any(not r[3] for r in rows) or scope == "uploads" and not rows else "simulated"

    def add_readings(self, scope, rows, simulated=False):
        if scope == "uploads" and len(rows) > MAX_UPLOAD_ROWS:
            raise CapacityExceeded("Hosted uploads are limited to 3,000 rows per file. No changes were saved.")
        current = self.mutable_scope(scope)["readings"]
        existing = {(r[0], r[1]): r[2] for r in current}
        additions, repeated = [], 0
        for row in rows:
            key = (row.building_id, row.timestamp.isoformat())
            if key in existing:
                if existing[key] != row.liters:
                    raise Conflict(f"Conflicting reading for {row.building_id} at {key[1]}: stored {existing[key]:g} L, uploaded {row.liters:g} L. Entire upload rejected; existing readings are unchanged.")
                repeated += 1
            else:
                additions.append([*key, row.liters, simulated])
                existing[key] = row.liters
        current.extend(additions)
        return {"inserted": len(additions), "repeated": repeated}

    def incidents(self, scope):
        state = self.scope(scope)
        result = []
        for incident in state["incidents"].values():
            copy = deepcopy(incident)
            copy["events"] = [deepcopy(e["event"]) for e in state["events"] if e["incident_id"] == incident["id"]]
            result.append(copy)
        return result

    def save_incident(self, scope, incident):
        state = self.mutable_scope(scope)
        if incident["status"] != "Repaired" and any(
            i["id"] != incident["id"] and i["building_id"] == incident["building_id"] and i["status"] != "Repaired"
            for i in state["incidents"].values()
        ):
            raise Conflict("An active incident already exists for this building.")
        state["incidents"][incident["id"]] = deepcopy({k: v for k, v in incident.items() if k not in ("events", "verification")})

    def add_event(self, scope, incident_id, event):
        state = self.mutable_scope(scope)
        if incident_id not in state["incidents"]:
            raise Conflict("Incident not found in this workspace.")
        if any(e["event"]["id"] == event["id"] for e in state["events"]):
            raise Conflict("Event already exists.")
        state["events"].append({"incident_id": incident_id, "event": deepcopy(event)})

    def get_meta(self, key):
        return self.document["metadata"].get(key)

    def set_meta(self, key, value):
        self.document["metadata"][key] = value

    def reset_replay(self):
        self.document["scopes"].pop("replay", None)
        self.document["metadata"].pop("replay_stage", None)
