"""
douban.client
~~~~~~~~~~~~~~
豆瓣数据获取工具，无外部框架依赖（仅需 httpx）。

功能：
  - 获取用户「想看」列表（需要有效 Cookie）
  - 搜索影视条目
  - 获取演职人员中文名（三层 fallback：rexxar JSON → PC HTML → JSON-LD）
  - Cookie 有效性验证
  - TMDB ID → 豆瓣 ID 映射

用法::

    import asyncio
    from douban import check_cookie, get_wish_list

    async def main():
        result = await check_cookie("dbcl2=12345678:xxxx; ck=yyyy")
        if result["valid"]:
            wishlist = await get_wish_list(cookie, result["user_id"])
            for item in wishlist:
                print(item["title"], item["year"])

    asyncio.run(main())
"""

import json
import logging
import re
import time
import asyncio
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://m.douban.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 内存缓存：douban_id → (cast列表, 过期时间戳)，TTL=24h
_cast_cache: dict[str, tuple[list[dict], float]] = {}
_CAST_CACHE_TTL = 24 * 3600


def _parse_cookie(cookie_str: str) -> dict:
    d: dict = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d


async def get_wish_list(cookie: str, user_id: str, media_type: str = "all") -> list[dict]:
    """
    拉取指定豆瓣用户的「想看」列表。

    :param cookie:     豆瓣 Cookie 字符串（含 dbcl2 / ck）
    :param user_id:    豆瓣用户数字 ID（非昵称）
    :param media_type: "movie" | "tv" | "all"
    :returns: list of ``{douban_id, title, year, media_type, poster, rating}``

    示例::

        wishlist = await get_wish_list(cookie, "12345678", media_type="movie")
    """
    results: list[dict] = []
    start = 0
    page_size = 30
    cookie_dict = _parse_cookie(cookie)
    type_map = {"movie": "movie", "tv": "tv", "all": ""}
    subj_type = type_map.get(media_type, "")

    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
        while True:
            url = (
                f"https://m.douban.com/rexxar/api/v2/user/{user_id}/wishlist"
                f"?type={subj_type}&start={start}&count={page_size}&ck=&for_mobile=1"
            )
            try:
                resp = await client.get(url, cookies=cookie_dict)
                if resp.status_code == 403:
                    logger.warning("[豆瓣] 想看列表拉取 403，请检查 Cookie 是否有效")
                    break
                data = resp.json()
            except Exception as e:
                logger.warning(f"[豆瓣] 想看列表请求异常: {e}")
                break

            items = data.get("items") or data.get("subjects") or []
            if not items:
                break

            for it in items:
                subject = it.get("subject") or it
                sid = str(subject.get("id") or "")
                title = subject.get("title") or ""
                year = str(subject.get("year") or "")
                stype = subject.get("type") or subject.get("subtype") or "movie"
                poster_raw = subject.get("cover") or {}
                poster = (
                    poster_raw.get("url")
                    or (subject.get("pic") or {}).get("large")
                    or subject.get("image")
                    or ""
                )
                rating = (subject.get("rating") or {}).get("value") or 0
                if sid and title:
                    results.append({
                        "douban_id": sid,
                        "title": title,
                        "year": year,
                        "media_type": "tv" if stype in ("tv",) else "movie",
                        "poster": poster,
                        "rating": rating,
                    })

            total = data.get("total") or data.get("count") or len(items)
            start += page_size
            if start >= total or len(items) < page_size:
                break
            await asyncio.sleep(0.5)

    logger.info(f"[豆瓣] 「想看」列表拉取完成: {len(results)} 条 (user={user_id})")
    return results


async def search_douban(title: str, year: str = "") -> list[dict]:
    """
    通过关键词搜索豆瓣影视条目，无需 Cookie。

    :param title: 标题关键词
    :param year:  年份字符串（可选），用于过滤年份相差超过 1 年的结果
    :returns: list of ``{douban_id, title, year, media_type, poster}``
    """
    url = f"https://movie.douban.com/j/subject_suggest?q={title}"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={
            **_HEADERS,
            "Referer": "https://movie.douban.com/",
        }) as client:
            resp = await client.get(url)
            items = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.debug(f"[豆瓣] 搜索异常: {e}")
        return []

    results = []
    for it in items:
        sid = str(it.get("id") or "")
        stitle = it.get("title") or ""
        syear = str(it.get("year") or "")
        stype = it.get("type") or "movie"
        img = it.get("img") or ""
        if not sid:
            continue
        try:
            year_diff = abs(int(syear) - int(year)) if year and syear else 0
        except (ValueError, TypeError):
            year_diff = 0
        if year and syear and year_diff > 1:
            continue
        results.append({
            "douban_id": sid,
            "title": stitle,
            "year": syear,
            "media_type": "tv" if stype == "tv" else "movie",
            "poster": img,
        })
    return results


