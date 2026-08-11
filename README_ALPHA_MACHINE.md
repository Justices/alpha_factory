# alpha_machine 使用说明

本目录的 `alpha_machine.py` 迁移自 `/Users/liujiaping/ai/quant/scripts/alpha_machine.py`(原样复制,sha 校验一致)。
它是 WorldQuant BRAIN 平台的封装:字段探索、一阶/二阶构造、回测任务与质量门筛选。

> 重要:它**不是独立库**,运行时依赖 quant 工作区 venv 里的真实平台客户端
> (`cnhkmcp.untracked.platform_functions`)。因此**必须用 quant 的 venv python 运行**。

## 迁移过来的文件

```
alpha_machine.py                    # 平台封装 (源: quant/scripts/)
cnhkmcp/
  __init__.py                       # shim 包入口
  session_manager.py                # BRAIN 会话持久化 (cookie)
  untracked/
    platform_functions.py           # shim: 加载 quant venv 里的真实客户端
.brain.json                         # BRAIN 账号凭据 (同 quant 账号, 权限600)
.brain_session.json                 # 登录会话缓存 (首次认证后自动生成)
```

## 为什么必须用 quant 的 venv python

真实平台客户端(在 `quant/.venv/site-packages/cnhkmcp/`)依赖 `mcp` / `pydantic`,
系统 python 没有装。用 quant venv 即可全部满足:

```bash
PY=/Users/liujiaping/ai/quant/.venv/bin/python
$PY --version   # Python 3.13
```

## 三种使用方式

### 1. 命令行 CLI(不写代码)

```bash
PY=/Users/liujiaping/ai/quant/.venv/bin/python

# ① 发现字段 (只读, 不消耗额度)
$PY alpha_machine.py discover \
    --region EUR --universe TOP2500 --delay 1 \
    --output runs/fields.json

# ② 预处理 + 一阶构造 + 配对 (离线)
$PY alpha_machine.py prepare \
    --fields runs/fields.json --output runs/prepared.json \
    --decays 6 --seed 42

# ③ 模拟回测 (⚠ 必须 --execute 才消耗额度)
$PY alpha_machine.py simulate \
    --region EUR --universe TOP2500 --delay 1 \
    --tasks runs/prepared.json --output runs/results.json \
    --execute

# ④ 质量门筛选 (离线)
$PY alpha_machine.py filter \
    --results runs/results.json --output runs/kept.json \
    --sharpe 1.2 --fitness 0.7 --margin 5
```

### 2. 代码 API(在项目里 import)

```python
import alpha_machine as am

# 只读: 拉字段
rows = await am.fetch_datafields("EUR", "TOP2500", 1)

# 回测: 返回结果行 (含 is 块 + checks)
results = await am.simulate(
    [{"expression": "ts_rank(close, 10)", "decay": 6.0}],
    am._ns(region="EUR", universe="TOP2500", delay=1)  # argparse.Namespace
)

# 质量门
kept, rejected = am.filter_alpha_results(results, am.QualityGate(sharpe=1.2))
```

### 3. 现有框架(推荐)

`alpha_operator_framework` 的 survey → deepen → submit 已经 `import alpha_machine`,
模拟后自动落库 SQLite。直接用框架入口即可:

```bash
$PY -m alpha_operator_framework.orchestrator survey \
    --region EUR --universe TOP2500 --sample 80 --execute
```

## 认证

- 凭据在项目根 `.brain.json`(已复制 quant 同账号,权限 600)。
- 首次访问平台自动登录,会话缓存到 `.brain_session.json`(下次免登录)。
- 换账号 / 失效时:编辑 `.brain.json`,或删掉 `.brain_session.json` 重新登录。

## 安全提示

- `.brain.json` 含账号密码,不要提交到 git / 分享。
- 回测消耗平台额度,`simulate` 必须显式 `--execute` 才执行;`discover` / `fetch_datafields` 是只读。

## 已知限制(源文件既有行为, 未改动)

- `fetch_datafields` 全量翻页:连续翻页过快会触发平台 429 限流。
  实际用时建议:只用第一页,或手动分批 + 请求间隔。
- `fetch_datafields(search=...)`:search + 翻页到越界 offset 会 400。
  需要搜索时,先拉全量再本地 `select_fields` 过滤,或只取首页。
