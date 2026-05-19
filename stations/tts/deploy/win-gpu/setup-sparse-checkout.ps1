# win-gpu sparse-checkout setup — Windows host (PowerShell)
#
# Idempotent: 第一次跑 clone + checkout，之後跑會 git fetch + pull。
# 對應 stations/tts/DEPLOY.md「win-gpu 部署 SOP」step 1。
#
# 使用：
#   ssh win-gpu
#   powershell -ExecutionPolicy Bypass -File C:\Users\User\setup-sparse-checkout.ps1
#
# 為什麼 sparse-checkout：workshop monolith 上 GB（vendor/, workbench/dist/, core/），
# win-gpu 只需 stations/tts + libs/sdk-client + mcp/tts + scripts + .claude/rules。

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/JonesHong/workshop.git"
$WorkshopDir = "C:\Users\User\workshop"
$Branch = "feature/tts-station-integration"

$SparsePaths = @(
    "stations/tts",
    "libs/sdk-client",
    "mcp/tts",
    "scripts",
    ".claude/rules"
)

if (-not (Test-Path "$WorkshopDir\.git")) {
    Write-Host "=== Clone workshop (sparse, treeless) ===" -ForegroundColor Cyan
    git clone --filter=blob:none --no-checkout $RepoUrl $WorkshopDir
    Push-Location $WorkshopDir
    git sparse-checkout init --cone
    git sparse-checkout set @SparsePaths
    git fetch origin $Branch
    git checkout $Branch
    Pop-Location
} else {
    Write-Host "=== Update existing workshop ===" -ForegroundColor Cyan
    Push-Location $WorkshopDir
    git fetch origin $Branch
    git checkout $Branch
    git pull --ff-only origin $Branch
    # Refresh sparse paths in case manifest changed
    git sparse-checkout set @SparsePaths
    Pop-Location
}

Write-Host "=== Sparse-checkout contents ===" -ForegroundColor Cyan
Push-Location $WorkshopDir
git sparse-checkout list
Write-Host "`n=== Disk usage ===" -ForegroundColor Cyan
$size = (Get-ChildItem -Recurse | Measure-Object -Property Length -Sum).Sum
Write-Host ("{0:N1} MB" -f ($size / 1MB))
Pop-Location

Write-Host "`n✓ Done. workshop is at $WorkshopDir on branch $Branch" -ForegroundColor Green
Write-Host "  Next: bash setup-tts-venv.sh (or run from WSL)" -ForegroundColor Yellow