async def get_cast_cn(douban_id: str, cookie: str = "") -> list[dict]:
    """
    从豆瓣获取影片/剧集的演职人员（中文名）。

    三层 fallback 策略：

    1. 移动端 rexxar JSON API（最稳定，不受 PC 页面改版影响）
    2. PC 端 /celebrities HTML 抓取 + 正则解析
    3. JSON-LD 结构化数据（部分页面）

    :param douban_id: 豆瓣影视 ID
    :param cookie:    豆瓣 Cookie 字符串（可选，有 Cookie 成功率更高）
    :returns: list of ``{name_cn, role, character, douban_person_id}``
              其中 role 为 "director" / "actor" / "writer"
    """
    cached = _cast_cache.get(douban_id)
    if cached and time.time() < cached[1]:
        return cached[0]

    cookie_dict = _parse_cookie(cookie) if cookie else {}
    cast_list: list[dict] = []

    # Layer 1：移动端 rexxar JSON API
    api_headers = {**_HEADERS, "Referer": "https://m.douban.com/", "Accept": "application/json, text/plain, */*"}
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=api_headers) as client:
            api_url = (
                f"https://m.douban.com/rexxar/api/v2/movie/{douban_id}"
                f"/celebrities?start=0&count=100&ck=&for_mobile=1"
            )
            resp = await client.get(api_url, cookies=cookie_dict)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    for person in data.get("directors", []):
                        name = (person.get("name") or "").strip()
                        if name:
                            cast_list.append({"name_cn": name, "role": "director", "character": "",
                                              "douban_person_id": str(person.get("id") or "")})
                    for person in data.get("actors", []):
                        name = (person.get("name") or "").strip()
                        if name:
                            cast_list.append({"name_cn": name, "role": "actor",
                                              "character": (person.get("character") or "").strip(),
                                              "douban_person_id": str(person.get("id") or "")})
                    for person in data.get("writers", []):
                        name = (person.get("name") or "").strip()
                        if name:
                            cast_list.append({"name_cn": name, "role": "writer", "character": "",
                                              "douban_person_id": str(person.get("id") or "")})
                except Exception:
                    pass

            if not cast_list:
                detail_url = f"https://m.douban.com/rexxar/api/v2/movie/{douban_id}?ck=&for_mobile=1"
                resp2 = await client.get(detail_url, cookies=cookie_dict)
                if resp2.status_code == 200:
                    try:
                        d2 = resp2.json()
                        for person in d2.get("directors", []):
                            name = (person.get("name") or "").strip()
                            if name:
                                cast_list.append({"name_cn": name, "role": "director", "character": "",
                                                  "douban_person_id": str(person.get("id") or "")})
                        for person in d2.get("actors", []):
                            name = (person.get("name") or "").strip()
                            if name:
                                cast_list.append({"name_cn": name, "role": "actor",
                                                  "character": (person.get("character") or "").strip(),
                                                  "douban_person_id": str(person.get("id") or "")})
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"[豆瓣] Layer1 API 请求异常: {e}")

    # Layer 2：PC 端 HTML 抓取
    if not cast_list:
        html = ""
        desktop_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://movie.douban.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=desktop_headers) as client:
                resp = await client.get(
                    f"https://movie.douban.com/subject/{douban_id}/celebrities",
                    cookies=cookie_dict,
                )
                if resp.status_code == 200:
                    html = resp.text
                elif resp.status_code == 403:
                    logger.warning(f"[豆瓣] 演职人员页返回 403 (douban_id={douban_id})")
        except Exception as e:
            logger.debug(f"[豆瓣] Layer2 HTML 请求异常: {e}")

        if html:
            for m in re.finditer(
                r'<li[^>]*class="[^"]*director[^"]*"[^>]*>.*?'
                r'<a[^>]*href="https://www\.douban\.com/celebrity/(\d+)[^"]*"[^>]*>'
                r'([^<]+)</a>',
                html, re.DOTALL
            ):
                cast_list.append({"name_cn": m.group(2).strip(), "role": "director",
                                  "character": "", "douban_person_id": m.group(1)})

            for block in re.findall(
                r'<li[^>]*class="[^"]*celebrity[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL
            ):
                name_m = re.search(r'<span[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)</span>', block)
                char_m = re.search(r'<span[^>]*class="[^"]*role[^"]*"[^>]*>([^<]+)</span>', block)
                id_m = re.search(r'href="https://www\.douban\.com/celebrity/(\d+)', block)
                if name_m:
                    cast_list.append({
                        "name_cn": name_m.group(1).strip(),
                        "role": "actor",
                        "character": char_m.group(1).strip() if char_m else "",
                        "douban_person_id": id_m.group(1) if id_m else "",
                    })

            if not cast_list:
                for m in re.finditer(
                    r'<a[^>]*href="https://www\.douban\.com/celebrity/(\d+)/?"[^>]*>'
                    r'\s*([^<]{2,30})\s*</a>',
                    html
                ):
                    name = m.group(2).strip()
                    pid = m.group(1)
                    if name and not any(c["douban_person_id"] == pid for c in cast_list):
                        cast_list.append({"name_cn": name, "role": "actor",
                                          "character": "", "douban_person_id": pid})

            # Layer 3：JSON-LD
            if not cast_list:
                for ld_match in re.finditer(
                    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                    html, re.DOTALL
                ):
                    try:
                        ld = json.loads(ld_match.group(1))
                        for person in ld.get("director", []):
                            name = person.get("name", "").strip()
                            if name:
                                cast_list.append({"name_cn": name, "role": "director",
                                                  "character": "", "douban_person_id": ""})
                        for person in ld.get("actor", []):
                            name = person.get("name", "").strip()
                            if name:
                                cast_list.append({"name_cn": name, "role": "actor",
                                                  "character": "", "douban_person_id": ""})
                    except Exception:
                        pass

    # 去重（按 name_cn）
    seen: set = set()
    deduped = []
    for c in cast_list:
        k = c["name_cn"]
        if k not in seen:
            seen.add(k)
            deduped.append(c)

    if deduped:
        _cast_cache[douban_id] = (deduped, time.time() + _CAST_CACHE_TTL)
        logger.info(f"[豆瓣] 演职人员解析成功: {len(deduped)} 条 (douban_id={douban_id})")
    else:
        logger.warning(f"[豆瓣] 演职人员解析为空 (douban_id={douban_id})")
    return deduped


