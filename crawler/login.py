"""
登录策略模块

职责：
- 提供多种登录方式：表单登录、API Token 登录
    - 表单登录：在 login.payload 提供必要字段（如 csrf ），代码默认补充 username/password
    - API登录： login.payload 返回含 token 或 access_token 时，自动加 Authorization
    - 验证码：保留 captcha_solver_hook 字段用于接入外部服务（需自行实现回调）
- 管理会话Cookie，支持登录状态检测与续期
- 预留验证码处理Hook（需用户实现具体服务调用）
"""

from __future__ import annotations

import asyncio
import json
import os
import httpx
from typing import Dict, Optional


class BaseLoginStrategy:
    """登录策略基类，定义通用接口。"""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def login(self, **kwargs) -> bool:
        raise NotImplementedError


class FormLoginStrategy(BaseLoginStrategy):
    """
    表单登录：
    - 支持附加 headers
    - 支持 payload 自定义（例如包含 CSRF token）
    - 登录成功后，Cookies 保持在 client 内
    """

    async def login(self, login_url: str, username: str, password: str, payload: Dict[str, str], headers: Dict[str, str]) -> bool:
        data = dict(payload or {})
        # 常见字段名（可覆盖）
        if "username" not in data:
            data["username"] = username
        if "password" not in data:
            data["password"] = password

        try:
            r = await self.client.post(login_url, data=data, headers=headers or {})
            ok = r.status_code < 400
            return ok
        except Exception:
            return False


class APILoginStrategy(BaseLoginStrategy):
    """
    API Token 登录：
    - 登录接口返回 Token，后续请求设置到 Authorization 头或指定头字段
    """

    async def login(self, login_url: str, payload: Dict[str, str], headers: Dict[str, str]) -> bool:
        try:
            r = await self.client.post(login_url, json=payload or {}, headers=headers or {})
            if r.status_code >= 400:
                return False
            data = r.json()
            token = data.get("token") or data.get("access_token")
            if token:
                self.client.headers["Authorization"] = f"Bearer {token}"
                return True
            return False
        except Exception:
            return False


class WeChatQRLoginStrategy(BaseLoginStrategy):
    async def login(self, login_url: str, save_cookies_file: str) -> bool:
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return False
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(login_url or "https://mp.weixin.qq.com", wait_until="networkidle")
                ok = False
                for _ in range(120):
                    await asyncio.sleep(1)
                    ck = await context.cookies()
                    names = {c.get("name") for c in ck}
                    domains = {c.get("domain") for c in ck}
                    if any("mp.weixin.qq.com" in (d or "") for d in domains) and ("wxuin" in names or "pass_ticket" in names):
                        jar = httpx.Cookies()
                        for c in ck:
                            jar.set(c.get("name"), c.get("value"), domain=c.get("domain"), path=c.get("path"))
                        self.client.cookies = jar
                        ok = True
                        if save_cookies_file:
                            try:
                                d = os.path.dirname(save_cookies_file)
                                if d:
                                    os.makedirs(d, exist_ok=True)
                                with open(save_cookies_file, "w", encoding="utf-8") as f:
                                    json.dump(ck, f, ensure_ascii=False)
                            except Exception:
                                pass
                        break
                await browser.close()
                return ok
        except Exception:
            return False


async def apply_cookies_file(client: httpx.AsyncClient, path: str) -> bool:
    try:
        if not path:
            return False
        if not os.path.exists(path):
            return False
        jar = httpx.Cookies()
        if path.lower().endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("cookies") or []
            if isinstance(data, list):
                for c in data:
                    jar.set(c.get("name"), c.get("value"), domain=c.get("domain"), path=c.get("path"))
        else:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        domain = parts[0]
                        name = parts[5]
                        value = parts[6]
                        pathv = parts[2] if len(parts) > 2 else "/"
                        jar.set(name, value, domain=domain, path=pathv)
        client.cookies = jar
        return True
    except Exception:
        return False


def build_login_strategy(client: httpx.AsyncClient, login_type: str) -> BaseLoginStrategy:
    if login_type == "api":
        return APILoginStrategy(client)
    if login_type == "wechat_qr":
        return WeChatQRLoginStrategy(client)
    return FormLoginStrategy(client)
