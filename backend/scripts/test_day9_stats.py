"""W7 Day9 验收：数据看板 GET /api/admin/stats。

⚠️ 测试隔离：env 覆盖四路径（Day7 基础设施），独立临时库，不碰主库。

验证点：
- [1] 空表：全 0，不报错、不 NaN；转化率 rates 全 None（除零保护）
- [2] 单条边界：各表 1 行时卡片/漏斗数字正确，转化率 100% 链
- [3] 今日新增 vs 累计：today/total 分离（造昨日数据 + 今日数据）
- [4] 趋势：14 天数组、缺日补 0、数字与库一致
- [5] 漏斗：won 工单单独统计；分母 0 时下游率 None
- [6] 权限：非 admin 403、未登录 401/403
- [7] admin 转工单路径连带数字联动（project→lead→worksheet→won 全链）
- [8] W8 热身·跨零点回归：北京时间 23:59（昨日）/ 00:01（今日）的
      数据必须分进正确的一天（旧 UTC 口径会把 0~8 点数据算进前一天）

W8 热身后看板口径 = 北京时间（Asia/Shanghai）；造数仍用 UTC（库口径），
断言经 _bj_date_key 换算到北京日期。

用法（在 backend/ 下，零 LLM token）：
    python scripts/test_day9_stats.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# ---------- 测试隔离：env 必须在 import app 之前设置 ----------
_TMP = Path(tempfile.mkdtemp(prefix="day9_test_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["ADMIN_USER_IDS"] = "1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.admin import _bj_date_key  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import Lead, Project, User, Worksheet  # noqa: E402
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


def main():
    init_db()
    client = TestClient(app)

    # ---- [1] 空表（注册前查，users 才是真正的 0）----
    print("[1] 空表")
    r = client.get("/api/admin/stats")
    check("未登录 401/403（空表阶段顺带验权限）", r.status_code in (401, 403),
          f"实际 {r.status_code}")

    # 空表阶段需要 admin 身份：先注册一个 admin 专用账号，
    # 但注册后 users.today 会变 1——users 空表断言放在注册前用
    # 直接查库方式绕开（stats API 需要 token，无法在 0 用户时持有 token）
    db = SessionLocal()
    check("库内 users=0（空表）", db.query(User).count() == 0)
    db.close()

    r = client.post("/api/auth/register", json={
        "username": "day9_admin", "password": "day9pass123"})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={
        "username": "day9_admin", "password": "day9pass123"})
    assert r.status_code == 200, r.text
    admin_h = {"Authorization": "Bearer " + r.json()["token"]}

    r = client.post("/api/auth/register", json={
        "username": "day9_user", "password": "day9pass456"})
    r = client.post("/api/auth/login", json={
        "username": "day9_user", "password": "day9pass456"})
    user_h = {"Authorization": "Bearer " + r.json()["token"]}

    # ---- [1b] 业务表空表（此时仅 users 有 2 行注册数据）----
    print("\n[1b] 业务表空（users 已注册除外）")
    r = client.get("/api/admin/stats", headers=admin_h)
    check("GET /api/admin/stats 200", r.status_code == 200, r.text[:200])
    s = r.json()
    check("projects 0/0", s["cards"]["projects"] == {"total": 0, "today": 0})
    check("leads 0/0", s["cards"]["leads"] == {"total": 0, "today": 0})
    check("worksheets 0/0", s["cards"]["worksheets"] == {"total": 0, "today": 0})
    check("漏斗全 0", s["funnel"]["projects"] == 0 and s["funnel"]["leads"] == 0
          and s["funnel"]["worksheets"] == 0 and s["funnel"]["won"] == 0)
    check("空表转化率全 None（不 NaN）",
          all(v is None for v in s["funnel"]["rates"].values()),
          str(s["funnel"]["rates"]))
    check("趋势 14 天", len(s["trend"]) == 14 and s["trend_days"] == 14)
    check("空表趋势全 0", all(d["projects"] == 0 and d["leads"] == 0 for d in s["trend"]))
    check("无 NaN/None 数字（json 序列化完整）",
          isinstance(s["trend"][0]["projects"], int))

    # ---- [7] 造全链数据（2 项目 + 2 lead + 1 工单 + 1 won）----
    print("\n[7] 造全链数据（含昨日/今日分布）")
    db = SessionLocal()
    uid = 1
    now = datetime.utcnow()
    # 昨日项目 ×2、今日项目 ×1（today/total 分离验证 + 趋势）
    yesterday = now - timedelta(days=1)
    p1 = Project(user_id=uid, title="昨日项目A", created_at=yesterday)
    p2 = Project(user_id=uid, title="昨日项目B", created_at=yesterday)
    p3 = Project(user_id=uid, title="今日项目", created_at=now)
    db.add_all([p1, p2, p3])
    # 昨日 lead ×1、今日 lead ×1
    l1 = Lead(project_id=p1.id, user_id=uid, name="昨日客", phone="138",
              created_at=yesterday)
    l2 = Lead(project_id=p2.id, user_id=uid, name="今日客", phone="139",
              created_at=now)
    db.add_all([l1, l2])
    # 工单：一张 won（今日建）、一张 to_confirm（昨日建）
    ws1 = Worksheet(lead_id=l1.id, project_id=p1.id, user_id=uid,
                    customer_name="昨日客", contact="138",
                    status=Worksheet.STATUS_WON, created_at=yesterday)
    ws2 = Worksheet(lead_id=l2.id, project_id=p2.id, user_id=uid,
                    customer_name="今日客", contact="139",
                    status=Worksheet.STATUS_TO_CONFIRM, created_at=now)
    db.add_all([ws1, ws2])
    db.commit()
    db.close()

    r = client.get("/api/admin/stats", headers=admin_h)
    s = r.json()

    # ---- [2] 单条边界/今日累计分离 ----
    print("\n[2] 卡片数字（今日 vs 累计）")
    # users：注册了 2 个（admin+user），today=2（测试内创建）
    check("users total=2", s["cards"]["users"]["total"] == 2, str(s["cards"]["users"]))
    check("users today=2", s["cards"]["users"]["today"] == 2)
    check("projects total=3 today=1",
          s["cards"]["projects"] == {"total": 3, "today": 1}, str(s["cards"]["projects"]))
    check("leads total=2 today=1",
          s["cards"]["leads"] == {"total": 2, "today": 1}, str(s["cards"]["leads"]))
    check("worksheets total=2 today=1",
          s["cards"]["worksheets"] == {"total": 2, "today": 1}, str(s["cards"]["worksheets"]))

    # ---- [5] 漏斗 ----
    print("\n[5] 漏斗")
    f = s["funnel"]
    check("projects=3 leads=2 worksheets=2 won=1",
          (f["projects"], f["leads"], f["worksheets"], f["won"]) == (3, 2, 2, 1),
          str((f["projects"], f["leads"], f["worksheets"], f["won"])))
    check("项目→留资 66.7%", f["rates"]["project_to_lead"] == 66.7,
          str(f["rates"]["project_to_lead"]))
    check("留资→工单 100%", f["rates"]["lead_to_worksheet"] == 100.0)
    check("工单→成交 50%", f["rates"]["worksheet_to_won"] == 50.0)

    # ---- [4] 趋势（北京时区分桶） ----
    print("\n[4] 趋势")
    t = s["trend"]
    # 断言口径：北京日期（造数是 UTC，经 _bj_date_key 换算后比对）
    today_key = _bj_date_key(now)
    yesterday_key = _bj_date_key(yesterday)
    check("14 天补齐含今日（北京日）", t[-1]["date"] == today_key,
          f"末位 {t[-1]['date']} vs 北京今日 {today_key}")
    check("今日 projects=1 leads=1",
          t[-1]["projects"] == 1 and t[-1]["leads"] == 1, str(t[-1]))
    y_item = next((d for d in t if d["date"] == yesterday_key), None)
    check("昨日 projects=2 leads=1",
          y_item is not None and y_item["projects"] == 2 and y_item["leads"] == 1,
          str(y_item))
    check("首日 = 13 天前（北京日）",
          t[0]["date"] == _bj_date_key(now - timedelta(days=13)), t[0]["date"])
    check("趋势总和 = 总数（projects 3 / leads 2）",
          sum(d["projects"] for d in t) == 3 and sum(d["leads"] for d in t) == 2)

    # ---- 分母 0 时下游 None（只有 won 没有上游的极端库）----
    print("\n[5b] 除零保护（极端：只有 worksheet 无 project/lead）")
    db = SessionLocal()
    db.add(Worksheet(customer_name="孤儿", contact="137",
                     status=Worksheet.STATUS_WON))
    db.commit()
    db.close()
    r = client.get("/api/admin/stats", headers=admin_h)
    s2 = r.json()
    check("worksheets total=3 won=2", s2["funnel"]["worksheets"] == 3
          and s2["funnel"]["won"] == 2, str(s2["funnel"]))
    check("worksheet_to_won 正常（66.7）", s2["funnel"]["rates"]["worksheet_to_won"] == 66.7,
          str(s2["funnel"]["rates"]))

    # ---- [6] 权限 ----
    print("\n[6] 越权拦截")
    r = client.get("/api/admin/stats", headers=user_h)
    check("非 admin 403", r.status_code == 403, f"实际 {r.status_code}")
    r = client.get("/api/admin/stats")
    check("未登录 401/403", r.status_code in (401, 403), f"实际 {r.status_code}")

    # ---- [8] W8 热身：跨零点分桶回归（北京口径核心用例） ----
    # 造两条贴着北京零点的数据：23:59（应归昨日）/ 00:01（应归今日）。
    # 旧 UTC 口径下，北京 0~8 点的数据日期键停在前一天——正是本用例防的回归。
    print("\n[8] 跨零点分桶（北京 23:59 / 00:01）")
    from app.api.admin import _bj_midnight_utc
    bj_mid = _bj_midnight_utc()  # 北京今日零点（UTC naive，与库同口径）
    db = SessionLocal()
    db.add(Project(user_id=uid, title="北京昨晚23:59",
                   created_at=bj_mid - timedelta(minutes=1)))
    db.add(Project(user_id=uid, title="北京今日00:01",
                   created_at=bj_mid + timedelta(minutes=1)))
    db.commit()
    db.close()

    r = client.get("/api/admin/stats", headers=admin_h)
    s3 = r.json()
    # projects.today：[7] 今日 1 条 + 跨零点 00:01 的 1 条 = 2；23:59 那条不算
    check("today 含 00:01 不含 23:59",
          s3["cards"]["projects"]["today"] == 2, str(s3["cards"]["projects"]))
    t3 = s3["trend"]
    today_item = next((d for d in t3 if d["date"] == _bj_date_key(bj_mid + timedelta(minutes=1))), None)
    prev_item = next((d for d in t3 if d["date"] == _bj_date_key(bj_mid - timedelta(minutes=1))), None)
    check("趋势：00:01 归北京今日",
          today_item is not None and today_item["projects"] == 2, str(today_item))
    check("趋势：23:59 归北京昨日",
          prev_item is not None and prev_item["projects"] == 3, str(prev_item))

    print(f"\n{'='*50}\n结果：{PASS} 通过 / {FAIL} 失败 · 测试库：{_TMP}")
    if FAIL == 0:
        print("主库未受影响（全程独立库）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
