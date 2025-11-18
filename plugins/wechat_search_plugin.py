from __future__ import annotations
"""
微信文章搜索列表页解析插件（WechatSearchPlugin）

功能与约束：
- 仅解析搜狗微信搜索（weixin.sogou.com）结果列表页，type=2 表示文章搜索模式；
- 从列表卡片中提取四要素：日期（date）、标题（title）、链接（url）、作者（author）；
- 输出到聚合文件：
  - articles.txt：按行记录 date\ttitle\turl\tauthor；
  - articles.csv：CSV 结构化结果（列顺序与 txt 一致）；
  - articles_dedup.txt：去重后的 URL 列表；
  - url_title_map.tsv / url_date_map.tsv：建立 URL→标题/日期 映射，便于后续补全；
  - deleted_urls.tsv：当详情页校验发现“内容已删除”时记录被清理的 URL；
- 支持受控翻页：search_follow_pages + search_max_pages；直接计算下一页 URL，不依赖页面上的“下一页”。
- 可选详情页删除提示校验：verify_detail 为 True 时将详情页入队，发现“该内容已被发布者删除”则清理聚合中的该 URL。

注意：
- 插件不解析详情正文，不保存 JSON；仅做列表聚合与可选的删除校验。
- 模块中的所有路径与文件写入均使用 storage.output_dir 下的相对文件。
"""

from typing import Dict, Any, List
import os
import re
import time
import csv
from urllib.parse import urlparse as _up, parse_qs as _pq
from urllib.parse import urlparse

from bs4 import BeautifulSoup


