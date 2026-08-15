param(
    [switch]$Production
)

$ErrorActionPreference = "Stop"
$LabRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $LabRoot "..\..")).Path
$AgentRoot = Join-Path $ProjectRoot "apps\agent-ui\agent"
$VenvPython = Join-Path $AgentRoot ".venv\Scripts\python.exe"
$RunRoot = Join-Path $LabRoot ".run"
$env:COPILOTKIT_TELEMETRY_DISABLED = "true"

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

# Codex desktop can expose both Path and PATH. Keep only the canonical entry so
# Start-Process can safely inherit the environment.
$InheritedPath = [Environment]::GetEnvironmentVariable("Path", "Process")
if (-not $InheritedPath) {
    $InheritedPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
}
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $InheritedPath, "Process")

function Test-ListeningPort {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(350) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [int]$Port,
        [bool]$RecordIdentity = $true
    )
    if (Test-ListeningPort $Port) {
        Write-Host "[skip] $Name already listens on $Port"
        return
    }

    $stdout = Join-Path $RunRoot "$Name.out.log"
    $stderr = Join-Path $RunRoot "$Name.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    try {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
        if (-not $processInfo) {
            throw "Unable to capture the spawned $Name process identity."
        }
        $process | Add-Member -NotePropertyName SpawnedExecutablePath -NotePropertyValue ([string]$processInfo.ExecutablePath)
        $process | Add-Member -NotePropertyName SpawnedCommandLine -NotePropertyValue ([string]$processInfo.CommandLine)
    }
    catch {
        $current = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
        if ($current) {
            $sameLifetime = [Math]::Abs((
                $current.StartTime.ToUniversalTime() - $process.StartTime.ToUniversalTime()
            ).TotalSeconds) -lt 1
            if ($sameLifetime) {
                Stop-Process -Id $current.Id -ErrorAction SilentlyContinue
            }
        }
        throw
    }
    if ($RecordIdentity) {
        $identity = [ordered]@{
            Id = $process.Id
            Name = $Name
            Port = $Port
            StartedAtUtc = $process.StartTime.ToUniversalTime().ToString("O")
            WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
        }
        $identity |
            ConvertTo-Json -Compress |
            Set-Content -Encoding utf8 -LiteralPath (Join-Path $RunRoot "$Name.pid")
    }
    Write-Host "[start] $Name pid=$($process.Id) port=$Port"
    return $process
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

function Test-ProcessIdentity {
    param($ExpectedIdentity)
    $current = Get-Process -Id $ExpectedIdentity.Id -ErrorAction SilentlyContinue
    if (-not $current) { return $false }
    $currentInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($ExpectedIdentity.Id)"
    if (-not $currentInfo) { return $false }
    $currentStartedAtUtc = $current.StartTime.ToUniversalTime().ToString("O")
    return (
        $currentStartedAtUtc -eq $ExpectedIdentity.StartedAtUtc -and
        [string]$currentInfo.ExecutablePath -eq $ExpectedIdentity.ExecutablePath -and
        [string]$currentInfo.CommandLine -eq $ExpectedIdentity.CommandLine
    )
}

function Stop-VerifiedDescendantListeners {
    param(
        [int]$Port,
        $SpawnedParentIdentity
    )
    if (-not $SpawnedParentIdentity -or -not (Test-ProcessIdentity $SpawnedParentIdentity)) {
        return
    }
    $connections = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Sort-Object OwningProcess -Unique
    )
    foreach ($connection in $connections) {
        if (-not (Test-ProcessDescendant $connection.OwningProcess $SpawnedParentIdentity.Id)) {
            continue
        }
        if (-not (Test-ProcessIdentity $SpawnedParentIdentity)) {
            return
        }
        $listener = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        if ($listener) {
            Stop-Process -Id $listener.Id -ErrorAction SilentlyContinue
        }
    }
}

