"""WorldQuant BRAIN 真实平台多任务模拟器 (Real Platform Simulator).

功能:
  1. 基于 BrainSessionManager 的进程安全认证会话
  2. 批量提交 Alpha 表达式至 WorldQuant BRAIN 平台真实模拟服务器 (POST /simulations)
  3. 异步轮询等待平台计算完成 (遵从 Retry-After 标头与流控限速)
  4. 采集平台真实回测结果 (Sharpe, Fitness, Turnover, Margin, Drawdown, 18 项 Checks, Correlations)
  5. 无缝对接到 AlphaJudge 执行实战终审
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

import requests

from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.platform.rate_limiter import AdaptiveRateLimiter
from cnhkmcp.session_manager import BrainSessionManager

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.worldquantbrain.com"


def _normalize_platform_url(base_url: str, location: str) -> str:
    """规范化平台 URL，防止重复协议头拼接."""
    if location.startswith("http://") or location.startswith("https://"):
        return location
    clean_base = base_url.rstrip("/")
    if location.startswith("/"):
        return f"{clean_base}{location}"
    return f"{clean_base}/{location}"


def _failure_details(payload: Mapping[str, Any]) -> str:
    """提取有用的平台错误信息。"""
    details: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for name in ("code", "message", "reason", "detail", "error"):
                if value.get(name) not in (None, ""):
                    nested = value[name]
                    if isinstance(nested, Mapping):
                        collect(nested)
                    else:
                        details.append(f"{name}={str(nested)[:300]}")
        elif value not in (None, ""):
            details.append(str(value)[:300])

    collect(payload)
    return "; ".join(dict.fromkeys(details)) or "no platform error detail"


@dataclass
class PlatformAlphaResult:
    """平台真实回测结果容器."""

    alpha_id: str
    expression: str
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    pnl: float = 0.0
    is_valid: bool = True
    status: str = "COMPLETED"
    checks_passed: bool = True
    failed_checks: List[str] = field(default_factory=list)
    raw_details: Dict[str, Any] = field(default_factory=dict)
    pc_value: float = 0.0
    sc_value: float = 0.0


class BrainPlatformSimulator:
    """WorldQuant BRAIN 平台真实回测执行器."""

    def __init__(
        self,
        session_manager: Optional[BrainSessionManager] = None,
        base_url: str = DEFAULT_BASE_URL,
        database: Optional[AlphaDatabase] = None,
        rate_limiter: Optional[AdaptiveRateLimiter] = None,
    ) -> None:
        self.session_manager = session_manager or BrainSessionManager()
        self.base_url = base_url.rstrip("/")
        self.database = database
        self.rate_limiter = rate_limiter or AdaptiveRateLimiter()
        self.session = requests.Session()
        self.session_manager.hydrate(self.session)

    def ensure_authenticated(self) -> None:
        """确保当前连接会话已成功认证且有效。

        若失效则尝试多次重新登录并序列化存储 Cookie。
        """
        logger.info("检查 WorldQuant BRAIN 平台会话身份认证有效性...")
        if not self.session.cookies:
            self.session_manager.hydrate(self.session)

        # 校验会话有效性
        try:
            resp = self.session.get(f"{self.base_url}/users/self", timeout=15)
            if resp.status_code == 200:
                logger.info("BRAIN 平台 Session 会话依然有效")
                return
        except Exception:
            pass

        # 尝试重新认证
        logger.info("Session 缺失或失效，正在重新发起 WorldQuant BRAIN 平台登录认证...")
        email, password = self.session_manager.credentials()
        resp = None
        for attempt in range(3):
            try:
                resp = self.session.post(
                    f"{self.base_url}/authentication",
                    auth=(email, password),
                    timeout=45,
                )
                if resp.status_code in (200, 201):
                    break
            except Exception as e:
                logger.warning("平台登录认证尝试失败 (第 %d/3 次): %s", attempt + 1, e)
                if attempt == 2:
                    raise e
                time.sleep(2.0)

        if not resp or resp.status_code not in (200, 201):
            err = resp.text[:200] if resp else "No response"
            code = resp.status_code if resp else "N/A"
            raise RuntimeError(f"BRAIN 平台认证失败 ({code}): {err}")

        self.session_manager.persist(self.session)
        logger.info("BRAIN 平台认证成功: %s", email)

    def submit_batch(
        self,
        tasks: Sequence[Union[Task, Dict[str, Any]]],
        settings: Dict[str, Any],
    ) -> str:
        """向 BRAIN 平台批量提交模拟回测任务，返回重定向 Location。

        Args:
            tasks: 待回测的任务序列。
            settings: 基础回测配置环境。

        Returns:
            str: 平台分配的用于进度查询的任务重定向 Location 相对或绝对 URL。
        """
        self.ensure_authenticated()

        region = settings.get("region", "GBR")
        universe = settings.get("universe", "TOP700" if region == "GBR" else "TOP1200")
        delay = int(settings.get("delay", 1))
        decay = int(settings.get("decay", 8))
        neutralization = settings.get("neutralization", "SUBINDUSTRY")
        truncation = float(settings.get("truncation", 0.08))
        unit_handling = settings.get("unitHandling", settings.get("unit_handling", "VERIFY"))
        nan_handling = settings.get("nan_handling", "OFF")

        logger.info("准备批量提交任务至平台. 区域: %s, 股票池: %s, 共 %d 个因子", region, universe, len(tasks))

        payload = []
        for t in tasks:
            expr = t.expression if isinstance(t, Task) else t["expression"]
            t_decay = t.meta.get("recommended_decay", decay) if isinstance(t, Task) else t.get("decay", decay)

            item_payload = {
                "type": "REGULAR",
                "settings": {
                    "instrumentType": "EQUITY",
                    "region": region,
                    "universe": universe,
                    "delay": delay,
                    "decay": int(t_decay),
                    "neutralization": neutralization,
                    "truncation": truncation,
                    "pasteurization": "ON",
                    "unitHandling": unit_handling,
                    "nanHandling": nan_handling,
                    "language": "FASTEXPR",
                    "visualization": False,
                },
                "regular": expr,
            }
            payload.append(item_payload)

        # 单个 simulation 直接发 dict，多个发 list
        post_body = payload if len(payload) > 1 else payload[0]
        
        resp = None
        for attempt in range(3):
            try:
                resp = self.session.post(f"{self.base_url}/simulations", json=post_body, timeout=90)
                if resp.status_code in (200, 201, 202):
                    break
                elif resp.status_code == 429:
                    logger.warning("触发平台限速 429，休眠 5s 后重试...")
                    time.sleep(5.0)
                else:
                    break
            except Exception as e:
                logger.warning("提交回测批次出错 (第 %d/3 次): %s", attempt + 1, e)
                if attempt == 2:
                    raise e
                time.sleep(3.0)

        if not resp or resp.status_code not in (200, 201, 202):
            err_msg = resp.text[:300] if resp else "No response"
            status = resp.status_code if resp else "N/A"
            raise RuntimeError(f"平台模拟任务提交失败 ({status}): {err_msg}")

        location = resp.headers.get("Location")
        if not location:
            raise RuntimeError("平台未返回模拟 Location 标头")

        logger.info("批次提交成功。进度重定向地址: %s", location)
        return location

    def poll_batch(
        self,
        location: str,
        max_wait_seconds: float = 600.0,
        poll_interval: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """轮询已提交的模拟回测状态，直到批次内所有因子回测完成并拉取详情。

        Args:
            location: 进度状态 URL。
            max_wait_seconds: 最大超时等待时间（秒）。
            poll_interval: 默认轮询检测间隔（秒）。

        Returns:
            List[Dict[str, Any]]: 每个子因子在平台的完整回测指标和 Check 列表。
        """
        self.ensure_authenticated()

        url = _normalize_platform_url(self.base_url, location)
        start_time = time.time()
        logger.info("开始轮询计算进度，Location=%s", location)

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_seconds:
                raise TimeoutError(f"等待平台回测完成超时 ({max_wait_seconds}s)")

            resp = self.session.get(url, timeout=20)
            if resp.status_code not in (200, 202):
                raise RuntimeError(f"轮询回测进度失败 ({resp.status_code}): {resp.text[:200]}")

            progress_data = resp.json() if resp.text else {}
            status = str(progress_data.get("status") or "").upper()
            retry_after = float(resp.headers.get("Retry-After", poll_interval))

            # 1. 单任务直接返回了 alpha ID
            if progress_data.get("alpha"):
                alpha_id = str(progress_data["alpha"])
                logger.info("单因子直接就绪，下载因子详情: %s", alpha_id)
                detail = self.fetch_alpha_detail(alpha_id)
                return [detail]

            # 2. 批次完成判断
            progress_val = float(progress_data.get("progress") or 0.0)
            logger.info("当前计算进度: %.1f%%, 平台状态: %s", progress_val * 100, status)
            
            if status in ("COMPLETE", "COMPLETED", "DONE", "FINISHED", "WARNING") or progress_val >= 1.0:
                logger.info("平台批量模拟计算完毕，进入结果收集阶段")
                break
            elif status in ("FAILED", "ERROR"):
                raise RuntimeError(
                    f"平台模拟任务执行失败: status={status}; location={location}; {_failure_details(progress_data)}"
                )

            # 等待建议重试时间
            time.sleep(max(1.0, min(retry_after, 5.0)))

        # 3. 批量任务解析 children
        children = progress_data.get("children") or []
        logger.info("发现此批次包含 %d 个子因子任务，开始提取每个子因子的 alpha_id...", len(children))
        results = []
        for child_item in children:
            if isinstance(child_item, str):
                child_loc = child_item if "/simulations/" in child_item or child_item.startswith("http") else f"/simulations/{child_item}"
                child_url = _normalize_platform_url(self.base_url, child_loc)
            else:
                child_url = _normalize_platform_url(self.base_url, child_item.get("id", ""))

            # 轮询单个 child 直到获得 alpha_id
            for _ in range(30):
                c_resp = self.session.get(child_url, timeout=20)
                if c_resp.status_code == 200:
                    c_json = c_resp.json()
                    c_status = str(c_json.get("status") or "").upper()
                    alpha_id = c_json.get("alpha")
                    if alpha_id:
                        logger.info("成功获取子任务 alpha_id=%s", alpha_id)
                        detail = self.fetch_alpha_detail(str(alpha_id))
                        results.append(detail)
                        break
                    elif c_status in ("COMPLETE", "COMPLETED", "DONE", "FINISHED", "WARNING", "FAILED", "ERROR"):
                        if c_json.get("message"):
                            logger.warning(f"Child simulation message: {c_json.get('message')}")
                        break
                time.sleep(2.0)

        logger.info("批量拉取所有子任务详情完成，实际成功获取 %d 个因子数据", len(results))
        return results

    def fetch_alpha_detail(self, alpha_id: str) -> Dict[str, Any]:
        """拉取指定 Alpha ID 在平台的完整绩效详情。"""
        self.ensure_authenticated()
        logger.info("从平台拉取 Alpha %s 详情...", alpha_id)
        resp = self.session.get(f"{self.base_url}/alphas/{alpha_id}", timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"获取 Alpha {alpha_id} 详情失败 ({resp.status_code}): {resp.text[:200]}")
        return resp.json()

    def run_simulations(
        self,
        tasks: Sequence[Union[Task, Dict[str, Any]]],
        region: str = "GBR",
        universe: str = "TOP700",
        neutralization: str = "SUBINDUSTRY",
        delay: int = 1,
        decay: int = 8,
        batch_size: int = 5,
        max_wait_seconds: float = 600.0,
    ) -> List[PlatformAlphaResult]:
        """将一组任务按分片批量提交至 WorldQuant BRAIN 真实网络环境并拉取结果。

        Args:
            tasks: 待执行的量化任务序列。
            region: 量化市场。
            universe: 量化股票宇宙。
            neutralization: 中性化方案。
            delay: 回测延迟。
            decay: 默认半衰期。
            batch_size: 并发回测切片批大小。
            max_wait_seconds: 最大回测超时（秒）。

        Returns:
            List[PlatformAlphaResult]: 转换并标准化后的真实回测结果列表。
        """
        settings = {
            "region": region,
            "universe": universe,
            "neutralization": neutralization,
            "delay": delay,
            "decay": decay,
        }

        all_platform_results: List[PlatformAlphaResult] = []

        task_list = list(tasks)
        total_tasks = len(task_list)
        eff_batch_size = max(1, batch_size)

        logger.info("准备在 BRAIN 平台上运行 %d 个模拟任务 (批分片大小=%d)...", total_tasks, eff_batch_size)

        for i in range(0, total_tasks, eff_batch_size):
            chunk = task_list[i : i + eff_batch_size]
            chunk_exprs = [
                (t.expression if isinstance(t, Task) else t.get("expression", ""))
                for t in chunk
            ]
            logger.info("执行切片队列: [%d/%d]", i + len(chunk), total_tasks)
            try:
                location = self.submit_batch(chunk, settings)
                raw_details_list = self.poll_batch(location, max_wait_seconds=max_wait_seconds)

                for idx, details in enumerate(raw_details_list):
                    aid = str(details.get("id") or "")
                    expr_fallback = chunk_exprs[idx] if idx < len(chunk_exprs) else ""
                    expr_code = str(details.get("regular", {}).get("code") or details.get("expression") or expr_fallback)
                    is_metrics = details.get("is", {})
                    checks = details.get("is", {}).get("checks", [])

                    failed_checks = [c.get("name") for c in checks if c.get("result") != "PASS"]

                    p_res = PlatformAlphaResult(
                        alpha_id=aid,
                        expression=expr_code,
                        sharpe=float(is_metrics.get("sharpe") or 0.0),
                        fitness=float(is_metrics.get("fitness") or 0.0),
                        turnover=float(is_metrics.get("turnover") or 0.0),
                        margin=float(is_metrics.get("margin") or 0.0),
                        annualized_return=float(is_metrics.get("returns") or 0.0),
                        max_drawdown=float(is_metrics.get("drawdown") or 0.0),
                        pnl=float(is_metrics.get("pnl") or 0.0),
                        is_valid=len(failed_checks) == 0,
                        status="COMPLETED",
                        checks_passed=len(failed_checks) == 0,
                        failed_checks=failed_checks,
                        raw_details=details,
                    )
                    all_platform_results.append(p_res)

            except Exception as e:
                logger.exception("平台并发批次回测遇到故障 (分片大小=%d): %s", len(chunk), e)
                for exp in chunk_exprs:
                    all_platform_results.append(
                        PlatformAlphaResult(
                            alpha_id="FAILED_SUBMISSION",
                            expression=exp,
                            is_valid=False,
                            status="FAILED",
                            checks_passed=False,
                            failed_checks=[str(e)],
                        )
                    )

        logger.info("所有 %d 个因子在平台回测调度完成", total_tasks)
        return all_platform_results

    def simulate_batch(
        self,
        tasks: Sequence[Union[Task, Dict[str, Any]]],
        settings: Optional[Dict[str, Any]] = None,
        poll_interval: float = 3.0,
        timeout: float = 600.0,
    ) -> List[PlatformAlphaResult]:
        """批量模拟回测别名方法."""
        cfg = settings or {}
        return self.run_simulations(
            tasks=tasks,
            region=cfg.get("region", "GBR"),
            universe=cfg.get("universe", "TOP700"),
            neutralization=cfg.get("neutralization", "SUBINDUSTRY"),
            delay=int(cfg.get("delay", 1)),
            decay=int(cfg.get("decay", 8)),
            max_wait_seconds=timeout,
        )
