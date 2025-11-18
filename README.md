# 通用网页爬虫工具（nor_crawler）

一个可配置、可扩展、抗反爬、支持登录与高并发的通用爬虫框架。默认使用 `httpx` 做异步请求，提供针对常见反爬手段的缓解策略（UA/代理轮换、节流与限速、退避重试、robots.txt 尊重、指纹随机化等），并提供插件机制以适配不同站点的解析逻辑。可选集成 Playwright（如安装）以渲染强依赖JS的页面。

## 特性总览
- 配置驱动：通过 `config.json` 定义站点、并发、代理、登录、抓取范围等
- 抗反爬策略：
  - `robots.txt` 检查与尊重
  - 403/429/5xx 智能退避重试（指数退避+抖动）
  - User-Agent 随机化，支持自定义UA池
  - 代理池轮换、失败降级与熔断
  - 站点级并发与速率限制（Domain级限速/队列）
  - Cookie/Session 维持，支持登录与自动续期
  - 指纹扰动：请求头随机化、Accept-Language、时延抖动
- 登录支持：
  - 表单登录（POST + CSRF处理）
  - API Token登录（Bearer/自定义头）
  - 外部验证码服务回调接口（预留Hook）
- 解析插件：
  - 按域或URL模式路由到插件
  - 使用 `BeautifulSoup` 进行CSS选择器解析（也可扩展 XPath/lxml）
- 存储与去重：
  - SQLite 记录已访问URL与状态
  - 文件系统存储 HTML 内容与解析结果（JSON）
  - 简易Frontier与去重
- 稳定性与性能：
  - 并发调度 + 站点级限速，避免触发封禁
  - 清晰日志与错误分级，便于定位问题
  - 可插拔的重试/熔断/代理策略

## 环境要求
- Python 3.10+
- Windows / macOS / Linux 均可
- 如需渲染大量JS页面，建议安装 Playwright（可选）

## 安装依赖
```bash
pip install -r requirements.txt
# 可选：如需JS渲染
# pip install playwright
# playwright install
```

## 快速开始
1. 编辑 `config.example.json` 并保存为 `config.json`
2. 运行
```bash
python -m crawler.cli --config config.json
```

## CLI 参数
- `--config <path>`：指定配置文件路径（JSON）。示例：
```bash
python -m crawler.cli --config config.json
```

## 两种抓取方式

### 1) 关键字模式（按关键字或关键字文件抓取）
- 启用插件：在 `config.json` 的 `plugins` 中加入 `plugins.keyword_plugin`
- 配置参数：在 `plugin_params.keyword` 中提供关键字与匹配策略
- 适用场景：跨页面筛选包含某些主题词的内容，或在站点内仅收集与关键词相关的页面

示例：
```json
{
  "seeds": ["https://example.com/"],
  "allowed_domains": ["example.com"],
  "plugins": ["plugins.keyword_plugin"],
  "plugin_params": {
    "keyword": {
      "keywords": ["Python", "爬虫"],
      "keywords_file": "plugins/rules/keywords.txt",
      "match": {
        "in_url": true,
        "in_title": true,
        "in_body": true,
        "case_sensitive": false
      },
      "discover": {
        "only_url_contains_keyword": false,
        "selectors": ["a[href]"],
        "attr": "href"
      }
    }
  }
}
```

使用建议：
- 先用 `in_url` / `in_title` 进行粗筛；必要时再开启 `in_body`
- 若抓取范围过大，可将 `discover.only_url_contains_keyword` 设为 `true`
- 关键字较多时使用文件（每行一个），便于复用与维护

### 2) 站点模式（直接按站点结构抓取）
- 启用插件：在 `plugins` 中加入 `plugins.rule_based_plugin`
- 编写规则：在 `plugin_params.rule_based` 定义域范围、页面匹配、字段提取、分页与详情链接发现、是否使用JS渲染等
- 参考示例：`plugins/rules/rule_based.example.json`

## Playwright 使用说明

- 作用
  - JS 渲染：当页面内容由前端动态生成时，使用浏览器渲染后再解析（`crawler/fetcher.py:194` 提供 `render_js(url)`）
  - 扫码登录：通过浏览器扫码建立登录态并保存 Cookies（`crawler/login.py:74` 策略与 `crawler/login.py:81` 实现）

- 安装
  - `pip install playwright`
  - `python -m playwright install`

- 在框架中的位置
  - 抓取层：可选渲染函数 `render_js(url)`，插件在解析前按需调用（如 `wechat_*` 插件遇到动态页面）
  - 登录层：`login.type="wechat_qr"` 触发扫码登录；登录成功后自动注入到 `httpx.AsyncClient`，并可保存到文件

