param([switch]$NonInteractive)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$key = Join-Path $projectRoot ".codex_raspberrypi_ed25519"
$knownHosts = Join-Path $projectRoot ".codex_known_hosts"
$statusPath = Join-Path $projectRoot ".station_camera_setup_status.json"
$remote = "znfxq@192.168.1.123"

function Write-SetupStatus([bool]$ok, [string]$message, [string]$codec = "") {
    [ordered]@{
        ok = $ok
        message = $message
        codec = $codec
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

try {
    Write-Host "`nStation camera secure setup" -ForegroundColor Cyan
    Write-Host "The password is used only by MediaMTX on the Raspberry Pi.`n"

    if ($NonInteractive) {
        $cameraUser = $env:STATION_CAMERA_USER
        if ([string]::IsNullOrWhiteSpace($cameraUser)) { $cameraUser = "admin" }
        $plainPassword = $env:STATION_CAMERA_PASSWORD
        if ([string]::IsNullOrWhiteSpace($plainPassword)) { throw "Camera password was not supplied" }
    } else {
        $cameraUser = Read-Host "Camera username (press Enter for admin)"
        if ([string]::IsNullOrWhiteSpace($cameraUser)) { $cameraUser = "admin" }
        $securePassword = Read-Host "Camera password (hidden)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        try {
            $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
    $encodedUser = [Uri]::EscapeDataString($cameraUser)
    $encodedPassword = [Uri]::EscapeDataString($plainPassword)

    $sshArgs = @(
        "-i", $key,
        "-o", "UserKnownHostsFile=$knownHosts",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=5",
        $remote
    )

    $currentLines = & $ssh @sshArgs "cat /etc/mediamtx.yml"
    if ($LASTEXITCODE -ne 0) { throw "Unable to read MediaMTX configuration" }
    $current = ($currentLines -join "`n").TrimEnd()

    $stationMarker = "`n  station:"
    $markerIndex = $current.IndexOf($stationMarker, [StringComparison]::Ordinal)
    if ($markerIndex -ge 0) { $current = $current.Substring(0, $markerIndex).TrimEnd() }

    $stationBlock = @"

  station:
    source: rtsp://${encodedUser}:${encodedPassword}@192.168.1.50:554/Streaming/Channels/101
    sourceOnDemand: true
    rtspTransport: tcp
"@
    $candidate = $current + $stationBlock + "`n"

    $deployCommand = "sudo cp /etc/mediamtx.yml /etc/mediamtx.yml.bak-station; sudo tee /etc/mediamtx.yml >/dev/null; sudo systemctl restart mediamtx.service; sleep 2; if systemctl is-active --quiet mediamtx.service; then exit 0; else sudo cp /etc/mediamtx.yml.bak-station /etc/mediamtx.yml; sudo systemctl restart mediamtx.service; exit 1; fi"
    $candidate | & $ssh @sshArgs $deployCommand
    if ($LASTEXITCODE -ne 0) { throw "MediaMTX rejected the new configuration; rollback completed" }

    Start-Sleep -Seconds 2
    $probe = & $ssh @sshArgs "timeout 15 ffprobe -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 rtsp://127.0.0.1:8554/station"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($probe -join ""))) {
        throw "Camera authentication or RTSP stream failed"
    }

    $probeText = ($probe -join "").Trim()
    $codec = ($probeText -split ",")[0]
    Write-SetupStatus $true "Station camera stream connected" $codec
    Write-Host "`nSuccess: $probeText" -ForegroundColor Green
    if ($codec -notin @("h264", "avc")) {
        Write-Host "Current codec is $codec. Set the camera main stream to H.264 for browser playback." -ForegroundColor Yellow
    }
} catch {
    Write-SetupStatus $false $_.Exception.Message
    Write-Host "`nSetup failed: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($plainPassword) { $plainPassword = $null }
    Write-Host "`nYou may close this window." -ForegroundColor DarkGray
    if (-not $NonInteractive) { Read-Host "Press Enter to exit" }
}
