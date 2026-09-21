"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../../lib/api";

interface Module {
  name: string;
  description: string;
  priority: string;
}
interface TechChoice {
  layer: string;
  choice: string;
  reason: string;
}
interface BudgetItem {
  item: string;
  basis: string;
  min_amount: number;
  max_amount: number;
}
interface Detail {
  id: number;
  title: string;
  status: string;
  budget_min: number | null;
  budget_max: number | null;
  solution: {
    requirements: { summary?: string };
    plan: {
      project_name: string;
      business_summary: string;
      core_business_modules: Module[];
      tech_architecture: string;
      tech_stack: TechChoice[];
      implementation_phases: string[];
      key_risks: string[];
    };
    budget: {
      total_min: number;
      total_max: number;
      line_items: BudgetItem[];
      assumptions: string[];
      budget_match: string;
    };
    feasibility: {
      overall: string;
      risk_level: string;
      tech_assessment: string;
      schedule_assessment: string;
      budget_assessment: string;
      suggestions: string[];
    } | null;
    generated_at: string;
  } | null;
}

const PRIORITY_STYLE: Record<string, { bg: string; fg: string; text: string }> = {
  P0: { bg: "#eff6ff", fg: "#2563eb", text: "P0 核心" },
  P1: { bg: "#fff7ed", fg: "#c2410c", text: "P1 重要" },
  P2: { bg: "#f0fdf4", fg: "#15803d", text: "P2 可选" },
};

const RISK_STYLE: Record<string, { bg: string; fg: string }> = {
  低: { bg: "#f0fdf4", fg: "#15803d" },
  中: { bg: "#fffbeb", fg: "#b45309" },
  高: { bg: "#fef2f2", fg: "#b91c1c" },
};

const STATUS_TEXT: Record<string, string> = {
  diagnosing: "需求诊断中",
  plan_generated: "方案待确认",
  confirmed: "方案已确认",
  delivering: "交付中",
  done: "已完成",
};

