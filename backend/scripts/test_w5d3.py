# -*- coding: utf-8 -*-
"""Week5 Day3 验收：方案展示页——业务/技术方案、预算明细、可行性、确认/修改按钮。

验收标准：方案排版清晰，预算表格可读（数据完整即可渲染清晰）。
- [1] 产出一个带完整方案的真项目（进程内 stub LLM 驱动图，确定性、零 token）
- [2] GET /api/project/{id}：plan / budget / feasibility / final_output 齐全
- [3] 前端 /project/{id} 页面可渲染
- [4] 「需要修改」按钮通路：revise → 方案重出（revision_round=1）
- [5] 「确认方案」按钮通路：confirm → status=confirmed

用法（在 backend/ 下，后端与前端已启动）：python scripts/test_w5d3.py
"""

import json
import sys
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command  # noqa: E402,F401  (备用)

from app.agent.graph import build_graph  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.infra import model_client  # noqa: E402
from app.services import diagnosis_service, project_service  # noqa: E402

BASE = "http://localhost:8000"
FRONT = "http://localhost:3000"

REQ_FIRST = {
    "project_title": "奶茶店点单小程序",
    "business_type": "餐饮",
    "core_features": ["扫码点单", "会员储值"],
    "target_users": ["顾客", "店员"],
    "mentioned_budget": None,
    "mentioned_deadline": None,
    "missing_info": ["预算范围？", "期望上线时间？"],
    "summary": "为奶茶店做扫码点单小程序，含会员储值。",
}
REQ_FULL = dict(REQ_FIRST, missing_info=[])
PLAN = {
    "project_name": "奶茶店点单小程序",
    "business_summary": "为奶茶店提供扫码点单与会员运营能力，提升点单效率与复购。",
    "core_business_modules": [
        {"name": "扫码点单", "description": "顾客扫码自助下单", "priority": "P0"},
        {"name": "会员储值", "description": "储值余额与充值", "priority": "P1"},
    ],
    "tech_architecture": "小程序前端 + 云端 API + MySQL。",
    "tech_stack": [
        {"layer": "前端", "choice": "微信小程序", "reason": "免安装"},
        {"layer": "后端", "choice": "Python FastAPI", "reason": "开发快"},
        {"layer": "数据库", "choice": "MySQL", "reason": "事务可靠"},
        {"layer": "部署", "choice": "云服务器", "reason": "运维简单"},
    ],
    "implementation_phases": ["一期：点单闭环", "二期：会员功能"],
    "key_risks": ["高峰并发", "支付合规"],
}
FEAS = {
    "overall": "可行",
    "risk_level": "低",
    "tech_assessment": "技术栈成熟，团队可驾驭。",
    "schedule_assessment": "两个月工期偏紧但可行。",
    "budget_assessment": "预算与测算区间匹配。",
    "suggestions": ["先上线点单闭环", "会员功能二期迭代"],
}


def http_json(method: str, url: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        p = project_service.create_project(db, "Day3验收：奶茶店点单",
                                           "我想给奶茶店做扫码点单小程序")
        pid = p.id
    finally:
        db.close()

    # stub：第 1 次 understand 缺信息（追问），之后齐全；generate/feasibility 各回各的 JSON
    calls = {"understand": 0}
    original = model_client.chat_client.chat

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"]
        if "可行性评估" in prompt or "suggestions" in prompt:
            return json.dumps(FEAS, ensure_ascii=False)
        if "core_business_modules" in prompt or "tech_stack" in prompt:
            return json.dumps(PLAN, ensure_ascii=False)
        calls["understand"] += 1
        req = REQ_FIRST if calls["understand"] == 1 else REQ_FULL
        return json.dumps(req, ensure_ascii=False)

    # 换全新编译的图：隔离 MemorySaver 里历史测试残留的 thread 状态
    # （被删项目复用自增 id 会撞 thread_id，chat_turn 会误判 resume）
    original_graph = diagnosis_service.diagnosis_graph
    diagnosis_service.diagnosis_graph = build_graph()
    model_client.chat_client.chat = stub_chat

    try:
        # ========== [1] 产出完整方案项目 ==========
        r1 = diagnosis_service.chat_turn(pid, "我想给奶茶店做扫码点单小程序")
        assert r1["phase"] == "clarify", f"第一轮应追问: {r1['phase']}"
        r2 = diagnosis_service.chat_turn(pid, "预算8万，两个月上线，堂食为主")
        assert r2["phase"] == "confirm_wait", f"第二轮应出方案: {r2['phase']}"
        assert r2["solution"] and r2["solution"]["budget"]
        print(f"[1] 方案产出 OK：项目 {pid} 停在 wait_confirmation，"
              f"预算 ¥{r2['solution']['budget']['total_min']}~"
              f"¥{r2['solution']['budget']['total_max']}")

        # ========== [2] API 返回结构完整 ==========
        d = http_json("GET", f"{BASE}/api/project/{pid}")
        assert d["solution"]["plan"]["core_business_modules"], "缺业务模块"
        assert d["solution"]["plan"]["tech_stack"], "缺技术选型"
        assert d["solution"]["budget"]["line_items"], "缺预算明细"
        assert d["solution"]["feasibility"], "缺可行性评估"
        assert d["solution"]["final_output"], "缺方案摘要"
        assert d["status"] == "plan_generated"
        print(f"[2] 方案数据 OK：模块 {len(d['solution']['plan']['core_business_modules'])} 个、"
              f"选型 {len(d['solution']['plan']['tech_stack'])} 层、"
              f"预算明细 {len(d['solution']['budget']['line_items'])} 项、可行性 {d['solution']['feasibility']['overall']}")

        # ========== [3] 前端页面可渲染 ==========
        html = urllib.request.urlopen(f"{FRONT}/project/{pid}").read().decode("utf-8")
        assert "Next.js" in html or "next" in html  # 正常渲染出的页面壳
        print("[3] 前端页面 OK：/project/{id} 渲染 200（方案排版与预算表格见浏览器）")

        # ========== [4] 修改按钮通路 ==========
        r3 = diagnosis_service.chat_turn(pid, "预算砍到5万以内，去掉会员储值")
        assert r3["phase"] == "confirm_wait" and r3["revision_round"] == 1, \
            f"修改后应重出方案: phase={r3['phase']} round={r3['revision_round']}"
        assert "修改" in r3["reply"] or "调整" in r3["reply"] or "第 1" in r3["reply"]
        print("[4] 需要修改 OK：方案重出，revision_round=1")

        # ========== [5] 确认按钮通路 ==========
        r4 = diagnosis_service.chat_turn(pid, "确认，就这样")
        assert r4["phase"] == "done"
        d2 = http_json("GET", f"{BASE}/api/project/{pid}")
        assert d2["status"] == "confirmed", f"status={d2['status']}"
        print("[5] 确认方案 OK：status=confirmed，方案锁定")

        print("\n✅ Week5 Day3 验收通过（方案展示页数据完整 + 确认/修改通路）")
    finally:
        model_client.chat_client.chat = original
        diagnosis_service.diagnosis_graph = original_graph
        project_service.delete_project(SessionLocal(), pid)
        print(f"\n[cleanup] 测试项目 {pid} 已删除")


if __name__ == "__main__":
    main()
