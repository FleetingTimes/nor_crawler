"""
工具函数模块

职责：
- 域名提取、随机UA/请求头生成
- 抖动延迟计算（用于速率限制）
- 简易的模式匹配工具
"""

from __future__ import annotations

import random
import time
import urllib.parse
from typing import List, Dict


DEFAULT_UA_POOL = [
    # 简单内置UA池；可在配置中覆盖
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
]


def pick_user_agent(pool: List[str] | None) -> str:
    """从给定UA池或默认池随机选取一个UA。"""
    candidates = pool if pool else DEFAULT_UA_POOL
    return random.choice(candidates)


def build_default_headers(ua_pool: List[str] | None) -> Dict[str, str]:
    """构造默认请求头，包含随机UA与通用头。"""
    return {
        "User-Agent": pick_user_agent(ua_pool),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(["zh-CN,zh;q=0.9", "en-US,en;q=0.9", "zh-TW,zh;q=0.9"]),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        # 指纹扰动：随机添加部分无害头
        **({"DNT": random.choice(["1", "0"])} if random.random() < 0.5 else {}),
    }


def jitter_delay_ms(base_ms: int, rate: float = 0.3) -> float:
    """
    计算带抖动的延迟时间（毫秒）。
    - base_ms: 基础延迟
    - rate: 抖动比例（0~1），默认0.3表示在 ±30% 范围随机。
    """
    if base_ms <= 0:
        return 0
    delta = base_ms * rate
    return base_ms + random.uniform(-delta, delta)


def sleep_ms(ms: float) -> None:
    """以毫秒为单位的阻塞睡眠（在异步中请使用 asyncio.sleep）。"""
    time.sleep(ms / 1000.0)


def get_domain(url: str) -> str:
    """从URL中提取域名（netloc）。"""
    return urllib.parse.urlparse(url).netloc


def same_domain(url: str, domains: List[str]) -> bool:
    """判断URL是否属于允许的域名列表中的任一域。"""
    netloc = get_domain(url).lower()
    return any(netloc.endswith(d.lower()) for d in domains)


def normalize_url(url: str) -> str:
    """规范化URL（去除片段、标准化大小写等）。"""
    parsed = urllib.parse.urlparse(url)
    # 去除片段（#hash），保留查询
    parsed = parsed._replace(fragment="")
    return urllib.parse.urlunparse(parsed)