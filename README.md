# streamstack-labs

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

StreamStack 系统实验室工具集的独立开源版本（GPL-3.0）。

每个模块均可独立使用，无需 StreamStack 主体。

## 模块列表

| 模块 | 说明 | 依赖 |
|---|---|---|
| `media_parser` | 媒体文件名解析 + 分类策略 | 无（标准库） |
| `douban` | 豆瓣数据获取工具 | httpx |
| `torrent_incubator` | 种子孵化器（监控目录 → qBittorrent） | httpx, pyyaml |
| `tmdb_hosts` | TMDB 防污染：境外多路 DNS 查询 + hosts 生成 | httpx |
| `ep_rules` | 集号偏移 + 季号覆盖规则引擎 | 无（标准库） |
| `notify` | 消息推送工具（PushDeer / Telegram / 企业微信） | httpx |
| `hdhive_checkin` | 影巢 HDHive 每日签到 + 积分查询 | httpx |

## 安装

```bash
pip install httpx pyyaml
```

克隆仓库后直接 import，或将对应目录加入 `PYTHONPATH`。

---

## media_parser — 媒体文件名解析

零依赖，仅使用 Python 标准库。

### 文件名解析

```python
from media_parser import mp_style_parse

# 标准剧集
print(mp_style_parse("她的盛焰 S01E05 2160p.mkv"))
# {'title': '她的盛焰', 'season': 1, 'episode': 5, 'videoFormat': '2160P', ...}

# 动漫 dash 格式
print(mp_style_parse("[ANi] 剑来 - 05 [1080p].mkv"))
# {'title': '剑来', 'season': None, 'episode': 5, 'videoFormat': '1080P', ...}

# 中文集数
print(mp_style_parse("庆余年 第二季 第10集 WEB-DL 2160p.mkv"))
# {'title': '庆余年', 'season': 2, 'episode': 10, ...}
```

返回字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | 提取出的完整标题 |
| `cn_name` | str | 中文部分 |
| `en_name` | str | 英文部分 |
| `year` | str \| None | 发行年份 |
| `season` | int \| None | 季数 |
| `episode` | int \| None | 集数（起始） |
| `episode_end` | int \| None | 集数（结束，多集合并时） |
| `videoFormat` | str | `"1080P"` / `"2160P"` / `"4K"` 等 |
| `videoCodec` | str | `"H265"` / `"HEVC"` / `"AV1"` 等 |
| `audioCodec` | str | `"DTS"` / `"AAC"` / `"TrueHD"` 等 |
| `is_special` | bool | 是否为 OVA/SP/特别篇 |
| `is_anime` | bool | 是否检测到动漫格式特征 |

### 媒体分类

```python
from media_parser import guess_category, evaluate_category_policy

# 基于 TMDB 元数据快速分类
media_info = {
    "genre_ids": [16],
    "original_language": "ja",
    "origin_country": ["JP"],
}
print(guess_category("tv", media_info))   # "日番"
print(guess_category("movie", {"genre_ids": [16]}))  # "动画电影"

# 使用自定义 YAML 策略
custom_policy = """
movie:
  国产电影:
    original_language: 'zh'
  好莱坞:
    origin_country: 'US'
  其他:
"""
print(evaluate_category_policy(
    {"original_language": "zh"}, custom_policy, "movie"
))  # "国产电影"
```

---

## douban — 豆瓣工具

需要 `httpx`。

```python
import asyncio
from douban import check_cookie, get_wish_list, get_cast_cn, search_douban

async def main():
    # 验证 Cookie
    result = await check_cookie("dbcl2=12345678:xxxx; ck=yyyy")
    print(result)  # {"valid": True, "user_id": "12345678", "name": "用户名"}

    # 获取「想看」列表
    if result["valid"]:
        wishlist = await get_wish_list(
            cookie="dbcl2=12345678:xxxx; ck=yyyy",
            user_id=result["user_id"],
            media_type="all",  # "movie" | "tv" | "all"
        )
        for item in wishlist[:3]:
            print(item["title"], item["year"])

    # 搜索影视
    results = await search_douban("流浪地球", year="2019")
    print(results[0])  # {"douban_id": "26266893", "title": "流浪地球", ...}

    # 获取演职人员中文名（需要 Cookie）
    cast = await get_cast_cn("26266893", cookie="...")
    for person in cast[:3]:
        print(person["name_cn"], person["role"])

asyncio.run(main())
```

---

## torrent_incubator — 种子孵化器

需要 `httpx` 和 `pyyaml`。

### 代码使用

