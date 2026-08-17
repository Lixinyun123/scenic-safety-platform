$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $projectRoot ".ground_dashboard_config.ps1")

$dashboardRoot = Join-Path $projectRoot "raspberry_pi_vision"
$outputDirectory = Join-Path $dashboardRoot "ground_output"
$python = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) {
    throw "找不到 pythonw.exe：$pythonw"
}

$arguments = @(
    "-u", "dashboard_server.py",
    "--host", "127.0.0.1",
    "--port", "8080",
    "--output", $outputDirectory
)
$stdoutLog = Join-Path $projectRoot ".ground_dashboard.stdout.log"
$stderrLog = Join-Path $projectRoot ".ground_dashboard.stderr.log"
$process = Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $dashboardRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
Start-Sleep -Milliseconds 800
if ($process.HasExited) {
    $errorText = if (Test-Path $stderrLog) { Get-Content -Raw -Encoding UTF8 $stderrLog } else { "未知错误" }
    throw "地面端启动失败：$errorText"
}
Write-Host "地面端已在后台启动：http://127.0.0.1:8080/"
