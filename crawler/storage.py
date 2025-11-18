"""
存储与状态模块

职责：
- 使用SQLite记录已抓取URL、状态码、时间戳（便于断点续抓）
- 将HTML与解析结果存储到本地文件系统
- 提供插入与查询API
"""

from __future__ import annotations

import os
import json
import sqlite3
import time
from typing import Optional


class Storage:
    """
    统一的存储抽象，封装SQLite与文件存储。

    参数说明：
    - sqlite_path: SQLite 数据库文件路径
    - output_dir: 输出根目录（页面快照与解析结果）
    - html_subdir: 页面HTML保存的子目录；为空字符串表示直接保存在 output_dir 根目录。
      例如设置为 "pages" 时，HTML 文件保存到 output_dir/pages 下。
    """

    def __init__(self, sqlite_path: str, output_dir: str, html_subdir: str = "") -> None:
        self.sqlite_path = sqlite_path
        self.output_dir = output_dir
        self.html_subdir = html_subdir or ""
        # 预创建根目录与HTML子目录（如配置）
        os.makedirs(self.output_dir, exist_ok=True)
        if self.html_subdir:
            os.makedirs(os.path.join(self.output_dir, self.html_subdir), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.sqlite_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                  url TEXT PRIMARY KEY,
                  status INTEGER,
                  ts INTEGER
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def record_page(self, url: str, status: int) -> None:
        conn = sqlite3.connect(self.sqlite_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO pages(url, status, ts) VALUES(?,?,?)",
                (url, status, int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()

    def save_html(self, url: str, html: str) -> str:
        """
        将页面HTML保存到指定目录，文件名使用URL安全替换。返回保存路径。

        路径策略：
        - 若配置了 html_subdir，则保存到 output_dir/html_subdir/
        - 否则直接保存到 output_dir/
        """
        safe_name = url.replace("/", "_").replace(":", "_").replace("?", "_")
        if len(safe_name) > 180:
            import hashlib
            h = hashlib.sha1(url.encode("utf-8")).hexdigest()
            safe_name = f"{safe_name[:60]}__{h}"
        base_dir = self.output_dir if not self.html_subdir else os.path.join(self.output_dir, self.html_subdir)
        # 防御性：确保目录存在（避免运行时路径被删除）
        os.makedirs(base_dir, exist_ok=True)
        path = os.path.join(base_dir, f"{safe_name}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def save_json(self, url: str, data: dict) -> str:
        """将解析结果保存为JSON。返回保存路径。"""
        safe_name = url.replace("/", "_").replace(":", "_").replace("?", "_")
        if len(safe_name) > 180:
            import hashlib
            h = hashlib.sha1(url.encode("utf-8")).hexdigest()
            safe_name = f"{safe_name[:60]}__{h}"
        path = os.path.join(self.output_dir, f"{safe_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path
