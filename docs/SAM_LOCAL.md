# Reproducible AWS SAM demonstration, without cloud login

This is **local Lambda/API emulation**, not AWS deployment. It uses the same FastAPI/Mangum handler and Linux Python 3.12 package as the prepared hosted backend. It exercises the AWS open-source SAM framework meaningfully without a cloud account or another login loop. Eligibility still requires organizer confirmation.

## Build

Prerequisites: the existing venv with `backend/requirements-aws-test.txt`, AWS SAM CLI, and Docker Desktop's Linux engine. Run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-sam.ps1
```

The script refreshes PATH from Machine/User values, preserves project entries, stages only backend Python/runtime manifests, runs `sam validate --lint`, then runs:

```powershell
sam build --template-file infra/template.yaml --use-container
```

It disables SAM telemetry, points AWS configuration and shared-credential discovery at nonexistent project-local paths, removes credential/profile environment settings in that child process and disables instance metadata lookup. No cached credential file is opened by the script, and no login, cloud API or resource deployment is required. Public image/dependency downloads still require internet access. Your other terminal's AWS configuration is unchanged.

The production template builds `BackendFunction` for Python 3.12/x86_64. Artifacts are in `.aws-sam/build/BackendFunction`; the generated production template is `.aws-sam/build/template.yaml`. Rebuild after backend changes. `infra/template.local.yaml` references those actual built artifacts rather than a separately reimplemented app.

## Run and test the local Lambda/API

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-sam-local.ps1
Invoke-RestMethod http://127.0.0.1:3001/api/health
.\.venv\Scripts\python.exe scripts/smoke_sam.py
```

First startup may take a minute while SAM fetches the public runtime image and initializes its container. Logs are `.tools/services/sam.out.log` and `.tools/services/sam.err.log`. Retry health once initialization finishes. Do not record the initial image download.

The start script executes `sam local start-api --template infra/template.local.yaml --host 127.0.0.1 --port 3001 --warm-containers EAGER --region ap-southeast-2`. The smoke test only targets this fixed loopback URL and checks real multipart upload, persistence across separate requests, normal replay, anomaly/Open incident, investigation, recorded repair/Awaiting data, completed comparison, and replay reset without deleting uploaded data. It can be repeated: the uploaded row is idempotent and only the local replay is reset.

## Optional: show the frontend using SAM locally

With SAM running, in another PowerShell terminal:

```powershell
$env:Path = "$PWD\.tools\node-v22.23.3-win-x64;$env:Path"
$env:VITE_HOSTED_DEMO = 'false'
$env:VITE_API_BASE_URL = ''
$env:LEAKLENS_API_TARGET = 'http://127.0.0.1:3001'
$env:LEAKLENS_VITE_CACHE = '.tools/vite-sam-local'
npm.cmd run dev -- --port 5181 --strictPort
```

Open http://127.0.0.1:5181 and click **Try simulated demo**. This optional browser port proxies to SAM; the main recording launcher at 5180 continues to use the normal Python server. Stop the optional Vite terminal with Ctrl+C. Do not show this local URL as a hosted deployment.

## Writable storage and isolation

The local template contains only a local function/API route and sets `LEAKLENS_STORAGE=sqlite`, `LEAKLENS_SAM_LOCAL_DEMO=true`, and `LEAKLENS_DB_PATH=/tmp/leaklens-local/demo.sqlite3`. SAM supplies `AWS_SAM_LOCAL=true`. Both local markers are required to permit SQLite inside a Lambda-shaped environment, and the path must stay under the isolated temporary directory. The production template has neither local opt-in nor SQLite configuration and still rejects SQLite in normal Lambda execution. No production DynamoDB table, hosted session or original local database is connected.

SAM's warm container keeps `/tmp` between requests, so the smoke test can investigate and compare across HTTP calls. **Data is disposable**: container replacement/restart can lose it. No host database volume is mounted and no production durability is implied. Use the regular local SQLite app for persistent desktop use; use DynamoDB for the prepared cloud deployment. This mode is a single-user loopback demonstration without hosted bearer sessions.

To stop only this project's recorded SAM launcher and its child processes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop-sam-local.ps1
```

It does not stop Docker Desktop or unrelated containers/processes. Starting a new SAM container provides a fresh temporary database. The in-app replay reset preserves uploads in the current container.

## What this verifies and does not

See [VERIFICATION.md](VERIFICATION.md) for actual execution results. A SAM build validates packaging in Linux; a local smoke test checks Lambda event translation, application behavior and local persistence. Neither proves AWS IAM enforcement, live API Gateway CORS, DynamoDB TTL delivery, CloudWatch ingestion, Amplify hosting or deployment success. Moto adapter tests also remain emulated checks. [AWS_DEPLOYMENT.md](../AWS_DEPLOYMENT.md) retains the exact hosting instructions for later use.

Official references: [SAM container builds](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-using-build.html), [SAM local start-api](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-command-reference-sam-local-start-api.html), [SAM CLI source](https://github.com/aws/aws-sam-cli).
