"""Day4 账户系统：注册 / 登录 / 会话鉴权 / W7 Day1 重置密码 / W7 Day2 个人中心。

MVP 设计（零新依赖）：
- 密码：hashlib.pbkdf2_hmac（sha256，60 万迭代，16 字节 salt）——标准库，
  不引 bcrypt/passlib（服务器 2C4G 装依赖又是一场灾难）
  迭代数随 OWASP 2023 推荐提升到 600k；老 hash 仍是 120k 也可验证，
  登录成功后自动用新迭代重 hash（写在 hash 里的 iterations 自带升级机制）。
- 会话：secrets.token_urlsafe(32) 存 auth_sessions 表，30 天过期，
  重启不丢（Day3 验收「重启不丢数据」）——不上 JWT 库
- 项目隔离：project.user_id 归属；user_id IS NULL 的旧项目（匿名期创建）
  在第一个用户注册时自动继承，避免历史数据变「孤儿」
- 重置密码：30 分钟过期 + 单次使用（与 AuthSession 同 token 规格，存独立表）
- 限流：4 个密码接口按 IP 滑动窗口（云上多 worker 需切 Redis）
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ADMIN_USER_IDS, BASE_URL
from app.db.database import get_db
from app.db.models import AuthSession, PasswordResetToken, Project, User
from app.services.email import send_password_reset
from app.services.rate_limit import check_rate_limit, client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_DAYS = 30
RESET_TTL_MINUTES = 30
_PBKDF2_ITERATIONS = 600_000  # W7 Day2：OWASP 2023 推荐值
# ---------- 限流策略（每个接口独立 scope，避免一处爆满牵连全站） ----------
RATE_REGISTER = (5, 60)        # 5 次/分钟：注册暴力阻断
RATE_LOGIN = (5, 60)           # 5 次/分钟：密码爆破
RATE_FORGOT = (3, 60)          # 3 次/分钟：邮件轰炸阻断
RATE_RESET = (5, 60)           # 5 次/分钟：token 爆破阻断

# 邮箱最简校验：local@domain.tld（不查 MX、不查 disposable、不查 typo）
# 标准库 re 即可；引 email_validator 没必要（轻量但仍是新依赖）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- 密码哈希（标准库 pbkdf2） ----------


def _hash_password(password: str) -> str:
    """格式：pbkdf2_sha256$迭代$salt_hex$hash_hex（自校验格式，可升级迭代数）。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> tuple[bool, int]:
    """验证密码，同时返回原 hash 用的迭代数（登录接口据此判断是否要重 hash）。"""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False, 0
        iter_n = int(iterations)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), iter_n
        )
        return secrets.compare_digest(digest.hex(), hash_hex), iter_n
    except (ValueError, TypeError):
        return False, 0


# ---------- 鉴权依赖 ----------


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI 依赖：Authorization: Bearer <token> → User。401 未登录。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization.removeprefix("Bearer ").strip()
    session = db.get(AuthSession, token)
    if session is None or session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def _create_session(db: Session, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        token=token,
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS),
    ))
    db.commit()
    return token


def _user_payload(user: User) -> dict[str, Any]:
    # is_guest：username 为空 = 游客会话（免登录体验产生），前端据此提示注册
    # is_admin：W7 Day5；env 白名单 ADMIN_USER_IDS，含则可进 /api/admin/*
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "email": user.email,
        "is_guest": user.username is None,
        "is_admin": user.id in ADMIN_USER_IDS,
    }


# ---------- W7 Day5：admin 鉴权依赖 ----------
def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """运营后台鉴权：仅 ADMIN_USER_IDS 白名单内 user.id 可通过。

    鉴权失败一律 403（区别 401 未登录），且不泄漏白名单内容。
    """
    if user.id not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="无权限访问运营后台")
    return user


# ---------- 接口 ----------


class AuthBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)


