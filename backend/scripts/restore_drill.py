"""备份恢复演练（W9 收尾 · A 项）：不能恢复的备份等于没有备份。

步骤（全程不碰主库/主 env，零风险）：
1. 取最新备份（backups/sqlite_*.db，backup_db.py 的产物）
2. PRAGMA integrity_check 验证备份文件本身完整
3. 用 sqlite3 backup API 模拟一次真实恢复（备份 → 恢复目标库），
   再对恢复目标做 integrity_check（证明备份经得起完整还原）
4. 用恢复出来的库跑只读健康检查（核心表可查、行数合理）
5. 快速档 pytest 交给调用方跑（见 README 恢复步骤），本脚本验证 DB 层

用法（backend/ 目录下）：
    python scripts/restore_drill.py
退出码 0 = 演练通过；非 0 = 备份不可恢复，立刻处理。
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backup_db import latest_backup  # noqa: E402

EXPECTED_TABLES = {"users", "projects", "cases", "leads", "worksheets"}


def check(path: Path, label: str) -> None:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        assert row and row[0] == "ok", f"[{label}] integrity_check 失败: {row}"
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = EXPECTED_TABLES - tables
        assert not missing, f"[{label}] 缺核心表: {missing}"
        n_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        n_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        print(f"[{label}] integrity_check=ok，users={n_users}，projects={n_projects}，表 {len(tables)} 张")
    finally:
        conn.close()


def main() -> None:
    src = latest_backup()
    if src is None:
        print("❌ backups/ 下没有备份，先跑 scripts/backup_db.py")
        sys.exit(1)
    print(f"演练备份: {src.name}（{src.stat().st_size / 1024:.0f} KB）")

    # 1. 备份文件本体完整性
    check(src, "备份本体")

    # 2. 模拟真实恢复：备份 → 临时恢复库（backup API，与 backup_db.py 同机制）
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False,
                                     prefix="restore_drill_") as f:
        restored = Path(f.name)
    try:
        s = sqlite3.connect(src)
        d = sqlite3.connect(restored)
        try:
            s.backup(d)
        finally:
            s.close()
            d.close()  # Windows 下不显式 close 会锁文件，finally unlink 失败
        check(restored, "恢复副本")
        print("✅ 恢复演练通过：备份可完整恢复，数据可查")
    finally:
        restored.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
