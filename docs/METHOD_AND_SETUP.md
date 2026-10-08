# LeakLens

A local application for a hostel maintenance supervisor: **upload → detection → investigation → repair → outcome comparison**. React + TypeScript + Vite, Python FastAPI, and SQLite. The original dashboard, CSV contract, hourly chart, and explainable **possible water loss** detector remain in place. No production authentication, chatbot, sensors, or maps. SQLite local development remains the default; optional AWS deployment support is documented in [AWS_DEPLOYMENT.md](../AWS_DEPLOYMENT.md).

## Run locally

Prerequisites: Python 3.11 or newer and Node.js 22.12 or newer (Node 22 LTS recommended). Run all commands from this repository's root. The backend needs internet access once to install dependencies; the application processes readings locally. Readings, incidents, and maintenance events persist in `data/leaklens.sqlite3`, which is created automatically and excluded from version control. Browser reloads restore the selected workspace/cutoff; backend restarts retain the database. SQLite is part of Python: no additional database service is needed.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd ci
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Keep that terminal open. In a second terminal in the same directory:

```powershell
npm.cmd run dev
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm ci
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
npm run dev
```

Open **http://127.0.0.1:5173**. Click **Load demo data** or **Upload readings**. The demo automatically selects the building with an alert. Use the building selector to compare the other hostels. API documentation: http://127.0.0.1:8000/docs. Vite proxies `/api` to the backend; no CORS configuration is needed for this setup.

On the original Windows workspace, a portable, checksum-verified Node installation was downloaded to the ignored `.tools` directory for validation. If Node is still not on your PATH, run this in each terminal before npm commands (or install Node normally):

```powershell
$env:Path = "$PWD\.tools\node-v22.23.3-win-x64;$env:Path"
```

`package-lock.json` records the tested frontend dependencies. For the exact tested Python versions, install `backend/requirements.lock.txt` instead of `backend/requirements.txt`; the latter lists the direct dependencies with supported ranges.

### Checks and production build

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

On macOS/Linux use `.venv/bin/python -m pytest backend/tests -q`. Linux may require `npx playwright install --with-deps chromium` for browser dependencies. End-to-end tests start dedicated servers on ports **5174, 5175, and 8001** and use `.tools/e2e.sqlite3`. They reset that test database before each browser test, never the normal workspace. Leave these test ports free. Tests require the virtual environment and example CSVs included in this repo. Backend tests use temporary databases.

`npm run build` runs strict TypeScript checks and writes the frontend to `dist/`. To check that build locally, keep FastAPI running and execute `npm run preview`, then open http://127.0.0.1:4173. This is a local preview, not a production deployment.

## CSV contract

```csv
building_id,timestamp,consumption_liters
Hostel A,2026-09-29T00:00:00+05:30,47.8
Hostel A,2026-09-29T01:00:00+05:30,43.2
```

- Header names and order must match exactly. UTF-8 (with or without BOM), comma-delimited. Extra columns are rejected; blank lines are ignored.
- Each timestamp is the **start of a one-hour interval**. The value is liters consumed during that interval, **not a cumulative meter reading**.
- ISO timestamps need an explicit offset (`+05:30`, another valid offset, or `Z`). Seconds are optional. Timestamps must align to a whole hour **after conversion to Asia/Kolkata**. For example, `2026-08-31T18:30:00Z` means midnight on 1 September in Kolkata. Fractional seconds are unsupported.
- Building identifiers are trimmed, case-sensitive, 1–80 printable characters. Timestamp years 1901–9998 are supported.
- Reject negative, non-finite, missing, or non-numeric consumption; invalid dates; timezone-free timestamps; duplicate building/instant pairs (even with different offsets). Limits: 8 MB, 100,000 readings, 1 billion liters per reading. Errors identify the first bad line; the entire file is rejected, never silently partially imported.
- Rows can arrive out of order. Missing hours remain missing; they are never imputed as zero. An actual reading of zero is valid.

## Detection method and assumptions

The implementation is in `backend/detector.py`; its constants are deliberately visible and simple.

