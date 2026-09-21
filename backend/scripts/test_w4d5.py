"""Week4 Day5 验收：冷启动案例库 + 检索 Top5 相关性 + 方案引用合理性。

验收标准：检索 Top5 相关案例，方案引用合理。
- [1] 5 个典型需求查询：期望案例进入 Top5（领域相关性）
- [2] 负例：不相干查询不返回高分结果（阈值过滤有效）
- [3] 真调 LLM：方案引用检索到的案例（需 DEEPSEEK_API_KEY，缺失则跳过）

前置：先运行 python scripts/seed_cases.py 录入 20 个标准案例。
用法（在 backend/ 目录下运行）：python scripts/test_w4d5.py
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes.generate import generate_node  # noqa: E402
from app.agent.nodes.retrieve import retrieve_node  # noqa: E402
from app.config import DEEPSEEK_API_KEY  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.retrieval.retriever import retrieve_cases  # noqa: E402
from app.services import case_service  # noqa: E402

# 生成方案用的完整需求（generate_node 要求需求已补全）
REQUIREMENTS = {
    "project_title": "金融客服智能问答机器人",
    "business_type": "金融",
    "core_features": ["账单还款常见问题自动回复", "多轮对话", "转人工"],
    "target_users": ["客服团队", "客户"],
    "mentioned_budget": None,
    "mentioned_deadline": None,
    "missing_info": [],
    "summary": "为消费金融公司做客服智能问答机器人",
}

# (用户需求, 期望命中的案例关键词——只需出现在 Top5 任一标题中)
QUERIES = [
    ("想做一个客服机器人，自动回复客户关于账单和还款的常见问题", "客服智能问答"),
    ("公司文档散落各处，想做个内部知识库，员工能问答搜索", "知识库"),
    ("连锁门店每天鲜食订货凭店长经验，报废率太高", "订货"),
    ("仓库靠纸质单据登记，账实不符还经常找不到货", "仓储"),
    ("给建筑工地做工人的实名考勤和安全教育记录管理", "工地"),
]


def main() -> None:
    init_db()

    # 清理历史测试残留的幽灵案例（非 seed_cases 的 20 个标准标题）
    from scripts.seed_cases import CASES  # noqa: E402
    standard_titles = {t for t, _, _ in CASES}
    db = SessionLocal()
    try:
        ghosts = [c.id for c in db.query(case_service.Case).all()
                  if c.title not in standard_titles]
        for cid in ghosts:
            case_service.delete_case(db, cid)
    finally:
        db.close()
    print(f"[0] 案例库就绪（清除 {len(ghosts)} 个测试残留），20 个标准案例\n")

    # ========== 1. Top5 相关性：期望案例进入 Top5 ==========
    gen_state = None
    for query, expect_kw in QUERIES:
        hits = retrieve_cases(query, top_k=5)
        assert hits, f"查询无结果：{query}"
        titles = [h["title"] for h in hits]
        hit_idx = next((i for i, t in enumerate(titles) if expect_kw in t), None)
        assert hit_idx is not None, \
            f"Top5 未命中关键词「{expect_kw}」\n查询: {query}\nTop5: {titles}"
        print(f"[1] ✓ {query[:24]}…")
        for i, h in enumerate(hits, 1):
            mark = " ← 命中" if i - 1 == hit_idx else ""
            print(f"    {i}. {h['title']}（{h['industry']}，score={h['score']:.2f}）{mark}")

        # 保留第一个查询的检索结果给第 3 步方案生成用
        if gen_state is None:
            gen_state = {"raw_idea": query, "requirements": REQUIREMENTS,
                         "retrieved_cases": hits}

    # ========== 2. 负例：不相干查询被阈值过滤 ==========
    off = retrieve_cases("宠物殡葬服务预约平台")
    assert not off or off[0]["score"] < 0.5, f"不相干查询仍返回高分: {off}"
    print(f"[2] 负例 OK：不相干查询返回 {len(off)} 条"
          f"{f'，top score={off[0]['score']:.2f} < 0.5' if off else '（空）'}\n")

    # ========== 3. 方案引用合理性：真调 LLM（需 key） ==========
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("[3] 跳过（未配置 DEEPSEEK_API_KEY），其余验收已通过")
    else:
        delta = generate_node(gen_state)
        assert "plan" in delta, delta.get("error")
        plan_text = json.dumps(delta["plan"], ensure_ascii=False)
        cited = [h["title"] for h in gen_state["retrieved_cases"] if h["title"] in plan_text]
        assert cited, f"方案未引用任何检索案例:\n{plan_text[:600]}"
        print(f"[3] 方案引用 OK：引用了 {len(cited)} 个案例：{cited}")

    print("\n" + "=" * 54)
    print("✅ Week4 Day5 验收通过（冷启动 20 案例 + Top5 相关性 + 方案引用）")
    print("=" * 54)


if __name__ == "__main__":
    main()
