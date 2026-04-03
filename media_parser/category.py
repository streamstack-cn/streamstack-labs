"""
media_parser.category
~~~~~~~~~~~~~~~~~~~~~~
基于 TMDB 元数据的媒体分类策略评估。

提供两种分类方式：
  - ``evaluate_category_policy``：基于用户自定义 YAML 策略文件，灵活可配置
  - ``guess_category``：内置硬编码规则，直接基于 TMDB genre_ids 和 origin_country 推断

用法::

    from media_parser.category import guess_category, evaluate_category_policy

    media_info = {"genre_ids": [16], "original_language": "ja", "origin_country": ["JP"]}
    print(guess_category("tv", media_info))   # "日番"

    print(evaluate_category_policy(media_info, "", "tv"))  # "日番"（使用默认策略）
"""

import logging

logger = logging.getLogger(__name__)

# TMDB genre_ids 参考：
#   16   = Animation（动画）
#   99   = Documentary（纪录片）
#   10762 = Kids（儿童）
#   10764 = Reality（真人秀/综艺）
#   10767 = Talk（脱口秀/综艺）

DEFAULT_CATEGORY_POLICY = """
movie:
  动画电影:
    genre_ids: '16'
  华语电影:
    original_language: 'zh,cn,bo,za'
  外语电影:
tv:
  儿童:
    genre_ids: '10762'
  日番:
    genre_ids: '16'
    origin_country: 'JP'
  动漫:
    genre_ids: '16'
  纪录片:
    genre_ids: '99'
  综艺:
    genre_ids: '10764,10767'
  国产剧:
    origin_country: 'CN,TW,HK'
  欧美剧:
    origin_country: 'US,FR,GB,DE,ES,IT,NL,PT,RU,UK'
  日韩剧:
    origin_country: 'JP,KP,KR,TH,IN,SG'
  未分类:
"""


def evaluate_category_policy(media_info: dict, policy_yaml: str, mtype: str) -> str:
    """
    根据 YAML 策略文件对媒体进行分类。

    :param media_info:  TMDB API 返回的媒体元数据字典
    :param policy_yaml: YAML 格式的分类策略字符串，为空时使用内置默认策略
    :param mtype:       媒体类型，"movie" 或 "tv"
    :returns:           匹配到的分类名，未匹配时返回空字符串

    YAML 格式示例::

        movie:
          动画电影:
            genre_ids: '16'
          华语电影:
            original_language: 'zh,cn,bo,za'
          外语电影:          # 无条件项：作为兜底分类
        tv:
          日番:
            genre_ids: '16'
            origin_country: 'JP'

    规则说明：

    - ``genre_ids``：以逗号分隔的 TMDB genre ID，OR 逻辑（任一命中即满足）
    - ``original_language``：以逗号分隔的语言代码，OR 逻辑
    - ``origin_country`` / ``production_countries``：以逗号分隔的国家代码，OR 逻辑
    - 当 ``original_language`` 和 ``origin_country`` **同时存在**时，两者为 OR 关系
      （任一满足即可）；各条件之间（含 genre_ids）为 AND 关系
    - 条件为空（值为 None）的分类项作为无条件兜底
    """
    effective_yaml = policy_yaml.strip() if policy_yaml else ""
    if not effective_yaml:
        effective_yaml = DEFAULT_CATEGORY_POLICY
    if media_info is None:
        return ""
    try:
        import yaml
        policy = yaml.safe_load(effective_yaml)
        if not isinstance(policy, dict):
            return ""
        section = policy.get(mtype)
        if not section or not isinstance(section, dict):
            return ""
        genre_ids = [str(g) for g in (media_info.get("genre_ids") or [])]
        original_language = (media_info.get("original_language") or "").lower()
        countries = []
        for c in media_info.get("production_countries", []):
            countries.append(c.get("iso_3166_1", "") if isinstance(c, dict) else str(c))
        for c in media_info.get("origin_country", []):
            countries.append(str(c))
        for cat_name, criteria in section.items():
            if not criteria:
                return cat_name
            if not isinstance(criteria, dict):
                continue
            match = True

            p_genres = criteria.get("genre_ids")
            if p_genres:
                p_genres_list = [g.strip() for g in str(p_genres).split(",")]
                if not any(g in p_genres_list for g in genre_ids):
                    match = False

            p_lang = criteria.get("original_language")
            p_country = criteria.get("origin_country") or criteria.get("production_countries")

            lang_checked = bool(p_lang)
            country_checked = bool(p_country)
            lang_ok = False
            country_ok = False

            if lang_checked:
                p_lang_list = [l.strip().lower() for l in str(p_lang).split(",")]
                lang_ok = original_language in p_lang_list

            if country_checked:
                p_country_list = [c.strip().upper() for c in str(p_country).split(",")]
                country_ok = any(c.upper() in p_country_list for c in countries)

            if lang_checked and country_checked:
                if not (lang_ok or country_ok):
                    match = False
            elif lang_checked:
                if not lang_ok:
                    match = False
            elif country_checked:
                if not country_ok:
                    match = False

            for key, val in criteria.items():
                if key in ["genre_ids", "original_language", "origin_country", "production_countries"]:
                    continue
                m_val = media_info.get(key)
                if m_val is not None and str(m_val).lower() != str(val).lower():
                    match = False

            if match:
                return cat_name
    except Exception as e:
        logger.warning(f"[category] Error evaluating policy: {e}")
    return ""


def guess_category(mtype: str, media_info: dict) -> str:
    """
    基于 TMDB genre_ids 和 origin_country 推断媒体分类。

    与 ``evaluate_category_policy`` 使用相同的内置策略，但以硬编码形式实现，
    无需解析 YAML，适合对性能敏感的场景。

    :param mtype:      "movie" 或 "tv"
    :param media_info: TMDB 媒体元数据字典
    :returns:          分类名字符串，无法识别时返回空字符串
    """
    if not media_info:
        return ""
    genres = [g.get("id") for g in media_info.get("genres", [])]
    if not genres and media_info.get("genre_ids"):
        genres = [int(gid) for gid in media_info.get("genre_ids")]
    production_countries = media_info.get("production_countries") or []
    if isinstance(production_countries, list) and len(production_countries) > 0:
        countries = [
            c.get("iso_3166_1") for c in production_countries
            if isinstance(c, dict) and c.get("iso_3166_1")
        ]
    else:
        countries = media_info.get("origin_country") or []
    if isinstance(countries, str):
        countries = [countries]
    original_language = (media_info.get("original_language") or "").lower()
    all_countries: set = set()
    if isinstance(countries, (list, set)):
        for c in countries:
            all_countries.add(str(c).upper())

    if mtype == "movie":
        if 16 in genres:
            return "动画电影"
        if original_language in ["zh", "cn", "bo", "za"]:
            return "华语电影"
        return "外语电影"
    elif mtype == "tv":
        if 10762 in genres:
            return "儿童"
        if 16 in genres:
            if "JP" in all_countries:
                return "日番"
            return "动漫"
        if 99 in genres:
            return "纪录片"
        if 10764 in genres or 10767 in genres:
            return "综艺"
        if any(c in ["CN", "TW", "HK"] for c in all_countries):
            return "国产剧"
        if any(c in ["US", "FR", "GB", "DE", "ES", "IT", "NL", "PT", "RU", "UK"] for c in all_countries):
            return "欧美剧"
        if any(c in ["JP", "KP", "KR", "TH", "IN", "SG"] for c in all_countries):
            return "日韩剧"
        return "未分类"
    return ""
