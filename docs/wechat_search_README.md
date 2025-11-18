# WeChat 搜索插件使用说明（wechat_search）

## 功能概述
- 根据关键词在微信文章搜索页（`weixin.sogou.com?type=2`）解析“标题 / 时间 / URL / 作者”，列表立即写入聚合
- 支持翻页抓取更多结果（受配置控制）；不解析正文、不保存 JSON
- 可选详情校验：对 `mp.weixin.qq.com/s...` 进行“删除提示”检测，命中后自动清理列表中的该条

## 环境准备
- Python `3.10+`
- 依赖：`httpx`、`beautifulsoup4`
- 可选：`playwright`（用于详情删除校验或登录态），安装：`pip install playwright`、`python -m playwright install`

## 配置
- 文件：`config/wechat_search.json`
- 关键字段：
  - `seeds_from_keywords.file`: `wechat_search_keywords.txt`
  - `seeds_from_keywords.template`: `https://weixin.sogou.com/weixin?type=2&query={kw}`
  - `plugins`: 仅 `plugins.wechat_search_plugin`
  - `allowed_domains`: 包含 `weixin.sogou.com` 与 `mp.weixin.qq.com`
  - `disable_global_link_extraction`: 建议 `true`
  - `plugin_params.wechat.search_follow_pages`: 是否翻页
  - `plugin_params.wechat.search_max_pages`: 跟随页数（不含第一页）
  - `plugin_params.wechat.reset_output_on_start`: 首次运行清空聚合文件
  - `plugin_params.wechat.verify_detail`: 启用详情删除校验

示例：
```
{
  "seeds": [],
  "seeds_from_keywords": {
    "file": "wechat_search_keywords.txt",
    "template": "https://weixin.sogou.com/weixin?type=2&query={kw}"
  },
  "allowed_domains": ["weixin.sogou.com", "mp.weixin.qq.com"],
  "max_concurrency": 2,
  "per_domain_delay_ms": 1500,
  "disable_global_link_extraction": true,
  "storage": {"output_dir": "output/wechat_search", "sqlite_path": "output/wechat_search/crawler_wechat_search.db", "html_subdir": "pages"},
  "plugins": ["plugins.wechat_search_plugin"],
  "plugin_params": {
    "wechat": {
      "search_follow_pages": true,
      "search_max_pages": 2,
      "reset_output_on_start": true,
      "verify_detail": true
    }
  }
}
```

## 关键词文件
- 路径：`wechat_search_keywords.txt`
- 一行一个关键词，例如：
```
新能源
AI投融资
区块链政策
```

## 运行
- 命令：`python -m crawler.cli --config config\wechat_search.json`
- 流程：
  - 列表页：解析并立即写入聚合（可翻页）
  - 详情页：仅删除校验，命中“该内容已被发布者删除”则从聚合清理

## 输出
- 聚合文本：`output/wechat_search/articles.txt`（每行：`date\ttitle\turl\tauthor`）
- 聚合CSV：`output/wechat_search/articles.csv`（表头：`date,title,url,author`）
- 去重文件：`output/wechat_search/articles_dedup.txt`
- 删除记录：`output/wechat_search/deleted_urls.tsv`
- 映射文件：`url_title_map.tsv`、`url_date_map.tsv`、`url_author_map.tsv`（用于标题与日期补齐）

## 登录与 Cookies（可选）
- Cookies 注入：配置 `login.cookies_file` 为 JSON 或 Netscape 文本，CLI 自动注入会话（`crawler/cli.py:63`）
- 扫码登录：`login.enabled=true`、`login.type="wechat_qr"`，用于更多文章可见性与稳定性

## 常见问题
- 结果仅 10 条：开启 `search_follow_pages=true` 并设置 `search_max_pages>0`；关键词若仅一页则不会增加
- 日期为空：部分卡片日期来自脚本 `timeConvert()`；已支持提取，但个别结构差异仍可能为空
- 频控/403：将 `max_concurrency` 降至 1~2、`per_domain_delay_ms` 升至 2000+，必要时启用登录态

## 代码参考
- 列表解析与聚合：`plugins/wechat_search_plugin.py:196`
- 日期提取与规范化：`plugins/wechat_search_plugin.py:202`
- 详情删除校验与清理：`plugins/wechat_search_plugin.py:279`
- CLI 启动与上下文注入：`crawler/cli.py:126`
