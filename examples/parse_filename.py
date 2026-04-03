"""
示例：媒体文件名批量解析
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from media_parser import mp_style_parse

TEST_CASES = [
    "她的盛焰 S01E05 2160p.mkv",
    "[ANi] 剑来 - 05 [1080p].mkv",
    "庆余年 第二季 第10集 WEB-DL 2160p.mkv",
    "The.Dark.Knight.2008.2160p.BluRay.x265.TrueHD.mkv",
    "【喵萌奶茶屋】★01月新番★[Re：从零开始的异世界生活 第三季][01][1080p][简中].mp4",
    "流浪地球2 (2023) 2160p.mkv",
    "你好1983.S01E01.mp4",
    "EP05.mkv",
    "005.mkv",
    "Season 2",
]

for title in TEST_CASES:
    info = mp_style_parse(title)
    print(f"\n输入: {title!r}")
    print(f"  标题: {info['title']!r}")
    if info['season'] is not None:
        print(f"  季/集: S{info['season']:02d}", end="")
        if info['episode'] is not None:
            print(f"E{info['episode']:02d}", end="")
            if info['episode_end']:
                print(f"-E{info['episode_end']:02d}", end="")
        print()
    elif info['episode'] is not None:
        print(f"  集数: {info['episode']}")
    if info['year']:
        print(f"  年份: {info['year']}")
    if info['videoFormat']:
        print(f"  画质: {info['videoFormat']}")
    if info['is_special']:
        print(f"  特别篇: True")
    if info['is_anime']:
        print(f"  动漫格式: True")
