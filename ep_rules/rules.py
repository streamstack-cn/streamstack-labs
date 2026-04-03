"""
ep_rules.rules
~~~~~~~~~~~~~~
集号偏移 + 季号覆盖规则引擎（纯 Python，零外部依赖）。

规则结构（dict 或 Rule 对象）：
    title_pattern   str   正则表达式，与影片标题做不区分大小写匹配
    ep_offset       int   集号偏移；偏移后 < 1 时跳过本规则
    season_override int|None  季号覆盖；None 表示不修改季号
    enabled         bool  是否启用（默认 True）

匹配逻辑：
    遍历规则列表，取第一条 title_pattern 命中的规则，
    依次应用 ep_offset 和 season_override，然后立即停止（不叠加后续规则）。

使用方法：
    from ep_rules import apply_episode_rules

    rules = [
        {"title_pattern": "庆余年", "ep_offset": -10, "season_override": 2}
    ]
    season, episode = apply_episode_rules("庆余年 第二季", season=None, episode=11, rules=rules)
    # season=2, episode=1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Rule:
    """类型化的规则对象，也可直接传入 dict。"""
    title_pattern: str
    ep_offset: int = 0
    season_override: Optional[int] = None
    enabled: bool = True


def apply_episode_rules(
    title: str,
    season: Optional[int],
    episode: Optional[int],
    rules: list[Union[dict, Rule]],
) -> tuple[Optional[int], Optional[int]]:
    """
    对解析出的集号/季号应用自定义规则。

    参数：
        title    影片或剧集标题（用于规则匹配）
        season   当前季号（可为 None）
        episode  当前集号（可为 None）
        rules    规则列表，每条规则为 dict 或 Rule 对象

    返回：
        (season, episode) — 经过规则处理后的季号和集号。
        若 episode 为 None 或 title 为空，直接返回原值。
    """
    if episode is None or not title:
        return season, episode

    for raw_rule in rules:
        if isinstance(raw_rule, Rule):
            rule = raw_rule
            enabled = rule.enabled
            pattern = rule.title_pattern
            ep_offset = rule.ep_offset
            s_override = rule.season_override
        else:
            if not raw_rule.get("enabled", True):
                continue
            pattern = raw_rule.get("title_pattern") or ""
            ep_offset = int(raw_rule.get("ep_offset") or 0)
            s_override = raw_rule.get("season_override")
            if s_override is not None:
                s_override = int(s_override)
            enabled = True

        if not enabled:
            continue
        if not pattern:
            continue

        try:
            if not re.search(pattern, title, re.I):
                continue
        except re.error:
            continue

        if ep_offset:
            adj_ep = episode + ep_offset
            if adj_ep >= 1:
                episode = adj_ep

        if s_override is not None:
            season = s_override

        break  # 第一条命中规则生效后停止

    return season, episode


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        print("用法: python -m ep_rules.rules <title> <episode> [rules_json_file]")
        print("示例: python -m ep_rules.rules '庆余年第二季' 11 rules.json")
        sys.exit(1)

    _title = sys.argv[1]
    _episode = int(sys.argv[2])
    _rules: list = []

    if len(sys.argv) >= 4:
        with open(sys.argv[3], encoding="utf-8") as f:
            _rules = json.load(f)

    _season, _ep = apply_episode_rules(_title, None, _episode, _rules)
    print(f"season={_season}  episode={_ep}")
