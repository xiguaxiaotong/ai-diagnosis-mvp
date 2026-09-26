"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { clearSession, getToken, useRequireAuth } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { font, radius, space, touch } from "../../lib/tokens";

interface MeUser {
  id: number;
  username: string;
  name: string;
  email: string | null;
  is_guest: boolean;
}

/** W7 Day2：个人中心（昵称 / 邮箱 / 密码）。三个表单相互独立，提交后刷新。 */
export default function MePage() {
  const { colors, borderStyle } = useTheme();
  const router = useRouter();
  const authed = useRequireAuth(); // 未登录 → /login

  const [user, setUser] = useState<MeUser | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  // 三段表单的局部状态
  const [nameInput, setNameInput] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [curPwdForEmail, setCurPwdForEmail] = useState("");
  const [curPwd, setCurPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [newPwdConfirm, setNewPwdConfirm] = useState("");

  // 每段表单的 UI 态
  type FlashState = { busy: boolean; ok: string | null; err: string | null };
  const emptyFlash = (): FlashState => ({ busy: false, ok: null, err: null });
  const [flashName, setFlashName] = useState<FlashState>(emptyFlash());
  const [flashEmail, setFlashEmail] = useState<FlashState>(emptyFlash());
  const [flashPwd, setFlashPwd] = useState<FlashState>(emptyFlash());

  // 加载用户信息
  useEffect(() => {
    if (authed === false) return;
    if (!getToken()) return;
    (async () => {
      try {
        const data = await api<{ user: MeUser }>("/api/auth/me");
        const u = data.user;
        setUser(u);
        setNameInput(u.name);
        setEmailInput(u.email ?? "");
      } catch (e) {
        setLoadErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [authed]);

  // ---------- PATCH 通用封装 ----------
  async function patchMe(body: Record<string, unknown>): Promise<{ ok: true; data: { user: MeUser; changed: string[] } } | { ok: false; detail: string }> {
    try {
      const data = await api<{ user: MeUser; changed: string[] }>("/api/auth/me", {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      return { ok: true, data };
    } catch (e) {
      return { ok: false, detail: e instanceof Error ? e.message : "网络异常，请重试" };
    }
  }

  // ---------- 三段表单提交 ----------

  async function submitName() {
    if (!user) return;
    if (!nameInput.trim()) { setFlashName({ ...emptyFlash(), err: "昵称不能为空" }); return; }
    if (nameInput === user.name) { setFlashName({ ...emptyFlash(), ok: "昵称未变化" }); return; }
    setFlashName({ busy: true, ok: null, err: null });
    const r = await patchMe({ name: nameInput });
    if (!r.ok) { setFlashName({ busy: false, ok: null, err: r.detail }); return; }
    setUser(r.data.user);
    setFlashName({ busy: false, ok: "昵称已更新", err: null });
  }

  async function submitEmail() {
    if (!user) return;
    const newEmail = emailInput.trim();
    if (!newEmail) { setFlashEmail({ ...emptyFlash(), err: "请输入新邮箱" }); return; }
    // 前端基本格式校验（后端）
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(newEmail)) {
      setFlashEmail({ ...emptyFlash(), err: "邮箱格式不正确" });
      return;
    }
    if (newEmail === user.email) { setFlashEmail({ ...emptyFlash(), ok: "邮箱未变化" }); return; }
    if (!curPwdForEmail) { setFlashEmail({ ...emptyFlash(), err: "修改邮箱需提供当前密码" }); return; }
    setFlashEmail({ busy: true, ok: null, err: null });
    const r = await patchMe({ new_email: newEmail, old_password: curPwdForEmail });
    if (!r.ok) { setFlashEmail({ busy: false, ok: null, err: r.detail }); return; }
    setUser(r.data.user);
    setCurPwdForEmail("");
    setFlashEmail({ busy: false, ok: "邮箱已更新", err: null });
  }

  async function submitPassword() {
    if (!user) return;
    if (!curPwd) { setFlashPwd({ ...emptyFlash(), err: "请输入当前密码" }); return; }
    if (newPwd.length < 6) { setFlashPwd({ ...emptyFlash(), err: "新密码至少 6 位" }); return; }
    if (newPwd !== newPwdConfirm) { setFlashPwd({ ...emptyFlash(), err: "两次输入的新密码不一致" }); return; }
    setFlashPwd({ busy: true, ok: null, err: null });
    const r = await patchMe({ new_password: newPwd, old_password: curPwd });
    if (!r.ok) { setFlashPwd({ busy: false, ok: null, err: r.detail }); return; }
    // 改密成功 → 清会话 + 强制重新登录（防其他设备残留旧 token 长期有效）
    // 简化：MVP 阶段清当前会话、跳登录页
    setFlashPwd({ busy: false, ok: "密码已更新，请重新登录", err: null });
    clearSession();
    setTimeout(() => router.replace("/login"), 1200);
  }

  // ---------- 渲染 ----------

  const cardStyle = {
    background: colors.bg.surface,
    border: borderStyle.card,
    borderRadius: radius.md,
    padding: `${space.xl}px`,
    marginBottom: space.lg,
    boxShadow: colors.shadow.card,
  } as const;

  const inputStyle = {
    width: "100%",
    minHeight: touch.large,
    padding: `0 ${space.lg}px`,
    background: colors.bg.muted,
    color: colors.text.primary,
    border: `1px solid ${colors.border.default}`,
    borderRadius: radius.md,
    fontSize: font.lg,  // 16px 防 iOS 聚焦放大
    outline: "none",
  } as const;

  const primaryBtn = (busy: boolean): React.CSSProperties => ({
    minHeight: touch.large,
    padding: `0 ${space.xxl}px`,
    background: busy ? colors.muted.bg : colors.brand.primary,
    color: colors.text.inverse,
    border: "none", borderRadius: radius.md,
    fontSize: font.base, fontWeight: 600,
    cursor: busy ? "wait" : "pointer",
  });

  const flashMsg = (s: FlashState) =>
    s.err ? (
      <p style={{
        margin: `${space.sm}px 0 0`,
        padding: `${space.md}px ${space.lg}px`,
        background: colors.status.dangerBg,
        border: `1px solid ${colors.status.danger}44`,
        borderRadius: radius.md,
        color: colors.status.dangerStrong,
        fontSize: font.sm,
      }}>
        {s.err}
      </p>
    ) : s.ok ? (
      <p style={{
        margin: `${space.sm}px 0 0`,
        padding: `${space.md}px ${space.lg}px`,
        background: colors.status.successBg,
        border: `1px solid ${colors.status.successBorder}`,
        borderRadius: radius.md,
        color: colors.status.successStrong,
        fontSize: font.sm,
      }}>
        {s.ok}
      </p>
    ) : null;

  if (authed === null) return null;
  if (!user) {
    return (
      <main style={{ maxWidth: 560, margin: `${space.pageTop}px auto`, padding: `0 ${space.xl}px` }}>
        <h1>个人中心</h1>
        {loadErr ? (
          <p style={{ color: colors.status.danger }}>加载失败：{loadErr}</p>
        ) : (
          <p style={{ color: colors.text.secondary }}>加载中…</p>
        )}
        <Link href="/" style={{ color: colors.brand.linkText }}>← 返回首页</Link>
      </main>
    );
  }

  // 游客不允许进入（理论上 useRequireAuth 拦得住，但服务端兜底）
  if (user.is_guest) {
    return (
      <main style={{ maxWidth: 560, margin: `${space.pageTop}px auto`, padding: `0 ${space.xl}px` }}>
        <h1>个人中心</h1>
        <p style={{ color: colors.text.secondary }}>游客无法修改个人资料，请先注册或登录。</p>
        <Link href="/login?next=%2Fme" style={{ color: colors.brand.linkText }}>去注册 / 登录 →</Link>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 560, margin: `${space.pageTop}px auto`, padding: `0 ${space.xl}px` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h1 style={{ margin: 0 }}>个人中心</h1>
        <Link href="/" style={{ color: colors.brand.linkText, fontSize: font.sm }}>← 返回首页</Link>
      </div>
      <p style={{ margin: `${space.xs}px 0 ${space.xl}px`, color: colors.text.secondary, fontSize: font.sm }}>
        账号、密码、邮箱都在这里管理
      </p>

      {/* 账号信息（只读） */}
      <section style={cardStyle}>
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>账号信息</h2>
        <Row label="用户名" value={user.username} />
        <Row label="用户 ID" value={String(user.id)} />
        <Row label="当前昵称" value={user.name} />
        <Row label="当前邮箱" value={user.email || "（未设置）"} />
      </section>

      {/* 改昵称（无需旧密码） */}
      <section style={cardStyle}>
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>修改昵称</h2>
        <input
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submitName(); }}
          placeholder="昵称"
          maxLength={32}
          style={inputStyle}
        />
        <button
          onClick={submitName}
          disabled={flashName.busy}
          style={{ ...primaryBtn(flashName.busy), marginTop: space.md }}
        >
          {flashName.busy ? "保存中…" : "保存昵称"}
        </button>
        {flashMsg(flashName)}
      </section>

      {/* 改邮箱（需旧密码） */}
      <section style={cardStyle}>
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>修改邮箱</h2>
        <p style={{ margin: `0 0 ${space.md}px`, color: colors.text.tertiary, fontSize: font.xs }}>
          需输入当前密码二次验证（防账号被盗后篡改邮箱）
        </p>
        <input
          value={emailInput}
          onChange={(e) => setEmailInput(e.target.value)}
          placeholder="新邮箱（如 you@example.com）"
          autoComplete="email"
          style={inputStyle}
        />
        <input
          type="password"
          value={curPwdForEmail}
          onChange={(e) => setCurPwdForEmail(e.target.value)}
          placeholder="当前密码"
          autoComplete="current-password"
          style={{ ...inputStyle, marginTop: space.md }}
        />
        <button
          onClick={submitEmail}
          disabled={flashEmail.busy}
          style={{ ...primaryBtn(flashEmail.busy), marginTop: space.md }}
        >
          {flashEmail.busy ? "保存中…" : "保存邮箱"}
        </button>
        {flashMsg(flashEmail)}
      </section>

      {/* 改密码（需旧密码） */}
      <section style={cardStyle}>
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>修改密码</h2>
        <p style={{ margin: `0 0 ${space.md}px`, color: colors.text.tertiary, fontSize: font.xs }}>
          修改成功后会自动退出当前会话，需重新登录
        </p>
        <input
          type="password"
          value={curPwd}
          onChange={(e) => setCurPwd(e.target.value)}
          placeholder="当前密码"
          autoComplete="current-password"
          style={inputStyle}
        />
        <input
          type="password"
          value={newPwd}
          onChange={(e) => setNewPwd(e.target.value)}
          placeholder="新密码（至少 6 位）"
          autoComplete="new-password"
          style={{ ...inputStyle, marginTop: space.md }}
        />
        <input
          type="password"
          value={newPwdConfirm}
          onChange={(e) => setNewPwdConfirm(e.target.value)}
          placeholder="再次输入新密码"
          autoComplete="new-password"
          style={{ ...inputStyle, marginTop: space.md }}
        />
        <button
          onClick={submitPassword}
          disabled={flashPwd.busy}
          style={{ ...primaryBtn(flashPwd.busy), marginTop: space.md }}
        >
          {flashPwd.busy ? "保存中…" : "保存密码"}
        </button>
        {flashMsg(flashPwd)}
      </section>
    </main>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  // Row 是内嵌小工具：复用一个 Row 组件避免重复写 label+value 的样式
  // 不抽到 components/ui/ 因为只在这一页用了 1 次（实际是 4 次，不算 ≤2 次原则下未达阈值；先 inline）
  const { colors } = useTheme();
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: `${space.sm}px 0`,
      borderBottom: `1px solid ${colors.border.subtle}`,
    }}>
      <span style={{ color: colors.text.secondary, fontSize: font.sm }}>{label}</span>
      <span style={{ color: colors.text.primary, fontSize: font.base, fontWeight: 500 }}>{value}</span>
    </div>
  );
}