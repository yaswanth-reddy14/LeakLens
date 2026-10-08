# LeakLens AWS deployment (manual Amplify upload)

This repository supports a small **temporary shared demo**. On 8 October 2026, the authorized corrected backend deployment reached `CREATE_COMPLETE` in `ap-southeast-2`; its live `/api/health` returned HTTP 200 with `{"status":"ok"}`. The frontend is now hosted at [https://demo.d2gicx0vj4suvu.amplifyapp.com](https://demo.d2gicx0vj4suvu.amplifyapp.com); the real hosted workflow passed browser verification on the same date. The Windows deployment commands below create billable AWS resources. No GitHub repository, push, Amplify CLI, AWS credentials in source, or secret values in chat are required.

## Current live deployment

- Frontend: [https://demo.d2gicx0vj4suvu.amplifyapp.com](https://demo.d2gicx0vj4suvu.amplifyapp.com)
- Amplify app: `d2gicx0vj4suvu`, name `leaklens-demo`, branch `demo`, platform `WEB`; no Git repository or automatic builds.
- Backend: `leaklens-demo`, profile `leaklens`, region `ap-southeast-2`, state `UPDATE_COMPLETE`.
- API base: `https://p31t0ua4hk.execute-api.ap-southeast-2.amazonaws.com`.
- Current `FrontendOrigin`: `https://demo.d2gicx0vj4suvu.amplifyapp.com`. Preserve this value on later backend deployments; the placeholder below is only historical/initial-deployment guidance.
- Latest Amplify publication: job `2`, `SUCCEED`, including the keyboard-accessible chart.

The app uses the root page and hash anchors, not pathname routing. No SPA rewrite is needed. Existing asset URLs are served directly. Hosting is billable; budget setup has not been verified.

## Architecture and readiness decisions

| Local assumption                                    | Hosted implementation                                                                                                   |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| SQLite file under `data/`                           | `LEAKLENS_STORAGE=dynamodb` selects `DynamoDBStorage`; SQLite remains the local default                                 |
| Long-running Uvicorn process                        | `backend.lambda_handler.handler` wraps FastAPI with Mangum for HTTP API payload v2; no server loop or background worker |
| Local persistent disk                               | Hosted requests never use SQLite; only transient multipart buffers may use Lambda's temporary disk                      |
| Shared local workspace                              | Server-issued bearer session isolates uploads, quick demo, replay, incidents, notes, and events                         |
| Relative `/api` and Vite proxy                      | `VITE_API_BASE_URL` is the HTTPS API **origin**, without `/api`; `VITE_HOSTED_DEMO=true` enables sessions               |
| Large local uploads                                 | Hosted limits below fit HTTP API/Lambda payload and bounded storage constraints                                         |
| SQLite transaction and unique active-incident index | Strongly consistent snapshot read plus conditional version-checked atomic replacement                                   |

The Lambda has no dependency on a particular warm process. DynamoDB is the persistence source. The session token and view preference survive reloads in the same browser tab through `sessionStorage`. The original local behavior still uses SQLite and local browser preferences. Existing detector, incident, and verification domain functions run unchanged except that recurrence search now considers observed nights instead of iterating potentially enormous empty calendar ranges.

## Atomic DynamoDB design and hard bounds

For this hackathon, a whole session is **one DynamoDB item** with `pk`, `revision`, `expires_at`, and a compressed JSON `payload`. The JSON contains separately named `uploads`, `demo`, and `replay` scopes plus replay metadata. No token is stored: `pk` contains a SHA-256 digest of the token. Readings, incidents, and maintenance events use the existing storage/transaction protocol.

Every operation loads that item with `GetItem(ConsistentRead=True)`. Mutations work on a private in-memory copy. The only commit is one `PutItem` conditioned on the original revision and an unexpired session. Any validation, conflict, capacity, or conditional-write failure commits **none** of the changes. An identical repeat upload produces no write. Concurrent requests cannot silently overwrite each other: the losing writer receives HTTP 409 and must refresh before retrying. An uncertain transport failure may have committed; refresh before retrying. Incident deduplication and replay expected-stage logic make those operation retries safe; note creation is not automatically retried.

This chooses the **bounded atomic operation** option, not staged/batched activation. It does not split an upload across DynamoDB transactions. DynamoDB limits transactions to 100 items / 4 MiB and each item to 400 KiB; a single bounded item avoids both transaction batching and partial publication. All size checks happen before the write. [DynamoDB limits](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html)

| Hosted bound                                      | Value                                              |
| ------------------------------------------------- | -------------------------------------------------- |
| CSV file                                          | 512 KiB, at most 3,000 rows per upload             |
| Complete HTTP request including multipart framing | 600 KiB                                            |
| Session readings across all three scopes          | 12,000                                             |
| Distinct building identifiers per session         | 12                                                 |
| Maintenance events across scopes                  | 300                                                |
| Uncompressed UTF-8 session document               | 2 MiB                                              |
| Compressed binary payload                         | 256 KiB, leaving room under the 400 KiB item limit |

The **first bound reached wins**; 12,000 readings is not a guaranteed allowance for every document. Size failures return HTTP 413 with a useful explanation and leave stored data unchanged. Original example CSVs and the complete replay fit these limits, including when loaded together. All ordinary requests use keyed GetItem/PutItem, never a table Scan or an unbounded partition query. The Lambda role has no Scan permission.

This layout intentionally rewrites a bounded snapshot for each mutation. It is simple and atomic but not suitable for large archives, high write concurrency, analytics, or production accounts. Moving beyond these limits requires a redesigned adapter (for example immutable staged datasets plus conditional activation), not silently chopping uploads into batches. There is no SQLite-to-DynamoDB migration: upload the CSV again in the hosted session.

## Temporary session isolation and cleanup

`POST /api/sessions` returns a cryptographically random **256-bit** URL-safe token. All stored-data endpoints require `Authorization: Bearer <token>`; a client-chosen or unknown token is rejected. The frontend keeps it in per-tab `sessionStorage`, never a URL or shared `localStorage`, and never logs it. Public health and generic example CSV downloads do not need a token. The session response and API responses use `Cache-Control: no-store`.

Each session has a fixed **24-hour lifetime**. Reads and commits check expiry immediately; expired sessions are rejected even while the item remains in DynamoDB. DynamoDB TTL on `expires_at` eventually removes the **entire item**, including all nested readings and maintenance state, without an additional cleanup service. TTL is asynchronous and can take days, so storage can remain billable after access expires. [AWS TTL behavior](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)

Replay reset changes only `replay` inside the current session's conditional snapshot. It cannot reset another visitor, the current visitor's uploads, or the quick sample. Reloading neither advances replay nor creates another incident. **Start new hosted session** abandons the current tab credential and obtains a new empty session; it does not delete the old item immediately. Closing a tab or clearing browser storage may lose access before expiry. Duplicating a tab may copy its credential and therefore share the same session. A separate browser profile/incognito context gets a separate session.

This is **temporary demo isolation, not production authentication**. Anyone holding a token can access that session; there is no identity, password, recovery flow, revocation UI, or cross-device account. Same-origin XSS or an untrusted browser extension could steal the credential. Do not share tokens, export browser storage, record response bodies/headers, or enable SDK wire logging. CORS restricts browser origins, not non-browser clients. Session issuance is public and can be abused despite throttling: there is no guaranteed total-spend cap. Use simulated/non-sensitive readings for this hosted demo.

## Local submission fallback

If cloud authentication is unavailable, do not repeat browser login attempts. Use [the credential-isolated SAM local demonstration](docs/SAM_LOCAL.md). SAM container build has been executed successfully; see [the verification record](docs/VERIFICATION.md) for current results. A local build/invocation is not cloud deployment.

## 1. Prerequisites on Windows

Run from `C:\Users\DELL\Desktop\leaklens` (or your checkout). Install Node.js 22.12+, Python 3.11+, AWS CLI v2, AWS SAM CLI, and Docker Desktop with its **Linux engine running**. Enable the required Windows/WSL2 virtualization support for Docker. Use official installers: [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html). Reopen PowerShell after installing CLI tools.

```powershell
Set-Location C:\Users\DELL\Desktop\leaklens
# Only if using the portable Node already present in this workspace:
$env:Path = "$PWD\.tools\node-v22.23.3-win-x64;$env:Path"
node --version
python --version
aws --version
sam --version
docker version
```

`docker version` must show a **Server** section, not only the client. The Lambda build uses Linux Python 3.12 in a SAM container, avoiding Windows-native dependency wheels. [SAM container builds](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-using-build.html)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-aws-test.txt
npm.cmd ci
npx.cmd playwright install chromium
```

## 2. Configure AWS locally and a budget

**Current workspace status (8 October 2026):** a fresh read-only STS check succeeded for profile `leaklens`, with identity output suppressed. Its configured default region is **ap-southeast-2 (Sydney)**. Do not initiate another login while this profile works. Earlier examples used ap-south-1 (Mumbai); the commands, configuration example and build/local scripts now consistently use Sydney. Login/session region and resource deployment region are separate concepts; Sydney is an explicit deployment choice here, not an assumption that every login region must host resources. The corrected `leaklens-demo` backend is now deployed in Sydney; no resources were moved between regions.

For this already-authenticated workspace, set `$awsRegion = "ap-southeast-2"` and `$stackName = "leaklens-demo"`, then continue to build/validation. The SSO setup below is only an alternative for a new environment with an appropriate Identity Center configuration; it is not required for the current browser-authenticated profile.

Use a non-root AWS identity. Prefer an IAM Identity Center profile; enter your own organization's SSO details in the **local CLI prompts**, not in chat or files committed to this repository:

```powershell
aws configure sso --profile leaklens
aws sso login --profile leaklens
aws sts get-caller-identity --profile leaklens
$awsRegion = "ap-southeast-2"
$stackName = "leaklens-demo"
```

If your account has no Identity Center configuration, follow your account's approved local AWS CLI credential setup instead. Do not use root access keys. [SSO configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)

The deploying identity needs permission to provision CloudFormation, Lambda, HTTP API Gateway, DynamoDB, CloudWatch Logs, the template's IAM role, and the SAM artifact S3 bucket, plus Amplify management for the manual frontend. The **runtime** role is much narrower: GetItem/PutItem on one table and CreateLogStream/PutLogEvents on its own log group. It has no deployment, Scan, S3, IAM, table deletion, or cross-table permissions. The function uses shared account concurrency with no dedicated per-function concurrency cap. The explicit reservation was removed after AWS rejected it because it would reduce unreserved account concurrency below the account minimum. Do not set reserved concurrency to zero: that disables execution. API throttling and restricted runtime permissions remain unchanged.

Before deployment, open **Billing and Cost Management → Budgets → Create budget → Cost budget**, choose a monthly amount you are comfortable spending (for example USD 5), and configure actual-spend email alerts at 50%, 80%, and 100%, plus a forecast alert at 100%. Use account-wide scope if you want other experimentation included. Confirm notification subscriptions when requested. Budget alerts are delayed notifications, **not an automatic spending stop**. [Create a cost budget](https://docs.aws.amazon.com/cost-management/latest/userguide/create-cost-budget.html), [budget notification limitations](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

Expected billable resources: Amplify hosting/storage/data transfer; API Gateway HTTP requests; Lambda invocations and execution duration; DynamoDB on-demand reads/writes and storage (whole-snapshot writes can cost more than per-row updates); CloudWatch log ingestion/storage; and the SAM deployment-artifact S3 bucket's storage/requests. Optional notification/budget actions, custom domains, or other account resources may add charges. Manual frontend builds run locally and do not need an Amplify build pipeline. No VPC/NAT gateway is created. Do not assume free-tier credits cover this deployment.

## 3. Check and build the SAM backend

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run format:check
.\.venv\Scripts\python.exe scripts\prepare_sam.py
.\.venv\Scripts\cfn-lint.exe infra\template.yaml
sam validate --template-file infra/template.yaml --lint --region $awsRegion --profile leaklens
sam build --template-file infra/template.yaml --use-container
```

`prepare_sam.py` recreates only `infra/.lambda-src` from the backend's top-level Python source and runtime manifests. It excludes `.venv`, SQLite databases, frontend assets, tests, credentials, and uploaded CSVs. Rerun it before every backend build. Do not point SAM CodeUri at the repository root. `.aws-sam` and generated sources are ignored. `infra/samconfig.example.toml` is an optional configuration reference; the explicit commands here do not depend on copying it.

Cloud-oriented tests use **Moto emulation and synthetic HTTP API events**, not AWS. Browser hosted-mode checks intercept a mock HTTPS API. The ordinary six browser tests still use real local FastAPI/SQLite. Passing these checks does not verify IAM enforcement, actual API Gateway CORS, Lambda Linux execution, service quotas, CloudWatch delivery, TTL cleanup, or real AWS persistence.

## 4. Deploy the backend (this creates AWS resources)

### Recovering the initial concurrency failure

The first `leaklens-demo` creation failed at `BackendFunction`: reserving five executions would reduce the account's unreserved concurrency below its minimum of 10. The source template now omits `ReservedConcurrentExecutions` entirely. Lambda shares the account concurrency pool; there is no dedicated function concurrency cap. Zero is not a substitute because it disables execution. API throttles, runtime IAM, timeouts and log retention are preserved.

For a failed **initial** creation, inspect CloudFormation events and resources, wait for `ROLLBACK_COMPLETE`, and delete only that failed stack before retrying. Use CloudFormation stack deletion, not a broad SAM cleanup: preserve retained resources and the shared SAM artifact bucket. Other stack states require diagnosis before deletion. Rebuild from the corrected source and inspect the generated change set before execution.

If Windows reports a locked `.aws-sam/build` file, stop this project's script-owned SAM local service with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop-sam-local.ps1`, then rerun `scripts/build-sam.ps1`. The ordinary local app services are separate.

Current backend deployment command, preserving the live Amplify origin (inspect any new change set before accepting):

```powershell
sam deploy --template-file .aws-sam/build/template.yaml --stack-name leaklens-demo --region ap-southeast-2 --profile leaklens --resolve-s3 --capabilities CAPABILITY_IAM --parameter-overrides "FrontendOrigin=https://demo.d2gicx0vj4suvu.amplifyapp.com" --confirm-changeset
```

The template has exactly one required parameter: `FrontendOrigin`. This explicit non-serving placeholder permits the first backend deployment before Amplify assigns an origin. The real HTTPS frontend origin remains the only application configuration value needed afterward; redeploy with that exact origin before using the hosted UI. No secret, account ID, table name or function name needs to be pasted into the template. An STS identity check alone does not validate deployment permissions or service quotas.

For a brand-new deployment before Amplify has assigned a URL, `https://example.invalid` can be used temporarily. For this live deployment, keep the actual origin shown below. Health can also be checked from PowerShell without an Origin header.

```powershell
sam deploy --template-file .aws-sam/build/template.yaml --stack-name $stackName --region $awsRegion --profile leaklens --resolve-s3 --capabilities CAPABILITY_IAM --parameter-overrides "FrontendOrigin=https://demo.d2gicx0vj4suvu.amplifyapp.com" --confirm-changeset
```

Review and accept the CloudFormation change set locally. Settings in the template: Python 3.12, 512 MB Lambda memory, 20-second function timeout, 22-second API integration timeout, shared account concurrency without a dedicated per-function cap, general API throttle 5 requests/second with burst 10, session creation 1 request/second with burst 2, and seven-day retention for both function and API access logs. Throttling is best-effort protection, not a strict billing cap.

```powershell
$stackOutputs = (aws cloudformation describe-stacks --stack-name $stackName --region $awsRegion --profile leaklens --output json | ConvertFrom-Json).Stacks[0].Outputs
$apiBase = ($stackOutputs | Where-Object OutputKey -eq "ApiUrl").OutputValue
$functionName = ($stackOutputs | Where-Object OutputKey -eq "FunctionName").OutputValue
$functionLogGroup = ($stackOutputs | Where-Object OutputKey -eq "FunctionLogGroup").OutputValue
Invoke-RestMethod -Uri "$apiBase/api/health"
```

Expected health response: `status = ok`. It reveals no tokens, account details, environment values, or table contents. This is a liveness check; the session/workflow checks below establish storage access.

## 5. Build and manually upload the frontend

```powershell
$apiBase = "https://p31t0ua4hk.execute-api.ap-southeast-2.amazonaws.com"
$env:VITE_API_BASE_URL = $apiBase
$env:VITE_HOSTED_DEMO = "true"
npm.cmd run build
Compress-Archive -Path .\dist\* -DestinationPath .\leaklens-frontend.zip -Force
```

Both Vite settings are public build-time configuration, not secrets. `.env.production.example` documents the same settings if you prefer a local ignored `.env.production` file. The API URL must be the output origin, with **no `/api` suffix**, path, query, or credentials. Changing it requires rebuilding and re-uploading the frontend. Do not put AWS credentials or bearer tokens in `VITE_*` values.

In AWS Amplify console, choose **Create new app → Deploy without Git → Next**. Name it `leaklens-demo`, choose a branch name such as `demo`, select **Drag and drop**, upload `leaklens-frontend.zip`, and choose **Save and deploy**. The ZIP must contain `index.html` at its root, not an enclosing `dist` directory. Record the assigned HTTPS URL and Amplify app ID locally. Do not connect a Git provider. [Official manual-upload instructions](https://docs.aws.amazon.com/amplify/latest/userguide/manual-deploys.html)

For a new app, API calls will be denied until the final frontend origin is configured in the next step. The current live app already has the correct origin. Subsequent frontend changes are another local build and manual ZIP upload to the same app/branch.

### Repeat a manual artifact upload using AWS CLI

Reuse the existing app/branch; inspect `aws amplify list-apps --profile leaklens --region ap-southeast-2` before creating any new app. After the hosted build and ZIP step above, the following uploads to the existing demo. The presigned upload URL stays in a variable; do not enable PowerShell tracing/transcripts or AWS debug output.

```powershell
$amplifyAppId = "d2gicx0vj4suvu"
$branchName = "demo"
$deploymentJson = aws amplify create-deployment --app-id $amplifyAppId --branch-name $branchName --profile leaklens --region ap-southeast-2 --output json
if ($LASTEXITCODE -ne 0) { throw "Create deployment failed" }
$deployment = $deploymentJson | ConvertFrom-Json
try {
    $null = Invoke-WebRequest -UseBasicParsing -Method Put -Uri $deployment.zipUploadUrl -InFile .\leaklens-frontend.zip -ContentType application/zip -TimeoutSec 120 -ErrorAction Stop
} catch {
    throw "Artifact upload failed; presigned URL withheld."
}
$jobId = $deployment.jobId
Remove-Variable deployment,deploymentJson
aws amplify start-deployment --app-id $amplifyAppId --branch-name $branchName --job-id $jobId --profile leaklens --region ap-southeast-2 --query 'jobSummary.{id:jobId,status:status}' --output json
if ($LASTEXITCODE -ne 0) { throw "Start deployment failed" }
aws amplify get-job --app-id $amplifyAppId --branch-name $branchName --job-id $jobId --profile leaklens --region ap-southeast-2 --query 'job.summary.{id:jobId,status:status}' --output json
```

Poll the final command until `SUCCEED`; investigate `FAILED` before claiming publication. Do not print the full CreateDeployment/GetJob responses: they can include signed upload or artifact/log URLs. [AWS manual deployment API](https://docs.aws.amazon.com/cli/latest/reference/amplify/create-deployment.html).

## 6. Set the exact final frontend origin

Use the assigned Amplify URL (scheme + host only; no trailing slash). For this existing deployment:

```powershell
$frontendOrigin = "https://demo.d2gicx0vj4suvu.amplifyapp.com"
sam deploy --template-file .aws-sam/build/template.yaml --stack-name $stackName --region $awsRegion --profile leaklens --resolve-s3 --capabilities CAPABILITY_IAM --parameter-overrides "FrontendOrigin=$frontendOrigin" --confirm-changeset --no-fail-on-empty-changeset
```

**Resubmit the built SAM template, as shown above.** Do not use CloudFormation `--use-previous-template` for this parameter change: in the observed change set it retained the old transformed API Gateway CORS origin while changing Lambda. That unexecuted change set was discarded. Submitting the built SAM template correctly produced only two non-replacing updates, to `BackendFunction` and `HttpApi`. Inspect property changes before execution. This updates both HTTP API CORS and backend origin checks. Only that exact HTTPS origin is allowed, with Authorization/Content-Type headers and GET/POST/OPTIONS. There is no wildcard or credentialed-cookie CORS. Use a separate deployment if you need a second frontend origin. If a custom domain is introduced later, update this parameter to its exact origin.

Check preflight from PowerShell and then reload Amplify (allow up to the configured 300-second preflight cache age after changing origins):

```powershell
$preflight = Invoke-WebRequest -UseBasicParsing -Method Options -Uri "$apiBase/api/workspace" -Headers @{ Origin = $frontendOrigin; "Access-Control-Request-Method" = "GET"; "Access-Control-Request-Headers" = "authorization" }
$preflight.Headers["Access-Control-Allow-Origin"]
```

## 7. Verify the hosted workflow and persistence

The automated live workflow below passed against AWS on 8 October 2026 (see [VERIFICATION.md](docs/VERIFICATION.md)). To repeat it with new disposable sessions:

```powershell
node scripts/verify-hosted.mjs https://demo.d2gicx0vj4suvu.amplifyapp.com
```

The script uses actual Chromium with two separate browser contexts, no API mocking, no trace/HAR capture, and no printed bearer tokens. It paces actions under the demo throttle and never retries mutations automatically. It verifies a deterministic 480-row upload, duplicate/conflict handling, investigation/repair notes, reload persistence, a 720 L expected versus 360 L observed comparison, five-stage replay, reset isolation, CORS rejection and desktop/mobile accessibility. Sanitized results/screenshots go to `.tools/hosted-verification/`.

Additional/manual checklist (expiry, physical TTL cleanup, CloudWatch delivery and forced Lambda recycle have **not** been verified):

1. Open Amplify in a normal browser window. Confirm a temporary private session starts and no errors appear. Do not export or share browser network headers/responses containing the bearer token.
2. Upload `examples/simulated-possible-water-loss.csv`. Confirm three buildings and Hostel B's alert. Upload the same file again and confirm the reading count is unchanged. Upload `simulated-normal.csv` and confirm a 409 conflict leaves the original dataset unchanged.
3. Create an incident from Hostel B's alert, repeat the action to check deduplication, save a note, start investigating, and record repair at the evaluation cutoff. It should say **Awaiting data**, not claim improvement without later readings. Reload and verify the incident and note remain.
4. Start guided replay. Advance through all five stages: normal → anomaly/Open → investigation → repair/Awaiting data → post-repair comparison. Reload at an intermediate stage; it must not advance or duplicate the incident. Confirm the final comparison's windows, baseline, coverage, and label.
5. Reset **replay only**, then return to saved uploads and confirm the uploaded incident is unchanged.
6. Open a separate incognito/browser profile. It must start empty with its own token. Load/reset its replay; the first visitor's uploads and incidents must remain untouched. Do not use a duplicated tab to test separate visitors because browsers may copy sessionStorage.
7. To demonstrate independence from a warm Lambda process, trigger a code refresh using the AWS Lambda console's deploy operation or the following update, then reload the **same tab**. All session data must remain until expiry:

```powershell
aws lambda update-function-configuration --function-name $functionName --description "LeakLens persistence verification" --region $awsRegion --profile leaklens
aws lambda wait function-updated --function-name $functionName --region $awsRegion --profile leaklens
```

8. Inspect CloudWatch in the console, or tail the function's logs. The application and access-log configuration intentionally omit request bodies, Authorization headers, and token values. Do not enable body/header tracing or SDK debug logging:

```powershell
aws logs tail $functionLogGroup --since 10m --region $awsRegion --profile leaklens
```

9. After 24 hours the old token must be denied even if TTL has not yet physically removed its item. Verify eventual TTL removal using the DynamoDB console after AWS's asynchronous cleanup. **Start new hosted session** creates an empty replacement, not an account recovery.

If any real check fails, record it as unverified and inspect the relevant service: 401 means missing/expired session; 403 usually means origin mismatch; 409 means data conflict or concurrent state change; 413 means a documented hosted bound; 429 means throttling; 503 indicates service/configuration failure. Do not work around CORS by allowing `*` or fix IAM errors by granting administrator access to the Lambda.

## 8. Cleanup after the hackathon

These commands intentionally delete hosted data/resources. Record the Amplify app ID from its console and use the exact stack/region you deployed:

```powershell
$amplifyAppId = "d2gicx0vj4suvu"
aws amplify delete-app --app-id $amplifyAppId --region $awsRegion --profile leaklens
sam delete --stack-name $stackName --region $awsRegion --profile leaklens
```

Follow SAM's local prompts for stack and deployment-artifact deletion. The stack uses **Delete** policies for the temporary session table; deletion removes session data immediately rather than waiting for TTL. The function, API, execution role, and both log groups are stack resources and are also removed. Confirm the CloudFormation deletion completes. Check S3 for any remaining SAM-managed artifact objects/bucket: remove only artifacts belonging to this demo, and do not delete a shared SAM bucket used by other stacks. Remove any separately created budget/notification/custom-domain resources if no longer wanted. Check Billing afterward for delayed usage and unrelated resources; deleting the app does not erase already incurred charges.

To return your shell to local frontend builds:

```powershell
Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:VITE_HOSTED_DEMO -ErrorAction SilentlyContinue
```

If you created `.env.production`, remove or edit that local configuration too. Local SQLite development and its database are unaffected by cloud deletion.

## Verification status of this preparation

Local/Moto adapter tests, original local browser checks, a mock-hosted browser session check, TypeScript/Vite builds, source staging, and local SAM-template linting can run without an AWS account. Linux Python 3.12 wheel resolution can check package availability but is not a Lambda invocation. **Amplify job 2 succeeded, the backend is UPDATE_COMPLETE, and the full real-browser workflow described above passed.** All four served frontend files matched local build SHA-256 hashes. The corrected mobile chart is keyboard-focusable; all seven local/mock browser tests and the final live accessibility checks passed. Remaining limits include comprehensive IAM denial testing, forced-process-recycle persistence, real-device/other-engine testing, CloudWatch delivery, 24-hour session expiry and physical TTL cleanup. These were not inferred from health or short-term persistence checks. Recovery, build and local test evidence are recorded in docs/VERIFICATION.md.

Pricing references for later deployment: [Lambda request/duration pricing](https://aws.amazon.com/lambda/pricing/), [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/), and [Amplify hosting pricing](https://aws.amazon.com/amplify/pricing/). Select Sydney and account-specific usage assumptions when estimating; no free deployment or fixed bill is promised.
