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
        """确保会话已成功认证."""
        if not self.session.cookies:
            self.session_manager.hydrate(self.session)

        # 校验会话有效性
        try:
            resp = self.session.get(f"{self.base_url}/users/self", timeout=15)
            if resp.status_code == 200:
                return
        except Exception:
            pass

        # 尝试重新认证
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
                if attempt == 2:
                    raise e
                time.sleep(2.0)

        if not resp or resp.status_code not in (200, 201):
            err = resp.text[:200] if resp else "No response"
            code = resp.status_code if resp else "N/A"
            raise RuntimeError(f"BRAIN 平台认证失败 ({code}): {err}")

        self.session_manager.persist(self.session)
        logger.info(f"BRAIN 平台认证成功: {email}")

    def submit_batch(
        self,
        tasks: Sequence[Union[Task, Dict[str, Any]]],
        settings: Dict[str, Any],
    ) -> str:
        """向 BRAIN 平台批量提交模拟回测任务."""
        self.ensure_authenticated()

        region = settings.get("region", "GBR")
        universe = settings.get("universe", "TOP700" if region == "GBR" else "TOP1200")
        delay = int(settings.get("delay", 1))
        decay = int(settings.get("decay", 8))
        neutralization = settings.get("neutralization", "SUBINDUSTRY")
        truncation = float(settings.get("truncation", 0.08))
        unit_handling = settings.get("unitHandling", settings.get("unit_handling", "VERIFY"))
        nan_handling = settings.get("nan_handling", "OFF")

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
                    time.sleep(5.0)
                else:
                    break
            except Exception as e:
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

        return location

    def poll_batch(
        self,
        location: str,
        max_wait_seconds: float = 600.0,
        poll_interval: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """轮询平台模拟任务直到完成，并拉取所有子任务详情."""
        self.ensure_authenticated()

        url = _normalize_platform_url(self.base_url, location)
        start_time = time.time()

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
                detail = self.fetch_alpha_detail(alpha_id)
                return [detail]

            # 2. 批次完成判断
            progress_val = float(progress_data.get("progress") or 0.0)
            if status in ("COMPLETE", "COMPLETED", "DONE", "FINISHED", "WARNING") or progress_val >= 1.0:
                break
            elif status in ("FAILED", "ERROR"):
                raise RuntimeError(f"平台模拟任务执行失败: {progress_data.get('message', 'Unknown error')}")

            # 等待建议重试时间
            time.sleep(max(1.0, min(retry_after, 5.0)))

        # 3. 批量任务解析 children
        children = progress_data.get("children") or []
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
                        detail = self.fetch_alpha_detail(str(alpha_id))
                        results.append(detail)
                        break
                    elif c_status in ("COMPLETE", "COMPLETED", "DONE", "FINISHED", "WARNING", "FAILED", "ERROR"):
                        if c_json.get("message"):
                            logger.warning(f"Child simulation message: {c_json.get('message')}")
                        break
                time.sleep(2.0)

        return results

    def fetch_alpha_detail(self, alpha_id: str) -> Dict[str, Any]:
        """获取单个 Alpha 完整回测指标与 Checks 数据."""
        self.ensure_authenticated()
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
        """执行完整平台真实回测批次并返回标准化的 PlatformAlphaResult."""
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

        for i in range(0, total_tasks, eff_batch_size):
            chunk = task_list[i : i + eff_batch_size]
            chunk_exprs = [
                (t.expression if isinstance(t, Task) else t.get("expression", ""))
                for t in chunk
            ]
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
                logger.error(f"平台并发批次回测失败 (批次大小={len(chunk)}): {e}")
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

