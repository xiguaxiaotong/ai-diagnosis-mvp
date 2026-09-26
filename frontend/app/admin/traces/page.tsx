"use client";

// W8 Day2/3：admin 诊断回放 · 会话成本汇总列表页。
// 数据源 GET /api/admin/traces（后端按 thread_id 聚合 trace.jsonl，
// 最后活动倒序；成本 = tokens × config 单价，估算口径回显在页脚）。
import { Activity } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "../../../lib/api";
import { getUser, useRequireAuth } from "../../../lib/auth";
import { useTheme } from "../../../lib/theme";
import { font, radius, space, touch } from "../../../lib/tokens";

interface TraceRow {
  thread_id: string;
  started_at: string | null;
  last_active_at: string | null;
  node_count: number;
  llm_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_duration_ms: number;
  cost_cny: number;
}

interface TracesResp {
  items: TraceRow[];
  totals: {
    sessions: number;
    node_count: number;
    llm_count: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_cny: number;
    price: { prompt_per_m: number; completion_per_m: number };
  };
  limit: number;
}

const fmtMs = (ms: number) =>
  ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
const fmtTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("zh-CN", { hour12: false }) : "—";

export default function AdminTracesPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();

  const [data, setData] = useState<TracesResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await api<TracesResp>("/api/admin/traces?limit=50");
      setData(r);
      setError(null);
    } catch (e) {
      setError(String(e));
      setData(null);
    }
  }, []);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>
          当前账号不在运营白名单中。需要 admin 权限才能访问 <code>/admin/traces</code>。
        </p>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>
          返回项目列表
        </Link>
      </main>
    );
  }

  const t = data?.totals;
  const GRID = "1.4fr 1.4fr 0.7fr 0.8fr 1fr 1fr 1fr 1.4fr 0.9fr";

  return (
    <main
      style={{
        maxWidth: 1280,
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
        <Activity size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>运营后台 · 诊断回放</h1>
        <Link href="/admin" style={navLink(colors, radius, touch, font, space)}>
          看板
        </Link>
        <Link href="/admin/leads" style={navLink(colors, radius, touch, font, space)}>
          Leads 跟进
        </Link>
        <Link href="/admin/worksheets" style={navLink(colors, radius, touch, font, space)}>
          工单跟单
        </Link>
        <Link href="/admin/cases" style={navLink(colors, radius, touch, font, space)}>
          案例库管理
        </Link>
      </header>

      {error && <p style={{ color: colors.status.danger, marginBottom: space.md }}>{error}</p>}

      {data === null && !error ? (
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      ) : (data?.items.length ?? 0) === 0 ? (
        <p style={{ color: colors.text.secondary, textAlign: "center", padding: space.xxl }}>
          还没有诊断调用记录。跑一次完整诊断后，节点级调用链会自动落 trace 并出现在这里。
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
              gridTemplateColumns: GRID,
              gap: space.sm,
              padding: `${space.md}px ${space.lg}px`,
              background: colors.bg.muted,
              fontSize: font.sm,
              fontWeight: 600,
              color: colors.text.secondary,
              borderBottom: `1px solid ${colors.border.row}`,
            }}
          >
            <div>会话</div>
            <div>开始时间</div>
            <div>节点数</div>
            <div>LLM 次数</div>
            <div>Prompt tokens</div>
            <div>Completion tokens</div>
            <div>总耗时</div>
            <div>最后活动</div>
            <div>成本（元）</div>
          </div>

          {data!.items.map((row) => {
            const short = row.thread_id.replace("project-", "").slice(0, 8);
            return (
              <div
                key={row.thread_id}
                style={{
                  display: "grid",
                  gridTemplateColumns: GRID,
                  gap: space.sm,
                  padding: `${space.md}px ${space.lg}px`,
                  fontSize: font.sm,
                  borderBottom: `1px solid ${colors.border.row}`,
                  alignItems: "center",
                }}
              >
                <div style={{ fontFamily: "monospace" }}>
                  <Link
                    href={`/admin/traces/${row.thread_id}`}
                    style={{ color: colors.brand.linkText, textDecoration: "none" }}
                  >
                    {short}…
                  </Link>
                </div>
                <div style={{ color: colors.text.tertiary }}>{fmtTime(row.started_at)}</div>
                <div>{row.node_count}</div>
                <div style={{ color: row.llm_count > 0 ? colors.text.primary : colors.text.tertiary }}>
                  {row.llm_count}
                </div>
                <div style={{ fontFamily: "monospace" }}>{row.prompt_tokens.toLocaleString()}</div>
                <div style={{ fontFamily: "monospace" }}>{row.completion_tokens.toLocaleString()}</div>
                <div>{fmtMs(row.total_duration_ms)}</div>
                <div style={{ color: colors.text.tertiary }}>{fmtTime(row.last_active_at)}</div>
                <div style={{ fontWeight: 600 }}>{row.cost_cny.toFixed(4)}</div>
              </div>
            );
          })}

          {/* 合计行（全部会话合计，不受本页 limit 影响） */}
          {t && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: GRID,
                gap: space.sm,
                padding: `${space.md}px ${space.lg}px`,
                fontSize: font.sm,
                fontWeight: 600,
                background: colors.bg.muted,
                color: colors.text.primary,
              }}
            >
              <div>合计（{t.sessions} 会话）</div>
              <div>—</div>
              <div>{t.node_count}</div>
              <div>{t.llm_count}</div>
              <div style={{ fontFamily: "monospace" }}>{t.prompt_tokens.toLocaleString()}</div>
              <div style={{ fontFamily: "monospace" }}>{t.completion_tokens.toLocaleString()}</div>
              <div>—</div>
              <div>—</div>
              <div>{t.cost_cny.toFixed(4)}</div>
            </div>
          )}
        </div>
      )}

      {t && (
        <p style={{ marginTop: space.lg, color: colors.text.tertiary, fontSize: font.sm }}>
          显示最近 {data?.items.length ?? 0} / {t.sessions} 会话 · 排序：最后活动优先 ·
          成本估算口径：输入 {t.price.prompt_per_m} 元 / 1M tokens · 输出 {t.price.completion_per_m} 元 / 1M
          tokens（可在后端 .env 调整 DEEPSEEK_PRICE_PROMPT / DEEPSEEK_PRICE_COMPLETION）
        </p>
      )}
    </main>
  );
}

// admin 页统一导航链接样式（与 worksheets 页一致）
function navLink(
  colors: ReturnType<typeof useTheme>["colors"],
  radius: { base: number },
  touch: { base: number },
  font: { sm: number },
  space: { sm: number; md: number },
): CSSProperties {
  return {
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
  };
}
