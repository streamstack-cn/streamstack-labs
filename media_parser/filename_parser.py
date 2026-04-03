"""
media_parser.filename_parser
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
媒体文件名解析器。

将视频文件名拆解为结构化元数据，支持：
  - 标准 SxxExx / 复合多集 / 纯数字文件名
  - 动漫 dash 格式：[SubGroup] 标题 - 05 [1080p]
  - EP/E 前缀、中文集数（数字 + 序数）、中文季数
  - 特别篇 / OVA / SP
  - 年份验证（1900–2050）、分辨率锚点、视频/音频编码

用法::

    from media_parser import mp_style_parse

    info = mp_style_parse("她的盛焰 S01E05 2160p.mkv")
    # {'title': '她的盛焰', 'season': 1, 'episode': 5, 'videoFormat': '2160P', ...}
"""

import re as _re

# ── 中文序数 → 整数映射 ───────────────────────────────────────────────────────
_CN_ORD_MAP: dict = {
    '〇': 0, '零': 0,
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
    '十六': 16, '十七': 17, '十八': 18, '十九': 19,
    '二十': 20, '二十一': 21, '二十二': 22, '二十三': 23, '二十四': 24,
    '二十五': 25, '二十六': 26, '二十七': 27, '二十八': 28, '二十九': 29,
    '三十': 30, '三十一': 31, '三十二': 32, '三十三': 33, '三十四': 34,
    '三十五': 35, '三十六': 36, '百': 100,
}

# 分辨率 token：1080p / 2160p / 4K / 8K / 720P 等
_PIX_RE = _re.compile(r'^\d{3,4}[PIp][IX]?$|^[248][Kk]$', _re.IGNORECASE)

# 开头括号剥离（各括号类型仅匹配自己的闭括号）
_LEADING_BRACKET_RE = _re.compile(
    r'^(?:【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^)]*\))\s*'
)

# 集季残留标记过滤
_JUNK_TOKEN_RE = _re.compile(
    r'^第[零一二三四五六七八九十百〇\d]+[集话話回期季]$'
    r'|^(?:OVA\d*|SP\d*|SPECIAL|番外篇?|特别篇?|特別篇?)$',
    _re.IGNORECASE,
)

# 片厂/发行商/语言版本独立 token 过滤
_SOURCE_TOKEN_RE = _re.compile(
    r'^(?:邵氏(?:兄弟)?|嘉禾(?:电影)?|永盛|寰亚|英皇(?:电影)?|天映(?:娱乐)?'
    r'|博纳(?:影业)?|万达(?:影业)?|光线(?:传媒|影业)?|中影(?:集团)?'
    r'|国语(?:版)?|粤语(?:版)?|普通话(?:版)?|国配|粤配'
    r'|修复版|高清修复|\d+[Kk]修复|数码修复|院线版|加长版|导演剪辑版)$',
    _re.UNICODE,
)

_CN_JUNK_TERM = (
    r'百度(?:网盘)?|迅雷网盘?|阿里(?:云盘)?|夸克(?:网盘)?|磁力|BT|网盘'
    r'|已更新|持续更新|最新|全\d+集|全集|共\d+集|完结'
    r'|纯净(?:无广|分享)?|无广(?:告)?|可投屏|未删减|完整版|蓝光|高码率'
    r'|国语中字|国语(?:音轨|配音)?'
    r'|中文(?:字幕)?|简繁英字幕|简繁(?:中文)?字幕|简繁(?:英)?(?:字幕)?'
    r'|英(?:语)?(?:字幕)?|中字|英字|双语|双字|多语|简体|繁体|字幕(?:组)?'
    r'|60帧(?:率)?(?:版本)?|120帧(?:率)?(?:版本)?|\d+FPS(?:版本?)?'
    r'|4K杜比|4KHDR|杜比视界?|影视剧?|首播|可以看'
    r'|邵氏(?:兄弟)?|嘉禾(?:电影)?|永盛|寰亚|英皇(?:电影)?|天映(?:娱乐)?'
    r'|博纳(?:影业)?|万达(?:影业)?|光线(?:传媒|影业)?|中影(?:集团)?'
    r'|粤语(?:版)?|国语(?:版)?|普通话(?:版)?|国配|粤配'
    r'|修复版?|高清修复|\d+[Kk]修复|数码修复|院线版?|加长版?|导演剪辑版?'
)
_CN_JUNK_RE = _re.compile(
    r'[\[【（(]\s*(?:' + _CN_JUNK_TERM
    + r')(?:\s*[/／&]\s*(?:' + _CN_JUNK_TERM + r'))*\s*[\]】）)]',
    _re.UNICODE,
)


