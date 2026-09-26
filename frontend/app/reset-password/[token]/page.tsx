"use client";

import { useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "../../../lib/api";
import { useTheme } from "../../../lib/theme";
import { font, radius, space, touch } from "../../../lib/tokens";

/** 重置密码页：从邮件链接进来（/reset-password/<token>）。
 *
 * 流程：
 * - URL 拿 token → 输入新密码 + 确认
 * - 调 POST /api/auth/reset-password
 * - 成功 → 提示「去登录」+ 跳 /login
 * - 失败（token 无效/过期/已用）→ 红色错误，按钮换成「重新申请」跳登录页
 */
function ResetForm() {
  const { colors, borderStyle } = useTheme();
  const router = useRouter();
  // token 从路径里取（Next App Router 的动态段）
  // 注：这是客户端组件，用 window.location 取更可靠；服务端组件才用 params
  const [token, setToken] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const segs = window.location.pathname.split("/").filter(Boolean);
    setToken(segs[segs.length - 1] || null);
  }, []);

  const invalidTokenReason = !token
    ? "链接无效（缺少令牌）"
    : token.length < 8
      ? "链接无效（令牌格式错误）"
      : null;

  async function submit() {
    setError(null);
    if (invalidTokenReason) return;
    if (password.length < 6) { setError("新密码至少 6 位"); return; }
    if (password !== confirm) { setError("两次输入的密码不一致"); return; }
    setBusy(true);
    try {
      await api("/api/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      setDone(true);
      // 5 秒后跳登录；给用户看「已重置」+「去登录」按钮
      setTimeout(() => router.replace("/login"), 5000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重置失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  const inputStyle = {
    width: "100%",
    minHeight: touch.large,
    padding: `0 ${space.lg}px`,
    background: colors.bg.surface,
    color: colors.text.primary,
    border: `1px solid ${colors.border.default}`,
    borderRadius: radius.md,
    fontSize: font.base,
    outline: "none",
  } as const;

  return (
    <main style={{ maxWidth: 400, margin: `${space.pageTop}px auto`, padding: `0 ${space.xl}px` }}>
      <h1 style={{ textAlign: "center" }}>重置密码</h1>
      <p style={{
        color: colors.text.secondary, fontSize: font.sm, textAlign: "center", marginTop: 0,
      }}>
        {done ? "密码已重置，请使用新密码登录" : "设置一个新的登录密码"}
      </p>

      {/* 重置成功态 */}
      {done ? (
        <div style={{
          background: colors.status.successBg,
          border: `1px solid ${colors.status.successBorder}`,
          borderRadius: radius.md,
          padding: `${space.md}px ${space.lg}px`,
          marginTop: space.lg,
        }}>
          <p style={{ margin: 0, fontSize: font.base, color: colors.status.successStrong }}>
            密码已重置成功
          </p>
          <p style={{ margin: `${space.sm}px 0 0`, fontSize: font.sm, color: colors.text.secondary }}>
            5 秒后自动跳到登录页…
          </p>
          <button
            onClick={() => router.replace("/login")}
            style={{
              marginTop: space.md,
              minHeight: touch.large,
              padding: `0 ${space.xl}px`,
              background: colors.brand.primary,
              color: colors.text.inverse,
              border: "none", borderRadius: radius.md,
              fontSize: font.base, fontWeight: 600, cursor: "pointer",
              width: "100%",
            }}
          >
            立即去登录
          </button>
        </div>
      ) : (
        /* 输入态 */
        <div style={{ display: "flex", flexDirection: "column", gap: space.md, marginTop: space.lg }}>
          {invalidTokenReason && (
            <p style={{
              color: colors.status.danger, background: colors.status.dangerBg,
              border: `1px solid ${colors.status.danger}44`, borderRadius: radius.md,
              padding: `${space.md}px ${space.lg}px`, fontSize: font.sm, margin: 0,
            }}>
              {invalidTokenReason}
            </p>
          )}

          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
            placeholder="新密码（至少 6 位）"
            autoComplete="new-password"
            disabled={Boolean(invalidTokenReason)}
            style={inputStyle}
          />
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
            placeholder="再次输入新密码"
            autoComplete="new-password"
            disabled={Boolean(invalidTokenReason)}
            style={inputStyle}
          />

          {error && (
            <p style={{
              color: colors.status.danger, background: colors.status.dangerBg,
              border: `1px solid ${colors.status.danger}44`, borderRadius: radius.md,
              padding: `${space.md}px ${space.lg}px`, fontSize: font.sm, margin: 0,
            }}>
              {error}
            </p>
          )}

          <button
            onClick={submit}
            disabled={busy || Boolean(invalidTokenReason)}
            style={{
              minHeight: touch.large,
              background: busy || invalidTokenReason ? colors.muted.bg : colors.brand.primary,
              color: colors.text.inverse,
              border: "none", borderRadius: radius.md,
              fontSize: font.base, fontWeight: 600,
              cursor: busy || invalidTokenReason ? "not-allowed" : "pointer",
              marginTop: space.sm,
            }}
          >
            {busy ? "请稍候…" : "重置密码"}
          </button>

          {error && /无效|过期|已被使用/.test(error) && (
            <button
              onClick={() => router.replace("/login")}
              style={{
                minHeight: touch.small,
                background: "transparent",
                color: colors.brand.linkText,
                border: "none",
                fontSize: font.sm, cursor: "pointer",
                marginTop: space.xs,
              }}
            >
              ← 重新申请重置链接
            </button>
          )}
        </div>
      )}

      <p style={{
        color: colors.text.tertiary, fontSize: font.xs,
        textAlign: "center", marginTop: space.xxl,
        borderTop: borderStyle.card, paddingTop: space.lg,
      }}>
        重置链接 30 分钟内有效，单次使用后即失效
      </p>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetForm />
    </Suspense>
  );
}