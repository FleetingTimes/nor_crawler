from __future__ import annotations
"""
页面导出插件（PageExportPlugin）

功能与输出：
- 按 URL 导出多种格式：PDF（高保真打印）、MHTML（整页归档）、单文件 HTML（SingleFile）、Markdown（正文抽取）；
- 统一输出在 storage.output_dir 下的子目录：pdf/、archive/、fullpage/、md/；并记录导出日志 export_log.tsv；
- 针对微信文章页，支持“已删除”提示识别，遇到删除内容时跳过导出。

渲染与兼容：
- 基于 Playwright 的 Chromium headless 渲染，支持：UA/Headers/Cookies/locale/timezone 注入；
- 自动滚动到底部（懒加载）、到达条件 wait_until 与预等待 pre_wait_ms；
- 打印媒体下的白屏处理：移除站点打印样式、强制显示正文容器、注入自定义打印样式后再生成 PDF；
- MHTML 通过 CDP 的 Page.captureSnapshot 生成（二进制写入），避免打开空白；
- 单文件 HTML 通过 SingleFile 脚本将资源内嵌，脚本不可用时回退写入 page.content()；

命名与文件名：
- 采用 host 与页面 title 生成易读的文件名，并追加 URL 的 SHA1 确保唯一；
- 过长或包含特殊字符的部分会被 slug 化（替换为安全字符并截断）。
"""

import os
import re
import hashlib
import threading
import time
from typing import Dict, Any, List
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from crawler.utils import pick_user_agent


