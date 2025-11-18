"""
反爬与礼貌抓取模块

职责：
- robots.txt 检查与缓存
- 站点级限速与并发控制（在调度/抓取中调用）
- 错误状态码的退避重试策略

注意：本模块不直接进行网络请求，仅提供策略计算与校验工具。
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from typing import Dict, Optional

import urllib.robotparser as robotparser


class RobotsCache:
    """
    robots.txt 缓存与校验。

    - 针对每个域名只加载一次 robots.txt，并缓存结果
    - 使用标准库 robotparser 进行允许性判断
    """

    def __init__(self, user_agent: str = "*") -> None:
        self.user_agent = user_agent
        self._cache: Dict[str, robotparser.RobotFileParser] = {}

    def _robots_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def allowed(self, url: str) -> bool:
        domain = urllib.parse.urlparse(url).netloc
        if domain not in self._cache:
            rp = robotparser.RobotFileParser()
            rp.set_url(self._robots_url(url))
            try:
                rp.read()
            except Exception:
                # 读取失败视为允许（保守策略可改为禁止）
                rp = None
            self._cache[domain] = rp or robotparser.RobotFileParser()
        rp = self._cache.get(domain)
        if not rp:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True


class BackoffStrategy:
    """
    指数退避策略：根据尝试次数计算等待时间，带上限与抖动。
    """

    def __init__(self, initial_ms: int, max_ms: int) -> None:
        self.initial_ms = initial_ms
        self.max_ms = max_ms

    def compute_delay_ms(self, attempt: int) -> float:
        base = min(self.initial_ms * (2 ** max(0, attempt - 1)), self.max_ms)
        # 抖动：±20%
        jitter = base * 0.2
        return base + (asyncio.get_event_loop().time() % jitter) - (jitter / 2)


class DomainRateLimiter:
    """
    域名级节流控制：确保同一域名的请求间隔至少为指定毫秒数。
    """

    def __init__(self, delay_ms: int) -> None:
        self.delay_ms = delay_ms
        self.last_request_ts: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, domain: str) -> None:
        async with self._lock:
            now = time.time()
            last = self.last_request_ts.get(domain, 0.0)
            wait_s = (self.delay_ms / 1000.0) - (now - last)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            self.last_request_ts[domain] = time.time()