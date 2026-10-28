"""极简联网搜索:抓 Bing CN 结果页(失败回落百度),仅标准库。"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_BING_ITEM = re.compile(r'<li class="b_algo".*?(?=<li class="b_algo"|</ol>)', re.S)
_BING_TITLE = re.compile(r"<h2[^>]*>\s*<a[^>]*href=\"(.*?)\"[^>]*>(.*?)</a>", re.S)
_BING_SNIP = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_BAIDU_ITEM = re.compile(r'<div[^>]*class="result[^"]*".*?(?=<div[^>]*class="result|</body>)', re.S)
_BAIDU_TITLE = re.compile(r"<h3[^>]*>.*?<a[^>]*>(.*?)</a>", re.S)
_NEWS_Q = re.compile(r"新闻|热点|热搜|头条|时事|要闻|最新消息|发生了什么|大事")
_NEWS_RSS = "https://www.chinanews.com.cn/rss/scroll-news.xml"
_RSS_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_RSS_TITLE = re.compile(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
_RSS_DESC = re.compile(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", re.S)
_RSS_DATE = re.compile(r"<pubDate>(.*?)</pubDate>", re.S)


def _text(s: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", s))).strip()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _bing(q: str, n: int, timeout: float):
    body = _fetch("https://cn.bing.com/search?q=" + urllib.parse.quote(q)
                  + "&setlang=zh-cn", timeout)
    out = []
    for block in _BING_ITEM.findall(body):
        tm = _BING_TITLE.search(block)
        if not tm:
            continue
        title = _text(tm.group(2))
        if not title:
            continue
        snips = [_text(s).replace("阅读更多", "").strip()
                 for s in _BING_SNIP.findall(block)]
        snippet = max(snips, key=len) if snips else ""
        out.append({"title": title, "snippet": snippet, "url": tm.group(1)})
        if len(out) >= n:
            break
    return out


def _baidu(q: str, n: int, timeout: float):
    body = _fetch("https://www.baidu.com/s?wd=" + urllib.parse.quote(q), timeout)
    out = []
    for block in _BAIDU_ITEM.findall(body):
        tm = _BAIDU_TITLE.search(block)
        if not tm:
            continue
        title = _text(tm.group(1))
        if not title:
            continue
        snippet = ""
        for part in re.findall(r'class="[^"]*(?:abstract|content-right)[^"]*"[^>]*>(.*?)</', block, re.S):
            t = _text(part)
            if len(t) > 20:
                snippet = t
                break
        out.append({"title": title, "snippet": snippet, "url": ""})
        if len(out) >= n:
            break
    return out


def _news(n: int, timeout: float):
    body = _fetch(_NEWS_RSS, timeout)
    out = []
    for it in _RSS_ITEM.findall(body):
        tm = _RSS_TITLE.search(it)
        if not tm:
            continue
        title = _text(tm.group(1))
        if not title:
            continue
        dm = _RSS_DESC.search(it)
        snippet = _text(dm.group(1))[:120] if dm else ""
        date = ""
        d = _RSS_DATE.search(it)
        if d:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(d.group(1).strip())
                date = dt.strftime("%m月%d日 %H:%M")
            except Exception:
                date = ""
        out.append({"title": title, "snippet": snippet, "url": "", "date": date})
        if len(out) >= n:
            break
    return out


def search(query: str, n: int = 4, timeout: float = 6.0):
    """返回 [{title, snippet, url}];整体失败给 []。"""
    q = (query or "").strip()
    if not q:
        return []
    if _NEWS_Q.search(q):
        try:
            res = _news(n, timeout)
        except Exception:
            res = []
        if res:
            return res
    for fn in (_bing, _baidu):
        try:
            res = fn(q, n, timeout)
        except Exception:
            res = []
        if res:
            return res
    return []


def history_lines(results, max_items: int = 6) -> str:
    """从搜索结果里抽出带年份的历史事件,避免模型被导航页摘要干扰。"""
    import time as _time
    this_year = _time.localtime().tm_year
    seen, lines = set(), []
    for r in results or []:
        blob = f"{r.get('title','')} {r.get('snippet','')}"
        for m in re.finditer(r"(\d{3,4})年(?:\d{1,2}月\d{1,2}日)?[^。；;\n]{4,70}", blob):
            year = int(m.group(1))
            if year >= this_year:
                continue
            line = _WS.sub(" ", m.group(0)).strip(" ,，.。;；")
            if re.search(r"查询|提供|了解|探索|更新|官网|百科", line):
                continue
            if line in seen:
                continue
            seen.add(line)
            lines.append(f"{len(lines)+1}. {line}")
            if len(lines) >= max_items:
                return "\n".join(lines)
    return "\n".join(lines)


def format_results(results, max_chars: int = 600) -> str:
    lines = []
    for i, r in enumerate(results or [], 1):
        s = f"{i}. {r.get('title','')}"
        if r.get("date"):
            s += f"（{r['date']}）"
        if r.get("snippet"):
            s += f": {r['snippet']}"
        lines.append(s)
    text = "\n".join(lines)
    return text[:max_chars]
