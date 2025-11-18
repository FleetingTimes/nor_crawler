"""
解析模块

职责：
- 提供基础HTML解析（BeautifulSoup）
- 暴露简单的选择器API

说明：
- 具体站点解析逻辑应在插件中实现，避免耦合
"""

from __future__ import annotations

from typing import List
from bs4 import BeautifulSoup


def extract_links(html: str) -> List[str]:
    """
    从HTML中提取所有<a>链接的href。
    - 返回可能包含相对链接，插件或调度阶段可进一步标准化与过滤
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if href:
            links.append(href)
    return links