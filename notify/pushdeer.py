"""
notify.pushdeer
~~~~~~~~~~~~~~~
PushDeer 消息推送（Markdown 格式）。

PushDeer 为国内服务，通常可直连，无需代理。
使用 markdown 类型分离 title / body，避免换行被压缩。
"""

from __future__ import annotations

import httpx


async def send_pushdeer(
    server: str,
    key: str,
    title: str,
    body: str,
) -> bool:
    """
    发送 PushDeer 推送消息。

    参数：
        server  PushDeer 服务器地址，如 "https://api2.pushdeer.com"
        key     PushDeer 推送 Key（pushkey）
        title   消息标题
        body    消息正文（支持换行，空行会被自动清理）

    返回：
        True 表示推送成功，False 表示失败。
    """
    url = f"{server.rstrip('/')}/message/push"
    lines = [line for line in body.split("\n") if line.strip()]
    desp = "  \n".join(lines)
    payload = {
        "pushkey": key,
        "text": title,
        "desp": desp,
        "type": "markdown",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, http2=True) as client:
            resp = await client.post(url, json=payload)
            return resp.json().get("code") == 0
    except Exception:
        return False


if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) < 5:
        print("用法: python -m notify.pushdeer <server> <key> <title> <body>")
        sys.exit(1)

    ok = asyncio.run(send_pushdeer(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
    print("成功" if ok else "失败")
    sys.exit(0 if ok else 1)
