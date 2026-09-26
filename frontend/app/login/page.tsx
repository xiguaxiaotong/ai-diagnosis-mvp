"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { AuthUser, isGuest, popGuestToken, saveSession } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { font, radius, space, touch } from "../../lib/tokens";

/** 已登录则直接进首页（刷新 /login 不再看表单）。
 *  游客例外：游客有 token 但来这儿就是为了注册，不能被踢回去。 */
function useRedirectIfAuthed() {
  const router = useRouter();
  useEffect(() => {
    if (localStorage.getItem("diag_token") && !isGuest()) router.replace("/");
  }, [router]);
}

function LoginForm() {
  const { colors, borderStyle } = useTheme();
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // W7 Day1：忘记密码子状态机
  // - 'login' 默认登录表单
  // - 'forgot' 输入用户名提交「忘记密码」，显示「已发送邮件」提示
  type Stage = "login" | "forgot" | "forgot-sent";
  const [stage, setStage] = useState<Stage>("login");

  useRedirectIfAuthed();

  async function submit() {
    const u = username.trim();
    if (u.length < 2 || password.length < 6) {
      setError("用户名至少 2 个字符，密码至少 6 位");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ token: string; user: AuthUser; note?: string }>(
        `/api/auth/${mode}`,
        {
          method: "POST",
          body: JSON.stringify({ username: u, password }),
        },
      );
      saveSession(data.token, data.user);
      // 游客项目过户：把游客名下项目全部转到刚登录的正式账号（失败不阻塞跳转）
      const guestToken = popGuestToken();
      if (guestToken) {
        try {
          await api("/api/auth/claim", {
            method: "POST",
            body: JSON.stringify({ guest_token: guestToken }),
          });
        } catch {
          /* 过户失败不影响登录本身 */
        }
      }
      if (data.note) setNote(data.note);
      router.replace(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function submitForgot() {
    const u = username.trim();
    if (u.length < 2) { setError("请输入你的用户名"); return; }
    setBusy(true); setError(null);
    try {
      await api("/api/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ username: u }),
      });
      // 不论用户名是否存在都返回 200（防枚举），但前端只在确实拿到 ok 时切到「已发送」
      setStage("forgot-sent");
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败，请重试");
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
      <h1 style={{ textAlign: "center" }}>
        {stage === "forgot" || stage === "forgot-sent"
          ? "找回密码"
          : mode === "login" ? "登录" : "注册"}
      </h1>
      <p style={{ color: colors.text.secondary, fontSize: font.sm, textAlign: "center", marginTop: 0 }}>
        {stage === "forgot"
          ? "输入用户名，我们会发送重置链接"
          : stage === "forgot-sent"
            ? "请查收邮箱，按邮件里的链接完成重置"
            : mode === "login" ? "登录后继续你的项目" : "创建账户，方案和项目只属于你"}
      </p>

      {/* 登录 / 注册切换（忘记密码时不显示） */}
      {stage === "login" && (
        <div style={{
          display: "flex", gap: space.sm, marginBottom: space.xl,
          background: colors.bg.muted, borderRadius: radius.md, padding: space.xs,
        }}>
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setError(null); }}
              style={{
                flex: 1, minHeight: touch.small,
                background: mode === m ? colors.brand.primary : "transparent",
                color: mode === m ? colors.text.inverse : colors.text.secondary,
                border: "none", borderRadius: radius.sm,
                fontSize: font.base, cursor: "pointer",
              }}
            >
              {m === "login" ? "登录" : "注册"}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
        {/* 忘记密码流程：只显示一个用户名输入框 */}
        {(stage === "forgot" || stage === "forgot-sent") ? (
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && stage === "forgot") submitForgot(); }}
            placeholder="用户名"
            autoComplete="username"
            disabled={stage === "forgot-sent"}
            style={inputStyle}
          />
        ) : (
          <>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="用户名（2-32 个字符）"
              autoComplete="username"
              style={inputStyle}
            />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
              placeholder="密码（至少 6 位）"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              style={inputStyle}
            />
          </>
        )}

        {error && (
          <p style={{
            color: colors.status.danger, background: colors.status.dangerBg,
            border: `1px solid ${colors.status.danger}44`, borderRadius: radius.md,
            padding: `${space.md}px ${space.lg}px`, fontSize: font.sm, margin: 0,
          }}>
            {error}
          </p>
        )}
        {note && (
          <p style={{
            color: colors.status.successStrong, background: colors.status.successBg,
            border: `1px solid ${colors.status.successBorder}`, borderRadius: radius.md,
            padding: `${space.md}px ${space.lg}px`, fontSize: font.sm, margin: 0,
          }}>
            {note}
          </p>
        )}

        {/* 主按钮：按 stage 走不同动作 */}
        {stage === "forgot" ? (
          <button
            onClick={submitForgot}
            disabled={busy}
            style={{
              minHeight: touch.large,
              background: busy ? colors.muted.bg : colors.brand.primary,
              color: colors.text.inverse,
              border: "none", borderRadius: radius.md,
              fontSize: font.base, fontWeight: 600,
              cursor: busy ? "wait" : "pointer",
              marginTop: space.sm,
            }}
          >
            {busy ? "请稍候…" : "发送重置链接"}
          </button>
        ) : stage === "forgot-sent" ? (
          <button
            onClick={() => { setStage("login"); setError(null); }}
            style={{
              minHeight: touch.large,
              background: colors.brand.primary,
              color: colors.text.inverse,
              border: "none", borderRadius: radius.md,
              fontSize: font.base, fontWeight: 600,
              cursor: "pointer", marginTop: space.sm,
            }}
          >
            返回登录
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={busy}
            style={{
              minHeight: touch.large,
              background: busy ? colors.muted.bg : colors.brand.primary,
              color: colors.text.inverse,
              border: "none", borderRadius: radius.md,
              fontSize: font.base, fontWeight: 600, cursor: busy ? "wait" : "pointer",
              marginTop: space.sm,
            }}
          >
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </button>
        )}

        {/* 副按钮：登录态下显示「忘记密码」入口；忘记密码态下显示「返回登录」 */}
        {stage === "login" && (
          <button
            onClick={() => { setStage("forgot"); setError(null); }}
            style={{
              minHeight: touch.small,
              background: "transparent",
              color: colors.brand.linkText,
              border: "none",
              fontSize: font.sm, cursor: "pointer",
              marginTop: space.xs,
            }}
          >
            忘记密码？
          </button>
        )}
        {stage === "forgot" && (
          <button
            onClick={() => { setStage("login"); setError(null); }}
            style={{
              minHeight: touch.small,
              background: "transparent",
              color: colors.text.tertiary,
              border: "none",
              fontSize: font.sm, cursor: "pointer",
              marginTop: space.xs,
            }}
          >
            ← 返回登录
          </button>
        )}
      </div>

      <p style={{
        color: colors.text.tertiary, fontSize: font.xs,
        textAlign: "center", marginTop: space.xxl,
        borderTop: borderStyle.card, paddingTop: space.lg,
      }}>
        项目与方案仅登录后可见，账户数据加密存储
      </p>
    </main>
  );
}

export default function LoginPage() {
  // useSearchParams 需要 Suspense 包裹（Next.js App Router 要求）
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