- 配置示例
  - 扫码登录：
    ```json
    {
      "login": {
        "enabled": true,
        "type": "wechat_qr",
        "login_url": "https://mp.weixin.qq.com/mp/profile_ext?action=home",
        "save_cookies_file": "secrets/wechat_cookies.json"
      }
    }
    ```
  - Cookies 注入：
    ```json
    {
      "login": {
        "enabled": false,
        "cookies_file": "secrets/wechat_cookies.json"
      }
    }
    ```

- Cookies 文件格式
  - JSON 列表：`[{"name":"pass_ticket","value":"...","domain":".mp.weixin.qq.com","path":"/"}]`
  - Netscape 文本：`domain\tflag\tpath\tsecure\texpires\tname\tvalue`
  - 加载入口：`crawler/cli.py:63`（运行时自动注入）

- 何时使用渲染
  - 主页不包含 `appmsg_token` 或内容通过 JS 动态插入
  - 详情页正文为空或被脚本延迟加载
  - 优先尝试纯 HTTP；仅在必要时调用渲染以降低资源开销与风控风险

- 常见问题
  - 未安装浏览器：执行 `python -m playwright install`
  - 运行后无弹窗：确保 `headless=False`（已在扫码登录策略中设置）
  - 频控：降低并发（`max_concurrency`），增大延迟（`per_domain_delay_ms`），并开启退避重试

- 代码参考
  - 渲染函数：`crawler/fetcher.py:194`
  - 扫码登录策略：`crawler/login.py:74`、`crawler/login.py:81`
 - CLI Cookies 注入与登录触发：`crawler/cli.py:63`、`crawler/cli.py:72`

## 插件总览与快速使用

- WeChat 搜索（列表聚合 + 删除校验）
  - 作用：按关键词解析微信文章搜索列表的“日期/标题/URL/作者”，列表立即写入；可翻页；可选对详情页执行“删除提示”校验，命中后从聚合清理
  - 配置文件：`config/wechat_search.json`
  - 关键词文件：`wechat_search_keywords.txt`（每行一个）
  - 运行：`python -m crawler.cli --config config\wechat_search.json`
  - 输出：`output/wechat_search/articles.txt`、`articles.csv`、`articles_dedup.txt`、`deleted_urls.tsv`
  - 代码参考：`plugins/wechat_search_plugin.py:196`（列表解析与聚合）、`plugins/wechat_search_plugin.py:279`（详情删除校验）

- URL→PDF 导出（页面快照型插件）
  - 作用：对 `url_to_pdf.txt` 中的 URL 批量导出 PDF；支持滚动到底部以触发懒加载；支持 UA/Headers/Cookies 注入与语言/时区设置；失败记录日志
  - 配置文件：`config/url_to_pdf.json`（`allowed_domains: []` 支持所有域名）
  - 输入文件：`url_to_pdf.txt`（每行一个 URL）
  - 运行：`python -m crawler.cli --config config\url_to_pdf.json`
  - 输出：`output/url_to_pdf/pdf/<host>_<title>_<hash>.pdf`，日志 `output/url_to_pdf/export_log.tsv`
  - 代码参考：`plugins/url_to_pdf_plugin.py`

## 常用配置示例（片段）

```json
{
  "seeds": [],
  "seeds_from_keywords": {"file": "wechat_search_keywords.txt", "template": "https://weixin.sogou.com/weixin?type=2&query={kw}"},
  "allowed_domains": ["weixin.sogou.com", "mp.weixin.qq.com"],
  "max_concurrency": 2,
  "per_domain_delay_ms": 1500,
  "disable_global_link_extraction": true,
  "storage": {"output_dir": "output/wechat_search", "sqlite_path": "output/wechat_search/crawler_wechat_search.db", "html_subdir": "pages"},
  "plugins": ["plugins.wechat_search_plugin"],
  "plugin_params": {"wechat": {"search_follow_pages": true, "search_max_pages": 2, "reset_output_on_start": true, "verify_detail": true}}
}
```

```json
{
  "seeds": [],
  "seeds_from_keywords": {"file": "url_to_pdf.txt", "template": "{kw}"},
  "allowed_domains": [],
  "max_concurrency": 2,
  "per_domain_delay_ms": 2000,
  "disable_global_link_extraction": true,
  "save_page_html": false,
  "storage": {"output_dir": "output/url_to_pdf", "sqlite_path": "output/url_to_pdf/crawler_url_to_pdf.db", "html_subdir": "pages"},
  "plugins": ["plugins.url_to_pdf_plugin"],
  "plugin_params": {"pdf": {"timeout_sec": 3000, "wait_until": "load", "pre_wait_ms": 2000, "scroll_to_bottom": true, "scroll_step_px": 1600, "scroll_pause_ms": 1000, "scroll_max_ms": 90000, "filename_use_title": true, "filename_prefix_host": true, "fallback_html": false, "user_agent": "", "extra_headers": {"Referer": "https://blog.csdn.net/", "Accept-Language": "zh-CN,zh;q=0.9"}, "cookies_file": "", "locale": "zh-CN", "timezone_id": "Asia/Shanghai"}}
}
```

