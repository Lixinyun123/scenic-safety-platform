$ErrorActionPreference = "Stop"

$ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$knownHosts = "C:\Users\yuantiangang\Documents\国赛无人机系统\.codex_known_hosts"
$publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINze8CA8qun+SQjXrMpffopYYgioGI2iHNtTm0suZEDa codex-raspberrypi-setup"
$remoteCommand = "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; grep -qxF '$publicKey' ~/.ssh/authorized_keys || printf '%s\n' '$publicKey' >> ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; echo KEY_INSTALLED"

Write-Host "正在连接树莓派 znfxq@10.87.229.113" -ForegroundColor Cyan
Write-Host "请输入树莓派密码；输入时不显示任何字符，这是正常的。" -ForegroundColor Yellow
& $ssh -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" "znfxq@10.87.229.113" $remoteCommand

if ($LASTEXITCODE -eq 0) {
    Write-Host "\n授权成功，可以关闭窗口。" -ForegroundColor Green
} else {
    Write-Host "\n授权失败，请检查密码后重试。" -ForegroundColor Red
}
Read-Host "按回车关闭窗口"
