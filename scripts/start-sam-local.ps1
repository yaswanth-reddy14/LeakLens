. "$PSScriptRoot\service-common.ps1"
Set-Location $projectRoot
if (!(Get-Command sam -ErrorAction SilentlyContinue)) { throw 'SAM CLI missing from Machine/User PATH.' }
if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop is required.' }
$engine = & docker info --format '{{.OSType}}' 2>$null
if ($LASTEXITCODE -ne 0 -or $engine -ne 'linux') { throw 'Start Docker Desktop with its Linux engine before continuing.' }
if (!(Test-Path '.aws-sam\build\BackendFunction\backend\lambda_handler.py')) { throw 'Run scripts/prepare_sam.py and sam build --template-file infra/template.yaml --use-container first.' }
Start-OwnedService 'sam' 3001
Write-Host 'SAM local API starting at http://127.0.0.1:3001; first container initialization can take a minute.'
Write-Host 'Only local container /tmp/leaklens-local/demo.sqlite3 is used. No production table or credentials.'
