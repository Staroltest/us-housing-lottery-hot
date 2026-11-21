#!/usr/bin/env python3
"""Bloom 适配器：把 Bloom/Next.js 城市保障房门户的公开房源
（服务端渲染页里 <script id="__NEXT_DATA__"> 内嵌的 openListings）
转成生成器条目。

适用源（sources.json 里 adapter="bloom"，用 city / city_short /
listing_base 区分）：
- 洛杉矶 Access Housing LA：https://access.housing.lacity.gov/listings
  2026-11-18 实测：200，分页 27 页、共 267 条在开房源；__NEXT_DATA__
  里 openListings[] 带 applicationDueDate、unitsAvailable、urlSlug、
  reviewOrderType、status、updatedAt；单条页
  /listing/{id}/{urlSlug} 200。
  2026-11-21 门户改版：/listings 页变成客户端拉数空壳，__NEXT_DATA__
  里 openListings/closedListings 均为 []、paginationData 为 null，
  SSR 每轮抓到 0 条（页面仍 200）。改走前端同款的
  /api/adapter/listings（Doorway 门户同款端点，见
  tools/fetch_bloom_api.py）：
  GET /api/adapter/listings?limit=100&page=N
      &filter[0][$comparison]==&filter[0][status]=active
  200，totalItems 269（3 页），行结构与 SSR 完全一致。
  注意该端点忽略 reviewOrderType 追加过滤（实测加 filter[1]
  后仍返回全量 269 条），只能取 active 全量、本地再筛。
  响应很大（单页 40–70MB 全量房源对象），下载约 1 分钟/页。
- 圣何塞 Housing Portal：https://housing.sanjoseca.gov/listings
  2026-11-18 实测：200，单页 48 条在开房源，同格式。

收录规则（只收带真实截止日的出租抽签 / 先到先得）：
- status == "active"
- reviewOrderType in ("lottery", "firstComeFirstServe")
- applicationDueDate >= 今天
- unitsAvailable > 0（等候名单类条目 unitsAvailable 常为 0，无法
  给出套数，不收）
- 截止日须在今天起 365 天内，且排除 1 月 1 日：门户用 1 月 1 日
  作默认占位截止日（圣何塞实测：2027-01-01 出现 6 次、2030-01-01
  5 次、2031-01-01 3 次，跨不相关楼盘完全相同，不可能是真实截止日）。
  被占位规则滤掉的条数会打印出来。
没有公开 JSON API（/api/listings 返回 404；?limit=100 不改每页
10 条），只能按 ?page=1..N 翻页，上限 40 页。
例外：某站 SSR 变空壳时（LA 2026-11-21），改走前端同款的
/api/adapter/listings（见 _api_page），先 SSR、空了再回退，
圣何塞等 SSR 正常的站不受影响。

版权与原创（本站硬规则，与 fetch_housing.py 相同）：
- title 不是官方标题原文：它是事实标识串
  "<City short> Lottery|First-Come · <City> · <n> units ·
  deadline <date>"，只含城市、类型、套数、截止日这些事实；
  同名同套数同截止日的两条用 listing id 后 4 位区分。
  楼盘名只写进内部 summary 事实串（"building (internal ref
  only)"，只进本地 data/store.json，不公开发布）。
- summary 是内部事实串（只进本地 data/store.json）；公开展示的
  简介一律是 data/zh_draft.json 里自己写的 zh_oneliner /
  en_oneliner。
- published 取截止日 23:59（本站时区 Asia/Shanghai 的显示口径），
  与 NYC / DAHLIA 适配器一致。注意门户的 applicationDueDate 是
  UTC 时间戳（如 2026-12-18T07:59:00Z），门户自己显示的截止日
  就是该时间戳的日期部分，本适配器同样取日期部分。
"""

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))
# 洛杉矶门户对非浏览器 UA 会 403（2026-11-18 实测：自定义 bot UA
# 在 generate 轮次里 403，标准浏览器 UA 则 200）。用标准浏览器
# 请求头；翻页之间停 1 秒，403/429/5xx 时 5 秒后重试一次。
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9"}
API_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
          "Accept": "application/json, text/plain, */*",
          "Accept-Language": "en-US,en;q=0.9"}
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
MAX_PAGES = 40
API_PAGE_SIZE = 100
API_MAX_PAGES = 10
REVIEW_TYPES = {"lottery": "lottery", "firstComeFirstServe": "first-come"}


