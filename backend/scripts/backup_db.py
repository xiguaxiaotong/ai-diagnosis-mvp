"""SQLite 自动备份（W9 收尾 · A 项）：sqlite3 backup API 热备。

为什么用 backup API 而不是复制文件：主库正被 uvicorn 写入时直接 copy
可能拿到「写了一半」的页（WAL 边界尤其危险）；Connection.backup 走
SQLite 页级拷贝，事务一致性由 SQLite 自己保证，**不停服务**。

用法（backend/ 目录下）：
    python scripts/backup_db.py            # 备份主库，保留最近 14 份
    python scripts/backup_db.py --keep 7   # 自定义保留份数

产物：backend/backups/sqlite_YYYYMMDD_HHMMSS.db
恢复演练：scripts/restore_drill.py（integrity_check + 快速档 pytest）
Windows 计划任务（每天 03:00，以当前用户运行，不用管理员）：

    schtasks /Create /TN "AIDiagnosis-DBBackup" /SC DAILY /ST 03:00 ^
      /TR "cmd /c cd /d D:/ai-diagnosis-mvp/backend && ^
C:/Users/31905/miniconda3/python.exe scripts/backup_db.py >> backups/backup.log 2>&1"

（^ 是 cmd 续行符；复制时合成一行，README 里有完整版说明）

注意：备份的是主业务库（SQLITE_PATH，默认 backend/data/sqlite.db）。
checkpoints.sqlite 不备份——checkpointer 是会话中间态，损坏/丢失只影响
进行中的对话，新会话照常，不值得翻倍备份。
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
KEEP_DEFAULT = 14


def latest_backup() -> Path | None:
    """最新的备份文件（无备份返回 None）。"""
    files = sorted(BACKUP_DIR.glob("sqlite_*.db"))
    return files[-1] if files else None


def prune_backups(keep: int = KEEP_DEFAULT) -> int:
    """删掉最旧的，只保留最近 keep 份。返回删除数。"""
    files = sorted(BACKUP_DIR.glob("sqlite_*.db"))
    doomed = files[:-keep] if keep > 0 else files
    for f in doomed:
        f.unlink()
        print(f"[清理] 删除旧备份 {f.name}")
    return len(doomed)


def backup(keep: int = KEEP_DEFAULT) -> Path:
    src = settings.SQLITE_PATH
    if not Path(src).exists():
        print(f"❌ 主库不存在: {src}")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / time.strftime("sqlite_%Y%m%d_%H%M%S.db")

    # 热备：源库连接句柄 → 目标库，SQLite 页级拷贝，不停服务
    t0 = time.monotonic()
    with sqlite3.connect(src) as src_conn, sqlite3.connect(dest) as dst_conn:
        src_conn.backup(dst_conn)
    ms = (time.monotonic() - t0) * 1000

    size_kb = dest.stat().st_size / 1024
    n = prune_backups(keep)
    print(f"[备份] {Path(src).name} → {dest.name}（{size_kb:.0f} KB，{ms:.0f} ms，清理 {n} 份旧备份）")
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SQLite 热备份")
    ap.add_argument("--keep", type=int, default=KEEP_DEFAULT, help="保留最近 N 份（默认 14）")
    args = ap.parse_args()
    backup(args.keep)
