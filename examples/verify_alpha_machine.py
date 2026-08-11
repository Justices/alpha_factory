#!/usr/bin/env python
"""手动验证 alpha_machine 迁移是否可用.

用法 (必须用 quant venv python, 因为它有 mcp/pydantic 依赖):
    PY=/Users/liujiaping/ai/quant/.venv/bin/python
    $PY examples/verify_alpha_machine.py                # 离线验证 (不访问平台)
    $PY examples/verify_alpha_machine.py --online       # 含平台只读请求 (认证+拉字段, 不消耗额度)

每一项打 ✅ 才说明迁移可用; 任一 ❌ 会立即报错退出。
"""

import sys
import asyncio
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ONLINE = "--online" in sys.argv


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "✅" if cond else "❌"
    print(f"  {status} {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        raise SystemExit(f"FAILED: {name}")


print("=== 1. import (必须是项目根的文件) ===")
import alpha_machine as am
import cnhkmcp
check("import alpha_machine", am.__file__.startswith(str(ROOT)), am.__file__)
check("import cnhkmcp (shim)", cnhkmcp.__file__.startswith(str(ROOT)), cnhkmcp.__file__)
from cnhkmcp.untracked.platform_functions import brain_client, create_multi_simulation
check("brain_client.ensure_authenticated 可用", callable(brain_client.ensure_authenticated))
check("create_multi_simulation 可调用", callable(create_multi_simulation))

print("=== 2. 离线函数 (字段解析/筛选/质量门/预处理) ===")
f = am.field_from_dict({'id': 'close', 'dataset_id': 'pv1', 'coverage': 0.95,
                        'userCount': 3, 'type': 'MATRIX'})
check("field_from_dict", f.id == 'close' and f.dataset_id == 'pv1' and f.type == 'MATRIX')

sel = am.select_fields([{'id': 'a', 'coverage': 0.9, 'userCount': 5},
                        {'id': 'b', 'coverage': 0.5, 'userCount': 1}], min_coverage=0.8)
check("select_fields", [x.id for x in sel] == ['a'])

rows = [
    {'alpha_id': 'x1', 'sharpe': 1.6, 'fitness': 1.1, 'margin': 6.0, 'turnover': 0.05,
     'is': {'checks': [{'name': 'LOW_SHARPE', 'result': 'PASS'}]}},
    {'alpha_id': 'x2', 'sharpe': 1.0, 'fitness': 0.5, 'margin': 3.0, 'turnover': 0.9},
]
kept, rejected = am.filter_alpha_results(rows, am.QualityGate(sharpe=1.2, fitness=0.7, margin=5.0))
check("filter_alpha_results",
      [r['alpha_id'] for r in kept] == ['x1'] and [r['alpha_id'] for r in rejected] == ['x2'])

exprs = am.preprocess_field(f)
check("preprocess_field", exprs[0].startswith('winsorize('), exprs[0][:40])

print("=== 3. 额度保护 (simulate 无 --execute 必须拒绝) ===")
try:
    am.command_simulate(argparse.Namespace(execute=False, region='EUR', universe='TOP2500', delay=1))
    check("simulate 无 --execute 被拒绝", False)
except SystemExit as e:
    check("simulate 无 --execute 被拒绝", "Refusing" in str(e), str(e).strip())

if ONLINE:
    print("=== 4. 平台只读验证 (认证 + 拉字段, 不消耗额度) ===")
    async def main() -> None:
        await brain_client.ensure_authenticated()
        check("BRAIN 认证成功", await brain_client.is_authenticated())

        resp = brain_client.session.get(
            f"{brain_client.base_url}/data-fields",
            params={'instrumentType': 'EQUITY', 'region': 'EUR', 'universe': 'TOP2500',
                    'delay': 1, 'limit': 10, 'offset': 0}
        )
        check("data-fields HTTP 200", resp.status_code == 200, f"status={resp.status_code}")
        payload = resp.json()
        results = payload.get('results') or []
        check("拿到真实字段数据", len(results) > 0, f"{len(results)} 个, count总数={payload.get('count')}")
    asyncio.run(main())
else:
    print("=== 4. 平台只读验证 (跳过, 加 --online 才访问平台) ===")

print("\n🎉 全部通过 — alpha_machine 迁移可用")
