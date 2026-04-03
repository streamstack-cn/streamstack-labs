"""
torrent_incubator.incubator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
种子孵化器核心逻辑（独立版，无数据库依赖）。

功能：
  1. 定期扫描监控目录，发现新 .torrent 文件
  2. 自动提交到 qBittorrent（打 incubator 标签）
  3. 轮询已提交种子的完成状态
  4. 完成后可选自动删除 .torrent 文件

数据持久化：使用本地 JSON 文件（默认 ~/.torrent_incubator/state.json），
无需数据库。

用法（命令行）::

    python -m torrent_incubator --config config.yaml

用法（代码）::

    import asyncio
    from torrent_incubator import TorrentIncubator, IncubatorConfig

    config = IncubatorConfig(
        watch_dir="/downloads/torrents",
        qb_url="http://localhost:8080",
        qb_username="admin",
        qb_password="password",
    )
    incubator = TorrentIncubator(config)
    asyncio.run(incubator.scan_once())
"""

import asyncio
import datetime
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_INCUBATOR_TAG = "incubator"

# 防并发重入：30 秒内不允许重复扫描
_MIN_SCAN_INTERVAL = 30.0

# SID 缓存（避免每次扫描都重新登录 qBittorrent）
_qb_sid_cache: dict[str, dict] = {}


@dataclass
class IncubatorConfig:
    """孵化器配置。"""
    watch_dir: str = "."
    qb_url: str = "http://localhost:8080"
    qb_username: str = "admin"
    qb_password: str = "adminadmin"
    qb_category: str = ""
    qb_save_path: str = ""
    qb_tags: str = ""          # 额外标签，以逗号分隔，自动追加 incubator 标签
    auto_delete_torrent: bool = False
    state_file: str = str(Path.home() / ".torrent_incubator" / "state.json")
    scan_interval_seconds: int = 300   # 用于 run_forever 模式


@dataclass
class TorrentRecord:
    """单个种子的跟踪记录。"""
    torrent_path: str
    torrent_filename: str
    status: str = "pending"          # pending | submitted | completed | failed
    info_hash: Optional[str] = None
    qb_name: Optional[str] = None
    error_msg: Optional[str] = None
    submitted_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())


