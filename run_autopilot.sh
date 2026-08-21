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

# 默认参数
REGION="GBR"
UNIVERSE="TOP700"
DATASETS="analyst7"
SAMPLE_PER_FAMILY=4
BATCH_SIZE=5
DECAY=12
NEUTRALIZATION="SUBINDUSTRY"
DRY_RUN=0

# 解析命名参数与位置参数
POSITIONAL_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -u|--universe)
            UNIVERSE="$2"
            shift 2
            ;;
        -d|--datasets)
            DATASETS="$2"
            shift 2
            ;;
        -s|--sample-per-family|--samples)
            SAMPLE_PER_FAMILY="$2"
            shift 2
            ;;
        -b|--batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --decay)
            DECAY="$2"
            shift 2
            ;;
        -n|--neutralization)
            NEUTRALIZATION="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            echo "用法: $0 [选项] 或 $0 [REGION] [UNIVERSE] [DATASETS] [SAMPLE_PER_FAMILY] [BATCH_SIZE] [DECAY] [NEUTRALIZATION]"
            echo ""
            echo "选项:"
            echo "  -r, --region <str>             目标市场代码 (默认: GBR)"
            echo "  -u, --universe <str>           股票池 (默认: TOP700)"
            echo "  -d, --datasets <str>           指定数据集列表，逗号分隔 (默认: analyst7)"
            echo "  -s, --samples, --sample-per-family <int> 每类生成抽取的数量 (默认: 4)"
            echo "  -b, --batch-size <int>         平台并发回测每批任务数 (默认: 5)"
            echo "      --decay <int>              时序衰减周期 (默认: 12)"
            echo "  -n, --neutralization <str>     行业中性化基准 (默认: SUBINDUSTRY)"
            echo "      --dry-run                  仅预览生成任务，不提交实际回测"
            echo "  -h, --help                     显示此帮助信息"
            exit 0
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

# 如果传入了位置参数，按位置覆盖
if [ ${#POSITIONAL_ARGS[@]} -ge 1 ]; then REGION="${POSITIONAL_ARGS[0]}"; fi
if [ ${#POSITIONAL_ARGS[@]} -ge 2 ]; then UNIVERSE="${POSITIONAL_ARGS[1]}"; fi
if [ ${#POSITIONAL_ARGS[@]} -ge 3 ]; then DATASETS="${POSITIONAL_ARGS[2]}"; fi
if [ ${#POSITIONAL_ARGS[@]} -ge 4 ]; then SAMPLE_PER_FAMILY="${POSITIONAL_ARGS[3]}"; fi
if [ ${#POSITIONAL_ARGS[@]} -ge 5 ]; then BATCH_SIZE="${POSITIONAL_ARGS[4]}"; fi
if [ ${#POSITIONAL_ARGS[@]} -ge 6 ]; then DECAY="${POSITIONAL_ARGS[5]}"; fi
if [ ${#POSITIONAL_ARGS[@]} -ge 7 ]; then NEUTRALIZATION="${POSITIONAL_ARGS[6]}"; fi

EXEC_FLAG="--execute"
if [ "$DRY_RUN" -eq 1 ]; then
    EXEC_FLAG=""
fi

# 执行一键流水线
PYTHON_BIN="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_BIN="python"
fi

$PYTHON_BIN alpha_machine.py auto-pilot \
    --region "$REGION" \
    --universe "$UNIVERSE" \
    --datasets "$DATASETS" \
    --sample-per-family "$SAMPLE_PER_FAMILY" \
    --batch-size "$BATCH_SIZE" \
    --decay "$DECAY" \
    --neutralization "$NEUTRALIZATION" \
    --min-sharpe 1.25 \
    --min-fitness 1.0 \
    $EXEC_FLAG \
    2>&1 | tee "$LOG_FILE"

echo ""
echo "🎉 无人值守流水线已执行完毕，完整日志已记录在: $LOG_FILE"
