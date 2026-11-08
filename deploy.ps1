# Watchtower - deploy the committed code to the VPS and restart the systemd service.
# Run: pwsh C:\Users\User\monitor\deploy.ps1
# Uses the `vps` SSH alias. Never copies .env or monitor.db.

Set-Location $PSScriptRoot
$Vps = "vps"
$RemoteDir = "watchtower/monitor"
$Files = @("main.py", "config.py", "storage.py", "alerter.py", "requirements.txt", "probes", "templates")

function Assert-Ok([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE). Stopped." }
    Write-Host "  OK: $Step" -ForegroundColor Green
}

# Production follows origin/main. Deploying anything else can roll back another session's work.
git fetch -q origin
Assert-Ok "git fetch"
$head = git rev-parse HEAD
$origin = git rev-parse origin/main
if ($head -ne $origin) { throw "Local HEAD $head is not origin/main $origin. Pull or push first. Nothing was deployed." }
$dirty = git status --porcelain -- $Files
if ($dirty) { throw "Uncommitted changes in deployed files. Nothing was deployed:`n$($dirty -join "`n")" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$list = ($Files -join " ")
ssh $Vps "cd $RemoteDir && mkdir -p ../backups && tar czf ../backups/monitor-code-$stamp.tgz $list"
Assert-Ok "backup to ~/watchtower/backups/monitor-code-$stamp.tgz"

scp -q -r @Files "${Vps}:${RemoteDir}/"
Assert-Ok "upload"

ssh $Vps "cd $RemoteDir && venv/bin/pip install -q -r requirements.txt"
Assert-Ok "pip install"

# Startup runs every probe before the app serves requests, so allow it time.
ssh $Vps "sudo systemctl restart watchtower && sleep 25 && systemctl is-active watchtower && curl -sf localhost:8080/health"
Assert-Ok "restart and health check"

Write-Host "Deployed $head. Log it in the CLAUDE.md changelog." -ForegroundColor Cyan
