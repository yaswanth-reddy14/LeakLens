"""Run against SAM local on loopback only; no AWS credentials or production URLs."""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:3001"


def call(path, body=None):
    request = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=35) as response:
        assert response.status == 200
        return json.load(response)


assert call("/api/health") == {"status": "ok"}
# Upload one simulated reading using the actual HTTP multipart route.
boundary = "sam-local-smoke-boundary"
csv = b"building_id,timestamp,consumption_liters\nSmoke simulated,2026-09-01T00:00:00+05:30,40\n"
multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="simulated.csv"\r\nContent-Type: text/csv\r\n\r\n').encode() + csv + f'\r\n--{boundary}--\r\n'.encode()
request = urllib.request.Request(BASE + "/api/analyze", data=multipart,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
with urllib.request.urlopen(request, timeout=35) as response:
    assert json.load(response)["reading_count"] == 1
before = call("/api/workspace?scope=uploads")
assert before["analysis"]["reading_count"] == 1
assert before["analysis"]["buildings"][0]["status"] == "insufficient_history"
assert call("/api/replay/reset", {})["replay"]["stage"] == 0
for stage in range(4):
    state = call("/api/replay/advance", {"expected_stage": stage})
    assert state["replay"]["stage"] == stage + 1
    if stage == 0:
        assert len(state["incidents"]) == 1 and state["incidents"][0]["status"] == "Open"
    if stage == 2:
        assert state["incidents"][0]["verification"]["status"] == "Awaiting data"
assert state["incidents"][0]["status"] == "Repaired"
assert state["incidents"][0]["verification"]["status"] == "Compared"
assert call("/api/workspace?scope=replay")["incidents"][0]["id"] == state["incidents"][0]["id"]
call("/api/replay/reset", {})
assert call("/api/workspace?scope=uploads") == before
print("PASS: SAM local health, multipart upload, cross-request SQLite persistence, five-stage incident workflow, repair comparison and reset isolation.")
