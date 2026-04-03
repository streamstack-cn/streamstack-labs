"""
notify.wechat
~~~~~~~~~~~~~
企业微信应用消息推送。

支持纯文本和图文消息（news 卡片）。
  - 有 image_url 时发送图文卡片（news），展示封面图 + 标题 + 描述。
  - 无 image_url 时发送纯文本消息（text）。

需要企业微信应用的 corp_id / app_secret / agent_id。
proxy_url 可指定代理（内网部署转发时使用），留空则直连 qyapi.weixin.qq.com。
"""

from __future__ import annotations

from typing import Optional

import httpx


async def send_wechat(
    corp_id: str,
    app_secret: str,
    agent_id: str,
    message: str,
    title: str = "",
    text: str = "",
    image_url: Optional[str] = None,
    proxy_url: Optional[str] = None,
    to_user: str = "@all",
) -> bool:
    """
    通过企业微信应用发送消息。

    参数：
        corp_id    企业 ID（corpid）
        app_secret 应用 Secret
        agent_id   应用 AgentId（字符串或整数均可）
        message    消息正文（纯文本模式使用此字段）
        title      图文卡片标题（有 image_url 时使用）
        text       图文卡片描述（有 image_url 时使用，限 512 字符）
        image_url  封面图 URL（可选）；有值时发送图文卡片
        proxy_url  代理转发地址，替换 qyapi.weixin.qq.com；None 表示直连
        to_user    接收者，默认 "@all" 表示全员

    返回：
        True 表示推送成功，False 表示失败。
    """
    base = proxy_url.rstrip("/") if proxy_url else "https://qyapi.weixin.qq.com"

    try:
        _agent_id = int(agent_id)
    except (ValueError, TypeError):
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0, http2=True) as client:
            token_resp = await client.get(
                f"{base}/cgi-bin/gettoken",
                params={"corpid": corp_id, "corpsecret": app_secret},
            )
            token_data = token_resp.json()
            if token_data.get("errcode", 0) != 0:
                return False
            access_token = token_data.get("access_token")
            if not access_token:
                return False

            if image_url:
                description = (text or message)[:512]
                payload = {
                    "touser": to_user,
                    "msgtype": "news",
                    "agentid": _agent_id,
                    "news": {
                        "articles": [{
                            "title": title or message[:64],
                            "description": description,
                            "url": "",
                            "picurl": image_url,
                        }]
                    },
                }
            else:
                payload = {
                    "touser": to_user,
                    "msgtype": "text",
                    "agentid": _agent_id,
                    "text": {"content": message},
                    "safe": 0,
                }

            send_resp = await client.post(
                f"{base}/cgi-bin/message/send",
                params={"access_token": access_token},
                json=payload,
            )
            return send_resp.json().get("errcode", -1) == 0
    except Exception:
        return False


if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) < 5:
        print("用法: python -m notify.wechat <corp_id> <app_secret> <agent_id> <message> [proxy_url]")
        sys.exit(1)

    _proxy = sys.argv[5] if len(sys.argv) >= 6 else None
    ok = asyncio.run(send_wechat(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], proxy_url=_proxy))
    print("成功" if ok else "失败")
    sys.exit(0 if ok else 1)
