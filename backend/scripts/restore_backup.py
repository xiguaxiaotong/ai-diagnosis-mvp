"""从备份快照恢复（W10 Day5）：默认 dry-run 校验，--apply 才动真库。

和 purge_test_data.py 同风格：默认模式一个字节不写真库——把备份快照
恢复到临时库并做全套校验（integrity + 行数 sanity），打印「将执行」
清单；--apply 才替换真库，替换前把当前真库再快照一份到 backups/
（恢复操作本身也要可撤销）。

用法（backend/ 下）：
    python scripts/restore_backup.py backups/20260926_030000   # dry-run 校验
    python scripts/restore_backup.py backups/20260926_030000 --apply  # 真恢复

--apply 前提：**后端已停**（uvicorn 占着 sqlite 会锁/写脏页）。
完整恢复三步（见 docs/DEPLOY_RUNBOOK.md「服务器端备份」）：
    停服 → 本脚本 --apply（替换库 + integrity_check）→ 起服。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import CHECKPOINTS_PATH, SQLITE_PATH  # noqa: E402

BACKUP_ROOT = Path(__file__).resolve().parent.parent / "backups"
DRILL_DIR = Path(__file__).resolve().parent.parent / "data" / "restore_drill_tmp"

SANITY_TABLES = ("users", "projects", "conversations", "leads", "worksheets")


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(1)


def _validate_backup_db(path: Path, what: str) -> None:
    """integrity_check + 行数 sanity；库文件损坏直接报错退出。"""
    try:
        con = sqlite3.connect(path)
    except sqlite3.DatabaseError as e:
        fail(f"{what} 打不开（文件损坏？）：{e}")
    try:
        ok = con.execute("pragma integrity_check").fetchone()[0]
        if ok != "ok":
            fail(f"{what} integrity_check = {ok}，备份不可用，拒绝恢复")
        print(f"  [校验] {what}: integrity ok")
        for t in SANITY_TABLES:
            try:
                n = con.execute(f"select count(*) from {t}").fetchone()[0]
                print(f"  [校验] {what}.{t}: {n} 行")
            except sqlite3.OperationalError:
                pass  # 表不存在（老备份结构差异）不算致命
    except sqlite3.DatabaseError as e:
        fail(f"{what} 读取失败（文件损坏？）：{e}")
    finally:
        con.close()


def verify_snapshot(snap: Path) -> None:
    """校验备份目录完整性：目录存在、主库在、能过 integrity。"""
    if not snap.exists():
        fail(f"备份目录不存在: {snap}")
    if not snap.is_dir():
        fail(f"不是目录: {snap}（要传 backups/YYYYMMDD_HHMMSS 这样的快照目录）")
    db = snap / "sqlite.db"
    if not db.exists():
        fail(f"快照缺主库文件: {db}\n（快照目录应含 sqlite.db，由 backup_full.py 生成）")
    _validate_backup_db(db, "主库备份")
    cp = snap / "checkpoints.sqlite"
    if cp.exists():
        _validate_backup_db(cp, "checkpoints 备份")
    else:
        print("  [校验] 无 checkpoints 备份（备份时库不存在，正常跳过）")
    purges = sorted(snap.glob("purge_*.json"))
    print(f"  [校验] 附带 purge 归档 {len(purges)} 份")


def dry_run(snap: Path) -> None:
    """恢复演练：把快照恢复到临时库并校验，真库一个字节不碰。"""
    verify_snapshot(snap)
    if DRILL_DIR.exists():
        shutil.rmtree(DRILL_DIR)
    DRILL_DIR.mkdir(parents=True)
    hot_copy(snap / "sqlite.db", DRILL_DIR / "sqlite.db")
    _validate_backup_db(DRILL_DIR / "sqlite.db", "临时恢复库（主库）")
    cp = snap / "checkpoints.sqlite"
    if cp.exists():
        hot_copy(cp, DRILL_DIR / "checkpoints.sqlite")
        _validate_backup_db(DRILL_DIR / "checkpoints.sqlite", "临时恢复库（checkpoints）")
    shutil.rmtree(DRILL_DIR)
    print("\n[DRY-RUN] 校验通过，未动真库。真恢复：加 --apply（须先停后端）")
    print(f"  将执行：{snap / 'sqlite.db'} → {SQLITE_PATH}")
    if cp.exists():
        print(f"  将执行：{cp} → {CHECKPOINTS_PATH}")


def hot_copy(src: Path, dest: Path) -> None:
    """源是备份文件（没人写它），但同样走 backup API 保持一致性。

    显式 close：connect 的 with 不关连接，Windows 上不关就删不掉文件。
    """
    s = sqlite3.connect(src)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()


def apply_restore(snap: Path) -> None:
    """真恢复：替换真库前先把当前真库快照一份（恢复也要可撤销）。"""
    verify_snapshot(snap)
    # 当前真库的「恢复前快照」（落在 backups/ 根，扁平文件，backup_db.py 风格）
    pre = BACKUP_ROOT / time.strftime("pre_restore_%Y%m%d_%H%M%S.db")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    hot_copy(SQLITE_PATH, pre)
    print(f"[恢复前快照] 当前真库 → {pre.name}")

    hot_copy(snap / "sqlite.db", SQLITE_PATH)
    _validate_backup_db(SQLITE_PATH, "恢复后的真库")
    cp = snap / "checkpoints.sqlite"
    if cp.exists():
        hot_copy(cp, CHECKPOINTS_PATH)
        _validate_backup_db(CHECKPOINTS_PATH, "恢复后的 checkpoints 库")
    print(f"✅ 已从 {snap.name} 恢复到真库。integrity ok。起服后建议跑快速档冒烟。")


def main() -> None:
    ap = argparse.ArgumentParser(description="从备份快照恢复（默认 dry-run）")
    ap.add_argument("snapshot", type=Path, help="快照目录（backups/YYYYMMDD_HHMMSS）")
    ap.add_argument("--apply", action="store_true", help="真恢复（默认 dry-run）")
    args = ap.parse_args()
    snap = args.snapshot
    if not snap.is_absolute():
        cand = BACKUP_ROOT / snap
        snap = cand if cand.exists() else snap
    if args.apply:
        print("⚠️ 确认后端已停（uvicorn 占着 sqlite 会锁/写脏页）——3 秒后开始恢复")
        time.sleep(3)
        apply_restore(snap)
    else:
        dry_run(snap)


if __name__ == "__main__":
    main()