function Record-ListeningProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$WorkingDirectory,
        $SpawnedParentIdentity
    )
    $listener = $null
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-ListeningPort $Port) {
            $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
                Select-Object -First 1
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $listener) {
        throw "The spawned $Name process did not create a listener on port $Port."
    }
    if (-not (Test-ProcessIdentity $SpawnedParentIdentity)) {
        throw "The Motion Lab parent process no longer matches the process started in this run."
    }
    if (-not (Test-ProcessDescendant $listener.OwningProcess $SpawnedParentIdentity.Id)) {
        throw "Port $Port is not owned by the Motion Lab process started in this run."
    }
    if (-not (Test-ProcessIdentity $SpawnedParentIdentity)) {
        throw "The Motion Lab parent process changed while validating its listener."
    }
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    if (
        -not $processInfo -or
        -not (Test-ProcessDescendant $process.Id $SpawnedParentIdentity.Id) -or
        -not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq $process.Id })
    ) {
        throw "The Motion Lab listener changed while its identity was being recorded."
    }
    $identity = [ordered]@{
        Id = $process.Id
        Name = $Name
        Port = $Port
        StartedAtUtc = $process.StartTime.ToUniversalTime().ToString("O")
        WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
        ExecutablePath = [string]$processInfo.ExecutablePath
        CommandLine = [string]$processInfo.CommandLine
        ParentId = $SpawnedParentIdentity.Id
        ParentStartedAtUtc = $SpawnedParentIdentity.StartedAtUtc
        ParentExecutablePath = $SpawnedParentIdentity.ExecutablePath
        ParentCommandLine = $SpawnedParentIdentity.CommandLine
    }
    $identity |
        ConvertTo-Json -Compress |
        Set-Content -Encoding utf8 -LiteralPath (Join-Path $RunRoot "$Name.pid")
    return $process
}

function Stop-ExactProcess {
    param($SpawnedProcess)
    if (-not $SpawnedProcess) { return }
    $current = Get-Process -Id $SpawnedProcess.Id -ErrorAction SilentlyContinue
    if (-not $current) { return }
    $currentStart = $current.StartTime.ToUniversalTime()
    $spawnedStart = $SpawnedProcess.StartTime.ToUniversalTime()
    $sameLifetime = [Math]::Abs(($currentStart - $spawnedStart).TotalSeconds) -lt 1
    if ($sameLifetime) {
        Stop-Process -Id $current.Id
    }
}

function Wait-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [string]$ExpectedText = ""
    )
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            $hasExpectedText = -not $ExpectedText -or $response.Content.Contains($ExpectedText)
            if ($response.StatusCode -eq 200 -and $hasExpectedText) {
                Write-Host "[ready] $Name $Url"
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    }
    throw "$Name did not become ready: $Url. See $RunRoot"
}

if (-not (Test-Path -LiteralPath (Join-Path $LabRoot "node_modules"))) {
    throw "Motion Lab dependencies are missing. Restore its node_modules junction first."
}

if (Test-ListeningPort 3011) {
    throw "Port 3011 is already in use. Stop the existing Motion Lab or free the port before starting a new instance."
}

if (-not (Test-ListeningPort 8123)) {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Backend is not running and its environment is missing. Run .\apps\agent-ui\start-dev.ps1 -Install first."
    }
    $null = Start-ManagedProcess "agent-8123" $VenvPython @(
        "-m", "poetry_agent.main"
    ) $AgentRoot 8123
}

$WebMode = "dev"
if ($Production) {
    & npm --prefix $LabRoot run build
    if ($LASTEXITCODE -ne 0) {
        throw "Motion Lab production build failed."
    }
    $WebMode = "start"
}

$Node = (Get-Command node).Source
$NextCli = Join-Path $LabRoot "node_modules\next\dist\bin\next"
$WebArguments = @($NextCli, $WebMode)
if ($WebMode -eq "dev") {
    $WebArguments += "--webpack"
}
$WebArguments += @("--hostname", "127.0.0.1", "--port", "3011")
$webParent = $null
$webParentIdentity = $null
$webListener = $null
try {
    $webParent = Start-ManagedProcess "web-3011" $Node $WebArguments $LabRoot 3011 $false
    $webParentIdentity = [pscustomobject]@{
        Id = $webParent.Id
        StartedAtUtc = $webParent.StartTime.ToUniversalTime().ToString("O")
        ExecutablePath = [string]$webParent.SpawnedExecutablePath
        CommandLine = [string]$webParent.SpawnedCommandLine
    }
    $webListener = Record-ListeningProcess "web-3011" 3011 $LabRoot $webParentIdentity
    Wait-Endpoint "agent" "http://127.0.0.1:8123/health" "poetry-agent-backend"
    Wait-Endpoint "motion-lab" "http://127.0.0.1:3011/" 'data-motion-lab-control="agent-ui-motion-lab"'
}
catch {
    Stop-VerifiedDescendantListeners 3011 $webParentIdentity
    Stop-ExactProcess $webListener
    if (-not $webListener -or $webListener.Id -ne $webParent.Id) {
        Stop-ExactProcess $webParent
    }
    $webPidFile = Join-Path $RunRoot "web-3011.pid"
    if (Test-Path -LiteralPath $webPidFile) {
        Remove-Item -LiteralPath $webPidFile -Force
    }
    throw
}

Write-Host ""
Write-Host "Motion Lab: http://127.0.0.1:3011/"
Write-Host "Original UI remains at: http://127.0.0.1:3000/"
Write-Host "Logs: $RunRoot"