## 统一说明与最佳实践

- 并发与限速：先小后大，遇到 403/429 提高延迟、降低并发
- 登录态：需要更高可见性或避免风控时，启用 Cookies 注入或扫码登录
- 目录结构：使用 `storage.html_subdir` 区分页面快照与业务输出；聚合文件置于站点目录下
- 开发分工：插件负责解析与业务输出；框架负责抓取、调度、限速、重试与登录

## 配置说明（config.json）
关键字段：
- `seeds`: 初始URL列表
- `allowed_domains`: 允许抓取的域名（用于范围控制）
- `max_concurrency`: 最大全局并发 建议从小到大调优
- `per_domain_delay_ms`: 每个域名的请求间隔（毫秒）默认 800ms，避免触发风控
- `user_agents`: UA列表（为空则使用内置默认池）
- `proxies`: 代理列表（可为空）
- `respect_robots_txt`: 是否尊重 robots.txt（建议 true）
- `login`: 登录配置（可选）
  - `type`: `form` 或 `api`
  - `login_url`: 表单登录页（form）或认证API（api）
  - `username`/`password`/`payload`: 登录所需字段
  - `headers`: 登录请求头
  - `captcha_solver_hook`: 验证码处理钩子（占位字符串，需在代码中实现）
- `plugins`: 插件模块路径列表（如 `plugins.example_plugin`）
- `storage`: 存储配置
  - `output_dir`: 输出目录（HTML/JSON）
  - `sqlite_path`: SQLite数据库路径

- `disable_global_link_extraction`: 禁用全局链接发现，限制抓取到种子页与插件返回链接；同时基础链接发现会忽略 `?page=` 分页链接。

- `plugin_params`: 插件参数（用于“规则驱动插件”等通用插件的参数化配置），例如：
```json
{
  "plugin_params": {
    "rule_based": {
      "domains": ["example.com"],
      "global": {"use_js": false},
      "pages": []
    }
  }
}
```

详见 `config.example.json` 注释。

## 插件开发
位置 ： plugins/ 下新建模块，类名后缀 Plugin 即可被自动加载

新建一个模块（例如 `plugins/example_plugin.py`）：
```python
class ExamplePlugin:
    """
    解析插件示例：通过 should_handle/url_pattern 控制触发，handle 内进行解析与入库。
     
      should_handle(url) 决定是否处理当前URL；
      handle(url, html, context) 执行解析与入库
      
      
    """
    url_pattern = "example.com"

    def should_handle(self, url: str) -> bool:
        return self.url_pattern in url

    def handle(self, url: str, html: str, context: dict) -> list[str]:
        # 返回新发现的URL列表（继续入队抓取）
        return []
```
在 `config.json` 中加入 `plugins`:
```json
{
  "plugins": ["plugins.example_plugin"]
}
```

### 通用规则驱动插件（无需写代码）
- 目的：通过配置即可完成字段提取、链接发现与分页。
- 使用：
  - 在 `plugins` 增加 `plugins.rule_based_plugin`
  - 在 `plugin_params.rule_based` 编写规则（参考 `plugins/rules/rule_based.example.json`）
- 规则要点：
  - `domains`: 插件适用域名
  - `global.use_js`: 是否全局开启JS渲染（需要安装 Playwright）
  - `global.discover`: 全局链接发现选择器数组（如 `{ "selector": "a[href]", "attr": "href" }`）
  - `pages`: 页面类型列表（匹配条件、字段提取、链接发现与是否JS渲染）

示例：
```json
{
  "plugins": ["plugins.rule_based_plugin"],
  "plugin_params": {
    "rule_based": {
      "domains": ["example.com"],
      "global": {
        "use_js": false,
        "discover": [{"selector": "a[href]", "attr": "href"}]
      },
      "pages": [
        {
          "name": "list",
          "match": {"url_contains": "/list"},
          "fields": [{"name": "titles", "selector": ".item .title", "type": "text", "many": true}],
          "discover": [
            {"selector": ".item a[href]", "attr": "href"},
            {"selector": "a.next[href]", "attr": "href"}
          ]
        }
      ]
}
}
}
```

## 插件开发指南（详细）
- 目标：让任何开发者都能基于此框架快速实现一个站点插件，并正确接入抓取、解析、存储与调度。

