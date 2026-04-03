"""
tmdb_hosts.resolver
~~~~~~~~~~~~~~~~~~~
在 GFW 环境下查询 TMDB / Fanart 相关域名的真实（未污染）IP，并生成 hosts 条目。

核心策略：
  直连三路并发（取最快）：ip-api.com / hackertarget.com / api.ip.sb
    ——三者均在境外完成 DNS 解析，返回结果不受 GFW 污染。
  兜底（需系统代理）：Cloudflare DoH → Google DoH

使用方法：
    import asyncio
    from tmdb_hosts import resolve_tmdb_ips, generate_hosts_content

    results = asyncio.run(resolve_tmdb_ips())
    print(generate_hosts_content(results))
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

import httpx

TMDB_DOMAINS = [
    "api.themoviedb.org",
    "image.tmdb.org",
    "www.themoviedb.org",
    "themoviedb.org",
    "api.thetvdb.com",
    "fanart.tv",
    "webservice.fanart.tv",
    "assets.fanart.tv",
]

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

_PRIVATE_PREFIXES = (
    "0.", "127.", "10.", "192.168.",
    *(f"172.{i}." for i in range(16, 32)),
)

# 内存缓存，避免短时间内重复请求外部服务
_ip_cache: dict[str, tuple[list[str], float]] = {}
_CACHE_TTL = 3600.0


def _is_valid_public_ipv4(ip: str) -> bool:
    """
    校验合法公网 IPv4：格式正确 + 每段 0-255 + 非私有/回环。
    GFW 投毒常见伪造：127.0.0.1、10.x.x.x、192.168.x.x 或格式无效字符串。
    """
    if not isinstance(ip, str) or not _IPV4_RE.match(ip):
        return False
    try:
        if not all(0 <= int(o) <= 255 for o in ip.split(".")):
            return False
    except (ValueError, AttributeError):
        return False
    return not ip.startswith(_PRIVATE_PREFIXES)


def _filter_public(ips: list[str]) -> list[str]:
    return [ip for ip in ips if _is_valid_public_ipv4(ip)]


async def _race_lookup(client: httpx.AsyncClient, domain: str) -> list[str]:
    """
    三路并发境外 IP 查询，返回最快的非空结果。
    任意一路返回有效 IP 后立即取消其余任务，防止协程泄漏。
    """

    async def _ip_api() -> list[str]:
        try:
            r = await client.get(
                f"http://ip-api.com/json/{domain}",
                params={"fields": "status,query"},
                timeout=8.0,
            )
            if r.status_code == 200:
                d = r.json()
                if d.get("status") == "success" and d.get("query"):
                    return _filter_public([d["query"]])
        except Exception:
            pass
        return []

    async def _hackertarget() -> list[str]:
        try:
            r = await client.get(
                "https://api.hackertarget.com/dnslookup/",
                params={"q": domain},
                timeout=8.0,
            )
            if r.status_code == 200 and "error" not in r.text.lower():
                ips = []
                for line in r.text.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        ips.append(parts[-1])
                return _filter_public(ips)
        except Exception:
            pass
        return []

    async def _ipsb() -> list[str]:
        try:
            r = await client.get(
                f"https://api.ip.sb/geoip/{domain}",
                headers={"User-Agent": "curl/7.88"},
                timeout=8.0,
            )
            if r.status_code == 200:
                ip = r.json().get("ip", "")
                return _filter_public([ip]) if ip else []
        except Exception:
            pass
        return []

    winner: list[str] = []
    pending: set[asyncio.Task] = {
        asyncio.create_task(_ip_api()),
        asyncio.create_task(_hackertarget()),
        asyncio.create_task(_ipsb()),
    }
    try:
        while pending and not winner:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                try:
                    result = fut.result()
                except Exception:
                    result = []
                if result and not winner:
                    winner = result
                    break
    except Exception:
        pass
    finally:
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    return winner


async def _lookup_via_doh(client: httpx.AsyncClient, domain: str) -> list[str]:
    """兜底 DoH（顺序）：需系统代理才能访问。"""
    for endpoint in [
        "https://cloudflare-dns.com/dns-query",
        "https://dns.google/resolve",
    ]:
        try:
            r = await client.get(
                endpoint,
                params={"name": domain, "type": "A"},
                headers={"Accept": "application/dns-json"},
                timeout=10.0,
            )
            if r.status_code == 200:
                ips = _filter_public([
                    a.get("data", "")
                    for a in r.json().get("Answer", [])
                    if a.get("type") == 1
                ])
                if ips:
                    return ips
        except Exception:
            continue
    return []


async def resolve_tmdb_ips(
    domains: Optional[list[str]] = None,
    proxy_url: Optional[str] = None,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """
    查询给定域名列表的真实公网 IP。

    参数：
        domains    需要查询的域名列表，默认为 TMDB_DOMAINS。
        proxy_url  HTTP/SOCKS5 代理地址（用于兜底 DoH），None 表示不使用代理。
        use_cache  是否使用内存缓存（默认 True，TTL = 1 小时）。

    返回：
        dict[domain -> list[ip]]，解析失败的域名对应空列表。
    """
    if domains is None:
        domains = TMDB_DOMAINS

    now = time.monotonic()
    cached: dict[str, list[str]] = {}
    to_fetch: list[str] = []

    if use_cache:
        for d in domains:
            entry = _ip_cache.get(d)
            if entry and now < entry[1]:
                cached[d] = entry[0]
            else:
                to_fetch.append(d)
    else:
        to_fetch = list(domains)

    if not to_fetch:
        return cached

    proxy_mounts = {"https://": httpx.AsyncHTTPTransport(proxy=proxy_url)} if proxy_url else None

    async with (
        httpx.AsyncClient(follow_redirects=True) as direct_client,
        httpx.AsyncClient(mounts=proxy_mounts, follow_redirects=True) as proxy_client,
    ):
        async def resolve_one(domain: str) -> list[str]:
            ips = await _race_lookup(direct_client, domain)
            if not ips:
                ips = await _lookup_via_doh(proxy_client, domain)
            return ips

        fresh_ips = await asyncio.gather(*[resolve_one(d) for d in to_fetch])

    results = dict(cached)
    expire_ts = now + _CACHE_TTL
    for domain, ips in zip(to_fetch, fresh_ips):
        results[domain] = ips
        if ips and use_cache:
            _ip_cache[domain] = (ips, expire_ts)

    return results


def generate_hosts_content(results: dict[str, list[str]]) -> str:
    """
    将 resolve_tmdb_ips() 的结果转换为 hosts 文件格式的字符串。

    示例输出：
        140.82.112.10        api.themoviedb.org
        151.101.193.140      image.tmdb.org
    """
    lines = []
    for domain, ips in results.items():
        if ips:
            lines.append(f"{ips[0]:<20} {domain}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    async def _main():
        domains = sys.argv[1:] or None
        results = await resolve_tmdb_ips(domains)
        hosts = generate_hosts_content(results)
        if hosts:
            print(hosts)
        else:
            print("未能解析任何域名（可能需要代理）", file=sys.stderr)

    asyncio.run(_main())
