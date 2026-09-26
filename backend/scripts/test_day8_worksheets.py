"""W7 Day8 验收：工单模块（lead 转工单 + 5 态状态机 + 时间线 + 列表）。

⚠️ 测试隔离：env 覆盖四路径（Day7 基础设施），独立临时库，不碰主库。

验证点：
- [1] 转工单字段映射：name→customer_name、phone→contact、
      project.raw_idea→requirement_summary、project.thread_id→thread_id
- [2] 幂等：重复转不重复建（created=False，同一张工单）
- [3] 转入写 system 时间线
- [4] 状态机合法流转：to_confirm→communicating→quoted→won 全链
      （每次流转强制写 status_change 时间线）
- [5] 非法流转 400：跳级 / 倒流 / 终态再动 / 未知状态
- [6] 列表：状态筛选 + updated_at 倒序
- [7] 权限：非 admin 读写 403；未登录 401/403
- [8] 404：不存在的 lead / 工单
- [9] 无 project 的 lead 转工单：requirement_summary 回退 lead.note、thread_id 空
- [10] bugfix 回归：悬空 project_id（项目已删）转工单不 500、project_id 置 None；
      closed lead 转工单 409 + 提示文案；删除项目同步清 leads.project_id

用法（在 backend/ 下，零 LLM token）：
    python scripts/test_day8_worksheets.py
"""
import os
import sys
import tempfile
from pathlib import Path

