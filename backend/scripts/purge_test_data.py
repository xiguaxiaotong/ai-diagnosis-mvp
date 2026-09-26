"""测试数据清理执行（W10 Day4）：audit 分拣结果的落地执行器。

安全设计（每一条都是被主库污染逼出来的）：
  1. 默认 dry-run：只打印将删清单，一个字节都不动；
  2. --execute 前先**全量归档**将删数据到 backups/purge_YYYYMMDD.json
     （含 checkpoint blob base64），删错可 --restore-file 恢复；
  3. 白名单硬保护：user_id=1（admin）、所有 leads/worksheets（含引用它们的
     projects 与关联用户）永远不进删除集——在 classify 层就排除，不靠操作顺序；
  4. 删除顺序（FK ON 下显式执行，不赌 CASCADE）：conversations →
     checkpoints/writes（独立库）→ password_reset_tokens → auth_sessions →
     被删项目的 leads/worksheets 引用置 NULL → projects → users；
  5. 删完跑 PRAGMA integrity_check（两个库都查），不 ok 直接报错退出非零。

用法（backend/ 下）：
    python scripts/purge_test_data.py                     # dry-run 主库
    python scripts/purge_test_data.py --execute           # 真删（先归档）
    python scripts/purge_test_data.py --db data/x.db --execute   # 演练库
    python scripts/purge_test_data.py --restore-file backups/purge_YYYYMMDD.json --user 2
        # 从归档恢复指定 user/project（--all 全量恢复），可逆验证
"""
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_test_data import (  # noqa: E402
    DEFAULT_CP,
    DEFAULT_DB,
    classify,
)

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
_BLOB_COLS = {"checkpoint", "value"}  # checkpoints/writes 里的 blob 列 → 归档时 base64


def _connect_rw(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    return con


def _rows(con: sqlite3.Connection, sql: str, args: list) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args)]


def _encode(rows: list[dict]) -> list[dict]:
    """blob 列 → base64 字符串（JSON 不能直接放 bytes）。"""
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, bytes):
                r[k] = {"__b64__": base64.b64encode(v).decode("ascii")}
    return rows


def _decode(rows: list[dict]) -> list[dict]:
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, dict) and "__b64__" in v:
                r[k] = base64.b64decode(v["__b64__"])
    return rows


def _qs(n: int) -> str:
    return ",".join("?" * n) if n else "select 1 where 0"


# ---------- 归档 ----------

def archive(db: Path, cp: Path, rep, out: Path) -> Path:
    """将删数据全量导出 JSON（可逆保障）。含被 SET NULL 波及的保护行。"""
    con = _connect_rw(db)
    uids = list(rep.users_confirmed)
    pids = list(rep.projects_confirmed)
    threads = list(rep.doomed_threads)
    data = {
        "meta": {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "db": str(db), "checkpoints": str(cp),
            "note": "purge_test_data 删除前归档；--restore-file 可恢复",
        },
        "users": _encode(_rows(con, f"select * from users where id in ({_qs(len(uids))})", uids)),
        "projects": _encode(_rows(con, f"select * from projects where id in ({_qs(len(pids))})", pids)),
        "conversations": _encode(_rows(
            con, f"select * from conversations where project_id in ({_qs(len(pids))})", pids)),
        "auth_sessions": _encode(_rows(
            con, f"select * from auth_sessions where user_id in ({_qs(len(uids))})", uids)),
        "password_reset_tokens": _encode(_rows(
            con, f"select * from password_reset_tokens where user_id in ({_qs(len(uids))})", uids)),
        # 被删项目的 leads/worksheets 引用会被置 NULL：归档原行以便还原
        "leads_touched": _encode(_rows(
            con, f"select * from leads where project_id in ({_qs(len(pids))})", pids)),
        "worksheets_touched": _encode(_rows(
            con, f"select * from worksheets where project_id in ({_qs(len(pids))})", pids)),
        # 被删用户写的 admin note：admin_id 会被置 NULL，归档原行
        "lead_notes_touched": _encode(_rows(
            con, f"select * from lead_notes where admin_id in ({_qs(len(uids))})", uids)),
        "worksheet_notes_touched": _encode(_rows(
            con, f"select * from worksheet_notes where admin_id in ({_qs(len(uids))})", uids)),
    }
    con.close()
    if cp.exists() and threads:
        con2 = _connect_rw(cp)
        data["checkpoints"] = _encode(_rows(
            con2, f"select * from checkpoints where thread_id in ({_qs(len(threads))})", threads))
        data["writes"] = _encode(_rows(
            con2, f"select * from writes where thread_id in ({_qs(len(threads))})", threads))
        con2.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
    kb = out.stat().st_size / 1024
    print(f"[归档] {out}（{kb:.0f} KB）")
    return out


