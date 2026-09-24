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

/** 全站唯一图标来源：Lucide 线性图标（统一 strokeWidth=1.5、按需尺寸），
 *  禁止再混入手绘 SVG / emoji / 彩色图标 */
import {
  BookOpen, Cpu, FileCheck2, FileSearch, Megaphone, MessageCircle,
  PenLine, Store, User as UserIcon, Wand2,
} from "lucide-react";

const ICONS = {
  chat: MessageCircle,
  book: BookOpen,
  doc: FileSearch,
  store: Store,
  user: UserIcon,
  mega: Megaphone,
  pen: PenLine,
  cpu: Cpu,
  docCheck: FileCheck2,
  spark: Wand2,
} as const;

function Icon({ name, size = 18 }: { name: keyof typeof ICONS; size?: number }) {
  const C = ICONS[name];
  return <C size={size} strokeWidth={1.5} aria-hidden />;
}

/** 三个高频场景卡：点击整段填入输入框——功能性视觉（帮用户一键开始），
 *  替代原来的轮换 placeholder 示例文字 */
const SCENARIOS = [
  {
    icon: "chat",
    title: "奶茶店 AI 客服",
    desc: "自动回微信、查菜单、处理预约",
    idea: "我想做一个自动回复客户微信消息的 AI 客服，能查菜单、处理预约",
  },
  {
    icon: "book",
    title: "私人知识库 AI",
    desc: "上传客户资料，随时查询",
    idea: "我想做一个私人知识库 AI，上传我的客户资料，随时查询",
  },
  {
    icon: "doc",
    title: "内部文档问答",
    desc: "员工快速查公司制度",
    idea: "给员工做一个内部文档问答 AI，让员工能快速查公司制度",
  },
] as const;

/** 三步流程条：告诉用户点下去会发生什么（信任建设，不占地方） */
const FLOW_STEPS = [
  { icon: "pen", label: "描述想法" },
  { icon: "cpu", label: "AI 诊断" },
  { icon: "docCheck", label: "出方案报价" },
] as const;

/** 目标人群徽章行（替代纯文字「适合门店/个体户/自媒体」） */
const AUDIENCE = [
  { icon: "store", label: "门店" },
  { icon: "user", label: "个体户" },
  { icon: "mega", label: "自媒体" },
] as const;

