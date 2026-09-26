"""W8 Day2/3 验收：会话级成本汇总 GET /api/admin/traces + 回放详情接口。

⚠️ 测试隔离：env 覆盖五路径（四路径 + TRACE_PATH），独立临时库，不碰主库、
不碰主 trace 文件。trace 数据直接手写 JSONL（不跑图，纯接口/聚合逻辑验证）。

验证点：
- [1] trace 文件不存在 → 200 + 空列表 + 全 0 totals，不报错
- [2] 空 trace 文件 → 同上
- [3] 单会话聚合：node/llm 计数、token 汇总、起止时间、总耗时口径正确
- [4] 多会话聚合：按会话隔离互不串；最后活动倒序
- [5] 成本换算：prompt/1M×单价 + completion/1M×单价（用 config 实际单价算期望值，
      4 位小数）
- [6] limit：截断生效；totals 不受 limit 影响（全量合计）；上限 200 封顶
- [7] 坏行/无 thread_id 行跳过，不炸接口
- [8] 权限：非 admin 403、未登录 401/403
- [9] 详情接口 GET /api/admin/trace/{tid} 返回该会话时间序记录（回放页数据源）

用法（在 backend/ 下，零 LLM token）：
    python scripts/test_w8d23_traces.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# ---------- 测试隔离：env 必须在 import app 之前设置 ----------
_TMP = Path(tempfile.mkdtemp(prefix="w8d23_traces_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["TRACE_PATH"] = str(_TMP / "trace.jsonl")
os.environ["ADMIN_USER_IDS"] = "1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import (  # noqa: E402
    DEEPSEEK_PRICE_COMPLETION,
    DEEPSEEK_PRICE_PROMPT,
    TRACE_PATH,
)
from app.db.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def write_lines(lines: list[dict]):
    with open(TRACE_PATH, "w", encoding="utf-8") as f:
        for rec in lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    init_db()
    client = TestClient(app)

    # admin / 普通用户
    r = client.post("/api/auth/register", json={
        "username": "t_admin", "password": "tpass123"})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"username": "t_admin", "password": "tpass123"})
    admin_h = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post("/api/auth/register", json={
        "username": "t_user", "password": "tpass456"})
    r = client.post("/api/auth/login", json={"username": "t_user", "password": "tpass456"})
    user_h = {"Authorization": "Bearer " + r.json()["token"]}

    def expect_cost(p: int, c: int) -> float:
        return round(p / 1_000_000 * DEEPSEEK_PRICE_PROMPT
                     + c / 1_000_000 * DEEPSEEK_PRICE_COMPLETION, 4)

    # ---- [1] 文件不存在 ----
    print("[1] trace 文件不存在")
    r = client.get("/api/admin/traces", headers=admin_h)
    check("200 不报错", r.status_code == 200, r.text[:200])
    s = r.json()
    check("空列表 + 全 0 totals", s["items"] == [] and s["totals"]["sessions"] == 0
          and s["totals"]["cost_cny"] == 0, str(s["totals"]))
    check("totals 回显单价", s["totals"]["price"] == {
        "prompt_per_m": DEEPSEEK_PRICE_PROMPT,
        "completion_per_m": DEEPSEEK_PRICE_COMPLETION}, str(s["totals"]["price"]))

    # ---- [2] 空文件 ----
    print("\n[2] 空 trace 文件")
    TRACE_PATH.write_text("", encoding="utf-8")
    r = client.get("/api/admin/traces", headers=admin_h)
    check("空文件 200 + 空 items", r.status_code == 200
          and r.json()["items"] == [], r.text[:200])

    # ---- [3] 单会话聚合 ----
    print("\n[3] 单会话聚合")
    # A 会话：3 node（100+200+50ms）+ 2 llm（p=1000,c=200 / p=500,c=300）
    A = "project-aaa111"
    write_lines([
        {"type": "node", "thread_id": A, "node": "understand", "duration_ms": 100,
         "ts": "2026-09-26T01:00:00+00:00"},
        {"type": "llm", "thread_id": A, "model": "deepseek-chat", "duration_ms": 95,
         "prompt_tokens": 1000, "completion_tokens": 200, "ts": "2026-09-26T01:00:01+00:00"},
        {"type": "node", "thread_id": A, "node": "generate", "duration_ms": 200,
         "ts": "2026-09-26T01:00:02+00:00"},
        {"type": "llm", "thread_id": A, "model": "deepseek-chat", "duration_ms": 190,
         "prompt_tokens": 500, "completion_tokens": 300, "ts": "2026-09-26T01:00:03+00:00"},
        {"type": "node", "thread_id": A, "node": "output", "duration_ms": 50,
         "ts": "2026-09-26T01:00:04+00:00"},
    ])
    r = client.get("/api/admin/traces", headers=admin_h)
    s = r.json()
    check("1 会话", s["totals"]["sessions"] == 1, str(s["totals"]))
    row = s["items"][0]
    check("node_count=3", row["node_count"] == 3, str(row))
    check("llm_count=2", row["llm_count"] == 2, str(row))
    check("prompt=1500 completion=500", row["prompt_tokens"] == 1500
          and row["completion_tokens"] == 500, str(row))
    check("总耗时=350ms（只加 node，不双计 llm）", row["total_duration_ms"] == 350, str(row))
    check("started/last 正确", row["started_at"] == "2026-09-26T01:00:00+00:00"
          and row["last_active_at"] == "2026-09-26T01:00:04+00:00", str(row))
    check(f"成本 {expect_cost(1500, 500)}", row["cost_cny"] == expect_cost(1500, 500),
          f"实际 {row['cost_cny']}")
    check("totals 成本与行一致", s["totals"]["cost_cny"] == row["cost_cny"])
    check("totals tokens 汇总一致",
          s["totals"]["prompt_tokens"] == 1500 and s["totals"]["llm_count"] == 2)

    # ---- [4] 多会话聚合 + 倒序 ----
    print("\n[4] 多会话聚合（B 最后活动更晚 → 排前）")
    B = "project-bbb222"
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "node", "thread_id": B, "node": "understand",
                            "duration_ms": 10, "ts": "2026-09-26T02:00:00+00:00"}) + "\n")
        f.write(json.dumps({"type": "llm", "thread_id": B, "model": "deepseek-chat",
                            "duration_ms": 9, "prompt_tokens": 100, "completion_tokens": 10,
                            "ts": "2026-09-26T02:00:01+00:00"}) + "\n")
    r = client.get("/api/admin/traces", headers=admin_h)
    s = r.json()
    check("2 会话且会话隔离", s["totals"]["sessions"] == 2
          and s["totals"]["prompt_tokens"] == 1600, str(s["totals"]))
    check("最后活动倒序（B 在前）", [x["thread_id"] for x in s["items"]] == [B, A],
          str([x["thread_id"] for x in s["items"]]))
    rowB = s["items"][0]
    check("B 行聚合正确", rowB["node_count"] == 1 and rowB["llm_count"] == 1
          and rowB["prompt_tokens"] == 100 and rowB["total_duration_ms"] == 10, str(rowB))
    check("B 成本", rowB["cost_cny"] == expect_cost(100, 10), str(rowB["cost_cny"]))
    check("totals 成本 = 两行和",
          s["totals"]["cost_cny"] == round(rowB["cost_cny"] + expect_cost(1500, 500), 4),
          f"{s['totals']['cost_cny']}")

    # ---- [7] 坏行跳过 ----
    print("\n[7] 坏行 / 无 thread_id 行跳过")
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write("{坏 json\n")
        f.write(json.dumps({"type": "node", "node": "孤儿", "duration_ms": 99,
                            "ts": "2026-09-26T03:00:00+00:00"}) + "\n")
    r = client.get("/api/admin/traces", headers=admin_h)
    check("坏行不影响（仍 2 会话）", r.json()["totals"]["sessions"] == 2,
          str(r.json()["totals"]))

    # ---- [6] limit ----
    print("\n[6] limit 截断 / 上限 / totals 不受影响")
    r = client.get("/api/admin/traces?limit=1", headers=admin_h)
    s = r.json()
    check("limit=1 返回 1 行", len(s["items"]) == 1, str(len(s["items"])))
    check("totals 仍全量（2 会话）", s["totals"]["sessions"] == 2, str(s["totals"]))
    r = client.get("/api/admin/traces?limit=9999", headers=admin_h)
    check("limit 超上限封 200（返回不超 2）", r.json()["limit"] == 200
          and len(r.json()["items"]) == 2, str(r.json()["limit"]))

    # ---- [9] 详情接口（回放页数据源） ----
    print("\n[9] 详情接口")
    r = client.get(f"/api/admin/trace/{A}", headers=admin_h)
    check("GET /api/admin/trace/{tid} 200", r.status_code == 200, r.text[:200])
    d = r.json()
    check("返回该会话 5 条时间序", d["count"] == 5
          and d["items"][0]["ts"] <= d["items"][-1]["ts"], str(d["count"]))
    r = client.get(f"/api/admin/trace/{A.replace('project-', '')}", headers=admin_h)
    check("裸 uuid 等价", r.json()["count"] == 5)

    # ---- [8] 权限 ----
    print("\n[8] 越权拦截")
    r = client.get("/api/admin/traces", headers=user_h)
    check("非 admin 403", r.status_code == 403, f"实际 {r.status_code}")
    r = client.get("/api/admin/traces")
    check("未登录 401/403", r.status_code in (401, 403), f"实际 {r.status_code}")

    print(f"\n{'='*50}\n结果：{PASS} 通过 / {FAIL} 失败 · 测试库：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
