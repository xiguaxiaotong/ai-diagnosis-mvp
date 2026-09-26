"""W7 Day8 bugfix：一次性清理主库存量悬空外键引用。

背景（lead #2 转工单 500 根因）：
- projects 删除路径历史上存在 FK PRAGMA 关闭期（database.py 的
  PRAGMA foreign_keys=ON 是后加的），期间删项目留下了
  leads.project_id → 已删项目 的悬空引用
- foreign_keys=ON 后插入 worksheets 引用悬空 id 直接 IntegrityError → 500

规则：所有指向 projects / users / leads 的可空引用列，发现悬空一律置 NULL。
（schema 设计本来就是 SET NULL，这里把没被 SET 到的存量补齐）

幂等：可重复跑；没有悬空引用时改 0 行。
用法（在 backend/ 下）：
    python scripts/cleanup_dangling_refs.py            # 清主库
    SQLITE_PATH=... python scripts/cleanup_dangling_refs.py  # 清指定库（env 覆盖）
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db.database import SessionLocal, init_db  # noqa: E402

# (表, 引用列, 被引用表) —— 只清可空引用列（NOT NULL 列清了会炸插入）
DANGLING_RULES = [
    ("leads", "project_id", "projects"),
    ("leads", "user_id", "users"),
    ("worksheets", "lead_id", "leads"),
    ("worksheets", "project_id", "projects"),
    ("worksheets", "user_id", "users"),
]


def main() -> int:
    init_db()
    db = SessionLocal()
    total = 0
    try:
        for table, col, ref in DANGLING_RULES:
            sql = text(f"""
                UPDATE {table} SET {col} = NULL
                WHERE {col} IS NOT NULL
                  AND {col} NOT IN (SELECT id FROM {ref})
            """)
            result = db.execute(sql)
            n = result.rowcount
            total += n
            print(f"  {table}.{col} → {ref}: 清理 {n} 行悬空引用")
        db.commit()
        print(f"\n完成：共清理 {total} 行。幂等，可重复跑。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
