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
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma"
CASES_DIR = DATA_DIR / "cases"
SQLITE_PATH = DATA_DIR / "sqlite.db"

# ---------- 对话模型（DeepSeek，OpenAI 兼容协议） ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-chat")
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.7"))
CHAT_TIMEOUT = float(os.getenv("CHAT_TIMEOUT", "60"))

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
