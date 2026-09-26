"use client";

// W7 Day9：admin 数据看板首页。
// 数据全部来自 GET /api/admin/stats（实时查库）；空表显示 0、
// 转化率分母为 0 显示「—」（后端返回 None，前端不出 NaN）。
// 趋势图纯 SVG 手画，不引图表库（项目体积 + 国产浏览器兼容考虑）。
import { Activity, BarChart3, Building2, ClipboardList, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { getUser, useRequireAuth } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { font, radius, space } from "../../lib/tokens";

interface StatCards {
  users: { total: number; today: number };
  projects: { total: number; today: number };
  leads: { total: number; today: number };
  worksheets: { total: number; today: number };
}

interface Funnel {
  projects: number;
  leads: number;
  worksheets: number;
  won: number;
  rates: {
    project_to_lead: number | null;
    lead_to_worksheet: number | null;
    worksheet_to_won: number | null;
  };
}

interface TrendDay {
  date: string;
  projects: number;
  leads: number;
}

interface StatsData {
  cards: StatCards;
  funnel: Funnel;
  trend: TrendDay[];
  trend_days: number;
}

const NAV_ITEMS = [
  { href: "/admin/leads", label: "Leads 跟进" },
  { href: "/admin/worksheets", label: "工单跟单" },
  { href: "/admin/cases", label: "案例库管理" },
];

export default function AdminDashboardPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();

  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [data, setData] = useState<StatsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  useEffect(() => {
    if (isAdmin !== true) return;
    api<StatsData>("/api/admin/stats")
      .then((r) => {
        setData(r);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [isAdmin]);

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>当前账号不在运营白名单中。</p>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>返回项目列表</Link>
      </main>
    );
  }

  if (isAdmin === null || (!data && !error)) {
    return (
      <main style={{ maxWidth: 1080, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main style={{ maxWidth: 1080, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <p style={{ color: colors.status.danger }}>加载失败：{error ?? "未知错误"}</p>
      </main>
    );
  }

  const c = data.cards;
  const f = data.funnel;

  const cardDefs = [
    { key: "users", label: "用户数", icon: <Users size={18} />, d: c.users },
    { key: "projects", label: "项目数", icon: <Building2 size={18} />, d: c.projects },
    { key: "leads", label: "Leads 留资", icon: <Activity size={18} />, d: c.leads },
    { key: "worksheets", label: "工单", icon: <ClipboardList size={18} />, d: c.worksheets },
  ];

  // 漏斗环节数据
  const funnelSteps = [
    { label: "诊断项目", value: f.projects },
    { label: "Leads 留资", value: f.leads },
    { label: "工单", value: f.worksheets },
    { label: "已成交", value: f.won },
  ];
  const funnelRates = [
    { label: "项目 → 留资", v: f.rates.project_to_lead },
    { label: "留资 → 工单", v: f.rates.lead_to_worksheet },
    { label: "工单 → 成交", v: f.rates.worksheet_to_won },
  ];

  return (
    <main
      style={{
        maxWidth: 1080,
        margin: "0 auto",
        padding: space.xl,
        color: colors.text.primary,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: space.sm,
          marginBottom: space.lg,
          flexWrap: "wrap",
        }}
      >
        <BarChart3 size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>运营看板</h1>
        <div style={{ marginLeft: "auto", display: "flex", gap: space.xs, flexWrap: "wrap" }}>
          {NAV_ITEMS.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              style={{
                padding: `${space.sm}px ${space.md}px`,
                background: colors.bg.surface,
                color: colors.brand.linkText,
                border: `1px solid ${colors.brand.primary}`,
                borderRadius: radius.base,
                textDecoration: "none",
                fontSize: font.sm,
              }}
            >
              {n.label}
            </Link>
          ))}
        </div>
      </header>

      {/* 统计卡片 */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: space.md,
          marginBottom: space.lg,
        }}
      >
        {cardDefs.map((cd) => (
          <div
            key={cd.key}
            style={{
              background: colors.bg.surface,
              border: borderStyle.card,
              borderRadius: radius.lg,
              padding: space.lg,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: space.xs,
                fontSize: font.sm,
                color: colors.text.secondary,
                marginBottom: space.sm,
              }}
            >
              <span style={{ display: "inline-flex", color: colors.brand.primary }}>
                {cd.icon}
              </span>
              {cd.label}
            </div>
            <div style={{ fontSize: 32, fontWeight: 700, lineHeight: 1 }}>
              {cd.d.total}
            </div>
            <div style={{ marginTop: space.xs, fontSize: font.sm, color: colors.text.tertiary }}>
              今日 +{cd.d.today}
            </div>
          </div>
        ))}
      </section>

      {/* 转化漏斗 */}
      <section
        style={{
          background: colors.bg.surface,
          border: borderStyle.card,
          borderRadius: radius.lg,
          padding: space.lg,
          marginBottom: space.lg,
        }}
      >
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>转化漏斗</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(4, 1fr)`,
            gap: space.sm,
          }}
        >
          {funnelSteps.map((s, i) => {
            // 宽度按上一环节比例缩（第一环全宽）；上游 0 时下游显示最小宽度条
            const upValue = i === 0 ? s.value : funnelSteps[i - 1].value;
            const pct = upValue > 0 ? Math.max((s.value / upValue) * 100, 6) : (s.value > 0 ? 100 : 6);
            return (
              <div key={s.label}>
                <div
                  style={{
                    fontSize: font.sm,
                    color: colors.text.secondary,
                    marginBottom: space.xs,
                  }}
                >
                  {s.label}
                </div>
                <div
                  style={{
                    background: colors.bg.muted,
                    borderRadius: radius.md,
                    padding: space.xxs,
                  }}
                >
                  <div
                    style={{
                      width: `${pct}%`,
                      background: i === 3 ? colors.status.successStrong : colors.brand.primary,
                      color: colors.text.inverse,
                      borderRadius: radius.md,
                      padding: `${space.sm}px ${space.md}px`,
                      fontSize: font.lg,
                      fontWeight: 700,
                      transition: "width 0.3s",
                      boxSizing: "border-box",
                      minWidth: 44,
                    }}
                  >
                    {s.value}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <div
          style={{
            display: "flex",
            gap: space.lg,
            flexWrap: "wrap",
            marginTop: space.md,
            fontSize: font.sm,
            color: colors.text.secondary,
          }}
        >
          {funnelRates.map((r) => (
            <span key={r.label}>
              {r.label}：
              <strong style={{ color: colors.brand.primary }}>
                {r.v === null ? "—" : `${r.v}%`}
              </strong>
            </span>
          ))}
        </div>
      </section>

      {/* 近 14 天趋势（纯 SVG） */}
      <section
        style={{
          background: colors.bg.surface,
          border: borderStyle.card,
          borderRadius: radius.lg,
          padding: space.lg,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: space.md,
            marginBottom: space.md,
            flexWrap: "wrap",
          }}
        >
          <h2 style={{ margin: 0, fontSize: font.lg }}>近 {data.trend_days} 天趋势</h2>
          <span style={{ display: "inline-flex", alignItems: "center", gap: space.xxs, fontSize: font.sm, color: colors.text.secondary }}>
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: 2,
                background: colors.brand.primary,
              }}
            />
            新增项目
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: space.xxs, fontSize: font.sm, color: colors.text.secondary }}>
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: 2,
                background: colors.status.warning,
              }}
            />
            新增 Leads
          </span>
        </div>
        <TrendChart trend={data.trend} />
      </section>

      <p style={{ marginTop: space.lg, fontSize: font.xs, color: colors.text.tertiary }}>
        数据实时查库 · 时区口径：北京时间（Asia/Shanghai）· 每日零点为界
      </p>
    </main>
  );
}

// ---- 纯 SVG 柱状趋势图（两组柱并排，缺日为 0） ----
function TrendChart({ trend }: { trend: TrendDay[] }) {
  const { colors } = useTheme();

  const W = 960;            // viewBox 宽
  const H = 160;            // 图高
  const PAD_TOP = 14;       // 柱顶数值标签行（fontSize 9 + 上部空间，防裁切）
  const PAD_BOTTOM = 24;    // 日期标签区
  const chartH = H - PAD_BOTTOM;
  const n = trend.length;
  // 每天一组：两根柱 + 间隙
  const dayW = W / n;
  const barW = Math.min(dayW * 0.28, 16);
  const gap = 4;

  const max = Math.max(1, ...trend.map((d) => Math.max(d.projects, d.leads)));

  const barX = (i: number, offset: number) => i * dayW + dayW / 2 - barW - gap / 2 + offset;
  // 最高柱也只能顶到 PAD_TOP（数值标签整行完整落在柱顶上方，不裁切）
  const barH = (v: number) => (v / max) * (chartH - PAD_TOP);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", height: "auto", display: "block" }}
      role="img"
      aria-label="近14天新增项目与Leads趋势图"
    >
      {/* 基线 */}
      <line x1={0} y1={chartH} x2={W} y2={chartH} stroke={colors.border.row} strokeWidth={1} />
      {/* 柱 */}
      {trend.map((d, i) => {
        const ymd = d.date.slice(5).replace("-", "/"); // MM-DD
        return (
          <g key={d.date}>
            <rect
              x={barX(i, 0)}
              y={chartH - barH(d.projects)}
              width={barW}
              height={barH(d.projects)}
              rx={2}
              fill={colors.brand.primary}
            >
              <title>{`${d.date} 新增项目 ${d.projects}`}</title>
            </rect>
            <rect
              x={barX(i, barW + gap)}
              y={chartH - barH(d.leads)}
              width={barW}
              height={barH(d.leads)}
              rx={2}
              fill={colors.status.warning}
            >
              <title>{`${d.date} 新增 Leads ${d.leads}`}</title>
            </rect>
            {/* 柱顶数值（>0 才标，防刷屏） */}
            {d.projects > 0 && (
              <text
                x={barX(i, 0) + barW / 2}
                y={chartH - barH(d.projects) - 3}
                textAnchor="middle"
                fontSize={9}
                fill={colors.text.tertiary}
              >
                {d.projects}
              </text>
            )}
            {d.leads > 0 && (
              <text
                x={barX(i, barW + gap) + barW / 2}
                y={chartH - barH(d.leads) - 3}
                textAnchor="middle"
                fontSize={9}
                fill={colors.text.tertiary}
              >
                {d.leads}
              </text>
            )}
            {/* 日期标签：隔天显示，防拥挤 */}
            {i % 2 === 0 && (
              <text
                x={i * dayW + dayW / 2}
                y={chartH + 14}
                textAnchor="middle"
                fontSize={9}
                fill={colors.text.tertiary}
              >
                {ymd}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
