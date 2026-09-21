"""Week4 Day4 验收：真实案例检索接入诊断图（retriever + retrieve 节点 + Prompt 注入）。

验收标准：AI 方案中能引用检索到的真实案例。
- [1][2][4] 离线：种子案例入库 → retriever 命中 → Prompt 含案例名
- [3] 需要 DEEPSEEK_API_KEY：generate_node 真调 LLM，方案文本引用案例名
- 结束时清理种子案例（DB + Chroma + 文件三处）

用法（在 backend/ 目录下运行）：
    python scripts/test_w4d4.py
"""

import json
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes.retrieve import retrieve_node  # noqa: E402
from app.agent.prompt_loader import render  # noqa: E402
from app.config import DEEPSEEK_API_KEY  # noqa: E402
from app.db.database import init_db  # noqa: E402
from app.retrieval.retriever import retrieve_cases  # noqa: E402
from app.services import case_service  # noqa: E402

# 独特案例名：断言它能从检索一路穿透到 LLM 方案文本里
CASE_TITLE = "青苗幼儿园放学接送小程序案例"
CASE_BODY = (
    "青苗幼儿园放学接送小程序项目复盘。家长在手机端查看放学时间与排队情况，"
    "老师扫码核销接送码确认孩子被接走，未到家长自动短信提醒。"
    "核心模块包括接送码生成与核销、家长与班级管理、放学排队大屏、"
    "请假与代接审批、消息通知中心。"
    "采用微信小程序家长端加教师端，后端 Python FastAPI 与 MySQL，"
    "短信用阿里云服务，部署在单台云服务器。"
    "项目上线两个月覆盖六个班级，接送平均等待时长缩短一半。"
) * 5  # >500 字，强制多 chunk

REQUIREMENTS = {
    "project_title": "幼儿园接送提醒小程序",
    "business_type": "教育",
    "core_features": ["家长查看放学时间", "接送码扫码核销", "未到园自动提醒家长"],
    "target_users": ["家长", "老师"],
    "mentioned_budget": None,
    "mentioned_deadline": None,
    "missing_info": [],
    "summary": "为幼儿园做接送核销与提醒小程序",
}


def seed_case() -> int:
    from app.db.database import SessionLocal

    tmp = Path(tempfile.mkdtemp(prefix="w4d4_"))
    path = tmp / "青苗幼儿园接送案例.md"
    path.write_text("# 案例复盘\n\n" + CASE_BODY, encoding="utf-8")
    # 注意：SessionLocal() 内联传参会被 GC，实例失绑后取 id 报
    # DetachedInstanceError —— 必须显式持有 session 引用
    db = SessionLocal()
    try:
        case = case_service.create_case_from_file(db, path, CASE_TITLE,
                                                  industry="教育")
        return case.id
    finally:
        db.close()


def main() -> None:
    init_db()
    import app.db.database as dbm

    cid = seed_case()
    print(f"[0] 种子案例入库：id={cid} title={CASE_TITLE!r}")

    try:
        # ========== 1. retriever：语义检索命中种子案例 ==========
        hits = retrieve_cases("幼儿园放学接孩子 扫码核销 家长提醒")
        assert hits, "检索无结果"
        assert hits[0]["title"] == CASE_TITLE, hits[0]
        assert hits[0]["industry"] == "教育" and hits[0]["score"] >= 0.35, hits[0]
        print(f"[1] retriever OK：top1 命中种子案例，score={hits[0]['score']}")

        # ========== 2. retrieve 节点：状态写入 retrieved_cases ==========
        state = {"raw_idea": "想给幼儿园做个放学接送提醒的小程序",
                 "requirements": REQUIREMENTS}
        delta = retrieve_node(state)
        cases = delta["retrieved_cases"]
        assert cases and cases[0]["title"] == CASE_TITLE, cases
        print(f"[2] retrieve 节点 OK：写入 {len(cases)} 个案例到诊断状态")

        # ========== 3. Prompt 注入：案例名出现在方案生成 Prompt 中 ==========
        lines = [f"- 《{c['title']}》{c['summary']}（相似度 {c['score']:.2f}）"
                 for c in cases]
        cases_section = "\n## 相似历史案例（真实项目复盘，供参考）\n\n" + "\n".join(lines) + "\n"
        prompt = render("generate",
                        requirements_json=json.dumps(REQUIREMENTS, ensure_ascii=False),
                        revision_feedback="", similar_cases=cases_section)
        assert CASE_TITLE in prompt, "案例名未注入 Prompt"
        print(f"[3] Prompt 注入 OK：案例名已进入方案生成 Prompt（{len(prompt)} 字）")

        # ========== 4. generate_node 真调 LLM：方案引用案例名（需 key） ==========
        if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
            print(f"[4] 跳过（未配置 DEEPSEEK_API_KEY），其余验收已通过")
        else:
            from app.agent.nodes.generate import generate_node

            gstate = {**state, "retrieved_cases": cases}
            delta = generate_node(gstate)
            assert "plan" in delta, delta.get("error")
            plan_text = json.dumps(delta["plan"], ensure_ascii=False)
            assert CASE_TITLE in plan_text, f"方案未引用案例名:\n{plan_text[:600]}"
            print(f"[4] 方案引用 OK：LLM 方案中引用了《{CASE_TITLE}》"
                  f"（{len(delta['plan']['core_business_modules'])} 模块）")
    finally:
        # 清理种子案例（DB + Chroma + 文件）
        case_service.delete_case(dbm.SessionLocal(), cid)
        print(f"[cleanup] 种子案例已删除")

    print("\n" + "=" * 54)
    print("✅ Week4 Day4 验收通过（检索 → 状态 → Prompt → 方案引用真实案例）")
    print("=" * 54)


if __name__ == "__main__":
    main()
