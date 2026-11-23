#!/usr/bin/env python3
"""DAHLIA 适配器：把旧金山 DAHLIA（San Francisco Housing Portal）
的公开房源 JSON 转成生成器条目。

接口：https://housing.sfgov.org/api/v1/listings.json（公开，无需 key）
2026-11-18 实测：200，114 条；Status=Active 65 条。
字段：Building_Name、Units_Available、Application_Due_Date、
Lottery_Results_Date、Listing_Type、Tenure、Status、listingID、
Accepting_Online_Applications。

收录规则（只收出租，不收卖房；抽签、先到先得与等候名单都收，
但等候名单必须在标题与简介里如实标为等候名单、不是抽签）：
- Status == "Active"
- Tenure in ("Re-rental", "New rental") —— 排除 Resale / New sale
- Application_Due_Date >= 今天
2026-11-18 当天：开放出租 4 条（另有 5 条在售房源被排除）。
Listing_Type 分三类：Standard Lottery（抽签）、First Come, First Served
（先到先得）、Waitlist Listing（等候名单）；内部标题的种类词按
Listing_Type 如实写，绝不把等候名单写成 Lottery。

版权与原创（本站硬规则，与 fetch_housing.py 相同）：
- title 不是官方标题原文：它是事实标识串
  "SF Lottery|First-Come|Waitlist · San Francisco · <n> unit(s) · deadline <date>"，
  种类词按 Listing_Type 如实写（Waitlist Listing 绝不写成 Lottery），
  只含城市、套数、截止日这些事实；同名同套数同截止日的两条
  用 listingID 后 4 位区分。楼盘名只写进内部 summary 事实串
  （"building (internal ref only)"，只进本地 data/store.json，
  不公开发布）。
- summary 是内部事实串（只进本地 data/store.json）；公开展示的
  简介一律是 data/zh_draft.json 里自己写的 zh_oneliner /
  en_oneliner。
- published 取截止日 23:59（本站时区 Asia/Shanghai 的显示口径），
  与 NYC 适配器一致：决定一条抽签是否“还活着”的是截止日。
- 官方链接：https://housing.sfgov.org/listings/{listingID}
  （2026-11-18 实测 200）。
"""

import json
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "us-housing-lottery-hotBot/1.0"}
API_URL = "https://housing.sfgov.org/api/v1/listings.json"
RENTAL_TENURES = ("Re-rental", "New rental")


def _http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _d(s):
    """'2026-12-15T01:00:00.000+0000' -> date，解析失败返回 None。"""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def categorize(row, today, units):
    end = _d(row.get("Application_Due_Date"))
    if end is not None and (end - today).days <= 2:
        return "closing-soon"
    if units >= 20:
        return "large"
    return "open"


def fetch_dahlia_items(src, now):
    """generate.py 的入口：按 sources.json 的源返回条目列表。"""
    today = now.astimezone(CST).date()
    data = _http_get_json(src["url"] or API_URL)
    rows = data.get("listings", []) if isinstance(data, dict) else []
    print("dahlia: DAHLIA listings: %d" % len(rows))
    items = []
    skipped = 0
    seen_titles = set()
    for row in rows:
        if row.get("Status") != "Active":
            skipped += 1
            continue
        if row.get("Tenure") not in RENTAL_TENURES:
            skipped += 1
            continue
        end = _d(row.get("Application_Due_Date"))
        if not end or end < today:
            skipped += 1
            continue
        listing_id = str(row.get("listingID") or row.get("Id") or "").strip()
        if not listing_id:
            skipped += 1
            continue
        units = _int(row.get("Units_Available"))
        days_left = (end - today).days
        cat = categorize(row, today, units)
        cat_word = {"closing-soon": "closing soon",
                    "large": "large lottery",
                    "open": "open now"}.get(cat, "open now")
        listing_type = (row.get("Listing_Type") or "").strip()
        tenure = (row.get("Tenure") or "").strip()
        # 种类词按 Listing_Type 如实写：等候名单绝不写成 Lottery
        # （2026-11-24 把关发现两条 Waitlist Listing 的内部标题写成了
        # SF Lottery，虽未上屏——展示用的是 zh/en 改写标题——但作为
        # 缺改写时的兜底标题仍会误导读者）。
        _lt = listing_type.lower()
        if "waitlist" in _lt:
            kind_label, kind_word = "Waitlist", "waitlist"
        elif "first come" in _lt:
            kind_label, kind_word = "First-Come", "first-come"
        else:
            kind_label, kind_word = "Lottery", "lottery"
        # 内部标题：事实标识串，绝不是官方标题原文（见模块 docstring）。
        unit_word = "unit" if units == 1 else "units"
        title = ("SF %s · San Francisco · %d %s · deadline %s"
                 % (kind_label, units, unit_word, end.isoformat()))
        if title in seen_titles:
            title = ("%s · #%s" % (title, listing_id[-4:]))
        seen_titles.add(title)
        facts = ["%s affordable rental" % kind_word, cat_word,
                 "deadline %s (%d days left)" % (end.isoformat(), days_left),
                 "San Francisco, %d units" % units,
                 "tenure %s" % tenure.lower(),
                 "listing type %s" % listing_type.lower()]
        results = _d(row.get("Lottery_Results_Date"))
        if results:
            facts.append("lottery results %s" % results.isoformat())
        if row.get("Accepting_Online_Applications"):
            facts.append("applying online")
        # 楼盘名只作本地起草参考（store.json 不推送）；公开文件里不许出现。
        name = (row.get("Building_Name") or row.get("Name") or "").strip()
        if name:
            facts.append("building (internal ref only): " + name)
        # published = 截止日 23:59（CST 显示口径），见模块 docstring。
        pub = datetime.combine(end, time(23, 59), tzinfo=CST)
        items.append({
            "title": title,
            "link": "https://housing.sfgov.org/listings/%s" % listing_id,
            "source": src["name"],
            "source_id": src["id"],
            "published": pub,
            "summary": " · ".join(facts),
            "category": cat,
        })
    items.sort(key=lambda it: it["published"])
    print("dahlia: %d open rentals now (%d skipped: not Active, "
          "not rental tenure, or past due)" % (len(items), skipped))
    return items
