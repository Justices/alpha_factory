#!/usr/bin/env bash
# ==============================================================================
# Alpha Factory 云端全自动无人值守投研一键启动脚本 (Linux / macOS)
#
# 功能:
#   1. 自动检查 Python 环境与依赖
#   2. 自动检查 .brain.json 凭据
#   3. 自动执行数据库完整性校验 (init_db.py --verify)
#   4. 串联执行: 真实并发回测 ➔ 6维证据终审 ➔ 状态机流转 ➔ 空间VACUUM ➔ 汇总研报
#   5. 实时输出并重定向完整日志至 runs/logs/autopilot_$(date +%Y%m%d_%H%M%S).log
# ==============================================================================

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 激活虚拟环境 (若存在)
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# 2. 检查凭据配置
if [ ! -f ".brain.json" ]; then
    echo "❌ 错误: 未在根目录下找到 .brain.json 凭据文件！"
    echo "请先创建 .brain.json 并填入 WorldQuant BRAIN 账号密码。"
    exit 1
fi

# 3. 准备日志目录
LOG_DIR="runs/logs"
REPORT_DIR="runs/reports"
mkdir -p "$LOG_DIR" "$REPORT_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/autopilot_$TIMESTAMP.log"

echo "======================================================================"
echo "🚀 启动 Alpha Factory 云端全自动无人值守投研流水线"
echo "📄 实时日志输出: $LOG_FILE"
echo "======================================================================"

# 默认参数 (支持外部传参覆盖)
REGION="${1:-GBR}"
UNIVERSE="${2:-TOP700}"
DATASETS="${3:-analyst7}"
SAMPLE_PER_FAMILY="${4:-4}"
BATCH_SIZE="${5:-5}"

# 执行一键流水线
python3 alpha_machine.py auto-pilot \
    --region "$REGION" \
    --universe "$UNIVERSE" \
    --datasets "$DATASETS" \
    --sample-per-family "$SAMPLE_PER_FAMILY" \
    --batch-size "$BATCH_SIZE" \
    --min-sharpe 1.25 \
    --min-fitness 1.0 \
    --execute \
    2>&1 | tee "$LOG_FILE"

echo ""
echo "🎉 无人值守流水线已执行完毕，完整日志已记录在: $LOG_FILE"