class WechatSearchPlugin:
    """搜狗微信文章搜索列表页解析插件。

    设计目标：
    - 列表页尽快、稳定、轻量地提取四要素并聚合；
    - 通过脚本与近邻节点提取日期并规范化；
    - 受控翻页，避免只输出 10 条的限制；
    - 可选详情页删除提示校验，用于后期清理聚合输出。
    """
    def __init__(self):
        self._reset_done = False
    def should_handle(self, url: str) -> bool:
        """仅匹配 weixin.sogou.com 的文章搜索列表页（type=2）。

        参数：
        - url：当前 URL。
        返回：
        - True 表示本插件负责处理；False 表示跳过。
        """
        p = urlparse(url)
        host = p.netloc or ""
        path = p.path or ""
        q = p.query or ""
        if "weixin.sogou.com" in host and "/weixin" in path and "type=2" in q:
            return True
        return False

    def handle(self, url: str, html: str, context: Dict[str, Any]) -> List[str]:
        """解析列表页并输出聚合文件；可选入队详情页用于删除提示校验。

        行为：
        1. 根据配置在首次处理时重置聚合文件（articles.*、url_*_map.tsv）；
        2. 当 URL 为搜狗文章列表页时：
           - 遍历卡片，选取标题链接；
           - 提取并规范化日期（脚本 timeConvert 与近邻文本）；
           - 写入 txt/csv/去重/映射文件；
           - 可选将详情页 URL 入队（verify_detail 模式）；
           - 受控计算下一页 URL 并返回 discovered 列表；
        3. 当 URL 为微信详情页且 verify_detail=True：
           - 发现“该内容已被发布者删除”时，清理聚合中的该 URL 并记录到 deleted_urls.tsv。
        返回：
        - 新发现的 URL 列表（下一页/详情校验）。
        """
        soup = BeautifulSoup(html, "html.parser")
        storage = context.get("storage")
        params = context.get("plugin_params", {}).get("wechat", {})
        if not self._reset_done and params.get("reset_output_on_start"):
            # 首次运行时清空聚合文件，避免历史数据干扰；CSV 写入表头。
            try:
                out_root = storage.output_dir
                os.makedirs(out_root, exist_ok=True)
                for name in ["articles.txt", "articles.ndjson", "articles_dedup.txt"]:
                    try:
                        open(os.path.join(out_root, name), "w", encoding="utf-8").close()
                    except Exception:
                        pass
                csv_path = os.path.join(out_root, "articles.csv")
                try:
                    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
                        w = csv.writer(cf)
                        w.writerow(["date", "title", "url", "author"])
                except Exception:
                    pass
            except Exception:
                pass
            self._reset_done = True
        p = urlparse(url)
        host = p.netloc or ""
        path = p.path or ""
        if "mp.weixin.qq.com" in host and path.startswith("/s"):
            # 非列表页：详情页统一在 verify_detail 模式下处理；否则忽略。
            return []
        if "weixin.sogou.com" in host and "/weixin" in path and "type=2" in (p.query or ""):
            discovered: List[str] = []
            def _norm_date(s: str) -> str:
                """规范化日期文本为 YYYY-MM-DD；支持 YYYY-[/-/年]MM-[/-/月]DD。

                若未匹配到合法格式，返回空字符串。
                """
                m = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})", s or "")
                if m:
                    y, mo, d = m.groups()
                    return f"{y}-{int(mo):02d}-{int(d):02d}"
                return ""
            def _extract_date(box: Any) -> str:
                """从卡片节点中提取日期：
                1. 优先解析脚本片段中的 timeConvert(epoch)；
                2. 回退到近邻文本节点的日期字符串；
                3. 再回退到卡片整体文本。
                """
                for s in box.select("script"):
                    txt = s.get_text() or ""
                    m = re.search(r"timeConvert\s*\(\s*['\"]?(\d{5,})['\"]?\s*\)", txt)
                    if m:
                        try:
                            return time.strftime("%Y-%m-%d", time.localtime(int(m.group(1))))
                        except Exception:
                            pass
                for sel in [
                    "p.s-p", "p[class*='s-p']", "span.s-p", "span[class*='s-p']",
                    "span.s2", "span[class*='s2']", "p.txt-info", "div.txt-info",
                ]:
                    el = box.select_one(sel)
                    if el:
                        nd = _norm_date(el.get_text(" ", strip=True))
                        if nd:
                            return nd
                nd = _norm_date(box.get_text(" ", strip=True))
                return nd
            boxes = soup.select("div.news-box, div.txt-box")
            for box in boxes:
                # 寻找标题链接：优先匹配 uigs 前缀，再回退 h3 a、泛 a[href]
                a = None
                for sel in ["a[uigs^='article_title_']", "h3 a", "a[href]"]:
                    t = box.select_one(sel)
                    if t and (t.get("href") or "").strip():
                        a = t
                        break
                if not a:
                    continue
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                # 处理搜狗跳转链接，尝试解码真实的微信文章 URL；失败则使用原链接。
                from urllib.parse import urljoin, urlparse as _u2, parse_qs as _q2, unquote as _uq2
                abs_href = urljoin(url, href)
                qd = _q2(_u2(abs_href).query)
                target = _uq2((qd.get("url", [""])[0] or "").strip())
                final_url = target if (target and "mp.weixin.qq.com" in target) else abs_href
                title_text = a.get_text(strip=True)
                author = ""
                # 作者通常位于 s-p 文本中，直接取近邻节点文本；不做复杂清洗，统一写出。
                auth_el = box.select_one("p.s-p, p[class*='s-p'], span.s-p, span[class*='s-p']")
                if auth_el:
                    author = auth_el.get_text(strip=True)
                dt = _extract_date(box)
                try:
                    # 写入映射与聚合文件；articles_dedup.txt 用于去重 URL。
                    os.makedirs(storage.output_dir, exist_ok=True)
                    if title_text:
                        with open(os.path.join(storage.output_dir, "url_title_map.tsv"), "a", encoding="utf-8") as uf:
                            uf.write(f"{final_url}\t{title_text}\n")
                    if dt:
                        with open(os.path.join(storage.output_dir, "url_date_map.tsv"), "a", encoding="utf-8") as uf:
                            uf.write(f"{final_url}\t{dt}\n")
                    dedup_path = os.path.join(storage.output_dir, "articles_dedup.txt")
                    seen = set()
                    if os.path.exists(dedup_path):
                        with open(dedup_path, "r", encoding="utf-8") as df:
                            seen = set(line.strip() for line in df if line.strip())
                    if final_url not in seen:
                        with open(dedup_path, "a", encoding="utf-8") as df:
                            df.write(final_url + "\n")
                        with open(os.path.join(storage.output_dir, "articles.txt"), "a", encoding="utf-8") as f:
                            f.write(f"{(dt or '-')}\t{(title_text or '-')}\t{final_url}\t{(author or '-')}\n")
                        csv_path = os.path.join(storage.output_dir, "articles.csv")
                        if not os.path.exists(csv_path):
                            with open(csv_path, "w", newline="", encoding="utf-8") as cf:
                                import csv as _csv
                                w = _csv.writer(cf)
                                w.writerow(["date", "title", "url", "author"])
                        with open(csv_path, "a", newline="", encoding="utf-8") as cf:
                            import csv as _csv
                            w = _csv.writer(cf)
                            w.writerow([dt or "-", title_text or "-", final_url, author or "-"])
                except Exception:
                    pass
                # 可选：验证详情页（删除提示）
                try:
                    verify_detail = bool(params.get("verify_detail", False))
                    if verify_detail and "mp.weixin.qq.com" in final_url:
                        # 详情页入队，由调度器后续拉取并触发下方的删除提示清理逻辑。
                        discovered.append(final_url)
                except Exception:
                    pass
            # 计算下一页URL，避免依赖页面上的下一页链接
            follow = bool(params.get("search_follow_pages", False))
            maxp = int(params.get("search_max_pages", 1) or 1)
            if follow and maxp > 0:
                try:
                    # 受控翻页：根据查询参数构造 page=next 的 URL，记录已跟随次数。
                    from urllib.parse import parse_qs, urlencode, urlunparse
                    qmap = parse_qs(p.query or "")
                    qv = (qmap.get("query", [""])[0] or "").strip()
                    cur_page = int((qmap.get("page", ["1"])[0] or "1"))
                    prog_file = os.path.join(storage.output_dir, "search_pages_followed.tsv")
                    seen = {}
                    if os.path.exists(prog_file):
                        with open(prog_file, "r", encoding="utf-8") as pf:
                            for line in pf:
                                line = line.strip()
                                if not line:
                                    continue
                                parts = line.split("\t")
                                if len(parts) == 2:
                                    seen[parts[0]] = int(parts[1]) if parts[1].isdigit() else 0
                    cur_follow = seen.get(qv, 0)
                    if cur_follow < maxp:
                        next_page = cur_page + 1
                        qmap["page"] = [str(next_page)]
                        qmap["type"] = ["2"]
                        qmap["query"] = [qv]
                        new_q = urlencode({k: v[0] if isinstance(v, list) else v for k, v in qmap.items()})
                        next_url = urlunparse((p.scheme or "https", p.netloc, p.path, "", new_q, ""))
                        discovered.append(next_url)
                        seen[qv] = cur_follow + 1
                        with open(prog_file, "w", encoding="utf-8") as pf:
                            for k, v in seen.items():
                                pf.write(f"{k}\t{v}\n")
                except Exception:
                    pass
            return discovered
        if "mp.weixin.qq.com" in host and path.startswith("/s"):
            verify_detail = bool(params.get("verify_detail", False))
            if not verify_detail:
                return []
            def _remove_url_from_outputs(u: str):
                """从聚合输出中删除指定 URL，并记录到 deleted_urls.tsv。"""
                try:
                    out_root = storage.output_dir
                    txt_path = os.path.join(out_root, "articles.txt")
                    if os.path.exists(txt_path):
                        with open(txt_path, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                        with open(txt_path, "w", encoding="utf-8") as f:
                            for ln in lines:
                                if u not in ln:
                                    f.write(ln)
                    csv_path = os.path.join(out_root, "articles.csv")
                    if os.path.exists(csv_path):
                        import csv as _csv
                        with open(csv_path, "r", encoding="utf-8") as cf:
                            rows = list(_csv.reader(cf))
                        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
                            w = _csv.writer(cf)
                            for row in rows:
                                if len(row) >= 3 and row[2] == u:
                                    continue
                                w.writerow(row)
                    dd = os.path.join(out_root, "articles_dedup.txt")
                    if os.path.exists(dd):
                        with open(dd, "r", encoding="utf-8") as df:
                            lines = df.readlines()
                        with open(dd, "w", encoding="utf-8") as df:
                            for ln in lines:
                                if u.strip() != ln.strip():
                                    df.write(ln)
                    with open(os.path.join(out_root, "deleted_urls.tsv"), "a", encoding="utf-8") as df:
                        df.write(f"{u}\tdeleted\n")
                except Exception:
                    pass
            try:
                # 详情页结构：body#activity-detail；删除提示位于 .weui-msg__title.warn。
                body = soup.select_one("body#activity-detail")
                if body:
                    del_title = soup.select_one(".weui-msg .weui-msg__text-area .weui-msg__title.warn")
                    txt = del_title.get_text(strip=True) if del_title else ""
                    if txt and ("该内容已被发布者删除" in txt):
                        _remove_url_from_outputs(url)
                        return []
            except Exception:
                pass
            return []
            return []
        if "weixin.sogou.com" in host and "/link" in path:
            # 忽略搜狗中间页。
            return []

        return []


Plugin = WechatSearchPlugin
