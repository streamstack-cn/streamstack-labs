"""
hdhive_checkin.checkin
~~~~~~~~~~~~~~~~~~~~~~
HDHive 每日签到 + 积分查询（纯 HTTP，无数据库依赖）。

需要 HDHive Premium 会员 + Open API Key。
API Key 可在 HDHive 个人设置 → Open API 中生成。

使用方法：
    import asyncio
    from hdhive_checkin import checkin, get_points

    result = asyncio.run(checkin(api_key="hh_openapi_xxx"))
    print(result)  # {"checked_in": True, "message": "签到成功，获得 10 积分"}

    info = asyncio.run(get_points(api_key="hh_openapi_xxx"))
    print(info)    # {"name": "用户名", "points": 2345, ...}
"""

from __future__ import annotations

from typing import Optional

import httpx


_DEFAULT_BASE_URL = "https://hdhive.com"
_USER_AGENT = "streamstack-labs/1.0 (hdhive_checkin)"


def _make_client(proxy_url: Optional[str], **kwargs) -> httpx.AsyncClient:
    proxy = proxy_url.strip() if proxy_url and proxy_url.strip() else None
    return httpx.AsyncClient(proxy=proxy, **kwargs) if proxy else httpx.AsyncClient(**kwargs)


def _build_headers(api_key: str) -> dict:
    return {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _USER_AGENT,
    }


class HDHiveClient:
    """
    HDHive Open API 简易客户端。

    参数：
        api_key   HDHive Open API Key
        base_url  HDHive 站点地址（默认 https://hdhive.com）
        proxy_url HTTP/SOCKS5 代理地址（可选）
        timeout   请求超时秒数（默认 15）
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        proxy_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.proxy_url = proxy_url
        self.timeout = timeout

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        headers = _build_headers(self.api_key)
        async with _make_client(self.proxy_url, timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            try:
                data = resp.json() if resp.content else {}
            except Exception:
                data = {}
            if not (200 <= resp.status_code < 300):
                desc = data.get("description") or data.get("message") or f"HTTP {resp.status_code}"
                raise RuntimeError(f"HDHive API error: {desc}")
            return data

    async def checkin(self, is_gambler: bool = False) -> dict:
        """每日签到（Premium 专属，支持赌狗模式）。"""
        data = await self._request("POST", "/api/open/checkin", json={"is_gambler": is_gambler})
        return {"message": data.get("message", ""), **(data.get("data") or {})}

    async def get_me(self) -> dict:
        """获取账户信息（积分、VIP 状态等）。"""
        data = await self._request("GET", "/api/open/me")
        return data.get("data", {})

    async def ping(self) -> dict:
        """验证 API Key 是否有效。"""
        data = await self._request("GET", "/api/open/ping")
        return data.get("data", {})


async def checkin(
    api_key: str,
    base_url: str = _DEFAULT_BASE_URL,
    proxy_url: Optional[str] = None,
    is_gambler: bool = False,
) -> dict:
    """
    执行 HDHive 每日签到。

    参数：
        api_key    HDHive Open API Key
        base_url   HDHive 站点地址（默认 https://hdhive.com）
        proxy_url  HTTP/SOCKS5 代理地址（可选）
        is_gambler 是否启用赌狗模式（True = 下注，可能获得更多或更少积分）

    返回：
        dict，包含 checked_in（bool）、message（str）等字段。
        失败时包含 error（str）字段。

    示例返回（成功）：
        {"checked_in": True, "message": "签到成功，获得 10 积分", "points": 2355}
    """
    client = HDHiveClient(api_key, base_url, proxy_url)
    try:
        return await client.checkin(is_gambler=is_gambler)
    except RuntimeError as e:
        return {"checked_in": False, "error": str(e)}


async def get_points(
    api_key: str,
    base_url: str = _DEFAULT_BASE_URL,
    proxy_url: Optional[str] = None,
) -> dict:
    """
    查询 HDHive 账户积分和 VIP 状态。

    参数：
        api_key    HDHive Open API Key
        base_url   HDHive 站点地址（默认 https://hdhive.com）
        proxy_url  HTTP/SOCKS5 代理地址（可选）

    返回：
        dict，包含 name（昵称）、points（积分）、is_vip（bool）等字段。
        失败时包含 error（str）字段。
    """
    client = HDHiveClient(api_key, base_url, proxy_url)
    try:
        return await client.get_me()
    except RuntimeError as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m hdhive_checkin.checkin <api_key> [base_url] [--gambler]")
        sys.exit(1)

    _api_key = sys.argv[1]
    _base_url = _DEFAULT_BASE_URL
    _is_gambler = False

    for arg in sys.argv[2:]:
        if arg == "--gambler":
            _is_gambler = True
        elif arg.startswith("http"):
            _base_url = arg

    async def _main():
        print("=== 签到 ===")
        r = await checkin(_api_key, _base_url, is_gambler=_is_gambler)
        print(r)
        print("=== 账户信息 ===")
        info = await get_points(_api_key, _base_url)
        print(info)

    asyncio.run(_main())
