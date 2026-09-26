"use client";

import { Search, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Project } from "../../lib/api";
import { useRequireAuth, getUser } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { font, radius, space, touch } from "../../lib/tokens";

const STATUS_TEXT: Record<string, string> = {
  diagnosing: "诊断中",
  plan_generated: "方案已生成",
  confirmed: "方案确认",
  delivering: "交付中",
  done: "已完成",
};

// 状态选项（顺序固定：诊断流程方向从左到右）
const STATUS_FILTERS = [
  "diagnosing",
  "plan_generated",
  "confirmed",
  "delivering",
  "done",
] as const;
type StatusKey = (typeof STATUS_FILTERS)[number];

export default function ProjectsPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth(); // 未登录 → /login
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 筛选状态
  const [query, setQuery] = useState("");
  // W7 Day6：admin 标识走 state（useEffect 里取），不能用 typeof window 直接内联判断——
  // SSR 端 false / 客户端 true 会导致 hydration mismatch（Next.js 报 Text content does not match）
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);
  const [activeStatuses, setActiveStatuses] = useState<Set<StatusKey>>(
    new Set(STATUS_FILTERS), // 默认全选 = 不过滤
  );

  // 拉项目列表（按当前筛选）
  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      // 后端空字符串/缺省 = 不过滤；这里 activeStatuses 为空 / 全选都按「全部」打
      //   - 空 = 用户主动「仅看全部」（chip 全关 → 返 500 项目，不合预期）
      //   - 全选 = 五个都选上 = 同样命中（IN 包含所有状态）
      // 为简化：只要非全选就发；全选视为「不过滤」不发。
      const allOn = activeStatuses.size === STATUS_FILTERS.length;
      if (!allOn && activeStatuses.size > 0) {
        params.set("status", Array.from(activeStatuses).join(","));
      }
      const qs = params.toString();
      const data = await api<{ items: Project[] }>(`/api/projects${qs ? `?${qs}` : ""}`);
      setProjects(data.items);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [query, activeStatuses]);

  // 筛选变化时重新拉（每次 query/status 变都触发）
  useEffect(() => {
    load();
  }, [load]);

  // 切换某个状态 chip
  const toggleStatus = useCallback((s: StatusKey) => {
    setActiveStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  }, []);

  // 是否有筛选（搜索框非空 或 有 chip 关闭）
  const hasFilter = useMemo(
    () => query.trim().length > 0 || activeStatuses.size !== STATUS_FILTERS.length,
    [query, activeStatuses],
  );

  function clearAll() {
    setQuery("");
    setActiveStatuses(new Set(STATUS_FILTERS));
  }

  async function remove(id: number, title: string) {
    if (!window.confirm(`确定删除「${title}」吗？删除后不可恢复。`)) return;
    try {
      await api(`/api/projects/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  // 顶栏「+ 新建诊断」按钮
  const bannerLink = (
    <div style={{ display: "flex", gap: space.sm, alignItems: "center" }}>
      {/* W7 Day5：admin 入口（仅 admin 可见；用 state 避免 hydration mismatch）。
          Day9 起入口指向运营看板 /admin（数据总览 → 各子页） */}
      {isAdmin && (
        <Link
          href="/admin"
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
          运营后台
        </Link>
      )}
      <Link
        href="/"
        style={{
          padding: `${space.sm}px ${space.xl}px`,
          background: colors.brand.primary,
          color: colors.text.inverse,
          borderRadius: radius.base,
          textDecoration: "none",
          fontSize: font.base,
        }}
      >
        + 新建诊断
      </Link>
    </div>
  );

  return (
    <main style={{ maxWidth: 720, margin: `${space.pageTop}px auto`, padding: `0 ${space.xl}px` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>历史项目</h1>
        {bannerLink}
      </div>

      <p style={{ margin: `${space.xs}px 0 ${space.lg}px`, fontSize: font.xs, color: colors.text.tertiary }}>
        所有项目属于当前账号，切换账号不会看到别的账号项目
      </p>

      {/* 筛选条：搜索框 + 状态 chips + 清空按钮 */}
      <section
        aria-label="筛选"
        style={{
          border: borderStyle.card,
          borderRadius: radius.md,
          padding: `${space.lg}px`,
          marginBottom: space.lg,
          background: colors.bg.surface,
          boxShadow: colors.shadow.card,
        }}
      >
        {/* 搜索框 */}
        <div style={{ position: "relative" }}>
          <Search
            size={16}
            strokeWidth={1.5}
            color={colors.text.tertiary}
            style={{
              position: "absolute",
              left: space.md,
              top: "50%",
              transform: "translateY(-50%)",
              pointerEvents: "none",
            }}
            aria-hidden
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索项目标题…"
            aria-label="搜索项目标题"
            style={{
              width: "100%",
              minHeight: touch.large,
              padding: `0 ${space.xxl}px 0 36px`,
              background: colors.bg.muted,
              color: colors.text.primary,
              border: `1px solid ${colors.border.default}`,
              borderRadius: radius.md,
              fontSize: font.lg,
              outline: "none",
            }}
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="清空搜索"
              style={{
                position: "absolute",
                right: space.sm,
                top: "50%",
                transform: "translateY(-50%)",
                width: 28,
                height: 28,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "transparent",
                color: colors.text.tertiary,
                border: "none",
                borderRadius: radius.pill,
                cursor: "pointer",
              }}
            >
              <X size={16} strokeWidth={1.5} />
            </button>
          )}
        </div>

        {/* 状态 chips + 清空 */}
        <div
          style={{
            marginTop: space.md,
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: space.xs,
          }}
        >
          {STATUS_FILTERS.map((s) => {
            const on = activeStatuses.has(s);
            return (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                aria-pressed={on}
                style={{
                  minHeight: 28,
                  padding: `${space.xxs}px ${space.md}px`,
                  fontSize: font.sm,
                  background: on ? colors.brand.primaryBg : "transparent",
                  color: on ? colors.brand.onPrimaryBg : colors.text.secondary,
                  border: `1px solid ${on ? colors.brand.primaryBorderPressed : colors.border.default}`,
                  borderRadius: radius.pill,
                  cursor: "pointer",
                  transition: "all 0.12s ease",
                }}
              >
                {STATUS_TEXT[s]}
              </button>
            );
          })}
          {hasFilter && (
            <button
              onClick={clearAll}
              style={{
                marginLeft: "auto",
                minHeight: 28,
                padding: `${space.xxs}px ${space.md}px`,
                fontSize: font.sm,
                background: "transparent",
                color: colors.brand.linkText,
                border: "none",
                cursor: "pointer",
              }}
            >
              清空筛选
            </button>
          )}
        </div>
      </section>

      {error && (
        <p
          style={{
            color: colors.status.danger,
            display: "flex",
            alignItems: "center",
            gap: space.md,
            flexWrap: "wrap",
          }}
        >
          请求失败：{error}
          <button
            onClick={load}
            style={{
              padding: `${space.sm}px ${space.xl}px`,
              minHeight: touch.small,
              fontSize: font.sm,
              background: colors.bg.surface,
              color: colors.brand.linkText,
              border: `1px solid ${colors.brand.linkText}`,
              borderRadius: radius.base,
              cursor: "pointer",
            }}
          >
            重试
          </button>
        </p>
      )}

      {projects === null && !error && (
        <p style={{ color: colors.text.secondary }}>加载中…</p>
      )}

      {projects?.length === 0 && !error && (
        <div
          style={{
            padding: `${space.xxxl}px ${space.xl}px`,
            textAlign: "center",
            color: colors.text.secondary,
            fontSize: font.sm,
          }}
        >
          {hasFilter ? (
            <>
              <p style={{ margin: 0 }}>没有匹配的项目</p>
              <p style={{ margin: `${space.xs}px 0 0`, color: colors.text.tertiary }}>
                试试清空筛选或换个关键词
              </p>
              <button
                onClick={clearAll}
                style={{
                  marginTop: space.md,
                  padding: `${space.sm}px ${space.xl}px`,
                  minHeight: touch.small,
                  background: colors.bg.surface,
                  color: colors.brand.linkText,
                  border: `1px solid ${colors.brand.linkText}`,
                  borderRadius: radius.base,
                  fontSize: font.sm,
                  cursor: "pointer",
                }}
              >
                清空筛选
              </button>
            </>
          ) : (
            <>还没有项目，点右上角新建一个试试</>
          )}
        </div>
      )}

      <ul style={{ listStyle: "none", padding: 0 }}>
        {projects?.map((p) => (
          <li
            key={p.id}
            style={{
              border: borderStyle.card,
              borderRadius: radius.md,
              padding: `${space.base}px ${space.xl}px`,
              marginBottom: space.base,
              boxShadow: colors.shadow.card,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <Link
                href={p.status === "diagnosing" ? `/chat/${p.id}` : `/project/${p.id}`}
                style={{
                  fontWeight: 600,
                  color: colors.text.primary,
                  textDecoration: "none",
                  display: "inline-block",
                  padding: `${space.xxs}px 0`,
                }}
              >
                {highlightMatch(p.title, query)}
              </Link>
              <div style={{ fontSize: font.sm, color: colors.text.secondary, marginTop: space.xxs }}>
                <span
                  style={{
                    display: "inline-block",
                    padding: `2px ${space.xs}px`,
                    background: colors.brand.primaryBg,
                    color: colors.brand.onPrimaryBg,
                    borderRadius: radius.base,
                    fontSize: font.xs,
                    marginRight: space.xs,
                  }}
                >
                  {STATUS_TEXT[p.status] ?? p.status}
                </span>
                {p.budget_min != null && p.budget_max != null && (
                  <>
                    {" · "}预算区间：¥{p.budget_min} ~ ¥{p.budget_max}
                  </>
                )}
                {p.created_at && (
                  <>
                    {" · "}
                    创建于{" "}
                    {new Date(p.created_at).toLocaleString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </>
                )}
              </div>
            </div>
            <button
              onClick={() => remove(p.id, p.title)}
              aria-label={`删除项目 ${p.title}`}
              style={{
                flexShrink: 0,
                minHeight: touch.base,
                marginLeft: space.base,
                padding: `${space.xs}px ${space.lg}px`,
                fontSize: font.sm,
                background: colors.bg.surface,
                color: colors.status.danger,
                border: `1px solid ${colors.status.danger}`,
                borderRadius: radius.base,
                cursor: "pointer",
              }}
            >
              删除
            </button>
          </li>
        ))}
      </ul>

      <Link href="/" style={{ color: colors.brand.linkText }}>
        ← 返回首页
      </Link>
    </main>
  );
}

/**
 * 把标题里的搜索关键词高亮（前端即时反馈）。
 * 没匹配 = 原样返回；命中 = 用 <mark> 包裹，大小写不敏感。
 * 这里用 mark 是语义化元素（浏览器给黄底），不引新依赖。
 */
function highlightMatch(text: string, q: string): React.ReactNode {
  const query = q.trim();
  if (!query) return text;
  const lower = text.toLowerCase();
  const qLower = query.toLowerCase();
  const idx = lower.indexOf(qLower);
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark
        style={{
          background: "rgba(250, 204, 21, 0.45)", // 黄色半透，三主题通用（不动主题色）
          color: "inherit",
          padding: "0 1px",
          borderRadius: 2,
        }}
      >
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}