function yuan(n: number): string {
  return n.toLocaleString("zh-CN");
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params.id);
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviseMode, setReviseMode] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [banner, setBanner] = useState<string | null>(null);

  const load = () =>
    api<Detail>(`/api/project/${projectId}`)
      .then(setD)
      .catch((e) => setError(String(e)));

  useEffect(() => {
    if (projectId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function confirmAction(action: "confirm" | "revise", fb?: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/project/${projectId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ action, feedback: fb }),
      });
      if (action === "confirm") {
        setBanner("✓ 方案已确认，进入交付准备");
      } else {
        setBanner("✓ 修改意见已提交，方案将重新生成");
      }
      setReviseMode(false);
      setFeedback("");
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !d) {
    return (
      <main style={{ maxWidth: 860, margin: "80px auto", textAlign: "center" }}>
        <p style={{ color: "#dc2626" }}>加载失败：{error}</p>
        <Link href="/projects" style={{ color: "#2563eb" }}>← 返回历史项目</Link>
      </main>
    );
  }
  if (!d) {
    return <main style={{ maxWidth: 860, margin: "80px auto", textAlign: "center", color: "#646a73" }}>加载中…</main>;
  }

  const s = d.solution;
  if (!s) {
    return (
      <main style={{ maxWidth: 860, margin: "80px auto", textAlign: "center" }}>
        <h1>{d.title}</h1>
        <p style={{ color: "#646a73", margin: "16px 0 24px" }}>
          方案还没生成——先到对话里完成需求诊断。
        </p>
        <Link
          href={`/chat/${d.id}`}
          style={{ padding: "10px 24px", background: "#2563eb", color: "#fff", borderRadius: 8, textDecoration: "none" }}
        >
          继续诊断 →
        </Link>
      </main>
    );
  }

  const { plan, budget, feasibility } = s;
  const isFinal = d.status === "confirmed" || d.status === "delivering" || d.status === "done";
  const riskStyle = feasibility ? RISK_STYLE[feasibility.risk_level] ?? RISK_STYLE["中"] : null;

  const card = (title: string, node: React.ReactNode) => (
    <section style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 12, padding: "20px 22px", marginBottom: 16 }}>
      <h2 style={{ fontSize: 16, margin: "0 0 14px", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 4, height: 16, background: "#2563eb", borderRadius: 2, display: "inline-block" }} />
        {title}
      </h2>
      {node}
    </section>
  );

  const th: React.CSSProperties = {
    textAlign: "left", padding: "8px 12px", fontSize: 13, color: "#646a73",
    borderBottom: "1px solid #e5e7eb", whiteSpace: "nowrap",
  };
  const td: React.CSSProperties = {
    padding: "8px 12px", fontSize: 13, borderBottom: "1px solid #f3f4f6",
    verticalAlign: "top", lineHeight: 1.6,
  };

  return (
    <main style={{ maxWidth: 860, margin: "0 auto", padding: "24px 16px 48px" }}>
      {/* 头部：标题 + 状态 + 预算区间 */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>{plan.project_name}</h1>
          <span style={{
            fontSize: 12, padding: "3px 10px", borderRadius: 999,
            background: isFinal ? "#f0fdf4" : "#eff6ff",
            color: isFinal ? "#15803d" : "#2563eb",
          }}>
            {STATUS_TEXT[d.status] ?? d.status}
          </span>
        </div>
        <p style={{ fontSize: 13, color: "#646a73", margin: "6px 0 0" }}>
          生成于 {s.generated_at}
          {d.budget_min != null && d.budget_max != null && (
            <> · 预算区间 <b style={{ color: "#1f2329" }}>¥{yuan(d.budget_min)} ~ ¥{yuan(d.budget_max)}</b></>
          )}
        </p>
        <Link href="/projects" style={{ fontSize: 13, color: "#2563eb", textDecoration: "none" }}>← 返回历史项目</Link>
      </div>

      {banner && (
        <p style={{ background: "#f0fdf4", color: "#15803d", border: "1px solid #bbf7d0", borderRadius: 8, padding: "10px 14px", fontSize: 14 }}>{banner}</p>
      )}

      {/* 需求确认摘要 */}
      {s.requirements?.summary &&
        card("需求确认", <p style={{ fontSize: 14, lineHeight: 1.8, margin: 0 }}>{s.requirements.summary}</p>)}

      {/* 业务方案 */}
      {card("业务方案", (
        <>
          <p style={{ fontSize: 14, lineHeight: 1.8, margin: "0 0 14px" }}>{plan.business_summary}</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...th, width: 90 }}>优先级</th>
                <th style={{ ...th, width: 150 }}>模块</th>
                <th style={th}>功能描述</th>
              </tr>
            </thead>
            <tbody>
              {plan.core_business_modules.map((m, i) => {
                const ps = PRIORITY_STYLE[m.priority] ?? PRIORITY_STYLE.P1;
                return (
                  <tr key={i}>
                    <td style={td}>
                      <span style={{ background: ps.bg, color: ps.fg, fontSize: 12, padding: "2px 8px", borderRadius: 6 }}>{ps.text}</span>
                    </td>
                    <td style={{ ...td, fontWeight: 600 }}>{m.name}</td>
                    <td style={td}>{m.description}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      ))}

      {/* 技术方案 */}
      {card("技术方案", (
        <>
          <p style={{ fontSize: 14, lineHeight: 1.8, margin: "0 0 14px" }}>{plan.tech_architecture}</p>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 14 }}>
            <thead>
              <tr>
                <th style={{ ...th, width: 90 }}>层级</th>
                <th style={{ ...th, width: 180 }}>选型</th>
                <th style={th}>理由</th>
              </tr>
            </thead>
            <tbody>
              {plan.tech_stack.map((t, i) => (
                <tr key={i}>
                  <td style={{ ...td, fontWeight: 600 }}>{t.layer}</td>
                  <td style={td}>{t.choice}</td>
                  <td style={{ ...td, color: "#646a73" }}>{t.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 13, margin: "0 0 6px", color: "#646a73" }}>分期实施</p>
          <ol style={{ fontSize: 13, lineHeight: 1.9, margin: "0 0 12px", paddingLeft: 20 }}>
            {plan.implementation_phases.map((p, i) => <li key={i}>{p}</li>)}
          </ol>
          <p style={{ fontSize: 13, margin: "0 0 6px", color: "#646a73" }}>关键风险</p>
          <ul style={{ fontSize: 13, lineHeight: 1.9, margin: 0, paddingLeft: 20 }}>
            {plan.key_risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </>
      ))}

      {/* 预算明细（表格主体） */}
      {card("预算明细", (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>计价项</th>
                <th style={th}>计价依据</th>
                <th style={{ ...th, width: 150, textAlign: "right" }}>金额（元）</th>
              </tr>
            </thead>
            <tbody>
              {budget.line_items.map((b, i) => (
                <tr key={i}>
                  <td style={{ ...td, fontWeight: 600 }}>{b.item}</td>
                  <td style={{ ...td, color: "#646a73", fontSize: 12 }}>{b.basis}</td>
                  <td style={{ ...td, textAlign: "right", whiteSpace: "nowrap" }}>
                    {yuan(b.min_amount)} ~ {yuan(b.max_amount)}
                  </td>
                </tr>
              ))}
              <tr>
                <td style={{ ...td, fontWeight: 700, borderBottom: "none" }} colSpan={2}>合计</td>
                <td style={{ ...td, textAlign: "right", fontWeight: 700, borderBottom: "none", whiteSpace: "nowrap" }}>
                  ¥{yuan(budget.total_min)} ~ ¥{yuan(budget.total_max)}
                </td>
              </tr>
            </tbody>
          </table>
          {budget.assumptions?.length > 0 && (
            <p style={{ fontSize: 12, color: "#646a73", margin: "10px 0 0", lineHeight: 1.8 }}>
              测算假设：{budget.assumptions.join("；")}
            </p>
          )}
          <p style={{ fontSize: 12, color: "#646a73", margin: "4px 0 0" }}>{budget.budget_match}</p>
        </>
      ))}

      {/* 可行性评估 */}
      {feasibility && card("可行性评估", (
        <>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <span style={{ background: "#eff6ff", color: "#2563eb", fontSize: 13, padding: "4px 12px", borderRadius: 8, fontWeight: 600 }}>
              {feasibility.overall}
            </span>
            <span style={{ background: riskStyle!.bg, color: riskStyle!.fg, fontSize: 13, padding: "4px 12px", borderRadius: 8, fontWeight: 600 }}>
              风险 {feasibility.risk_level}
            </span>
          </div>
          <ul style={{ fontSize: 13, lineHeight: 1.9, margin: "0 0 10px", paddingLeft: 20, color: "#374151" }}>
            <li>技术：{feasibility.tech_assessment}</li>
            <li>工期：{feasibility.schedule_assessment}</li>
            <li>预算：{feasibility.budget_assessment}</li>
          </ul>
          {feasibility.suggestions?.length > 0 && (
            <>
              <p style={{ fontSize: 13, margin: "0 0 6px", color: "#646a73" }}>落地建议</p>
              <ol style={{ fontSize: 13, lineHeight: 1.9, margin: 0, paddingLeft: 20 }}>
                {feasibility.suggestions.map((sg, i) => <li key={i}>{sg}</li>)}
              </ol>
            </>
          )}
        </>
      ))}

      {/* 确认 / 修改操作区 */}
      <section style={{
        position: "sticky", bottom: 0, background: "#fff", borderTop: "1px solid #e5e7eb",
        padding: "14px 0", display: "flex", gap: 10, alignItems: "center",
      }}>
        {isFinal ? (
          <p style={{ margin: 0, fontSize: 14, color: "#15803d" }}>✓ 方案已确认</p>
        ) : reviseMode ? (
          <>
            <input
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && feedback.trim() && confirmAction("revise", feedback)}
              placeholder="填写修改意见，如：预算砍到 5 万以内、去掉 App 端…"
              style={{ flex: 1, padding: "10px 12px", fontSize: 14, border: "1px solid #d1d5db", borderRadius: 8, outline: "none" }}
            />
            <button
              onClick={() => confirmAction("revise", feedback)}
              disabled={busy || !feedback.trim()}
              style={{ padding: "10px 18px", background: busy || !feedback.trim() ? "#9ca3af" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              提交修改
            </button>
            <button
              onClick={() => { setReviseMode(false); setFeedback(""); }}
              style={{ padding: "10px 14px", background: "#fff", color: "#646a73", border: "1px solid #d1d5db", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              取消
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => confirmAction("confirm")}
              disabled={busy}
              style={{ padding: "10px 26px", background: busy ? "#9ca3af" : "#16a34a", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              ✓ 确认方案
            </button>
            <button
              onClick={() => setReviseMode(true)}
              disabled={busy}
              style={{ padding: "10px 22px", background: "#fff", color: "#2563eb", border: "1px solid #2563eb", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              ✏️ 需要修改
            </button>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>修改后方案与预算会重新生成</span>
          </>
        )}
      </section>
    </main>
  );
}
