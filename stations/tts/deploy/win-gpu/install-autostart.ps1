# win-gpu autostart installer — registers Workshop TTS Service in Task Scheduler.
#
# Use:
#   powershell -ExecutionPolicy Bypass -File install-autostart.ps1
#
# Reversible: `Unregister-ScheduledTask -TaskName "Workshop TTS Service" -Confirm:$false`

$ErrorActionPreference = "Stop"

$HereDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$XmlPath = Join-Path $HereDir "workshop-tts-autostart.xml"
$TaskName = "Workshop TTS Service"

if (-not (Test-Path $XmlPath)) {
    Write-Error "XML not found: $XmlPath"
    exit 1
}

# Idempotent: remove existing then re-register
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$xmlContent = Get-Content $XmlPath | Out-String
Register-ScheduledTask -Xml $xmlContent -TaskName $TaskName
Write-Host "✓ Registered '$TaskName'" -ForegroundColor Green

Write-Host "`n=== Verify ===" -ForegroundColor Cyan
Get-ScheduledTask -TaskName $TaskName | Select TaskName, State, @{Name="NextRun"; Expression={(Get-ScheduledTaskInfo -TaskName $_.TaskName).NextRunTime}}

Write-Host "`nTrigger now (test):  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "Watch logs:           Get-Content C:\Users\User\workshop\stations\tts\tts.autostart.log -Wait" -ForegroundColor Yellow
Write-Host "Remove:               Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Yellow