class TorrentIncubator:
    """
    种子孵化器主类。

    :param config: ``IncubatorConfig`` 实例
    """

    def __init__(self, config: IncubatorConfig):
        self.config = config
        self._last_scan_ts: float = 0.0
        self._records: dict[str, TorrentRecord] = {}
        self._load_state()

    # ─────────────────────────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────────────────────────

    async def scan_once(self, force: bool = False) -> dict:
        """
        执行一次扫描：发现新种子 → 提交 → 检查完成。

        :param force: True 时跳过冷却时间检查
        :returns: 本次扫描摘要 dict
        """
        now = time.time()
        if not force and now - self._last_scan_ts < _MIN_SCAN_INTERVAL:
            remaining = int(_MIN_SCAN_INTERVAL - (now - self._last_scan_ts))
            return {"skipped": True, "reason": f"冷却中，请 {remaining} 秒后再试"}
        self._last_scan_ts = now

        watch_dir = self.config.watch_dir
        if not os.path.isdir(watch_dir):
            logger.warning(f"[孵化器] 监控目录不存在: {watch_dir}")
            return {"skipped": True, "reason": f"目录不存在: {watch_dir}"}

        torrent_files = _find_torrent_files(watch_dir)
        logger.debug(f"[孵化器] 发现 {len(torrent_files)} 个 .torrent 文件")

        submitted_count = 0
        skipped_count = 0
        failed_count = 0

        for fpath in torrent_files:
            rec = self._records.get(fpath)
            if rec and rec.status in ("submitted", "completed"):
                skipped_count += 1
                continue
            if rec and rec.status == "failed":
                skipped_count += 1
                continue

            ok = await self._submit_torrent(fpath)
            if ok:
                submitted_count += 1
            else:
                failed_count += 1

        completed_count = await self._check_completions()

        summary = {
            "watch_dir": watch_dir,
            "total_files": len(torrent_files),
            "submitted": submitted_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "newly_completed": completed_count,
        }
        logger.info(
            f"[孵化器] 扫描完成：发现{len(torrent_files)}个，"
            f"新提交{submitted_count}个，完成{completed_count}个"
        )
        return summary

    async def run_forever(self) -> None:
        """
        持续运行模式：每隔 ``config.scan_interval_seconds`` 秒执行一次扫描。

        可通过 Ctrl+C 停止。
        """
        logger.info(
            f"[孵化器] 启动持续监控，间隔 {self.config.scan_interval_seconds}s，"
            f"目录: {self.config.watch_dir}"
        )
        while True:
            try:
                await self.scan_once(force=True)
            except Exception as e:
                logger.error(f"[孵化器] 扫描异常: {e}")
            await asyncio.sleep(self.config.scan_interval_seconds)

    def reset_failed(self, torrent_path: str) -> bool:
        """将指定种子的失败记录重置为 pending，下次扫描时重新提交。"""
        rec = self._records.get(torrent_path)
        if not rec:
            return False
        rec.status = "pending"
        rec.error_msg = None
        rec.info_hash = None
        rec.submitted_at = None
        rec.completed_at = None
        self._save_state()
        return True

    def get_records(self) -> list[dict]:
        """返回所有种子记录列表（按 created_at 倒序）。"""
        records = list(self._records.values())
        records.sort(key=lambda r: r.created_at or "", reverse=True)
        return [asdict(r) for r in records]

    def get_stats(self) -> dict:
        """返回各状态种子数量统计。"""
        records = list(self._records.values())
        return {
            "total": len(records),
            "pending": sum(1 for r in records if r.status == "pending"),
            "submitted": sum(1 for r in records if r.status == "submitted"),
            "completed": sum(1 for r in records if r.status == "completed"),
            "failed": sum(1 for r in records if r.status == "failed"),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 内部：提交种子
    # ─────────────────────────────────────────────────────────────────────────

    async def _submit_torrent(self, fpath: str) -> bool:
        filename = os.path.basename(fpath)
        logger.info(f"[孵化器] 提交种子: {filename}")

        try:
            content = Path(fpath).read_bytes()
        except Exception as e:
            logger.warning(f"[孵化器] 读取文件失败: {filename} — {e}")
            self._upsert_record(fpath, filename, status="failed", error_msg=str(e))
            return False

        client = await _get_authed_client(self.config)
        if not client:
            self._upsert_record(fpath, filename, status="failed", error_msg="qB 登录失败")
            return False

        cfg = self.config
        tags = ",".join(filter(None, [cfg.qb_tags, _INCUBATOR_TAG]))
        payload: dict = {"tags": tags, "useAutoTMM": "true"}
        if cfg.qb_category:
            payload["category"] = cfg.qb_category
        if cfg.qb_save_path:
            payload["savepath"] = cfg.qb_save_path
            payload["useAutoTMM"] = "false"

        try:
            files = {"torrents": (filename, content, "application/x-bittorrent")}
            add_resp = await client.post(
                f"{cfg.qb_url}/api/v2/torrents/add",
                files=files,
                data=payload,
            )
            text = add_resp.text.strip()

            if add_resp.status_code == 200 and text in ("Ok.", "Fails."):
                await asyncio.sleep(2.0)
                info_hash, qb_name = await _fetch_hash_by_tag(client, cfg.qb_url, filename)
                self._upsert_record(
                    fpath, filename, status="submitted",
                    info_hash=info_hash, qb_name=qb_name,
                    submitted_at=datetime.datetime.utcnow().isoformat(),
                )
                logger.info(f"[孵化器] 提交成功: {filename} hash={info_hash or '待获取'}")
                return True
            else:
                self._upsert_record(fpath, filename, status="failed",
                                    error_msg=f"qB 响应: {text} (HTTP {add_resp.status_code})")
                return False
        except Exception as e:
            logger.warning(f"[孵化器] 提交异常: {filename} — {e}")
            self._upsert_record(fpath, filename, status="failed", error_msg=str(e))
            return False
        finally:
            await client.aclose()

    # ─────────────────────────────────────────────────────────────────────────
    # 内部：完成检测
    # ─────────────────────────────────────────────────────────────────────────

    async def _check_completions(self) -> int:
        pending = [r for r in self._records.values() if r.status == "submitted"]
        if not pending:
            return 0

        client = await _get_authed_client(self.config)
        if not client:
            return 0

        newly_completed = 0
        seeding_states = {"uploading", "stalledup", "forcedup", "queuedup", "pausedup", "stoppedup"}
        try:
            for rec in pending:
                if not rec.info_hash:
                    info_hash, qb_name = await _fetch_hash_by_tag(
                        client, self.config.qb_url, rec.torrent_filename or ""
                    )
                    if info_hash:
                        rec.info_hash = info_hash
                        rec.qb_name = qb_name
                        self._save_state()
                    continue

                try:
                    resp = await client.get(
                        f"{self.config.qb_url}/api/v2/torrents/info",
                        params={"hashes": rec.info_hash},
                    )
                    if resp.status_code != 200:
                        continue
                    items = resp.json()
                    if not items:
                        self._mark_completed(rec)
                        newly_completed += 1
                        continue

                    t = items[0]
                    progress = t.get("progress", 0)
                    tags_str = (t.get("tags") or "").upper()
                    state = (t.get("state") or "").lower()

                    is_done = (
                        progress >= 1.0
                        or "COMPLETED" in tags_str
                        or state in seeding_states
                    )
                    if is_done:
                        logger.info(
                            f"[孵化器] 下载完成: {rec.qb_name or rec.torrent_filename} "
                            f"progress={progress:.0%} state={state}"
                        )
                        self._mark_completed(rec)
                        newly_completed += 1
                except Exception as e:
                    logger.debug(f"[孵化器] 检查单条记录时出错: {e}")
        finally:
            await client.aclose()

        return newly_completed

    def _mark_completed(self, rec: TorrentRecord) -> None:
        rec.status = "completed"
        rec.completed_at = datetime.datetime.utcnow().isoformat()
        self._save_state()
        if self.config.auto_delete_torrent and rec.torrent_path:
            try:
                if os.path.isfile(rec.torrent_path):
                    os.remove(rec.torrent_path)
                    logger.info(f"[孵化器] 已删除 .torrent 文件: {rec.torrent_path}")
            except Exception as e:
                logger.warning(f"[孵化器] 删除 .torrent 文件失败: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # 内部：状态持久化（JSON 文件）
    # ─────────────────────────────────────────────────────────────────────────

    def _upsert_record(self, torrent_path: str, torrent_filename: str, **kwargs) -> None:
        rec = self._records.get(torrent_path)
        if rec:
            for k, v in kwargs.items():
                setattr(rec, k, v)
        else:
            self._records[torrent_path] = TorrentRecord(
                torrent_path=torrent_path,
                torrent_filename=torrent_filename,
                **kwargs,
            )
        self._save_state()

    def _load_state(self) -> None:
        state_path = Path(self.config.state_file)
        if not state_path.exists():
            return
        try:
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("records", []):
                rec = TorrentRecord(**{k: v for k, v in item.items() if k in TorrentRecord.__dataclass_fields__})
                self._records[rec.torrent_path] = rec
            logger.debug(f"[孵化器] 加载状态: {len(self._records)} 条记录")
        except Exception as e:
            logger.warning(f"[孵化器] 加载状态文件失败: {e}")

    def _save_state(self) -> None:
        state_path = Path(self.config.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"records": [asdict(r) for r in self._records.values()]},
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logger.warning(f"[孵化器] 保存状态文件失败: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _find_torrent_files(watch_dir: str) -> list[str]:
    """递归查找目录下所有 .torrent 文件，按修改时间升序返回，跳过正在写入的文件。"""
    result = []
    try:
        for root, _dirs, files in os.walk(watch_dir):
            for f in files:
                if f.lower().endswith(".torrent"):
                    full = os.path.join(root, f)
                    try:
                        stat = os.stat(full)
                        if time.time() - stat.st_mtime < 3:   # 正在写入，跳过
                            continue
                        if stat.st_size < 32:                  # 不可能是有效 .torrent
                            continue
                        result.append(full)
                    except OSError:
                        continue
    except Exception as e:
        logger.warning(f"[孵化器] 扫描目录出错: {e}")
    result.sort(key=lambda p: os.path.getmtime(p))
    return result


async def _get_authed_client(config: IncubatorConfig) -> Optional[httpx.AsyncClient]:
    """返回已登录的 httpx.AsyncClient（带 SID cookie），失败返回 None。"""
    url = config.qb_url.rstrip("/")
    headers = {"Referer": f"{url}/", "Origin": url}
    client = httpx.AsyncClient(timeout=15.0, headers=headers)

    cached = _qb_sid_cache.get(url)
    if cached and time.time() < cached["expires"]:
        client.cookies.set("SID", cached["sid"])
        return client

    try:
        resp = await client.post(
            f"{url}/api/v2/auth/login",
            data={"username": config.qb_username, "password": config.qb_password},
        )
        if resp.text.strip() != "Ok.":
            await client.aclose()
            return None
        sid = client.cookies.get("SID")
        if sid:
            _qb_sid_cache[url] = {"sid": sid, "expires": time.time() + 1200}
        return client
    except Exception as e:
        await client.aclose()
        logger.warning(f"[孵化器] qB 登录失败: {e}")
        return None


async def _fetch_hash_by_tag(
    client: httpx.AsyncClient, qb_url: str, filename: str
) -> tuple[Optional[str], Optional[str]]:
    """提交后立即查询 qB，从 incubator 标签的种子中找刚加入的（按 added_on 倒序）。"""
    try:
        resp = await client.get(
            f"{qb_url}/api/v2/torrents/info",
            params={"tag": _INCUBATOR_TAG, "sort": "added_on", "reverse": "true", "limit": "20"},
        )
        if resp.status_code != 200:
            return None, None
        items = resp.json()
        if not items:
            return None, None
        stem = os.path.splitext(filename)[0].lower()
        for item in items:
            name = (item.get("name") or "").lower()
            if stem in name or name in stem:
                return item.get("hash"), item.get("name")
        return items[0].get("hash"), items[0].get("name")
    except Exception as e:
        logger.debug(f"[孵化器] 获取 hash 失败: {e}")
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def _load_config_from_yaml(path: str) -> IncubatorConfig:
    """从 YAML 文件加载配置，未指定的字段使用默认值。"""
    import yaml
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    fields = {k: v for k, v in data.items() if k in IncubatorConfig.__dataclass_fields__}
    return IncubatorConfig(**fields)


async def _cli_main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="种子孵化器 — 自动监控目录并提交到 qBittorrent")
    parser.add_argument("--config", "-c", default="config.yaml", help="YAML 配置文件路径")
    parser.add_argument("--once", action="store_true", help="仅执行一次扫描后退出")
    parser.add_argument("--stats", action="store_true", help="打印统计信息后退出")
    args = parser.parse_args()

    config = _load_config_from_yaml(args.config) if os.path.exists(args.config) else IncubatorConfig()
    incubator = TorrentIncubator(config)

    if args.stats:
        import pprint
        pprint.pprint(incubator.get_stats())
        return

    if args.once:
        result = await incubator.scan_once(force=True)
        import pprint
        pprint.pprint(result)
    else:
        await incubator.run_forever()


if __name__ == "__main__":
    asyncio.run(_cli_main())
