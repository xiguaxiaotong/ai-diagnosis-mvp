"""打包项目（排除本地开发产物），产出 _deploy/app.tar.gz。

排除：node_modules / .next / .venv / __pycache__ / .git / 日志 / chroma、hf 大缓存。
保留：backend/data（sqlite + checkpoint，5.9MB，历史项目数据）、根 .env（API key）。
"""
import shutil
import tarfile
from pathlib import Path

ROOT = Path(r"d:/ai-diagnosis-mvp")
OUT = ROOT / "_deploy" / "app.tar.gz"

EXCLUDE_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "_deploy", "hf_cache"}
EXCLUDE_SUFFIX = (".log", ".pyc")
EXCLUDE_NAMES = {".env.local", "exported_image.png", "_memory_check1.py", "_memory_check2.py"}


def keep(p: Path) -> bool:
    if p.name in EXCLUDE_NAMES or p.suffix in EXCLUDE_SUFFIX:
        return False
    return not any(part in EXCLUDE_DIRS for part in p.parts)


def main() -> None:
    files = [
        p for p in ROOT.rglob("*")
        if p.is_file() and keep(p.relative_to(ROOT))
        # chroma 向量库与 embedding 模型缓存不带走（容器内会重建）
        and "backend\\data\\chroma" not in str(p)
        and "backend\\data\\hf" not in str(p)
        # torch wheel（187MB）服务器上已存在，不重复传（省 12 分钟上传）
        and "backend\\wheels" not in str(p)
    ]
    OUT.parent.mkdir(exist_ok=True)
    with tarfile.open(OUT, "w:gz") as tar:
        for p in files:
            tar.add(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
    size = OUT.stat().st_size / 1024 / 1024
    print(f"打包完成: {OUT}  {size:.1f} MB  共 {len(files)} 个文件")


if __name__ == "__main__":
    main()
