# ==============================================================================
# Alpha Factory 云端全自动无人值守投研一键启动脚本 (Windows PowerShell)
# ==============================================================================

param (
    [string]$Region = "GBR",
    [string]$Universe = "TOP700",
    [string]$Datasets = "analyst7",
    [int]$SamplePerFamily = 4,
    [int]$BatchSize = 5,
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"

# 1. 激活虚拟环境 (若存在)
if (Test-Path ".venv\Scripts\Activate.ps1") {
    .venv\Scripts\Activate.ps1
} elseif (Test-Path "venv\Scripts\Activate.ps1") {
    venv\Scripts\Activate.ps1
}

# 2. 检查凭据配置
if (-not (Test-Path ".brain.json")) {
    Write-Host "❌ 错误: 未在根目录下找到 .brain.json 凭据文件！" -ForegroundColor Red
    exit 1
}

# 3. 准备日志目录
New-Item -ItemType Directory -Force -Path "runs\logs", "runs\reports" | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = "runs\logs\autopilot_$Timestamp.log"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "🚀 启动 Alpha Factory 全自动无人值守投研流水线" -ForegroundColor Cyan
Write-Host "📄 实时日志输出: $LogFile" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$ArgsList = @(
    "alpha_machine.py", "auto-pilot",
    "--region", $Region,
    "--universe", $Universe,
    "--datasets", $Datasets,
    "--sample-per-family", $SamplePerFamily,
    "--batch-size", $BatchSize,
    "--min-sharpe", "1.25",
    "--min-fitness", "1.0"
)

if (-not $DryRun) {
    $ArgsList += "--execute"
}

# 启动执行并同时输出屏幕与写入日志
& python $ArgsList *>&1 | Tee-Object -FilePath $LogFile

Write-Host ""
Write-Host "🎉 无人值守流水线已执行完毕，完整日志已记录在: $LogFile" -ForegroundColor Green
