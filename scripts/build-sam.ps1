. "$PSScriptRoot\service-common.ps1"
Set-Location $projectRoot
if (!(Get-Command sam -ErrorAction SilentlyContinue)) { throw 'SAM CLI missing. Refresh/install it using AWS_DEPLOYMENT.md.' }
$env:AWS_CONFIG_FILE = Join-Path $serviceDir 'no-aws-config'
$env:AWS_SHARED_CREDENTIALS_FILE = Join-Path $serviceDir 'no-aws-credentials'
$env:AWS_EC2_METADATA_DISABLED = 'true'
$env:SAM_CLI_TELEMETRY = '0'
foreach ($key in @('AWS_PROFILE','AWS_DEFAULT_PROFILE','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_WEB_IDENTITY_TOKEN_FILE','AWS_ROLE_ARN','AWS_CONTAINER_CREDENTIALS_RELATIVE_URI','AWS_CONTAINER_CREDENTIALS_FULL_URI')) {
    Remove-Item "Env:$key" -ErrorAction SilentlyContinue
}
& '.\.venv\Scripts\python.exe' scripts/prepare_sam.py
if ($LASTEXITCODE -ne 0) { throw 'Source staging failed.' }
& sam validate --template-file infra/template.yaml --lint --region ap-southeast-2
if ($LASTEXITCODE -ne 0) { throw 'SAM validation failed.' }
& sam build --template-file infra/template.yaml --use-container
if ($LASTEXITCODE -ne 0) { throw 'SAM container build failed.' }
