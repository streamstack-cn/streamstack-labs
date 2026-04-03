"""
notify.telegram
~~~~~~~~~~~~~~~
Telegram Bot 消息推送。

支持纯文本和图片（sendPhoto）。发送图片失败时自动降级为纯文本。
需要系统代理或直连 Telegram API 的网络环境。
"""

from __future__ import annotations

from typing import Optional

import httpx


async def send_telegram(
    token: str,
    chat_id: str,
    text: str,
    image_url: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> bool:
    """
    发送 Telegram 消息。

    参数：
        token      Bot Token（从 @BotFather 获取）
        chat_id    目标频道 / 群组 / 用户 ID，如 "@channel" 或 "123456789"
        text       消息正文（纯文本模式最多 4096 字符）
        image_url  图片 URL（可选）；优先发送 sendPhoto，失败后降级为 sendMessage
        proxy_url  HTTP/SOCKS5 代理，如 "http://127.0.0.1:7890"；None 表示直连

    返回：
        True 表示推送成功，False 表示失败。
    """
    proxy_mounts = {"https://": httpx.AsyncHTTPTransport(proxy=proxy_url)} if proxy_url else None
    client_kwargs: dict = {"timeout": 15.0, "http2": True}
    if proxy_mounts:
        client_kwargs["mounts"] = proxy_mounts

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            if image_url:
                photo_url = f"https://api.telegram.org/bot{token}/sendPhoto"
                caption = text[:1024]
                resp = await client.post(
                    photo_url,
                    json={"chat_id": chat_id, "photo": image_url, "caption": caption},
                )
                if resp.json().get("ok"):
                    return True

            text_url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = await client.post(
                text_url,
                json={"chat_id": chat_id, "text": text[:4096]},
            )
            return bool(resp.json().get("ok"))
    except Exception:
        return False


if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) < 4:
        print("用法: python -m notify.telegram <token> <chat_id> <text> [proxy_url]")
        sys.exit(1)

    _proxy = sys.argv[4] if len(sys.argv) >= 5 else None
    ok = asyncio.run(send_telegram(sys.argv[1], sys.argv[2], sys.argv[3], proxy_url=_proxy))
    print("成功" if ok else "失败")
    sys.exit(0 if ok else 1)
