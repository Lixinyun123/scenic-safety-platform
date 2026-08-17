param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"

# Some launch environments expose both `Path` and `PATH`. PowerShell's
# Start-Process treats that as a duplicate dictionary key and refuses to
# create pythonw.exe, leaving port 8090 unavailable. Keep one canonical key.
$processEnvironment = [Environment]::GetEnvironmentVariables("Process")
$canonicalPath = if ($processEnvironment.Contains("Path")) {
    [string]$processEnvironment["Path"]
} else {
    [string]$processEnvironment["PATH"]
}
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $canonicalPath, "Process")

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "pythonw.exe was not found."
}

$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8090/" }
    exit 0
}

$stdoutLog = Join-Path $projectRoot ".base_station.stdout.log"
$stderrLog = Join-Path $projectRoot ".base_station.stderr.log"
$arguments = @(
    "-m", "ground_station.base_station_server",
    "--host", "127.0.0.1",
    "--port", "8090"
)

$process = Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
Start-Sleep -Milliseconds 900

if ($process.HasExited) {
    $detail = if (Test-Path -LiteralPath $stderrLog) { Get-Content -Raw -Encoding UTF8 $stderrLog } else { "Unknown error" }
    throw "Base station dashboard failed to start: $detail"
}

if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8090/" }