### 插件生命周期与职责
- 生命周期：调度器拿到某个 URL → 框架路由到匹配的插件 → 抓取器提供该页的 HTML → 插件解析并可保存结果（JSON/文件） → 返回新发现的 URL（用于继续抓取）。
- 插件职责：
- 选择性处理：通过 `should_handle(url)` 或属性约定筛选适配页面。
- 页面解析：使用选择器解析所需字段与资源链接。
- 结果存储：保存结构化结果（JSON）与必要的二进制（如图片）。
- 链接发现：返回需要继续抓取的 URL 列表（可为空）。

### 约定与接口
- 位置与命名：
- 文件放在 `plugins/` 目录，例如 `plugins/example_site_plugin.py`。
- 类名以 `Plugin` 结尾（如 `ExampleSitePlugin`），框架可自动发现。
- 必需方法：
- `should_handle(url: str) -> bool`：是否由当前插件处理该 URL。
- `handle(url: str, html: str, context: dict) -> list[str]`：解析页面、保存结果并返回新链接。
- 可选属性：
- `url_pattern: str` 或 `domains: list[str]`：用于简化匹配逻辑（框架可据此预筛）。

### 关联配置
- 在 `config.json` 中注册插件：
```json
{
  "plugins": ["plugins.example_site_plugin"],
  "plugin_params": {
    "example_site_plugin": {
      "use_js": false,
      "selectors": {
        "title": ".article-title",
        "images": ".gallery img"
      },
      "discover": {
        "links": [
          {"selector": ".next-page a[href]", "attr": "href"}
        ]
      }
    }
  }
}
```
- 约定：`plugin_params.<模块名或类的下划线形式>` 会注入到 `context["params"]`，供插件读取。

### 最小可用插件示例（含详尽注释）
```python
# plugins/example_site_plugin.py
from __future__ import annotations
from typing import List, Dict
from bs4 import BeautifulSoup
import os
import json

class ExampleSitePlugin:
    """
    示例插件：
    - 通过 url_pattern 限定适配的站点/路径；
    - 在 should_handle 中进一步判断是否处理该 URL；
    - 在 handle 中完成解析、（可选）保存与链接发现。

    约定：框架将以 (url, html, context) 调用 handle。
    - url: 当前页面的绝对 URL
    - html: 抓取器返回的原始 HTML 字符串（若 use_js=true 或框架启用 JS 渲染，则为渲染后的 HTML）
    - context: 执行上下文，常见字段：
        - context["logger"]: 日志记录器（可用 .info/.warning/.error）
        - context["params"]: 来自 config.json 的插件参数对象
        - context["save_html"](html, url): 保存 HTML 的便捷方法（若提供）
        - context["save_json"](obj, url): 保存 JSON 的便捷方法（若提供）
        - context["output_dir"]: 输出根目录（若提供）
        - 其他可能的对象：如 fetcher / storage（视框架版本而定）
    """

    # 供框架预筛的简单模式（可选）：若 URL 中包含该模式，优先路由到此插件
    url_pattern = "example.com"

    def should_handle(self, url: str) -> bool:
        """
        决定是否由当前插件处理该 URL。
        - 返回 True 表示 handle 会被调用；False 则忽略。
        - 可根据域名、路径、查询参数、页面类型等自定义判断。
        """
        return self.url_pattern in url and ("/article/" in url or "/gallery/" in url)

    def handle(self, url: str, html: str, context: Dict) -> List[str]:
        """
        解析页面、保存结果并返回新发现的链接列表。

        通常步骤：
        1) 解析 HTML，提取结构化数据（如标题、正文、图片链接）。
        2) （可选）保存 JSON 结果、HTML 快照或二进制文件。
        3) （可选）发现下一页/详情页链接，并返回供框架继续抓取。
        """
        logger = context.get("logger")
        params = context.get("params", {})

        # 1) 解析 HTML
        soup = BeautifulSoup(html, "html.parser")
        title_sel = params.get("selectors", {}).get("title", ".title")
        image_sel = params.get("selectors", {}).get("images", "img")

        title_el = soup.select_one(title_sel)
        images_el = soup.select(image_sel)
        title = title_el.get_text(strip=True) if title_el else None
        image_urls = [img.get("src") for img in images_el if img.get("src")]

        result = {
            "url": url,
            "title": title,
            "image_urls": image_urls,
        }

        # 2) 保存结果（优先使用框架提供的 save_* 方法；否则降级为手工保存）
        try:
            if "save_json" in context:
                # 使用框架的 JSON 保存（通常会自动生成文件名并写入 output_dir）
                context["save_json"](result, url)
                if logger:
                    logger.info(f"Saved JSON via context.save_json for {url}")
            else:
                # 手工保存：将 URL 安全化作为文件名，写入 output_dir
                safe_name = url.replace("/", "_").replace(":", "_").replace("?", "_")
                output_dir = context.get("output_dir", "output")
                os.makedirs(output_dir, exist_ok=True)
                path = os.path.join(output_dir, f"{safe_name}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                if logger:
                    logger.info(f"Saved JSON to {path}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to save result for {url}: {e}")

        # （可选）保存 HTML 快照，便于后续复查或二次解析
        if "save_html" in context:
            try:
                context["save_html"](html, url)
                if logger:
                    logger.info(f"Saved HTML snapshot via context.save_html for {url}")
            except Exception as e:
                if logger:
                    logger.warning(f"Save HTML failed for {url}: {e}")

        # 3) 发现下一页或详情页链接（如存在 next-page 按钮或列表项链接）
        discovered: List[str] = []
        for rule in params.get("discover", {}).get("links", []):
            sel = rule.get("selector")
            attr = rule.get("attr", "href")
            for a in soup.select(sel or "a[href]"):
                href = a.get(attr)
                if href:
                    # 这里假设框架会处理相对链接的规范化；若需要，也可以在此进行绝对化。
                    discovered.append(href)

        # 返回新发现的链接（框架会将其加入队列并继续抓取）
        return discovered
```

