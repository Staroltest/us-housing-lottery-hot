#!/usr/bin/env python3
"""Bloom API 适配器：把 Bloom/Next.js 城市保障房门户的公开 JSON API
（/api/adapter/listings，后端 Bloom 服务）转成生成器条目。

适用源（sources.json 里 adapter="bloom_api"）：
- 湾区 Doorway Housing Portal：https://housingbayarea.mtc.ca.gov
  2026-11-19 实测：旧域名 housing.bayareametro.gov 已无法解析；
  现用域名 housingbayarea.mtc.ca.gov 的 /listings 页 SSR 只返回空
  openListings（__NEXT_DATA__ 里 openListings/closedListings 均为 []），
  必须走前端同款的 /api/adapter/listings：
  GET /api/adapter/listings?limit=100&page=1
      &filter[0][$comparison]==&filter[0][status]=active
  200，totalItems 25（active 全量，单页可取完）；limit=all 会 502，
  不要用。浏览器访问该站会被 CloudFront 按国家拦截（403），但
  服务器端直连返回 200，半小时轮次的抓取不受影响。
  状态枚举里没有 "open"，开放态叫 "active"；filter 须写成索引式
  filter[0][...]，JSON 数组写法会被 400 拒绝。
  2026-11-19 实测：active 25 条，全带真实未来截止日；其中
  lottery 4 + firstComeFirstServe 10（unitsAvailable>0）共 14 条，
  扣掉 2 条 2027-01-01 占位截止日后实收 12 条；waitlist /
  waitlistLottery 11 条不收（与波士顿口径一致：只收直接分房的
  抽签 / 先到先得，不收排队等候名单）。21/25 条近两周内有更新。
  城市取 listingsBuildingAddress.city（奥克兰、都柏林、南旧金山、
  圣克拉拉等 10 城），覆盖湾区 9 县，是旧金山 DAHLIA（仅 SF 市）
  之外的湾区增量。

收录规则（与 tools/fetch_bloom.py 的 SSR 适配器一致）：
- status == "active"
- reviewOrderType in ("lottery", "firstComeFirstServe")
- applicationDueDate >= 今天
- unitsAvailable > 0
- 截止日须在今天起 365 天内，且排除 1 月 1 日：门户用 1 月 1 日
  作默认占位截止日（Doorway 实测：2027-01-01 出现 2 次，跨不相关
  楼盘完全相同，不可能是真实截止日）。

版权与原创（本站硬规则，与 fetch_bloom.py 相同）：
- title 不是官方标题原文：它是事实标识串
  "Bay Area Lottery|First-Come · <City> · <n> units · deadline <date>"，
  只含城市、类型、套数、截止日这些事实；同名同套数同截止日的两条
  用 listing id 后 4 位区分。
  楼盘名只写进内部 summary 事实串（"building (internal ref
  only)"，只进本地 data/store.json，不公开发布）。
- summary 是内部事实串（只进本地 data/store.json）；公开展示的
  简介一律是 data/zh_draft.json 里自己写的 zh_oneliner /
  en_oneliner。
- published 取截止日 23:59（本站时区 Asia/Shanghai 的显示口径），
  与 NYC / DAHLIA / Bloom SSR 适配器一致。注意门户的
  applicationDueDate 是 UTC 时间戳（如 2026-11-20T01:00:00Z），
  门户自己显示的截止日就是该时间戳的日期部分，本适配器同样取
  日期部分。
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))
# 门户对非浏览器 UA 可能 403（洛杉矶门户 2026-11-18 实测），用标准
# 浏览器请求头；5xx 时 5 秒后重试一次。
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "en-US,en;q=0.9"}
MAX_PAGES = 10
PAGE_SIZE = 100
REVIEW_TYPES = {"lottery": "lottery", "firstComeFirstServe": "first-come"}


def _http_get_json(url, timeout=30):
    import time as _time
    last_err = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code >= 500:
                _time.sleep(5)
                continue
            raise
        except Exception as e:  # noqa: BLE001 - 网络抖动重试一次
            last_err = e
            _time.sleep(5)
            continue
    raise last_err


def _d(s):
    """ISO 时间戳 -> date（只取日期部分，与门户显示一致）。"""
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


def categorize(days_left, units):
    if days_left <= 2:
        return "closing-soon"
    if units >= 20:
        return "large"
    return "open"


def fetch_bloom_api_items(src, now):
    """generate.py 的入口：按 sources.json 的源返回条目列表。"""
    today = now.astimezone(CST).date()
    base = (src["url"] or "").rstrip("/")
    city_short = src.get("city_short", "Bay Area")
    listing_base = (src.get("listing_base") or "").rstrip("/")
    horizon = today + timedelta(days=365)
    rows = []
    total_pages = 1
    page = 1
    while page <= min(total_pages, MAX_PAGES):
        qs = urllib.parse.urlencode({
            "limit": PAGE_SIZE,
            "page": page,
            "filter[0][$comparison]": "=",
            "filter[0][status]": "active",
        })
        url = "%s?%s" % (base, qs)
        if page > 1:
            import time as _time
            _time.sleep(1)  # 翻页之间停 1 秒，别把门户打爆
        data = _http_get_json(url)
        listings = data.get("items") or []
        meta = data.get("meta") or {}
        try:
            total_pages = int(meta.get("totalPages") or 1)
        except (TypeError, ValueError):
            total_pages = 1
        print("bloom-api %s: page %d/%d: %d active listings"
              % (city_short, page, total_pages, len(listings)))
        rows.extend(listings)
        page += 1
    print("bloom-api %s: %d active listings fetched" % (city_short, len(rows)))
    items = []
    skipped = 0
    skipped_placeholder = 0
    seen_titles = set()
    for row in rows:
        review = row.get("reviewOrderType")
        if row.get("status") != "active" or review not in REVIEW_TYPES:
            skipped += 1
            continue
        end = _d(row.get("applicationDueDate"))
        if not end or end < today:
            skipped += 1
            continue
        if end > horizon or (end.month == 1 and end.day == 1):
            # 占位截止日（见模块 docstring）：1 月 1 日或一年以上。
            skipped_placeholder += 1
            continue
        units = _int(row.get("unitsAvailable"))
        if units <= 0:
            skipped += 1
            continue
        listing_id = str(row.get("id") or "").strip()
        slug = str(row.get("urlSlug") or "").strip()
        if not listing_id or not slug:
            skipped += 1
            continue
        addr = row.get("listingsBuildingAddress") or {}
        city = (addr.get("city") or "").strip()
        if not city:
            juris = row.get("jurisdictions") or {}
            city = (juris.get("name") or "").strip() or "Bay Area"
        days_left = (end - today).days
        cat = categorize(days_left, units)
        cat_word = {"closing-soon": "closing soon",
                    "large": "large lottery",
                    "open": "open now"}.get(cat, "open now")
        kind = REVIEW_TYPES[review]
        kind_label = "Lottery" if kind == "lottery" else "First-Come"
        # 内部标题：事实标识串，绝不是官方标题原文（见模块 docstring）。
        title = ("%s %s · %s · %d units · deadline %s"
                 % (city_short, kind_label, city, units, end.isoformat()))
        if title in seen_titles:
            title = "%s · #%s" % (title, listing_id[-4:])
        seen_titles.add(title)
        facts = ["%s affordable rental" % kind, cat_word,
                 "deadline %s (%d days left)" % (end.isoformat(), days_left),
                 "%s, %d units" % (city, units)]
        # 楼盘名只作本地起草参考（store.json 不推送）；公开文件里不许出现。
        name = (row.get("name") or "").strip()
        if name:
            facts.append("building (internal ref only): " + name)
        # published = 截止日 23:59（CST 显示口径），见模块 docstring。
        pub = datetime.combine(end, time(23, 59), tzinfo=CST)
        items.append({
            "title": title,
            "link": "%s/%s/%s" % (listing_base, listing_id, slug),
            "source": src["name"],
            "source_id": src["id"],
            "published": pub,
            "summary": " · ".join(facts),
            "category": cat,
        })
    items.sort(key=lambda it: it["published"])
    print("bloom-api %s: %d open dated rentals now (%d skipped, "
          "%d placeholder deadlines skipped)"
          % (city_short, len(items), skipped, skipped_placeholder))
    return items
