"""W7 Day7 回归 runner：现有 5 个进程内测试脚本 + 独立测试库。

不碰 backend/data 主库（每个脚本一个独立 temp 目录），
也不需要 uvicorn :8000 / LLM key（这些脚本全部自带 stub）。

用法（在 backend/ 下）：
    python scripts/run_regression.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

SCRIPTS = [
    "test_intent_classify.py",      # 意图分流规则（纯函数）
    "test_confirm_fix.py",         # 确认循环收尾（stub LLM）
    # 注：test_budget_constraint.py 场景4 为存量失败，按指示未修
    # （现象/判断/处理选项见 backend/docs/TODO.md T-1），跑出来 ✗ 是预期
    "test_budget_constraint.py",   # 预算约束（stub LLM）
    "test_consult_graph.py",       # 咨询分流图（stub LLM）
    "test_consult_confirm_stage.py",  # 咨询+确认衔接（stub LLM）
]


def run_one(script: str) -> bool:
    tmp = Path(tempfile.mkdtemp(prefix=f"regr_{script[:12]}_"))
    env = dict(os.environ)
    env.update({
        "SQLITE_PATH": str(tmp / "sqlite.db"),
        "CHROMA_DIR": str(tmp / "chroma"),
        "CASES_DIR": str(tmp / "cases"),
        "CHECKPOINTS_PATH": str(tmp / "checkpoints.sqlite"),
    })
    # 引导：先在独立库上跑迁移建表（部分脚本假设库已初始化，主库场景下靠的是
    # 历史遗留表结构；独立库必须先 init）
    boot = subprocess.run(
        [PYTHON, "-c", "from app.db.database import init_db; init_db()"],
        cwd=str(BACKEND), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    if boot.returncode != 0:
        print(f"✗ {script}  (init_db 引导失败)")
        for line in boot.stderr.splitlines()[-10:]:
            print(" ", line)
        return False
    p = subprocess.run(
        [PYTHON, str(BACKEND / "scripts" / script)], cwd=str(BACKEND), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )
    ok = p.returncode == 0
    print(f"{'✓' if ok else '✗'} {script}  (exit={p.returncode})")
    # 失败时给全量输出方便定位
    if not ok:
        print("  ---- stdout ----")
        for line in p.stdout.splitlines()[-30:]:
            print(" ", line)
        print("  ---- stderr ----")
        for line in p.stderr.splitlines()[-15:]:
            print(" ", line)
    return ok


def main():
    results = {s: run_one(s) for s in SCRIPTS}
    n_ok = sum(results.values())
    print(f"\n{'='*50}")
    print(f"回归：{n_ok}/{len(SCRIPTS)} 通过（独立测试库，主库零写入）")
    for s, ok in results.items():
        print(f"  {'✓' if ok else '✗'} {s}")
    return 0 if n_ok == len(SCRIPTS) else 1


if __name__ == "__main__":
    sys.exit(main())
