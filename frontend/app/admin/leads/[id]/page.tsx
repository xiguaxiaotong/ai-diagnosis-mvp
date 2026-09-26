"use client";

import {
  ArrowLeft, Building2, ClipboardList, MessageSquarePlus, Phone, Send,
  StickyNote, ShieldCheck, User as UserIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { getUser, useRequireAuth } from "../../../../lib/auth";
import { useTheme } from "../../../../lib/theme";
import { font, radius, space, touch } from "../../../../lib/tokens";
import { Timeline } from "../../../../components/admin/Timeline";

// 5 态（与后端一致）
const STATUS_OPTIONS = ["pending", "contacted", "quoted", "won", "closed"] as const;
type LeadStatus = (typeof STATUS_OPTIONS)[number];

const STATUS_TEXT: Record<LeadStatus, string> = {
  pending: "待联系",
  contacted: "已联系",
  quoted: "已报价",
  won: "已成交",
  closed: "已关闭",
};

const NOTE_TYPES = [
  { v: "manual", t: "手动跟进" },
  { v: "system", t: "系统记录" },
] as const;
type NoteType = (typeof NOTE_TYPES)[number]["v"];

interface AdminLead {
  id: number;
  project_id: number | null;
  project_title: string | null;
  project_status: string | null;
  user_id: number | null;
  username: string | null;
  name: string;
  phone: string;
  company: string | null;
  note: string | null;
  status: LeadStatus;
  created_at: string | null;
  updated_at: string | null;
}

interface AdminNote {
  id: number;
  lead_id: number;
  admin_id: number | null;
  admin_username: string | null;
  note_type: string;
  content: string;
  created_at: string | null;
}

interface ProjectSummary {
  id: number;
  title: string;
  status: string;
  raw_idea: string | null;
  budget_min: number | null;
  budget_max: number | null;
  created_at: string | null;
  updated_at: string | null;
  solution_generated_at: string | null;
  req_profile_snippet: string | null;
  thread_id: string | null;
}

interface LeadDetailData {
  lead: AdminLead;
  project_summary: ProjectSummary | null;
  notes: AdminNote[];
  stats: { messages_count: number };
  worksheet_id: number | null; // Day8：已转工单则非空
}

// ---- 5 态配色（与列表/ProjectPage 统一） ----
function statusBg(colors: ReturnType<typeof useTheme>["colors"], s: LeadStatus): string {
  switch (s) {
    case "pending": return colors.status.cautionBg;
    case "contacted": return colors.brand.primaryBg;
    case "quoted": return colors.status.warningBg;
    case "won": return colors.status.successBg;
    case "closed": return colors.bg.muted;
  }
}
function statusFg(colors: ReturnType<typeof useTheme>["colors"], s: LeadStatus): string {
  switch (s) {
    case "pending": return colors.status.caution;
    case "contacted": return colors.brand.onPrimaryBg;
    case "quoted": return colors.status.warning;
    case "won": return colors.status.successStrong;
    case "closed": return colors.text.tertiary;
  }
}
// 时间线渲染已抽到 components/admin/Timeline.tsx（Day8：leads 与工单详情共用）

export default function LeadDetailPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();
  const params = useParams();
  const leadId = Number(params.id);

  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [data, setData] = useState<LeadDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noteContent, setNoteContent] = useState("");
  const [noteType, setNoteType] = useState<NoteType>("manual");
  const [submitting, setSubmitting] = useState(false);
  const [converting, setConverting] = useState(false);
  const router = useRouter();

  // SSR 阶段 getUser() 拿不到（window undefined），推迟到 hydration
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    if (!Number.isFinite(leadId)) return;
    try {
      const r = await api<LeadDetailData>(`/api/admin/leads/${leadId}`);
      setData(r);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [leadId]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  const updateStatus = async (newStatus: LeadStatus) => {
    if (!data) return;
    // 乐观更新
    const old = data;
    setData({
      ...data,
      lead: { ...data.lead, status: newStatus },
    });
    try {
      const r = await api<{ lead: AdminLead; note: AdminNote }>(
        `/api/admin/leads/${leadId}`,
        { method: "PATCH", body: JSON.stringify({ status: newStatus }) },
      );
      // 服务端时间线最新条目已写，直接 prepend
      setData((prev) =>
        prev ? {
          ...prev,
          lead: r.lead,
          notes: [r.note, ...prev.notes],
        } : prev,
      );
    } catch (e) {
      setData(old);
      alert("状态更新失败：" + String(e));
    }
  };

  // Day8：lead 转工单（后端幂等：已转则直接返回既有工单）
  const convertToWorksheet = async () => {
    if (!data || converting) return;
    setConverting(true);
    try {
      const r = await api<{ worksheet: { id: number }; created: boolean }>(
        `/api/admin/leads/${leadId}/worksheet`,
        { method: "POST" },
      );
      router.push(`/admin/worksheets/${r.worksheet.id}`);
    } catch (e) {
      alert("转工单失败：" + String(e));
      setConverting(false);
    }
  };

  const submitNote = async () => {
    const content = noteContent.trim();
    if (!content || submitting) return;
    setSubmitting(true);
    try {
      const r = await api<{ note: AdminNote }>(
        `/api/admin/leads/${leadId}/notes`,
        { method: "POST", body: JSON.stringify({ content, note_type: noteType }) },
      );
      // prepend 进时间线
      setData((prev) =>
        prev ? { ...prev, notes: [r.note, ...prev.notes] } : prev,
      );
      setNoteContent("");
    } catch (e) {
      alert("添加失败：" + String(e));
    } finally {
      setSubmitting(false);
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

  const lead = data.lead;
  const summary = data.project_summary;

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
          href="/admin/leads"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: space.xs,
            color: colors.brand.linkText,
            textDecoration: "none",
            fontSize: font.sm,
          }}
        >
          <ArrowLeft size={16} /> 返回 Leads 列表
        </Link>
      </div>

      <header style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.lg }}>
        <ShieldCheck size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>Lead #{lead.id}</h1>
        {/* Day8：转工单入口（已转则显示跳转） */}
        <div style={{ marginLeft: "auto" }}>
          {data.worksheet_id ? (
            <Link
              href={`/admin/worksheets/${data.worksheet_id}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: space.xs,
                padding: `${space.xs}px ${space.md}px`,
                background: colors.status.successBg,
                color: colors.status.successStrong,
                border: `1px solid ${colors.status.successStrong}`,
                borderRadius: radius.md,
                textDecoration: "none",
                fontSize: font.sm,
                fontWeight: 600,
                minHeight: touch.base,
              }}
            >
              <ClipboardList size={14} /> 查看工单 #{data.worksheet_id}
            </Link>
          ) : lead.status === "closed" ? (
            // 已关闭的 lead 不允许转工单（后端 409 兜底，前端先置灰）
            <span
              title="该 lead 已关闭（客户流失/归档），不能转为工单。如需跟进，请先把状态改为非「已关闭」"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: space.xs,
                padding: `${space.xs}px ${space.md}px`,
                background: colors.bg.muted,
                color: colors.text.tertiary,
                border: `1px solid ${colors.border.row}`,
                borderRadius: radius.md,
                fontSize: font.sm,
                cursor: "not-allowed",
                minHeight: touch.base,
              }}
            >
              <ClipboardList size={14} /> 已关闭，不可转工单
            </span>
          ) : (
            <button
              onClick={convertToWorksheet}
              disabled={converting}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: space.xs,
                padding: `${space.xs}px ${space.md}px`,
                background: converting ? colors.bg.muted : colors.brand.primary,
                color: converting ? colors.text.tertiary : colors.text.inverse,
                border: "none",
                borderRadius: radius.md,
                fontSize: font.sm,
                fontWeight: 600,
                cursor: converting ? "not-allowed" : "pointer",
                minHeight: touch.base,
              }}
            >
              <ClipboardList size={14} /> {converting ? "转入中…" : "转为工单"}
            </button>
          )}
        </div>
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
              color: colors.text.primary,
            }}
          >
            <UserIcon size={20} color={colors.text.secondary} /> {lead.name}
          </span>

          <select
            value={lead.status}
            onChange={(e) => updateStatus(e.target.value as LeadStatus)}
            aria-label="lead 状态"
            style={{
              marginLeft: "auto",
              background: statusBg(colors, lead.status),
              color: statusFg(colors, lead.status),
              border: `1px solid ${statusFg(colors, lead.status)}`,
              borderRadius: radius.md,
              padding: `${space.xs}px ${space.sm}px`,
              fontSize: font.sm,
              fontWeight: 600,
              cursor: "pointer",
              minHeight: touch.base,
            }}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {STATUS_TEXT[s]}
              </option>
            ))}
          </select>
        </div>

        <Row icon={<Phone size={16} />} label="手机号">
          <a
            href={`tel:${lead.phone}`}
            style={{ color: colors.brand.linkText, textDecoration: "none", fontFamily: "monospace" }}
          >
            {lead.phone}
          </a>
        </Row>
        {lead.company && (
          <Row icon={<Building2 size={16} />} label="公司">
            {lead.company}
          </Row>
        )}
        {lead.note && (
          <Row icon={<UserIcon size={16} />} label="客户备注">
            <span style={{ color: colors.text.secondary }}>{lead.note}</span>
          </Row>
        )}

        {/* 用户归属 */}
        <div
          style={{
            marginTop: space.md,
            paddingTop: space.md,
            borderTop: `1px solid ${colors.border.row}`,
            fontSize: font.sm,
            color: colors.text.secondary,
          }}
        >
          归属用户：
          <strong>{lead.username ?? "(已注销)"}</strong>
          {lead.user_id && (
            <span style={{ color: colors.text.tertiary, marginLeft: space.xs }}>
              (id={lead.user_id})
            </span>
          )}
          {" · "}留资时间：
          {lead.created_at ? new Date(lead.created_at).toLocaleString("zh-CN") : "—"}
          {" · "}最近更新：
          {lead.updated_at ? new Date(lead.updated_at).toLocaleString("zh-CN") : "—"}
        </div>
      </section>

      {/* 项目摘要 */}
      {summary && (
        <section
          style={{
            background: colors.bg.surface,
            border: borderStyle.card,
            borderRadius: radius.lg,
            padding: space.lg,
            marginBottom: space.lg,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: space.md }}>
            <h2 style={{ margin: 0, fontSize: font.lg }}>关联项目</h2>
            <Link
              href={`/admin/project/${summary.id}`}
              style={{
                color: colors.brand.linkText,
                textDecoration: "none",
                fontSize: font.sm,
              }}
            >
              查看完整诊断 →
            </Link>
          </div>
          <div style={{ marginBottom: space.sm, fontSize: font.base }}>
            <strong>{summary.title}</strong>
            <span style={{ marginLeft: space.sm, fontSize: font.sm, color: colors.text.tertiary }}>
              状态: {summary.status}
            </span>
          </div>
          {summary.raw_idea && (
            <div
              style={{
                background: colors.bg.muted,
                padding: space.md,
                borderRadius: radius.md,
                fontSize: font.sm,
                color: colors.text.secondary,
                lineHeight: 1.6,
                whiteSpace: "pre-wrap",
                marginBottom: space.sm,
              }}
            >
              {summary.raw_idea.slice(0, 300)}
              {summary.raw_idea.length > 300 && "…"}
            </div>
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: space.md, fontSize: font.sm, color: colors.text.tertiary }}>
            {summary.budget_min !== null && summary.budget_max !== null && (
              <span>预算：¥{Math.round(summary.budget_min).toLocaleString()} - ¥{Math.round(summary.budget_max).toLocaleString()}</span>
            )}
            <span>对话消息数：{data.stats.messages_count}</span>
            {summary.solution_generated_at && (
              <span>方案生成：{new Date(summary.solution_generated_at).toLocaleString("zh-CN")}</span>
            )}
          </div>
        </section>
      )}

      {/* 跟进时间线 + 添加 */}
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
          <StickyNote size={20} color={colors.brand.primary} />
          <h2 style={{ margin: 0, fontSize: font.lg }}>跟进时间线</h2>
          <span style={{ marginLeft: "auto", fontSize: font.sm, color: colors.text.tertiary }}>
            共 {data.notes.length} 条
          </span>
        </div>

        {/* 添加跟进表单 */}
        <div
          style={{
            background: colors.bg.muted,
            padding: space.md,
            borderRadius: radius.md,
            marginBottom: space.lg,
          }}
        >
          <textarea
            value={noteContent}
            onChange={(e) => setNoteContent(e.target.value)}
            placeholder="记录跟进要点（电话沟通内容、客户反馈、报价情况…）"
            aria-label="跟进内容"
            maxLength={2000}
            style={{
              width: "100%",
              minHeight: 72,
              padding: space.sm,
              border: borderStyle.input,
              borderRadius: radius.md,
              background: colors.bg.surface,
              color: colors.text.primary,
              fontSize: font.base,
              fontFamily: "inherit",
              resize: "vertical",
              marginBottom: space.sm,
              boxSizing: "border-box",
            }}
          />
          <div style={{ display: "flex", gap: space.sm, alignItems: "center", flexWrap: "wrap" }}>
            <select
              value={noteType}
              onChange={(e) => setNoteType(e.target.value as NoteType)}
              aria-label="跟进类型"
              style={{
                padding: `${space.xs}px ${space.sm}px`,
                border: borderStyle.input,
                borderRadius: radius.md,
                background: colors.bg.surface,
                color: colors.text.primary,
                fontSize: font.sm,
                minHeight: touch.base,
              }}
            >
              {NOTE_TYPES.map((nt) => (
                <option key={nt.v} value={nt.v}>{nt.t}</option>
              ))}
            </select>
            <button
              onClick={submitNote}
              disabled={submitting || !noteContent.trim()}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: space.xs,
                padding: `${space.sm}px ${space.md}px`,
                background: noteContent.trim() && !submitting ? colors.brand.primary : colors.bg.muted,
                color: noteContent.trim() && !submitting ? colors.text.inverse : colors.text.tertiary,
                border: "none",
                borderRadius: radius.md,
                fontSize: font.sm,
                fontWeight: 600,
                cursor: noteContent.trim() && !submitting ? "pointer" : "not-allowed",
                minHeight: touch.base,
              }}
            >
              <Send size={14} /> {submitting ? "提交中…" : "添加跟进"}
            </button>
            <span style={{ marginLeft: "auto", fontSize: font.xs, color: colors.text.tertiary }}>
              {noteContent.length} / 2000
            </span>
          </div>
        </div>

        {/* 时间线列表（Day8 抽出共享组件，工单详情复用） */}
        <Timeline notes={data.notes} />
      </section>

      {/* 占位：与 admin 列表首屏呼应 */}
      <p style={{ fontSize: font.xs, color: colors.text.tertiary, textAlign: "center" }}>
        <MessageSquarePlus size={12} /> 跟进记录仅 admin 可见
      </p>
    </main>
  );
}

// 简单 Row 组件（内联，避免拉 components/ui/ 扩张）
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