# ---------- 测试隔离：env 必须在 import app 之前设置 ----------
_TMP = Path(tempfile.mkdtemp(prefix="day8_test_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["ADMIN_USER_IDS"] = "1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import Lead, Project  # noqa: E402
from app.main import app  # noqa: E402
from app.services import project_service  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def seed(uid: int) -> dict:
    """灌 3 个项目 + 3 条 lead（lead3 无 project，验证回退）。返回 {name: (lead_id, project_id)}。"""
    db = SessionLocal()
    out = {}
    try:
        specs = [
            # (name, phone, company, note, raw_idea, with_project)
            ("张三", "13800000001", "三味书屋", "想要门店点单系统",
             "我想做一个连锁奶茶店的扫码点单小程序，要会员储值和库存同步", True),
            ("李四", "13900000002", "四叶草科技", "想给团队上知识库",
             "搭一个企业内部知识库问答，接入我们现有的 ERP 系统查库存", True),
            ("王五", "13700000003", None, "客户只留了电话，说想做客服机器人", None, False),
        ]
        for name, phone, company, note, raw_idea, with_p in specs:
            pid = None
            tid = None
            if with_p:
                p = Project(user_id=uid, title=f"项目-{name}",
                            raw_idea=raw_idea, thread_id=f"day8-thread-{name}")
                db.add(p)
                db.flush()
                pid, tid = p.id, p.thread_id
            lead = Lead(project_id=pid, user_id=uid, name=name, phone=phone,
                        company=company, note=note)
            db.add(lead)
            db.flush()
            out[name] = (lead.id, pid, tid)
        db.commit()
    finally:
        db.close()
    return out


def main():
    init_db()  # 独立库跑全部迁移（0001→0009）

    client = TestClient(app)

    # admin（id=1 白名单内）+ 普通用户
    r = client.post("/api/auth/register", json={
        "username": "day8_admin", "password": "day8pass123"})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={
        "username": "day8_admin", "password": "day8pass123"})
    assert r.status_code == 200, r.text
    admin_h = {"Authorization": "Bearer " + r.json()["token"]}
    admin_uid = 1

    r = client.post("/api/auth/register", json={
        "username": "day8_user", "password": "day8pass456"})
    r = client.post("/api/auth/login", json={
        "username": "day8_user", "password": "day8pass456"})
    user_h = {"Authorization": "Bearer " + r.json()["token"]}

    leads = seed(admin_uid)
    print(f"\n[seed] 独立库灌入 3 条 lead，库目录 {_TMP}\n")

    # ---- [1] 转工单 + 字段映射 ----
    print("[1] 转工单（字段映射）")
    lead_id, project_id, thread_id = leads["张三"]
    r = client.post(f"/api/admin/leads/{lead_id}/worksheet", headers=admin_h)
    check("POST 转工单 200", r.status_code == 200, r.text[:300])
    body = r.json()
    ws1 = body["worksheet"]
    check("created=true", body.get("created") is True)
    check("customer_name ← lead.name", ws1["customer_name"] == "张三", ws1["customer_name"])
    check("contact ← lead.phone", ws1["contact"] == "13800000001", ws1["contact"])
    check("company ← lead.company", ws1["company"] == "三味书屋")
    check("requirement_summary ← project.raw_idea",
          "扫码点单" in (ws1["requirement_summary"] or ""), str(ws1["requirement_summary"])[:80])
    check("thread_id ← project.thread_id", ws1["thread_id"] == thread_id, f'{ws1["thread_id"]} vs {thread_id}')
    check("初始状态 to_confirm", ws1["status"] == "to_confirm", ws1["status"])
    check("lead 详情带 worksheet_id", client.get(
        f"/api/admin/leads/{lead_id}", headers=admin_h).json().get("worksheet_id") == ws1["id"])

    # ---- [3] 转入写 system 时间线 ----
    r = client.get(f"/api/admin/worksheets/{ws1['id']}", headers=admin_h)
    ws1_notes = r.json()["notes"]
    check("转入写 system 时间线", len(ws1_notes) == 1
          and ws1_notes[0]["note_type"] == "system"
          and f"Lead #{lead_id}" in ws1_notes[0]["content"], str(ws1_notes))
    check("详情返回 next_statuses=[communicating, closed]",
          set(r.json()["next_statuses"]) == {"communicating", "closed"},
          str(r.json()["next_statuses"]))

    # ---- [2] 幂等 ----
    print("\n[2] 幂等（重复转不重复建）")
    r = client.post(f"/api/admin/leads/{lead_id}/worksheet", headers=admin_h)
    check("重复转 created=false", r.status_code == 200
          and r.json()["created"] is False and r.json()["worksheet"]["id"] == ws1["id"],
          r.text[:200])
    n = client.get("/api/admin/worksheets", headers=admin_h).json()["items"]
    check("库里仍只有 1 张工单", len(n) == 1, f"实际 {len(n)}")

    # ---- [5] 非法流转（先在 ws1 上测跳级/倒流/终态，再走合法链）----
    print("\n[5] 非法流转 400")
    wid = ws1["id"]
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "quoted"}, headers=admin_h)
    check("跳级 to_confirm→quoted 400", r.status_code == 400 and "非法流转" in r.json()["detail"],
          f"{r.status_code} {r.text[:120]}")
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "won"}, headers=admin_h)
    check("跳级 to_confirm→won 400", r.status_code == 400)
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "unknown"}, headers=admin_h)
    check("未知状态 422（validator）", r.status_code == 422, f"实际 {r.status_code}")
    # 合法走一步，再测倒流
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "communicating"}, headers=admin_h)
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "to_confirm"}, headers=admin_h)
    check("倒流 communicating→to_confirm 400", r.status_code == 400)
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "won"}, headers=admin_h)
    check("跳级 communicating→won 400", r.status_code == 400)
    # 关闭后终态
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "closed"}, headers=admin_h)
    check("communicating→closed 200（非终态可关闭）", r.status_code == 200, r.text[:120])
    r = client.patch(f"/api/admin/worksheets/{wid}", json={"status": "to_confirm"}, headers=admin_h)
    check("终态 closed→to_confirm 400", r.status_code == 400)
    r = client.get(f"/api/admin/worksheets/{wid}", headers=admin_h)
    check("终态 next_statuses 为空", r.json()["next_statuses"] == [] and
          r.json()["worksheet"]["status"] == "closed")

    # ---- [4] 合法全链（ws2：张三已关，用李四）----
    print("\n[4] 合法流转全链 to_confirm→communicating→quoted→won")
    lead2, project2, _ = leads["李四"]
    r = client.post(f"/api/admin/leads/{lead2}/worksheet", headers=admin_h)
    ws2 = r.json()["worksheet"]["id"]
    steps = ["communicating", "quoted", "won"]
    before_notes = len(client.get(f"/api/admin/worksheets/{ws2}", headers=admin_h).json()["notes"])
    for s in steps:
        r = client.patch(f"/api/admin/worksheets/{ws2}", json={"status": s}, headers=admin_h)
        check(f"→ {s} 200", r.status_code == 200, r.text[:150])
        check("  返回新 next_statuses", "next_statuses" in r.json())
    r = client.patch(f"/api/admin/worksheets/{ws2}", json={"status": "communicating"}, headers=admin_h)
    check("终态 won→communicating 400", r.status_code == 400)
    # 时间线：3 次流转 = 3 条 status_change
    notes2 = client.get(f"/api/admin/worksheets/{ws2}", headers=admin_h).json()["notes"]
    sc = [n for n in notes2 if n["note_type"] == "status_change"]
    check("每次流转写时间线（3 条 status_change）", len(sc) == 3, f"实际 {len(sc)}")
    check("时间线含流转文案", all("→" in n["content"] for n in sc), str(sc)[:120])
    check("转入 system + 流转 status_change 共 4 条", len(notes2) == before_notes + 3)

    # ---- [6] 列表：筛选 + 排序 ----
    print("\n[6] 列表筛选 / 排序")
    lead3, _, _ = leads["王五"]
    r = client.post(f"/api/admin/leads/{lead3}/worksheet", headers=admin_h)
    ws3 = r.json()["worksheet"]["id"]
    check("无 project 的 lead 也能转", r.status_code == 200, r.text[:200])
    # ws3 流转一步（created_at 是 CURRENT_TIMESTAMP 秒级、流转 utcnow 微秒级，
    # 混精度同秒会让排序断言抖动——流转一次确保 ws3.updated_at 严格晚于 ws2）
    r = client.patch(f"/api/admin/worksheets/{ws3}", json={"status": "communicating"}, headers=admin_h)
    assert r.status_code == 200, r.text
    r = client.get("/api/admin/worksheets", headers=admin_h)
    items = r.json()["items"]
    check("列表 3 张工单", len(items) == 3, f"实际 {len(items)}")
    # updated_at 倒序：ws3 刚流转（最新）→ ws2 won → ws1 closed（最早）
    check("按更新时间倒序 [ws3, ws2, ws1]",
          [i["id"] for i in items] == sorted([ws3, ws2, wid], reverse=True),
          str([(i["id"], i["status"]) for i in items]))
    r = client.get("/api/admin/worksheets", params={"status": "won"}, headers=admin_h)
    won_items = r.json()["items"]
    check("status=won 只筛出 ws2", len(won_items) == 1 and won_items[0]["id"] == ws2)
    r = client.get("/api/admin/worksheets", params={"status": "communicating"}, headers=admin_h)
    check("status=communicating 只筛出 ws3", len(r.json()["items"]) == 1
          and r.json()["items"][0]["id"] == ws3)
    r = client.get("/api/admin/worksheets", params={"status": "closed,won"}, headers=admin_h)
    check("逗号多选 closed,won → 2 张", len(r.json()["items"]) == 2)
    r = client.get("/api/admin/worksheets", params={"q": "李四"}, headers=admin_h)
    check("q=李四 命中 customer_name", len(r.json()["items"]) == 1
          and r.json()["items"][0]["id"] == ws2)

    # ---- [9] 无 project 的 lead：回退映射 ----
    print("\n[9] 无 project 回退")
    ws3_view = client.get(f"/api/admin/worksheets/{ws3}", headers=admin_h).json()["worksheet"]
    check("requirement_summary ← lead.note 回退",
          "客服机器人" in (ws3_view["requirement_summary"] or ""), str(ws3_view["requirement_summary"]))
    check("thread_id 为空", ws3_view["thread_id"] is None)

    # ---- [7] 权限 ----
    print("\n[7] 越权拦截")
    r = client.get("/api/admin/worksheets", headers=user_h)
    check("非 admin 列表 403", r.status_code == 403, f"实际 {r.status_code}")
    r = client.post(f"/api/admin/leads/{lead_id}/worksheet", headers=user_h)
    check("非 admin 转工单 403", r.status_code == 403)
    r = client.patch(f"/api/admin/worksheets/{ws2}", json={"status": "quoted"}, headers=user_h)
    check("非 admin 流转 403（且未改成功）", r.status_code == 403)
    r = client.get("/api/admin/worksheets")
    check("未登录 401/403", r.status_code in (401, 403), f"实际 {r.status_code}")
    # 权限被拒后 ws2 仍 won
    r = client.get(f"/api/admin/worksheets/{ws2}", headers=admin_h)
    check("越权请求未污染状态", r.json()["worksheet"]["status"] == "won")

    # ---- [8] 404 ----
    r = client.post("/api/admin/leads/99999/worksheet", headers=admin_h)
    check("不存在 lead 404", r.status_code == 404)
    r = client.get("/api/admin/worksheets/99999", headers=admin_h)
    check("不存在工单 404", r.status_code == 404)
    r = client.patch("/api/admin/worksheets/99999", json={"status": "won"}, headers=admin_h)
    check("流转不存在工单 404", r.status_code == 404)

    # ---- [10] bugfix 回归：悬空引用 / closed 409 / 删除清引用 ----
    print("\n[10] 悬空 project_id 转工单（lead #2 500 复现修复）")
    from sqlalchemy import text as sa_text
    db = SessionLocal()
    # 造悬空引用：建 project + lead，然后 FK 关闭下直删 project 行
    # （模拟历史脏数据产生路径：PRAGMA foreign_keys=ON 是后加的，
    #   关闭期删项目 → leads.project_id 悬空）
    p = Project(user_id=admin_uid, title="悬空测试项目", raw_idea="悬空项目的原始需求")
    db.add(p)
    db.flush()
    lead_d = Lead(project_id=p.id, user_id=admin_uid, name="赵六",
                  phone="13600000006", note="赵六的备注：悬空测试")
    db.add(lead_d)
    db.commit()
    dangling_pid, dangling_lid = p.id, lead_d.id
    db.close()

    db = SessionLocal()
    db.execute(sa_text("PRAGMA foreign_keys = OFF"))
    db.execute(sa_text("DELETE FROM projects WHERE id = :pid"),
               {"pid": dangling_pid})
    db.execute(sa_text("PRAGMA foreign_keys = ON"))  # 同一连接上还原，防污染连接池
    db.commit()
    db.close()

    r = client.post(f"/api/admin/leads/{dangling_lid}/worksheet", headers=admin_h)
    check("悬空 project_id 转工单 200（原来 500）", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    ws_d = r.json()["worksheet"]
    check("worksheet.project_id 置 None（不带悬空 id）",
          ws_d["project_id"] is None, str(ws_d["project_id"]))
    check("requirement_summary 回退 lead.note",
          "悬空测试" in (ws_d["requirement_summary"] or ""), str(ws_d["requirement_summary"]))
    check("thread_id 为空", ws_d["thread_id"] is None)

    # 跑真清理脚本（子进程继承本测试的隔离 env → 落在测试库）：
    # 验证 cleanup_dangling_refs.py 能把悬空引用清掉（上线前主库也要跑一次）
    import subprocess
    cp = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "cleanup_dangling_refs.py")],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",  # Windows 默认 GBK 解码子进程 UTF-8 输出会炸
        env=dict(os.environ),
    )
    check("cleanup_dangling_refs.py 跑通", cp.returncode == 0,
          (cp.stdout + cp.stderr)[-200:])
    db = SessionLocal()
    after = db.get(Lead, dangling_lid)
    check("清理脚本把悬空 lead.project_id 置空",
          after is not None and after.project_id is None,
          str(after.project_id if after else "lead 不存在"))
    db.close()

    # closed lead → 409
    print("\n[11] closed lead 转工单 409")
    db = SessionLocal()
    lead_c = Lead(user_id=admin_uid, name="钱七", phone="13500000007",
                  note="已关闭线索")
    db.add(lead_c)
    db.commit()
    closed_lid = lead_c.id
    db.close()
    r = client.patch(f"/api/admin/leads/{closed_lid}", json={"status": "closed"}, headers=admin_h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/leads/{closed_lid}/worksheet", headers=admin_h)
    check("closed lead 转工单 409", r.status_code == 409, f"实际 {r.status_code}")
    check("409 提示文案明确", "已关闭" in r.json().get("detail", "")
          and "不能转为工单" in r.json().get("detail", ""), r.text[:150])
    n = client.get("/api/admin/worksheets", headers=admin_h).json()["items"]
    check("409 未建出任何工单", all(w["lead_id"] != closed_lid for w in n))
    # 状态改回非 closed 后可转（给运营一条自助解锁路径）
    r = client.patch(f"/api/admin/leads/{closed_lid}", json={"status": "pending"}, headers=admin_h)
    r = client.post(f"/api/admin/leads/{closed_lid}/worksheet", headers=admin_h)
    check("改回非 closed 后可转", r.status_code == 200, f"实际 {r.status_code}")

    # 删除项目同步清 leads.project_id
    print("\n[12] 删除项目同步清引用")
    db = SessionLocal()
    p2 = Project(user_id=admin_uid, title="待删项目", raw_idea="删除清理测试")
    db.add(p2)
    db.flush()
    lead_e = Lead(project_id=p2.id, user_id=admin_uid, name="孙八",
                  phone="13400000008", note="删除清理")
    db.add(lead_e)
    db.commit()
    del_pid, del_lid = p2.id, lead_e.id
    db.close()
    ok = project_service.delete_project(SessionLocal(), del_pid)
    db = SessionLocal()
    cleared = db.get(Lead, del_lid)
    check("删除项目成功", ok is True)
    check("lead 保留（不删线索）", cleared is not None)
    check("lead.project_id 已置空", cleared is not None and cleared.project_id is None,
          str(cleared.project_id if cleared else "lead 不存在"))
    db.close()

    print(f"\n{'='*50}\n结果：{PASS} 通过 / {FAIL} 失败 · 测试库：{_TMP}")
    if FAIL == 0:
        print("主库未受影响（全程独立库）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