### 开发步骤（从零到可用）
- 1) 明确目标页面与数据字段：列出需要抓取的页面类型、选择器与输出格式。
- 2) 脚手架：在 `plugins/` 目录新建模块与类，按上述约定实现 `should_handle` 与 `handle`。
- 3) 解析实现：用 `BeautifulSoup` 或你偏好的解析器选择并提取字段。
- 4) 存储实现：优先使用 `context["save_json"]`/`context["save_html"]`；若不可用，手工保存到 `output_dir`。
- 5) 链接发现：根据站点结构返回下一步要抓取的链接（如分页/详情）。
- 6) 配置与运行：把插件加入 `config.json` 的 `plugins`，编写 `plugin_params.<你的插件>`。
- 7) 验证与迭代：检查输出文件、日志与数据库记录，微调选择器与速率。

### 插件功能具体化编写教程（逐项详解）
- 目标：针对常见需求，提供“逐项可复制”的实现方式与代码片段，任何人照着即可完成插件开发。

#### 1. URL 路由与匹配（should_handle）
- 作用：只让插件处理目标页面，避免误解析。
- 做法：使用域名/路径/查询参数判断。
```python
class MyPlugin:
    url_pattern = "example.com"  # 可选：便于快速预筛

    def should_handle(self, url: str) -> bool:
        """
        返回 True 表示处理该 URL；常见做法是限制在某域名，并根据路径区分列表/详情等。
        """
        from urllib.parse import urlparse
        p = urlparse(url)
        if self.url_pattern not in (p.netloc or ""):
            return False
        path = p.path or ""
        return ("/list" in path) or path.startswith("/detail/")
```

#### 2. 字段解析（使用选择器）
- 作用：从 HTML 提取结构化数据（标题、图片、正文等）。
- 做法：`BeautifulSoup.select` + 配置化选择器；提供备选与空值容忍。
```python
from bs4 import BeautifulSoup

def _parse_fields(html: str, params: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_sel = params.get("selectors", {}).get("title", ".title")
    body_sel  = params.get("selectors", {}).get("body",  ".content")
    img_sel   = params.get("selectors", {}).get("images", "img")

    title_el = soup.select_one(title_sel)
    body_el  = soup.select_one(body_sel)
    img_els  = soup.select(img_sel)

    return {
        "title": title_el.get_text(strip=True) if title_el else None,
        "body":  body_el.get_text("\n", strip=True) if body_el else None,
        "image_urls": [img.get("src") for img in img_els if img.get("src")],
    }
```

#### 3. 保存 HTML 快照与 JSON 结果
- 作用：留存证据与支持二次解析；JSON 便于后续分析与查重。
- 做法：优先用 `context["storage"]` 的方法，框架会统一命名与路径。
```python
def _persist(storage, url: str, html: str, data: dict) -> None:
    # 保存 HTML（CLI 已保存一份；这里可按需再保存或跳过）
    try:
        storage.save_html(url, html)
    except Exception:
        pass

    # 保存 JSON（文件名由框架用 URL 安全化生成）
    storage.save_json(url, data)
```

