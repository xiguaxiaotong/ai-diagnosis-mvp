"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Project } from "../../lib/api";
import { useRequireAuth } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { font, radius, space, touch } from "../../lib/tokens";

const STATUS_TEXT: Record<string, string> = {
  diagnosing: "诊断中",
  plan_generated: "方案已生成",
  confirmed: "方案确认",
  delivering: "交付中",
  done: "已完成",
};

export default function ProjectsPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth(); // Day4：未登录 → /login
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<{ items: Project[] }>("/api/projects");
      setProjects(data.items);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(id: number, title: string) {
    // 二次确认，防误触（移动端尤其容易点错）
    if (!window.confirm(`确定删除「${title}」吗？删除后不可恢复。`)) return;
    try {
      await api(`/api/projects/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <main style={{ maxWidth: 720, margin: `${space.pageTop}px auto`, padding: `0 ${space.xl}px` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>历史项目</h1>
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

      {/* 账号隔离提示（#5）：让用户明确知道数据跟着账号走 */}
      <p style={{ margin: `${space.xs}px 0 0`, fontSize: font.xs, color: colors.text.tertiary }}>
        所有项目属于当前账号，切换账号不会看到别的账号项目
      </p>

      {error && (
        <p style={{ color: colors.status.danger, display: "flex", alignItems: "center", gap: space.md, flexWrap: "wrap" }}>
          请求失败：{error}
          <button
            onClick={load}
            style={{
              padding: `${space.sm}px ${space.xl}px`, minHeight: touch.small, fontSize: font.sm,
              background: colors.bg.surface, color: colors.brand.linkText,
              border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.base, cursor: "pointer",
            }}
          >
            重试
          </button>
        </p>
      )}

      {projects === null && !error && <p style={{ color: colors.text.secondary }}>加载中…</p>}

      {projects?.length === 0 && (
        <p style={{ color: colors.text.secondary }}>还没有项目，点右上角新建一个试试</p>
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
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              {/* 按状态直达：诊断中→对话页（可继续点选项卡），已有方案→方案页。
                  不再经过「方案还没生成」中间页 */}
              <Link
                href={p.status === "diagnosing" ? `/chat/${p.id}` : `/project/${p.id}`}
                style={{
                  fontWeight: 600, color: colors.text.primary, textDecoration: "none",
                  display: "inline-block", padding: `${space.xxs}px 0`,
                }}
              >
                {p.title}
              </Link>
              <div style={{ fontSize: font.sm, color: colors.text.secondary, marginTop: space.xxs }}>
                状态：{STATUS_TEXT[p.status] ?? p.status}
                {p.budget_min != null && p.budget_max != null && (
                  <>
                    {" · "}预算区间：¥{p.budget_min} ~ ¥{p.budget_max}
                  </>
                )}
                {p.created_at && (
                  <>
                    {" · "}
                    创建于 {new Date(p.created_at).toLocaleString("zh-CN", {
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