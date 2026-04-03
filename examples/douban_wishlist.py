"""
示例：获取豆瓣「想看」列表

使用前请将 COOKIE 替换为你的豆瓣 Cookie（需包含 dbcl2 和 ck 字段）。
可在浏览器开发者工具 → Network → 任意豆瓣请求 → Request Headers → Cookie 中获取。
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from douban import check_cookie, get_wish_list

COOKIE = "dbcl2=YOUR_UID:YOUR_HASH; ck=YOUR_CK"  # ← 替换为真实 Cookie


async def main():
    print("正在验证 Cookie...")
    result = await check_cookie(COOKIE)
    print(f"Cookie 状态: valid={result['valid']}, user_id={result['user_id']}, name={result['name']}")

    if not result["valid"]:
        print("Cookie 无效，请检查并重新获取")
        return

    print(f"\n正在获取「想看」列表...")
    wishlist = await get_wish_list(COOKIE, result["user_id"], media_type="all")
    print(f"共 {len(wishlist)} 条\n")

    for item in wishlist[:10]:
        mtype = "📽️" if item["media_type"] == "movie" else "📺"
        print(f"{mtype} {item['title']} ({item['year']}) ⭐{item['rating']}")


asyncio.run(main())