1. **Select the evaluation period per building.** Take the end of its latest reading (timestamp + one hour). Select the latest midnight–06:00 Asia/Kolkata window whose end is no later than that time. This can be a historical date. If the upload ends mid-night, that ongoing night is not yet evaluated. The UI shows the exact evaluated date. Different buildings can have different latest nights.
2. **Build a historical baseline.** For each hour, use only that same building's readings at that local hour within the 28 calendar days strictly before the evaluated midnight. Compute the median, requiring at least 7 samples for that hour. Current-night readings never enter their own baseline. The chart shows this same prior-period baseline for daytime hours too, but daytime is not checked for alerts.
3. **Set an hourly threshold.** `max(2 × baseline, baseline + 50 liters)`. A reading must be strictly greater than the threshold. This combines a relative change with a minimum absolute change so near-zero baselines do not create trivial alerts.
4. **Require persistence.** An alert needs at least 3 consecutive unusual hourly intervals between 00:00 and 06:00 (hour starts 0 through 5). Normal readings, missing readings, and hours without enough history break a run. Report each qualifying run with its start/end, duration, observed total, baseline total, and sum of the per-hour thresholds. Detection compares individual hours, not period totals. The table exposes exact hourly evidence and sample counts.
5. **Keep uncertainty visible.** If a run qualifies, report possible water loss even if other overnight hours are missing or lack history, and display those limitations. Without a qualifying run, report insufficient history first, then incomplete readings, otherwise no sustained pattern. An incomplete assessment never appears as a clean result.

These thresholds are a transparent hackathon heuristic, not calibrated probabilities. “Comparable” means the same building and local clock hour; weekday/weekend, occupancy, holidays, cleaning, tank filling, and other operational changes are not modeled. Seven samples is a minimum rule, not proof of statistical reliability. The median tolerates occasional spikes but prolonged unusual history can raise the baseline. Each evaluation checks **only the latest eligible night at its cutoff**. Select an earlier cutoff to inspect an earlier night; the app does not automatically scan every historical night. Short, daytime, or smaller losses may be missed. High consumption can have legitimate explanations; inspect taps, tanks, and schedules before deciding what action to take. Alerts never establish the cause or confirm a leak.

## Reproducible simulated examples

All supplied examples are **simulated**, not actual hostel measurements:

- `examples/simulated-possible-water-loss.csv`: three buildings, 29 full days (1–29 September 2026), 2,088 readings. Hostel B has an extra **160 L in each hour beginning 01:00, 02:00, 03:00, and 04:00 on 29 September**. This yields one four-hour possible water loss alert. Hostels A and C remain normal under this rule.
- `examples/simulated-normal.csv`: identical seed and underlying consumption, with no injected increase. Includes ordinary morning and evening peaks.

Both files are downloadable in the UI. The original **Load demo data** button opens an isolated quick sample; the **Start / resume guided replay** button opens the extended maintenance scenario described below. Regenerate the original CSVs byte-for-byte with:

```powershell
.\.venv\Scripts\python.exe -m backend.demo
```

Use `.venv/bin/python -m backend.demo` on macOS/Linux. The generator uses Python's `random.Random(42)`, fixed dates, and standard-library CSV output. Backend demo/download endpoints use the same generator. Uploading an exact supplied example is marked simulated by content comparison, but it is persisted in the **uploads** workspace. Edited examples are treated as user uploads, so their provenance must be understood by the user. The two original example files intentionally disagree at the injected hours: uploading both to the same saved workspace therefore produces a conflict. Use the isolated quick demo for the anomaly and upload the normal example separately, or use a separate database for experiments.

## Persistent uploads and conflict policy

Uploads merge into the `uploads` workspace. The canonical key is `(workspace, building_id, timestamp converted to Asia/Kolkata)`. An identical numeric value at an existing key is a no-op. A different value is an HTTP **409 Conflict** with the building, timestamp, stored liters, and uploaded liters. The entire upload transaction rolls back, including any new rows in that batch. There is deliberately no silent overwrite or correction UI in this milestone. The original CSV validator still rejects duplicate rows **within a file**, even if their values match.

Only parsed readings are stored, not the original CSV file. The quick sample (`demo`) and guided scenario (`replay`) have separate namespaces from uploads, including their incidents and events. A replay reset clears only `replay`. The SQLite adapter uses transactions and a unique active-incident constraint to prevent concurrent duplicate creation. Services use a small `Storage`/`Transaction` interface; the bounded DynamoDB adapter preserves atomicity with a conditional whole-session snapshot write. See AWS_DEPLOYMENT.md for hosted limits and session isolation.

Optionally choose a different local database before starting FastAPI:

```powershell
$env:LEAKLENS_DB_PATH = "$PWD\data\another-workspace.sqlite3"
```

On macOS/Linux: `export LEAKLENS_DB_PATH="$PWD/data/another-workspace.sqlite3"`. Stop the backend before copying the database for a manual backup. No schema migration or import/correction tool is included.

## Historical evaluation

Use **Evaluate as of (Asia/Kolkata)** and **Apply cutoff**. **Latest available** restores the default per-building latest-eligible-night assessment. API: `GET /api/workspace?scope=uploads&cutoff=2026-09-30T06:00:00%2B05:30` (encode the `+` when using a URL). The API requires an explicit timezone offset; the UI explicitly interprets its date/time input in Asia/Kolkata.

