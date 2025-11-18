# URL 到 PDF/归档 导出插件说明（url_to_pdf）

## 功能概述
- 批量读取 `url_to_pdf.txt` 中的 URL，按需导出多种格式：
  - PDF 高保真快照（可开启或关闭）
  - Markdown 可编辑正文（正文容器抽取+常见标签转 Markdown）
  - MHTML 单文件归档（内嵌资源，适合完整离线快照）
  - 单文件 HTML（SingleFile，本地脚本，兼容性更好）
- 自动滚动到底部与延迟等待，确保懒加载内容完整
- 文件名可按“域名+标题”组合生成，便于归档与检索
- 支持 UA/Headers/Cookies/语言/时区注入，适配风控策略

## 环境准备
- Python `3.10+`
- 依赖：`httpx`、`beautifulsoup4`、`playwright`
- 安装：
  - `pip install playwright`
  - `python -m playwright install`

## 配置（关键项）
- 文件：`config/page_export.json`
- 通用：
  - `seeds_from_keywords.file`: `url_to_pdf.txt`（每行一个 URL）
  - `allowed_domains`: `[]`（支持所有域名）
  - `disable_global_link_extraction`: `true`（不做链接发现）
  - `save_page_html`: 建议 `true`，便于问题定位
  - `plugins`: `plugins.url_to_pdf_plugin`
- PDF（`plugin_params.pdf`）：
  - `enabled`: `true/false`（是否生成 PDF）
  - `wait_until`: `load/domcontentloaded/networkidle`
  - `pre_wait_ms`: 到达后额外等待毫秒（慢渲染页面建议 3000+）
  - `scroll_to_bottom/scroll_*`: 懒加载页面建议开启并提高 `scroll_max_ms`
  - `print_pre_wait_ms`: 打印媒体前等待（字体与样式准备）
  - `prefer_css_page_size`: 尊重页面 `@page` 设置
  - `filename_use_title/filename_prefix_host`: 友好文件名
  - `fallback_html`: 失败保存回退 HTML
  - 会话指纹：`user_agent/extra_headers/cookies_file/locale/timezone_id`
  - 打印兼容：
    - `inject_print_css`: `true` 时注入自定义打印样式覆盖
    - `print_css`: 自定义打印样式内容
    - `disable_page_print_css`: 移除站点自身 `media="print"` 样式
    - `force_show_selectors`: 强制显示正文容器选择器列表
- Markdown（`plugin_params.markdown`）：
  - `enabled`: 是否生成 Markdown
  - `selectors`: 正文容器优先级列表（默认含博客园等常见容器）
  - `include_title/filename_*`: 标题与命名控制
- 归档 MHTML（`plugin_params.archive`）：
  - `enabled`: 是否生成 `.mhtml`
  - 与 PDF 同步的 `wait/scroll` 参数，用于完整快照
- 单文件 HTML（`plugin_params.fullpage`）：
  - `enabled`: 是否生成单文件 `.html`
  - `singlefile_script_path`: 本地 `assets/single-file.js`，仅使用本地脚本
  - `wait/scroll` 参数：与 MHTML 类似，适配懒加载

## 输入文件
- 路径：`url_to_pdf.txt`，一行一个 URL，例如：
```
https://www.cnblogs.com/sister/p/4700702.html
https://cloud.tencent.com/developer/article/2485043
```

## 运行与输出
- 运行：`python -m crawler.cli --config config\page_export.json`
- 输出位置：
  - PDF：`output/page_export/pdf/*.pdf`
  - Markdown：`output/page_export/md/*.md`
  - MHTML：`output/page_export/archive/*.mhtml`
  - 单文件 HTML：`output/page_export/fullpage/*.html`
  - 页面快照：`output/page_export/pages/*.html`
  - 日志：`output/page_export/export_log.tsv`（URL、状态、错误原因）