# ---------- 删除 ----------

def execute_purge(db: Path, cp: Path, rep) -> None:
    uids, pids, threads = (list(rep.users_confirmed),
                           list(rep.projects_confirmed), list(rep.doomed_threads))
    con = _connect_rw(db)
    n_conv = con.execute(
        f"select count(*) from conversations where project_id in ({_qs(len(pids))})", pids).fetchone()[0]
    con.execute(f"delete from conversations where project_id in ({_qs(len(pids))})", pids)
    n_tok = con.execute(
        f"select count(*) from password_reset_tokens where user_id in ({_qs(len(uids))})", uids).fetchone()[0]
    con.execute(f"delete from password_reset_tokens where user_id in ({_qs(len(uids))})", uids)
    n_sess = con.execute(
        f"select count(*) from auth_sessions where user_id in ({_qs(len(uids))})", uids).fetchone()[0]
    con.execute(f"delete from auth_sessions where user_id in ({_qs(len(uids))})", uids)
    # 保护对象引用先解绑（leads/worksheets 一律保留，只把指向死项目的引用置空）
    con.execute(f"update leads set project_id=null where project_id in ({_qs(len(pids))})", pids)
    con.execute(f"update worksheets set project_id=null where project_id in ({_qs(len(pids))})", pids)
    con.execute(f"delete from projects where id in ({_qs(len(pids))})", pids)
    con.execute(f"delete from users where id in ({_qs(len(uids))})", uids)
    con.commit()
    left = con.execute("select count(*) from users").fetchone()[0]
    con.close()

    n_cp = n_wr = 0
    if cp.exists() and threads:
        con2 = _connect_rw(cp)
        n_cp = con2.execute(
            f"select count(*) from checkpoints where thread_id in ({_qs(len(threads))})",
            threads).fetchone()[0]
        n_wr = con2.execute(
            f"select count(*) from writes where thread_id in ({_qs(len(threads))})",
            threads).fetchone()[0]
        con2.execute(f"delete from checkpoints where thread_id in ({_qs(len(threads))})", threads)
        con2.execute(f"delete from writes where thread_id in ({_qs(len(threads))})", threads)
        con2.commit()
        con2.close()
    print(f"[删除] users {len(uids)} / projects {len(pids)} / conversations {n_conv} "
          f"/ sessions {n_sess} / reset_tokens {n_tok} / checkpoints {n_cp} / writes {n_wr}")
    print(f"[删除后] 主库剩余用户 {left}")


def integrity_check(db: Path, cp: Path) -> None:
    for p in (db, cp):
        if not p.exists():
            continue
        con = sqlite3.connect(p)
        ok = con.execute("pragma integrity_check").fetchone()[0]
        con.close()
        print(f"[integrity] {p.name}: {ok}")
        if ok != "ok":
            print(f"❌ {p.name} integrity_check 未通过")
            sys.exit(1)


# ---------- 恢复 ----------

