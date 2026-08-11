"""Alpha获取模块 — 从不同来源获取alpha列表.

支持三种来源:
  1. 从工作流结果获取 (survey/deepen的结果)
  2. 从平台查询 (alpha_machine)
  3. 从文件读取 (JSON)

配合optimize.py的筛选功能使用。
"""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Sequence


# ---------------------------------------------------------------------------
# 方式1: 从工作流结果获取
# ---------------------------------------------------------------------------

def get_alphas_from_workflow_result(
    result,  # WorkflowResult对象
    stage: str = "survey"
) -> List[Dict[str, Any]]:
    """从WorkflowResult中提取alpha列表.

    Args:
        result: run_full_workflow返回的结果
        stage: 阶段名 ("survey"/"deepen"/"submit")

    Returns:
        alpha列表

    Example:
        >>> result = await run_full_workflow(...)
        >>> alphas = get_alphas_from_workflow_result(result, "survey")
    """
    if isinstance(result, dict):
        stage_result = result.get(stage)
        if stage_result and hasattr(stage_result, 'candidates'):
            return stage_result.candidates
        elif stage_result and hasattr(stage_result, 'top_templates'):
            # survey阶段返回top模板，不是alpha列表
            return []
        elif stage_result and hasattr(stage_result, '__dict__'):
            # 尝试从文件读取
            if stage_result.results_file:
                return load_alphas_from_file(stage_result.results_file)
    return []


# ---------------------------------------------------------------------------
# 方式2: 从文件读取
# ---------------------------------------------------------------------------

def load_alphas_from_file(
    file_path: str | Path
) -> List[Dict[str, Any]]:
    """从JSON文件读取alpha列表.

    支持多种文件格式:
      - alpha_machine的模拟结果JSON
      - survey/deepen的结果JSON
      - 自定义alpha列表JSON

    Args:
        file_path: JSON文件路径

    Returns:
        alpha列表

    Example:
        >>> alphas = load_alphas_from_file("runs/survey_results_EUR_pv1.json")
        >>> len(alphas)
        100
    """
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"⚠ 文件不存在: {file_path}")
        return []

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))

        # 处理不同格式
        if isinstance(data, list):
            # 直接是列表
            return data
        elif isinstance(data, dict):
            # 可能是 {"results": [...]} 或 {"alphas": [...]}
            if "results" in data:
                return data["results"]
            elif "alphas" in data:
                return data["alphas"]
            elif "kept" in data:
                # deepen的kept文件
                return data["kept"]
            else:
                # 单个alpha
                return [data]
        else:
            return []

    except json.JSONDecodeError as e:
        print(f"⚠ JSON解析失败: {e}")
        return []


# ---------------------------------------------------------------------------
# 方式3: 从平台查询 (需要alpha_machine)
# ---------------------------------------------------------------------------

