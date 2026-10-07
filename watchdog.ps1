$ErrorActionPreference = 'SilentlyContinue'
$logFile = Join-Path $PSScriptRoot "watchdog.log"
$url = "http://127.0.0.1:5002/api/einstellungen"

$ok = $false
try {
    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    $ok = $resp.StatusCode -eq 200
} catch {
    $ok = $false
}

if (-not $ok) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "$ts - Dashboard nicht erreichbar, starte CorrispettiviBackend neu."
    Stop-ScheduledTask -TaskName "CorrispettiviBackend"
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName "CorrispettiviBackend"
}
