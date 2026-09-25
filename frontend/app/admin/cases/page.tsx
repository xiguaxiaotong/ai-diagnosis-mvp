"use client";

import { BookOpen, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../lib/api";
import { useRequireAuth, getUser } from "../../../lib/auth";
import { useTheme } from "../../../lib/theme";
import { font, radius, space, touch } from "../../../lib/tokens";

interface AdminCase {
  id: number;
  title: string;
  industry: string | null;
  scenario: string | null;
  features: string | null;
  tech_stack: string | null;
  budget_min: number | null;
  budget_max: number | null;
  duration_weeks: string | null;
  source_type: string | null;
  data_quality: string | null;
  review_status: string;
  published: boolean;
  vector_ok: boolean;
  summary: string | null;
  created_at: string | null;
}

interface RetrieveHit {
  title: string;
  industry: string;
  summary: string;
  score: number;
}

// 检索预览结果条数（运营人工核对够用；后端上限 10）
const PREVIEW_TOP_K = 5;

export default function AdminCasesPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();

  const [cases, setCases] = useState<AdminCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // 上下架筛选：null = 全部
  const [pubFilter, setPubFilter] = useState<"all" | "on" | "off">("all");

  // 检索预览
  const [previewQuery, setPreviewQuery] = useState("我想做个能自动回客户咨询的客服");
  const [previewHits, setPreviewHits] = useState<RetrieveHit[] | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // 鉴权：admin gate（hydration 后再判断，防 SSR/客户端不一致）
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (pubFilter === "on") params.set("published", "true");
      if (pubFilter === "off") params.set("published", "false");
      const qs = params.toString();
      const r = await api<{ items: AdminCase[] }>(
        `/api/admin/cases${qs ? "?" + qs : ""}`,
      );
      setCases(r.items);
      setError(null);
    } catch (e) {
      setError(String(e));
      setCases([]);
    }
  }, [query, pubFilter]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  const togglePublish = async (c: AdminCase) => {
    // 乐观更新
    const old = cases;
    if (old) {
      setCases(old.map((x) => (x.id === c.id ? { ...x, published: !c.published } : x)));
    }
    try {
      await api<{ case: AdminCase }>(`/api/admin/cases/${c.id}`, {
        method: "PATCH",
        body: JSON.stringify({ published: !c.published }),
      });
    } catch (e) {
      if (old) setCases(old); // 回滚
      alert("上下架失败：" + String(e));
    }
  };

  const runPreview = async () => {
    if (!previewQuery.trim()) return;
    setPreviewBusy(true);
    setPreviewError(null);
    try {
      const params = new URLSearchParams({
        query: previewQuery.trim(),
        top_k: String(PREVIEW_TOP_K),
      });
      const r = await api<{ items: RetrieveHit[] }>(
        `/api/admin/cases/retrieve-preview?${params.toString()}`,
      );
      setPreviewHits(r.items);
    } catch (e) {
      setPreviewError(String(e));
      setPreviewHits([]);
    } finally {
      setPreviewBusy(false);
    }
  };

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <p style={{ color: colors.text.secondary }}>
          当前账号不在运营白名单中。需要 admin 权限才能访问 <code>/admin/cases</code>。
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
        <BookOpen size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl }}>运营后台 · 案例库管理</h1>
        <Link
          href="/admin/leads"
          style={{
            marginLeft: "auto",
            padding: `${space.sm}px ${space.md}px`,
            background: colors.bg.surface,
            color: colors.brand.linkText,
            border: `1px solid ${colors.brand.primary}`,
            borderRadius: radius.base,
            textDecoration: "none",
            fontSize: font.sm,
            minHeight: touch.base,
            display: "inline-flex",
            alignItems: "center",
          }}
        >
          ← Leads 跟进
        </Link>
      </header>

      {/* 检索预览卡 */}
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
          <Search size={18} color={colors.brand.primary} />
          <h2 style={{ margin: 0, fontSize: font.lg }}>检索预览</h2>
          <span style={{ fontSize: font.sm, color: colors.text.tertiary }}>
            用真实用户问题预演线上召回（只含已上架案例）
          </span>
        </div>
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <input
            type="text"
            value={previewQuery}
            onChange={(e) => setPreviewQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runPreview();
            }}
            placeholder="输入用户会怎么描述需求，如：我想做个客服机器人"
            aria-label="检索预览问题"
            style={{
              flex: "1 1 320px",
              minHeight: touch.base,
              background: colors.bg.muted,
              border: borderStyle.input,
              borderRadius: radius.md,
              padding: `0 ${space.md}px`,
              color: colors.text.primary,
              fontSize: font.base,
              outline: "none",
            }}
          />
          <button
            onClick={runPreview}
            disabled={previewBusy}
            style={{
              minHeight: touch.base,
              padding: `0 ${space.lg}px`,
              background: colors.brand.primary,
              color: colors.text.inverse,
              border: "none",
              borderRadius: radius.md,
              fontSize: font.base,
              fontWeight: 600,
              cursor: previewBusy ? "wait" : "pointer",
            }}
          >
            {previewBusy ? "检索中…" : "预演检索"}
          </button>
        </div>
        {previewError && (
          <p style={{ color: colors.status.danger, marginTop: space.md, marginBottom: 0 }}>
            {previewError}
          </p>
        )}
        {previewHits && (
          <div style={{ marginTop: space.md }}>
            {previewHits.length === 0 ? (
              <p style={{ color: colors.text.secondary, margin: 0 }}>
                无命中（相似度低于阈值，用户会得到兜底话术）
              </p>
            ) : (
              previewHits.map((h, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: space.md,
                    alignItems: "baseline",
                    padding: `${space.sm}px 0`,
                    borderBottom: `1px solid ${colors.border.row}`,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: font.sm,
                      color:
                        h.score >= 0.5
                          ? colors.status.successStrong
                          : h.score >= 0.4
                            ? colors.status.warning
                            : colors.text.tertiary,
                      minWidth: 52,
                    }}
                  >
                    {h.score.toFixed(4)}
                  </span>
                  <span style={{ fontWeight: 600 }}>{h.title}</span>
                  <span style={{ fontSize: font.sm, color: colors.text.tertiary }}>
                    {h.industry}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </section>

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
            placeholder="搜索标题/行业/场景/功能"
            aria-label="搜索案例"
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
          {(
            [
              ["all", "全部"],
              ["on", "已上架"],
              ["off", "已下架"],
            ] as const
          ).map(([key, label]) => {
            const on = pubFilter === key;
            return (
              <button
                key={key}
                onClick={() => setPubFilter(key)}
                aria-pressed={on}
                style={{
                  minHeight: touch.base,
                  padding: `0 ${space.md}px`,
                  background: on ? colors.brand.primaryBg : colors.bg.surface,
                  color: on ? colors.brand.onPrimaryBg : colors.text.secondary,
                  border: `1px solid ${on ? colors.brand.primary : borderStyle.input}`,
                  borderRadius: radius.pill,
                  fontSize: font.sm,
                  cursor: "pointer",
                  fontWeight: on ? 600 : 400,
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {error && <p style={{ color: colors.status.danger, marginBottom: space.md }}>{error}</p>}

      {/* 案例表格 */}
      {cases === null ? (
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      ) : cases.length === 0 ? (
        <p style={{ color: colors.text.secondary, textAlign: "center", padding: space.xxl }}>
          没有匹配的案例
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
              gridTemplateColumns: "2.2fr 1fr 1fr 1.1fr 0.8fr 0.9fr",
              gap: space.sm,
              padding: `${space.md}px ${space.lg}px`,
              background: colors.bg.muted,
              fontSize: font.sm,
              fontWeight: 600,
              color: colors.text.secondary,
              borderBottom: `1px solid ${colors.border.row}`,
            }}
          >
            <div>标题 / 功能</div>
            <div>场景 · 行业</div>
            <div>预算区间</div>
            <div>核验 / 数据口径</div>
            <div>上下架</div>
            <div>创建时间</div>
          </div>
          {cases.map((c) => (
            <div
              key={c.id}
              style={{
                display: "grid",
                gridTemplateColumns: "2.2fr 1fr 1fr 1.1fr 0.8fr 0.9fr",
                gap: space.sm,
                padding: `${space.md}px ${space.lg}px`,
                fontSize: font.base,
                borderBottom: `1px solid ${colors.border.row}`,
                color: colors.text.primary,
                alignItems: "start",
                opacity: c.published ? 1 : 0.55,
              }}
            >
              <div>
                <div style={{ fontWeight: 600 }}>
                  {c.title}
                  {!c.vector_ok && (
                    <span
                      style={{
                        marginLeft: space.xs,
                        fontSize: font.xs,
                        color: colors.status.warning,
                      }}
                      title="vector_id 缺失，检索召回不到，需跑 backfill"
                    >
                      ⚠ 无向量
                    </span>
                  )}
                </div>
                {c.features && (
                  <div
                    style={{
                      fontSize: font.sm,
                      color: colors.text.secondary,
                      maxHeight: 44,
                      overflow: "hidden",
                      lineHeight: 1.4,
                    }}
                  >
                    {c.features}
                  </div>
                )}
              </div>
              <div style={{ fontSize: font.sm }}>
                <div>{c.scenario || "—"}</div>
                <div style={{ color: colors.text.tertiary }}>{c.industry || "—"}</div>
              </div>
              <div style={{ fontSize: font.sm }}>
                {c.budget_min != null && c.budget_max != null ? (
                  c.budget_min === c.budget_max ? (
                    <span>¥{c.budget_min.toLocaleString()}</span>
                  ) : (
                    <span>
                      ¥{c.budget_min.toLocaleString()}–{c.budget_max.toLocaleString()}
                    </span>
                  )
                ) : (
                  <span style={{ color: colors.text.tertiary }}>—</span>
                )}
                {c.duration_weeks && (
                  <div style={{ color: colors.text.tertiary }}>{c.duration_weeks} 周</div>
                )}
              </div>
              <div style={{ fontSize: font.sm }}>
                <span
                  style={{
                    display: "inline-block",
                    padding: `1px ${space.xs}px`,
                    borderRadius: radius.sm,
                    background:
                      c.review_status === "verified"
                        ? colors.status.successBg
                        : colors.status.cautionBg,
                    color:
                      c.review_status === "verified"
                        ? colors.status.successStrong
                        : colors.status.caution,
                    fontWeight: 600,
                    fontSize: font.xs,
                  }}
                >
                  {c.review_status === "verified" ? "已核验" : "待核验"}
                </span>
                {c.data_quality && (
                  <div
                    style={{
                      color: colors.text.tertiary,
                      fontSize: font.xs,
                      maxHeight: 32,
                      overflow: "hidden",
                      lineHeight: 1.4,
                      marginTop: 2,
                    }}
                    title={c.data_quality}
                  >
                    {c.data_quality}
                  </div>
                )}
              </div>
              <div>
                <button
                  onClick={() => togglePublish(c)}
                  aria-label={`案例 ${c.id} ${c.published ? "下架" : "上架"}`}
                  style={{
                    minHeight: touch.base,
                    padding: `0 ${space.md}px`,
                    background: c.published
                      ? colors.status.successBg
                      : colors.bg.muted,
                    color: c.published
                      ? colors.status.successStrong
                      : colors.text.tertiary,
                    border: `1px solid ${c.published ? colors.status.successStrong : borderStyle.input}`,
                    borderRadius: radius.md,
                    fontSize: font.sm,
                    fontWeight: 600,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {c.published ? "上架中" : "已下架"}
                </button>
              </div>
              <div style={{ fontSize: font.sm, color: colors.text.tertiary }}>
                {c.created_at ? new Date(c.created_at).toLocaleDateString("zh-CN") : "—"}
              </div>
            </div>
          ))}
        </div>
      )}

      <p style={{ marginTop: space.lg, color: colors.text.tertiary, fontSize: font.sm }}>
        共 {cases?.length ?? 0} 条 · 下架案例仍保留全部数据，重新上架零成本
      </p>
    </main>
  );
}
