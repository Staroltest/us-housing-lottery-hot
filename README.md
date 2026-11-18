# 美国保障房抽签HOT / US Housing Lottery HOT

纽约保障房抽签日历：首版只收 Housing Connect 公开抽签，按截止日排序，
快截止的置顶，每半小时刷新。站：https://Staroltest.github.io/us-housing-lottery-hot

## 这站收什么

- 信源（唯一，T1）：NYC Open Data 公开数据集 vy5i-a666
  （Advertised Lotteries on Housing Connect by Lottery），
  `https://data.cityofnewyork.us/resource/vy5i-a666.json`
- 2026-11-18 实测：`lottery_status='Active'` 共 47 条，但 Active 是状态
  字段、不是日期过滤，其中很多行已过截止日；适配器只收
  `start <= 今天 <= end` 的真正开放抽签，当天 15 条。
- 首版只做 NYC。其它城市系统割裂、无统一公开 API，先不编造信源。

## 分类

| key | 中文 | 规则 |
| --- | --- | --- |
| closing-soon | 即将截止 | 截止日在 2 天内（含今天） |
| new-this-week | 本周新开 | 开盘日在 7 天内 |
| large | 大盘多套 | 套数 ≥ 20 |
| open | 正在开放 | 其余开放抽签 |

区（布朗克斯 / 布鲁克林 / 皇后区 / 曼哈顿 / 史坦顿岛）写进标题与简介，
不单独成类——单分类模型下，截止 urgency 优先于区。

## 版权与原创（硬规则）

- 公开文件里只有：本站自己改写的标题 + 一句自己写的一句话简介
  （含一句自己的点评，如还剩几天、适合谁）+ 事实字段（区、套数、
  截止日）+ 官方申请链接。
- 绝不把 Housing Connect 的原文标题、正文、摘要复制进任何公开文件。
- `tools/fetch_housing.py` 的内部 `title` 是事实标识串
  `Lottery #<id> · <Borough> · <n> units · deadline <date>`，
  不是官方标题原文——因为生成器的公开 JSON 与详情页“原文标题”栏
  都会原样露出 `title`。
- 内部 `summary` 是事实串，只进本地 `data/store.json`（不推送），
  公开展示的简介一律是 `data/zh_draft.json` 里的 `zh_oneliner` /
  `en_oneliner`。`en_oneliner` 只翻译自家的 `zh_oneliner`。
- 英文树零中文：标题、简介、关于页、页脚、分类、日报全部英文。

## 生成器改动（相对模板）

- 新增 `tools/fetch_housing.py`（Socrata 适配器，见上）。
- `tools/generate.py` 最小改动：`adapter == "housing"` 分支（hk-ipo-hot
  同款）+ 已收录条目刷新可变事实（标题/事实串/截止日/分类）；
  `enrich_store_item` 保留适配器算好的分类；`hot_score` 对未来
  截止日不做反向衰减（否则最远的截止日会冲到榜首）；
  时间线按截止日升序（最先截止的在前）。
- `published` 取截止日 23:59（本站时区口径）：对日历站，决定一条
  抽签是否“还活着”的是截止日；过了截止日的抽签自然掉出精选与热点，
  30 天后出全部动态。
- 赞赏码：`site.tips` 为空，模板自带的他人收款二维码已从 `assets/`
  删除。用户确认自己的加密钱包收款地址后，再按 `config.json` 的
  `site.tips` 格式补上。

## 本地运行

```bash
cd ~/workspace/us-housing-lottery-hot
python3 tools/generate.py            # 半小时轮次
python3 tools/generate.py --daily    # 06:00 那轮出日报
python3 tools/geo_audit.py           # 只做自检
```

`data/store.json` 与 `data/zh_draft.json` 是本机文件，不推送。
推送不走 git（本机无 `~/.git-credentials`，PAT 只覆盖 api.github.com）：
用 GitHub Contents / Git Data API 推，见 `docs/` 里的半小时任务模板。

## 待办（v1 未完成）

- GitHub Pages：在仓库 Settings → Pages 开 main / root（PAT 无
  Administration 权限，需浏览器/用户操作）。
- Cloudflare Pages 镜像：项目 `us-housing-lottery-hot`；本机没有
  `custom.cloudflare/bin/cf.py`，需走 Cloudflare Pages 直接上传 API。
- Cloudflare Web Analytics：镜像上线后在后台给该项目开 Web Analytics，
  把 beacon token 填进 `config.json` 的 `site.web_analytics_token`。
- 赞赏码：等用户给加密钱包收款地址。

## 许可

MIT License。流水线源自 HOT 模板（MIT）。
