#!/usr/bin/env bash
# ==============================================================================
# Alpha Factory 生产环境多市场/多数据集全自主循环投研矩阵调度器
# ==============================================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 1. 环境激活
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# 2. 检查凭据
if [ ! -f ".brain.json" ]; then
    echo "❌ [ERROR] 未找到 .brain.json 凭据文件，生产环境无法启动！" >&2
    exit 1
fi

mkdir -p runs/logs runs/reports data

LOG_TIME=$(date +"%Y%m%d_%H%M%S")
MAIN_LOG="runs/logs/prod_matrix_${LOG_TIME}.log"

echo "======================================================================" | tee -a "$MAIN_LOG"
echo "🚀 启动 Alpha Factory 生产环境全自动投研矩阵 (PID: $$)" | tee -a "$MAIN_LOG"
echo "📅 开始时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$MAIN_LOG"
echo "📄 日志文件: $MAIN_LOG" | tee -a "$MAIN_LOG"
echo "======================================================================" | tee -a "$MAIN_LOG"

# 3. 生产投研任务矩阵配置 (市场 | 股票池 | 数据集组合 | Decay | 抽样数)
TARGET_MATRIX=(
    "GBR|TOP700|analyst7,fundamental31|12|5"
    "USA|TOP3000|model250,risk71|15|6"
    "EUR|TOP2500|insider_agg_matrix,pattern_scores|10|5"
    "ASI|TOP1000|fundamental31,risk60|12|5"
)

for target in "${TARGET_MATRIX[@]}"; do
    IFS="|" read -r REGION UNIVERSE DATASETS DECAY SAMPLES <<< "$target"
    echo "" | tee -a "$MAIN_LOG"
    echo "🎯 [生产任务] 正在执行: 市场=$REGION, Universe=$UNIVERSE, 数据集=$DATASETS, Decay=$DECAY, 样本=$SAMPLES" | tee -a "$MAIN_LOG"
    
    python alpha_machine.py auto-pilot \
        --region "$REGION" \
        --universe "$UNIVERSE" \
        --datasets "$DATASETS" \
        --sample-per-family "$SAMPLES" \
        --batch-size 5 \
        --decay "$DECAY" \
        --neutralization SUBINDUSTRY \
        --min-sharpe 1.25 \
        --execute >> "$MAIN_LOG" 2>&1 || {
            echo "⚠️ [WARN] 任务 ($REGION / $UNIVERSE) 发生异常，已记录日志并自动切入下一目标" | tee -a "$MAIN_LOG"
        }
    
    # 生产任务间隔冷却 (30 秒防封防限流)
    echo "⏳ [Cooling] 生产批次间隔休眠 30 秒..." | tee -a "$MAIN_LOG"
    sleep 30
done

# 4. 生产周期结束自动执行数据库碎片清理
echo "" | tee -a "$MAIN_LOG"
echo "🧹 [维护] 执行生产数据库碎片清理与物理空间回收 (VACUUM)..." | tee -a "$MAIN_LOG"
python alpha_machine.py clean-db --mode stale >> "$MAIN_LOG" 2>&1 || true

echo "======================================================================" | tee -a "$MAIN_LOG"
echo "🎉 生产投研矩阵全流程执行完毕！结束时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$MAIN_LOG"
echo "======================================================================" | tee -a "$MAIN_LOG"
