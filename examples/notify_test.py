"""
示例：测试各推送渠道

运行前请替换下面的配置参数。
"""
import asyncio
from notify import send_pushdeer, send_telegram, send_wechat

# ── 配置（替换为真实值）──────────────────────────────────────────────────────

PUSHDEER_SERVER = "https://api2.pushdeer.com"
PUSHDEER_KEY = "PDU...your_key..."

TG_TOKEN = "123456:ABCDEFxxx"
TG_CHAT_ID = "@your_channel"
TG_PROXY = None  # 如 "http://127.0.0.1:7890"

WECHAT_CORP_ID = "ww1234..."
WECHAT_APP_SECRET = "secret..."
WECHAT_AGENT_ID = "100001"

# ─────────────────────────────────────────────────────────────────────────────


async def main():
    print("=== PushDeer ===")
    ok = await send_pushdeer(
        server=PUSHDEER_SERVER,
        key=PUSHDEER_KEY,
        title="测试推送",
        body="这是一条来自 streamstack-labs 的测试消息\n第二行内容",
    )
    print(f"PushDeer: {'成功' if ok else '失败'}")

    print("\n=== Telegram ===")
    ok = await send_telegram(
        token=TG_TOKEN,
        chat_id=TG_CHAT_ID,
        text="这是一条来自 streamstack-labs 的 Telegram 测试消息",
        proxy_url=TG_PROXY,
    )
    print(f"Telegram: {'成功' if ok else '失败（网络不通或配置错误）'}")

    print("\n=== 企业微信 ===")
    ok = await send_wechat(
        corp_id=WECHAT_CORP_ID,
        app_secret=WECHAT_APP_SECRET,
        agent_id=WECHAT_AGENT_ID,
        message="这是一条来自 streamstack-labs 的企业微信测试消息",
    )
    print(f"企业微信: {'成功' if ok else '失败'}")


if __name__ == "__main__":
    asyncio.run(main())
