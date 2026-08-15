$ErrorActionPreference = "Stop"
$LabRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $LabRoot ".run\web-3011.pid"

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "[skip] Motion Lab has no recorded web process."
    exit 0
}

function Test-RecordedIdentity {
    param(
        $Process,
        [string]$StartedAtUtc,
        [string]$ExecutablePath,
        [string]$CommandLine
    )
    if (-not $Process) { return $false }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)"
    if (-not $processInfo) { return $false }
    $recordedStart = [DateTime]::Parse($StartedAtUtc).ToUniversalTime()
    $actualStart = $Process.StartTime.ToUniversalTime()
    return $Process.ProcessName -eq "node" -and
        [Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -lt 1 -and
        $ExecutablePath -eq [string]$processInfo.ExecutablePath -and
        $CommandLine -eq [string]$processInfo.CommandLine
}

function Test-ProcessDescendant {
    param([int]$ProcessId, [int]$AncestorId)
    $currentId = $ProcessId
    for ($depth = 0; $depth -lt 12; $depth++) {
        if ($currentId -eq $AncestorId) { return $true }
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $currentId"
        if (-not $processInfo) { return $false }
        $parentId = [int]$processInfo.ParentProcessId
        if ($parentId -le 0 -or $parentId -eq $currentId) { return $false }
        $currentId = $parentId
    }
    return $false
}

$record = try {
    Get-Content -LiteralPath $PidFile -Encoding utf8 -Raw | ConvertFrom-Json
}
catch {
    throw "Refusing to stop a process because the Motion Lab PID record is invalid."
}

$resolvedLabRoot = (Resolve-Path -LiteralPath $LabRoot).Path
if (
    [string]$record.Name -ne "web-3011" -or
    [int]$record.Port -ne 3011 -or
    [string]$record.WorkingDirectory -ne $resolvedLabRoot
) {
    throw "Refusing to stop a process because the PID record does not belong to this Motion Lab."
}

$recordedListener = Get-Process -Id ([int]$record.Id) -ErrorAction SilentlyContinue
$recordedListenerValid = Test-RecordedIdentity `
    $recordedListener `
    ([string]$record.StartedAtUtc) `
    ([string]$record.ExecutablePath) `
    ([string]$record.CommandLine)
$parent = Get-Process -Id ([int]$record.ParentId) -ErrorAction SilentlyContinue
$parentValid = Test-RecordedIdentity `
    $parent `
    ([string]$record.ParentStartedAtUtc) `
    ([string]$record.ParentExecutablePath) `
    ([string]$record.ParentCommandLine)

$listenerConnections = @(
    Get-NetTCPConnection -State Listen -LocalPort 3011 -ErrorAction SilentlyContinue |
        Sort-Object OwningProcess -Unique
)
$listenerProcesses = @()
foreach ($connection in $listenerConnections) {
    $listenerProcess = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    $matchesRecordedListener = $listenerProcess -and
        $listenerProcess.Id -eq [int]$record.Id -and
        $recordedListenerValid
    $isVerifiedDescendant = $listenerProcess -and
        $parentValid -and
        (Test-ProcessDescendant $listenerProcess.Id $parent.Id)
    if (-not $matchesRecordedListener -and -not $isVerifiedDescendant) {
        throw "Refusing to stop port 3011 because its current listener is not owned by this Motion Lab."
    }
    $listenerProcesses += $listenerProcess
}

foreach ($listenerProcess in $listenerProcesses) {
    Stop-Process -Id $listenerProcess.Id -ErrorAction SilentlyContinue
    Write-Host "[stop] Motion Lab listener pid=$($listenerProcess.Id)"
}

if (
    $recordedListenerValid -and
    -not ($listenerProcesses | Where-Object { $_.Id -eq $recordedListener.Id })
) {
    Stop-Process -Id $recordedListener.Id -ErrorAction SilentlyContinue
}
if (
    $parentValid -and
    -not ($listenerProcesses | Where-Object { $_.Id -eq $parent.Id })
) {
    Stop-Process -Id $parent.Id -ErrorAction SilentlyContinue
}
if ($listenerProcesses.Count -eq 0 -and -not $recordedListenerValid -and -not $parentValid) {
    Write-Host "[skip] Recorded Motion Lab processes are no longer running."
}

Remove-Item -LiteralPath $PidFile -Force
Write-Host "Shared backend on 8123 was left untouched."
