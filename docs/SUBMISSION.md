# LeakLens — submission writeup

## Short description

LeakLens helps college-hostel maintenance supervisors investigate possible overnight water loss using hourly CSV readings, understandable alerts, a maintenance history, and evidence-based post-repair comparisons.

## Problem and intended user

A supervisor needs to decide which building to inspect and whether consumption changed afterward. A high reading alone cannot explain whether the cause is a running tap, tank overflow, occupancy change, or scheduled use. LeakLens connects the reading to a documented next action without claiming it can diagnose the cause.

## Solution and environmental relevance

Upload readings, choose a building, and inspect its latest eligible overnight period or a historical cutoff. The alert shows observed liters, the same building's historical baseline, the threshold and the sustained duration. Create an incident, record an investigation and a repair, then check matched post-repair observations against clean historical periods.

The environmental aim is to support earlier investigation of avoidable water loss and better follow-through on maintenance. No actual water saved, environmental-impact total, field deployment, user adoption or supervisor feedback has been measured. All demonstration data is explicitly simulated.

## What makes it distinctive

The project completes the path from detection to investigation to outcome evidence. Missing readings stay missing. A recorded repair does not become an automatic success claim. The replay uses the real detector and incident logic, advances an explicit cutoff, and keeps simulated state separate from uploaded data. Alerts describe possible water loss, not confirmed leaks.

## Technology and AWS integration

React, TypeScript and Vite provide the responsive accessible dashboard. Python FastAPI supplies CSV validation and workflow endpoints. A small Storage/Transaction interface supports SQLite locally and DynamoDB for the live hosted demo.

AWS SAM defines the HTTP API/Lambda infrastructure, builds the Linux Python 3.12 package, and runs the real Lambda entry point locally. The separate local-only SAM template uses isolated temporary SQLite with warm-container persistence; the production template still requires DynamoDB. A scripted local smoke test checks upload, incident transitions, repair comparison and reset boundaries. See [SAM_LOCAL.md](SAM_LOCAL.md) and [VERIFICATION.md](VERIFICATION.md) for exactly what was executed.

The hosted demo uses Amplify manual ZIP upload, HTTP API Gateway, Lambda, DynamoDB and CloudWatch. It includes restricted IAM, explicit CORS, throttling and 24-hour isolated bearer sessions. **Live demo: [https://demo.d2gicx0vj4suvu.amplifyapp.com](https://demo.d2gicx0vj4suvu.amplifyapp.com).** The frontend and backend are deployed in `ap-southeast-2` (Sydney). Real Chromium checks on 8 October 2026 passed the five-stage demo, CSV upload, incident lifecycle and reload persistence, repair comparison, independent sessions, isolated reset, exact-origin CORS, and desktop/mobile accessibility. No API mocks were used for these checks. Deployment used profile `leaklens`; the backend origin change set was inspected before execution. Amplify remains a manual artifact deployment, not automatic GitHub-to-Amplify deployment.

## Evaluation

On 100 labeled synthetic building-night scenarios, LeakLens records TP 20, FP 10, TN 40 and FN 30: precision 0.667, recall 0.400. A fixed 100 L/hour comparator, selected on 40 separate tuning scenarios, records TP 35, FP 25, TN 25 and FN 15. Its F1 is higher on this constructed set. LeakLens misses gradual small increases and interrupted evidence, and both methods can confuse legitimate overnight activity with loss. These are synthetic screening results, not real-world accuracy or a superiority claim. [EVALUATION.md](EVALUATION.md) contains the full protocol and generated evidence.

## Challenges and lessons

Atomic merging matters: a conflict must reject the entire upload, even across many readings. For a small hosted demo, a bounded compressed session snapshot with one conditional DynamoDB write preserves atomicity without transaction batching. This trades scale and write efficiency for simplicity. Per-visitor sessions prevent unrelated visitors from changing one another's records, but bearer tokens are not production authentication.

The first backend deployment hit an account concurrency-reservation limit; removing that reservation preserved the other controls. Change-set review also caught a stale API Gateway origin when reusing the previous processed SAM template. Resubmitting the built SAM template updated both origin checks. Live mobile accessibility testing found a scrollable chart that needed keyboard focus; the fix passed local regression tests and the live rerun.

## Limitations and next steps

Validate with consented real hostel data and maintenance ground truth; incorporate occupancy and scheduled-use context; evaluate slow changes without sacrificing explainability; add production authentication, operational monitoring and scalable storage only after validation. Current overnight heuristics are not calibrated probabilities. Estimated consumption reduction is an observational difference, not causal savings.

## Final fields — complete before submitting

- Participant name: **[YOUR NAME]**
- Track: **Heat and Water**
- Public repository: [yaswanth-reddy14/LeakLens](https://github.com/yaswanth-reddy14/LeakLens).
- YouTube demo, public/unlisted and under three minutes: **PENDING - [YOUR VIDEO URL]**
- Hosted URL: [https://demo.d2gicx0vj4suvu.amplifyapp.com](https://demo.d2gicx0vj4suvu.amplifyapp.com) - deployed and browser-verified.
- Optional blog URL: **[YOUR PUBLISHED URL, or omit]**
- AI disclosure: **OpenAI Codex assisted implementation, testing and documentation. Add any other tools actually used.**
- Build timeline: **[YOUR FACTUAL EVENT START/WORK TIMELINE]**. The rules exclude projects begun before the event; do not imply otherwise or alter history.
- Eligibility: **Unconfirmed**. Ask the organizer whether the documented SAM CLI integration qualifies under the open-source route, and resolve the build-timeline question. No prize or interview eligibility is claimed.
