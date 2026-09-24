"use client";

import { Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../../lib/api";
import { useRequireAuth, getUser } from "../../../lib/auth";
import { useTheme } from "../../../lib/theme";
import { font, radius, space, touch } from "../../../lib/tokens";

// 5 态枚举（与后端 Lead.ALL_STATUSES 一致）
const STATUS_OPTIONS = [
  "pending",
  "contacted",
  "quoted",
  "won",
  "closed",
] as const;
type LeadStatus = (typeof STATUS_OPTIONS)[number];

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

// 状态展示文案（运营视角）
const STATUS_TEXT: Record<LeadStatus, string> = {
  pending: "待联系",
  contacted: "已联系",
  quoted: "已报价",
  won: "已成交",
  closed: "已关闭",
};

export default function AdminLeadsPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();

  const [leads, setLeads] = useState<AdminLead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeStatuses, setActiveStatuses] = useState<Set<LeadStatus>>(
    new Set(), // 空集 = 不过滤
  );

  // 鉴权：admin gate
  // SSR 阶段 getUser() 拿不到（window undefined），所以延迟到 hydration 后再判断
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (activeStatuses.size > 0 && activeStatuses.size < STATUS_OPTIONS.length) {
        // 多选 → 逗号分隔（不全选时打 status=）
        params.set("status", Array.from(activeStatuses).join(","));
      }
      const qs = params.toString();
      const r = await api<{ items: AdminLead[] }>(
        `/api/admin/leads${qs ? "?" + qs : ""}`,
      );
      setLeads(r.items);
      setError(null);
    } catch (e) {
      setError(String(e));
      setLeads([]);
    }
  }, [query, activeStatuses]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  const toggleStatus = (s: LeadStatus) => {
    setActiveStatuses((prev) => {
      const n = new Set(prev);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  };

  const updateLeadStatus = async (lead: AdminLead, newStatus: LeadStatus) => {
    // 乐观更新
    const old = leads;
    if (old) {
      setLeads(
        old.map((l) =>
          l.id === lead.id ? { ...l, status: newStatus, updated_at: new Date().toISOString() } : l,
        ),
      );
    }
    try {
      const r = await api<{ lead: AdminLead }>(
        `/api/admin/leads/${lead.id}`,
        { method: "PATCH", body: JSON.stringify({ status: newStatus }) },
      );
      // 用服务端返回值再刷一遍（updated_at 是 server 权威）
      if (old) {
        setLeads(old.map((l) => (l.id === lead.id ? r.lead : l)));
      }
    } catch (e) {
      // 失败回滚
      setLeads(old);
      alert("状态更新失败：" + String(e));
    }
  };

  // 鉴权失败
  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>
          当前账号不在运营白名单中。需要 admin 权限才能访问 <code>/admin/leads</code>。
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
        <ShieldCheck size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>运营后台 · Leads 跟进</h1>
        <a
          href={`${(typeof window !== "undefined" && (window as any).__API_BASE) || "http://localhost:8000"}/api/admin/leads/export.csv` +
            (activeStatuses.size > 0 && activeStatuses.size < STATUS_OPTIONS.length
              ? "?status=" + Array.from(activeStatuses).join(",")
              : "")}
          download
          onClick={async (e) => {
            // 浏览器同源策略：dev 跨端口 → 用 fetch + Blob 触发下载
            e.preventDefault();
            const params = new URLSearchParams();
            if (activeStatuses.size > 0 && activeStatuses.size < STATUS_OPTIONS.length) {
              params.set("status", Array.from(activeStatuses).join(","));
            }
            const qs = params.toString();
            const token = typeof window !== "undefined" ? localStorage.getItem("diag_token") : null;
            const r = await fetch(`http://localhost:8000/api/admin/leads/export.csv${qs ? "?" + qs : ""}`, {
              headers: token ? { Authorization: "Bearer " + token } : {},
            });
            if (!r.ok) {
              alert("导出失败 HTTP " + r.status);
              return;
            }
            const blob = await r.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            const cd = r.headers.get("Content-Disposition") || "";
            const m = cd.match(/filename="?([^"]+)"?/);
            a.download = m ? m[1] : "leads.csv";
            a.click();
            URL.revokeObjectURL(url);
          }}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: space.xs,
            marginLeft: "auto",
            padding: `${space.sm}px ${space.md}px`,
            background: colors.brand.primary,
            color: colors.text.inverse,
            borderRadius: radius.md,
            textDecoration: "none",
            fontSize: font.sm,
            fontWeight: 600,
            minHeight: touch.base,
          }}
        >
          ↓ 导出 CSV
        </a>
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
            placeholder="搜索姓名/手机号/项目名/用户名"
            aria-label="搜索 leads"
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
                  background: on ? statusBg(colors, s) : colors.bg.surface,
                  color: on ? statusFg(colors, s) : colors.text.secondary,
                  border: `1px solid ${on ? statusFg(colors, s) : borderStyle.input}`,
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

      {/* 表格 */}
      {leads === null ? (
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      ) : leads.length === 0 ? (
        <p style={{ color: colors.text.secondary, textAlign: "center", padding: space.xxl }}>
          没有匹配的 leads
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
              gridTemplateColumns: "1fr 1.2fr 1.4fr 1fr 1.4fr 1fr",
              gap: space.sm,
              padding: `${space.md}px ${space.lg}px`,
              background: colors.bg.muted,
              fontSize: font.sm,
              fontWeight: 600,
              color: colors.text.secondary,
              borderBottom: `1px solid ${colors.border.row}`,
            }}
          >
            <div>姓名</div>
            <div>手机号</div>
            <div>公司 / 备注</div>
            <div>用户 · 项目</div>
            <div>状态</div>
            <div>更新时间</div>
          </div>
          {leads.map((l) => (
            <div
              key={l.id}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1.2fr 1.4fr 1fr 1.4fr 1fr",
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
                  href={`/admin/leads/${l.id}`}
                  style={{ color: colors.brand.linkText, textDecoration: "none" }}
                >
                  {l.name}
                </Link>
                {l.company && (
                  <div style={{ fontSize: font.sm, fontWeight: 400, color: colors.text.secondary }}>
                    {l.company}
                  </div>
                )}
              </div>
              <div style={{ fontFamily: "monospace" }}>{l.phone}</div>
              <div
                style={{
                  fontSize: font.sm,
                  color: colors.text.secondary,
                  maxHeight: 60,
                  overflow: "auto",
                  lineHeight: 1.4,
                }}
              >
                {l.note || <em style={{ color: colors.text.tertiary }}>无备注</em>}
              </div>
              <div style={{ fontSize: font.sm }}>
                <div style={{ color: colors.text.primary }}>
                  {l.username ? `@${l.username}` : `(已注销)`}
                </div>
                {l.project_title && (
                  <Link
                    href={`/project/${l.project_id}`}
                    style={{
                      color: colors.brand.linkText,
                      textDecoration: "none",
                      fontSize: font.sm,
                    }}
                  >
                    {l.project_title}
                  </Link>
                )}
              </div>
              <div>
                <select
                  value={l.status}
                  onChange={(e) => updateLeadStatus(l, e.target.value as LeadStatus)}
                  aria-label={`lead ${l.id} 状态`}
                  style={{
                    background: statusBg(colors, l.status),
                    color: statusFg(colors, l.status),
                    border: `1px solid ${statusFg(colors, l.status)}`,
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
              <div style={{ fontSize: font.sm, color: colors.text.tertiary }}>
                {l.updated_at ? new Date(l.updated_at).toLocaleString("zh-CN") : "—"}
              </div>
            </div>
          ))}
        </div>
      )}

      <p style={{ marginTop: space.lg, color: colors.text.tertiary, fontSize: font.sm }}>
        共 {leads?.length ?? 0} 条 · 排序：最近跟进优先（updated_at DESC）
      </p>
    </main>
  );
}

// ---- 5 态配色（与 ProjectPage 徽章统一） ----
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