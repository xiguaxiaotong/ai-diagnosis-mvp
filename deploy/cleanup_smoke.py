"""生产库冒烟数据清理（v2.0 上线预案包 · W10 Day3）。

用途：DEPLOY_RUNBOOK 第 6 步——对生产 API 跑完 tests/test_smoke_e2e.py 后，
本地没有生产库文件（SMOKE_DB 未设 → 套件只做 API 级清理），smoke_ 前缀的
注册用户/会话行会残留在生产库。本脚本在**服务器宿主机**上直接清：

    cd /home/ubuntu/ai-diagnosis
    python3 deploy/cleanup_smoke.py backend/data/sqlite.db

幂等：重复跑无副作用；只删 username 以 smoke_ 开头的行（LIKE 转义下划线，
不会误伤名字里恰好带 smoke 的正常用户）。

为什么删用户行：项目/对话已由套件内 API 删除（test_99），剩余的
users/auth_sessions 行没有对应用户的删除 API，只能 SQL 清。
"""
import sqlite3
import sys
from pathlib import Path

SQL = """
DELETE FROM conversations WHERE project_id IN (
    SELECT p.id FROM projects p JOIN users u ON p.user_id = u.id
    WHERE u.username LIKE 'smoke\\_%' ESCAPE '\\');
DELETE FROM projects WHERE user_id IN (
    SELECT id FROM users WHERE username LIKE 'smoke\\_%' ESCAPE '\\');
DELETE FROM auth_sessions WHERE user_id IN (
    SELECT id FROM users WHERE username LIKE 'smoke\\_%' ESCAPE '\\');
DELETE FROM users WHERE username LIKE 'smoke\\_%' ESCAPE '\\';
"""


def main() -> None:
    if len(sys.argv) != 2:
        print(f"用法: python3 {sys.argv[0]} <sqlite.db 路径>")
        sys.exit(2)
    db = Path(sys.argv[1])
    if not db.exists():
        print(f"库文件不存在: {db}")
        sys.exit(2)

    con = sqlite3.connect(db)
    try:
        before = con.execute(
            "SELECT COUNT(*) FROM users WHERE username LIKE 'smoke\\_%' ESCAPE '\\'"
        ).fetchone()[0]
        con.executescript(SQL)
        con.commit()
        after = con.execute(
            "SELECT COUNT(*) FROM users WHERE username LIKE 'smoke\\_%' ESCAPE '\\'"
        ).fetchone()[0]
        print(f"smoke_ 用户: 清理前 {before} → 清理后 {after}")
        if after != 0:
            print("警告：仍有残留，检查上面的表结构是否变更")
            sys.exit(1)
        print("清理完成（幂等，可重复执行）")
    finally:
        con.close()


if __name__ == "__main__":
    main()
