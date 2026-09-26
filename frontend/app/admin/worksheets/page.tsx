"use client";

// W7 Day8：工单列表页（admin）。
// 状态流转不放列表（与 leads 不同）——工单是严格状态机，列表里误选非法流转
// 会 400，操作收敛到详情页「流转按钮」（只显示合法下一步）。
import { ClipboardList, Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../lib/api";
import { getUser, useRequireAuth } from "../../../lib/auth";
import { useTheme } from "../../../lib/theme";
import { font, radius, space, touch } from "../../../lib/tokens";

// 5 态（与后端 Worksheet.ALL_STATUSES 一致）
const STATUS_OPTIONS = [
  "to_confirm",
  "communicating",
  "quoted",
  "won",
  "closed",
] as const;
type WsStatus = (typeof STATUS_OPTIONS)[number];

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

export default function AdminWorksheetsPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();

  const [worksheets, setWorksheets] = useState<AdminWorksheet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeStatuses, setActiveStatuses] = useState<Set<WsStatus>>(new Set());

  // admin gate（SSR 拿不到 localStorage，推迟到 hydration 后判断——hydration 教训见 projects 页）
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (activeStatuses.size > 0 && activeStatuses.size < STATUS_OPTIONS.length) {
        params.set("status", Array.from(activeStatuses).join(","));
      }
      const qs = params.toString();
      const r = await api<{ items: AdminWorksheet[] }>(
        `/api/admin/worksheets${qs ? "?" + qs : ""}`,
      );
      setWorksheets(r.items);
      setError(null);
    } catch (e) {
      setError(String(e));
      setWorksheets([]);
    }
  }, [query, activeStatuses]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  const toggleStatus = (s: WsStatus) => {
    setActiveStatuses((prev) => {
      const n = new Set(prev);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  };

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>
          当前账号不在运营白名单中。需要 admin 权限才能访问 <code>/admin/worksheets</code>。
        </p>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>
          返回项目列表
        </Link>
      </main>
    );
  }

  return (
    <main
      style={{
        maxWidth: 1200,
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
        <ClipboardList size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>运营后台 · 工单跟单</h1>
        <Link
          href="/admin/leads"
          style={{
            display: "inline-flex",
            alignItems: "center",
            marginLeft: "auto",
            padding: `${space.sm}px ${space.md}px`,
            background: colors.bg.surface,
            color: colors.brand.linkText,
            border: `1px solid ${colors.brand.primary}`,
            borderRadius: radius.base,
            textDecoration: "none",
            fontSize: font.sm,
            minHeight: touch.base,
          }}
        >
          ← Leads 跟进
        </Link>
        <Link
          href="/admin/cases"
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: `${space.sm}px ${space.md}px`,
            background: colors.bg.surface,
            color: colors.brand.linkText,
            border: `1px solid ${colors.brand.primary}`,
            borderRadius: radius.base,
            textDecoration: "none",
            fontSize: font.sm,
            minHeight: touch.base,
          }}
        >
          案例库管理 →
        </Link>
        <Link
          href="/admin/traces"
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: `${space.sm}px ${space.md}px`,
            background: colors.bg.surface,
            color: colors.brand.linkText,
            border: `1px solid ${colors.brand.primary}`,
            borderRadius: radius.base,
            textDecoration: "none",
            fontSize: font.sm,
            minHeight: touch.base,
          }}
        >
          诊断回放 →
        </Link>
      </header>

      {/* 筛选条 */}
      <div
        style={{
          display: "flex",
          gap: space.md,
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: space.md,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: space.xs,
            background: colors.bg.surface,
            border: borderStyle.input,
            borderRadius: radius.md,
            padding: `0 ${space.md}px`,
            minHeight: touch.base,
            flex: "1 1 240px",
            maxWidth: 360,
          }}
        >
          <Search size={16} color={colors.text.tertiary} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索客户名/联系方式/公司/需求"
            aria-label="搜索工单"
            style={{
              flex: 1,
              minWidth: 0,
              border: "none",
              outline: "none",
              background: "transparent",
              color: colors.text.primary,
              fontSize: font.base,
              padding: `${space.sm}px 0`,
            }}
          />
        </div>
        <div style={{ display: "flex", gap: space.xs, flexWrap: "wrap" }}>
          {STATUS_OPTIONS.map((s) => {
            const on = activeStatuses.has(s);
            return (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                aria-pressed={on}
                style={{
                  minHeight: touch.base,
                  padding: `0 ${space.md}px`,
                  background: on ? wsStatusBg(colors, s) : colors.bg.surface,
                  color: on ? wsStatusFg(colors, s) : colors.text.secondary,
                  border: `1px solid ${on ? wsStatusFg(colors, s) : borderStyle.input}`,
                  borderRadius: radius.pill,
                  fontSize: font.sm,
                  cursor: "pointer",
                  fontWeight: on ? 600 : 400,
                }}
              >
                {STATUS_TEXT[s]}
              </button>
            );
          })}
          {activeStatuses.size > 0 && (
            <button
              onClick={() => setActiveStatuses(new Set())}
              style={{
                minHeight: touch.base,
                padding: `0 ${space.md}px`,
                background: colors.bg.surface,
                color: colors.text.secondary,
                border: borderStyle.input,
                borderRadius: radius.pill,
                fontSize: font.sm,
                cursor: "pointer",
              }}
            >
              清空筛选
            </button>
          )}
        </div>
      </div>

      {error && (
        <p style={{ color: colors.status.danger, marginBottom: space.md }}>{error}</p>
      )}

      {/* 表格（后端排序：updated_at 倒序） */}
      {worksheets === null ? (
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      ) : worksheets.length === 0 ? (
        <p style={{ color: colors.text.secondary, textAlign: "center", padding: space.xxl }}>
          没有匹配的工单。从 <Link href="/admin/leads" style={{ color: colors.brand.linkText }}>Leads 详情页</Link> 点「转为工单」创建。
        </p>
      ) : (
        <div
          style={{
            background: colors.bg.surface,
            border: borderStyle.card,
            borderRadius: radius.lg,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.1fr 1fr 1.8fr 1fr 1fr",
              gap: space.sm,
              padding: `${space.md}px ${space.lg}px`,
              background: colors.bg.muted,
              fontSize: font.sm,
              fontWeight: 600,
              color: colors.text.secondary,
              borderBottom: `1px solid ${colors.border.row}`,
            }}
          >
            <div>客户</div>
            <div>联系方式</div>
            <div>需求摘要</div>
            <div>状态</div>
            <div>更新时间</div>
          </div>
          {worksheets.map((w) => (
            <div
              key={w.id}
              style={{
                display: "grid",
                gridTemplateColumns: "1.1fr 1fr 1.8fr 1fr 1fr",
                gap: space.sm,
                padding: `${space.md}px ${space.lg}px`,
                fontSize: font.base,
                borderBottom: `1px solid ${colors.border.row}`,
                color: colors.text.primary,
                alignItems: "start",
              }}
            >
              <div style={{ fontWeight: 600 }}>
                <Link
                  href={`/admin/worksheets/${w.id}`}
                  style={{ color: colors.brand.linkText, textDecoration: "none" }}
                >
                  #{w.id} {w.customer_name}
                </Link>
                {w.company && (
                  <div style={{ fontSize: font.sm, fontWeight: 400, color: colors.text.secondary }}>
                    {w.company}
                  </div>
                )}
              </div>
              <div style={{ fontFamily: "monospace" }}>{w.contact}</div>
              <div
                style={{
                  fontSize: font.sm,
                  color: colors.text.secondary,
                  maxHeight: 60,
                  overflow: "auto",
                  lineHeight: 1.4,
                }}
              >
                {w.requirement_summary || <em style={{ color: colors.text.tertiary }}>（无摘要）</em>}
              </div>
              <div>
                <span
                  style={{
                    display: "inline-block",
                    background: wsStatusBg(colors, w.status),
                    color: wsStatusFg(colors, w.status),
                    border: `1px solid ${wsStatusFg(colors, w.status)}`,
                    borderRadius: radius.md,
                    padding: `${space.xs}px ${space.sm}px`,
                    fontSize: font.sm,
                    fontWeight: 600,
                  }}
                >
                  {w.status_text}
                </span>
              </div>
              <div style={{ fontSize: font.sm, color: colors.text.tertiary }}>
                {w.updated_at ? new Date(w.updated_at).toLocaleString("zh-CN") : "—"}
              </div>
            </div>
          ))}
        </div>
      )}

      <p style={{ marginTop: space.lg, color: colors.text.tertiary, fontSize: font.sm }}>
        共 {worksheets?.length ?? 0} 条 · 排序：最近更新优先（updated_at DESC） · 流转操作在工单详情页
      </p>
    </main>
  );
}

// ---- 5 态配色（语义与 leads 状态对齐：黄待办/紫进行/橙关键/绿成交/灰关闭） ----
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