#### 4. 下载图片并命名保存（含扩展名推断）
- 作用：将页面中的图片保存到 `output_dir/images`。
- 做法：同步 `httpx.Client` 下载，按 URL/Content-Type 推断扩展名，安全化文件名。
```python
import os

def _download_image_sync(image_url: str):
    import httpx
    with httpx.Client(timeout=30.0) as client:
        r = client.get(image_url)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type")

def _guess_ext(image_url: str, content_type: str | None) -> str:
    url = (image_url or "").lower()
    ct = (content_type or "").lower()
    if url.endswith(".jpg") or "jpeg" in ct:
        return ".jpg"
    if url.endswith(".png") or "png" in ct:
        return ".png"
    if url.endswith(".webp") or "webp" in ct:
        return ".webp"
    return ".bin"

def _save_image(storage, name_without_ext: str, image_bytes: bytes, ext: str) -> str:
    base_dir = getattr(storage, "output_dir", "output")
    img_dir = os.path.join(base_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    safe = name_without_ext.replace("/", "_").replace(":", "_").replace("?", "_")
    path = os.path.join(img_dir, f"{safe}{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path

def download_and_save_first_image(url: str, html: str, storage, params: dict) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    img_sel = params.get("image_selector", ".content .poster img")
    img = soup.select_one(img_sel)
    image_url = img.get("src") if img else None
    if not image_url:
        return {"url": url, "error": "image_not_found"}

    img_bytes, ct = _download_image_sync(image_url)
    ext = _guess_ext(image_url, ct)
    filename = url.replace("/", "_").replace(":", "_").replace("?", "_")
    saved_path = _save_image(storage, filename, img_bytes, ext)
    return {"url": url, "image_url": image_url, "saved_path": saved_path}
```

#### 5. 分页与链接发现
- 作用：发现下一页、详情页或相关推荐链接，交给框架继续抓取。
- 做法：从配置读取若干规则，统一按选择器提取并返回。
```python
def discover_links(html: str, params: dict) -> list[str]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    discovered: list[str] = []
    for rule in params.get("discover", {}).get("links", []):
        sel = rule.get("selector")
        attr = rule.get("attr", "href")
        for a in soup.select(sel or "a[href]"):
            href = a.get(attr)
            if href:
                discovered.append(href)
    return discovered
```

#### 6. 详情页解析与文本写入（按固定格式）
- 作用：提取内容、发布日期、类别，写入文本；示例结构参考 `AllJavxx_Output/data.txt`。
- 做法：解析后按行写入，并可维护“去重/失败回滚”。
```python
def append_record_txt(path: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
        f.write("\n")

def parse_detail_and_write(html: str, url: str, out_txt: str) -> None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    code = (soup.select_one(".info .code").get_text(strip=True) if soup.select_one(".info .code") else "")
    content = (soup.select_one("#video-details .desc .content") or soup.select_one("#video-info .title"))
    content_text = content.get_text(" ", strip=True) if content else ""
    publish = ""
    for div in soup.select("#video-details .meta div"):
        label = (div.select_one("label") or div.select_one(".label"))
        text = label.get_text(strip=True) if label else ""
        if "发布日期" in text:
            publish = (div.select_one("span") or div.select_one(".value")).get_text(strip=True)
            break
    categories = []
    for div in soup.select("#video-details .meta div"):
        label = (div.select_one("label") or div.select_one(".label"))
        if label and "类别" in label.get_text(strip=True):
            for el in div.select("a, span"):
                t = el.get_text(strip=True)
                if t:
                    categories.append(f"{t}#")
            break

    lines = [code, content_text, url, publish, "".join(categories)]
    append_record_txt(out_txt, lines)
```

#### 7. 关键字工作流（读取/删除/失败归档）
- 作用：在基于关键字的爬取中，识别成功/失败，并维护关键字源文件。
- 做法：解析出关键字，成功/失败后从源文件移除，并把失败写入 `failed_keywords.txt`。
```python
from threading import Lock
_kw_lock = Lock()

def remove_keyword_from_file(file_path: str, keyword: str) -> None:
    if not (file_path and keyword):
        return
    try:
        with _kw_lock:
            if not os.path.isfile(file_path):
                return
            with open(file_path, "r", encoding="utf-8", errors="ignore") as rf:
                lines = [ln.rstrip("\n") for ln in rf]
            target = keyword.strip()
            new_lines = [ln for ln in lines if ln.strip() != target]
            if new_lines != lines:
                with open(file_path, "w", encoding="utf-8") as wf:
                    wf.write("\n".join(new_lines) + ("\n" if new_lines else ""))
    except Exception:
        pass

def record_failed_keyword(output_dir: str, keyword: str) -> None:
    if not keyword:
        return
    try:
        os.makedirs(output_dir, exist_ok=True)
        failed_path = os.path.join(output_dir, "failed_keywords.txt")
        existing = set()
        if os.path.isfile(failed_path):
            with open(failed_path, "r", encoding="utf-8", errors="ignore") as rf:
                existing = {ln.strip() for ln in rf if ln.strip()}
        if keyword not in existing:
            with open(failed_path, "a", encoding="utf-8") as wf:
                wf.write(keyword + "\n")
    except Exception:
        pass
```

