"""全局配置：API key、模型名、路径。

Day2 (P5)：DeepSeek 对话模型 + bge-small 本地 Embedding 配置。
环境变量统一从项目根目录 .env 读取。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ 目录（data 等本地数据都挂在这里）
BASE_DIR = Path(__file__).resolve().parent.parent
# 项目根目录（.env 所在位置）
ROOT_DIR = BASE_DIR.parent

# 加载根目录 .env（不存在则跳过，走默认值）
load_dotenv(ROOT_DIR / ".env")

# ---------- 本地数据路径 ----------
# W7 Day7：四个路径全部支持 env 覆盖（测试隔离用——测试脚本设临时目录，
# 不污染 backend/data 主库；生产不设 env 即走默认值，行为不变）
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = Path(os.getenv("CHROMA_DIR") or (DATA_DIR / "chroma"))
CASES_DIR = Path(os.getenv("CASES_DIR") or (DATA_DIR / "cases"))
SQLITE_PATH = Path(os.getenv("SQLITE_PATH") or (DATA_DIR / "sqlite.db"))
CHECKPOINTS_PATH = Path(os.getenv("CHECKPOINTS_PATH") or (DATA_DIR / "checkpoints.sqlite"))
# W8 Day1：节点级 trace 落盘路径（追加写 JSONL）。env 覆盖供测试隔离。
TRACE_PATH = Path(os.getenv("TRACE_PATH") or (BASE_DIR / "logs" / "trace.jsonl"))

# ---------- 对话模型（DeepSeek，OpenAI 兼容协议） ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-chat")
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.7"))
CHAT_TIMEOUT = float(os.getenv("CHAT_TIMEOUT", "60"))
# W8 Day2：DeepSeek 计费单价（元 / 1M tokens，成本估算用；调价只改 .env 不动代码）
# 默认值对齐 deepseek-chat 2025 官方刊例价（输入 2 / 输出 3），仅估非结算
DEEPSEEK_PRICE_PROMPT = float(os.getenv("DEEPSEEK_PRICE_PROMPT", "2.0"))
DEEPSEEK_PRICE_COMPLETION = float(os.getenv("DEEPSEEK_PRICE_COMPLETION", "3.0"))

# ---------- Embedding 模型（bge-small 本地加载，无需 key） ----------
# 中文小模型，512 维，约 100MB
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
# HuggingFace 镜像（国内访问用）
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

# ---------- 服务 ----------
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# 前端来源（CORS）
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# ---------- W7 Day1：密码重置 / 邮件 ----------
# BASE_URL：所有邮件链接的前缀（重置密码、邀请等统一来源）
#   本地 dev 默认 http://localhost:3000；云上改为公网域名 + HTTPS
BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")
# 邮件后端：console / tencent / aliyun / smtp。MVP 仅实现 console。
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "console")


def _parse_admin_user_ids() -> set[int]:
    """W7 Day5：运营后台白名单。
    env: ADMIN_USER_IDS=1,2,3
    默认空集合 = 没人是运营；通过 SQL 查 user.id 后回填即可。
    """
    raw = os.getenv("ADMIN_USER_IDS", "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


# ---------- W7 Day5：运营后台 admin 白名单 ----------
ADMIN_USER_IDS: set[int] = _parse_admin_user_ids()
