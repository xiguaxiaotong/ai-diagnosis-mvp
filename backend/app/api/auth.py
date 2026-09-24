"""Day4 账户系统：注册 / 登录 / 会话鉴权。

MVP 设计（零新依赖）：
- 密码：hashlib.pbkdf2_hmac（sha256，12 万迭代，16 字节 salt）——标准库，
  不引 bcrypt/passlib（服务器 2C4G 装依赖又是一场灾难）
- 会话：secrets.token_urlsafe(32) 存 auth_sessions 表，30 天过期，
  重启不丢（Day3 验收「重启不丢数据」）——不上 JWT 库
- 项目隔离：project.user_id 归属；user_id IS NULL 的旧项目（匿名期创建）
  在第一个用户注册时自动继承，避免历史数据变「孤儿」
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AuthSession, Project, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_DAYS = 30
_PBKDF2_ITERATIONS = 120_000


# ---------- 密码哈希（标准库 pbkdf2） ----------


def _hash_password(password: str) -> str:
    """格式：pbkdf2_sha256$迭代$salt_hex$hash_hex（自校验格式，可升级迭代数）。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return secrets.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


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
    return {"id": user.id, "username": user.username, "name": user.name, "is_guest": user.username is None}


# ---------- 接口 ----------


class AuthBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)


@router.post("/register", status_code=201)
def register(body: AuthBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    """注册。第一个注册用户自动继承所有匿名期创建的旧项目（user_id IS NULL）。"""
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
def login(body: AuthBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if user is None or not user.password_hash or not _verify_password(body.password, user.password_hash):
        # 统一报错文案，不区分「用户不存在/密码错」，防用户名枚举
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = _create_session(db, user.id)
    return {"token": token, "user": _user_payload(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": _user_payload(user)}


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
