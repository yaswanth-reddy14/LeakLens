$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$serviceDir = Join-Path $projectRoot '.tools\services'
New-Item -ItemType Directory -Path $serviceDir -Force | Out-Null
$pathParts = @($env:Path -split ';') + @([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') + @([Environment]::GetEnvironmentVariable('Path', 'User') -split ';')
$portableNode = Join-Path $projectRoot '.tools\node-v22.23.3-win-x64'
if (Test-Path (Join-Path $portableNode 'node.exe')) { $pathParts = @($portableNode) + $pathParts }
$env:Path = (($pathParts | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique) -join ';')

function Get-OwnedService($name) {
    $recordFile = Join-Path $serviceDir "$name.json"
    if (!(Test-Path $recordFile)) { return $null }
    $record = Get-Content -LiteralPath $recordFile -Raw | ConvertFrom-Json
    $process = Get-Process -Id $record.Id -ErrorAction SilentlyContinue
    if (!$process -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $record.StartTicks) { return $null }
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.Id)"
    if (!$info.CommandLine -or !$info.CommandLine.Contains((Join-Path $PSScriptRoot 'service-worker.ps1')) -or !$info.CommandLine.Contains($name)) {
        throw "Cannot verify ownership of $name; refusing to manage that process."
    }
    return $process
}

function Start-OwnedService($name, $port) {
    if (Get-OwnedService $name) { Write-Host "$name already running."; return }
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Port $port is occupied. No process was stopped. Choose another time or stop its owner yourself."
    }
    $worker = Join-Path $PSScriptRoot 'service-worker.ps1'
    $process = Start-Process powershell.exe -WindowStyle Hidden -WorkingDirectory $projectRoot -PassThru -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$worker`"", '-Service', $name) -RedirectStandardOutput (Join-Path $serviceDir "$name.out.log") -RedirectStandardError (Join-Path $serviceDir "$name.err.log")
    @{ Id = $process.Id; StartTicks = $process.StartTime.ToUniversalTime().Ticks.ToString() } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $serviceDir "$name.json")
}

function Stop-OwnedService($name) {
    $process = Get-OwnedService $name
    if (!$process) { Write-Host "$name is not running under these scripts."; return }
    # Snapshot only descendants of our verified launcher. Never kill by image name or port.
    $all = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.List[int]]::new()
    $ids.Add($process.Id)
    for ($i = 0; $i -lt $ids.Count; $i++) {
        foreach ($child in $all | Where-Object { $_.ParentProcessId -eq $ids[$i] }) { $ids.Add([int]$child.ProcessId) }
    }
    for ($i = $ids.Count - 1; $i -ge 0; $i--) {
        $current = Get-Process -Id $ids[$i] -ErrorAction SilentlyContinue
        $original = $all | Where-Object ProcessId -eq $ids[$i]
        if ($current -and $original -and [Math]::Abs(($current.StartTime - $original.CreationDate).TotalSeconds) -lt 1) {
            Stop-Process -Id $ids[$i] -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath (Join-Path $serviceDir "$name.json") -ErrorAction SilentlyContinue
    Write-Host "Stopped $name and its verified child processes."
}
