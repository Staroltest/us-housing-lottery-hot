# 定时任务模板：每日精选把关

> 用法：创建 cron 时占位符已按 2026-11-18 的真实值填好，正文作为任务 body。schedule：daily，06:00 之后
> 约 1.5 小时（例如日报 06:00 则把关 07:42），归属新站的 goal。

> 本机实测（2026-11-18）：推送不走 git，见半小时任务模板顶部的“本机实测”；
> 部署与赞赏码同上。GitHub Pages 尚未开通。
>
---

美国保障房抽签HOT 每日精选把关（纽约 Housing Connect 公开抽签（首版只做 NYC），循环持续跑、没用户命令不许停；绝不要自己停掉或删除这个任务）。

站点：https://Staroltest.github.io/us-housing-lottery-hot；仓库 Staroltest/us-housing-lottery-hot（main 分支）；本地工作目录 ~/workspace/us-housing-lottery-hot；另有个持久 git 检出 （不设：本机不走 git 推送，见顶部“本机实测”）（与仓库 main 同步，专门用来推）。更新主力是每半小时跑一次的 us-housing-lottery-hot-half-hourly-update 任务（拉源、翻译、上传全包，北京时间 06:00 那轮出日报）；GitHub Actions 已停用。你的工作是每天一次精选把关，不是 24 小时在线。翻译不再是你的活——新条目翻译由半小时任务负责；你只管精选质量、权重、信源，包括主动找新源。

每轮做：
1. 看今天的精选质量：读线上 data/hot.json（今日精选 10 条、热点 20 条）与 data/daily.json（当日日报），以及仓库里的 config.json（打分权重、精选门槛）与 sources.json（信源列表）。判断精选是不是真对美国大城市中低收入租房者，追新开抽签、怕错过截止日的人有用（分类：closing-soon 即将截止 / open 正在开放 / new-this-week 本周新开 / large 大盘多套）；跑题内容、促销、纯资讯进了精选就是问题。英文版同查一遍：en/data/hot.json 与 en/data/daily.json 的英文标题/简介是否对味、有无中文简介泄露。
2. 查信源健康：有没有源连续多天 0 条、403/超时、重复。已知：唯一信源 NYC Open Data vy5i-a666；Active 状态含过期行，适配器按日期过滤（2026-11-18 当天 47 Active → 15 条真正开放）。赞赏码已配好（USDT TRC20 + Solana，用户自己的地址），不要动 config.json 的 site.tips。。
3. 主动找新源，不能只减不增：对照分类（closing-soon 即将截止 / open 正在开放 / new-this-week 本周新开 / large 大盘多套）与不活跃的源找缺口，中英都搜、优先中文源；每个候选逐个实测——订阅源可达、近两周内有更新、内容是 美国大城市中低收入租房者，追新开抽签、怕错过截止日的人 愿意点进去看、看完对工作有用的；玩家新闻、促销、抽奖占多数的源不收。测过的留下来、定个合适的分级，先观察一两天，质量不行就降级或摘掉；每个测过的候选（收了还是没收、为什么）都记下来。没有合格的候选就如实记一笔，绝不硬凑。
4. 需要调权重、改门槛、修信源时：在 ~/workspace/us-housing-lottery-hot 里改 config.json / sources.json，本地跑 python3 tools/generate.py --daily 验证生成正常，再把改动推到仓库。若本轮动了 data/zh_draft.json（一般不动），合并必须字段级：按链接、按字段取并集，同一字段冲突保留本地，`en_title` / `en_oneliner` 永不丢。**推送走 git + key（不再弹确认卡）**：先 `cd （不设：本机不走 git 推送，见顶部“本机实测”） && git pull --ff-only` 同步到最新头（pull 失败或检出坏了就重 clone），再用 rsync 把工作目录的改动同步进检出（`rsync -a --delete --exclude='.git/' --exclude='.github/' --exclude='__pycache__/' --exclude='*.pyc' --exclude='data/store.json' ~/workspace/us-housing-lottery-hot/ （不设：本机不走 git 推送，见顶部“本机实测”）/`），然后 `git add -A`、`git commit -m "美国保障房抽签HOT 把关：<改了什么>"`、`git push origin main`（走 ~/.git-credentials 里的 key 自动认证）。推送铁律：绝对不要把 .github/workflows/daily.yml 放进推送——工作流文件本身只能走浏览器改，不要碰。推完核对新头 hash 与本地一致。推送失败就记下来下一轮再推，不要强行重试。
5. 只在有事时向用户汇报（主聊天）：改了权重/信源、新增了信源（加了谁、为什么加）、某源死了、精选质量明显变差、或需要她拍板。什么都没变就保持沉默，不要发“一切正常”的消息。不要改 MEMORY.md；观察记到 ~/memory/YYYY-MM-DD.md。
