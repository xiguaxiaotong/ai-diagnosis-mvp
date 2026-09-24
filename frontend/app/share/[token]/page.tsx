"use client";

// 方案公开分享页（转化优化）：老板把链接转给合伙人/朋友，
// 无需注册登录即可浏览完整方案。数据来自公开接口 GET /api/share/{token}。
// 只读：无确认/修改/PDF 等操作，刻意不带 raw_idea 与对话记录（隐私）。

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE } from "../../../lib/api";
import { useTheme } from "../../../lib/theme";
import { font, fontFluid, lineHeight, radius, space } from "../../../lib/tokens";
import { BookOpen, Lightbulb, Pin, Share2, TriangleAlert } from "lucide-react";

interface SharedData {
  title: string;
  status: string;
  budget_min: number | null;
  budget_max: number | null;
  created_at: string | null;
  solution: Solution | null;
}

interface Solution {
  plan: {
    project_name: string;
    one_liner: string;
    business_summary: string;
    core_business_modules: { name: string; description: string; example: string; priority: string }[];
    tech_architecture: string;
    tech_stack: { layer: string; choice: string; reason: string }[];
    glossary: { term: string; explanation: string }[];
    implementation_phases: string[];
    key_risks: string[];
  } | null;
  budget: {
    total_min: number;
    total_max: number;
    line_items: { item: string; basis: string; min_amount: number; max_amount: number }[];
    assumptions: string[];
    budget_match: string;
  } | null;
  feasibility: { overall: string; risk_level: string; tech_assessment: string; suggestions: string[] } | null;
  confirmed_pain_points: string[];
  budget_tier: { tier: string; recap: string } | null;
  generated_at: string;
}

const PRIORITY_TEXT: Record<string, string> = { P0: "第一期必做", P1: "第二期建议", P2: "以后再说" };
const RISK_TEXT: Record<string, string> = { "低": "低风险 · 放心做", "中": "中风险 · 有注意点", "高": "高风险 · 要谨慎" };

function yuan(n: number): string {
  return `¥${n >= 10000 ? `${(n / 10000).toFixed(n % 10000 ? 1 : 0)} 万` : n}`;
}

