from pathlib import Path
from typing import Annotated, Literal
import os
import logging

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .demo import make_demo
from .detector import CSVError, MAX_BYTES, analyze, parse_csv, parse_cutoff
from .replay import STAGES, advance_replay, start_replay
from .storage import CapacityExceeded, Conflict, SessionExpired, SQLiteStorage, Storage
from .workflow import WorkflowError, change_incident, create_incident, latest_cutoff, snapshot

app = FastAPI(title="LeakLens", version="0.2.0", description="Local water-loss investigation and outcome comparison.")
Scope = Literal["uploads", "demo", "replay"]


def storage_mode():
    mode = os.environ.get("LEAKLENS_STORAGE", "sqlite")
    local_sam = (os.environ.get("AWS_SAM_LOCAL") == "true"
                 and os.environ.get("LEAKLENS_SAM_LOCAL_DEMO") == "true")
    if mode not in ("sqlite", "dynamodb") or (os.environ.get("AWS_LAMBDA_FUNCTION_NAME") and mode != "dynamodb" and not local_sam):
        raise RuntimeError("Invalid storage configuration")
    if local_sam and (mode != "sqlite" or not os.environ.get("LEAKLENS_DB_PATH", "").startswith("/tmp/leaklens-local/")
                      or ".." in Path(os.environ.get("LEAKLENS_DB_PATH", "")).parts):
        raise RuntimeError("SAM local demo requires isolated temporary SQLite storage")
    return mode


def get_storage(request: Request):
    if storage_mode() == "dynamodb":
        from .dynamodb_storage import DynamoDBStorage
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise SessionExpired("A demo session is required. Reload to start a session.")
        return DynamoDBStorage(os.environ["LEAKLENS_TABLE_NAME"], authorization[7:])
    return SQLiteStorage(os.environ.get("LEAKLENS_DB_PATH", str(Path(__file__).resolve().parents[1] / "data" / "leaklens.sqlite3")))


Store = Annotated[Storage, Depends(get_storage)]


@app.middleware("http")
async def hosted_boundary(request: Request, call_next):
    if storage_mode() != "dynamodb":
        return await call_next(request)
    origin = request.headers.get("origin")
    allowed = os.environ.get("LEAKLENS_FRONTEND_ORIGIN", "")
    if not allowed.startswith("https://") or allowed.endswith("/"):
        return JSONResponse(status_code=503, content={"detail": "Hosted configuration is incomplete."})
    if origin and origin != allowed:
        return JSONResponse(status_code=403, content={"detail": "This frontend origin is not allowed."})
    if request.method == "OPTIONS":
        response = Response(status_code=204)
    else:
        # API Gateway/Lambda also limit payloads; this lower limit precedes multipart parsing.
        try:
            declared = int(request.headers.get("content-length", "0"))
            if declared < 0 or declared > 600 * 1024 or len(await request.body()) > 600 * 1024:
                response = JSONResponse(status_code=413, content={"detail": "Hosted request exceeds 600 KiB. CSV files must be at most 512 KiB."})
            else:
                response = await call_next(request)
        except ValueError:
            response = JSONResponse(status_code=400, content={"detail": "Invalid request."})
        except Exception as exc:
            # Log only the exception TYPE, never events, headers, tokens, bodies or SDK messages.
            logging.getLogger("leaklens").error("Hosted request failed: %s", type(exc).__name__)
            response = JSONResponse(status_code=503, content={"detail": "The service could not complete this request. Refresh before retrying; a previous write may have completed."})
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if origin == allowed:
        response.headers["Access-Control-Allow-Origin"] = allowed
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
    return response


@app.exception_handler(SessionExpired)
async def session_error(request, exc):
    return JSONResponse(status_code=401, content={"detail": str(exc)}, headers={"WWW-Authenticate": "Bearer"})


@app.exception_handler(CapacityExceeded)
async def capacity_error(request, exc):
    return JSONResponse(status_code=413, content={"detail": str(exc)})


@app.post("/api/sessions")
def new_session():
    if storage_mode() != "dynamodb":
        raise HTTPException(status_code=404, detail="Sessions are only used by the hosted demo.")
    from .dynamodb_storage import issue_session
    return JSONResponse(issue_session(os.environ["LEAKLENS_TABLE_NAME"]), headers={"Cache-Control": "no-store"})


