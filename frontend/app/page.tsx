"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, API_BASE } from "../lib/api";

export default function Home() {
  const router = useRouter();
  const [idea, setIdea] = useState("");
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 联调：检测后端健康状态
  useEffect(() => {
    fetch(`${API_BASE}/api/health`)
      .then((r) => setBackendOk(r.ok))
      .catch(() => setBackendOk(false));
  }, []);

  // 创建新诊断项目：title 取想法前 20 字，raw_idea 存全文
  async function startDiagnosis() {
    const text = idea.trim();
    if (!text || creating) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api<{ id: number }>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ title: text.slice(0, 20), raw_idea: text }),
      });
      router.push(`/chat/${project.id}`);
    } catch (e) {
      setError(String(e));
      setCreating(false);
    }
  }

  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "96px 16px 64px",
        textAlign: "center",
      }}
    >
      <p
        style={{
          display: "inline-block",
          fontSize: 13,
          color: "#2563eb",
          background: "#eff6ff",
          borderRadius: 999,
          padding: "4px 14px",
          marginBottom: 20,
        }}
      >
        AI 需求诊断 · 方案生成 · 预算评估
      </p>
      <h1 style={{ fontSize: 36, marginBottom: 12, letterSpacing: 1 }}>
        把你的想法，变成可落地的方案
      </h1>
      <p style={{ color: "#646a73", marginBottom: 32, fontSize: 15 }}>
        描述你的业务需求，AI 结合相似案例帮你生成方案、预算与可行性评估
      </p>

      <div
        style={{
          display: "flex",
          gap: 12,
          maxWidth: 640,
          margin: "0 auto 12px",
        }}
      >
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              startDiagnosis();
            }
          }}
          placeholder="例如：我想给连锁餐饮店做一个扫码点单小程序，支持会员储值…"
          rows={3}
          style={{
            flex: 1,
            padding: "12px 14px",
            fontSize: 15,
            border: "1px solid #d1d5db",
            borderRadius: 10,
            resize: "vertical",
            outline: "none",
            fontFamily: "inherit",
          }}
        />
      </div>
      <div style={{ marginBottom: 24 }}>
        <button
          onClick={startDiagnosis}
          disabled={!idea.trim() || creating || backendOk === false}
          style={{
            padding: "12px 36px",
            fontSize: 15,
            background: backendOk === false ? "#9ca3af" : "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 10,
            cursor:
              !idea.trim() || creating || backendOk === false
                ? "not-allowed"
                : "pointer",
          }}
        >
          {creating ? "创建中…" : "开始新诊断"}
        </button>
      </div>

      {error && <p style={{ color: "#dc2626", fontSize: 14 }}>创建失败：{error}</p>}

      <p style={{ marginBottom: 8, fontSize: 14 }}>
        后端状态：{" "}
        {backendOk === null ? (
          <span style={{ color: "#646a73" }}>检测中…</span>
        ) : backendOk ? (
          <span style={{ color: "#16a34a" }}>● 已连接</span>
        ) : (
          <span style={{ color: "#dc2626" }}>● 未连接（请先启动后端 :8000）</span>
        )}
      </p>

      <a
        href="/projects"
        style={{ color: "#2563eb", fontSize: 14, textDecoration: "none" }}
      >
        查看历史项目 →
      </a>
    </main>
  );
}