def _cn_ord_to_int(s: str | None) -> int | None:
    """中文序数（含纯数字）→ int。None 安全。"""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    return _CN_ORD_MAP.get(s)


def mp_style_parse(title: str) -> dict:
    """
    媒体文件名解析器。

    返回字段::

        {
            "title":        str,   # 提取出的完整标题
            "cn_name":      str,   # 中文部分
            "en_name":      str,   # 英文部分
            "chinese":      str,   # 同 cn_name（向后兼容）
            "english":      str,   # 同 en_name（向后兼容）
            "tokens":       list,  # 标题 token 列表
            "year":         str | None,
            "season":       int | None,
            "episode":      int | None,
            "episode_end":  int | None,
            "site":         str,   # 首个括号内内容（字幕组等）
            "part":         str,
            "videoFormat":  str,   # "1080P" / "2160P" / "4K" …
            "videoCodec":   str,   # "H265" / "HEVC" / "AV1" …
            "audioCodec":   str,   # "DTS" / "AAC" / "TrueHD" …
            "releaseGroup": str,
            "customization":str,
            "edition":      str,
            "is_special":   bool,
            "is_anime":     bool,
            "base_title":   str,   # CJK+年份合并形式，如 "你好1983"
        }

    示例::

        >>> mp_style_parse("她的盛焰 S01E05 2160p.mkv")
        {'title': '她的盛焰', 'season': 1, 'episode': 5, 'videoFormat': '2160P', ...}

        >>> mp_style_parse("[ANi] 剑来 - 05 [1080p].mkv")
        {'title': '剑来', 'season': None, 'episode': 5, 'videoFormat': '1080P', ...}
    """
    site_tag = ""
    site_match = _re.match(r'^[\[【（(](.+?)[\]】）)]', title.strip())
    if site_match:
        site_tag = site_match.group(1)

    clean_title = title.strip()
    clean_title = _re.sub(r'\{tmdbid-\d+\}', '', clean_title)
    clean_title = _re.sub(r'^[\u2600-\u27FF\u2B00-\u2BFF\U0001F300-\U0001FAFF✓✔✗×→]+\s*', '', clean_title)
    clean_title = _re.sub(r'^[TZ]\s*[-‐‑]\s*', '', clean_title)
    clean_title = _re.sub(r'^[TZ]【', '【', clean_title)

    _bracket_title: str = ""
    _bracket_year_override: str = ""
    _bt_m = _re.match(r'^(?:【([^】]+)】|\[([^\]]+)\]|（([^）]+)）)', clean_title)
    if _bt_m:
        _braw = (_bt_m.group(1) or _bt_m.group(2) or _bt_m.group(3) or "").strip()
        _by_m = _re.search(r'[(（](\d{4})[)）]', _braw)
        if _by_m:
            _bracket_year_override = _by_m.group(1)
            _braw = _braw[:_by_m.start()].strip()
        _not_meta = not _re.fullmatch(
            r'[\dKkPp\s×xHhDd\-/]+'
            r'|4K|HD|FHD|UHD|SDR|HDR|杜比|Dolby|IMAX',
            _braw, _re.I,
        )
        if _re.search(r'[\u4e00-\u9fff]', _braw) and len(_braw) <= 30 and _not_meta:
            _bracket_title = _braw

    _bracket_ep_m = _re.search(
        r'[\[【]\s*第\s*(\d+)\s*(?:[~～\-至到]\s*第?\s*(\d+)\s*)?[集话話][^\[【\]】]*[\]】]',
        clean_title,
    )
    _bracket_ep: int | None = None
    _bracket_ep_end: int | None = None
    if _bracket_ep_m:
        _ep_raw = int(_bracket_ep_m.group(1))
        if 0 <= _ep_raw <= 2000:
            _bracket_ep = _ep_raw
            if _bracket_ep_m.group(2):
                _ep_end_raw = int(_bracket_ep_m.group(2))
                if _ep_end_raw > _ep_raw and _ep_end_raw <= 2000:
                    _bracket_ep_end = _ep_end_raw
        clean_title = clean_title[:_bracket_ep_m.start()] + ' ' + clean_title[_bracket_ep_m.end():]

    clean_title = _CN_JUNK_RE.sub(' ', clean_title)
    clean_title = _re.sub(r'\b(?:60|120|240|48)\s*FPS\b', '', clean_title, flags=_re.I)
    clean_title = _re.sub(r'持续更新|最新更新|全集已更新', '', clean_title)
    clean_title = _re.sub(r'[(（]\s*(?:4K|HD|FHD|UHD|4KHDR|SDR|HDR|杜比|Dolby)\s*[)）]', '', clean_title, flags=_re.I)

    for _ in range(6):
        new_ct = _LEADING_BRACKET_RE.sub('', clean_title.strip())
        if new_ct.strip() == clean_title.strip():
            break
        clean_title = new_ct
    clean_title = _re.sub(r'^[】\]\)）]+\s*', '', clean_title.strip())

    _is_format_only = bool(_re.fullmatch(r'[\dKkPp\s×xHhDd\-/]+|4K|HD|UHD|HDR', clean_title.strip(), _re.I))
    if (not clean_title.strip() or _is_format_only) and _bracket_title:
        clean_title = _bracket_title
        if _bracket_year_override:
            clean_title = f"{_bracket_title} ({_bracket_year_override})"

    clean_title = _re.sub(r'^\d{4}[\.\-]\d{2}[\.\-]\d{2}[\s\.]', '', clean_title)
    clean_title = _re.sub(r'\d+(\.\d+)?\s*(?:GB|MB|TB)\b', '', clean_title, flags=_re.I)
    clean_title = _re.sub(
        r'\.(mkv|mp4|ts|iso|avi|rmvb|mov|flv|wmv|m2ts|m4v|webm)$',
        '', clean_title, flags=_re.I,
    )
    clean_title = clean_title.strip()

    _bare = clean_title.strip()
    if _bare.isdigit() and len(_bare) < 5:
        return {
            "title": "", "cn_name": "", "en_name": "",
            "chinese": "", "english": "", "tokens": [],
            "year": None, "season": None, "episode": int(_bare), "episode_end": None,
            "site": site_tag,
            "part": "", "videoFormat": "", "videoCodec": "", "audioCodec": "",
            "releaseGroup": "", "customization": "", "edition": "", "is_special": False,
            "is_anime": False, "base_title": "",
        }

    _season_only = _re.fullmatch(r'(?:Season\s*|S)(\d{1,3})', _bare, _re.IGNORECASE)
    if _season_only:
        return {
            "title": _bare, "cn_name": "", "en_name": "",
            "chinese": "", "english": "", "tokens": [_bare],
            "year": None, "season": int(_season_only.group(1)), "episode": None, "episode_end": None,
            "site": site_tag,
            "part": "", "videoFormat": "", "videoCodec": "", "audioCodec": "",
            "releaseGroup": "", "customization": "", "edition": "", "is_special": False,
            "is_anime": False, "base_title": "",
        }

    is_special = bool(_re.search(
        r'(?<![A-Za-z])(OVA(?=\d|\b)|SP(?=\d|\b)|SPECIAL|特别篇|特別篇|番外篇?)',
        clean_title, _re.I,
    ))
    sp_episode = None
    _sp_match = _re.search(r'(?<![A-Za-z])(?:OVA|SP)[-_\s]*(\d{1,3})(?!\d)', clean_title, _re.I)
    if _sp_match:
        sp_episode = int(_sp_match.group(1))

    _CN_NUM_PAT = r'([零一二三四五六七八九十百〇\d]+)'
    cn_episode: int | None = None
    cn_episode_end: int | None = None
    cn_season: int | None = None

    _cn_ep_m = _re.search(
        r'第\s*' + _CN_NUM_PAT + r'\s*[集话話回期]'
        r'(?:\s*[-~至到]\s*第?\s*' + _CN_NUM_PAT + r'\s*[集话話回期])?',
        clean_title,
    )
    if _cn_ep_m:
        cn_episode = _cn_ord_to_int(_cn_ep_m.group(1))
        if _cn_ep_m.lastindex and _cn_ep_m.lastindex >= 2 and _cn_ep_m.group(2):
            cn_episode_end = _cn_ord_to_int(_cn_ep_m.group(2))

    _cn_s_m = _re.search(r'第\s*' + _CN_NUM_PAT + r'\s*季', clean_title)
    if _cn_s_m:
        cn_season = _cn_ord_to_int(_cn_s_m.group(1))

    _is_double_bracket = bool(_re.search(r'【[^】]+】\s*(?:【|\[)', title.strip()))
    _site_tag_is_fansub = bool(site_tag) and bool(_re.search(r'[A-Za-z\u4e00-\u9fff]', site_tag))
    _is_anime_format: bool = _site_tag_is_fansub or _is_double_bracket

    _anime_ep: int | None = None
    _anime_ep_m = _re.search(
        r'(?<!\d)\s[-～]\s{0,2}(\d{1,4})(?:v\d)?\s{0,2}'
        r'(?=[\[\(]|\b(?:1080|2160|720|480|4[Kk]|8[Kk]|[Uu][Hh][Dd])\b|$)',
        clean_title,
    )
    if _anime_ep_m:
        _ae = int(_anime_ep_m.group(1))
        if _ae < 1900:
            _anime_ep = _ae
            _is_anime_format = True

    _pre_video_codec: str = ""
    _pvc_m = _re.search(r'\bH[._]?(265|264)\b', clean_title, _re.IGNORECASE)
    if _pvc_m:
        _pre_video_codec = "H265" if _pvc_m.group(1) == "265" else "H264"
    elif _re.search(r'\bHEVC\b', clean_title, _re.IGNORECASE):
        _pre_video_codec = "HEVC"
    elif _re.search(r'\bAV1\b', clean_title, _re.IGNORECASE):
        _pre_video_codec = "AV1"

    clean_title_no_se = _re.sub(
        r'第\s*[零一二三四五六七八九十百〇\d]+\s*[集话話回期季]', '', clean_title
    ).strip()
    if is_special:
        clean_title_no_se = _re.sub(
            r'(?<![A-Za-z])(?:OVA(?=\d|\b)|SP(?=\d|\b)|SPECIAL|番外篇?|特别篇?|特別篇?)\d*',
            '', clean_title_no_se, flags=_re.I,
        ).strip()

    _base_title_from_cjk_yr: str = ""
    _cjk_yr_m = _re.search(
        r'([\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,})((?:19|20)\d{2})(?=[.\s\[\(（【_\-]|$)',
        clean_title_no_se,
    )
    if _cjk_yr_m:
        _yr_candidate = int(_cjk_yr_m.group(2))
        if 1900 < _yr_candidate < 2050:
            _base_title_from_cjk_yr = _cjk_yr_m.group(0)

    with_spaces = _re.sub(r'([\u4e00-\u9fff])([a-zA-Z])', r'\1 \2', clean_title_no_se)
    with_spaces = _re.sub(r'([\u4e00-\u9fff])(\d{3,})', r'\1 \2', with_spaces)
    with_spaces = _re.sub(r'([a-zA-Z0-9])([\u4e00-\u9fff])', r'\1 \2', with_spaces)

    tokens = _re.split(
        r'\.|\s+|\(|\)|\[|\]|【|】|\{|\}|/|～|;|&|\||#|_|「|」|~',
        with_spaces,
    )
    tokens = [t.strip() for t in tokens if t.strip()]

    _META_KW = {
        '1080P', '2160P', '4320P', '720P', '480P', '4K', '8K', 'UHD',
        'BLURAY', 'BLU-RAY', 'WEB', 'DVD', 'REMUX', 'HDTV', 'UHDTV',
        'WEBRIP', 'BDRIP', 'DVDRIP', 'WEB-DL', 'BD', 'HDRIP',
        'HDR', 'HDR10', 'HDR10+', 'DV', 'DOVI', 'DOLBY', 'HLG', 'SDR',
        'H264', 'H265', 'X264', 'X265', 'HEVC', 'AVC', 'AV1',
        'DTS', 'AAC', 'TRUEHD', 'FLAC', 'DDP', 'DD', 'AC3', 'LPCM', 'OPUS', 'ATMOS',
        'UNCUT', 'INTERNAL', 'REPACK', 'PROPER', 'LIMITED', 'CRITERION',
        'EXTENDED', 'UNRATED', '10BIT',
        'DSNP', 'DSNY', 'NF', 'AMZN', 'HMAX', 'ATVP', 'PCOK', 'CRKL',
        'IQIYI', 'BILIBILI', 'YOUKU', 'TENCENT', 'MGTV',
        'DISNEY', 'NETFLIX', 'HULU', 'STAN', 'BCORE',
        'ITA', 'SPA', 'FRE', 'GER', 'POR', 'RUS', 'JPN', 'KOR',
        'CHS', 'CHT', 'ENG',
        'FPS',
    }

    year: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_end: int | None = None
    anchor_idx: int = -1
    _year_set_anchor: bool = False
    last_token_type: str = ""

    for i, token in enumerate(tokens):
        t_upper = token.upper()

        if _PIX_RE.match(token):
            if anchor_idx == -1 or (anchor_idx == 0 and _year_set_anchor):
                anchor_idx = i
            _year_set_anchor = False
            last_token_type = "pix"
            continue

        if _re.fullmatch(r'(19|20)\d{2}', token):
            yr_int = int(token)
            if 1900 < yr_int < 2050:
                if not year:
                    year = token
                    if anchor_idx == -1:
                        anchor_idx = i
                        _year_set_anchor = True
                elif _year_set_anchor:
                    year = token
                    anchor_idx = i
                last_token_type = "year"
                continue

        _complex = _re.fullmatch(
            r'S(\d{1,3})E(\d{1,4})(?:E(\d{1,4})|[-~]E?(\d{1,4}))+',
            t_upper,
        )
        if _complex:
            if season is None:
                season = int(_complex.group(1))
            if episode is None:
                episode = int(_complex.group(2))
            _e_end_a = _complex.group(3)
            _e_end_b = _complex.group(4)
            if episode_end is None:
                if _e_end_a:
                    episode_end = int(_e_end_a)
                elif _e_end_b:
                    episode_end = int(_e_end_b)
            if anchor_idx == -1 or (anchor_idx == 0 and _year_set_anchor):
                anchor_idx = i
            _year_set_anchor = False
            last_token_type = "episode"
            continue

        _se = _re.fullmatch(r'S(\d{1,3})E(\d{1,4})', t_upper)
        if _se:
            if season is None:
                season = int(_se.group(1))
            if episode is None:
                episode = int(_se.group(2))
            if anchor_idx == -1 or (anchor_idx == 0 and _year_set_anchor):
                anchor_idx = i
            _year_set_anchor = False
            last_token_type = "episode"
            continue

        _s_only = _re.fullmatch(r'S(\d{1,3})', t_upper)
        if _s_only and season is None:
            season = int(_s_only.group(1))
            if anchor_idx == -1 or (anchor_idx == 0 and _year_set_anchor):
                anchor_idx = i
            _year_set_anchor = False
            last_token_type = "season"
            continue

        if t_upper == "SEASON":
            last_token_type = "SEASON_WORD"
            continue
        if season is None and token.isdigit() and len(token) <= 2 and last_token_type == "SEASON_WORD":
            season = int(token)
            if anchor_idx == -1:
                anchor_idx = i
            last_token_type = "season"
            continue

        _ep = _re.fullmatch(r'EP?(\d{1,4})(?:[-~]E?(\d{1,4}))?', t_upper)
        if _ep and episode is None:
            episode = int(_ep.group(1))
            if _ep.group(2):
                episode_end = int(_ep.group(2))
            if anchor_idx == -1 or (anchor_idx == 0 and _year_set_anchor):
                anchor_idx = i
            _year_set_anchor = False
            last_token_type = "episode"
            continue

        if t_upper == "EPISODE":
            last_token_type = "EPISODE_WORD"
            continue
        if episode is None and token.isdigit() and len(token) <= 4 and last_token_type == "EPISODE_WORD":
            episode = int(token)
            if anchor_idx == -1:
                anchor_idx = i
            last_token_type = "episode"
            continue

        _prev_token = tokens[i - 1].upper() if i > 0 else ""
        _next_is_quality = (
            i + 1 < len(tokens)
            and (_PIX_RE.match(tokens[i + 1]) or tokens[i + 1].upper() in _META_KW)
        )
        if (
            episode is None
            and token.isdigit()
            and 1 < len(token) <= 3
            and last_token_type not in ("year", "season", "SEASON_WORD")
            and _prev_token not in {"H", "X"}
            and (anchor_idx != -1 or (last_token_type == "" and _next_is_quality))
        ):
            ep_val = int(token)
            if ep_val < 1900:
                episode = ep_val
                last_token_type = "episode"
                continue

        if t_upper in _META_KW:
            if anchor_idx == -1 or (anchor_idx == 0 and _year_set_anchor):
                anchor_idx = i
            _year_set_anchor = False
            last_token_type = "meta"
            continue

        last_token_type = ""

    if episode is None and cn_episode is not None:
        episode = cn_episode
    if episode_end is None and cn_episode_end is not None:
        episode_end = cn_episode_end
    if season is None and cn_season is not None:
        season = cn_season
    if episode is None and _anime_ep is not None:
        episode = _anime_ep
    if episode is None and _bracket_ep is not None:
        episode = _bracket_ep
    if episode_end is None and _bracket_ep_end is not None:
        episode_end = _bracket_ep_end
    if year is None and _bracket_year_override:
        year = _bracket_year_override

    if is_special:
        if season is None:
            season = 0
        if sp_episode is not None and episode is None:
            episode = sp_episode

    if episode is not None and anchor_idx == -1:
        anchor_idx = len(tokens)

    if anchor_idx == -1:
        extracted_tokens = tokens
    elif anchor_idx == 0:
        extracted_tokens = tokens[1:] if len(tokens) > 1 else tokens
    else:
        extracted_tokens = tokens[:anchor_idx]

    extracted_tokens = [
        t for t in extracted_tokens
        if not _JUNK_TOKEN_RE.match(t) and not _SOURCE_TOKEN_RE.match(t)
    ]

    video_format, video_codec, audio_codec = "", "", ""
    _PIX_MAP = {
        '2160P': '2160P', '4320P': '4320P', '1080P': '1080P', '1080I': '1080I',
        '720P': '720P', '480P': '480P', '4K': '2160P', '8K': '4320P', 'UHD': '2160P',
    }
    _VC_MAP = {
        'HEVC': 'HEVC', 'H265': 'H265', 'H264': 'H264', 'X265': 'X265',
        'X264': 'X264', 'AVC': 'AVC', 'AV1': 'AV1',
    }
    _AC_MAP = {
        'DTS': 'DTS', 'AAC': 'AAC', 'TRUEHD': 'TrueHD', 'FLAC': 'FLAC',
        'DDP': 'DDP', 'DD': 'DD', 'AC3': 'AC3', 'ATMOS': 'Atmos',
        'OPUS': 'Opus', 'LPCM': 'LPCM',
    }
    for tok in tokens:
        tu = tok.upper()
        if not video_format:
            if tu in _PIX_MAP:
                video_format = _PIX_MAP[tu]
            elif _PIX_RE.match(tok):
                video_format = tok.upper()
        if not video_codec and tu in _VC_MAP:
            video_codec = _VC_MAP[tu]
        if not audio_codec and tu in _AC_MAP:
            audio_codec = _AC_MAP[tu]

    if not video_codec and _pre_video_codec:
        video_codec = _pre_video_codec

    chinese_parts = [t for t in extracted_tokens if _re.search(r'[\u4e00-\u9fff]', t)]
    english_parts = [t for t in extracted_tokens if not _re.search(r'[\u4e00-\u9fff]', t)]

    return {
        "title": " ".join(extracted_tokens),
        "cn_name": " ".join(chinese_parts).strip(),
        "en_name": " ".join(english_parts).strip(),
        "chinese": " ".join(chinese_parts).strip(),
        "english": " ".join(english_parts).strip(),
        "tokens": extracted_tokens,
        "year": year,
        "season": season,
        "episode": episode,
        "episode_end": episode_end,
        "site": site_tag,
        "part": "",
        "videoFormat": video_format,
        "videoCodec": video_codec,
        "audioCodec": audio_codec,
        "releaseGroup": "",
        "customization": "",
        "edition": "",
        "is_special": is_special,
        "is_anime": _is_anime_format,
        "base_title": _base_title_from_cjk_yr,
    }
