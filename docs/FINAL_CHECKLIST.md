# Final submission checklist

## Technical preparation

See [VERIFICATION.md](VERIFICATION.md) for commands actually executed and results. A checked test is not field validation, cloud deployment, registration or eligibility confirmation.

- Local CSV → anomaly → investigation → repair → comparison workflow.
- Repeat uploads, conflict rejection, cutoff, missing evidence and replay reset boundaries.
- Real desktop/mobile screenshots and automated accessibility checks.
- Reproducible evaluation with separate tuning/evaluation scenarios and disclosed misses.
- SAM production template and separate local-only Lambda/API demonstration.
- Start/stop/reset scripts scoped to this repository's recorded processes.
- Writeup, narration, interview answers and manual deployment guide.

## Manual actions, in order

1. **Review eligibility and timeline first.** Check the actual build start against the official opening time; disclose existing work and ask if uncertain. Do not alter timestamps/history or imply work began later.
2. **Register/check in and complete student verification.** Review current age, enrollment, location and team requirements yourself. Resolve AWS Builder Center/SheerID requirements through the event flow; CLI login is separate.
3. **Ask the organizer:** “LeakLens uses SAM CLI to build its Linux Python Lambda package and run the real FastAPI/Mangum handler locally through an HTTP API, including persistence and a complete workflow smoke test. The production backend and Amplify frontend are deployed, with a verified simulated workflow. Does this local SAM integration satisfy the open-source route? Does my disclosed build timeline satisfy the new-work rule?” No message was sent on your behalf.
4. **Record/upload** the demo to YouTube, public/unlisted, under three minutes. Show SAM use in the video. Test signed-out access.
5. **Review the source repository.** Use [yaswanth-reddy14/LeakLens](https://github.com/yaswanth-reddy14/LeakLens) and verify signed-out public access. Keep local databases, credentials, caches and dependencies excluded. Preserve truthful history and credit tools. Git pushes do not deploy the manually hosted Amplify app.
6. **Fill links** in SUBMISSION.md and submit once through the event form before its current deadline. Recheck additional fields and keep the receipt. Never insert a fake hosted URL.

## Official sources reviewed

Reviewed 8 October 2026. The [event overview](https://www.wemakedevs.org/aws/env) lists SAM CLI under its local open-source options. That supports asking about the integration; it is not an individual eligibility decision.

The [full rules](https://www.wemakedevs.org/aws/rules), updated 16 September 2026, require new work within the event, AI-tool disclosure, a public repository, short writeup and a YouTube demo under three minutes showing AWS use. They exclude projects begun before the event, even if rewritten. Read the complete current rules and form yourself. Registration, student status, actual work timeline, final links and submission have not been verified here.
