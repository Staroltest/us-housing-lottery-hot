#!/usr/bin/env python3
"""IndexNow 提交脚本（美国保障房抽签HOT）。

用法：
  python3 tools/submit_indexnow.py <url1> <url2> ...
  python3 tools/submit_indexnow.py --file <urls.txt>   # 每行一个 URL

只提交规范 host（config.json 里 site.url）下的增量 URL，绝不全量提交 sitemap。
POST https://api.indexnow.org/indexnow，JSON：{host, key, keyLocation, urlList}。
key 取 config.json 顶层 indexnow_key；keyLocation 为 {site.url}/{key}.txt。
非 200 / 超时 / 异常时只打印失败信息并以 exit 2 退出，不重试、不改写任何文件；
调用方（半小时轮次）负责把失败记到 ~/memory/YYYY-MM-DD.md 并留待下轮重试。
注意：200 只代表 Bing“已接受”，不代表已收录；效果看 1-2 周 Bing 抓取/收录数。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_URL = "https://api.indexnow.org/indexnow"
TIMEOUT = 20


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    args = sys.argv[1:]
    urls = []
    if args and args[0] == "--file":
        if len(args) < 2:
            print("submit_indexnow: --file 需要一个文件路径", file=sys.stderr)
            return 2
        with open(args[1], encoding="utf-8") as f:
            urls = [ln.strip() for ln in f if ln.strip()]
    else:
        urls = [a.strip() for a in args if a.strip()]
    if not urls:
        print("submit_indexnow: 没有要提交的 URL", file=sys.stderr)
        return 2

    cfg = load_config()
    key = cfg.get("indexnow_key", "")
    site_url = cfg.get("site", {}).get("url", "")
    if not key or not site_url:
        print("submit_indexnow: config.json 缺 indexnow_key 或 site.url", file=sys.stderr)
        return 2
    host = urllib.parse.urlparse(site_url).netloc
    key_location = f"{site_url.rstrip('/')}/{key}.txt"

    # 只提交规范 host 下的 URL，其他一律跳过并告警。
    kept, skipped = [], []
    for u in urls:
        if urllib.parse.urlparse(u).netloc == host:
            kept.append(u)
        else:
            skipped.append(u)
    for u in skipped:
        print(f"submit_indexnow: 跳过非规范 host：{u}", file=sys.stderr)
    if not kept:
        print("submit_indexnow: 没有规范 host 下的 URL 可提交", file=sys.stderr)
        return 2

    payload = json.dumps({
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": kept,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")[:500]
            print(f"submit_indexnow: HTTP {resp.status}，提交 {len(kept)} 条：{body!r}")
            return 0 if resp.status in (200, 202) else 2
    except urllib.error.HTTPError as e:
        print(f"submit_indexnow: HTTP {e.code}，提交失败：{e.read().decode('utf-8', 'replace')[:500]!r}",
              file=sys.stderr)
        return 2
    except Exception as e:  # 超时、DNS、代理等：只报错，不重试
        print(f"submit_indexnow: 提交异常（{type(e).__name__}）：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
