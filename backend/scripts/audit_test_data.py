"""主库测试数据审计（W10 Day4）：只读扫描，按 test_data_rules 分拣。

绝不写库：连接用 immutable 只读模式，跑一百遍也不碰主库一个字节。
输出报告：确定删除 / 疑似 / 白名单保护 三区，每类计数 + 代表样本 5 条
+ 预计释放空间；purge_test_data.py 复用 classify() 计算同一删除集。

用法（backend/ 下）：
    python scripts/audit_test_data.py                  # 扫主库
    python scripts/audit_test_data.py --db data/x.db  # 扫指定库（演练）
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_data_rules as rules  # noqa: E402

SAMPLES = 5
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "sqlite.db"
DEFAULT_CP = Path(__file__).resolve().parent.parent / "data" / "checkpoints.sqlite"


def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        print(f"❌ 库不存在: {path}")
        sys.exit(1)
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _hit_username(username: str | None, name: str | None) -> str | None:
    """用户名命中确认级规则 → 返回规则描述，否则 None。游客规则单独判。"""
    if username is None:
        return "游客默认账号" if (name or "").strip() == rules.GUEST_NAME else None
    for p in rules.USERNAME_PREFIXES:
        if username.startswith(p):
            return f"用户名前缀 {p}"
    for pat in rules.USERNAME_PATTERNS:
        if pat.match(username):
            return f"用户名正则 {pat.pattern}"
    return None


def _hit_title_confirmed(title: str) -> str | None:
    for word, pat in rules.TITLE_CONFIRMED_PATTERNS:
        if pat.search(title):
            return word
    return None


def _hit_title_suspect(title: str) -> str | None:
    for word, pat in rules.TITLE_SUSPECT_PATTERNS:
        if pat.search(title):
            return word
    return None


@dataclass
class Report:
    """分拣结果。purge 复用同一结构算删除集。"""

    # 确认级
    users_confirmed: dict[int, str] = field(default_factory=dict)   # user_id -> 命中原因
    projects_confirmed: dict[int, str] = field(default_factory=dict)  # project_id -> 命中原因
    orphan_threads: list[str] = field(default_factory=list)        # checkpoints 孤儿 thread
    # 保护
    protected_users: dict[int, str] = field(default_factory=dict)
    protected_projects: set[int] = field(default_factory=set)
    protected_admin_projects: dict[int, str] = field(default_factory=dict)
    # 疑似
    users_suspect: dict[int, str] = field(default_factory=dict)
    projects_suspect: dict[int, str] = field(default_factory=dict)
    fake_phones: list[tuple[int, str, str]] = field(default_factory=list)  # (lead_id, phone, 名字)
    # 统计
    total_users: int = 0
    total_projects: int = 0

    @property
    def doomed_threads(self) -> set[str]:
        """将被清理的 checkpoint thread：删除项目的 thread + 孤儿 thread。"""
        return set(self.threads_by_project) | set(self.orphan_threads)

    threads_by_project: dict[int, str] = field(default_factory=dict)


def classify(db: Path, cp: Path) -> Report:
    """只读扫描主库，产出分拣报告（audit 与 purge 共用，保证看到即删到）。"""
    con = _connect_ro(db)
    rep = Report()
    users = {r["id"]: r for r in con.execute("select * from users")}
    projects = {r["id"]: r for r in con.execute("select * from projects")}
    rep.total_users = len(users)
    rep.total_projects = len(projects)

    # --- 白名单：admin + 有 leads/worksheets 的用户（业务数据一律保留） ---
    lead_users = {r["user_id"] for r in con.execute(
        "select distinct user_id from leads where user_id is not null")}
    ws_users = {r["user_id"] for r in con.execute(
        "select distinct user_id from worksheets where user_id is not null")}
    lead_projects = {r["project_id"] for r in con.execute(
        "select distinct project_id from leads where project_id is not null")}
    ws_projects = {r["project_id"] for r in con.execute(
        "select distinct project_id from worksheets where project_id is not null")}
    {r["lead_id"] for r in con.execute(
        "select distinct lead_id from worksheets where lead_id is not null")}

    for uid in rules.PROTECTED_USER_IDS | lead_users | ws_users:
        if uid in users:
            if uid in rules.PROTECTED_USER_IDS:
                why = "admin（白名单）"
            elif uid in lead_users:
                why = "名下有 leads（业务数据一律保留）"
            else:
                why = "名下有 worksheets（业务数据一律保留）"
            rep.protected_users[uid] = why
    rep.protected_projects = (lead_projects | ws_projects) & set(projects)

    # --- 用户确认级：前缀/正则/游客（白名单用户不判删） ---
    for uid, u in users.items():
        if uid in rep.protected_users:
            continue
        hit = _hit_username(u["username"], u["name"])
        if hit:
            rep.users_confirmed[uid] = hit

    # --- 项目确认级 ---
    for pid, p in projects.items():
        owner = p["user_id"]
        if pid in rep.protected_projects:
            continue
        if owner in rep.users_confirmed:
            # 属主已判删 → 整个用户连同项目走，原因记用户级
            rep.projects_confirmed[pid] = f"属主命中({rep.users_confirmed[owner]})"
        elif owner is None:
            rep.projects_confirmed[pid] = "孤儿项目（user_id 为空）"
        else:
            hit = _hit_title_confirmed(p["title"] or "")
            if hit:
                note = "admin 自用测试标题" if owner in rep.protected_users else "标题黑名单"
                rep.projects_confirmed[pid] = f"{note}：{hit}"
            elif owner in rep.protected_users:
                # W10 Day4 用户定夺：白名单用户（admin/有 leads）名下未命中
                # 确认级的都是真实诊断（原疑似区 22 条），收编白名单
                rep.protected_admin_projects[pid] = "白名单用户真实诊断（疑似区收编）"

    # --- 疑似区（只报告）：非 admin 用户名下命中疑似词的项目 ---
    for pid, p in projects.items():
        if (pid in rep.projects_confirmed or pid in rep.protected_projects
                or p["user_id"] in rules.PROTECTED_USER_IDS):
            continue
        hit = _hit_title_suspect(p["title"] or "")
        if hit:
            rep.projects_suspect[pid] = f"标题疑似词「{hit}」"

    # --- 假手机（只报告：leads 受保护） ---
    for r in con.execute("select id, name, phone from leads where phone is not null"):
        if rules.FAKE_PHONE_PATTERN.match(r["phone"]):
            rep.fake_phones.append((r["id"], r["phone"], r["name"] or "?"))

    # --- checkpoint threads ---
    for pid in set(rep.projects_confirmed):
        t = projects[pid]["thread_id"]
        if t:
            rep.threads_by_project[pid] = t
    if cp.exists():
        con2 = _connect_ro(cp)
        main_threads = {p["thread_id"] for p in projects.values() if p["thread_id"]}
        rep.orphan_threads = [
            r["thread_id"] for r in con2.execute(
                "select distinct thread_id from checkpoints")
            if r["thread_id"] not in main_threads
        ]
        con2.close()
    con.close()
    return rep


def _estimate_space(db: Path, cp: Path, rep: Report) -> str:
    con = _connect_ro(db)
    pids = list(rep.projects_confirmed) or [-1]
    conv_b = con.execute(
        "select coalesce(sum(length(content)),0) from conversations "
        "where project_id in ({})".format(",".join("?" * len(pids))), pids).fetchone()[0]
    plan_b = con.execute(
        "select coalesce(sum(length(coalesce(plan,'')) + length(coalesce(raw_idea,'')) "
        "+ length(coalesce(req_profile,''))),0) from projects "
        "where id in ({})".format(",".join("?" * len(pids))), pids).fetchone()[0]
    con.close()
    cp_b = 0
    if cp.exists() and rep.doomed_threads:
        con2 = _connect_ro(cp)
        ts = list(rep.doomed_threads)
        q = ",".join("?" * len(ts))
        cp_b = con2.execute(
            f"select coalesce(sum(length(checkpoint)),0) from checkpoints "
            f"where thread_id in ({q})", ts).fetchone()[0]
        cp_b += con2.execute(
            f"select coalesce(sum(length(value)),0) from writes "
            f"where thread_id in ({q})", ts).fetchone()[0]
        con2.close()
    return (f"对话 {conv_b/1024:.0f} KB + 项目正文 {plan_b/1024:.0f} KB "
            f"+ checkpoint blob {cp_b/1024/1024:.1f} MB")


def _print_group(title: str, items: list[str], total: int) -> None:
    print(f"\n  {title}：共 {total} 条")
    for line in items[:SAMPLES]:
        print(f"    - {line}")
    if total > len(items):
        print(f"    ……（其余 {total - len(items)} 条略）")


def print_report(db: Path, cp: Path) -> Report:
    rep = classify(db, cp)
    con = _connect_ro(db)

    print("=" * 72)
    print(f"测试数据审计报告（只读）：{db}")
    print(f"用户 {rep.total_users} / 项目 {rep.total_projects}")
    print("=" * 72)

    # 白名单
    print("\n【白名单保护】（purge 永不删）")
    for uid, why in sorted(rep.protected_users.items()):
        u = con.execute("select username, name from users where id=?", (uid,)).fetchone()
        print(f"  - user {uid}（{u['username'] or u['name']}）：{why}")
    if rep.protected_projects:
        print(f"  - 受 leads/worksheets 引用的项目 {len(rep.protected_projects)} 个："
              f"{sorted(rep.protected_projects)}")
    if rep.protected_admin_projects:
        print(f"  - 白名单用户真实诊断项目 {len(rep.protected_admin_projects)} 个"
              f"（疑似区已收编，永不删）："
              f"{sorted(rep.protected_admin_projects)}")

    # 确认级
    print(f"\n【确定删除】用户 {len(rep.users_confirmed)} / 项目 {len(rep.projects_confirmed)}"
          f" / 孤儿 checkpoint thread {len(rep.orphan_threads)}")
    by_reason: dict[str, list[str]] = {}
    for uid, why in rep.users_confirmed.items():
        by_reason.setdefault(why, []).append(f"user {uid}（{users_name(con, uid)}）")
    for why, items in sorted(by_reason.items()):
        _print_group(f"用户·{why}", items, len(items))

    rows = con.execute(
        f"select id, user_id, title from projects where id in "
        f"({','.join('?' * len(rep.projects_confirmed)) or '-1'})",
        list(rep.projects_confirmed)).fetchall() if rep.projects_confirmed else []
    by_reason = {}
    for r in rows:
        by_reason.setdefault(rep.projects_confirmed[r["id"]], []).append(
            f"project {r['id']} (user {r['user_id']})「{r['title'][:24]}」")
    for why, items in sorted(by_reason.items()):
        _print_group(f"项目·{why}", items, len(items))

    _print_group("孤儿 checkpoint thread（不在任何 project 名下）",
                 rep.orphan_threads, len(rep.orphan_threads))

    # 疑似区
    print("\n【疑似】（只报告不删，人工定夺）")
    if rep.fake_phones:
        _print_group("假手机号 lead（受保护不删，供核查话术样本）",
                     [f"lead {i} {p} {n}" for i, p, n in rep.fake_phones],
                     len(rep.fake_phones))
    rows = con.execute(
        f"select id, user_id, title from projects where id in "
        f"({','.join('?' * len(rep.projects_suspect)) or '-1'})",
        list(rep.projects_suspect)).fetchall() if rep.projects_suspect else []
    by_reason = {}
    for r in rows:
        by_reason.setdefault(rep.projects_suspect[r["id"]], []).append(
            f"project {r['id']} (user {r['user_id']})「{r['title'][:24]}」")
    for why, items in sorted(by_reason.items()):
        _print_group(f"项目·{why}", items, len(items))

    pids = list(rep.projects_confirmed)
    if pids:
        q = ",".join("?" * len(pids))
        n_conv = con.execute(
            f"select count(*) from conversations where project_id in ({q})", pids).fetchone()[0]
        n_sess = con.execute(
            "select count(*) from auth_sessions where user_id in "
            f"({','.join('?' * len(rep.users_confirmed)) or '-1'})",
            list(rep.users_confirmed)).fetchone()[0] if rep.users_confirmed else 0
        print(f"\n【预计释放】{_estimate_space(db, cp, rep)}"
          f"\n  连带清理：conversations {n_conv} 行 / sessions {n_sess} 行"
          f" / checkpoint+writes thread {len(rep.doomed_threads)} 个")
    con.close()
    print("\n（audit 只读，未动库。真删：python scripts/purge_test_data.py --execute）")
    return rep


def users_name(con: sqlite3.Connection, uid: int) -> str:
    r = con.execute("select username, name from users where id=?", (uid,)).fetchone()
    return r["username"] or r["name"] if r else "?"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="主库测试数据审计（只读）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--checkpoints", type=Path, default=DEFAULT_CP)
    args = ap.parse_args()
    print_report(args.db, args.checkpoints)
