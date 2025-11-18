"""
调度器与队列模块

职责：
- 管理待抓取URL队列（Frontier）
- 去重与抓取范围控制（allowed_domains）
- 协调并发抓取任务
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable, Set, List

from .utils import normalize_url, same_domain

logger = logging.getLogger(__name__)


class Scheduler:
    """
    简易调度器：
    - 使用 asyncio.Queue 管理待抓取URL
    - 维护已见集合避免重复抓取
    - 通过 allowed_domains 控制抓取范围
    """

    def __init__(self, seeds: List[str], allowed_domains: List[str]) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.seen: Set[str] = set()
        self.allowed_domains = allowed_domains or []

        for url in seeds:
            self.enqueue(url)

    def enqueue(self, url: str) -> None:
        url = normalize_url(url)
        if self.allowed_domains and not same_domain(url, self.allowed_domains):
            logger.debug("Skip (out of domain): %s", url)
            return
        if url in self.seen:
            return
        self.seen.add(url)
        self.queue.put_nowait(url)

    async def run(self, worker: Callable[[str], Awaitable[None]], concurrency: int) -> None:
        """以指定并发度启动抓取任务。"""
        async def _worker_task(idx: int) -> None:
            while True:
                url = await self.queue.get()
                try:
                    await worker(url)
                except Exception as e:
                    logger.exception("Worker %s failed on %s: %s", idx, url, e)
                finally:
                    self.queue.task_done()

        tasks = [asyncio.create_task(_worker_task(i)) for i in range(concurrency)]
        await self.queue.join()
        for t in tasks:
            t.cancel()