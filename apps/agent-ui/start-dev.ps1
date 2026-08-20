param(
    [switch]$Install,
    [switch]$SkipOffline,
    [switch]$Production
)

$ErrorActionPreference = "Stop"
$AgentUiRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $AgentUiRoot "..\..")
$AgentRoot = Join-Path $AgentUiRoot "agent"
$WebRoot = Join-Path $AgentUiRoot "web"
$RunRoot = Join-Path $AgentUiRoot ".run"
$VenvPython = Join-Path $AgentRoot ".venv\Scripts\python.exe"
$OfflineEntryUrl = "http://127.0.0.1:8770/29_%E5%8F%82%E8%B5%9B%E5%AF%BC%E8%88%AA.html"
$env:COPILOTKIT_TELEMETRY_DISABLED = "true"

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

function Import-AgentEnvironment {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $allowedKeys = @(
        "AGENT_LLM_BASE_URL",
        "AGENT_LLM_API_KEY",
        "AGENT_LLM_MODEL"
    )
    foreach ($line in Get-Content -LiteralPath $Path) {
        $entry = $line.Trim()
        if (-not $entry -or $entry.StartsWith("#")) {
            continue
        }
        $parts = $entry.Split("=", 2)
        if ($parts.Count -ne 2 -or $parts[0].Trim() -notin $allowedKeys) {
            throw "Unsupported entry in $Path"
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not $value) {
            throw "$key cannot be empty in $Path"
        }
        if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
    Write-Host "[config] loaded agent/.env"
}

Import-AgentEnvironment (Join-Path $AgentRoot ".env")

# Some desktop hosts expose both Path and PATH. Windows PowerShell treats them
# as duplicate keys when Start-Process builds the child environment.
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
        [int]$Port
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
    Set-Content -Encoding ascii -Path (Join-Path $RunRoot "$Name.pid") -Value $process.Id
    Write-Host "[start] $Name pid=$($process.Id) port=$Port"
}

function Wait-Endpoint {
    param([string]$Name, [string]$Url)
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "[ready] $Name $Url"
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "$Name did not become ready: $Url. See $RunRoot"
}

if ($Install) {
    if (-not (Test-Path $VenvPython)) {
        & python -m venv (Join-Path $AgentRoot ".venv")
    }
    & $VenvPython -m pip install -e "$AgentRoot[test]"
    & npm --prefix $WebRoot install --legacy-peer-deps --no-audit --no-fund
}

if (-not (Test-Path $VenvPython)) {
    throw "Backend environment is missing. Run .\apps\agent-ui\start-dev.ps1 -Install first."
}
if (-not (Test-Path (Join-Path $WebRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run .\apps\agent-ui\start-dev.ps1 -Install first."
}

$WebScript = "dev"
if ($Production) {
    if (-not (Test-Path (Join-Path $WebRoot ".next\BUILD_ID"))) {
        & npm --prefix $WebRoot run build
    }
    $WebScript = "start"
}

if (-not $SkipOffline) {
    $SystemPython = (Get-Command python).Source
    Start-ManagedProcess "offline-8770" $SystemPython @(
        "tools/serve_output.py", "--host", "127.0.0.1", "--port", "8770", "--no-open"
    ) $ProjectRoot 8770
}

Start-ManagedProcess "agent-8123" $VenvPython @(
    "-m", "poetry_agent.main"
) $AgentRoot 8123

$Node = (Get-Command node).Source
$NextCli = "node_modules/next/dist/bin/next"
Start-ManagedProcess "web-3000" $Node @(
    $NextCli, $WebScript, "--hostname", "127.0.0.1", "--port", "3000"
) $WebRoot 3000

if (-not $SkipOffline) {
    Wait-Endpoint "offline" $OfflineEntryUrl
}
Wait-Endpoint "agent" "http://127.0.0.1:8123/health"
Wait-Endpoint "web" "http://127.0.0.1:3000/"

Write-Host ""
Write-Host "Agent UI: http://127.0.0.1:3000/"
Write-Host "Agent API: http://127.0.0.1:8123/docs"
if (-not $SkipOffline) {
    Write-Host "Offline exhibits: $OfflineEntryUrl"
}
