# Recording checklist

## Prepare

1. Close account/credential browser tabs and notifications. Use only simulated readings.
2. Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-demo.ps1 -ResetDemo` from the repository. Open http://127.0.0.1:5180 in a fresh browser tab.
3. Click **Try simulated demo**. Confirm **Stage 1 of 5: Normal operation**. The command resets only the recording database's replay; uploads and the original local database are untouched.
4. Keep docs/EVALUATION.md, infra/template.yaml and the SAM local test output ready. Use a rendered Markdown preview for the evaluation table.
5. Run [SAM_LOCAL.md](SAM_LOCAL.md)'s commands before recording. Wait for health, then run the smoke test. Initial build/image pulls can be slow; they do not belong in the recording.
6. Use 1440×1080 or 1440×900 desktop capture. Verify text legibility and microphone sound. A real 390-pixel mobile capture is in screenshots/mobile-anomaly.png; optionally show it without claiming another device test.
7. Rehearse [DEMO_SCRIPT.md](DEMO_SCRIPT.md) with a timer. Aim at 2:45, leaving a buffer under three minutes.

## Record

- Show the actual product in the opening seconds, then anomaly explanation, incident/note, recorded repair, Awaiting data and completed comparison.
- Show the evaluation's misses and the actual SAM integration.
- Keep simulation and estimated-reduction language explicit.
- Stop before 3:00. Play back the entire video before uploading.

## Reset and fallbacks

- In the app: **Reset replay only**. It leaves uploads and the quick sample intact.
- Terminal: `.\.venv\Scripts\python.exe scripts/reset_demo.py --stage 0`, then click **Try simulated demo**. Avoid applying a previously saved future cutoff after resetting.
- Rehearse a stage with `--stage 1` (anomaly), `--stage 3` (repair awaiting evidence), or `--stage 4` (comparison). Record the full progression for the final take.
- A busy port is not permission to kill another program. The launch script stops with an error. Close its owner yourself or use `stop-demo.ps1` for services owned by these scripts.
- Logs are in `.tools/services/`. The launcher uses the existing venv and portable Node if present. Install dependencies only if missing.
- If SAM is unavailable, the ordinary SQLite demo still works. Show only verified SAM build/test evidence; do not claim the current container is running. Hosting remains unverified.
- Internet is needed for first dependency/image downloads, not for the seeded app. External font loading was removed for reliable offline recording.
- Stop recording services with `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop-demo.ps1`. Stop SAM separately with `scripts/stop-sam-local.ps1`.

## After recording

Upload to YouTube as public or unlisted; verify signed-out access and duration. Fill SUBMISSION.md's real links, review FINAL_CHECKLIST.md, then push and submit yourself. No video has been generated or uploaded by this preparation.