class PageExportPlugin:
    """页面导出插件主体。

    处理范围：
    - 所有以 http(s) 开头的 URL（should_handle 简单放行，具体格式由 handle 控制）

    设计要点：
    - 将导出控制项集中在 plugin_params 下（pdf/markdown/archive/fullpage）；
    - 对打印白屏常见场景做内置兼容（移除站点打印样式/注入自定义打印样式/强制显示容器）；
    - 对慢渲染/懒加载页面提供滚动与等待参数；
    - 对受限站点提供 UA/Headers/Cookies/locale/timezone 注入入口。
    """
    def should_handle(self, url: str) -> bool:
        p = urlparse(url)
        return (p.scheme or "").startswith("http")

    def _is_deleted(self, html: str) -> bool:
        """识别微信文章页的“已删除”提示。

        只在 `body#activity-detail` 结构下检查 `.weui-msg__title.warn` 的文案，包含“该内容已被发布者删除”则视为删除。
        """
        soup = BeautifulSoup(html, "html.parser")
        body = soup.select_one("body#activity-detail")
        if not body:
            return False
        el = soup.select_one(".weui-msg .weui-msg__text-area .weui-msg__title.warn")
        txt = el.get_text(strip=True) if el else ""
        return bool(txt and ("该内容已被发布者删除" in txt))

    def _save_pdf_playwright(self, url: str, out_path: str, timeout_sec: int, log_path: str, wait_until: str, pre_wait_ms: int, scroll_to_bottom: bool, scroll_step_px: int, scroll_pause_ms: int, scroll_max_ms: int, user_agent: str, extra_headers: Dict[str, str], cookies: List[Dict[str, Any]], locale: str, timezone_id: str, print_pre_wait_ms: int, prefer_css_page_size: bool) -> bool:
        """使用 Playwright 生成 PDF。

        关键流程：
        1. 启动 Chromium headless，并创建上下文（UA/语言/时区）与注入 Headers/Cookies；
        2. page.goto(wait_until)，到达后按需预等待 pre_wait_ms；
        3. 自动滚动到底部（step/pause/limit）以触发懒加载；
        4. 移除站点打印样式、强制显示正文容器、注入自定义打印样式；
        5. 切换到打印媒体 emulate_media('print') 并等待字体就绪与 print_pre_wait_ms；
        6. page.pdf(format='A4', print_background=True, prefer_css_page_size) 生成文件；
        7. 写入导出日志（ok/fail + 错误信息）。
        """
        ok = False
        err: str = ""
        def run_pdf():
            import asyncio
            try:
                from playwright.async_api import async_playwright
            except Exception as e:
                nonlocal err
                err = f"playwright_import_error: {e}"
                return
            async def go():
                nonlocal err
                try:
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        context = await browser.new_context(
                            user_agent=user_agent or None,
                            locale=locale or None,
                            timezone_id=timezone_id or None,
                        )
                        # 注入额外请求头与 Cookies（防风控/复用登录态）
                        if extra_headers:
                            try:
                                await context.set_extra_http_headers(extra_headers)
                            except Exception:
                                pass
                        if cookies:
                            try:
                                await context.add_cookies(cookies)
                            except Exception:
                                pass
                        page = await context.new_page()
                        # 页面到达条件：默认 networkidle，兼容长链路资源
                        wu = wait_until if wait_until in ("load", "domcontentloaded", "networkidle") else "networkidle"
                        ref = extra_headers.get("Referer") if extra_headers else None
                        try:
                            await page.goto(url, wait_until=wu, referer=ref)
                        except Exception:
                            await page.goto(url, wait_until=wu)
                        # 预等待：给首屏/脚本留出时间
                        if pre_wait_ms and pre_wait_ms > 0:
                            await page.wait_for_timeout(pre_wait_ms)
                        # 自动滚动到底部：触发懒加载与瀑布流内容
                        if scroll_to_bottom:
                            step = max(100, int(scroll_step_px or 800))
                            pause = max(50, int(scroll_pause_ms or 300))
                            limit = max(1000, int(scroll_max_ms or 60000))
                            start = time.time()
                            try:
                                prev_height = await page.evaluate("document.body.scrollHeight")
                            except Exception:
                                prev_height = 0
                            while (time.time() - start) * 1000 < limit:
                                try:
                                    await page.evaluate("window.scrollBy(0, arguments[0])", step)
                                except Exception:
                                    break
                                await page.wait_for_timeout(pause)
                                try:
                                    new_height = await page.evaluate("document.body.scrollHeight")
                                except Exception:
                                    break
                                if new_height <= prev_height:
                                    break
                                prev_height = new_height
                        # 打印兼容：移除站点打印样式与强制显示正文容器
                        try:
                            if extra_headers.get("__disable_page_print_css__") == "1":
                                await page.evaluate('document.querySelectorAll("style[media=\'print\'], link[rel=\'stylesheet\'][media=\'print\']").forEach(el => el.remove())')
                        except Exception:
                            pass
                        try:
                            sels = (extra_headers.get("__force_show_selectors__") or "").split(",")
                            for sel in [s.strip() for s in sels if s.strip()]:
                                await page.evaluate("(s)=>{var el=document.querySelector(s); if(el){el.style.display='block'; el.style.visibility='visible'; el.style.opacity='1'; el.style.position='static'; el.style.transform='none';}}", sel)
                        except Exception:
                            pass
                        # 可选：注入打印样式，避免导出纯白
                        try:
                            if extra_headers.get("__inject_print_css_flag__") == "1":
                                css = extra_headers.get("__print_css__") or ""
                                if css:
                                    await page.add_style_tag(content=css)
                        except Exception:
                            pass
                        # 为了让 @media print 中的样式生效，这里切换到 print 媒体
                        # 某些站点在打印媒体下隐藏正文或使用不同样式，注入的打印样式将进行覆盖
                        await page.emulate_media(media="print")
                        # 字体与样式就绪再导出，减少缺字与样式跳变
                        try:
                            await page.evaluate("document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()")
                        except Exception:
                            pass
                        if print_pre_wait_ms and print_pre_wait_ms > 0:
                            await page.wait_for_timeout(print_pre_wait_ms)
                        await page.pdf(path=out_path, format="A4", print_background=True, prefer_css_page_size=prefer_css_page_size)
                        await browser.close()
                except Exception as e:
                    err = f"playwright_run_error: {e}"
            try:
                asyncio.run(go())
            except Exception as e:
                err = f"asyncio_run_error: {e}"
        t = threading.Thread(target=run_pdf)
        t.start()
        t.join(timeout_sec)
        ok = os.path.exists(out_path)
        # 记录导出日志
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{url}\t{'ok' if ok else 'fail'}\t{err}\n")
        except Exception:
            pass
        return ok

    def _save_mhtml_playwright(self, url: str, out_path: str, timeout_sec: int, log_path: str, wait_until: str, pre_wait_ms: int, scroll_to_bottom: bool, scroll_step_px: int, scroll_pause_ms: int, scroll_max_ms: int, user_agent: str, extra_headers: Dict[str, str], cookies: List[Dict[str, Any]], locale: str, timezone_id: str) -> bool:
        """使用 CDP 生成 MHTML 单文件归档。

        说明：
        - 通过 `Page.captureSnapshot` 获取 MHTML；优先二进制写入，兼容不同查看器；
        - 同样执行滚动与等待，确保页面资源充分加载。
        """
        ok = False
        err: str = ""
        def run_mhtml():
            import asyncio
            try:
                from playwright.async_api import async_playwright
            except Exception as e:
                nonlocal err
                err = f"playwright_import_error: {e}"
                return
            async def go():
                nonlocal err
                try:
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        context = await browser.new_context(
                            user_agent=user_agent or None,
                            locale=locale or None,
                            timezone_id=timezone_id or None,
                        )
                        if extra_headers:
                            try:
                                await context.set_extra_http_headers(extra_headers)
                            except Exception:
                                pass
                        if cookies:
                            try:
                                await context.add_cookies(cookies)
                            except Exception:
                                pass
                        page = await context.new_page()
                        wu = wait_until if wait_until in ("load", "domcontentloaded", "networkidle") else "networkidle"
                        ref = extra_headers.get("Referer") if extra_headers else None
                        try:
                            await page.goto(url, wait_until=wu, referer=ref)
                        except Exception:
                            await page.goto(url, wait_until=wu)
                        if pre_wait_ms and pre_wait_ms > 0:
                            await page.wait_for_timeout(pre_wait_ms)
                        if scroll_to_bottom:
                            step = max(100, int(scroll_step_px or 800))
                            pause = max(50, int(scroll_pause_ms or 300))
                            limit = max(1000, int(scroll_max_ms or 60000))
                            start = time.time()
                            try:
                                prev_height = await page.evaluate("document.body.scrollHeight")
                            except Exception:
                                prev_height = 0
                            while (time.time() - start) * 1000 < limit:
                                try:
                                    await page.evaluate("window.scrollBy(0, arguments[0])", step)
                                except Exception:
                                    break
                                await page.wait_for_timeout(pause)
                                try:
                                    new_height = await page.evaluate("document.body.scrollHeight")
                                except Exception:
                                    break
                                if new_height <= prev_height:
                                    break
                                prev_height = new_height
                        try:
                            session = await context.new_cdp_session(page)
                            await session.send("Page.enable")
                            snap = await session.send("Page.captureSnapshot", {"format": "mhtml"})
                            data = snap or ""
                            if isinstance(data, dict):
                                data = data.get("data") or ""
                            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                            try:
                                with open(out_path, "wb") as f:
                                    f.write((data or "").encode("utf-8"))
                            except Exception:
                                with open(out_path, "w", encoding="utf-8") as f:
                                    f.write(data or "")
                        except Exception as e:
                            err = f"mhtml_error: {e}"
                        try:
                            await browser.close()
                        except Exception:
                            pass
                except Exception as e:
                    err = f"playwright_run_error: {e}"
            try:
                asyncio.run(go())
            except Exception as e:
                err = f"asyncio_run_error: {e}"
        t = threading.Thread(target=run_mhtml)
        t.start()
        t.join(timeout_sec)
        ok = os.path.exists(out_path)
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{url}\t{'ok' if ok else 'fail'}\t{err}\n")
        except Exception:
            pass
        return ok

    def _save_singlefile_html_playwright(self, url: str, out_path: str, timeout_sec: int, log_path: str, wait_until: str, pre_wait_ms: int, scroll_to_bottom: bool, scroll_step_px: int, scroll_pause_ms: int, scroll_max_ms: int, user_agent: str, extra_headers: Dict[str, str], cookies: List[Dict[str, Any]], locale: str, timezone_id: str, sf_script_content: str | None = None) -> bool:
        """生成单文件 HTML（SingleFile 内嵌资源）。

        行为：
        - 注入本地 SingleFile 脚本（失败则写入 page.content() 兜底）；
        - 通过 singlefile.getProcessedHTML(opt) 获取内嵌资源的完整 HTML；
        - opt 默认保留样式/隐藏元素并压缩 CSS，提升还原度与体积平衡。
        """
        ok = False
        err: str = ""
        def run_sf():
            import asyncio
            try:
                from playwright.async_api import async_playwright
            except Exception as e:
                nonlocal err
                err = f"playwright_import_error: {e}"
                return
            async def go():
                nonlocal err
                try:
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        context = await browser.new_context(
                            user_agent=user_agent or None,
                            locale=locale or None,
                            timezone_id=timezone_id or None,
                        )
                        if extra_headers:
                            try:
                                await context.set_extra_http_headers(extra_headers)
                            except Exception:
                                pass
                        if cookies:
                            try:
                                await context.add_cookies(cookies)
                            except Exception:
                                pass
                        page = await context.new_page()
                        wu = wait_until if wait_until in ("load", "domcontentloaded", "networkidle") else "networkidle"
                        ref = extra_headers.get("Referer") if extra_headers else None
                        try:
                            await page.goto(url, wait_until=wu, referer=ref)
                        except Exception:
                            await page.goto(url, wait_until=wu)
                        if pre_wait_ms and pre_wait_ms > 0:
                            await page.wait_for_timeout(pre_wait_ms)
                        if scroll_to_bottom:
                            step = max(100, int(scroll_step_px or 800))
                            pause = max(50, int(scroll_pause_ms or 300))
                            limit = max(1000, int(scroll_max_ms or 60000))
                            start = time.time()
                            try:
                                prev_height = await page.evaluate("document.body.scrollHeight")
                            except Exception:
                                prev_height = 0
                            while (time.time() - start) * 1000 < limit:
                                try:
                                    await page.evaluate("window.scrollBy(0, arguments[0])", step)
                                except Exception:
                                    break
                                await page.wait_for_timeout(pause)
                                try:
                                    new_height = await page.evaluate("document.body.scrollHeight")
                                except Exception:
                                    break
                                if new_height <= prev_height:
                                    break
                                prev_height = new_height
                        html_str = ""
                        try:
                            if sf_script_content:
                                await page.add_script_tag(content=sf_script_content)
                                html_str = await page.evaluate("(async ()=>{ const opt = { removeUnusedStyles:false, compressCSS:true, removeHiddenElements:false, blockMixedContent:false }; const r = await singlefile.getProcessedHTML(opt); return r; })()")
                            else:
                                raise Exception("singlefile_no_script")
                        except Exception as e:
                            err = f"singlefile_error: {e}"
                            try:
                                html_str = await page.content()
                            except Exception:
                                try:
                                    html_str = await page.evaluate("document.documentElement.outerHTML")
                                except Exception:
                                    html_str = ""
                        try:
                            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                            with open(out_path, "w", encoding="utf-8") as f:
                                f.write(html_str or "")
                        except Exception:
                            pass
                        try:
                            await browser.close()
                        except Exception:
                            pass
                except Exception as e:
                    err = f"playwright_run_error: {e}"
            try:
                asyncio.run(go())
            except Exception as e:
                err = f"asyncio_run_error: {e}"
        t = threading.Thread(target=run_sf)
        t.start()
        t.join(timeout_sec)
        ok = os.path.exists(out_path)
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{url}\t{'ok' if ok else 'fail'}\t{err}\n")
        except Exception:
            pass
        return ok

    def _select_main_container(self, soup: BeautifulSoup, selectors: List[str]) -> Any:
        """
        选择主要正文容器：按选择器优先级返回第一个命中的元素；若未命中则回退到 `body`。
        """
        for sel in selectors or []:
            try:
                el = soup.select_one(sel)
                if el:
                    return el
            except Exception:
                continue
        return soup.body or soup

    def _html_to_markdown(self, el: Any) -> str:
        """
        将 HTML 元素转换为 Markdown 文本：
        - 支持标题、段落、链接、图片、列表、代码块、内联代码、强调、引用、分隔线等常见标签
        - 保留纯文本并进行合理的换行
        """
        from bs4 import NavigableString, Tag
        def text_of(node):
            try:
                return node.get_text(strip=True)
            except Exception:
                return ""
        def walk(node) -> str:
            if node is None:
                return ""
            if isinstance(node, NavigableString):
                return str(node)
            if not isinstance(node, Tag):
                return ""
            name = node.name.lower()
            if name in ("script", "style", "noscript"):
                return ""
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(name[1])
                return "{} {}\n\n".format("#" * max(1, min(6, level)), text_of(node))
            if name in ("p", "div"):
                inner = "".join(walk(child) for child in node.children)
                return (inner.strip() + "\n\n") if inner.strip() else ""
            if name == "br":
                return "\n"
            if name in ("strong", "b"):
                inner = "".join(walk(child) for child in node.children)
                return f"**{inner}**"
            if name in ("em", "i"):
                inner = "".join(walk(child) for child in node.children)
                return f"*{inner}*"
            if name == "code":
                inner = "".join(walk(child) for child in node.children)
                # 若父节点为 pre，则由 pre 负责生成代码块
                return f"`{inner}`" if node.parent and node.parent.name != "pre" else inner
            if name == "pre":
                code_el = node.find("code")
                lang = ""
                if code_el:
                    cls = " ".join(code_el.get("class", []) or [])
                    m = re.search(r"language-([a-zA-Z0-9_+-]+)", cls or "")
                    if m:
                        lang = m.group(1)
                code_text = code_el.get_text() if code_el else node.get_text()
                return f"```{lang}\n{code_text}\n```\n\n"
            if name == "a":
                href = (node.get("href") or "").strip()
                inner = text_of(node)
                return f"[{inner}]({href})" if href else inner
            if name == "img":
                src = (node.get("src") or "").strip()
                alt = (node.get("alt") or "").strip()
                title = (node.get("title") or "").strip()
                label = alt or title or "image"
                return f"![{label}]({src})\n\n" if src else ""
            if name in ("ul", "ol"):
                buf = []
                ordered = (name == "ol")
                idx = 1
                for li in node.find_all("li", recursive=False):
                    line = "".join(walk(child) for child in li.children).strip()
                    if not line:
                        continue
                    prefix = f"{idx}. " if ordered else "- "
                    buf.append(prefix + line)
                    idx += 1
                return "\n".join(buf) + ("\n\n" if buf else "")
            if name == "blockquote":
                inner = "".join(walk(child) for child in node.children)
                lines = [l for l in inner.splitlines() if l.strip()]
                return "\n".join("> " + l for l in lines) + ("\n\n" if lines else "")
            if name == "hr":
                return "\n---\n\n"
            # 其他标签：递归其子节点
            return "".join(walk(child) for child in node.children)
        return walk(el)


    def handle(self, url: str, html: str, context: Dict[str, Any]) -> List[str]:
        """统一入口：按配置导出 PDF/MHTML/单文件 HTML/Markdown。

        流程：
        1. 检查“已删除”提示（微信文章页）并跳过；
        2. 解析标题与主机名，生成安全/易读的文件名；
        3. 读取导出控制参数（pdf/markdown/archive/fullpage）；
        4. 构造 UA/Headers/Cookies/locale/timezone；
        5. 按开关生成对应格式，并写入 `export_log.tsv`；
        6. 返回空列表（此插件不做链接发现）。
        """
        if self._is_deleted(html):
            return []
        storage = context.get("storage")
        all_params = context.get("plugin_params", {})
        params = all_params.get("pdf", {})
        md_params = all_params.get("markdown", {})
        arch_params = all_params.get("archive", {})
        out_root = storage.output_dir
        pdf_dir = os.path.join(out_root, "pdf")
        os.makedirs(pdf_dir, exist_ok=True)
        # filename from title/host
        soup = BeautifulSoup(html or "", "html.parser")
        title = ""
        try:
            mt = soup.select_one('meta[property="og:title"]') or soup.select_one('meta[name="twitter:title"]')
            if mt:
                title = (mt.get("content") or "").strip()
            if not title:
                tt = soup.select_one("title")
                title = tt.get_text(strip=True) if tt else ""
        except Exception:
            title = ""
        host = (urlparse(url).netloc or "").strip()
        def slug(s: str) -> str:
            s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
            s = re.sub(r"\s+", "_", s)
            return (s or "-")[:80]
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        ts = time.strftime("%Y%m%d_%H%M%S")
        use_title = bool(params.get("filename_use_title", True))
        prefix_host = bool(params.get("filename_prefix_host", True))
        base = ""
        if prefix_host and host:
            base = slug(host)
        if use_title and title:
            tslug = slug(title)
            base = f"{base}_{tslug}" if base else tslug
        if not base:
            base = ts
        out_path = os.path.join(pdf_dir, f"{base}_{h}.pdf")
        arch_dir = os.path.join(out_root, "archive")
        os.makedirs(arch_dir, exist_ok=True)
        arch_path = os.path.join(arch_dir, f"{base}_{h}.mhtml")
        sf_dir = os.path.join(out_root, "fullpage")
        os.makedirs(sf_dir, exist_ok=True)
        sf_path = os.path.join(sf_dir, f"{base}_{h}.html")
        timeout_sec = int(params.get("timeout_sec", 180) or 180)
        wait_until = str(params.get("wait_until", "networkidle") or "networkidle")
        pre_wait_ms = int(params.get("pre_wait_ms", 0) or 0)
        scroll_to_bottom = bool(params.get("scroll_to_bottom", True))
        scroll_step_px = int(params.get("scroll_step_px", 800) or 800)
        scroll_pause_ms = int(params.get("scroll_pause_ms", 300) or 300)
        scroll_max_ms = int(params.get("scroll_max_ms", 60000) or 60000)
        # user agent & headers & cookies
        cfg = context.get("config")
        ua_cfg_pool = getattr(cfg, "user_agents", []) if cfg else []
        ua = str(params.get("user_agent", "") or "")
        if not ua:
            try:
                ua = pick_user_agent(ua_cfg_pool)
            except Exception:
                ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36"
        extra_headers = dict(params.get("extra_headers", {}))
        inject_print_css = bool(params.get("inject_print_css", False))
        print_css = str(params.get("print_css", "") or "")
        if inject_print_css and print_css:
            extra_headers["__inject_print_css_flag__"] = "1"
            extra_headers["__print_css__"] = print_css
        if bool(params.get("disable_page_print_css", True)):
            extra_headers["__disable_page_print_css__"] = "1"
        force_selectors = params.get("force_show_selectors", []) or []
        if isinstance(force_selectors, list) and force_selectors:
            extra_headers["__force_show_selectors__"] = ",".join([str(x) for x in force_selectors])
        if "Accept-Language" not in extra_headers:
            extra_headers["Accept-Language"] = "zh-CN,zh;q=0.9"
        cookies_file = str(params.get("cookies_file", "") or "")
        locale = str(params.get("locale", "zh-CN") or "zh-CN")
        timezone_id = str(params.get("timezone_id", "Asia/Shanghai") or "Asia/Shanghai")
        def _load_cookies_file(path: str) -> List[Dict[str, Any]]:
            items: List[Dict[str, Any]] = []
            try:
                if not path:
                    return items
                if not os.path.exists(path):
                    return items
                if path.lower().endswith(".json"):
                    import json as _json
                    with open(path, "r", encoding="utf-8") as f:
                        data = _json.load(f)
                    if isinstance(data, dict):
                        data = data.get("cookies") or []
                    for c in data or []:
                        items.append({
                            "name": c.get("name"),
                            "value": c.get("value"),
                            "domain": c.get("domain"),
                            "path": c.get("path") or "/",
                        })
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            parts = line.split("\t")
                            if len(parts) >= 7:
                                items.append({
                                    "domain": parts[0],
                                    "path": parts[2] if len(parts) > 2 else "/",
                                    "name": parts[5],
                                    "value": parts[6],
                                })
            except Exception:
                pass
            return items
        cookies = _load_cookies_file(cookies_file)
        log_path = os.path.join(out_root, "export_log.tsv")
        print_pre_wait_ms = int(params.get("print_pre_wait_ms", 3000) or 0)
        prefer_css_page_size = bool(params.get("prefer_css_page_size", True))
        pdf_enabled = bool(params.get("enabled", False))
        ok = True
        if pdf_enabled:
            ok = self._save_pdf_playwright(url, out_path, timeout_sec, log_path, wait_until, pre_wait_ms, scroll_to_bottom, scroll_step_px, scroll_pause_ms, scroll_max_ms, ua, extra_headers, cookies, locale, timezone_id, print_pre_wait_ms, prefer_css_page_size)
            if not ok:
                if bool(params.get("fallback_html", True)):
                    fallback_path = os.path.join(pdf_dir, f"{base}_{h}.html")
                try:
                    if bool(params.get("fallback_html", True)):
                        with open(fallback_path, "w", encoding="utf-8") as f:
                            f.write(html or "")
                except Exception:
                    pass
        arch_enabled = bool(arch_params.get("enabled", True))
        if arch_enabled:
            arch_timeout = int(arch_params.get("timeout_sec", timeout_sec) or timeout_sec)
            arch_wait_until = str(arch_params.get("wait_until", wait_until) or wait_until)
            arch_pre_wait = int(arch_params.get("pre_wait_ms", pre_wait_ms) or pre_wait_ms)
            arch_scroll = bool(arch_params.get("scroll_to_bottom", scroll_to_bottom))
            arch_step = int(arch_params.get("scroll_step_px", scroll_step_px) or scroll_step_px)
            arch_pause = int(arch_params.get("scroll_pause_ms", scroll_pause_ms) or scroll_pause_ms)
            arch_limit = int(arch_params.get("scroll_max_ms", scroll_max_ms) or scroll_max_ms)
            self._save_mhtml_playwright(url, arch_path, arch_timeout, log_path, arch_wait_until, arch_pre_wait, arch_scroll, arch_step, arch_pause, arch_limit, ua, extra_headers, cookies, locale, timezone_id)
        sf_params = all_params.get("fullpage", {})
        if bool(sf_params.get("enabled", True)):
            sf_timeout = int(sf_params.get("timeout_sec", timeout_sec) or timeout_sec)
            sf_wait_until = str(sf_params.get("wait_until", wait_until) or wait_until)
            sf_pre_wait = int(sf_params.get("pre_wait_ms", pre_wait_ms) or pre_wait_ms)
            sf_scroll = bool(sf_params.get("scroll_to_bottom", scroll_to_bottom))
            sf_step = int(sf_params.get("scroll_step_px", scroll_step_px) or scroll_step_px)
            sf_pause = int(sf_params.get("scroll_pause_ms", scroll_pause_ms) or scroll_pause_ms)
            sf_limit = int(sf_params.get("scroll_max_ms", scroll_max_ms) or scroll_max_ms)
            sf_script = None
            sf_script = None
            try:
                local_path = str(sf_params.get("singlefile_script_path", "") or "")
                if local_path and os.path.exists(local_path):
                    with open(local_path, "r", encoding="utf-8") as f:
                        sf_script = f.read()
            except Exception:
                pass
            self._save_singlefile_html_playwright(url, sf_path, sf_timeout, log_path, sf_wait_until, sf_pre_wait, sf_scroll, sf_step, sf_pause, sf_limit, ua, extra_headers, cookies, locale, timezone_id, sf_script)
        # Markdown 导出（可选）
        try:
            if bool(md_params.get("enabled", True)):
                md_dir = os.path.join(out_root, "md")
                os.makedirs(md_dir, exist_ok=True)
                md_base = ""
                if bool(md_params.get("filename_prefix_host", True)) and host:
                    md_base = slug(host)
                if bool(md_params.get("filename_use_title", True)) and title:
                    tslug = slug(title)
                    md_base = f"{md_base}_{tslug}" if md_base else tslug
                if not md_base:
                    md_base = ts
                md_path = os.path.join(md_dir, f"{md_base}_{h}.md")
                selectors = list(md_params.get("selectors", [
                    "#cnblogs_post_body", ".postBody", ".post", "#main", "#content", "article", ".entry-content"
                ]) or [])
                container = self._select_main_container(soup, selectors)
                body_md = self._html_to_markdown(container)
                parts = []
                if bool(md_params.get("include_title", True)) and title:
                    parts.append(f"# {title}\n")
                parts.append(body_md)
                content = "\n".join(parts).strip() + "\n"
                with open(md_path, "w", encoding="utf-8") as mf:
                    mf.write(content)
        except Exception:
            pass
        return []


Plugin = PageExportPlugin