@app.exception_handler(CSVError)
@app.exception_handler(WorkflowError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(Conflict)
async def conflict_error(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def ensure_demo(tx):
    if not tx.readings("demo"):
        tx.add_readings("demo", parse_csv(make_demo()), simulated=True)


def effective_cutoff(tx, scope, value=None):
    if scope == "demo":
        ensure_demo(tx)
    if scope == "replay":
        if tx.get_meta("replay_stage") is None:
            raise WorkflowError("Start the guided replay first.")
        limit = parse_cutoff(STAGES[int(tx.get_meta("replay_stage"))][1])
        cutoff = parse_cutoff(value) if value else limit
        if cutoff > limit:
            raise WorkflowError("Advance the replay stage to make later readings available.")
        return cutoff
    return parse_cutoff(value) if value else latest_cutoff(tx.readings(scope))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze")
async def upload(file: Annotated[UploadFile, File()], store: Store):
    try:
        content = await file.read(MAX_BYTES + 1)
        def process():
            if storage_mode() == "dynamodb":
                from .dynamodb_storage import MAX_UPLOAD_BYTES
                if len(content) > MAX_UPLOAD_BYTES:
                    raise CapacityExceeded("Hosted CSV uploads are limited to 512 KiB and 3,000 rows. No changes were saved.")
            rows = parse_csv(content)
            simulated = content in (make_demo(), make_demo(False))
            with store.transaction() as tx:
                tx.add_readings("uploads", rows, simulated)
                return analyze(tx.readings("uploads"), tx.source("uploads"))
        return await run_in_threadpool(process)
    finally:
        await file.close()


@app.get("/api/demo")
def demo(store: Store):
    with store.transaction() as tx:
        ensure_demo(tx)
        return analyze(tx.readings("demo"), "simulated")


@app.get("/api/workspace")
def workspace(store: Store, scope: Scope = "uploads", cutoff: str | None = None):
    with store.transaction() as tx:
        result = snapshot(tx, scope, effective_cutoff(tx, scope, cutoff))
        if scope == "replay":
            stage = int(tx.get_meta("replay_stage"))
            result["replay"] = {"stage": stage, "label": STAGES[stage][0], "stage_count": len(STAGES)}
        return result


class OpenIncident(BaseModel):
    scope: Scope = "uploads"
    building_id: str
    alert_start: str
    cutoff: str
    note: str = Field(default="", max_length=2000)


class UpdateIncident(BaseModel):
    scope: Scope = "uploads"
    cutoff: str
    status: Literal["Open", "Investigating", "Repaired"] | None = None
    note: str = Field(default="", max_length=2000)
    repair_time: str | None = None


@app.post("/api/incidents")
def open_incident(body: OpenIncident, store: Store):
    with store.transaction() as tx:
        cutoff = effective_cutoff(tx, body.scope, body.cutoff)
        incident, created = create_incident(tx, body.scope, body.building_id,
                                           parse_cutoff(body.alert_start).isoformat(), cutoff, body.note.strip())
        result = snapshot(tx, body.scope, cutoff)
        result["message"] = "Incident created." if created else "Linked to the existing incident; no duplicate was created."
        result["incident_id"] = incident["id"]
        return result


@app.post("/api/incidents/{incident_id}/events")
def update_incident(incident_id: str, body: UpdateIncident, store: Store):
    with store.transaction() as tx:
        cutoff = effective_cutoff(tx, body.scope, body.cutoff)
        change_incident(tx, body.scope, incident_id, cutoff, body.status, body.note,
                        parse_cutoff(body.repair_time) if body.repair_time else None)
        return snapshot(tx, body.scope, cutoff)


@app.post("/api/replay/start")
def replay_start(store: Store):
    with store.transaction() as tx:
        return start_replay(tx)


class Advance(BaseModel):
    expected_stage: int = Field(ge=0, le=4)


@app.post("/api/replay/advance")
def replay_advance(body: Advance, store: Store):
    with store.transaction() as tx:
        return advance_replay(tx, body.expected_stage)


@app.post("/api/replay/reset")
def replay_reset(store: Store):
    with store.transaction() as tx:
        tx.reset_replay()
        return start_replay(tx)


@app.get("/api/examples/{kind}")
def example(kind: Literal["normal", "possible-water-loss"]):
    return Response(make_demo(kind == "possible-water-loss"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="simulated-{kind}.csv"'})
