"""
抓取器模块

职责：
- 执行HTTP请求，集成：
  - 站点级限速（DomainRateLimiter）
  - 退避重试（BackoffStrategy）
  - 代理轮换与失败熔断
  - UA与请求头随机化
  - robots.txt 允许性检查（可选）
- 可选：Playwright 渲染（如用户安装），用于处理JS重度页面

说明：
- 本模块设计为通用抓取层，不嵌入站点解析逻辑。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from .anti_bot import DomainRateLimiter, BackoffStrategy, RobotsCache
from .utils import build_default_headers, get_domain

logger = logging.getLogger(__name__)


class ProxyPool:
    """
    简易代理池：循环使用代理，记录失败次数，达到阈值后短暂熔断。
    """

    def __init__(self, proxies: List[str], fail_threshold: int = 3) -> None:
        self.proxies = proxies or []
        self.fail_threshold = fail_threshold
        self.fail_counts: Dict[str, int] = {p: 0 for p in self.proxies}
        self._idx = 0

    def next(self) -> Optional[str]:
        if not self.proxies:
            return None
        # 循环选择下一个代理
        start = self._idx
        while True:
            proxy = self.proxies[self._idx]
            self._idx = (self._idx + 1) % len(self.proxies)
            if self.fail_counts.get(proxy, 0) < self.fail_threshold:
                return proxy
            if self._idx == start:
                # 所有代理都熔断，返回None，走直连或等待
                return None

    def mark_failure(self, proxy: Optional[str]) -> None:
        if not proxy:
            return
        self.fail_counts[proxy] = self.fail_counts.get(proxy, 0) + 1

    def mark_success(self, proxy: Optional[str]) -> None:
        if not proxy:
            return
        self.fail_counts[proxy] = 0


class Fetcher:
    """
    通用抓取器，支持异步HTTP抓取与可选JS渲染。
    """

    def __init__(
        self,
        ua_pool: List[str],
        proxies: List[str],
        per_domain_delay_ms: int,
        max_retries: int,
        backoff_initial_ms: int,
        backoff_max_ms: int,
        respect_robots: bool,
    ) -> None:
        self.rate_limiter = DomainRateLimiter(per_domain_delay_ms)
        self.backoff = BackoffStrategy(backoff_initial_ms, backoff_max_ms)
        self.robots = RobotsCache()
        self.ua_pool = ua_pool
        self.proxy_pool = ProxyPool(proxies)
        self.max_retries = max_retries
        self.respect_robots = respect_robots

        # 使用HTTP/2 + 合理的超时（如站点不支持HTTP/2，httpx会回退）
        self.client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(30.0), follow_redirects=True)

        # Playwright 仅在用户安装时启用
        try:
            from playwright.async_api import async_playwright  # type: ignore
            self._playwright_factory = async_playwright
        except Exception:
            self._playwright_factory = None

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(self, url: str) -> Tuple[int, str]:
        """
        进行HTTP抓取，返回 (status_code, text)。
        - 应用 robots 检查
        - 应用域名限速
        - 进行重试与代理轮换
        - 请求头每次随机UA与轻微扰动
        """
        domain = get_domain(url)

        if self.respect_robots:
            try:
                if not self.robots.allowed(url):
                    logger.info("Blocked by robots: %s", url)
                    return 451, "Blocked by robots.txt"
            except Exception:
                # 解析异常时不阻断
                pass

        await self.rate_limiter.wait(domain)

        attempt = 0
        proxy_used: Optional[str] = None
        while attempt <= self.max_retries:
            headers = build_default_headers(self.ua_pool)
            proxy_used = proxy_used or self.proxy_pool.next()
            try:
                # httpx >=0.28 不再支持在请求级别传入 proxies；
                # 需要在客户端级别配置代理。
                # 这里根据是否命中代理池，临时创建一个带代理的客户端进行本次请求。
                client = self.client
                temp_client: Optional[httpx.AsyncClient] = None
                if proxy_used:
                    temp_client = httpx.AsyncClient(
                        http2=True,
                        timeout=httpx.Timeout(30.0),
                        follow_redirects=True,
                        proxies=proxy_used,
                    )
                    client = temp_client

                r = await client.get(url, headers=headers)
                status = r.status_code
                text = r.text

                if status in (403, 429, 500, 502, 503):
                    # 可重试错误码：触发退避
                    delay_ms = self.backoff.compute_delay_ms(attempt + 1)
                    logger.warning("%s -> %s; backoff %.0fms", status, url, delay_ms)
                    await asyncio.sleep(delay_ms / 1000.0)
                    attempt += 1
                    # 标记代理失败，轮换
                    self.proxy_pool.mark_failure(proxy_used)
                    proxy_used = None
                    continue

                # 成功：重置代理失败计数
                self.proxy_pool.mark_success(proxy_used)
                # 关闭临时客户端（如有）
                if temp_client:
                    try:
                        await temp_client.aclose()
                    except Exception:
                        pass
                return status, text
            except httpx.RequestError as e:
                # 网络错误：退避+代理轮换
                delay_ms = self.backoff.compute_delay_ms(attempt + 1)
                logger.error("Network error on %s: %s; retry in %.0fms", url, e, delay_ms)
                await asyncio.sleep(delay_ms / 1000.0)
                attempt += 1
                self.proxy_pool.mark_failure(proxy_used)
                proxy_used = None
                # 关闭临时客户端（如有）
                try:
                    if 'temp_client' in locals() and temp_client:
                        await temp_client.aclose()
                except Exception:
                    pass
            except Exception as e:
                # 未知异常不重试（可根据需要扩展）
                logger.exception("Unexpected error on %s: %s", url, e)
                # 关闭临时客户端（如有）
                try:
                    if 'temp_client' in locals() and temp_client:
                        await temp_client.aclose()
                except Exception:
                    pass
                return 520, "Unexpected error"

        return 599, "Max retries exceeded"

    async def render_js(self, url: str) -> Tuple[int, str]:
        """
        使用 Playwright 进行JS渲染（如可用），返回 (status_code, html)。
        - 若 Playwright 未安装或初始化失败，返回 501 与错误提示
        - 该方法仅在必要时调用，避免不必要的资源开销
        """
        if not self._playwright_factory:
            return 501, "Playwright not available"

        try:
            async with self._playwright_factory() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle")
                content = await page.content()
                await browser.close()
                return 200, content
        except Exception as e:
            logger.error("Playwright error: %s", e)
            return 520, f"Playwright error: {e}"
