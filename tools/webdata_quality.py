#!/usr/bin/env python3
"""WebDataScope 数据包 → 数据集/字段质量排名 + 中性化推荐。

用法:
    python3 tools/webdata_quality.py --zip runs/WebData_20260219_V0.10.9.zip --region USA --delay 1
    python3 tools/webdata_quality.py --zip runs/WebData_20260219_V0.10.9.zip --region USA --delay 1 --json-out runs/dataset_quality.json

依赖: pip install msgpack
输出: stdout 打印 markdown 摘要; --json-out 可另存完整排名 JSON。
规则说明见 alpha_operator_framework/evaluation.py。
"""
from __future__ import annotations

import argparse
import json
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict, List

import msgpack


ROOT = Path(__file__).resolve().parent.parent


def load_bin(zf: zipfile.ZipFile, name: str) -> Any:
    """解压并反序列化 .bin 文件."""
    return msgpack.unpackb(zlib.decompress(zf.read(name)), strict_map_key=False)


def extract_quality_stats(zip_path: str, region: str, delay: int) -> Dict[str, Any]:
    """
    从数据包提取数据集/字段质量统计.

    Args:
        zip_path: 数据包路径
        region: 区域 (USA/EUR/CHN/...)
        delay: 延迟 (0/1)

    Returns:
        dict 含 datasets, sweet_spot, fields, mean_sharpe 等
    """
    key = f"{region}_{delay}"
    with zipfile.ZipFile(zip_path) as zf:
        info = load_bin(zf, 'data/oth/info_data.bin')

    if key not in info:
        available = sorted(info.keys())
        raise ValueError(f"{key} 不在数据包中, 可用: {available}")

    isos = info[key]['isos']
    neut = info[key]['neutralization']
    mean_sharpe = isos['mean']['sharpe_ratio']

    def best_neuts(nstats: Dict, min_n: int) -> List:
        rows = [
            (k, v['sharpe_ratio'], v['count'])
            for k, v in nstats.items()
            if v.get('count', 0) >= min_n
        ]
        return sorted(rows, key=lambda x: -x[1])[:3]

    # 数据集统计
    ds_rows = []
    for ds, s in isos['dataset'].items():
        bn = best_neuts(neut['dataset'].get(ds, {}), 20)
        ds_rows.append({
            'dataset': ds,
            'count': s.get('count', 0),
            'sharpe': round(s.get('sharpe_ratio', 0), 3),
            'fitness': round(s.get('fitness_ratio', 0), 3),
            'best_neuts': [
                {'neut': n, 'sharpe': round(sh, 3), 'count': c}
                for n, sh, c in bn
            ]
        })
    ds_rows.sort(key=lambda r: -r['count'])

    # 甜点区
    sweet = sorted(
        [
            r for r in ds_rows
            if 100 <= r['count'] <= 3000 and r['sharpe'] >= mean_sharpe * 1.1
        ],
        key=lambda r: -r['sharpe']
    )

    # 字段统计
    f_rows = []
    for f, s in isos['datafield'].items():
        bn = best_neuts(neut['datafield'].get(f, {}), 5)
        f_rows.append({
            'field': f,
            'count': s.get('count', 0),
            'sharpe': round(s.get('sharpe_ratio', 0), 3),
            'fitness': round(s.get('fitness_ratio', 0), 3),
            'best_neuts': [
                {'neut': n, 'sharpe': round(sh, 3), 'count': c}
                for n, sh, c in bn
            ]
        })
    f_rows.sort(key=lambda r: -r['count'])

    return {
        'region_delay': key,
        'mean_sharpe': mean_sharpe,
        'total_count': isos['total_count'],
        'window': f"{info[key]['sub_beg_time']} → {info[key]['sub_end_time']}",
        'datasets': ds_rows,
        'sweet_spot': sweet,
        'fields': f_rows,
    }


def main():
    ap = argparse.ArgumentParser(
        description="WebDataScope 数据包 → 数据集/字段质量排名"
    )
    ap.add_argument('--zip', default=str(ROOT / 'runs/WebData_20260219_V0.10.9.zip'),
                    help='数据包路径 (默认: runs/WebData_20260219_V0.10.9.zip)')
    ap.add_argument('--region', default='USA', help='区域 (默认: USA)')
    ap.add_argument('--delay', type=int, default=1, help='延迟 (默认: 1)')
    ap.add_argument('--top', type=int, default=30, help='显示 Top N (默认: 30)')
    ap.add_argument('--json-out', default=None, help='JSON 输出路径')
    args = ap.parse_args()

    stats = extract_quality_stats(args.zip, args.region, args.delay)

    print(f"# {stats['region_delay']} 社区提交统计  窗口 {stats['window']}")
    print(f"总量 {stats['total_count']}  平均 sharpe {stats['mean_sharpe']:.3f}\n")

    # 数据集 Top N
    print(f"## 数据集 Top{args.top} (按提交数)\n")
    print("| dataset | count | sharpe | fitness | best neuts |\n|---|---|---|---|---|")
    for r in stats['datasets'][:args.top]:
        bn = ', '.join(f"{b['neut']}({b['sharpe']},n={b['count']})" for b in r['best_neuts'])
        print(f"| {r['dataset']} | {r['count']} | {r['sharpe']} | {r['fitness']} | {bn} |")

    # 甜点区
    print(f"\n## 甜点区 (100≤count≤3000 且 sharpe≥1.1×均值)\n")
    print("| dataset | count | sharpe | fitness | best neuts |\n|---|---|---|---|---|")
    for r in stats['sweet_spot'][:args.top]:
        bn = ', '.join(f"{b['neut']}({b['sharpe']},n={b['count']})" for b in r['best_neuts'])
        print(f"| {r['dataset']} | {r['count']} | {r['sharpe']} | {r['fitness']} | {bn} |")

    if args.json_out:
        with open(args.json_out, 'w') as fh:
            json.dump(stats, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON 已写入 {args.json_out}")


if __name__ == '__main__':
    main()