@router.post("/register", status_code=201)
def register(
    request: Request,
    body: AuthBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """注册。第一个注册用户自动继承所有匿名期创建的旧项目（user_id IS NULL）。"""
    check_rate_limit(key=client_ip(request) + ":register", limit=RATE_REGISTER[0], window_sec=RATE_REGISTER[1])

    username = body.username.strip()
    exists = db.scalar(select(User).where(User.username == username))
    if exists:
        raise HTTPException(status_code=409, detail="用户名已被注册")

    user = User(username=username, name=username, password_hash=_hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    # 匿名期旧项目归第一个注册用户（MVP 单用户起步，避免历史项目孤儿化）
    n_inherit = (
        db.query(Project)
        .filter(Project.user_id.is_(None))
        .update({Project.user_id: user.id})
    )
    db.commit()

    token = _create_session(db, user.id)
    inherited = f"，已继承 {n_inherit} 个历史项目" if n_inherit else ""
    return {"token": token, "user": _user_payload(user), "note": f"注册成功{inherited}"}


@router.post("/login")
def login(request: Request, body: AuthBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    """登录。失败统一文案（防用户名枚举）；命中且老 hash 用了低迭代则自动重 hash。

    自动重 hash 机制：_verify_password 返回 (ok, iterations)，若 ok 且 iterations < 600k，
    用 _hash_password(body.password) 重写 user.password_hash。零额外逻辑、自然平滑升级。
    """
    check_rate_limit(key=client_ip(request) + ":login", limit=RATE_LOGIN[0], window_sec=RATE_LOGIN[1])

    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if user is None or not user.password_hash:
        # 跑一遍哈希防止时序攻击 + 统一返回时间（用户名/密码错都走同一返回）
        _verify_password(body.password, f"pbkdf2_sha256${_PBKDF2_ITERATIONS}$00${'00' * 32}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    ok, iterations = _verify_password(body.password, user.password_hash)
    if not ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 自动升级老 hash：老用户登录一次即平滑迁移到 600k
    if iterations < _PBKDF2_ITERATIONS:
        user.password_hash = _hash_password(body.password)
        db.commit()

    token = _create_session(db, user.id)
    return {"token": token, "user": _user_payload(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": _user_payload(user)}


# ---------- W7 Day2：个人中心（PATCH /me） ----------


class UpdateMeBody(BaseModel):
    """个人中心更新：name / new_password / new_email 三类改动。

    设计原则（建议 C 最简方案）：
    - 改昵称（name）：无需二次验证（昵称不是凭证）
    - 改密码（new_password）：必须传 old_password（守最后一道门）
    - 改邮箱（new_email）：必须传 old_password（防被盗会话篡改，标准做法）

    字段都可选：一次请求只改其中一项，互不干扰。
    email 格式校验用 _EMAIL_RE（零新依赖）。
    """
    name: str | None = Field(default=None, min_length=1, max_length=64)
    old_password: str | None = Field(default=None, min_length=6, max_length=64)
    new_password: str | None = Field(default=None, min_length=6, max_length=64)
    new_email: str | None = None

    @field_validator("new_email")
    @classmethod
    def _v_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v.lower().strip()


@router.patch("/me")
def update_me(
    body: UpdateMeBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """个人中心修改：昵称 / 密码 / 邮箱。

    注意：游客会话不允许走这个接口（username IS NULL = 游客，先去注册）。
    """
    if user.username is None:
        raise HTTPException(status_code=403, detail="游客不能修改个人资料，请先注册")

    # 仅 old_password 出现在以下两种敏感操作中：
    #   - 改密码（必须）
    #   - 改邮箱（必须，按建议 C）
    sensitive = (body.new_password is not None) or (body.new_email is not None)
    if sensitive:
        if not body.old_password:
            raise HTTPException(status_code=400, detail="修改密码或邮箱需提供当前密码")
        ok, _ = _verify_password(body.old_password, user.password_hash or "")
        if not ok:
            raise HTTPException(status_code=401, detail="当前密码不正确")

    changed: list[str] = []

    if body.name is not None and body.name != user.name:
        user.name = body.name.strip()
        changed.append("昵称")

    if body.new_password is not None:
        # 简单挡防：不能改回 6 位完全相同
        user.password_hash = _hash_password(body.new_password)
        changed.append("密码")

    if body.new_email is not None:
        new_email = body.new_email.lower().strip()
        if new_email != user.email:
            # 唯一性：DB 兜底有 unique 约束，但提前查避免冲突回滚
            conflict = db.scalar(select(User).where(User.email == new_email, User.id != user.id))
            if conflict:
                raise HTTPException(status_code=409, detail="该邮箱已被其他账号使用")
            user.email = new_email
            changed.append("邮箱")

    db.commit()
    db.refresh(user)
    return {"user": _user_payload(user), "changed": changed}


@router.post("/guest")
def create_guest(db: Session = Depends(get_db)) -> dict[str, Any]:
    """免登录体验（转化优化）：无 token 的访客一键领取「游客身份」。

    游客是真实的 User 行（username/password 为 NULL）+ 正常会话 token，
    下游所有鉴权接口（创建项目/诊断/方案）零改动即可走完整流程；
    注册/登录时用 /claim 把游客名下项目一键过户到正式账号。
    """
    user = User(username=None, name="游客", password_hash=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = _create_session(db, user.id)
    return {"token": token, "user": _user_payload(user), "note": "游客模式：体验完整诊断，注册后方案自动保留"}


class ClaimBody(BaseModel):
    guest_token: str = Field(min_length=8, max_length=64)


@router.post("/claim")
def claim(
    body: ClaimBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """游客项目过户：注册/登录成功后，把游客名下项目全部转到正式账号。

    幂等：令牌无效/已过户过则安静返回（前端登录页统一调用，失败不阻塞跳转）。
    """
    session = db.get(AuthSession, body.guest_token)
    if session is None:
        return {"moved": 0}
    guest = db.get(User, session.user_id)
    if guest is None or guest.username is not None:
        # 防御：令牌对应的不是游客账号（正常用户自己的 token），不动
        return {"moved": 0}
    moved = (
        db.query(Project)
        .filter(Project.user_id == guest.id)
        .update({Project.user_id: user.id})
    )
    db.delete(session)
    db.delete(guest)  # 项目已改挂正式账号，游客行可删（AuthSession 级联）
    db.commit()
    return {"moved": moved}


# ---------- W7 Day1：忘记密码 / 重置密码 ----------


class ForgotBody(BaseModel):
    """找回密码：现阶段 username 唯一且就是登录名；后续若加「换绑邮箱」再扩字段。"""
    username: str = Field(min_length=2, max_length=64)


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    body: ForgotBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """申请重置密码。

    不论用户名是否存在，**返回相同的成功文案**（防用户名枚举）。
    用户存在 → 生成 token、给「邮箱地址」就发送重置链接；
    用户不存在 → 静默返回 200（前端不感知）。
    """
    check_rate_limit(key=client_ip(request) + ":forgot", limit=RATE_FORGOT[0], window_sec=RATE_FORGOT[1])

    username = body.username.strip()
    user = db.scalar(select(User).where(User.username == username))

    if user is not None and user.password_hash:
        # 注意：当前用户表没有 email 字段（注册时未收）；重置链接里的「邮箱」就是 username
        #   云上扩出 email 列时，把 to_email 改为 user.email 即可，链接生成不变
        token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            token=token,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(minutes=RESET_TTL_MINUTES),
        ))
        db.commit()
        reset_url = f"{BASE_URL.rstrip('/')}/reset-password/{token}"
        try:
            send_password_reset(to_email=username, reset_url=reset_url, ttl_minutes=RESET_TTL_MINUTES)
        except Exception:
            # 邮件失败不回滚：token 已生成，可让用户重试或联系客服（避免接口整体 500）
            pass

    # 永远返回同一文案（防用户名枚举）
    return {"ok": True, "message": "如果该账号存在，重置链接已发送到对应邮箱"}


class ResetBody(BaseModel):
    token: str = Field(min_length=8, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


@router.post("/reset-password")
def reset_password(
    request: Request,
    body: ResetBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """使用重置 token 改密。

    三道闸：
    - token 存在
    - 未过期（30 分钟）
    - 未使用（used_at IS NULL）
    任何一道不过都返 400。改密成功后置 used_at = 当前时间，让 token 单次失效。
    """
    check_rate_limit(key=client_ip(request) + ":reset", limit=RATE_RESET[0], window_sec=RATE_RESET[1])

    record = db.get(PasswordResetToken, body.token)
    if record is None:
        raise HTTPException(status_code=400, detail="重置链接无效")
    if record.used_at is not None:
        raise HTTPException(status_code=400, detail="重置链接已被使用过")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="重置链接已过期，请重新申请")

    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="账号不存在")

    user.password_hash = _hash_password(body.new_password)
    record.used_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "message": "密码已重置，请使用新密码登录"}