export default function Home() {
  const router = useRouter();
  const { colors, borderStyle } = useTheme();
  const authed = useAuthed(); // 游客可浏览首页介绍，点「开始诊断」才引导注册（数据隔离 #2）
  const [user, setUser] = useState<AuthUser | null>(null);
  const [idea, setIdea] = useState("");
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 空提交引导：按钮不再静默禁用，点击时明确告诉用户还缺什么
  const [hint, setHint] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // 右下角用户菜单：avatar 弹窗（个人信息/退出），替代原右上角角标
  const [menuOpen, setMenuOpen] = useState(false);
  const [showProfile, setShowProfile] = useState(false);

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
      setHint("请先用一两句话描述你想解决的问题，再来生成方案和报价");
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
      <style jsx global>{`
        /* 断行点固定在语义边界「帮你判断」后；窄屏隐藏 <br> 交给自然换行 */
        .hero-br { display: none; }
        @media (min-width: 420px) { .hero-br { display: inline; } }
      `}</style>
      <h1
        style={{
          fontSize: fontFluid.hero,
          maxWidth: 640,
          margin: `0 auto ${space.base}px`,
          fontWeight: 700,
          letterSpacing: 1,
          lineHeight: 1.3,
        }}
      >
        描述你的想法，帮你判断
        <br className="hero-br" />
        能不能做、多少钱、怎么做
      </h1>
      <p style={{ color: colors.text.secondary, margin: `0 0 ${space.xxl}px`, fontSize: font.md }}>
        不用懂代码，只需要讲清楚你想解决什么问题
      </p>

      {/* 场景卡：不知道写什么 → 点一张直接填入（功能性视觉，替代轮换示例文字）
          移动端（<560px）切「图标左 + 文案右」紧凑横排并缩小图标，
          避免三张竖排大卡把输入框挤出首屏；桌面端保持竖排大卡 */}
      <style jsx global>{`
        .sc-card { display: flex; flex-direction: column; align-items: flex-start; gap: ${space.sm}px; }
        .sc-body { display: flex; flex-direction: column; gap: 3px; }
        @media (max-width: 559px) {
          .sc-card { flex-direction: row; align-items: center; gap: ${space.md}px; padding: ${space.sm}px ${space.md}px; }
          .sc-icon { width: 30px; height: 30px; }
          .sc-icon svg { width: 16px; height: 16px; }
        }
      `}</style>
      <div
        style={{
          display: "flex", flexWrap: "wrap", justifyContent: "center",
          gap: space.md, marginBottom: space.xl, textAlign: "left",
        }}
      >
        {SCENARIOS.map((s) => (
          <button
            key={s.title}
            className="sc-card"
            onClick={() => {
              setIdea(s.idea);
              if (hint) setHint(null);
              textareaRef.current?.focus();
            }}
            style={{
              flex: "1 1 30%", minWidth: 200, maxWidth: 260,
              padding: `${space.base + 2}px ${space.base + 2}px`,
              background: colors.bg.surface,
              border: borderStyle.card, borderRadius: radius.lg,
              boxShadow: colors.shadow.card,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >
            <span
              className="sc-icon"
              style={{
                borderRadius: radius.md,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: colors.brand.primaryBg, color: colors.brand.linkText,
                flexShrink: 0,
              }}
            >
              <Icon name={s.icon} size={19} />
            </span>
            <span className="sc-body">
              <span style={{ fontSize: font.base, fontWeight: 600, color: colors.text.primary }}>
                {s.title}
              </span>
              <span style={{ fontSize: font.sm, color: colors.text.secondary, lineHeight: lineHeight.tight }}>
                {s.desc}
              </span>
            </span>
          </button>
        ))}
      </div>

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
        placeholder="或在这里直接描述你的想法…"
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
          resize: "vertical",
          outline: "none",
          fontFamily: "inherit",
          lineHeight: lineHeight.normal,
        }}
      />

      {/* 主按钮：主题色行动点，文字前加同色系线性小图标（无 emoji） */}
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
          margin: `0 auto ${space.xl}px`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: space.sm,
          background: creating ? colors.muted.bg : colors.brand.primary,
          color: colors.text.inverse,
          border: "none",
          borderRadius: radius.md,
          cursor: creating ? "not-allowed" : "pointer",
          transition: "filter 0.15s ease",
        }}
      >
        <Icon name="spark" size={19} />
        {creating ? "创建中…" : "生成方案与报价评估"}
      </button>

      {/* 三步流程条：数字圆点 + 细线相连，说明「点下去会发生什么」 */}
      <div
        style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          gap: space.sm, margin: `${space.base}px auto ${space.xl}px`,
        }}
      >
        {FLOW_STEPS.map((s, i) => (
          <span key={s.label} style={{ display: "flex", alignItems: "center", gap: space.sm }}>
            {i > 0 && (
              <span
                aria-hidden="true"
                style={{ width: 24, height: 1, background: colors.border.default, flexShrink: 0 }}
              />
            )}
            <span style={{ display: "flex", alignItems: "center", gap: space.xs }}>
              <span
                style={{
                  width: 22, height: 22, borderRadius: "50%",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: colors.brand.primaryBg, color: colors.brand.linkText,
                  fontSize: font.xs, fontWeight: 600, flexShrink: 0,
                }}
              >
                {i + 1}
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: font.sm, color: colors.text.secondary }}>
                <Icon name={s.icon} size={15} />
                {s.label}
              </span>
            </span>
          </span>
        ))}
      </div>

      {/* 目标人群徽章行：小图标 + 文字（替代纯文字「适合门店/个体户/自媒体」） */}
      <div
        style={{
          display: "flex", flexWrap: "wrap", justifyContent: "center",
          gap: space.sm, marginBottom: space.base,
        }}
      >
        {AUDIENCE.map((a) => (
          <span
            key={a.label}
            style={{
              display: "inline-flex", alignItems: "center", gap: space.xs,
              padding: `${space.xxs}px ${space.md}px`,
              borderRadius: radius.pill,
              border: `1px solid ${colors.brand.primaryBorder}`,
              color: colors.text.secondary, fontSize: font.xs,
            }}
          >
            <span style={{ color: colors.brand.linkText, display: "flex" }}>
              <Icon name={a.icon} size={13} />
            </span>
            {a.label}
          </span>
        ))}
        <span style={{ fontSize: font.xs, color: colors.text.secondary, alignSelf: "center" }}>
          均可使用｜输出完整功能方案+预算评估
        </span>
      </div>
      {/* 温馨提示：全页最弱层级 */}
      <p style={{ margin: `0 0 ${space.xxl}px`, fontSize: font.xs, color: colors.text.tertiary }}>
        本工具仅做需求诊断，前期无任何费用
      </p>
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
                  boxShadow: colors.shadow.float,
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
                  <span style={{ color: colors.brand.linkText, display: "flex" }}>
                    <UserIcon size={16} strokeWidth={1.5} />
                  </span>
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

            {/* 圆形头像按钮：48px 触控目标，取姓名首字，无姓名时用线性人形图标 */}
            <button
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="用户菜单"
              style={{
                width: touch.cta, height: touch.cta,
                borderRadius: "50%",
                background: colors.brand.primaryBg,
                border: `1px solid ${colors.brand.primaryBorder}`,
                color: colors.brand.linkText,
                fontSize: font.xl, fontWeight: 600,
                cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: colors.shadow.float,
              }}
            >
              {user.name ? user.name.slice(0, 1) : <UserIcon size={20} strokeWidth={1.5} />}
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
            boxShadow: colors.shadow.float,
          }}
        >
          登录 / 注册
        </button>
      )}
    </main>
  );
}