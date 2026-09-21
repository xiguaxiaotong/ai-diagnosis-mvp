"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

export default function Home() {
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  // 联调：检测后端健康状态
  useEffect(() => {
    fetch(`${API_BASE}/api/health`)
      .then((r) => setBackendOk(r.ok))
      .catch(() => setBackendOk(false));
  }, []);

  return (
    <main style={{ maxWidth: 720, margin: "80px auto", textAlign: "center" }}>
      <h1 style={{ fontSize: 32, marginBottom: 12 }}>AI 诊断 MVP</h1>
      <p style={{ color: "#646a73", marginBottom: 16 }}>
        描述你的需求，AI 帮你生成方案、预算与可行性评估
      </p>
      <p style={{ marginBottom: 40, fontSize: 14 }}>
        后端状态：{" "}
        {backendOk === null ? (
          <span style={{ color: "#646a73" }}>检测中…</span>
        ) : backendOk ? (
          <span style={{ color: "#16a34a" }}>● 已连接</span>
        ) : (
          <span style={{ color: "#dc2626" }}>● 未连接（请先启动后端 :8000）</span>
        )}
      </p>
      <div style={{ display: "flex", gap: 16, justifyContent: "center" }}>
        <Link
          href="/chat/new"
          style={{
            padding: "12px 28px",
            background: "#2563eb",
            color: "#fff",
            borderRadius: 8,
            textDecoration: "none",
          }}
        >
          开始新诊断
        </Link>
        <Link
          href="/projects"
          style={{
            padding: "12px 28px",
            background: "#fff",
            color: "#2563eb",
            border: "1px solid #2563eb",
            borderRadius: 8,
            textDecoration: "none",
          }}
        >
          历史项目
        </Link>
      </div>
    </main>
  );
}
