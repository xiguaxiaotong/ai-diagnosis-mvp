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

  // 创建一个演示项目（联调验证 CRUD 通路）
  async function createDemo() {
    try {
      await api("/api/projects", {
        method: "POST",
        body: JSON.stringify({
          title: "演示项目：扫码点单小程序",
          raw_idea: "我想给餐饮店做一个扫码点单小程序",
        }),
      });
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function remove(id: number) {
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
        <button
          onClick={createDemo}
          style={{
            padding: "8px 16px",
            background: "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          + 新建演示项目
        </button>
      </div>

      {error && <p style={{ color: "#dc2626" }}>请求失败：{error}</p>}

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
            <div>
              <Link href={`/project/${p.id}`} style={{ fontWeight: 600, color: "#111" }}>
                {p.title}
              </Link>
              <div style={{ fontSize: 13, color: "#646a73", marginTop: 4 }}>
                状态：{STATUS_TEXT[p.status] ?? p.status}
                {p.budget_min != null && p.budget_max != null && (
                  <>
                    {" · "}预算区间：¥{p.budget_min} ~ ¥{p.budget_max}
                  </>
                )}
              </div>
            </div>
            <button
              onClick={() => remove(p.id)}
              style={{
                padding: "6px 12px",
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
