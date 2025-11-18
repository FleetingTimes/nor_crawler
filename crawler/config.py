"""
配置模块

职责：
- 定义配置数据结构（使用 Python 标准库 dataclasses）
- 从 JSON 文件加载配置，并进行基本校验与默认值填充

说明：
- 使用 JSON 以减少外部依赖（不使用 YAML）
- 提供较为详细的中文注释，便于阅读与维护
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class StorageConfig:
    output_dir: str = "output"
    sqlite_path: str = "crawler.db"
    # 新增：HTML页面子目录（仅影响页面HTML的保存路径，不影响JSON）
    # 例如：设置为 "pages" 时，页面会保存到 output_dir/pages 下
    html_subdir: str = ""


@dataclass
class LoginConfig:
    enabled: bool = False
    type: str = "form"  # 可选："form" 或 "api"
    login_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    payload: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    captcha_solver_hook: str = ""  # 验证码Hook标识（需在代码中实现回调映射）
    cookies_file: Optional[str] = None
    save_cookies_file: Optional[str] = None


@dataclass
class Config:
    seeds: List[str] = field(default_factory=list)
    allowed_domains: List[str] = field(default_factory=list)
    max_concurrency: int = 8
    per_domain_delay_ms: int = 800
    respect_robots_txt: bool = True
    max_retries: int = 3
    retry_backoff_initial_ms: int = 500
    retry_backoff_max_ms: int = 8000
    user_agents: List[str] = field(default_factory=list)
    proxies: List[str] = field(default_factory=list)
    login: LoginConfig = field(default_factory=LoginConfig)
    plugins: List[str] = field(default_factory=list)
    storage: StorageConfig = field(default_factory=StorageConfig)
    # 新增：插件参数映射。用于向通用插件传递规则与配置。
    # 例如 {"rule_based": { ...规则定义... }}。
    plugin_params: Dict[str, dict] = field(default_factory=dict)
    # 新增：根据关键字文件自动生成 seeds 的配置（可选）
    # 格式示例：{"file": "keywords.txt", "template": "https://site/search?keyword={kw}"}
    seeds_from_keywords: Dict[str, str] = field(default_factory=dict)
    # 新增：是否禁用全局链接提取（extract_links）。
    # 说明：默认 True 时，抓取仅停留在种子URL和插件返回的链接，避免页面内的
    # 语言跳转、分页（?page=）等被自动加入队列；对于站点专项抓取更安全。
    # 若需要全站爬取，可设置为 False。
    disable_global_link_extraction: bool = False
    save_page_html: bool = True


def load_config(path: str) -> Config:
    """
    从 JSON 文件加载配置，返回 Config 对象。

    - 进行基本的必填字段检查（如 seeds 非空）
    - 填充默认值（dataclass 默认）
    - 校验路径存在与创建输出目录
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 反序列化嵌套结构
    storage = StorageConfig(**raw.get("storage", {}))
    login = LoginConfig(**raw.get("login", {}))

    cfg = Config(
        seeds=raw.get("seeds", []),
        allowed_domains=raw.get("allowed_domains", []),
        max_concurrency=int(raw.get("max_concurrency", 8)),
        per_domain_delay_ms=int(raw.get("per_domain_delay_ms", 800)),
        respect_robots_txt=bool(raw.get("respect_robots_txt", True)),
        max_retries=int(raw.get("max_retries", 3)),
        retry_backoff_initial_ms=int(raw.get("retry_backoff_initial_ms", 500)),
        retry_backoff_max_ms=int(raw.get("retry_backoff_max_ms", 8000)),
        user_agents=raw.get("user_agents", []),
        proxies=raw.get("proxies", []),
        login=login,
        plugins=raw.get("plugins", []),
        storage=storage,
        plugin_params=raw.get("plugin_params", {}),
        seeds_from_keywords=raw.get("seeds_from_keywords", {}),
        disable_global_link_extraction=bool(raw.get("disable_global_link_extraction", False)),
        save_page_html=bool(raw.get("save_page_html", True)),
    )

    # 若提供 seeds_from_keywords，则从文件读取关键字并按模板生成 seeds
    # 模板中使用 {kw} 占位符替换为关键字文本
    if cfg.seeds_from_keywords:
        file_path = cfg.seeds_from_keywords.get("file", "")
        template = cfg.seeds_from_keywords.get("template", "")
        if file_path and template:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    kws = [line.strip() for line in f if line.strip()]
                generated = [template.replace("{kw}", kw) for kw in kws]
                # 在原 seeds 基础上追加生成的 seeds，保持用户原有配置
                cfg.seeds = (cfg.seeds or []) + generated
            except Exception as e:
                raise ValueError(f"读取关键字文件失败: {file_path} - {e}")

    # 当 seeds 为空时的处理策略：
    # - 若配置了 seeds_from_keywords，但关键字文件为空或全部已处理导致 seeds 为空：
    #   允许通过由 CLI 层进行优雅退出（打印提示信息并终止任务），避免在此抛出异常。
    # - 若既没有 seeds 也没有 seeds_from_keywords（即没有任何入口可用于抓取）：
    #   仍然抛出异常提醒用户补充配置。
    if not cfg.seeds and not cfg.seeds_from_keywords:
        raise ValueError("seeds 不能为空，请在配置文件或 seeds_from_keywords 中提供至少一个初始URL")

    # 输出目录预创建，避免后续存储失败
    os.makedirs(cfg.storage.output_dir, exist_ok=True)

    return cfg
