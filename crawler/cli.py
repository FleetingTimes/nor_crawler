"""
CLI 入口模块

用法：
    先在 config.json 中配置好参数，再运行：
    python -m crawler.cli --config config.json
    python -m crawler.cli --config config\\alljavxx.json

说明：
- 读取配置，初始化各组件，并启动爬取。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
from typing import List

from .config import load_config
from .fetcher import Fetcher
from .scheduler import Scheduler
from .storage import Storage
from .parser import extract_links
from .login import build_login_strategy


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main(config_path: str) -> None:
    cfg = load_config(config_path)

    # 优雅退出：当 seeds 为空时（例如关键字已删光或关键字文件为空），
    # 在 CLI 层打印清晰提示并终止运行，而非继续创建空任务队列。
    # 说明：
    # - 若配置存在 seeds_from_keywords，则多半表示关键字文件为空或已全部处理，提示“当前爬取已完成或关键字文件为空”。
    # - 若完全没有 seeds_from_keywords，且 seeds 为空，提示“未提供入口 seeds”。
    if not cfg.seeds:
        if cfg.seeds_from_keywords:
            logging.info("当前爬取已完成或关键字文件为空，退出爬虫。")
        else:
            logging.info("未提供 seeds，退出爬虫。")
        return

    # 存储初始化：传入 html_subdir，使页面HTML可定向到子目录
    storage = Storage(cfg.storage.sqlite_path, cfg.storage.output_dir, getattr(cfg.storage, "html_subdir", ""))
    fetcher = Fetcher(
        ua_pool=cfg.user_agents,
        proxies=cfg.proxies,
        per_domain_delay_ms=cfg.per_domain_delay_ms,
        max_retries=cfg.max_retries,
        backoff_initial_ms=cfg.retry_backoff_initial_ms,
        backoff_max_ms=cfg.retry_backoff_max_ms,
        respect_robots=cfg.respect_robots_txt,
    )

    if cfg.login and cfg.login.cookies_file:
        try:
            from .login import apply_cookies_file
            applied = await apply_cookies_file(fetcher.client, cfg.login.cookies_file)
            if applied:
                logging.info("已加载Cookies文件")
        except Exception as e:
            logging.warning("Cookies加载失败：%s", e)

    if cfg.login and cfg.login.enabled:
        try:
            strategy = build_login_strategy(fetcher.client, cfg.login.type)
            if cfg.login.type == "api":
                ok = await strategy.login(
                    login_url=cfg.login.login_url or "",
                    payload=cfg.login.payload,
                    headers=cfg.login.headers,
                )
            elif cfg.login.type == "wechat_qr":
                ok = await strategy.login(
                    login_url=cfg.login.login_url or "https://mp.weixin.qq.com/mp/profile_ext?action=home",
                    save_cookies_file=cfg.login.save_cookies_file or (cfg.login.cookies_file or ""),
                )
            else:
                ok = await strategy.login(
                    login_url=cfg.login.login_url or "",
                    username=cfg.login.username or "",
                    password=cfg.login.password or "",
                    payload=cfg.login.payload,
                    headers=cfg.login.headers,
                )
            if not ok:
                logging.warning("登录未成功，后续请求可能无登录态：%s", cfg.login.login_url)
            else:
                logging.info("登录成功，已建立会话")
        except Exception as e:
            logging.error("登录流程异常：%s", e)

    # 加载插件模块列表
    plugins: List[object] = []
    for mod in cfg.plugins:
        try:
            m = importlib.import_module(mod)
            # 支持模块内暴露 Plugin 类或插件实例列表
            if hasattr(m, "Plugin"):
                plugins.append(getattr(m, "Plugin")())
            elif hasattr(m, "plugins"):
                plugins.extend(getattr(m, "plugins"))
            else:
                # 兼容 ExamplePlugin 命名
                for name in dir(m):
                    if name.endswith("Plugin"):
                        plugins.append(getattr(m, name)())
        except Exception as e:
            logging.error("加载插件失败 %s: %s", mod, e)

    scheduler = Scheduler(cfg.seeds, cfg.allowed_domains)

    async def worker(url: str) -> None:
        status, html = await fetcher.fetch(url)
        storage.record_page(url, status)
        if status != 200:
            return
        if getattr(cfg, "save_page_html", True):
            storage.save_html(url, html)

        # 插件处理：根据should_handle决定是否解析与入库
        discovered: List[str] = []
        for p in plugins:
            try:
                if hasattr(p, "should_handle") and p.should_handle(url):
                    # 注入上下文：fetcher、storage、完整配置（含插件参数）
                    new_links = p.handle(
                        url,
                        html,
                        {
                            "storage": storage,
                            "fetcher": fetcher,
                            "config": cfg,
                            "plugin_params": getattr(cfg, "plugin_params", {}),
                        },
                    ) or []
                    discovered.extend(new_links)
            except Exception as e:
                logging.error("插件处理失败 %s on %s: %s", p.__class__.__name__, url, e)

        # 基础链接提取（仅作示例）：
        # 如配置禁用，则不进行全局提取，避免语言切换与分页链接扩散
        if not getattr(cfg, "disable_global_link_extraction", False):
            for link in extract_links(html):
                # 轻量过滤：丢弃包含分页参数的链接（?page=），常见于搜索结果的分页
                # 说明：仅作为安全网，精准的链接选择应在插件中实现。
                try:
                    import urllib.parse as _up
                    q = _up.urlparse(link).query
                    if "page=" in q:
                        continue
                except Exception:
                    pass
                discovered.append(link)

        # 链接入队
        for link in discovered:
            try:
                scheduler.enqueue(link)
            except Exception:
                pass

    try:
        await scheduler.run(worker, cfg.max_concurrency)
    finally:
        await fetcher.close()


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="通用爬虫CLI")
    ap.add_argument("--config", required=True, help="配置文件路径（JSON）")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.config))
