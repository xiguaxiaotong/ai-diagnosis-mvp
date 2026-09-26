"use client";

// W8 Day2/3：诊断回放详情页 · 按时间顺序渲染节点链。
// LLM 调用行高亮缩进，点行展开输入/输出摘要；耗时 + tokens 显示在每行。
import { ArrowLeft, Bot, Cpu } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { getUser, useRequireAuth } from "../../../../lib/auth";
import { useTheme } from "../../../../lib/theme";
import { font, radius, space } from "../../../../lib/tokens";

interface TraceItem {
  type: "node" | "llm";
  ts: string;
  thread_id?: string;
  // node
  node?: string;
  start?: string;
  duration_ms?: number;
  input_summary?: string;
  output_summary?: string;
  llm_calls?: number;
  tokens?: { prompt: number; completion: number };
  interrupted?: boolean;
  error?: string;
  // llm
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

interface TraceDetail {
  thread_id: string;
  count: number;
  node_count: number;
  llm_count: number;
  items: TraceItem[];
}

const fmtMs = (ms?: number) =>
  ms === undefined ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
const fmtTime = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("zh-CN", { hour12: false, fractionalSecondDigits: 1 }) : "—";

export default function TraceDetailPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();
  const params = useParams();
  const threadId = String(params.thread_id);

  const [data, setData] = useState<TraceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await api<TraceDetail>(`/api/admin/trace/${threadId}`);
      setData(r);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [threadId]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  const toggle = (i: number) => {
    setExpanded((prev) => {
      const n = new Set(prev);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });
  };

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>需要 admin 权限才能访问诊断回放。</p>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>
          返回项目列表
        </Link>
      </main>
    );
  }

  return (
    <main
      style={{
        maxWidth: 960,
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
          marginBottom: space.md,
          flexWrap: "wrap",
        }}
      >
        <Link
          href="/admin/traces"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: space.xs,
            color: colors.brand.linkText,
            textDecoration: "none",
            fontSize: font.sm,
          }}
        >
          <ArrowLeft size={16} /> 返回回放列表
        </Link>
      </header>

      <h1 style={{ marginTop: 0, fontSize: font.xl, display: "flex", alignItems: "center", gap: space.sm }}>
        <Bot size={22} color={colors.brand.primary} />
        诊断调用链
      </h1>
      <p style={{ fontFamily: "monospace", fontSize: font.sm, color: colors.text.secondary, wordBreak: "break-all" }}>
        {threadId}
      </p>

      {error && <p style={{ color: colors.status.danger, marginBottom: space.md }}>{error}</p>}

      {data === null && !error ? (
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      ) : data && data.count === 0 ? (
        <p style={{ color: colors.text.secondary, textAlign: "center", padding: space.xxl }}>
          该会话还没有 trace 记录（可能是旧会话——trace 自 W8 Day1 起才开始记录）。
        </p>
      ) : (
        <>
          <p style={{ color: colors.text.tertiary, fontSize: font.sm, marginBottom: space.md }}>
            {data!.node_count} 个节点 · {data!.llm_count} 次 LLM 调用 · 时间序（点击行展开输入/输出摘要）
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            {data!.items.map((it, i) => {
              const isLlm = it.type === "llm";
              const open = expanded.has(i);
              const hasDetail = Boolean(it.input_summary || it.output_summary);
              return (
                <div
                  key={i}
                  style={{
                    background: isLlm ? colors.brand.primaryBg : colors.bg.surface,
                    border: `1px solid ${isLlm ? colors.brand.primary : borderStyle.card}`,
                    borderLeft: isLlm
                      ? `3px solid ${colors.brand.primary}`
                      : `3px solid ${colors.border.row}`,
                    borderRadius: radius.md,
                    padding: `${space.sm}px ${space.md}px`,
                    marginLeft: isLlm ? space.xl : 0,
                  }}
                >
                  <div
                    role={hasDetail ? "button" : undefined}
                    tabIndex={hasDetail ? 0 : undefined}
                    onClick={hasDetail ? () => toggle(i) : undefined}
                    onKeyDown={hasDetail ? (e) => e.key === "Enter" && toggle(i) : undefined}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: space.sm,
                      flexWrap: "wrap",
                      cursor: hasDetail ? "pointer" : "default",
                      fontSize: font.sm,
                    }}
                  >
                    {isLlm ? (
                      <Cpu size={14} color={colors.brand.onPrimaryBg} />
                    ) : (
                      <span style={{ width: 14, textAlign: "center", color: colors.text.tertiary }}>•</span>
                    )}
                    <strong style={{ minWidth: 120 }}>
                      {isLlm ? `LLM · ${it.model ?? "?"}` : it.node}
                    </strong>
                    <span style={{ fontFamily: "monospace", color: colors.text.tertiary }}>
                      {fmtTime(it.ts)}
                    </span>
                    <span style={{ marginLeft: "auto", fontFamily: "monospace", color: colors.text.secondary }}>
                      {isLlm
                        ? `${it.prompt_tokens ?? 0}p / ${it.completion_tokens ?? 0}c tok`
                        : `⏱ ${fmtMs(it.duration_ms)}`}{" "}
                      {isLlm ? `· ⏱ ${fmtMs(it.duration_ms)}` : ""}
                    </span>
                    {!isLlm && it.llm_calls !== undefined && it.llm_calls > 0 && (
                      <span style={{ fontFamily: "monospace", color: colors.brand.linkText }}>
                        · LLM×{it.llm_calls} · tok {it.tokens?.prompt ?? 0}p/{it.tokens?.completion ?? 0}c
                      </span>
                    )}
                    {it.interrupted && (
                      <span style={{ fontSize: font.xs, color: colors.status.caution }}>
                        · interrupt 等待输入
                      </span>
                    )}
                    {it.error && (
                      <span style={{ fontSize: font.xs, color: colors.status.danger }}> · {it.error}</span>
                    )}
                    {hasDetail && <span style={{ color: colors.text.tertiary }}>{open ? "▾" : "▸"}</span>}
                  </div>
                  {open && (
                    <div
                      style={{
                        marginTop: space.sm,
                        padding: space.sm,
                        background: colors.bg.muted,
                        borderRadius: radius.base,
                        fontSize: font.sm,
                      }}
                    >
                      {it.input_summary && (
                        <p style={{ margin: 0, color: colors.text.secondary }}>
                          <strong>输入：</strong>
                          {it.input_summary}
                        </p>
                      )}
                      {it.output_summary && (
                        <p style={{ margin: `${space.xs}px 0 0`, color: colors.text.secondary }}>
                          <strong>输出：</strong>
                          {it.output_summary}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </main>
  );
}
