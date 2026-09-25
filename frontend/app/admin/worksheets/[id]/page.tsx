"use client";

// W7 Day8：工单详情页（admin）。
// 状态流转按钮只显示后端 next_statuses（合法下一步），非法流转在 API 层 400 拦截；
// 时间线复用 components/admin/Timeline.tsx（与 leads 详情同一组件）。
import {
  ArrowLeft, Building2, ClipboardList, History, Phone,
  ShieldCheck, User as UserIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { getUser, useRequireAuth } from "../../../../lib/auth";
import { useTheme } from "../../../../lib/theme";
import { font, radius, space, touch } from "../../../../lib/tokens";
import { Timeline, TimelineNote } from "../../../../components/admin/Timeline";

type WsStatus = "to_confirm" | "communicating" | "quoted" | "won" | "closed";

const STATUS_TEXT: Record<WsStatus, string> = {
  to_confirm: "待确认",
  communicating: "沟通中",
  quoted: "已报价",
  won: "已成交",
  closed: "已关闭",
};

interface AdminWorksheet {
  id: number;
  lead_id: number | null;
  lead_name: string | null;
  project_id: number | null;
  user_id: number | null;
  customer_name: string;
  contact: string;
  company: string | null;
  requirement_summary: string | null;
  thread_id: string | null;
  status: WsStatus;
  status_text: string;
  created_at: string | null;
  updated_at: string | null;
}

interface WsDetailData {
  worksheet: AdminWorksheet;
  next_statuses: WsStatus[];
  notes: TimelineNote[];
}

export default function WorksheetDetailPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();
  const params = useParams();
  const wsId = Number(params.id);

  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [data, setData] = useState<WsDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);

  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    if (!Number.isFinite(wsId)) return;
    try {
      const r = await api<WsDetailData>(`/api/admin/worksheets/${wsId}`);
      setData(r);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [wsId]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  // 状态流转（按钮只出现在 next_statuses 里，非法组合前端根本渲染不出来；
  // 后端状态机仍是权威——并发/绕过 UI 的请求由 API 400 兜底）
  const transition = async (next: WsStatus) => {
    if (!data || transitioning) return;
    setTransitioning(true);
    try {
      const r = await api<{
        worksheet: AdminWorksheet;
        note: TimelineNote;
        next_statuses: WsStatus[];
      }>(`/api/admin/worksheets/${wsId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      // 服务端已写时间线，直接 prepend
      setData((prev) =>
        prev ? {
            worksheet: r.worksheet,
            next_statuses: r.next_statuses,
            notes: [r.note, ...prev.notes],
          } : prev,
      );
    } catch (e) {
      alert("流转失败：" + String(e));
      await load(); // 状态机拒绝时回拉权威数据
    } finally {
      setTransitioning(false);
    }
  };

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>
          当前账号不在运营白名单中。
        </p>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>
          返回项目列表
        </Link>
      </main>
    );
  }

  if (isAdmin === null || !data) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <p style={{ color: colors.text.secondary }}>{error ? `加载失败：${error}` : "加载中…"}</p>
      </main>
    );
  }

  const ws = data.worksheet;

  return (
    <main
      style={{
        maxWidth: 960,
        margin: "0 auto",
        padding: space.xl,
        color: colors.text.primary,
      }}
    >
      {/* 顶部 */}
      <div style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.lg }}>
        <Link
          href="/admin/worksheets"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: space.xs,
            color: colors.brand.linkText,
            textDecoration: "none",
            fontSize: font.sm,
          }}
        >
          <ArrowLeft size={16} /> 返回工单列表
        </Link>
      </div>

      <header style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.lg, flexWrap: "wrap" }}>
        <ShieldCheck size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>工单 #{ws.id}</h1>
        <span
          style={{
            background: wsStatusBg(colors, ws.status),
            color: wsStatusFg(colors, ws.status),
            border: `1px solid ${wsStatusFg(colors, ws.status)}`,
            borderRadius: radius.pill,
            padding: `${space.xs}px ${space.md}px`,
            fontSize: font.sm,
            fontWeight: 600,
          }}
        >
          {ws.status_text}
        </span>
      </header>

      {/* 客户信息 */}
      <section
        style={{
          background: colors.bg.surface,
          border: borderStyle.card,
          borderRadius: radius.lg,
          padding: space.lg,
          marginBottom: space.lg,
        }}
      >
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>客户信息</h2>

        <div style={{ display: "flex", alignItems: "center", gap: space.md, flexWrap: "wrap", marginBottom: space.md }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: space.xs,
              fontSize: font.xl,
              fontWeight: 600,
            }}
          >
            <UserIcon size={20} color={colors.text.secondary} /> {ws.customer_name}
          </span>
        </div>

        <Row icon={<Phone size={16} />} label="联系方式">
          <a
            href={`tel:${ws.contact}`}
            style={{ color: colors.brand.linkText, textDecoration: "none", fontFamily: "monospace" }}
          >
            {ws.contact}
          </a>
        </Row>
        {ws.company && (
          <Row icon={<Building2 size={16} />} label="公司">
            {ws.company}
          </Row>
        )}

        <div
          style={{
            marginTop: space.md,
            paddingTop: space.md,
            borderTop: `1px solid ${colors.border.row}`,
            fontSize: font.sm,
            color: colors.text.secondary,
            display: "flex",
            flexWrap: "wrap",
            gap: space.md,
          }}
        >
          {ws.lead_id && (
            <span>
              来源：
              <Link href={`/admin/leads/${ws.lead_id}`} style={{ color: colors.brand.linkText }}>
                Lead #{ws.lead_id}
              </Link>
            </span>
          )}
          {ws.project_id && (
            <span>
              诊断项目：
              <Link href={`/admin/project/${ws.project_id}`} style={{ color: colors.brand.linkText }}>
                查看#{ws.project_id} →
              </Link>
            </span>
          )}
          {ws.thread_id && (
            <span style={{ color: colors.text.tertiary }}>
              诊断线程：<code style={{ fontSize: font.xs }}>{ws.thread_id.slice(0, 8)}…</code>
            </span>
          )}
          <span style={{ color: colors.text.tertiary }}>
            创建：{ws.created_at ? new Date(ws.created_at).toLocaleString("zh-CN") : "—"}
          </span>
        </div>
      </section>

      {/* 需求摘要 */}
      {ws.requirement_summary && (
        <section
          style={{
            background: colors.bg.surface,
            border: borderStyle.card,
            borderRadius: radius.lg,
            padding: space.lg,
            marginBottom: space.lg,
          }}
        >
          <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>需求摘要</h2>
          <div
            style={{
              background: colors.bg.muted,
              padding: space.md,
              borderRadius: radius.md,
              fontSize: font.sm,
              color: colors.text.secondary,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              maxHeight: 200,
              overflow: "auto",
            }}
          >
            {ws.requirement_summary}
          </div>
        </section>
      )}

      {/* 状态流转 */}
      <section
        style={{
          background: colors.bg.surface,
          border: borderStyle.card,
          borderRadius: radius.lg,
          padding: space.lg,
          marginBottom: space.lg,
        }}
      >
        <h2 style={{ margin: `0 0 ${space.md}px`, fontSize: font.lg }}>状态流转</h2>
        <p style={{ margin: `0 0 ${space.md}px`, fontSize: font.sm, color: colors.text.tertiary }}>
          主流程：待确认 → 沟通中 → 已报价 → 已成交；非终态可直接关闭。
          已成交 / 已关闭为终态，不可再流转。
        </p>
        {data.next_statuses.length === 0 ? (
          <p style={{ color: colors.text.secondary, fontSize: font.base }}>
            当前已是终态（{ws.status_text}），无可用流转。
          </p>
        ) : (
          <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
            {data.next_statuses.map((s) => (
              <button
                key={s}
                onClick={() => transition(s)}
                disabled={transitioning}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: space.xs,
                  padding: `${space.sm}px ${space.lg}px`,
                  background: s === "closed" ? colors.bg.muted : wsStatusBg(colors, s),
                  color: s === "closed" ? colors.text.secondary : wsStatusFg(colors, s),
                  border: `1px solid ${s === "closed" ? colors.border.row : wsStatusFg(colors, s)}`,
                  borderRadius: radius.md,
                  fontSize: font.base,
                  fontWeight: 600,
                  cursor: transitioning ? "not-allowed" : "pointer",
                  minHeight: touch.base,
                }}
              >
                {s === "closed" ? "✕ 关闭工单" : `→ ${STATUS_TEXT[s]}`}
              </button>
            ))}
          </div>
        )}
      </section>

      {/* 时间线（复用 leads 的组件） */}
      <section
        style={{
          background: colors.bg.surface,
          border: borderStyle.card,
          borderRadius: radius.lg,
          padding: space.lg,
          marginBottom: space.lg,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.md }}>
          <History size={20} color={colors.brand.primary} />
          <h2 style={{ margin: 0, fontSize: font.lg }}>流转 / 跟进时间线</h2>
          <span style={{ marginLeft: "auto", fontSize: font.sm, color: colors.text.tertiary }}>
            共 {data.notes.length} 条
          </span>
        </div>
        <Timeline notes={data.notes} />
      </section>

      <p style={{ fontSize: font.xs, color: colors.text.tertiary, textAlign: "center" }}>
        <ClipboardList size={12} /> 工单仅 admin 可见；每次流转自动写时间线
      </p>
    </main>
  );
}

// 简单 Row 组件（与 leads 详情同构）
function Row({
  icon, label, children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  const { colors } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "start",
        gap: space.sm,
        marginBottom: space.sm,
        fontSize: font.base,
      }}
    >
      <span style={{ color: colors.text.tertiary, marginTop: 2, display: "inline-flex" }}>
        {icon}
      </span>
      <span style={{ minWidth: 56, color: colors.text.secondary, fontSize: font.sm }}>{label}</span>
      <span style={{ flex: 1 }}>{children}</span>
    </div>
  );
}

// ---- 5 态配色（与列表页一致） ----
function wsStatusBg(colors: ReturnType<typeof useTheme>["colors"], s: WsStatus): string {
  switch (s) {
    case "to_confirm": return colors.status.cautionBg;
    case "communicating": return colors.brand.primaryBg;
    case "quoted": return colors.status.warningBg;
    case "won": return colors.status.successBg;
    case "closed": return colors.bg.muted;
  }
}
function wsStatusFg(colors: ReturnType<typeof useTheme>["colors"], s: WsStatus): string {
  switch (s) {
    case "to_confirm": return colors.status.caution;
    case "communicating": return colors.brand.onPrimaryBg;
    case "quoted": return colors.status.warning;
    case "won": return colors.status.successStrong;
    case "closed": return colors.text.tertiary;
  }
}
