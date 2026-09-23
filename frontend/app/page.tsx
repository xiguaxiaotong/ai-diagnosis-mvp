"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "../lib/api";
import { getUser, useAuthed, getToken, type AuthUser } from "../lib/auth";
import { useTheme } from "../lib/theme";
import { font, fontFluid, lineHeight, radius, space, touch } from "../lib/tokens";

/** 弹窗菜单项统一样式（触控目标 40px，全宽左对齐） */
function menuItemStyle(
  colors: ReturnType<typeof useTheme>["colors"],
  borderTop: string,
): React.CSSProperties {
  return {
    display: "block", width: "100%",
    minHeight: touch.base, textAlign: "left",
    padding: `0 ${space.md}px`,
    background: "transparent",
    color: colors.text.tertiary,
    border: "none", borderTop,
    borderRadius: radius.base,
    fontSize: font.base, lineHeight: `${touch.base}px`,
    cursor: "pointer",
  };
}

/** 目标人群（个体户/个人/工作室）的填写示范：真实场景 + 无术语 */
const HOME_EXAMPLES = [
  "示例（奶茶店）：我想做一个自动回复客户微信消息的 AI 客服，能查菜单、处理预约…",
  "示例（个人）：我想做一个私人知识库 AI，上传我的客户资料，随时查询…",
  "示例（工作室）：给员工做一个内部文档问答 AI，快速查公司制度…",
];

