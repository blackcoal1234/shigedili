$ErrorActionPreference = "Continue"
$AgentUiRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $AgentUiRoot ".run"

if (-not (Test-Path $RunRoot)) {
    Write-Host "No managed processes found."
    exit 0
}

Get-ChildItem -Path $RunRoot -Filter "*.pid" | ForEach-Object {
    $processId = [int](Get-Content $_.FullName)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        Write-Host "[stop] $($_.BaseName) pid=$processId"
    }
    Remove-Item $_.FullName -Force
}
