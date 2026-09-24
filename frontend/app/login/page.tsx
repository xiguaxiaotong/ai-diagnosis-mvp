"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { API_BASE } from "../../lib/api";
import { isGuest, popGuestToken, saveSession } from "../../lib/auth";
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
      const resp = await fetch(`${API_BASE}/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u, password }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setError(data.detail ?? "请求失败，请重试");
        return;
      }
      saveSession(data.token, data.user);
      // 游客项目过户：把游客名下项目全部转到刚登录的正式账号（失败不阻塞跳转）
      const guestToken = popGuestToken();
      if (guestToken) {
        try {
          await fetch(`${API_BASE}/api/auth/claim`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${data.token}`,
            },
            body: JSON.stringify({ guest_token: guestToken }),
          });
        } catch {
          /* 过户失败不影响登录本身 */
        }
      }
      if (data.note) setNote(data.note);
      router.replace(next);
    } catch {
      setError("网络异常，请检查网络后重试");
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
        {mode === "login" ? "登录" : "注册"}
      </h1>
      <p style={{ color: colors.text.secondary, fontSize: font.sm, textAlign: "center", marginTop: 0 }}>
        {mode === "login" ? "登录后继续你的项目" : "创建账户，方案和项目只属于你"}
      </p>

      {/* 登录 / 注册切换 */}
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

      <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
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