## 兼容与防白屏（关键技巧）
- 打印媒体切换与样式注入：见 `plugins/url_to_pdf_plugin.py:502-511`（打印样式注入/移除站点打印样式/强制显示容器）与 `plugins/url_to_pdf_plugin.py:560-570`（PDF 导出前等待与兜底回退）
- 单文件 HTML（本地 SingleFile）：见 `plugins/page_export_plugin.py:590-599`（读取本地脚本）与 `plugins/page_export_plugin.py:610-634`（脚本注入与失败回退 `page.content()`）
- MHTML 导出（二进制写入）：确保归档文件结构正确，见 `plugins/url_to_pdf_plugin.py` 内 `Page.captureSnapshot` 写入逻辑
- 慢渲染/懒加载：提高 `pre_wait_ms` 与 `scroll_max_ms`（如 `8000/120000`），必要时加大 `scroll_step_px`/`scroll_pause_ms`

## 微信页面处理
- 详情删除提示：`body#activity-detail` 下 `.weui-msg__title.warn` 含“该内容已被发布者删除”时跳过导出（`plugins/url_to_pdf_plugin.py:20-27`）
- 验证码拦截：出现 `mp/wappoc_appmsgcaptcha` 需注入有效 `cookies_file` 或手动通过后再导出

## 常见问题与建议
- 打开后空白：
  - PDF：开启 `inject_print_css` 并配置 `print_css`；同时启用 `disable_page_print_css/force_show_selectors`
  - MHTML：确保以二进制写入；用 Chrome/Edge 打开
  - 单文件：确认 `assets/single-file.js` 存在并可读取；失败时至少会写入 `page.content()`
- 403/风控：设置 `user_agent/extra_headers.Referer/cookies_file/locale/timezone_id`
- 内容不全：提升 `pre_wait_ms/scroll_max_ms` 并保持 `scroll_to_bottom: true`
- 微信/需登录站点：使用 `cookies_file` 复用已登录会话

## 代码参考
- CLI 启动与插件上下文：`crawler/cli.py:134-144`
- 插件主流程与参数读取：`plugins/page_export_plugin.py:480-626`
- 打印样式控制与 PDF 导出：`plugins/page_export_plugin.py:502-570`
- 单文件 HTML（SingleFile）：`plugins/page_export_plugin.py:590-634`

## SingleFile 脚本说明（单文件 HTML）
- 脚本来源与放置：
  - 本地脚本路径：`assets/single-file.js`（通过配置 `plugin_params.fullpage.singlefile_script_path` 指定）
  - 固定使用本地版本，避免网络不稳定或 CSP 限制；不存在时仍会输出 `page.content()` 兜底
- 注入与执行流程（代码参考 `plugins/url_to_pdf_plugin.py:610-634`）：
  - 页面完成加载、滚动与等待后，将本地脚本注入到页面上下文
  - 执行 `singlefile.getProcessedHTML(opt)` 获取“所有资源内嵌”的完整 HTML 字符串
  - 若注入或执行失败，回退为 `await page.content()`，再失败回退 `documentElement.outerHTML`
- 默认处理参数（当前版本内置）：
  - `removeUnusedStyles: false`（保留全部样式，防止样式丢失）
  - `compressCSS: true`（压缩样式，减小体积）
  - `removeHiddenElements: false`（不移除隐藏元素，避免误删正文）
  - `blockMixedContent: false`（允许混合内容内嵌，提升完整性）
- 输出位置与文件名：
  - 路径：`output/page_export/fullpage/<host>_<title>_<hash>.html`
  - 命名与 PDF/Markdown 一致，便于归档与检索
- 典型站点兼容建议：
  - 慢渲染/懒加载：提高 `fullpage.pre_wait_ms`（如 `8000`）与 `fullpage.scroll_max_ms`（如 `120000`），保持 `scroll_to_bottom: true`
  - 严格 CSP 页：本地脚本注入仍可能失败，日志会出现 `singlefile_error`；此时使用 `page.content()` 兜底版本（不内嵌资源），确保不空白
  - 需登录或受风控站点：配置 `cookies_file`、`user_agent` 与 `extra_headers.Referer`，并设置 `locale/timezone_id`
  - 微信验证页：出现 `wappoc_appmsgcaptcha` 需通过验证码或注入有效会话后再运行
- 快速检查与定位：
  - 查看 `output/page_export/export_log.tsv` 是否存在 `singlefile_error` 或空内容记录
  - 检查 `assets/single-file.js` 是否存在且可读（在仓库根目录）
  - 打开 `pages/` 下原始快照对比，确认页面本身是否内容加载不完整
