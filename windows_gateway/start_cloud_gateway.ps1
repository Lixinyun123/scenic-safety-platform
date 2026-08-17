param([switch]$Check)

$ErrorActionPreference = "Stop"
$gatewayRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $gatewayRoot
$envFile = Join-Path $gatewayRoot "cloud-gateway.env"
$example = Join-Path $gatewayRoot "cloud-gateway.env.example"

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $example -Destination $envFile
    Write-Host "已生成配置文件：$envFile"
    Write-Host "请填写 CLOUD_STATION_PUBLISH_URL 和 CLOUD_DRONE_PUBLISH_URL。"
}

$arguments = @((Join-Path $gatewayRoot "cloud_gateway.py"), "--env", $envFile)
if ($Check) { $arguments += "--check" }

& python @arguments
exit $LASTEXITCODE
