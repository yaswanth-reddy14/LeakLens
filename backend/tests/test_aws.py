"""Moto emulation only: these tests never contact a real AWS endpoint."""
import asyncio
import base64
import json
import time
from datetime import datetime

import pytest
pytest.importorskip("moto")
import boto3
from moto import mock_aws
from fastapi.testclient import TestClient

from backend.demo import make_demo
from backend.detector import IST, Reading, parse_csv
from backend.dynamodb_storage import DynamoDBStorage, issue_session, session_key
from backend.main import app
from backend.replay import start_replay, advance_replay
from backend.storage import CapacityExceeded, Conflict, SessionExpired
from backend.workflow import create_incident, snapshot


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("LEAKLENS_STORAGE", "dynamodb")
    monkeypatch.setenv("LEAKLENS_TABLE_NAME", "leaklens-test")
    monkeypatch.setenv("LEAKLENS_FRONTEND_ORIGIN", "https://demo.example.com")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-south-1")
        client.create_table(TableName="leaklens-test", KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
                            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        yield client


def new_store(cloud):
    session = issue_session("leaklens-test", cloud)
    return DynamoDBStorage("leaklens-test", session["token"], cloud), session


def stored(cloud, token):
    return cloud.get_item(TableName="leaklens-test", Key={"pk": {"S": session_key(token)}}, ConsistentRead=True)["Item"]


def test_dynamo_reconnect_idempotency_and_atomic_conflict(cloud):
    store, session = new_store(cloud)
    rows = parse_csv(make_demo())
    with store.transaction() as tx:
        assert tx.add_readings("uploads", rows)["inserted"] == 2088
    before = stored(cloud, session["token"])
    reopened = DynamoDBStorage("leaklens-test", session["token"], cloud)
    with reopened.transaction() as tx:
        assert tx.readings("uploads") == rows
        assert tx.add_readings("uploads", rows)["repeated"] == 2088
    assert stored(cloud, session["token"]) == before
    with pytest.raises(Conflict):
        with reopened.transaction() as tx:
            tx.add_readings("uploads", [Reading("New", rows[0].timestamp, 1), Reading(rows[0].building_id, rows[0].timestamp, 999)])
    assert stored(cloud, session["token"]) == before


def test_dynamo_conditional_commit_prevents_lost_updates(cloud):
    store, session = new_store(cloud)
    a, b = store.transaction(), store.transaction()
    ta, tb = a.__enter__(), b.__enter__()
    ta.set_meta("winner", "A")
    tb.set_meta("loser", "B")
    a.__exit__(None, None, None)
    with pytest.raises(Conflict, match="another request"):
        b.__exit__(None, None, None)
    with store.transaction() as tx:
        assert tx.get_meta("winner") == "A"
        assert tx.get_meta("loser") is None


def test_concurrent_incidents_and_history_remain_atomic(cloud):
    store, session = new_store(cloud)
    with store.transaction() as tx:
        tx.add_readings("uploads", parse_csv(make_demo()))
    a, b = store.transaction(), store.transaction()
    ta, tb = a.__enter__(), b.__enter__()
    args = ("uploads", "Hostel B", "2026-09-29T01:00:00+05:30", datetime(2026, 9, 30, tzinfo=IST))
    first, _ = create_incident(ta, *args)
    create_incident(tb, *args)
    a.__exit__(None, None, None)
    with pytest.raises(Conflict):
        b.__exit__(None, None, None)
    with store.transaction() as tx:
        again, created = create_incident(tx, *args)
        assert not created and again["id"] == first["id"]
        assert len(tx.incidents("uploads")) == 1
        assert len(tx.incidents("uploads")[0]["events"]) == 1


def test_sessions_and_replay_reset_are_isolated_with_real_workflow(cloud):
    alice, _ = new_store(cloud)
    bob, _ = new_store(cloud)
    for store in (alice, bob):
        with store.transaction() as tx:
            tx.add_readings("uploads", parse_csv(make_demo()))
            tx.add_readings("demo", parse_csv(make_demo()), True)
            start_replay(tx)
            for stage in range(4):
                result = advance_replay(tx, stage)
            assert result["incidents"][0]["status"] == "Repaired"
            assert result["incidents"][0]["verification"]["difference_liters"] > 0
    with bob.transaction() as tx:
        bob_before = snapshot(tx, "replay")
    with alice.transaction() as tx:
        uploads = snapshot(tx, "uploads")
        demo = snapshot(tx, "demo")
        tx.reset_replay()
        assert start_replay(tx)["incidents"] == []
        assert snapshot(tx, "uploads") == uploads
        assert snapshot(tx, "demo") == demo
    with bob.transaction() as tx:
        assert snapshot(tx, "replay") == bob_before


@pytest.mark.parametrize("limit,value", [("MAX_PAYLOAD_BYTES", 10), ("MAX_DOCUMENT_BYTES", 100), ("MAX_SESSION_READINGS", 1), ("MAX_SESSION_BUILDINGS", 1), ("MAX_SESSION_EVENTS", 0)])
def test_capacity_failure_never_partially_commits(cloud, monkeypatch, limit, value):
    store, session = new_store(cloud)
    before = stored(cloud, session["token"])
    monkeypatch.setattr("backend.dynamodb_storage." + limit, value)
    with pytest.raises(CapacityExceeded):
        with store.transaction() as tx:
            tx.add_readings("uploads", parse_csv(make_demo()))
            create_incident(tx, "uploads", "Hostel B", "2026-09-29T01:00:00+05:30", datetime(2026, 9, 30, tzinfo=IST))
    assert stored(cloud, session["token"]) == before


def test_expiration_rejects_access_before_ttl_physical_cleanup(cloud):
    store, session = new_store(cloud)
    expired = DynamoDBStorage("leaklens-test", session["token"], cloud, clock=lambda: session["expires_at"])
    with pytest.raises(SessionExpired):
        with expired.transaction():
            pass
    assert stored(cloud, session["token"])["expires_at"]["N"] == str(session["expires_at"])
    # Raw token is neither the table key nor part of the stored payload.
    assert session["token"] not in str(stored(cloud, session["token"]))


def test_expiration_during_transaction_cannot_commit(cloud):
    store, session = new_store(cloud)
    now = [int(time.time())]
    store.clock = lambda: now[0]
    before = stored(cloud, session["token"])
    with pytest.raises(SessionExpired):
        with store.transaction() as tx:
            tx.set_meta("changed", "yes")
            now[0] = session["expires_at"]
    assert stored(cloud, session["token"]) == before


def test_hosted_api_requires_server_issued_tokens_and_has_explicit_cors(cloud, caplog):
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/workspace").status_code == 401
        assert client.get("/api/workspace", headers={"Authorization": "Bearer " + "a" * 43}).status_code == 401
        a = client.post("/api/sessions").json()
        b = client.post("/api/sessions").json()
        assert a["token"] != b["token"] and len(a["token"]) == 43
        ah = {"Authorization": "Bearer " + a["token"], "Origin": "https://demo.example.com"}
        bh = {"Authorization": "Bearer " + b["token"]}
        response = client.post("/api/analyze", files={"file": ("simulated.csv", make_demo())}, headers=ah)
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "https://demo.example.com"
        assert response.headers["Cache-Control"] == "no-store"
        assert client.get("/api/workspace", headers=bh).json()["analysis"]["reading_count"] == 0
        assert client.get("/api/workspace", headers=ah).json()["analysis"]["reading_count"] == 2088
        assert client.post("/api/sessions", headers={"Origin": "https://wrong.example.com"}).status_code == 403
        preflight = client.options("/api/analyze", headers={"Origin": "https://demo.example.com", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"})
        assert preflight.status_code == 204
        assert "Authorization" in preflight.headers["Access-Control-Allow-Headers"]
        assert a["token"] not in caplog.text and b["token"] not in caplog.text


def test_hosted_http_payload_and_row_limits_leave_no_data(cloud):
    with TestClient(app) as client:
        token = client.post("/api/sessions").json()["token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.post("/api/analyze", content=b"x" * (600 * 1024 + 1), headers=headers).status_code == 413
        assert client.post("/api/analyze", files={"file": ("big.csv", b"x" * (512 * 1024 + 1))}, headers=headers).status_code == 413
        rows = ["building_id,timestamp,consumption_liters"] + [f"B{i},2026-09-01T00:00:00+05:30,1" for i in range(3001)]
        result = client.post("/api/analyze", files={"file": ("rows.csv", "\n".join(rows).encode())}, headers=headers)
        assert result.status_code == 413 and "3,000" in result.json()["detail"]
        assert client.get("/api/workspace", headers=headers).json()["analysis"]["reading_count"] == 0


def test_adapter_uses_only_keyed_reads_and_conditional_writes(cloud, monkeypatch):
    methods = []
    original = cloud._make_api_call
    def record(operation, parameters):
        methods.append(operation)
        if operation == "GetItem":
            assert parameters["ConsistentRead"] is True
        if operation == "PutItem":
            assert parameters.get("ConditionExpression")
        return original(operation, parameters)
    monkeypatch.setattr(cloud, "_make_api_call", record)
    store, _ = new_store(cloud)
    with store.transaction() as tx:
        tx.add_readings("uploads", parse_csv(make_demo()))
    assert set(methods) == {"GetItem", "PutItem"}


def test_lambda_http_api_v2_entry_point(cloud):
    from backend.lambda_handler import handler
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        event = {"version": "2.0", "routeKey": "ANY /{proxy+}", "rawPath": "/api/health", "rawQueryString": "",
                 "headers": {"host": "test.execute-api.ap-south-1.amazonaws.com"},
                 "requestContext": {"http": {"method": "GET", "path": "/api/health", "sourceIp": "127.0.0.1", "protocol": "HTTP/1.1"}},
                 "isBase64Encoded": False}
        response = handler(event, {})
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"status": "ok"}
        # Exercise the actual Lambda adapter's auth and binary multipart path as well.
        event["rawPath"] = "/api/sessions"
        event["requestContext"]["http"].update(method="POST", path="/api/sessions")
        response = handler(event, {})
        assert response["statusCode"] == 200
        token = json.loads(response["body"])["token"]
        boundary = "leaklens-test-boundary"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample.csv"\r\n'
                'Content-Type: text/csv\r\n\r\n').encode() + make_demo() + f'\r\n--{boundary}--\r\n'.encode()
        event["rawPath"] = "/api/analyze"
        event["requestContext"]["http"]["path"] = "/api/analyze"
        event["headers"].update({"authorization": "Bearer " + token,
                                 "content-type": "multipart/form-data; boundary=" + boundary})
        event.update(body=base64.b64encode(body).decode(), isBase64Encoded=True)
        response = handler(event, {})
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["reading_count"] == 2088
    finally:
        loop.close()
        asyncio.set_event_loop(None)
