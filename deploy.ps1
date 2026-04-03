# Monitor Framework — Deploy to AWS Lightsail VPS
# Run from: C:\Users\user\monitor>
# Requires: SSH access to VPS (see CLAUDE.md setup section)

param(
    [string]$VpsHost = "18.139.210.59",
    [string]$VpsUser = "ubuntu",
    [string]$KeyPath = "C:\Users\user\PycharmProjects\CryptoStrategy\mcp_server\LightsailDefaultKey-ap-southeast-1.pem",
    [string]$RemoteDir = "/home/ubuntu/monitor"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Monitor Framework Deploy ===" -ForegroundColor cyan

# 1. Check SSH connectivity
Write-Host "[1/6] Testing SSH connectivity..." -ForegroundColor yellow
$sshTest = ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -i "$KeyPath" "${VpsUser}@${VpsHost}" "echo ok" 2>&1
if ($sshTest -notmatch "ok") {
    Write-Host "SSH FAILED: $sshTest" -ForegroundColor red
    Write-Host "Fix SSH access first: see CLAUDE.md §VPS Setup" -ForegroundColor red
    exit 1
}
Write-Host "  SSH OK" -ForegroundColor green

# 2. Create remote directory
Write-Host "[2/6] Creating remote directory..." -ForegroundColor yellow
ssh -o StrictHostKeyChecking=no -i "$KeyPath" "${VpsUser}@${VpsHost}" "mkdir -p $RemoteDir" 2>&1

# 3. Upload files via scp
Write-Host "[3/6] Uploading monitor/ directory..." -ForegroundColor yellow
scp -o StrictHostKeyChecking=no -i "$KeyPath" -r `
    "$PSScriptRoot\main.py" `
    "$PSScriptRoot\config.py" `
    "$PSScriptRoot\storage.py" `
    "$PSScriptRoot\alerter.py" `
    "$PSScriptRoot\requirements.txt" `
    "$PSScriptRoot\probes" `
    "$PSScriptRoot\templates" `
    "${VpsUser}@${VpsHost}:${RemoteDir}/" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "SCP FAILED" -ForegroundColor red
    exit 1
}
Write-Host "  Upload OK" -ForegroundColor green

# 4. Create .env on VPS
Write-Host "[4/6] Creating .env on VPS..." -ForegroundColor yellow
Write-Host "  Note: Set these env vars manually on VPS if needed:" -ForegroundColor yellow
Get-Content "$PSScriptRoot\.env.example" | ForEach-Object { Write-Host "    $_" }

# 5. Install Python deps
Write-Host "[5/6] Installing Python dependencies..." -ForegroundColor yellow
ssh -o StrictHostKeyChecking=no -i "$KeyPath" "${VpsUser}@${VpsHost}" @"
cd $RemoteDir
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
"@ 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  pip install failed" -ForegroundColor red
    exit 1
}
Write-Host "  Deps OK" -ForegroundColor green

# 6. Start the service
Write-Host "[6/6] Starting monitor service..." -ForegroundColor yellow
ssh -o StrictHostKeyChecking=no -i "$KeyPath" "${VpsUser}@${VpsHost}" @"
cd $RemoteDir
source venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8080 > /tmp/monitor.log 2>&1 &
echo \$! > /tmp/monitor.pid
sleep 3
if kill -0 \$(cat /tmp/monitor.pid) 2>/dev/null; then
    echo 'Monitor started OK'
else
    echo 'Monitor FAILED to start - check /tmp/monitor.log'
    cat /tmp/monitor.log
fi
"@ 2>&1

Write-Host ""
Write-Host "=== Deployed ===" -ForegroundColor green
Write-Host "Dashboard: http://${VpsHost}:8080/" -ForegroundColor cyan
Write-Host "API:      http://${VpsHost}:8080/api/checks" -ForegroundColor cyan
Write-Host "Health:   http://${VpsHost}:8080/health" -ForegroundColor cyan
Write-Host ""
Write-Host "Set env vars on VPS:" -ForegroundColor yellow
Write-Host "  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RESEND_API_KEY," -ForegroundColor yellow
Write-Host "  ALERT_EMAIL, GITHUB_TOKEN" -ForegroundColor yellow
Write-Host "See $RemoteDir/.env.example" -ForegroundColor yellow