#### 8. 插件参数注入与读取（plugin_params）
- 作用：让插件逻辑“配置驱动”，便于无代码修改行为。
- 做法：在 `config.json` 的 `plugin_params.<插件名>` 写参数，在插件 `handle` 中读取。
```json
{
  "plugins": ["plugins.my_site_plugin"],
  "plugin_params": {
    "my_site_plugin": {
      "selectors": {"title": ".title", "images": ".gallery img"},
      "discover": {"links": [{"selector": ".pagination a.next[href]", "attr": "href"}]},
      "image_selector": ".content .poster img"
    }
  }
}
```
```python
def handle(self, url: str, html: str, context: dict) -> list[str]:
    params = context.get("plugin_params", {}).get("my_site_plugin", {})
    # 现在可以用 params 中的选择器与规则做解析/发现/下载
```

#### 9. 将上述功能拼成一个完整插件
- 做法：在 `handle` 中依次执行：解析字段→保存→图片下载→链接发现→（可选）详情写文本→维护关键字文件。
- 示例：参考本 README 的两个模板代码与 `plugins/javxx_search_image_plugin.py`、`plugins/alljavxx_plugin.py` 的实现风格。

#### 10. 验证与排错建议（专项）
- 单页试跑：先用 1 个种子或 1 个关键字试跑，检查 `output` 目录中文件是否正确生成。
- 日志核对：搜索插件类名的日志，确认路由与解析是否命中。
- 快照复查：打开保存的 `.html` 快照，对照选择器检查节点是否存在与稳定。
- 失败复盘：对 `failed_keywords.txt` 做二次抓取或调整选择器后重试。

### 并发与文件安全建议
- 共享文件写入：若插件需要写入共享文件（如关键字源文件），使用 `threading.Lock` 或模块级锁，避免并发写入导致内容错乱。
- 命名与覆盖：为二进制资源（图片、附件）采用稳定、可逆的命名；结合 `skip_if_exists/overwrite` 参数控制覆盖行为。
- 速率与退避：尊重全局与域级限速；当站点风控严格时，适当提高延迟并减少并发。

### 调试与排错
- 日志：通过 `context["logger"]` 输出关键步骤与异常，便于定位问题。
- 快照：保存 HTML 以便在选择器不匹配时快速复查页面结构。
- 选择器健壮性：避免过于脆弱的选择器（尽量使用语义更强的 class/id）；为站点小改动预留冗余。
- 失败重试：可在解析失败时返回空链接并记录错误；框架的抓取与重试策略会在网络层处理。

### 配置示例（小站点 + 仅列表分页）
```json
{
  "allowed_domains": ["example.com"],
  "plugins": ["plugins.example_site_plugin"],
  "seeds": ["https://example.com/list"],
  "disable_global_link_extraction": true,
  "plugin_params": {
    "example_site_plugin": {
      "selectors": {
        "title": ".item .title",
        "images": ".item img"
      },
      "discover": {
        "links": [
          {"selector": ".pagination a.next[href]", "attr": "href"},
          {"selector": ".item a.detail[href]", "attr": "href"}
        ]
      }
    }
  }
}
```

### 常见坑与最佳实践
- URL 绝对化：若站点大量使用相对链接，需在插件或框架层做绝对化（结合页面基址）。
- 字符编码：保存文件时统一为 UTF-8，避免 Windows 下默认编码导致乱码。
- 选择器冗余：为关键节点提供备选选择器，避免页面小改动导致解析失败。
- 结果结构化：为后续分析与查重，JSON 中尽量包含 `url`、`title`、关键字段与时间戳。
- 退出策略：当无新链接或关键字文件为空时，框架将优雅退出（详见 CLI 说明）。

## 抗反爬策略细节
- UA/请求头随机化：降低固定指纹被识别的概率
- 速率限制与抖动：避免固定频率触发风控，带随机抖动
- 退避重试：403/429/5xx触发指数退避，有限次数重试
- 代理轮换：失败次数达到阈值后切换代理，代理健康度监控
- robots.txt：使用标准库 `urllib.robotparser` 解析，若 disallow 则跳过
- Session维持与续期：登录成功后复用Cookies，状态失效后自动重登

## 运行建议
- 慎重设置并发与速率，逐步增大，观察错误率
- 对强风控站点优先使用登录态 + 合理抓取窗口（夜间/非高峰）
- 使用专用代理池，按域名隔离，记录代理健康度
- 对需要JS渲染页面，优先尝试API接口或静态备选页，渲染仅作为必要兜底