export default function SharedPlanPage() {
  const params = useParams<{ token: string }>();
  const { colors, borderStyle } = useTheme();
  const [d, setD] = useState<SharedData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/share/${params.token}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "分享链接不存在或已失效" : "加载失败");
        return r.json() as Promise<SharedData>;
      })
      .then(setD)
      .catch((e) => setError(String(e.message ?? e)));
  }, [params.token]);

  const card = (title: string, node: React.ReactNode) => (
    <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.xl, padding: `${space.xl}px ${space.xl + 2}px`, marginBottom: space.lg, boxShadow: colors.shadow.card }}>
      <h2 style={{ fontSize: font.lg, margin: `0 0 ${space.base}px`, display: "flex", alignItems: "center", gap: space.sm }}>
        <span style={{ width: space.xxs, height: space.xl, background: colors.brand.primary, borderRadius: radius.xs, display: "inline-block" }} />
        {title}
      </h2>
      {node}
    </section>
  );

  const th: React.CSSProperties = {
    textAlign: "left", padding: `${space.xs}px ${space.base}px`, fontSize: font.sm, color: colors.text.secondary,
    borderBottom: borderStyle.card, whiteSpace: "nowrap",
  };
  const td: React.CSSProperties = {
    padding: `${space.xs}px ${space.base}px`, fontSize: font.sm, borderBottom: borderStyle.row,
    verticalAlign: "top", lineHeight: lineHeight.normal,
  };

  if (error) {
    return (
      <main style={{ maxWidth: 560, margin: "20vh auto 0", padding: `0 ${space.xl}px`, textAlign: "center" }}>
        <Share2 size={40} strokeWidth={1.5} style={{ color: colors.text.tertiary }} />
        <h1 style={{ fontSize: font.xl }}>{error}</h1>
        <p style={{ color: colors.text.secondary }}>请向分享人确认链接是否完整。</p>
      </main>
    );
  }
  if (!d) {
    return (
      <main style={{ maxWidth: 860, margin: "20vh auto 0", textAlign: "center", color: colors.text.secondary }}>
        正在加载方案…
      </main>
    );
  }

  const s = d.solution;
  const plan = s?.plan;
  if (!plan) {
    return (
      <main style={{ maxWidth: 560, margin: "20vh auto 0", padding: `0 ${space.xl}px`, textAlign: "center" }}>
        <h1>{d.title}</h1>
        <p style={{ color: colors.text.secondary }}>该项目的方案还在生成中，请稍后再来看。</p>
      </main>
    );
  }

  const { budget, feasibility } = s;
  const isFree = s.budget_tier?.tier === "free";

  return (
    <main style={{ maxWidth: 860, margin: "0 auto", padding: `${space.xxxl}px ${space.xl}px ${space.huge}px` }}>
      {/* 分享来源说明 */}
      <p style={{ display: "flex", alignItems: "center", gap: space.xs, fontSize: font.xs, color: colors.text.tertiary, margin: `0 0 ${space.lg}px` }}>
        <Share2 size={13} strokeWidth={1.5} />
        来自好友分享的 AI 需求诊断方案 · {d.created_at?.slice(0, 10)}
      </p>

      {/* 一句话总结 */}
      {plan.one_liner && (
        <div style={{
          marginBottom: space.xl, padding: `${space.base}px ${space.lg}px`,
          background: colors.brand.primaryBg, borderRadius: radius.md,
          border: `1px solid ${colors.brand.primaryBorder}`,
        }}>
          <p style={{ margin: 0, fontSize: font.xxl, fontWeight: 700, lineHeight: lineHeight.loose, color: colors.brand.onPrimaryBg, display: "flex", alignItems: "flex-start", gap: space.sm }}>
            <Lightbulb size={18} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 4 }} />
            {plan.one_liner}
          </p>
        </div>
      )}

      {/* 标题 + 预算区间 */}
      <div style={{ marginBottom: space.xl }}>
        <h1 style={{ fontSize: fontFluid.section, margin: 0 }}>{plan.project_name}</h1>
        <p style={{ fontSize: font.sm, color: colors.text.secondary, margin: `${space.xs}px 0 0` }}>
          {isFree ? "免费思路版" : d.budget_min != null && d.budget_max != null
            ? <>预算区间 <b style={{ color: colors.text.primary }}>¥{yuan(d.budget_min)} ~ {yuan(d.budget_max)}</b></>
            : null}
          {s.budget_tier?.recap ? ` · ${s.budget_tier.recap}` : ""}
        </p>
      </div>

      {/* 大白话总结 */}
      {card("这个方案是做什么的", (
        <p style={{ margin: 0, fontSize: font.base, lineHeight: lineHeight.loose, color: colors.text.primary }}>
          {plan.business_summary}
        </p>
      ))}

      {/* 能解决的麻烦 */}
      {s.confirmed_pain_points?.length > 0 && card("能帮你解决这些麻烦", (
        <div>
          {s.confirmed_pain_points.map((p, i) => (
            <p key={i} style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0, display: "flex", gap: space.sm }}>
              <span style={{ color: colors.status.successStrong, flexShrink: 0 }}>✓</span>
              <span>{p}</span>
            </p>
          ))}
        </div>
      ))}

      {/* 业务方案 */}
      {card("功能模块", (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>模块</th>
                <th style={th}>做什么</th>
                <th style={th}>优先级</th>
              </tr>
            </thead>
            <tbody>
              {plan.core_business_modules.map((m, i) => (
                <tr key={i}>
                  <td style={{ ...td, fontWeight: 600, whiteSpace: "nowrap" }}>{m.name}</td>
                  <td style={td}>
                    {m.description}
                    {m.example && (
                      <div style={{ fontSize: font.xs, color: colors.text.tertiary, marginTop: space.xxs }}>
                        例子：{m.example}
                      </div>
                    )}
                  </td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    <span style={{
                      fontSize: font.xs, padding: `${space.xxs - 1}px ${space.md}px`, borderRadius: radius.pill,
                      background: colors.brand.primaryBg, color: colors.brand.onPrimaryBg,
                    }}>
                      {PRIORITY_TEXT[m.priority] ?? m.priority}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {/* 术语小白卡 */}
      {plan.glossary?.length > 0 && card("术语小白卡", (
        <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
          {plan.glossary.map((g, i) => (
            <details key={i} style={{ background: colors.bg.muted, borderRadius: radius.md, padding: `${space.sm}px ${space.md}px` }}>
              <summary style={{ cursor: "pointer", fontSize: font.base, fontWeight: 600, display: "flex", alignItems: "center", gap: space.xs }}>
                <BookOpen size={14} strokeWidth={1.5} style={{ flexShrink: 0 }} /> {g.term}
              </summary>
              <p style={{ margin: `${space.xs}px 0 0`, fontSize: font.sm, lineHeight: lineHeight.loose, color: colors.text.secondary }}>{g.explanation}</p>
            </details>
          ))}
        </div>
      ))}

      {/* 技术方案（折叠） */}
      {card("技术方案（给懂技术的朋友看）", (
        <>
          <p style={{ margin: `0 0 ${space.md}px`, fontSize: font.base, lineHeight: lineHeight.loose }}>{plan.tech_architecture}</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {plan.tech_stack.map((t, i) => (
                <tr key={i}>
                  <td style={{ ...th, width: 80, borderBottom: borderStyle.row }}>{t.layer}</td>
                  <td style={{ ...td, fontWeight: 600, borderBottom: borderStyle.row }}>{t.choice}</td>
                  <td style={{ ...td, color: colors.text.secondary, borderBottom: borderStyle.row }}>{t.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ))}

      {/* 风险提醒 */}
      {plan.key_risks?.length > 0 && card("关键风险提醒", (
        <div>
          {plan.key_risks.map((r, i) => (
            <p key={i} style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0, display: "flex", gap: space.sm }}>
              <TriangleAlert size={15} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 4, color: colors.status.warning }} />
              <span>{r}</span>
            </p>
          ))}
        </div>
      ))}

      {/* 预算明细 */}
      {budget && card("预算明细", (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={th}>项目</th>
                  <th style={th}>依据</th>
                  <th style={th}>费用区间</th>
                </tr>
              </thead>
              <tbody>
                {budget.line_items.map((it, i) => (
                  <tr key={i}>
                    <td style={{ ...td, fontWeight: 600 }}>{it.item}</td>
                    <td style={{ ...td, color: colors.text.secondary }}>{it.basis}</td>
                    <td style={{ ...td, whiteSpace: "nowrap" }}>{yuan(it.min_amount)} ~ {yuan(it.max_amount)}</td>
                  </tr>
                ))}
                <tr>
                  <td style={{ ...td, fontWeight: 700 }}>合计</td>
                  <td style={td} />
                  <td style={{ ...td, fontWeight: 700, whiteSpace: "nowrap" }}>{yuan(budget.total_min)} ~ {yuan(budget.total_max)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          {budget.assumptions?.length > 0 && (
            <p style={{ margin: `${space.md}px 0 0`, fontSize: font.xs, color: colors.text.tertiary, lineHeight: lineHeight.loose }}>
              前提：{budget.assumptions.join("；")}
            </p>
          )}
        </>
      ))}

      {/* 可行性 */}
      {feasibility && card("可行性评估", (
        <>
          <p style={{ margin: `0 0 ${space.base}px`, display: "flex", alignItems: "center", gap: space.sm }}>
            <span style={{
              fontSize: font.sm, fontWeight: 600, padding: `${space.xxs - 1}px ${space.md}px`, borderRadius: radius.pill,
              background: colors.status.successBg, color: colors.status.successStrong,
            }}>
              {RISK_TEXT[feasibility.risk_level] ?? feasibility.risk_level}
            </span>
            <span style={{ fontSize: font.sm, color: colors.text.secondary }}>{feasibility.overall}</span>
          </p>
          <p style={{ margin: 0, fontSize: font.sm, lineHeight: lineHeight.loose, color: colors.text.secondary }}>
            {feasibility.tech_assessment}
          </p>
        </>
      ))}

      {/* 底部：转化入口 */}
      <div style={{
        marginTop: space.xl, padding: `${space.lg}px ${space.base}px`, textAlign: "center",
        background: colors.brand.primaryBg, borderRadius: radius.md, border: `1px solid ${colors.brand.primaryBorder}`,
      }}>
        <p style={{ margin: 0, fontSize: font.base, color: colors.brand.onPrimaryBg, display: "flex", alignItems: "center", justifyContent: "center", gap: space.xs }}>
          <Pin size={15} strokeWidth={1.5} />
          你也有想做的 AI 项目？说说想法，免费拿一份这样的方案
        </p>
        <a
          href="/"
          style={{
            display: "inline-block", marginTop: space.md, padding: `${space.sm}px ${space.xxl}px`,
            background: colors.brand.primary, color: colors.text.inverse, textDecoration: "none",
            borderRadius: radius.md, fontSize: font.base, fontWeight: 600,
          }}
        >
          我也要一份免费方案 →
        </a>
      </div>
      <p style={{ marginTop: space.xl, fontSize: font.xs, color: colors.text.tertiary, textAlign: "center" }}>
        本方案由 AI 需求诊断生成，报价为参考区间 · 分享页只读
      </p>
    </main>
  );
}
