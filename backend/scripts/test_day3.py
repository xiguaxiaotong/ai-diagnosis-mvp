"""Day3 测试脚本：P10 数据层验证（SQLite 建表 + 项目 CRUD）。

用法（在 backend/ 目录下运行）：
    python scripts/test_day3.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import SQLITE_PATH
from app.db.database import SessionLocal, init_db
from app.db.models import Conversation, Case, Project, User
from app.services import project_service


def main() -> None:
    # 1. 建表
    init_db()
    assert SQLITE_PATH.exists(), "sqlite.db 未生成"
    print(f"✅ 建表成功: {SQLITE_PATH}")

    db = SessionLocal()
    try:
        # 2. 建用户
        user = User(name="测试用户")
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ 创建用户: id={user.id}, name={user.name}")

        # 3. 项目 CRUD
        # Create
        p = project_service.create_project(
            db, title="餐饮扫码点单小程序", raw_idea="我想给餐饮店做一个扫码点单小程序",
            user_id=user.id,
        )
        print(f"✅ Create 项目: id={p.id}, title={p.title}, status={p.status}")

        # Read
        got = project_service.get_project(db, p.id)
        assert got is not None and got.title == "餐饮扫码点单小程序"
        print(f"✅ Read 项目: id={got.id}, raw_idea={got.raw_idea[:20]}...")

        # Update（方案确认后更新状态与预算区间）
        updated = project_service.update_project(
            db, p.id,
            status=Project.STATUS_PLAN_GENERATED,
            plan='{"summary": "小程序 + 后台管理系统"}',
            budget_min=25000, budget_max=35000,
        )
        assert updated.status == Project.STATUS_PLAN_GENERATED
        assert updated.budget_min == 25000 and updated.budget_max == 35000
        print(f"✅ Update 项目: status={updated.status}, budget=[{updated.budget_min}, {updated.budget_max}]")

        # List
        project_service.create_project(db, title="CRM 客户管理系统")
        all_projects = project_service.list_projects(db)
        assert len(all_projects) == 2
        print(f"✅ List 项目: 共 {len(all_projects)} 条, 最新: {all_projects[0].title}")

        # 4. 对话消息
        project_service.add_message(db, p.id, "user", "我想做一个点单小程序")
        project_service.add_message(db, p.id, "assistant", "好的，请问日均订单量大概多少？")
        msgs = project_service.get_messages(db, p.id)
        assert len(msgs) == 2 and msgs[0].role == "user"
        print(f"✅ 对话消息: {len(msgs)} 条 ({msgs[0].role} → {msgs[1].role})")

        # 5. 案例表可写
        case = Case(title="某连锁餐饮点单系统", industry="餐饮", summary="脱敏摘要示例")
        db.add(case)
        db.commit()
        db.refresh(case)
        print(f"✅ 案例入库: id={case.id}, industry={case.industry}")

        # 6. Delete（验证级联删除对话）
        ok = project_service.delete_project(db, p.id)
        assert ok and project_service.get_project(db, p.id) is None
        left = db.query(Conversation).filter(Conversation.project_id == p.id).count()
        assert left == 0, "对话消息未级联删除"
        print("✅ Delete 项目: 对话消息已级联删除")

        # 清理测试用户，保持库干净
        db.delete(user)
        db.commit()

    finally:
        db.close()

    print("\n" + "=" * 50)
    print("✅ Day3 数据层全部测试通过")


if __name__ == "__main__":
    main()