```python
import asyncio
from torrent_incubator import TorrentIncubator, IncubatorConfig

config = IncubatorConfig(
    watch_dir="/downloads/torrents",
    qb_url="http://localhost:8080",
    qb_username="admin",
    qb_password="adminadmin",
    auto_delete_torrent=True,    # 完成后删除 .torrent 文件
    scan_interval_seconds=300,   # 持续模式下的扫描间隔
)

incubator = TorrentIncubator(config)

# 单次扫描
asyncio.run(incubator.scan_once())

# 持续监控（Ctrl+C 停止）
asyncio.run(incubator.run_forever())
```

### 命令行使用

复制 `torrent_incubator/config.yaml.example` 为 `config.yaml` 并编辑：

```bash
# 单次扫描
python -m torrent_incubator.incubator --config config.yaml --once

# 持续监控
python -m torrent_incubator.incubator --config config.yaml

# 查看统计
python -m torrent_incubator.incubator --config config.yaml --stats
```

状态默认保存在 `~/.torrent_incubator/state.json`，可通过 `state_file` 配置修改。

---

## tmdb_hosts — TMDB 防污染 DNS 查询

需要 `httpx`。在 GFW 环境下查询 TMDB / Fanart 域名的真实 IP，生成 hosts 条目。

```python
import asyncio
from tmdb_hosts import resolve_tmdb_ips, generate_hosts_content

async def main():
    results = await resolve_tmdb_ips()
    for domain, ips in results.items():
        print(f"{domain}: {ips}")

    hosts = generate_hosts_content(results)
    print(hosts)
    # 140.82.112.10        api.themoviedb.org
    # 151.101.193.140      image.tmdb.org

asyncio.run(main())
```

---

## ep_rules — 集号规则引擎

零依赖，仅使用 Python 标准库。对集号/季号应用自定义偏移和覆盖规则。

```python
from ep_rules import apply_episode_rules

rules = [
    {
        "enabled": True,
        "title_pattern": "庆余年",
        "ep_offset": -10,    # 集号 -10（将第11集映射为第1集）
        "season_override": 2,  # 强制季号为 2
    }
]

season, episode = apply_episode_rules("庆余年 第二季", season=None, episode=11, rules=rules)
print(season, episode)  # 2  1
```

规则字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title_pattern` | str | 正则表达式，匹配影片标题 |
| `ep_offset` | int | 集号偏移（正数增加，负数减少），偏移后 < 1 时跳过 |
| `season_override` | int \| None | 覆盖季号；`None` 表示不修改 |
| `enabled` | bool | 是否启用此规则（默认 True） |

---

## notify — 消息推送工具

需要 `httpx`。支持 PushDeer / Telegram Bot / 企业微信三种推送渠道。

```python
import asyncio
from notify import send_pushdeer, send_telegram, send_wechat

async def main():
    # PushDeer
    ok = await send_pushdeer(
        server="https://api2.pushdeer.com",
        key="PDU...your_key...",
        title="测试推送",
        body="这是一条来自 streamstack-labs 的测试消息",
    )
    print("PushDeer:", ok)  # True / False

    # Telegram Bot
    ok = await send_telegram(
        token="123456:ABCDEFxxx",
        chat_id="@your_channel",
        text="Telegram 测试消息",
    )
    print("Telegram:", ok)

    # 企业微信
    ok = await send_wechat(
        corp_id="ww1234...",
        app_secret="secret...",
        agent_id="100001",
        message="企业微信测试消息",
    )
    print("WeChat:", ok)

asyncio.run(main())
```

---

## hdhive_checkin — 影巢签到工具

需要 `httpx`。调用 HDHive Open API 完成每日签到和积分查询。

```python
import asyncio
from hdhive_checkin import checkin, get_points

async def main():
    # 每日签到（需要 HDHive Open API Key）
    result = await checkin(
        api_key="hh_openapi_xxxx",
        base_url="https://hdhive.com",   # 可替换为自定义镜像
        is_gambler=False,                # True 启用赌狗模式
    )
    print(result)  # {"checked_in": True, "message": "签到成功，获得 10 积分"}

    # 查询积分
    info = await get_points(api_key="hh_openapi_xxxx")
    print(info)  # {"name": "用户名", "points": 2345, ...}

asyncio.run(main())
```

---

## 许可证

本项目采用 **GPL-3.0** 许可证开源。

你可以自由使用、修改和分发本代码，但衍生作品必须以相同的 GPL-3.0 协议开源。
详见 [LICENSE](./LICENSE) 文件或 [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html)。

## 相关项目

- [StreamStack](https://streamstack.cn) — 115 云盘 + Emby 媒体管理工具
- [streamstack-labs on GitHub](https://github.com/streamstack-cn/streamstack-labs)