A reading is available only when its full hourly interval has ended: `timestamp + 1 hour <= cutoff`. Filter **before** selecting the latest night, counting readings, showing chart values, building baselines, or verifying repairs. A 05:00 reading is unavailable at 05:59. An incomplete current night is not evaluated as if it were complete. The chart may show empty slots for later hours, but no future consumption values. A missing entire recent period can leave an older eligible night selected; always read the displayed assessment date. There is no intrahour or real-time detection claim.

This is a **measurement-time retrospective view of currently uploaded data**, not an ingestion-time archive: the CSV does not tell us when a reading first became known to the supervisor. Backfilled readings can change a historical assessment. Incident status and notes are reconstructed from events effective at or before the cutoff; later actions are hidden. Previously recorded alert evidence is retained as an incident snapshot.

## Investigation and repair workflow

1. Upload readings, select a building, and optionally apply a historical cutoff.
2. On a qualifying alert, choose **Create incident from alert**. The server recomputes the alert at that cutoff; the client cannot invent alert evidence.
3. Add a maintenance note and choose **Start investigation**. Further notes can be saved with **Save note**.
4. Advance the cutoff if necessary, enter **Repair time (Asia/Kolkata)**, add a note, and choose **Record repair**.
5. Upload later readings or advance the cutoff; view the comparison and coverage under **Investigation & repair**. Reloads retain the incident and notes.

Allowed status transitions are strictly **Open → Investigating → Repaired**. Reopening, skipping stages, repeating a transition, and events before the latest incident event are rejected. Repair time must be at or after the incident's creation, latest event, and observed alert end, and no later than the evaluation cutoff. This deliberately requires entering actions in chronological order. Notes remain possible after repair. **Repaired is a user-recorded status**, independent of measured improvement.

The incident's `created_at` and event `effective_at` are the selected **evaluation time** so historical investigations and the replay can be recorded consistently. Every event also has a separate real `recorded_at` timestamp for the app audit trail. The UI labels both. A repair can precede the wall-clock recording time but cannot precede the incident's effective chronology.

At most one unrepaired incident exists per building per workspace. Repeated alerts and consecutive anomalous nights attach to that episode. Replaying the same alert is idempotent and adds no duplicate incident. After repair, continued high consumption still links to the old episode until a **complete, sufficiently supported overnight assessment with no sustained pattern** occurs between repair and a later alert. Only then can the later alert create a separate recurrence. Missing or insufficient-history nights do not establish recovery. This is an operational episode rule, not proof that the original cause disappeared.

## Repair verification assumptions

- Compare the **first three full overnight periods** after repair: 00:00–06:00 Asia/Kolkata, six hourly readings each, for a fixed target of **18 matched hours**. A repair exactly at midnight can include that night; otherwise start the next midnight. The UI shows the enclosing three-day window with an exclusive end; daytime hours are not compared.
- Reference window: the 28 days ending at midnight starting the incident's first anomalous night. For each local hour, use the same building's median with at least **7 clean historical samples**. Never use the anomalous period as a supposed no-repair counterfactual.
- Exclude intervals overlapping **known incidents** in the same building, from first anomaly through the later of recorded repair or last linked alert end; an unrepaired episode extends to the evaluation cutoff. Exclude known incident overlaps from post-repair comparisons too. Only incidents/events visible at that cutoff are known. Exclusion counts and per-hour historical sample counts appear in the UI.
- Sum expected and observed liters over exactly the **same matched, available hourly intervals**. Missing readings stay missing; no extrapolation, zero-fill, annual projection, or financial estimate occurs. Partial totals are labeled as matched-hour totals, not full-window consumption.
- Report **Awaiting data** until all 18 hours are present, each has a valid reference baseline, and no known incident overlaps those hours. Display matched/target coverage, available readings, elapsed missing hours, and hours not yet elapsed. A permanently missing hour or inadequate historical coverage keeps the comparison incomplete even after the window ends; upload the missing history if available.
- Once complete, difference in liters = **expected baseline − observed**. Percentage difference = difference / expected × 100 when expected is positive; it is undefined for a zero baseline. Positive means reduction, zero means no change, negative means increase. An increase does not change the recorded repair status.

The label is **estimated consumption reduction against baseline**, never proven water savings. Returning to the ordinary pre-incident baseline may show no reduction against that baseline even after a real repair. Occupancy, scheduled use, meter errors, and seasonality can alter consumption; this observational comparison does not establish causation. Weekdays/weekends remain pooled. Known incident periods only cover recorded episodes, so unrecorded problems can still contaminate history.

