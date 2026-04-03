"""
示例：查询 TMDB 域名真实 IP 并生成 hosts 条目
"""
import asyncio
from tmdb_hosts import resolve_tmdb_ips, generate_hosts_content


async def main():
    print("正在查询 TMDB 域名真实 IP（约 8-10 秒）...")
    results = await resolve_tmdb_ips()

    print("\n=== 解析结果 ===")
    for domain, ips in results.items():
        status = ", ".join(ips) if ips else "❌ 未解析到"
        print(f"  {domain:<30} {status}")

    hosts = generate_hosts_content(results)
    if hosts:
        print("\n=== hosts 文件内容 ===")
        print(hosts)
        print("\n复制以上内容追加到 /etc/hosts（需要 sudo）")
    else:
        print("\n未能解析任何域名，请检查网络或配置代理。")


if __name__ == "__main__":
    asyncio.run(main())