async def fetch_user_alphas(
    region: Optional[str] = None,
    status: str = "IS",  # IS=未提交, OS=已提交
    min_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    limit: int = 100,
    order_by: str = "-is.sharpe",
    page_size: int = 50,          # 每页获取数量
    max_pages: int = 20,          # 最大页数(防止无限循环)
    enable_pagination: bool = True # 是否启用分页
) -> List[Dict[str, Any]]:
    """从平台查询用户的alpha列表(支持分页).

    Args:
        region: 地区筛选 (可选)
        status: 状态 (IS=In-Sample, OS=Out-of-Sample)
        min_sharpe: 最小Sharpe (可选)
        min_fitness: 最小Fitness (可选)
        limit: 最大返回总数 (0表示无限制,默认100)
        order_by: 排序字段 (默认按Sharpe降序)
        page_size: 每页获取数量 (默认50)
        max_pages: 最大页数 (默认20,防止无限循环)
        enable_pagination: 是否启用分页 (默认True)

    Returns:
        alpha列表

    Example:
        >>> # 获取EUR市场所有未提交的alpha
        >>> alphas = await fetch_user_alphas(
        ...     region="EUR",
        ...     status="IS",
        ...     limit=0,  # 0表示获取全部
        ...     enable_pagination=True
        ... )

        >>> # 获取前500个高质量alpha
        >>> alphas = await fetch_user_alphas(
        ...     min_sharpe=1.2,
        ...     limit=500,
        ...     page_size=100
        ... )

    Note:
        - 启用分页时,会循环获取直到: 达到limit / 没有更多数据 / 达到max_pages
        - limit=0表示获取全部(受max_pages限制)
        - 需要安装alpha_machine并配置brain_client
    """
    try:
        import alpha_machine

        all_alphas = []
        page = 0
        offset = 0

        while True:
            # 检查是否达到最大页数
            if enable_pagination and page >= max_pages:
                print(f"达到最大页数限制({max_pages}),停止查询")
                break

            # 计算本次获取数量
            if limit > 0:
                # 有总数限制
                remaining = limit - len(all_alphas)
                if remaining <= 0:
                    break
                current_page_size = min(page_size, remaining)
            else:
                # 无总数限制
                current_page_size = page_size

            # 查询参数
            params = {
                "stage": status,
                "limit": current_page_size,
                "offset": offset,
                "order": order_by
            }

            if region:
                params["region"] = region

            # 查询当前页
            try:
                alpha_rows = await alpha_machine.fetch_user_alphas(**params)
            except Exception as e:
                print(f"⚠ 查询第{page+1}页失败: {e}")
                break

            # 没有数据了
            if not alpha_rows or len(alpha_rows) == 0:
                if page == 0:
                    print("未查询到符合条件的alpha")
                break

            # 转换为标准格式
            page_alphas = []
            for row in alpha_rows:
                alpha = {
                    "alpha_id": row.get("id"),
                    "expression": row.get("regular", {}).get("code"),
                    "sharpe": row.get("is", {}).get("sharpe"),
                    "fitness": row.get("is", {}).get("fitness"),
                    "turnover": row.get("is", {}).get("turnover"),
                    "margin": row.get("is", {}).get("margin"),
                    "pnl": row.get("is", {}).get("pnl"),
                    "longCount": row.get("is", {}).get("longCount"),
                    "shortCount": row.get("is", {}).get("shortCount"),
                    "region": row.get("settings", {}).get("region"),
                    "decay": row.get("settings", {}).get("decay"),
                    "dateCreated": row.get("dateCreated")
                }

                # 应用质量筛选
                if min_sharpe and alpha["sharpe"] and alpha["sharpe"] < min_sharpe:
                    continue
                if min_fitness and alpha["fitness"] and alpha["fitness"] < min_fitness:
                    continue

                page_alphas.append(alpha)

            all_alphas.extend(page_alphas)

            # 打印进度
            if enable_pagination:
                print(f"第{page+1}页: 获取{len(page_alphas)}个, 累计{len(all_alphas)}个")

            # 检查是否还有下一页
            if not enable_pagination:
                # 不分页,只获取第一页
                break

            if len(alpha_rows) < current_page_size:
                # 返回数据少于请求数量,说明没有更多了
                break

            # 准备下一页
            page += 1
            offset += current_page_size

            # 检查是否达到limit
            if limit > 0 and len(all_alphas) >= limit:
                break

        return all_alphas

    except ImportError:
        print("⚠ 未安装alpha_machine，无法从平台查询")
        print("  使用方法: pip install alpha_machine")
        return []
    except Exception as e:
        print(f"⚠ 查询失败: {e}")
        return []


async def fetch_alpha_by_ids(
    alpha_ids: List[str],
    batch_size: int = 10,    # 每批查询数量
    max_retries: int = 3     # 失败重试次数
) -> List[Dict[str, Any]]:
    """从平台查询指定的alpha(支持批量查询).

    Args:
        alpha_ids: alpha_id列表
        batch_size: 每批查询数量 (默认10)
        max_retries: 失败重试次数 (默认3)

    Returns:
        alpha列表

    Example:
        >>> # 批量查询100个alpha
        >>> alphas = await fetch_alpha_by_ids(
        ...     alpha_ids_list,  # 100个ID
        ...     batch_size=20    # 每批20个
        ... )

        >>> # 查询失败会自动重试
        >>> alphas = await fetch_alpha_by_ids(
        ...     ["alpha_001", "alpha_002"],
        ...     max_retries=5
        ... )
    """
    if not alpha_ids:
        return []

    try:
        import alpha_machine

        all_alphas = []
        failed_ids = []

        # 分批查询
        total_batches = (len(alpha_ids) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(alpha_ids))
            batch_ids = alpha_ids[start:end]

            print(f"查询批次{batch_idx+1}/{total_batches}: {len(batch_ids)}个alpha")

            # 重试逻辑
            for retry in range(max_retries):
                try:
                    batch_alphas = []

                    for alpha_id in batch_ids:
                        try:
                            # 查询单个alpha
                            alpha_detail = await alpha_machine.get_alpha_details(alpha_id)

                            alpha = {
                                "alpha_id": alpha_detail.get("id"),
                                "expression": alpha_detail.get("regular", {}).get("code"),
                                "sharpe": alpha_detail.get("is", {}).get("sharpe"),
                                "fitness": alpha_detail.get("is", {}).get("fitness"),
                                "turnover": alpha_detail.get("is", {}).get("turnover"),
                                "margin": alpha_detail.get("is", {}).get("margin"),
                                "pnl": alpha_detail.get("is", {}).get("pnl"),
                                "longCount": alpha_detail.get("is", {}).get("longCount"),
                                "shortCount": alpha_detail.get("is", {}).get("shortCount"),
                                "region": alpha_detail.get("settings", {}).get("region"),
                                "decay": alpha_detail.get("settings", {}).get("decay"),
                            }

                            batch_alphas.append(alpha)

                        except Exception as e:
                            print(f"⚠ 查询alpha {alpha_id}失败: {e}")
                            failed_ids.append(alpha_id)

                    all_alphas.extend(batch_alphas)
                    break  # 成功,跳出重试循环

                except Exception as e:
                    if retry < max_retries - 1:
                        print(f"批次{batch_idx+1}查询失败,重试{retry+1}/{max_retries}...")
                        await asyncio.sleep(1)  # 等待1秒后重试
                    else:
                        print(f"⚠ 批次{batch_idx+1}查询失败,已达到最大重试次数")
                        failed_ids.extend(batch_ids)

        # 报告失败情况
        if failed_ids:
            print(f"\n⚠ 共{len(failed_ids)}个alpha查询失败:")
            for fid in failed_ids[:10]:  # 只显示前10个
                print(f"  - {fid}")
            if len(failed_ids) > 10:
                print(f"  ... 还有{len(failed_ids)-10}个")

        print(f"\n总计获取: {len(all_alphas)}/{len(alpha_ids)}个alpha")
        return all_alphas

    except ImportError:
        print("⚠ 未安装alpha_machine，无法从平台查询")
        return []
    except Exception as e:
        print(f"⚠ 查询失败: {e}")
        return []


