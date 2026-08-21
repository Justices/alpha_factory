# 🏭 Alpha Factory 生产环境部署与无人值守运维手册
> **Enterprise Production Deployment & High-Availability Operations Guide**

---

## 📖 目录

1. [生产环境基建要求与安全准则](#1-生产环境基建要求与安全准则)
2. [生产部署三部曲 (Standard Deployment)](#2-生产部署三部曲-standard-deployment)
3. [生产调度方式 1: Systemd 系统级守护进程 (推荐)](#3-生产调度方式-1-systemd-系统级守护进程-推荐)
4. [生产调度方式 2: Crontab 定时矩阵巡检](#4-生产调度方式-2-crontab-定时矩阵巡检)
5. [生产调度方式 3: Screen / Tmux 持久会话](#5-生产调度方式-3-screen--tmux-持久会话)
6. [多市场/多数据集生产矩阵配置](#6-多市场多数据集生产矩阵配置)
7. [生产监控、日志轮转与告警集成](#7-生产监控日志轮转与告警集成)
8. [容灾恢复与断点续传 (Zero-Data-Loss)](#8-容灾恢复与断点续传-zero-data-loss)

---

## 1. 生产环境基建要求与安全准则

### 1.1 硬件与系统推荐
- **操作系统**：Ubuntu 22.04 LTS / Debian 12 / Rocky Linux 9 (或 Windows Server 2022)
- **CPU / 内存**：4 核 8G 内存以上
- **磁盘**：NVMe SSD（SQLite 高频 WAL 并发读写需要高 IOPS）
- **网络**：具备稳定访问 WorldQuant BRAIN API 官方服务器的公网通道

### 1.2 生产安全规范
- **禁止提交数据库文件**：生产库 `data/alpha_research.db` 必须由 `init_db.py` 在部署时本地全新生成，严禁通过 Git 提交二进制库；
- **凭据最小权限隔离**：`.brain.json` 权限设为 `chmod 600 .brain.json`，防止非授权用户读取。

---

## 2. 生产部署三部曲 (Standard Deployment)

```bash
# 步骤 1: 拉取代码并建立生产环境目录
git clone <YOUR_GIT_REPO_URL> /opt/alpha_factory
cd /opt/alpha_factory

# 步骤 2: 建立 Python 生产虚拟环境与依赖安装
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 步骤 3: 配置 BRAIN 认证与初始化数据库
cat << 'EOF' > .brain.json
{
  "email": "your_production_account@worldquant.com",
  "password": "your_secure_password"
}
EOF
chmod 600 .brain.json

# 一键初始化生产表结构与索引
python init_db.py --verify
```

---

## 3. 生产调度方式 1: Systemd 系统级守护进程 (推荐)

使用 Linux `systemd` 将 Alpha Factory 注册为后台系统服务，享有**开机自启、故障自动拉起重启、统一日志管理**能力：

```bash
# 1. 复制服务配置文件到系统服务目录
sudo cp scripts/alpha-factory.service /etc/systemd/system/

# 2. 重新加载 systemd 守护进程
sudo systemctl daemon-reload

# 3. 启动服务并设置开机自启
sudo systemctl start alpha-factory.service
sudo systemctl enable alpha-factory.service

# 4. 查看实时运行状态与日志
sudo systemctl status alpha-factory.service
sudo journalctl -u alpha-factory.service -f
```

---

## 4. 生产调度方式 2: Crontab 定时矩阵巡检

适合每天在固定时间（如隔夜/非交易时段）轮转探索多个市场与数据集：

```bash
# 编辑定时任务
crontab -e

# 添加如下调度规则（每天凌晨 02:00 自动启动）：
0 2 * * * /bin/bash /opt/alpha_factory/scripts/prod_pipeline_matrix.sh > /dev/null 2>&1
```

---

## 5. 生产调度方式 3: Screen / Tmux 持久会话

适用于运维工程师临时快速挂机投研：

```bash
# 1. 创建名为 alpha 的 screen 会话
screen -S alpha

# 2. 在会话中启动生产矩阵
./scripts/prod_pipeline_matrix.sh

# 3. 按键盘 Ctrl+A 紧接着按 D 键，安全脱离会话（后台保持全速运行）

# 4. 重新接入查看进展
screen -r alpha
```

---

## 6. 多市场/多数据集生产矩阵配置

编辑 [`scripts/prod_pipeline_matrix.sh`](file:///d:/quant/alpha_factory/scripts/prod_pipeline_matrix.sh) 中的 `TARGET_MATRIX` 数组，可自定义跨市场巡检任务流：

```bash
TARGET_MATRIX=(
    # 格式: 市场|Universe|数据集列表|Decay周期|每族抽样数
    "GBR|TOP700|analyst7,fundamental31|12|5"
    "USA|TOP3000|model250,risk71|15|6"
    "EUR|TOP2500|insider_agg_matrix,pattern_scores|10|5"
    "ASI|TOP1000|fundamental31,risk60|12|5"
)
```
- 每次跑完一个数据集，系统会自动将达标因子**反向蒸馏为高阶模板**存入知识库；
- 当切换到下一个市场或数据集时，系统自动复用上一个数据集探索出的高阶经验！

---

## 7. 生产监控、日志轮转与告警集成

### 7.1 查看实时生产日志
```bash
# 查看今日生产执行日志
tail -f runs/logs/prod_matrix_$(date +%Y%m%d)*.log
```

### 7.2 达标 Alpha 自动查询与告警
```bash
# 查询今日最新达标进入 SUBMISSION_READY 的优胜因子
python -c "
from alpha_operator_framework.database import AlphaDatabase
db = AlphaDatabase()
alphas = db.get_submission_candidates()
print(f'🏆 生产库累计达标 Alpha 总数: {len(alphas)}')
for a in alphas[:10]:
    print(f'  • [{a.alpha_id}] Sharpe={a.sharpe:.2f}, Margin={a.margin:.1f}bp | {a.expression}')
"
```

---

## 8. 容灾恢复与断点续传 (Zero-Data-Loss)

- **批次持久化保障**：回测每完成一批（默认 5 条），立即向 SQLite 写入不可变事件与绩效结果。即便遭遇服务器断电、断网或进程被 Kill，**已跑完的数据 100% 完好无损**；
- **增量防重保护**：重启后系统自动扫描已有 SHA-256 指纹，优先从未测空间抽取候选，**绝不产生重复回测消耗**；
- **Outbox Saga 自动恢复**：
  ```powershell
  # 执行崩溃断点续传演练与自动修复
  python alpha_machine.py drill-recovery
  ```