def _http_get(url, timeout=30):
    import time as _time
    import urllib.error
    last_err = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429) or e.code >= 500:
                _time.sleep(5)
                continue
            raise
        except Exception as e:  # noqa: BLE001 - 网络抖动重试一次
            last_err = e
            _time.sleep(5)
            continue
    raise last_err


def _api_page(base, page):
    """前端同款 /api/adapter/listings（见模块 docstring）：取
    status=active 全量一页。行结构与 SSR 的 openListings 完全一致。
    响应很大（单页可达 70MB），超时放宽到 180 秒；5xx 重试一次。"""
    import time as _time
    import urllib.error
    qs = urllib.parse.urlencode({
        "limit": API_PAGE_SIZE,
        "page": page,
        "filter[0][$comparison]": "=",
        "filter[0][status]": "active",
    })
    # 端点挂在站点根下，不是 /listings 子路径：/api/adapter/listings。
    parts = urllib.parse.urlparse(base)
    api_root = "%s://%s" % (parts.scheme, parts.netloc)
    url = "%s/api/adapter/listings?%s" % (api_root, qs)
    last_err = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=API_UA)
            with urllib.request.urlopen(req, timeout=180) as r:
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


def _page_listings(html):
    m = NEXT_DATA_RE.search(html)
    if not m:
        return [], 1
    try:
        props = json.loads(m.group(1))["props"]["pageProps"]
    except (KeyError, ValueError):
        return [], 1
    listings = props.get("openListings") or []
    total_pages = 1
    pag = props.get("paginationData") or {}
    try:
        total_pages = int(pag.get("totalPages") or 1)
    except (TypeError, ValueError):
        total_pages = 1
    return listings, total_pages


def categorize(days_left, units):
    if days_left <= 2:
        return "closing-soon"
    if units >= 20:
        return "large"
    return "open"


def fetch_bloom_items(src, now):
    """generate.py 的入口：按 sources.json 的源返回条目列表。"""
    today = now.astimezone(CST).date()
    base = (src["url"] or "").rstrip("/")
    city = src.get("city", "")
    city_short = src.get("city_short", city)
    listing_base = (src.get("listing_base") or "").rstrip("/")
    horizon = today + timedelta(days=365)
    rows = []
    html = _http_get(base)
    listings, total_pages = _page_listings(html)
    print("bloom %s: page 1/%d: %d open listings"
          % (city_short, total_pages, len(listings)))
    if listings:
        rows.extend(listings)
        page = 2
        while page <= min(total_pages, MAX_PAGES):
            import time as _time
            _time.sleep(1)  # 翻页之间停 1 秒，别把市政门户打爆
            html = _http_get("%s?page=%d" % (base, page))
            listings, total_pages = _page_listings(html)
            print("bloom %s: page %d/%d: %d open listings"
                  % (city_short, page, total_pages, len(listings)))
            rows.extend(listings)
            page += 1
    else:
        # SSR 为空：门户改版为客户端拉数（LA 2026-11-21 实测：
        # __NEXT_DATA__ 里 openListings/closedListings 均为 []，
        # paginationData 为 null，页面只剩空壳），改走前端同款的
        # /api/adapter/listings（Doorway 门户同款端点，见
        # tools/fetch_bloom_api.py）。行结构与 SSR 完全一致，
        # 下游过滤共用。SSR 正常的站（圣何塞）不会走到这里。
        print("bloom %s: SSR empty, falling back to /api/adapter/listings"
              % city_short)
        total_pages = 1
        page = 1
        while page <= min(total_pages, API_MAX_PAGES):
            if page > 1:
                import time as _time
                _time.sleep(1)
            data = _api_page(base, page)
            api_listings = data.get("items") or []
            meta = data.get("meta") or {}
            try:
                total_pages = int(meta.get("totalPages") or 1)
            except (TypeError, ValueError):
                total_pages = 1
            print("bloom %s: api page %d/%d: %d active listings"
                  % (city_short, page, total_pages, len(api_listings)))
            rows.extend(api_listings)
            page += 1
    print("bloom %s: %d open listings fetched" % (city_short, len(rows)))
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
    print("bloom %s: %d open dated rentals now (%d skipped, "
          "%d placeholder deadlines skipped)"
          % (city_short, len(items), skipped, skipped_placeholder))
    return items
