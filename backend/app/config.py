"""全局配置：API key、模型名、路径（W9 热身：pydantic-settings 收编）。

演进史：
- Day2 (P5)：DeepSeek 对话模型 + bge-small 本地 Embedding，.env 从项目根读取
- W7 Day5/W8：散落的 os.getenv 逐个加进来（admin 白名单、单价、trace 路径…）
- W9 热身：全部收编进 Settings(BaseSettings) 统一管理——
  * 单一来源：字段即文档，默认值/类型一目了然
  * .env 与真实环境变量都支持（环境变量优先，与原 load_dotenv 语义一致：
    load_dotenv 不覆盖已有 env，pydantic-settings 也是 env > env_file）
  * 12 个模块 `from app.config import XXX` 的老用法零改动——
    模块底部用 settings 单例一次性导出同名常量（兼容层，禁止新代码直接
    改常量，一律走 settings / .env）

注意：HF_ENDPOINT 仍需 load_dotenv 写入 os.environ（sentence-transformers
读的是系统环境变量，不走本模块），故保留 load_dotenv 调用。
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（data 等本地数据都挂在这里）
BASE_DIR = Path(__file__).resolve().parent.parent
# 项目根目录（.env 所在位置）
ROOT_DIR = BASE_DIR.parent

# 加载根目录 .env（不覆盖已有环境变量；供 HF 等第三方库读 os.environ 用）
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    """全部配置项（字段名 = 环境变量名，大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env 里允许出现本类未收录的第三方变量（如 HF_HUB_OFFLINE）
    )

    # ---------- 本地数据路径（None = 走默认；测试隔离时设临时目录） ----------
    CHROMA_DIR: Path | None = None
    CASES_DIR: Path | None = None
    SQLITE_PATH: Path | None = None
    CHECKPOINTS_PATH: Path | None = None
    # W8 Day1：节点级 trace 落盘路径（追加写 JSONL）
    TRACE_PATH: Path | None = None

    # ---------- 对话模型（DeepSeek，OpenAI 兼容协议） ----------
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    CHAT_MODEL: str = "deepseek-chat"
    CHAT_TEMPERATURE: float = 0.7
    CHAT_TIMEOUT: float = 60.0
    # W8 Day2：计费单价（元 / 1M tokens，成本估算用；调价只改 .env 不动代码）
    # 默认值对齐 deepseek-chat 2025 官方刊例价（输入 2 / 输出 3），仅估非结算
    DEEPSEEK_PRICE_PROMPT: float = 2.0
    DEEPSEEK_PRICE_COMPLETION: float = 3.0

    # ---------- Embedding 模型（bge-small 本地加载，无需 key） ----------
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-zh-v1.5"
    EMBEDDING_DEVICE: str = "cpu"
    HF_ENDPOINT: str = "https://hf-mirror.com"

    # ---------- 服务 ----------
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    # 前端来源（CORS）
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # ---------- W7 Day1：密码重置 / 邮件 ----------
    # BASE_URL：所有邮件链接的前缀；本地 dev 默认前端地址，云上改公网域名 + HTTPS
    BASE_URL: str = "http://localhost:3000"
    # 邮件后端：console / tencent / aliyun / smtp。MVP 仅实现 console。
    EMAIL_BACKEND: str = "console"

    # ---------- W7 Day5：运营后台 admin 白名单 ----------
    # 逗号分隔 user.id；默认空 = 没人是运营；查 user.id 后回填
    ADMIN_USER_IDS: str = ""

    @model_validator(mode="after")
    def _fill_default_paths(self) -> "Settings":
        """路径默认值在验证后填充（默认值依赖 DATA_DIR，写死在字段默认里做不到）。"""
        data_dir = BASE_DIR / "data"
        if self.CHROMA_DIR is None:
            self.CHROMA_DIR = data_dir / "chroma"
        if self.CASES_DIR is None:
            self.CASES_DIR = data_dir / "cases"
        if self.SQLITE_PATH is None:
            self.SQLITE_PATH = data_dir / "sqlite.db"
        if self.CHECKPOINTS_PATH is None:
            self.CHECKPOINTS_PATH = data_dir / "checkpoints.sqlite"
        if self.TRACE_PATH is None:
            self.TRACE_PATH = BASE_DIR / "logs" / "trace.jsonl"
        return self

    @property
    def admin_user_ids(self) -> set[int]:
        """ADMIN_USER_IDS 环境变量 → user.id 集合（非法 token 静默跳过）。"""
        out: set[int] = set()
        for tok in self.ADMIN_USER_IDS.split(","):
            tok = tok.strip()
            if tok.isdigit():
                out.add(int(tok))
        return out


settings = Settings()

# ---------- 兼容层：老代码 `from app.config import XXX` 零改动 ----------
# 新代码建议直接 from app.config import settings。
# `or` 兜底是给 mypy 看的：validator 已保证非 None，运行时永远走 settings 值。
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR: Path = settings.CHROMA_DIR or (DATA_DIR / "chroma")
CASES_DIR: Path = settings.CASES_DIR or (DATA_DIR / "cases")
SQLITE_PATH: Path = settings.SQLITE_PATH or (DATA_DIR / "sqlite.db")
CHECKPOINTS_PATH: Path = settings.CHECKPOINTS_PATH or (DATA_DIR / "checkpoints.sqlite")
TRACE_PATH: Path = settings.TRACE_PATH or (BASE_DIR / "logs" / "trace.jsonl")

DEEPSEEK_API_KEY: str = settings.DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL: str = settings.DEEPSEEK_BASE_URL
CHAT_MODEL: str = settings.CHAT_MODEL
CHAT_TEMPERATURE: float = settings.CHAT_TEMPERATURE
CHAT_TIMEOUT: float = settings.CHAT_TIMEOUT
DEEPSEEK_PRICE_PROMPT: float = settings.DEEPSEEK_PRICE_PROMPT
DEEPSEEK_PRICE_COMPLETION: float = settings.DEEPSEEK_PRICE_COMPLETION

EMBEDDING_MODEL_NAME: str = settings.EMBEDDING_MODEL_NAME
EMBEDDING_DEVICE: str = settings.EMBEDDING_DEVICE
HF_ENDPOINT: str = settings.HF_ENDPOINT

BACKEND_HOST: str = settings.BACKEND_HOST
BACKEND_PORT: int = settings.BACKEND_PORT
FRONTEND_ORIGIN: str = settings.FRONTEND_ORIGIN
BASE_URL: str = settings.BASE_URL
EMAIL_BACKEND: str = settings.EMAIL_BACKEND

# W7 Day5：运营后台白名单（set[int]）
ADMIN_USER_IDS: set[int] = settings.admin_user_ids
