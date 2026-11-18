#!/usr/bin/env python3
"""Housing 适配器：把 NYC Open Data 的 Housing Connect 公开抽签数据集
（Socrata vy5i-a666）转成生成器条目。

生成器只吃 RSS/Atom，但抽签数据只有公开 JSON API，没有 RSS。
本适配器由 tools/generate.py 的拉源循环按 sources.json 的
"adapter": "housing" 标记调用，返回 parse_feed() 同形的条目 dict：

    {title, link, source, source_id, published (datetime),
     summary, category}

版权与原创（本站硬规则）：
- title 不是官方 listing 标题的复制：它是事实标识串
  "Lottery #<id> · <Borough> · <n> units · deadline <date>"，
  只含抽签编号、区、套数、截止日这些事实。公开 JSON（data/hot.json、
  data/days/*.json）与详情页的“原文标题”栏都会原样露出 title，
  所以 title 里绝不能放官方标题原文。
- summary 是内部事实串（只进本地 data/store.json，不公开发布；
  公开展示的简介一律是 data/zh_draft.json 里自己写的 zh_oneliner /
  en_oneliner）。summary 里可含楼盘名作起草参考，因为 store.json
  本地专用、不推送；公开文件里出现楼盘名原文即视为泄漏，生成后
  要 grep 核查。
- published 取截止日 23:59（本站时区 Asia/Shanghai 的显示口径）：
  对日历站来说，决定一条抽签是否“还活着”的是截止日，不是开盘日；
  用截止日作 published，精选/热点/时间线才能按“还剩几天”排序，
  过了截止日的抽签自然掉出精选与热点。开盘日只写进 summary 事实串。
- Socrata 的 lottery_status='Active' 是状态字段、不是日期过滤：
  2026-11-18 实测 Active 47 条，其中很多行的 lottery_end_date 已
  过期；适配器只收 start <= 今天 <= end 的真正开放抽签（当天 15 条）。
"""

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "us-housing-lottery-hotBot/1.0"}

BOROUGH_ZH = {"BX": "布朗克斯", "BK": "布鲁克林", "QN": "皇后区",
              "MN": "曼哈顿", "SI": "史坦顿岛"}
BOROUGH_EN = {"BX": "Bronx", "BK": "Brooklyn", "QN": "Queens",
              "MN": "Manhattan", "SI": "Staten Island"}


def _http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _d(s):
    """'2026-11-19T00:00:00.000' -> date，解析失败返回 None。"""
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


def _bedroom_mix(row):
    parts = []
    for key, label in (("unit_distribution_studio", "studio"),
                       ("unit_distribution_1bed", "1-bed"),
                       ("unit_distribution_2bed", "2-bed"),
                       ("unit_distribution_3bed", "3-bed")):
        n = _int(row.get(key))
        if n:
            parts.append("%d %s" % (n, label))
    return ", ".join(parts)


def _ami_bands(row):
    parts = []
    for key, label in (("applied_income_ami_ext_low", "extremely low"),
                       ("applied_income_ami_very_low", "very low"),
                       ("applied_income_ami_low", "low"),
                       ("applied_income_ami_moderate", "moderate"),
                       ("applied_income_ami_middle", "middle")):
        n = _int(row.get(key))
        if n:
            parts.append("%d %s AMI" % (n, label))
    return "; ".join(parts)


def categorize(row, today):
    start, end = _d(row.get("lottery_start_date")), _d(row.get("lottery_end_date"))
    if end is not None and (end - today).days <= 2:
        return "closing-soon"
    if start is not None and 0 <= (today - start).days <= 7:
        return "new-this-week"
    if _int(row.get("unit_count")) >= 20:
        return "large"
    return "open"


def fetch_housing_items(src, now):
    """generate.py 的入口：按 sources.json 的源返回条目列表。"""
    today = now.astimezone(CST).date()
    base = src["url"].split("?")[0]
    params = {"$limit": "50000",
              "$where": "lottery_status='Active'",
              "$order": "lottery_end_date ASC"}
    url = base + "?" + urllib.parse.urlencode(params)
    rows = _http_get_json(url)
    print("housing: Socrata Active rows: %d" % len(rows))
    items = []
    skipped_stale = 0
    for row in rows:
        start, end = _d(row.get("lottery_start_date")), _d(row.get("lottery_end_date"))
        if not start or not end or not (start <= today <= end):
            skipped_stale += 1
            continue
        lottery_id = str(row.get("lottery_id", "")).strip()
        if not lottery_id:
            continue
        borough = (row.get("borough") or "").strip().upper()
        borough_en = BOROUGH_EN.get(borough, borough or "NYC")
        units = _int(row.get("unit_count"))
        days_left = (end - today).days
        cat = categorize(row, today)
        cat_word = {"closing-soon": "closing soon",
                    "new-this-week": "new this week",
                    "large": "large lottery",
                    "open": "open now"}.get(cat, "open now")
        # 内部标题：事实标识串，绝不是官方标题原文（见模块 docstring）。
        title = ("Lottery #%s · %s · %d units · deadline %s"
                 % (lottery_id, borough_en, units, end.isoformat()))
        facts = ["lottery affordable rental", cat_word,
                 "deadline %s (%d days left)" % (end.isoformat(), days_left),
                 "open %s to %s" % (start.isoformat(), end.isoformat()),
                 "%s, %d units" % (borough_en, units)]
        mix = _bedroom_mix(row)
        if mix:
            facts.append("bedrooms: " + mix)
        ami = _ami_bands(row)
        if ami:
            facts.append("income bands: " + ami)
        # 楼盘名只作本地起草参考（store.json 不推送）；公开文件里不许出现。
        name = (row.get("lottery_name") or "").strip()
        if name:
            facts.append("building (internal ref only): " + name)
        # published = 截止日 23:59（CST 显示口径），见模块 docstring。
        pub = datetime.combine(end, time(23, 59), tzinfo=CST)
        items.append({
            "title": title,
            "link": "https://housingconnect.nyc.gov/PublicWeb/details/%s" % lottery_id,
            "source": src["name"],
            "source_id": src["id"],
            "published": pub,
            "summary": " · ".join(facts),
            "category": cat,
        })
    print("housing: %d open now (%d stale Active rows skipped, "
          "end date before today or not yet started)" % (len(items), skipped_stale))
    return items
