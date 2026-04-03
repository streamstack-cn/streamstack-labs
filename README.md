# streamstack-labs

StreamStack 系统实验室工具集的独立开源版本。

包含三个相互独立的模块，每个模块均可单独安装使用，无需 StreamStack 主体。

## 模块列表

| 模块 | 说明 | 依赖 |
|---|---|---|
| `media_parser` | 媒体文件名解析 + 分类策略 | 无（标准库） |
| `douban` | 豆瓣数据获取工具 | httpx |
| `torrent_incubator` | 种子孵化器（监控目录 → qBittorrent） | httpx, pyyaml |

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

## 许可证

MIT License — 可自由使用、修改、商业用途，保留版权声明即可。

## 相关项目

- [StreamStack](https://streamstack.cn) — 115 云盘 + Emby 媒体管理工具
- [streamstack-labs on GitHub](https://github.com/streamstack-cn/streamstack-labs)
