param([switch]$ResetDemo)
. "$PSScriptRoot\service-common.ps1"
Set-Location $projectRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { throw 'Missing .venv. Run python -m venv .venv, then install backend\requirements.txt.' }
& '.\.venv\Scripts\python.exe' -c 'import fastapi, uvicorn, multipart, tzdata'
if ($LASTEXITCODE -ne 0) { throw 'Install dependencies: .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt' }
if (!(Get-Command node -ErrorAction SilentlyContinue) -or !(Test-Path 'node_modules\vite\bin\vite.js')) { throw 'Node 22.12+ and npm ci are required. Portable project Node is supported automatically.' }
$nodeVersion = (& node --version).TrimStart('v').Split('.')
if ([int]$nodeVersion[0] -lt 22 -or ([int]$nodeVersion[0] -eq 22 -and [int]$nodeVersion[1] -lt 12)) { throw 'Node 22.12 or newer is required; use the project portable Node or update your local Node installation.' }
if (!(Get-OwnedService 'frontend')) {
    $env:VITE_HOSTED_DEMO = 'false'
    $env:VITE_API_BASE_URL = ''
    & npm.cmd run build -- --outDir .tools/demo-dist
    if ($LASTEXITCODE -ne 0) { throw 'Recording frontend build failed. See TypeScript/Vite output above.' }
}
if ($ResetDemo) {
    & '.\.venv\Scripts\python.exe' scripts/reset_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Demo reset failed.' }
}
Start-OwnedService 'backend' 8010
Start-OwnedService 'frontend' 5180
$ready = $false
for ($attempt = 0; $attempt -lt 45; $attempt++) {
    try {
        $null = Invoke-RestMethod 'http://127.0.0.1:8010/api/health' -TimeoutSec 2
        $null = Invoke-WebRequest 'http://127.0.0.1:5180' -UseBasicParsing -TimeoutSec 2
        $ready = $true; break
    } catch { Start-Sleep -Milliseconds 700 }
}
if (!$ready) { throw 'Services did not become ready. See .tools/services/*.err.log; use scripts/stop-demo.ps1 to stop only these services.' }
Write-Host 'LeakLens recording demo: http://127.0.0.1:5180'
Write-Host 'Click Try simulated demo. Data: data/recording.sqlite3. Original local workspace is untouched.'
