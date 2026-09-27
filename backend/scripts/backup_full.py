"""一键全量备份（W10 Day5）：主库 + checkpoints 库 + 当日 purge 归档。

与 W9 的 backup_db.py（单库热备）的关系：那是每日自动备份的轻量版，
本脚本是**全量快照版**——一次备份齐全套可恢复的东西：

    backups/20260926_030000/
        sqlite.db            # 主库热备（backup API，不停服）
        checkpoints.sqlite   # checkpointer 库热备（同 API；不存在则跳过）
        purge_20260926.json  # 当日的 purge 归档（如有，从 backups 根捞进来）

备份后立即对**备份副本**跑 PRAGMA integrity_check，任何一个不 ok 都
非零退出（备份的意义是「能恢复」，不是「文件存在」）。

用法（backend/ 下）：
    python scripts/backup_full.py             # 全量备份 + 默认保留 7 份快照
    python scripts/backup_full.py --prune 3    # 只保留最近 3 份
    python scripts/backup_full.py --no-prune   # 只备不清

服务器 cron 用法（宿主 python3 无 venv，纯标准库）：
    python3 scripts/backup_full.py --db data/sqlite.db --checkpoints data/checkpoints.sqlite

Windows 计划任务注册：scripts/register_backup_task.bat（每天 03:00）。
恢复：scripts/restore_backup.py（默认 dry-run，--apply 才动真库）。

⚠️ 本脚本只准用标准库：设计上服务器 cron / 任何裸 python 都要能跑，
曾因 import app.config 拖进 dotenv 依赖在服务器上 ModuleNotFoundError
（W11 Day3 实战踩坑）。默认路径仍与 app.config 对齐。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKUP_ROOT = Path(__file__).resolve().parent.parent / "backups"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "sqlite.db"
DEFAULT_CP = Path(__file__).resolve().parent.parent / "data" / "checkpoints.sqlite"
SNAPSHOT_DIR_RE = re.compile(r"^\d{8}_\d{6}$")  # 20260926_030000
PRUNE_DEFAULT = 7


def hot_backup(src: Path, dest: Path) -> None:
    """SQLite backup API 热备（页级拷贝，源库正被写入也安全）。

    注意显式 close：sqlite3.connect 的 with 只管事务不关连接，
    句柄不关 Windows 上删不掉文件（restore 演练要删临时库）。
    """
    s = sqlite3.connect(src)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()


def integrity_ok(path: Path) -> bool:
    """对库文件跑 PRAGMA integrity_check；打不开（损坏）同样算不过。"""
    try:
        con = sqlite3.connect(path)
    except sqlite3.DatabaseError:
        return False
    try:
        return con.execute("pragma integrity_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        return False
    finally:
        con.close()


def collect_purge_archives(backup_root: Path, today: str) -> list[Path]:
    """当日的 purge 归档（purge_YYYYMMDD*.json），从 backups 根目录捞。"""
    return sorted(backup_root.glob(f"purge_{today}*.json"))


def make_backup(
    db: Path, cp: Path | None, backup_root: Path,
    today: str | None = None, now: str | None = None,
) -> Path:
    """做一份全量快照，返回快照目录。备份副本 integrity 不过会非零退出。

    today/now 可注入（测试用）；默认取系统当前日期/时间戳。
    """
    if not db.exists():
        print(f"❌ 主库不存在: {db}")
        sys.exit(1)
    today = today or time.strftime("%Y%m%d")
    stamp = now or time.strftime("%Y%m%d_%H%M%S")
    dest_dir = backup_root / stamp
    while dest_dir.exists():  # 同秒重跑：等 1 秒换新戳，保持命名规范
        time.sleep(1)          # （prune 按目录名排序，名字必须始终匹配 SNAPSHOT_DIR_RE）
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest_dir = backup_root / stamp
    dest_dir.mkdir(parents=True)

    # 1) 主库热备
    t0 = time.monotonic()
    hot_backup(db, dest_dir / "sqlite.db")
    ms = (time.monotonic() - t0) * 1000

    # 2) checkpoints 库（不存在则跳过，不算错——空库天经地义）
    cp_note = "无（跳过）"
    if cp and cp.exists():
        hot_backup(cp, dest_dir / "checkpoints.sqlite")
        cp_note = f"{cp.stat().st_size / 1024:.0f} KB"

    # 3) 当日 purge 归档
    n_purge = 0
    for f in collect_purge_archives(backup_root, today):
        shutil.copy2(f, dest_dir / f.name)
        n_purge += 1

    # 4) 备份副本立即 integrity_check（失败非零退出）
    ok = integrity_ok(dest_dir / "sqlite.db")
    cp_ok = True
    if (dest_dir / "checkpoints.sqlite").exists():
        cp_ok = integrity_ok(dest_dir / "checkpoints.sqlite")
    print(f"[备份] {dest_dir}")
    print(f"  主库 sqlite.db（{(dest_dir / 'sqlite.db').stat().st_size / 1024:.0f} KB，{ms:.0f} ms）"
          f" integrity={'ok' if ok else 'FAIL'}")
    print(f"  checkpoints {cp_note} integrity={'ok' if cp_ok else 'FAIL'}")
    print(f"  当日 purge 归档 {n_purge} 份")
    if not (ok and cp_ok):
        print(f"❌ 备份副本 integrity_check 未通过，快照 {dest_dir} 不可信")
        sys.exit(1)
    return dest_dir


def prune_snapshots(backup_root: Path, keep: int, dry: bool = False) -> list[Path]:
    """只保留最近 keep 份快照目录（YYYYMMDD_HHMMSS），删旧前打印清单。

    只动快照目录——backups 根下的单库热备（sqlite_*.db）和 purge 归档
    （purge_*.json）是 backup_db.py / purge_test_data.py 的产物，不归本
    脚本管。返回被删目录列表（dry=True 只列不删）。
    """
    snaps = sorted(d for d in backup_root.iterdir()
                    if d.is_dir() and SNAPSHOT_DIR_RE.match(d.name))
    doomed = snaps[:-keep] if keep > 0 else snaps
    if doomed:
        print(f"[prune] 将删除 {len(doomed)} 份旧快照（保留最近 {keep} 份）：")
        for d in doomed:
            print(f"  - {d.name}")
        if not dry:
            for d in doomed:
                shutil.rmtree(d)
    else:
        print(f"[prune] 现有 {len(snaps)} 份快照 ≤ 保留 {keep} 份，无需清理")
    return doomed


def main() -> None:
    ap = argparse.ArgumentParser(description="一键全量备份（主库+checkpoints+purge归档）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="主库路径（默认 data/sqlite.db）")
    ap.add_argument("--checkpoints", type=Path, default=DEFAULT_CP,
                    help="checkpoints 库路径（默认 data/checkpoints.sqlite）")
    ap.add_argument("--prune", type=int, default=PRUNE_DEFAULT,
                    help=f"保留最近 N 份快照（默认 {PRUNE_DEFAULT}；0 = 全清）")
    ap.add_argument("--no-prune", action="store_true", help="只备不清")
    ap.add_argument("--backup-root", type=Path, default=BACKUP_ROOT)
    args = ap.parse_args()

    make_backup(args.db, args.checkpoints, args.backup_root)
    if not args.no_prune:
        prune_snapshots(args.backup_root, args.prune)
    print("✅ 全量备份完成")


if __name__ == "__main__":
    main()