async def tmdb_to_douban_id(title: str, year: str = "", media_type: str = "movie") -> Optional[str]:
    """
    通过标题+年份在豆瓣搜索，返回最匹配的豆瓣 ID。

    :param title:       影视标题
    :param year:        年份（可选）
    :param media_type:  "movie" 或 "tv"（当前未用于过滤，保留参数供未来扩展）
    :returns:           豆瓣 ID 字符串，未找到时返回 None
    """
    results = await search_douban(title, year)
    if not results:
        return None
    for r in results:
        if r["title"] == title and (not year or r["year"] == year):
            return r["douban_id"]
    for r in results:
        if title in r["title"] or r["title"] in title:
            return r["douban_id"]
    return results[0]["douban_id"] if results else None


def _extract_uid_from_cookie(cookie_str: str) -> str:
    """从 dbcl2 Cookie 直接提取用户 ID（无需网络请求）。"""
    for part in cookie_str.split(";"):
        part = part.strip()
        if part.lower().startswith("dbcl2="):
            val = part[6:].strip().strip('"').strip("'")
            uid = val.split(":")[0].strip().strip('"')
            if uid.isdigit():
                return uid
    return ""


async def check_cookie(cookie: str) -> dict:
    """
    检测豆瓣 Cookie 是否有效。

    :param cookie: 豆瓣 Cookie 字符串
    :returns: ``{"valid": bool, "user_id": str, "name": str}``

    多重回退策略：

    1. 直接从 dbcl2 字段提取 user_id（最可靠，不需要网络）
    2. 调用 douban.com JSON 接口获取用户昵称
    3. 兜底：仅凭 dbcl2 存在即判定有效
    """
    cookie_dict = _parse_cookie(cookie)
    uid_from_cookie = _extract_uid_from_cookie(cookie)
    name = ""
    network_ok = False

    desktop_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.douban.com/",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=desktop_headers, follow_redirects=True) as client:
            resp = await client.get("https://www.douban.com/j/people/", cookies=cookie_dict)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    payload = data.get("payload") or data
                    uid_net = str(payload.get("uid") or payload.get("user_id") or "")
                    name = payload.get("name") or payload.get("screen_name") or ""
                    if uid_net:
                        network_ok = True
                        if not uid_from_cookie:
                            uid_from_cookie = uid_net
                except Exception:
                    pass

            if not network_ok and uid_from_cookie:
                ck_val = cookie_dict.get("ck", "")
                resp2 = await client.get(
                    f"https://m.douban.com/rexxar/api/v2/user/{uid_from_cookie}"
                    f"?ck={ck_val}&for_mobile=1",
                    cookies=cookie_dict,
                    headers={**desktop_headers, **_HEADERS},
                )
                if resp2.status_code == 200:
                    try:
                        d2 = resp2.json()
                        name = d2.get("name") or d2.get("screen_name") or name
                        network_ok = True
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"[豆瓣] Cookie 网络验证异常: {e}")

    valid = bool(uid_from_cookie)
    return {"valid": valid, "user_id": uid_from_cookie, "name": name}