## Replayable simulated demo

Choose **Start / resume guided replay**. The server persists the stage and uses the real detector, incident creation, transitions, and verification functions. Use **Advance replay** through these stages:

| Stage                        | Evaluation cutoff (Asia/Kolkata) | What becomes available                                       |
| ---------------------------- | -------------------------------- | ------------------------------------------------------------ |
| Normal operation             | 29 Sep 2026, 00:00               | 28 days of ordinary readings; no incident                    |
| Detectable overnight anomaly | 30 Sep 2026, 00:00               | Hostel B's 29 September anomaly; an Open incident is created |
| Investigation                | 30 Sep 2026, 12:00               | Further completed readings; an investigation event and note  |
| Repair recorded              | 1 Oct 2026, 12:00                | A simulated repair event; verification is Awaiting data      |
| Post-repair monitoring       | 5 Oct 2026, 06:00                | Complete 2–4 October overnight comparison; measured outcome  |

All scenario readings are **simulated**, using seed 42 for the original 29-day sample and seed 91 for its extension. Hostel B's increase continues before the simulated repair; post-repair overnight readings are generated around 32 L/hour, below its earlier roughly 54 L/hour baseline. This is a constructed example, not evidence from a real repair. The complete scenario has 2,466 readings across three buildings, but responses expose only readings completed by the current stage cutoff. Explicit replay cutoffs cannot jump past the unlocked stage.

**Reset replay only** returns the guided scenario to normal operation and removes its incidents/events; it does not change uploads or the quick sample. **View saved uploads** returns to your data. Reloading or resuming does not advance a stage or create incidents. The advance endpoint includes an expected-stage value, so retrying the same advance request cannot advance twice. You may also record incident actions manually during the replay; advancing will not repeat an already recorded transition.

## Project layout

- `src/`: responsive dashboard, upload/error/loading states, building selection, SVG chart, accessible hourly table, and explanations.
- `backend/main.py`: upload, workspace/cutoff, incident, replay, and example HTTP routes.
- `backend/storage.py`: storage/transaction protocols and the local SQLite adapter. SQL is confined here (apart from a test-only database reset fixture).
- `backend/workflow.py`: incident state transitions, episode deduplication, historical event projection, and repair comparison.
- `backend/replay.py`: deterministic guided scenario and stage orchestration using the same detector and incident functions as uploaded data.
- `src/Workflow.tsx`: cutoff/replay controls, incident details, notes, event history, and repair evidence; the existing chart is unchanged.
- `backend/detector.py`: validation and historical comparison, with no ML dependencies.
- `backend/demo.py`, `examples/`: deterministic sample generator and CSVs.
- `backend/tests/`: detector, timezone, validation, API, persistence, conflict, cutoff, recurrence, transition, comparison, and replay-isolation tests.
- `tests/app.spec.ts`: real-browser upload/demo, building selection, downloads, errors/retry, the complete persisted incident workflow and replay, mobile layout, keyboard entry, and automated WCAG accessibility checks. Automated scans supplement manual layout review; they do not certify complete accessibility.

`npm run format` formats frontend source and project configuration. `npm run format:check` verifies formatting without modifying files.

## Local milestone limitations

This remains a single-supervisor, local app. It has no authentication, automatic monitoring, notifications, scheduled jobs, database migration framework, or production user authentication. Optional AWS deployment preparation is provided separately. Each request loads the local workspace into memory; it is intended for hackathon-sized datasets, not unlimited archives. The upload-size check applies after multipart parsing, so this is not an internet-facing hardened service. Keep development servers bound to loopback. Frontend fonts have system fallbacks. No annual projections, financial savings, or proven water-savings claims are made. No AWS resources have been deployed; see [AWS_DEPLOYMENT.md](../AWS_DEPLOYMENT.md) for the manual Amplify + SAM workflow, costs, and remaining cloud verification.

Framework setup references: [Vite guide](https://vite.dev/guide/) and [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/).

## Optional AWS preparation checks

Install `backend/requirements-aws-test.txt` to run the Moto-emulated DynamoDB/session tests and CloudFormation linter. Without these optional packages, the cloud test module is skipped; the original local dependencies and SQLite behavior are unchanged.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-aws-test.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe scripts\prepare_sam.py
.\.venv\Scripts\cfn-lint.exe infra\template.yaml
```

Browser checks use local ports 5174/8001 plus port 5175 for a hosted-mode frontend with an intercepted mock API. No AWS calls occur in those tests. Hosted builds use `VITE_API_BASE_URL` and `VITE_HOSTED_DEMO=true`; leave them unset for local development.
