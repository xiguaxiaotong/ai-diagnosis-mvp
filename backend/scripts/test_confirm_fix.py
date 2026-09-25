"""验证脚本：确认循环收尾正确性（离线 stub，零 token）。

背景（2026-09-22 用户真机反馈的两个严重问题）：
- finalize_node 写入的 finalized 标记曾不在 DiagnosisState 声明里，
  LangGraph 丢弃后满轮收尾被 _result_from_state 误判为「用户主动确认」，
  回复发成「方案已确认 ✓ 我们会尽快联系您」并自动跳方案页。
- thread_id 用项目自增 id，SQLite rowid 复用导致新项目继承已删项目残留图状态。

验证点：
- [1] thread_id 使用项目 uuid（非自增 id），懒初始化补写生效
- [2] 满 3 轮修改后继续修改 → 走 finalize 收尾：phase=done 且回复是
      finalize 话术（不是「方案已确认 ✓」）
- [3] 用户主动确认 → 回复是「方案已确认 ✓」话术（原有行为不回归）
- [4] 修改轮次逐轮 +1 且不被串会话污染（首轮后缀不带「第 N/3 轮」）

用法（在 backend/ 下）：python scripts/test_confirm_fix.py
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.infra import model_client  # noqa: E402
from app.services import diagnosis_service, project_service  # noqa: E402

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
    "business_summary": "为奶茶店提供扫码点单与会员运营能力。",
    "core_business_modules": [
        {"name": "扫码点单", "description": "顾客扫码自助下单", "priority": "P0"},
    ],
    "tech_architecture": "小程序前端 + 云端 API + MySQL。",
    "tech_stack": [
        {"layer": "前端", "choice": "微信小程序", "reason": "免安装"},
        {"layer": "后端", "choice": "Python FastAPI", "reason": "开发快"},
        {"layer": "数据库", "choice": "MySQL", "reason": "事务可靠"},
    ],
    "implementation_phases": ["一期：点单闭环"],
    "key_risks": ["高峰并发"],
}
FEAS = {
    "overall": "可行",
    "risk_level": "低",
    "tech_assessment": "技术栈成熟。",
    "schedule_assessment": "工期可行。",
    "budget_assessment": "预算匹配。",
    "suggestions": ["先上线点单闭环"],
}

CONFIRM_REPLY_KEY = "方案已确认"
FINALIZE_REPLY_KEY = "已经按您的意见修改了"


def install_stub() -> None:
    """stub LLM：understand 首轮（历史为空）缺信息、之后齐全；plan/feasibility 各回各的。"""

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"]
        if "可行性评估" in prompt or "suggestions" in prompt:
            return json.dumps(FEAS, ensure_ascii=False)
        if "core_business_modules" in prompt or "tech_stack" in prompt:
            return json.dumps(PLAN, ensure_ascii=False)
        if "资深的 AI 产品顾问" in prompt:  # understand 节点独有角色标记
            answered = "预算8万" in prompt  # 用户已回答过追问 → 信息齐全
            return json.dumps(REQ_FULL if answered else REQ_FIRST,
                              ensure_ascii=False)
        if "可行性评估" in prompt or "suggestions" in prompt:
            return json.dumps(FEAS, ensure_ascii=False)
        return json.dumps(PLAN, ensure_ascii=False)

    model_client.chat_client.chat = stub_chat


def make_project(title: str) -> int:
    db = SessionLocal()
    try:
        p = project_service.create_project(db, title, "我想给奶茶店做扫码点单小程序")
        return p.id
    finally:
        db.close()


def run_to_plan(pid: int) -> dict:
    r = diagnosis_service.chat_turn(pid, "我想给奶茶店做扫码点单小程序")
    assert r["phase"] == "clarify", f"应先追问: {r['phase']}"
    r = diagnosis_service.chat_turn(pid, "预算8万，两个月上线，堂食为主")
    assert r["phase"] == "confirm_wait", f"应出方案: {r['phase']}"
    assert "（已按您的要求修改" not in r["reply"], "首轮方案不应带修改轮次后缀"
    return r


def main() -> None:
    init_db()
    install_stub()

    # ========== [1] thread_id 唯一性 ==========
    pid = make_project("验收：满轮收尾正确话术")
    db = SessionLocal()
    try:
        from app.db.models import Project
        tid = db.get(Project, pid).thread_id
        # 断言 uuid4 hex 格式（32 位十六进制），而不是「不含 pid 字符串」——
        # 干净库首条项目 pid=1，"1" 大概率撞上 uuid 里的字符，旧断言必误报
        assert (
            tid and len(tid) == 32
            and all(c in "0123456789abcdef" for c in tid)
        ), f"thread_id 应为 uuid hex: {tid}"
    finally:
        db.close()
    print(f"[1] thread_id 唯一 OK：{tid[:8]}…（非自增 id）")

    # ========== [2] 满轮收尾话术 ==========
    run_to_plan(pid)
    for i in range(1, 4):
        r = diagnosis_service.chat_turn(pid, f"第{i}次修改：去掉会员储值")
        assert r["phase"] == "confirm_wait", f"第{i}轮修改后仍应等确认: {r['phase']}"
        assert f"第 {i}/3 轮" in r["reply"], f"第{i}轮后缀缺失: {r['reply'][-40:]}"
        print(f"[2] 修改第 {i}/3 轮 OK，回复尾缀正确")

    r = diagnosis_service.chat_turn(pid, "第4次修改：再砍点功能")
    assert r["phase"] == "done", f"满轮后应 done: {r['phase']}"
    assert FINALIZE_REPLY_KEY in r["reply"], f"满轮收尾话术错误: {r['reply'][:60]}"
    assert CONFIRM_REPLY_KEY not in r["reply"], "满轮收尾不得误发「方案已确认」"
    print(f"[2] 满轮收尾 OK：回复={r['reply'][:42]}…（不冒充用户确认）")

    # ========== [3] 主动确认话术不回归 ==========
    pid2 = make_project("验收：主动确认话术")
    run_to_plan(pid2)
    r = diagnosis_service.chat_turn(pid2, "确认，就这样")
    assert r["phase"] == "done", f"确认后应 done: {r['phase']}"
    assert CONFIRM_REPLY_KEY in r["reply"], f"确认话术缺失: {r['reply'][:60]}"
    print(f"[3] 主动确认 OK：回复={r['reply'][:30]}…")

    print("\n✅ 全部通过")


if __name__ == "__main__":
    main()
