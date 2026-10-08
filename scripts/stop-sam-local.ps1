. "$PSScriptRoot\service-common.ps1"
Stop-OwnedService 'sam'
# Windows process termination may leave a warm Docker container. Stop only IDs
# emitted by this launcher's log AND bound to this exact project's built code.
$logFile = Join-Path $serviceDir 'sam.err.log'
$expectedSource = '/' + $projectRoot.Substring(0, 1).ToLower() + '/' + $projectRoot.Substring(3).Replace('\', '/') + '/.aws-sam/build/BackendFunction'
if ((Test-Path $logFile) -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    $content = Get-Content -LiteralPath $logFile -Raw
    foreach ($match in [regex]::Matches($content, 'SAM_CONTAINER_ID: ([a-f0-9]{64})')) {
        $containerId = $match.Groups[1].Value
        $existing = & docker ps -a --no-trunc -q --filter "id=$containerId"
        if (!$existing) { continue }
        $mountJson = & docker inspect --format '{{json .Mounts}}' $containerId 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $mounts = $mountJson | ConvertFrom-Json
        if (@($mounts | Where-Object { $_.Source -eq $expectedSource -and $_.Destination -eq '/var/task' -and !$_.RW }).Count -eq 1) {
            & docker stop --time 5 $containerId | Out-Null
            if ($LASTEXITCODE -eq 0) { & docker rm $containerId | Out-Null; Write-Host "Removed this project's temporary SAM container." }
        } else { Write-Warning 'Container mount ownership could not be verified; left untouched.' }
    }
}
