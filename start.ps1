param(
    [int]$Port = 8765,
    [switch]$Foreground,
    [switch]$SkipBuild,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Web = Join-Path $Root "web"
$Logs = Join-Path $Root "logs"
$StateFile = Join-Path $Logs "service-$Port.json"
$Url = "http://127.0.0.1:$Port"

if ($Stop) {
    if (-not (Test-Path $StateFile)) {
        Write-Output "No managed Stock Monitor process recorded for port $Port."
        return
    }
    $State = Get-Content -Raw $StateFile | ConvertFrom-Json
    $Worker = Get-CimInstance Win32_Process -Filter "ProcessId = $($State.processId)"
    if ($Worker -and $Worker.CommandLine.Contains("backend.server:app") -and $Worker.CommandLine.Contains($Root)) {
        Stop-Process -Id $State.processId -ErrorAction Stop
        Write-Output "Stock Monitor stopped (PID $($State.processId))."
    }
    Remove-Item $StateFile
    return
}

try {
    $Health = Invoke-RestMethod "$Url/api/health" -TimeoutSec 2
}
catch {
    $Health = $null
}
if ($Health -and $Health.name -eq "Stock Monitor" -and $Health.monitorStartedAt) {
    Write-Output "Stock Monitor is already running: $Url"
    return
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is occupied. Use -Port with a free port, or stop the previous instance explicitly."
}

if (-not $SkipBuild) {
    Push-Location $Web
    try {
        if (-not (Test-Path "node_modules")) {
            npm install
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    }
    finally {
        Pop-Location
    }
}
if (-not (Test-Path (Join-Path $Web "dist\index.html"))) {
    throw "No web build found. Run start.ps1 without -SkipBuild."
}

py -3.11 -m pip install -r (Join-Path $Root "backend\requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }
$Python = (py -3.11 -c "import sys; print(sys.executable)").Trim()
if ($Foreground) {
    Push-Location $Root
    try {
        & $Python -m uvicorn backend.server:app --host 127.0.0.1 --port $Port --timeout-graceful-shutdown 8
    }
    finally {
        Pop-Location
    }
    return
}

New-Item -ItemType Directory -Force $Logs | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Stdout = Join-Path $Logs "stock-monitor-$Stamp.stdout.log"
$Stderr = Join-Path $Logs "stock-monitor-$Stamp.stderr.log"
$Arguments = "-m uvicorn backend.server:app --app-dir `"$Root`" --host 127.0.0.1 --port $Port --timeout-graceful-shutdown 8"
$Worker = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -PassThru
$State = @{ processId = $Worker.Id; port = $Port; stdout = $Stdout; stderr = $Stderr; startedAt = (Get-Date).ToUniversalTime().ToString("o") }
[IO.File]::WriteAllText($StateFile, ($State | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Write-Output "Stock Monitor launching in the background: $Url (PID $($Worker.Id))"
Write-Output "Logs: $Stderr"
Write-Output "Stop: .\start.ps1 -Stop -Port $Port"
