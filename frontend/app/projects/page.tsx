"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Project } from "../../lib/api";

const STATUS_TEXT: Record<string, string> = {
  diagnosing: "诊断中",
  plan_generated: "方案已生成",
  confirmed: "方案确认",
  delivering: "交付中",
  done: "已完成",
};

export default function ProjectsPage() {
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
    <main style={{ maxWidth: 720, margin: "60px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>历史项目</h1>
        <Link
          href="/"
          style={{
            padding: "8px 16px",
            background: "#2563eb",
            color: "#fff",
            borderRadius: 6,
            textDecoration: "none",
            fontSize: 14,
          }}
        >
          + 新建诊断
        </Link>
      </div>

      {error && (
        <p style={{ color: "#dc2626", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          请求失败：{error}
          <button
            onClick={load}
            style={{
              padding: "8px 16px", minHeight: 36, fontSize: 13,
              background: "#fff", color: "#2563eb",
              border: "1px solid #2563eb", borderRadius: 6, cursor: "pointer",
            }}
          >
            重试
          </button>
        </p>
      )}

      {projects === null && !error && <p style={{ color: "#646a73" }}>加载中…</p>}

      {projects?.length === 0 && (
        <p style={{ color: "#646a73" }}>还没有项目，点右上角新建一个试试</p>
      )}

      <ul style={{ listStyle: "none", padding: 0 }}>
        {projects?.map((p) => (
          <li
            key={p.id}
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: "12px 16px",
              marginBottom: 12,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <Link
                href={`/project/${p.id}`}
                style={{
                  fontWeight: 600, color: "#111", textDecoration: "none",
                  display: "inline-block", padding: "4px 0",
                }}
              >
                {p.title}
              </Link>
              <div style={{ fontSize: 13, color: "#646a73", marginTop: 4 }}>
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
                minHeight: 40,
                marginLeft: 12,
                padding: "6px 14px",
                fontSize: 13,
                background: "#fff",
                color: "#dc2626",
                border: "1px solid #dc2626",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              删除
            </button>
          </li>
        ))}
      </ul>

      <Link href="/" style={{ color: "#2563eb" }}>
        ← 返回首页
      </Link>
    </main>
  );
}