### 性能调优
- 并发调参：从 `2~4` 并发起步，观察错误率，逐步提升；提高到 `8~16` 需配合代理池与充分限速。
- 代理策略：失败计数达到阈值后熔断并轮换代理；可考虑按照域名维护独立代理池。
- 存储与IO：如输出较大，可将 `output_dir` 指向SSD目录并启用增量清理机制。

## 通用爬虫框架 vs 常规爬虫：优缺点对比
- 优点（通用框架）：
- 复用性强：配置驱动与插件机制，快速适配不同站点。
- 可维护性高：限速、重试、代理、登录、robots 等策略集中管理。
- 可扩展性好：并发调度、代理池、JS渲染、规则驱动解析均可插拔。
- 可观测性强：统一日志、SQLite 状态、HTML/JSON 持久化，支持断点续抓与追溯。
- 协作友好：规则/插件分工清晰，统一约定便于代码评审与版本演进。
- 合规与稳定：默认尊重 `robots.txt`，节流与指纹扰动降低被封风险。
- 工作流增强：关键词文件、失败关键词归档、关键字文件为空时的友好退出等能力。

- 缺点（通用框架）：
- 学习成本与抽象开销：需要理解配置模型与插件 API。
- 性能额外开销：通用能力带来一定的运行与组织成本。
- 灵活度边界：面向特定站点的“硬编码”技巧可能受框架约束。
- 调试复杂度：跨模块问题定位需要经验与清晰日志策略。
- 初期搭建成本：对一次性小脚本而言显得“重”。

- 优点（常规爬虫/一次性脚本）：
- 上手非常快：直接写脚本即可运行，无框架约束。
- 灵活“硬编码”：可按站点特性快速施加专用逻辑与技巧。
- 轻量：仅保留必要功能，资源占用低。
- 定向优化：针对目标站点做极致性能与结构优化。

- 缺点（常规爬虫/一次性脚本）：
- 复用与维护差：需求变化需改代码，跨站点往往重复造轮子。
- 稳健性与合规弱：限速/重试/代理/robots 等需要自行实现，容易忽视。
- 可观测性不足：缺少统一日志、状态存储、断点续抓与数据追溯。
- 协作困难：缺少标准化约定与模块边界，难以团队维护。
- 风险较高：容易触发风控或被封，恢复与追责困难。

- 如何选择：
- 选通用框架：多站点/长期维护、需要登录/代理/并发控制、强调合规与可追溯、多人协作。
- 选常规爬虫：一次性小任务、目标站点结构稳定、无并发/代理需求、速度优先且可控。

## 法律与伦理
- 尊重站点 `robots.txt` 与服务条款
- 不进行破坏性抓取；合理限速与带宽控制
- 不抓取敏感、受限或私人数据；不绕过授权与付费墙

## 目录结构
```
.
├── requirements.txt
├── README.md
├── config.example.json
├── plugins/
│   └── example_plugin.py
│   ├── rule_based_plugin.py
│   ├── keyword_plugin.py
│   └── rules/
│       └── rule_based.example.json
│       └── keyword.example.json
└── crawler/
    ├── __init__.py
    ├── cli.py    命令行入口，串起配置、调度、抓取与插件
    ├── config.py
    ├── utils.py
    ├── anti_bot.py Backoff策略、Robots缓存、域级限速
    ├── login.py  表单登录与API Token登录策略，Cookies自动维持
    ├── fetcher.py  HTTP抓取，重试/退避/限速/代理轮换/robots检查
    ├── scheduler.py  Frontier队列管理，去重与范围控制
    ├── storage.py   SQLite记录已抓取、文件系统保存HTML/JSON
    └── parser.py    基础链接抽取（示例），推荐把站点逻辑放插件
```

## 常见问题
- 安装 Playwright 报错：此功能为可选，先不启用JS渲染亦可正常抓取
- 403/429 较多：降低并发与请求速率、启用代理轮换、增加UA池
- 登录后仍未带登录态：检查登录表单字段、CSRF、重定向后Cookies是否持久

## 解析与存储
- HTML保存：每个成功抓取的页面会保存原始HTML，便于后续审阅与二次解析。
- JSON保存：插件的结构化解析结果保存为JSON，文件名根据URL安全转换生成。
- SQLite：记录每个URL的抓取状态与时间戳，支持断点续抓与重复过滤。

## 故障排查（Troubleshooting）
- 抓取返回 `451 Blocked by robots.txt`：确认是否开启了 `respect_robots_txt` 且站点禁止抓取；如需抓取，请遵守站点政策或关闭该选项（不推荐）。
- 网络错误或超时：检查代理与网络，提升 `retry_backoff_max_ms`，降低并发与速率。
- 结果为空：检查选择器是否正确匹配，是否需要JS渲染，或页面结构是否变化。