def _insert_back(con: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    sql = (f"insert or replace into {table} ({','.join(cols)}) "
           f"values ({','.join('?' * len(cols))})")
    con.executemany(sql, [[r[c] for c in cols] for r in rows])
    return len(rows)


def restore(archive_file: Path, db: Path, cp: Path,
            user: int | None, project: int | None, all_data: bool) -> None:
    """从归档恢复。--user/--project 恢复该对象及其级联（验证可逆）；--all 全量。"""
    data = json.loads(archive_file.read_text(encoding="utf-8"))
    for key in ("users", "projects", "checkpoints", "writes"):
        data[key] = _decode(data.get(key, []))
    con = _connect_rw(db)

    if all_data:
        pick_users, pick_projects = data["users"], data["projects"]
    elif user is not None:
        pick_users = [r for r in data["users"] if r["id"] == user]
        uids = {r["id"] for r in pick_users}
        pick_projects = [r for r in data["projects"] if r["user_id"] in uids]
        if not pick_users:
            print(f"❌ 归档中无 user {user}")
            sys.exit(1)
    elif project is not None:
        pick_users, pick_projects = [], [r for r in data["projects"] if r["id"] == project]
        if not pick_projects:
            print(f"❌ 归档中无 project {project}")
            sys.exit(1)
    else:
        print("❌ 需指定 --user / --project / --all 之一")
        sys.exit(1)

    pids = {r["id"] for r in pick_projects}
    uids2 = {r["id"] for r in pick_users}
    n = _insert_back(con, "users", pick_users)
    n += _insert_back(con, "projects", pick_projects)
    n += _insert_back(con, "conversations",
                      [r for r in _decode(data.get("conversations", []))
                       if r["project_id"] in pids])
    n += _insert_back(con, "auth_sessions",
                      [r for r in _decode(data.get("auth_sessions", []))
                       if r["user_id"] in uids2])
    n += _insert_back(con, "password_reset_tokens",
                      [r for r in _decode(data.get("password_reset_tokens", []))
                       if r["user_id"] in uids2])
    # 保护行引用还原（被置 NULL 的 project_id / admin_id）
    for table, key, col in (("leads", "leads_touched", "project_id"),
                            ("worksheets", "worksheets_touched", "project_id"),
                            ("lead_notes", "lead_notes_touched", "admin_id"),
                            ("worksheet_notes", "worksheet_notes_touched", "admin_id")):
        rows = _decode(data.get(key, []))
        if not all_data:
            wanted = pids if col == "project_id" else uids2
            rows = [r for r in rows if r.get(col) in wanted]
        n += _insert_back(con, table, rows)
    con.commit()
    con.close()

    # checkpoint 库：全量恢复取全部归档行（含孤儿 thread）；
    # 定向恢复只取恢复项目的 thread
    if cp.exists():
        con2 = _connect_rw(cp)
        if all_data:
            n += _insert_back(con2, "checkpoints", data["checkpoints"])
            n += _insert_back(con2, "writes", data["writes"])
        else:
            threads = {r["thread_id"] for r in pick_projects if r.get("thread_id")}
            if threads:
                n += _insert_back(con2, "checkpoints",
                                  [r for r in data["checkpoints"] if r["thread_id"] in threads])
                n += _insert_back(con2, "writes",
                                  [r for r in data["writes"] if r["thread_id"] in threads])
        con2.commit()
        con2.close()
    print(f"[恢复] {archive_file.name} → 写回 {n} 行"
          + ("（全量）" if all_data else f"（user {user} 级联）" if user is not None
             else f"（project {project}）"))


# ---------- dry-run ----------

def dry_run(db: Path, cp: Path, rep) -> None:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    uids, pids = list(rep.users_confirmed), list(rep.projects_confirmed)
    n_conv = con.execute(
        f"select count(*) from conversations where project_id in ({_qs(len(pids))})", pids).fetchone()[0]
    n_sess = con.execute(
        f"select count(*) from auth_sessions where user_id in ({_qs(len(uids))})", uids).fetchone()[0]
    names = [r["username"] or r["name"] for r in con.execute(
        f"select username, name from users where id in ({_qs(len(uids))})", uids)]
    con.close()
    print("=" * 72)
    print("DRY-RUN（未动库）。将删除：")
    print(f"  users {len(uids)}: {', '.join(names[:12])}{'…' if len(names) > 12 else ''}")
    print(f"  projects {len(pids)} / conversations {n_conv} / sessions {n_sess}")
    print(f"  checkpoint+writes threads {len(rep.doomed_threads)}（含孤儿 {len(rep.orphan_threads)}）")
    print(f"  白名单保护：{len(rep.protected_users)} 用户 / {len(rep.protected_projects)} 项目不动")
    print("真删请加 --execute（删前自动归档到 backups/purge_*.json）")
    print("=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(description="测试数据清理执行（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--checkpoints", type=Path, default=DEFAULT_CP)
    ap.add_argument("--execute", action="store_true", help="真删（默认 dry-run）")
    ap.add_argument("--out", type=Path, default=None, help="归档路径（默认 backups/purge_日期.json）")
    ap.add_argument("--restore-file", type=Path, help="从归档恢复")
    ap.add_argument("--user", type=int, help="恢复该用户（级联其项目/对话）")
    ap.add_argument("--project", type=int, help="恢复该项目（级联对话）")
    ap.add_argument("--all", action="store_true", help="全量恢复")
    args = ap.parse_args()

    if args.restore_file:
        restore(args.restore_file, args.db, args.checkpoints,
                args.user, args.project, args.all)
        integrity_check(args.db, args.checkpoints)
        return

    rep = classify(args.db, args.checkpoints)
    if args.execute:
        if rep.users_confirmed and rep.protected_users.keys() & set(rep.users_confirmed):
            print("❌ 白名单用户混入删除集，拒绝执行")  # classify 已排除，双保险
            sys.exit(1)
        out = args.out or (BACKUP_DIR / time.strftime("purge_%Y%m%d.json"))
        if out.exists():  # 同天重跑：加时间戳，不覆盖上一份归档
            out = out.with_name(out.stem + time.strftime("_%H%M%S") + out.suffix)
        archive(args.db, args.checkpoints, rep, out)
        execute_purge(args.db, args.checkpoints, rep)
        integrity_check(args.db, args.checkpoints)
        print(f"✅ 清理完成。归档可恢复：--restore-file {out}")
    else:
        dry_run(args.db, args.checkpoints, rep)


if __name__ == "__main__":
    main()
