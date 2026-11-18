#!/usr/bin/env python3
"""Metrolist 适配器：把波士顿 Metrolist（City of Boston 保障房门户）
的公开房源 JSON 转成生成器条目。

接口：https://www.boston.gov/metrolist/api/v1/developments?_format=json
（公开，无需 key；从搜索页 JS 包里找到的端点：
getDevelopmentsApiEndpoint()）
2026-11-18 实测：200，142 条；字段：title、offer、assignment、
applicationDueDate、units[]（每组 {count, bedrooms, price}）、
neighborhood、city、streetAddress、slug、id、listingDate。
官方链接：https://www.boston.gov/metrolist/search/housing/{slug}
（node/{id} 会 301 到它，实测最终 200）。

收录规则（只收带真实截止日的出租抽签 / 先到先得）：
- offer == "rent"（排除 sale）
- assignment in ("lottery", "first")—— 等候名单（waitlist）不收：
  虽然 84 条等候名单也有未来截止日，但等候名单拼的是排位、
  等待以年计，与本站“抽签日历”的定位不符；且 12 月 31 日在
  等候名单里出现 9 次、抽签/先到先得里出现 5 次，像是系统
  默认的年末截止日。等候名单以后如需加，另议。
- applicationDueDate >= 今天；units（各组 count 之和）> 0
- 同一 id 去重（接口里同一房源会出现两次，如 Oasis at Plainville）
2026-11-18 当天：lottery 7 条 + first 13 条 = 20 条，共 220 套。

已知缺口（2026-11-18 实测，写进报告、不手补）：
- 该端点是 Metrolist 搜索页自己的数据源，但至少有一个已验证
  的在开抽签不在端点里：345 Harrison Ave Unit #2（node 16637266，
  1 居、$1,809/月、Lottery Application Deadline 2026-12-31 23:45，
  2026-11-04 发布），页面 200 且内容齐全，端点里没有它；
  首页的另几个 node 链接（15959741、15965716、13654116）也
  不在端点里，但 15959741 已 301 回 /metrolist，是已下架的旧盘。
  原因未明（可能是单套房源不走 developments 端点），发现
  机制待后续研究；不手补单条，避免破坏适配器模式。

版权与原创（本站硬规则，与 fetch_housing.py 相同）：
- title 不是官方标题原文：它是事实标识串
  "Boston Lottery|First-Come · <City> · <n> units · deadline <date>"，
  只含城市、类型、套数、截止日这些事实；同名同套数同截止日的
  两条用 id 后 4 位区分。楼盘名只写进内部 summary 事实串
  （"building (internal ref only)"，只进本地 data/store.json，
  不公开发布）。
- summary 是内部事实串（只进本地 data/store.json）；公开展示的
  简介一律是 data/zh_draft.json 里自己写的 zh_oneliner /
  en_oneliner。
- published 取截止日 23:59（本站时区 Asia/Shanghai 的显示口径），
  与 NYC / DAHLIA / Bloom 适配器一致。
"""

import json
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "us-housing-lottery-hotBot/1.0"}
API_URL = "https://www.boston.gov/metrolist/api/v1/developments?_format=json"


def _http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _d(s):
    """'2026-12-31' -> date，解析失败返回 None。"""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _units(row):
    total = 0
    for u in (row.get("units") or []):
        try:
            total += int(u.get("count") or 0)
        except (TypeError, ValueError):
            continue
    return total


def categorize(days_left, units):
    if days_left <= 2:
        return "closing-soon"
    if units >= 20:
        return "large"
    return "open"


def fetch_boston_items(src, now):
    """generate.py 的入口：按 sources.json 的源返回条目列表。"""
    today = now.astimezone(CST).date()
    rows = _http_get_json(src["url"] or API_URL)
    if not isinstance(rows, list):
        rows = []
    print("boston: Metrolist developments: %d" % len(rows))
    items = []
    skipped = 0
    seen_ids = set()
    seen_titles = set()
    for row in rows:
        if row.get("offer") != "rent":
            skipped += 1
            continue
        assignment = row.get("assignment")
        if assignment not in ("lottery", "first"):
            skipped += 1
            continue
        end = _d(row.get("applicationDueDate"))
        if not end or end < today:
            skipped += 1
            continue
        units = _units(row)
        if units <= 0:
            skipped += 1
            continue
        listing_id = str(row.get("id") or "").strip()
        slug = str(row.get("slug") or "").strip()
        if not listing_id or not slug:
            skipped += 1
            continue
        if listing_id in seen_ids:
            skipped += 1
            continue
        seen_ids.add(listing_id)
        city = (row.get("city") or "").strip() or "Greater Boston"
        days_left = (end - today).days
        cat = categorize(days_left, units)
        cat_word = {"closing-soon": "closing soon",
                    "large": "large lottery",
                    "open": "open now"}.get(cat, "open now")
        kind = "lottery" if assignment == "lottery" else "first-come"
        kind_label = "Lottery" if assignment == "lottery" else "First-Come"
        # 内部标题：事实标识串，绝不是官方标题原文（见模块 docstring）。
        unit_word = "unit" if units == 1 else "units"
        title = ("Boston %s · %s · %d %s · deadline %s"
                 % (kind_label, city, units, unit_word, end.isoformat()))
        if title in seen_titles:
            title = "%s · #%s" % (title, listing_id[-4:])
        seen_titles.add(title)
        facts = ["%s affordable rental" % kind, cat_word,
                 "deadline %s (%d days left)" % (end.isoformat(), days_left),
                 "%s, %d units" % (city, units)]
        neighborhood = (row.get("neighborhood") or "").strip()
        if neighborhood:
            facts.append("neighborhood %s" % neighborhood)
        # 楼盘名只作本地起草参考（store.json 不推送）；公开文件里不许出现。
        name = (row.get("title") or "").strip()
        if name:
            facts.append("building (internal ref only): " + name)
        # published = 截止日 23:59（CST 显示口径），见模块 docstring。
        pub = datetime.combine(end, time(23, 59), tzinfo=CST)
        items.append({
            "title": title,
            "link": "https://www.boston.gov/metrolist/search/housing/%s" % slug,
            "source": src["name"],
            "source_id": src["id"],
            "published": pub,
            "summary": " · ".join(facts),
            "category": cat,
        })
    items.sort(key=lambda it: it["published"])
    print("boston: %d open dated rentals now (%d skipped: not rent, "
          "not lottery/first-come, past due, or no units)"
          % (len(items), skipped))
    return items