# ---------------------------------------------------------------------------
# 便捷函数: 一站式筛选
# ---------------------------------------------------------------------------

async def get_and_filter_alphas(
    # 获取方式
    source: str = "platform",  # "platform" / "file" / "workflow"
    file_path: Optional[str] = None,
    workflow_result = None,

    # 平台查询参数
    region: Optional[str] = None,
    status: str = "IS",
    limit: int = 100,

    # 筛选参数
    alpha_ids: Optional[List[str]] = None,
    min_sharpe: Optional[float] = None,
    max_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    max_fitness: Optional[float] = None,
    min_turnover: Optional[float] = None,
    max_turnover: Optional[float] = None
) -> List[Dict[str, Any]]:
    """一站式获取并筛选alpha.

    自动处理获取和筛选两步:
      1. 从指定来源获取alpha列表
      2. 应用筛选条件

    Args:
        source: 来源 ("platform"/"file"/"workflow")
        file_path: 文件路径 (source="file"时)
        workflow_result: 工作流结果 (source="workflow"时)
        region: 地区筛选 (平台查询时)
        status: 状态 (平台查询时)
        limit: 最大获取数量
        alpha_ids: 指定alpha_id列表(精确筛选)
        min_sharpe: 最小Sharpe
        max_sharpe: 最大Sharpe
        min_fitness: 最小Fitness
        max_fitness: 最大Fitness
        min_turnover: 最小Turnover
        max_turnover: 最大Turnover

    Returns:
        筛选后的alpha列表

    Example:
        >>> # 方式1: 从平台查询并筛选
        >>> filtered = await get_and_filter_alphas(
        ...     source="platform",
        ...     region="EUR",
        ...     min_sharpe=1.58,
        ...     limit=50
        ... )

        >>> # 方式2: 从文件读取并筛选
        >>> filtered = await get_and_filter_alphas(
        ...     source="file",
        ...     file_path="runs/survey_results.json",
        ...     min_sharpe=1.2,
        ...     max_sharpe=1.8
        ... )

        >>> # 方式3: 指定alpha_id查询
        >>> filtered = await get_and_filter_alphas(
        ...     source="platform",
        ...     alpha_ids=["alpha_001", "alpha_002"]
        ... )
    """
    # 第一步: 获取alpha列表
    alphas = []

    if source == "platform":
        if alpha_ids:
            # 精确查询
            alphas = await fetch_alpha_by_ids(alpha_ids)
        else:
            # 条件查询
            alphas = await fetch_user_alphas(
                region=region,
                status=status,
                min_sharpe=min_sharpe,
                min_fitness=min_fitness,
                limit=limit
            )

    elif source == "file":
        if file_path:
            alphas = load_alphas_from_file(file_path)
        else:
            print("⚠ source='file'时需提供file_path参数")

    elif source == "workflow":
        if workflow_result:
            alphas = get_alphas_from_workflow_result(workflow_result)
        else:
            print("⚠ source='workflow'时需提供workflow_result参数")

    # 第二步: 应用筛选 (如果还有额外筛选条件)
    if alpha_ids and source != "platform":
        # 已精确查询,无需再筛选alpha_ids
        pass
    elif any([min_sharpe, max_sharpe, min_fitness, max_fitness, min_turnover, max_turnover]):
        # 应用筛选
        from .ai_workflow import filter_alphas_for_optimization
        alphas = filter_alphas_for_optimization(
            alphas,
            alpha_ids=alpha_ids if source != "platform" else None,  # 平台已精确查询
            min_sharpe=min_sharpe if source != "platform" else None,  # 平台已筛选
            max_sharpe=max_sharpe,
            min_fitness=min_fitness if source != "platform" else None,
            max_fitness=max_fitness,
            min_turnover=min_turnover,
            max_turnover=max_turnover,
            limit=limit
        )

    return alphas


__all__ = [
    # 获取函数
    "get_alphas_from_workflow_result",
    "load_alphas_from_file",
    "fetch_user_alphas",
    "fetch_alpha_by_ids",
    "get_and_filter_alphas",
]