export default function Home() {
  const router = useRouter();
  const { colors, borderStyle } = useTheme();
  const authed = useAuthed(); // 游客可浏览首页介绍，点「开始诊断」才引导注册（数据隔离 #2）
  const [user, setUser] = useState<AuthUser | null>(null);
  const [idea, setIdea] = useState("");
  const [exampleIdx, setExampleIdx] = useState(0);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 空提交引导：按钮不再静默禁用，点击时明确告诉用户还缺什么
  const [hint, setHint] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // 右下角用户菜单：avatar 弹窗（个人信息/退出），替代原右上角角标
  const [menuOpen, setMenuOpen] = useState(false);
  const [showProfile, setShowProfile] = useState(false);

  // 目标用户（小店/个人/工作室）不知道写什么 → placeholder 每 4 秒轮换真实场景示例
  // 用户开始输入（idea 非空）就停，不打扰打字
  useEffect(() => {
    if (idea) return;
    const t = setInterval(() => setExampleIdx((i) => (i + 1) % HOME_EXAMPLES.length), 4000);
    return () => clearInterval(t);
  }, [idea]);

  // 游客带着想法去注册（账号隔离 #2）：登录回来自动恢复输入，接着走诊断
  useEffect(() => {
    const pending = sessionStorage.getItem("diag_pending_idea");
    if (pending) {
      setIdea(pending);
      sessionStorage.removeItem("diag_pending_idea");
    }
  }, []);

  // 联调：检测后端健康状态
  useEffect(() => {
    fetch(`${API_BASE}/api/health`)
      .then((r) => setBackendOk(r.ok))
      .catch(() => setBackendOk(false));
  }, []);

  // 登录用户名展示（守卫通过后取 localStorage）
  useEffect(() => {
    if (authed) setUser(getUser());
  }, [authed]);

  function logout() {
    localStorage.removeItem("diag_token");
    localStorage.removeItem("diag_user");
    router.replace("/login");
  }

  // 创建新诊断项目：title 取想法前 20 字，raw_idea 存全文
  async function startDiagnosis() {
    const text = idea.trim();
    if (creating) return;
    // 空输入 / 后端未连接不再静默拦截：给出明确提示 + 聚焦输入框，
    // 让用户知道「点了没反应」其实是缺了什么（移动端尤其重要）
    if (!text) {
      setHint("请先用一两句话描述你想解决的问题，再来生成方案和报价 👇");
      textareaRef.current?.focus();
      return;
    }
    if (backendOk === false) {
      setHint("后端服务未连接，请稍候再试（页面底部可查看服务状态）");
      return;
    }
    setHint(null);
    // 未登录游客：想法暂存到本会话，先去注册/登录（回来自动恢复接着创建）。
    // 项目数据只在登录账号下存库（隔离设计 #4：游客不产生后端数据）
    if (!getToken()) {
      sessionStorage.setItem("diag_pending_idea", text);
      router.push("/login?next=%2F");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const project = await api<{ id: number }>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ title: text.slice(0, 20), raw_idea: text }),
      });
      router.push(`/chat/${project.id}`);
    } catch (e) {
      setError(String(e));
      setCreating(false);
    }
  }

  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        // 首页 hero 区有意的大留白节奏（56/96px），其他页面用 space.huge
        padding: `clamp(56px, 12vh, 96px) ${space.xl}px ${space.huge}px`,
        textAlign: "center",
        minHeight: "100dvh",
        display: "flex", flexDirection: "column",
        position: "relative",
      }}
    >
      {/* 视觉层级（强→弱）：主标题 → 输入框 → 一行简介 → 主按钮 → 次按钮 → 底部状态 */}
      <h1
        style={{
          fontSize: fontFluid.hero,
          margin: `0 0 ${space.base}px`,
          fontWeight: 700, // 页面最强：白色粗体
          letterSpacing: 1,
          lineHeight: 1.3,
        }}
      >
        描述你的想法，帮你判断能不能做、多少钱、怎么做
      </h1>
      <p style={{ color: colors.text.secondary, margin: `0 0 ${space.huge}px`, fontSize: font.md }}>
        不用懂代码，只需要讲清楚你想解决什么问题
      </p>

      {/* 核心交互区：输入框（其余一切都为它服务） */}
      <textarea
        ref={textareaRef}
        value={idea}
        onChange={(e) => {
          setIdea(e.target.value);
          if (hint) setHint(null); // 用户开始输入，清掉引导提示
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            startDiagnosis();
          }
        }}
        placeholder={HOME_EXAMPLES[exampleIdx]}
        rows={3}
        style={{
          display: "block",
          width: "100%",
          maxWidth: 640,
          margin: `0 auto ${space.lg}px`,
          padding: `${space.base}px ${space.lg}px`,
          fontSize: font.lg, // ≥16px，避免 iOS 聚焦自动放大
          color: colors.text.primary,
          background: colors.bg.surface,
          border: hint ? `2px solid ${colors.status.danger}` : borderStyle.input,
          borderRadius: radius.lg,
          boxShadow: colors.shadow.card,
          resize: "vertical",
          outline: "none",
          fontFamily: "inherit",
          lineHeight: lineHeight.normal,
        }}
      />

      {/* 一行简介（压缩版，取代原三行 ✅ 勾选文字） */}
      <p style={{ margin: 0, fontSize: font.sm, color: colors.text.secondary }}>
        适合门店/个体户/自媒体｜输出完整功能方案+预算评估，无需写代码
      </p>
      {/* 温馨提示：全页最弱层级 */}
      <p style={{ margin: `${space.xs}px 0 ${space.xxl}px`, fontSize: font.xs, color: colors.text.tertiary }}>
        本工具仅做需求诊断，前期无任何费用
      </p>

      {/* 主按钮：紫色行动点（饱和度压低一档，hover 浅紫见 .cta-btn） */}
      <style jsx global>{`
        .cta-btn:not(:disabled):hover { filter: brightness(1.15); }
      `}</style>
      <button
        onClick={startDiagnosis}
        disabled={creating}
        className="cta-btn"
        style={{
          padding: `${font.sm}px ${space.xxxl * 1.5}px`,
          fontSize: font.lg,
          fontWeight: 600,
          minHeight: touch.cta,
          width: "100%",
          maxWidth: 360,
          margin: `0 auto ${space.base}px`,
          display: "block",
          background: creating ? colors.muted.bg : colors.brand.primary,
          color: colors.text.inverse,
          border: "none",
          borderRadius: radius.lg,
          cursor: creating ? "not-allowed" : "pointer",
          transition: "filter 0.15s ease",
        }}
      >
        {creating ? "创建中…" : "生成方案与报价评估"}
      </button>
      {/* 空提交引导：手机上「点了没反应」是最差的体验，必须说话 */}
      {hint && (
        <p style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sm, color: colors.status.danger }}>
          {hint}
        </p>
      )}
      {error && (
        <p style={{ margin: `0 0 ${space.sm}px`, color: colors.status.danger, fontSize: font.base }}>
          创建失败：{error}
        </p>
      )}

      {/* 次要按钮：描边淡紫、文字浅紫，刻意弱化，不与主按钮抢视觉 */}
      <a
        href="/projects"
        style={{
          display: "inline-block",
          minHeight: touch.large, lineHeight: `${touch.large}px`,
          padding: `0 ${space.xxxl}px`,
          background: "transparent", color: colors.brand.linkText,
          border: `1px solid ${colors.brand.primaryBorder}`,
          borderRadius: radius.md,
          fontSize: font.base, textDecoration: "none", cursor: "pointer",
        }}
      >
        查看历史项目
      </a>

      {/* 后端状态：全页最底部，最小最淡（放按钮中间是拥挤最大元凶，已挪走） */}
      <p style={{ marginTop: "auto", paddingTop: space.huge, marginBottom: 0, fontSize: font.xs, color: colors.text.tertiary }}>
        {backendOk === null ? "后端：检测中…" : backendOk ? "后端：● 已连接" : "后端：● 未连接（请先启动后端 :8000）"}
      </p>

      {/* 右下角悬浮头像菜单（移动端 H5 通用做法）：
          原右上角「用户名+退出」角标会与 hero 大标题在小屏挤在一起，
          移到右下角悬浮圆钮，点开弹窗【个人信息｜退出登录】。
          透明遮罩负责点外部关闭；safe-area 防止 iPhone 底部小黑条遮住按钮。 */}
      {authed && user && (
        <>
          {menuOpen && (
            <div
              onClick={() => { setMenuOpen(false); setShowProfile(false); }}
              style={{ position: "fixed", inset: 0, zIndex: 999 }}
            />
          )}
          <div
            style={{
              position: "fixed",
              right: space.xxl,
              bottom: `calc(env(safe-area-inset-bottom) + ${space.xxl}px)`,
              zIndex: 1000,
              display: "flex", flexDirection: "column", alignItems: "flex-end",
            }}
          >
            {/* 弹窗菜单：从头像上方弹出 */}
            {menuOpen && (
              <div
                style={{
                  marginBottom: space.md,
                  minWidth: 180,
                  background: colors.bg.surface,
                  border: borderStyle.card,
                  borderRadius: radius.lg,
                  padding: space.md,
                  boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
                }}
              >
                {/* 菜单头部：当前登录人 */}
                <div
                  style={{
                    display: "flex", alignItems: "center", gap: space.sm,
                    padding: `0 0 ${space.md}px`, marginBottom: space.md,
                    borderBottom: borderStyle.row,
                  }}
                >
                  <span style={{ fontSize: font.md }}>👤</span>
                  <span style={{ fontSize: font.base, color: colors.text.primary, fontWeight: 600 }}>
                    {user.name}
                  </span>
                </div>

                {!showProfile ? (
                  <>
                    <button
                      onClick={() => setShowProfile(true)}
                      style={menuItemStyle(colors, borderStyle.row)}
                    >
                      个人信息
                    </button>
                    <button
                      onClick={logout}
                      style={{
                        ...menuItemStyle(colors, "none"),
                        color: colors.status.danger,
                      }}
                    >
                      退出登录
                    </button>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: font.sm, color: colors.text.secondary, lineHeight: lineHeight.loose, padding: `${space.xs} ${space.md}` }}>
                      <div>姓名：{user.name}</div>
                      <div>用户名：{user.username}</div>
                    </div>
                    <button
                      onClick={() => setShowProfile(false)}
                      style={menuItemStyle(colors, borderStyle.row)}
                    >
                      返回
                    </button>
                  </>
                )}
              </div>
            )}

            {/* 圆形头像按钮：48px 触控目标，取姓名首字，未加载时用 👤 */}
            <button
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="用户菜单"
              style={{
                width: touch.cta, height: touch.cta,
                borderRadius: "50%",
                background: colors.brand.primaryBg,
                border: `1px solid ${colors.brand.primaryBorder}`,
                color: colors.text.primary,
                fontSize: font.xl, fontWeight: 600,
                cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              }}
            >
              {user.name ? user.name.slice(0, 1) : "👤"}
            </button>
          </div>
        </>
      )}

      {/* 游客（未登录）：右下角同一位置放「登录」入口，介绍随便看，创建项目要账号 */}
      {authed === false && (
        <button
          onClick={() => router.push("/login")}
          aria-label="登录或注册"
          style={{
            position: "fixed",
            right: space.xxl,
            bottom: `calc(env(safe-area-inset-bottom) + ${space.xxl}px)`,
            zIndex: 1000,
            minHeight: touch.cta, padding: `0 ${space.xl}px`,
            borderRadius: radius.lg,
            background: colors.brand.primary,
            border: "none",
            color: colors.text.inverse,
            fontSize: font.base, fontWeight: 600,
            cursor: "pointer",
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
          }}
        >
          登录 / 注册
        </button>
      )}
    </main>
  );
}