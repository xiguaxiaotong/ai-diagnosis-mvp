"""W10 Day5：备份/恢复例行化的核心逻辑测试（快速档）。

覆盖：快照目录生成（主库+checkpoints+当日 purge 归档）、备份副本
integrity、prune 计数与保留边界、restore 对坏备份目录的友好报错
且不碰真库。全部走临时目录，不碰 backend/data 真库。
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
SCRIPTS = BACKEND / "scripts"
sys.path.insert(0, str(SCRIPTS))

backup_full = importlib.import_module("backup_full")
restore_backup = importlib.import_module("restore_backup")


def _make_db(path: Path, users: int = 3) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        "create table users (id integer primary key, username text);"
        "create table projects (id integer primary key, user_id integer);")
    con.executemany("insert into users values (?, ?)",
                    [(i, f"u{i}") for i in range(1, users + 1)])
    con.commit()
    con.close()


@pytest.fixture()
def env(tmp_path: Path):
    """主库 + checkpoints 库 + 两份旧 purge 归档的 backups 根。"""
    db = tmp_path / "sqlite.db"
    cp = tmp_path / "checkpoints.sqlite"
    _make_db(db)
    _make_db(cp, users=0)
    root = tmp_path / "backups"
    root.mkdir()
    (root / "purge_20260101.json").write_text("{}", encoding="utf-8")
    (root / "purge_20260102.json").write_text("{}", encoding="utf-8")
    return db, cp, root


# ---------- 快照目录生成 ----------

def test_make_backup_creates_snapshot_dir(env):
    """快照目录含主库+checkpoints 热备副本与当日 purge 归档，副本 integrity ok。"""
    db, cp, root = env
    snap = backup_full.make_backup(db, cp, root, today="20260101",
                                   now="20260102_030000")
    assert snap.name == "20260102_030000"
    assert (snap / "sqlite.db").exists()
    assert (snap / "checkpoints.sqlite").exists()
    # 只捞「当日」（today=20260101）的 purge 归档，前一天的 20260102 不进来
    assert (snap / "purge_20260101.json").exists()
    assert not (snap / "purge_20260102.json").exists()
    # 备份副本数据完整
    con = sqlite3.connect(snap / "sqlite.db")
    assert con.execute("select count(*) from users").fetchone()[0] == 3
    con.close()


def test_make_backup_skip_missing_checkpoints(env):
    """checkpoints 库不存在时快照只含主库，不算错（空库天经地义）。"""
    db, _, root = env
    snap = backup_full.make_backup(db, None, root, today="20260101",
                                   now="20260102_030001")
    assert not (snap / "checkpoints.sqlite").exists()
    assert (snap / "sqlite.db").exists()


def test_make_backup_rejects_missing_db(env, capsys):
    """主库不存在 → 非零退出且报错信息含路径。"""
    with pytest.raises(SystemExit):
        backup_full.make_backup(env[2] / "nope.db", None, env[2])
    assert "nope.db" in capsys.readouterr().out


def test_make_backup_corrupt_dest_fails(tmp_path, monkeypatch):
    """integrity 不通过时非零退出（备份的意义是能恢复，不是文件存在）。"""
    db = tmp_path / "sqlite.db"
    _make_db(db)
    calls = {"n": 0}

    def fake_hot_backup(src, dest):
        calls["n"] += 1
        dest.write_bytes(b"this is not a sqlite file at all")

    monkeypatch.setattr(backup_full, "hot_backup", fake_hot_backup)
    with pytest.raises(SystemExit):
        backup_full.make_backup(db, None, tmp_path, today="20260101",
                                now="20260102_030002")
    assert calls["n"] == 1


# ---------- prune ----------

def _snapshots(root: Path, n: int) -> None:
    for i in range(n):
        (root / f"2026010{i + 1}_030000").mkdir()
        (root / f"2026010{i + 1}_030000" / "sqlite.db").write_bytes(b"x")


def test_prune_keeps_recent_and_counts(env):
    """保留最近 N 份，删除数 = 总数-N，被删清单先打印后删。"""
    _, _, root = env
    _snapshots(root, 5)
    doomed = backup_full.prune_snapshots(root, keep=2)
    assert len(doomed) == 3
    left = sorted(d.name for d in root.iterdir() if d.is_dir()
                  and backup_full.SNAPSHOT_DIR_RE.match(d.name))
    assert left == ["20260104_030000", "20260105_030000"]


def test_prune_ignores_flat_files_and_other_dirs(env):
    """prune 只动 YYYYMMDD_HHMMSS 快照目录；单库热备/purge 归档/杂目录不动。"""
    _, _, root = env
    _snapshots(root, 1)
    (root / "sqlite_20260101_030000.db").write_bytes(b"x")   # W9 单库热备
    (root / "purge_20260101.json").write_text("{}", encoding="utf-8")
    (root / "not_a_snapshot").mkdir()
    doomed = backup_full.prune_snapshots(root, keep=1)
    assert doomed == []
    assert (root / "sqlite_20260101_030000.db").exists()
    assert (root / "purge_20260101.json").exists()
    assert (root / "not_a_snapshot").exists()


def test_prune_zero_removes_all(env):
    """keep=0 = 全清（边界约定）。"""
    _, _, root = env
    _snapshots(root, 3)
    assert len(backup_full.prune_snapshots(root, keep=0)) == 3


# ---------- restore：坏备份目录 ----------

def test_restore_rejects_missing_dir(tmp_path, capsys):
    """目录不存在 → SystemExit(1) + 友好报错，不碰任何真库。"""
    with pytest.raises(SystemExit) as e:
        restore_backup.verify_snapshot(tmp_path / "no_such_snapshot")
    assert e.value.code == 1
    assert "不存在" in capsys.readouterr().out


def test_restore_rejects_missing_db(tmp_path, capsys):
    """目录在但缺 sqlite.db → SystemExit(1)，说清快照目录应长什么样。"""
    d = tmp_path / "20260101_030000"
    d.mkdir()
    with pytest.raises(SystemExit):
        restore_backup.verify_snapshot(d)
    out = capsys.readouterr().out
    assert "缺主库文件" in out


def test_restore_rejects_corrupt_db(tmp_path, capsys):
    """sqlite.db 是垃圾字节 → integrity 拒绝，报「文件损坏」不碰真库。"""
    d = tmp_path / "20260101_030000"
    d.mkdir()
    (d / "sqlite.db").write_bytes(b"garbage not sqlite")
    with pytest.raises(SystemExit):
        restore_backup.verify_snapshot(d)
    out = capsys.readouterr().out
    assert "损坏" in out


def test_restore_dry_run_verifies_and_touches_nothing(env, tmp_path, monkeypatch, capsys):
    """dry-run：合法快照恢复到临时库校验通过；真库（注入的路径）零写入。"""
    db, cp, root = env
    snap = backup_full.make_backup(db, cp, root, today="20260101",
                                   now="20260102_030000")
    fake_real = tmp_path / "real_lib"
    fake_real.mkdir()
    monkeypatch.setattr(restore_backup, "DRILL_DIR", tmp_path / "drill")
    monkeypatch.setattr(restore_backup, "SQLITE_PATH", fake_real / "sqlite.db")
    monkeypatch.setattr(restore_backup, "CHECKPOINTS_PATH", fake_real / "checkpoints.sqlite")
    restore_backup.dry_run(snap)
    out = capsys.readouterr().out
    assert "integrity ok" in out
    assert "未动真库" in out
    assert list(fake_real.iterdir()) == []          # 真库目录零写入
    assert not (tmp_path / "drill").exists()          # 演练临时库已清
