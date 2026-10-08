param([ValidateSet('backend', 'frontend', 'sam')][string]$Service)
. "$PSScriptRoot\service-common.ps1"
Set-Location $projectRoot
if ($Service -eq 'backend') {
    $env:LEAKLENS_STORAGE = 'sqlite'
    $env:LEAKLENS_DB_PATH = Join-Path $projectRoot 'data\recording.sqlite3'
    Remove-Item Env:AWS_LAMBDA_FUNCTION_NAME -ErrorAction SilentlyContinue
    & '.\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
} elseif ($Service -eq 'frontend') {
    $env:VITE_HOSTED_DEMO = 'false'
    $env:VITE_API_BASE_URL = ''
    $env:LEAKLENS_API_TARGET = 'http://127.0.0.1:8010'
    $env:LEAKLENS_VITE_CACHE = '.tools/vite-recording'
    & node (Join-Path $projectRoot 'node_modules\vite\bin\vite.js') preview --host 127.0.0.1 --port 5180 --strictPort --outDir .tools/demo-dist
} else {
    # Prevent all credential/config discovery for this entirely local process.
    $env:AWS_CONFIG_FILE = Join-Path $serviceDir 'no-aws-config'
    $env:AWS_SHARED_CREDENTIALS_FILE = Join-Path $serviceDir 'no-aws-credentials'
    $env:AWS_EC2_METADATA_DISABLED = 'true'
    $env:SAM_CLI_TELEMETRY = '0'
    foreach ($key in @('AWS_PROFILE','AWS_DEFAULT_PROFILE','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_WEB_IDENTITY_TOKEN_FILE','AWS_ROLE_ARN','AWS_CONTAINER_CREDENTIALS_RELATIVE_URI','AWS_CONTAINER_CREDENTIALS_FULL_URI')) {
        Remove-Item "Env:$key" -ErrorAction SilentlyContinue
    }
    & sam local start-api --template infra/template.local.yaml --host 127.0.0.1 --port 3001 --warm-containers EAGER --region ap-southeast-2
}
exit $LASTEXITCODE
