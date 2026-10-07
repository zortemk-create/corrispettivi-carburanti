# Richtet den Autostart ein (als Administrator ausfuehren):
#  - CorrispettiviBackend:  startet das Dashboard beim Systemstart (Konto SYSTEM, ohne Anmeldung)
#  - CorrispettiviWatchdog: prueft alle 5 Minuten, ob das Dashboard antwortet, und startet es sonst neu
# Erneutes Ausfuehren ersetzt die bestehenden Aufgaben.

$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$python = (Get-Command python).Source

$backendAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" `
    -Argument "/c `"`"$python`" `"$dir\app.py`" >> `"$dir\backend.log`" 2>&1`"" -WorkingDirectory $dir
$backendSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "CorrispettiviBackend" -Force `
    -Description "Corrispettivi Carburanti Dashboard (http://127.0.0.1:5002)" `
    -Action $backendAction -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $backendSettings `
    -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount) | Out-Null

$watchAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$dir\watchdog.ps1`"" -WorkingDirectory $dir
$watchTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "CorrispettiviWatchdog" -Force `
    -Description "Startet das Corrispettivi-Dashboard neu, falls es nicht antwortet" `
    -Action $watchAction -Trigger $watchTrigger `
    -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew) `
    -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest) | Out-Null

Start-ScheduledTask -TaskName "CorrispettiviBackend"
Write-Output "Autostart eingerichtet. Dashboard: http://127.0.0.1:5002"
