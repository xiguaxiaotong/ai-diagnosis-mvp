"""邮件发送服务（W7 Day1）。

MVP 设计：
- 本地 dev：直接 print 到后端日志，方便复制链接手测（不污染收件箱）
- 云上：按 EMAIL_BACKEND 选择后端
  - console（默认，与 dev 同）：仅打印
  - tencent / aliyun：腾讯云 / 阿里云邮件推送 API（按官方 SDK 异步 POST）
  - smtp：通用 SMTP 兜底（自建邮局 / Mailgun / SendGrid）

切换规则：仅云上 `EMAIL_BACKEND != console` 才走真实发送。
BASE_URL：所有邮件里的链接都以它为前缀（重置链接 / 分享链接统一来源）。
"""
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailBackend(Protocol):
    def send(self, *, to: str, subject: str, html: str, text: str) -> None: ...


class ConsoleBackend:
    """本地 dev 后端：日志打印邮件正文（链接可直接复制手测）。"""

    def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        # 显眼分隔，方便从日志里 grep；同时 print 一份到 stdout（logger 在 uvicorn
        # 重定向下未必能稳定输出，print 直击最稳）
        banner = "=" * 60
        for line in [banner, f"[邮件/Console] → {to} | 主题: {subject}",
                     "[邮件/正文/Text]", text, banner]:
            print(line)
            logger.info(line)


def get_email_backend() -> EmailBackend:
    """按 EMAIL_BACKEND 选后端。MVP 阶段只实现 console，其它留 TODO。"""
    from app.config import EMAIL_BACKEND

    if EMAIL_BACKEND == "console":
        return ConsoleBackend()
    # TODO: 加 tencent / aliyun / smtp 后端（云上接真实发送时再实现）
    raise NotImplementedError(
        f"EMAIL_BACKEND={EMAIL_BACKEND!r} 尚未实现，先用 console"
    )


def send_password_reset(*, to_email: str, reset_url: str, ttl_minutes: int = 30) -> None:
    """发送重置密码邮件。"""
    subject = "重置你的密码"
    text = (
        f"你正在重置密码。\n"
        f"\n"
        f"请点击下方链接（{ttl_minutes} 分钟内有效，单次使用）：\n"
        f"{reset_url}\n"
        f"\n"
        f"如果不是你本人的操作，请忽略本邮件。\n"
    )
    html = (
        f"<p>你正在重置密码。</p>"
        f'<p><a href="{reset_url}">点这里重置密码</a>'
        f"（{ttl_minutes} 分钟内有效，单次使用）。</p>"
        f"<p>如果不是你本人的操作，请忽略本邮件。</p>"
    )
    get_email_backend().send(to=to_email, subject=subject, html=html, text=text)