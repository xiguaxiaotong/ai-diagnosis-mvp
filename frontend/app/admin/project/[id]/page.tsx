"use client";

import { ArrowLeft, Bot, ChevronRight, ListTree, ShieldCheck, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { getUser, useRequireAuth } from "../../../../lib/auth";
import { useTheme } from "../../../../lib/theme";
import { font, fontFluid, radius, space, touch } from "../../../../lib/tokens";

interface Module {
  name: string;
  description: string;
  example?: string;
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

interface SolutionPlan {
  project_name: string;
  one_liner?: string;
  business_summary: string;
  core_business_modules: Module[];
  tech_architecture: string;
  tech_stack: TechChoice[];
  glossary?: { term: string; explanation: string }[];
  implementation_phases: string[];
  key_risks: string[];
}

interface SolutionFeasibility {
  overall: string;
  risk_level: string;
  tech_assessment: string;
  schedule_assessment: string;
  budget_assessment: string;
  suggestions: string[];
}

interface AdminProjectDetail {
  id: number;
  title: string;
  raw_idea: string | null;
  status: string;
  budget_min: number | null;
  budget_max: number | null;
  thread_id: string | null;
  user_id: number | null;
  username: string | null;
  user_email: string | null;
  user_name: string | null;
  solution: { plan: SolutionPlan; feasibility?: SolutionFeasibility | null; budget?: any } | null;
  req_profile: any;
  messages: Array<{ id: number; role: string; content: string; created_at: string | null }>;
  created_at: string | null;
  updated_at: string | null;
}

export default function AdminProjectPage() {
  const { colors, borderStyle } = useTheme();
  useRequireAuth();
  const params = useParams();
  const projectId = Number(params.id);

  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [data, setData] = useState<AdminProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsAdmin(getUser()?.is_admin === true);
  }, []);

  const load = useCallback(async () => {
    if (!Number.isFinite(projectId)) return;
    try {
      const r = await api<AdminProjectDetail>(`/api/admin/projects/${projectId}`);
      setData(r);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [projectId]);

  useEffect(() => {
    if (isAdmin !== true) return;
    load();
  }, [isAdmin, load]);

  if (isAdmin === false) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <h1>无权限</h1>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>返回项目列表</Link>
      </main>
    );
  }
  if (isAdmin === null || !data) {
    return (
      <main style={{ maxWidth: 720, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
        <p style={{ color: colors.text.secondary }}>{error ? `加载失败：${error}` : "加载中…"}</p>
      </main>
    );
  }

  const plan = data.solution?.plan;
  const feas = data.solution?.feasibility;

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: space.xl, color: colors.text.primary }}>
      <div style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.lg, flexWrap: "wrap" }}>
        <Link href="/admin/leads" style={{ display: "inline-flex", alignItems: "center", gap: space.xs, color: colors.brand.linkText, textDecoration: "none", fontSize: font.sm }}>
          <ArrowLeft size={16} /> 返回 Leads 列表
        </Link>
      </div>

      <header style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.lg, flexWrap: "wrap" }}>
        <ShieldCheck size={22} color={colors.brand.primary} />
        <h1 style={{ margin: 0, fontSize: font.xl, flex: 1 }}>{data.title}</h1>
        <span style={{
          padding: `${space.xxs}px ${space.sm}px`,
          borderRadius: radius.pill,
          background: colors.status.cautionBg,
          color: colors.status.caution,
          fontSize: font.sm,
          fontWeight: 600,
        }}>
          {data.status}
        </span>
      </header>

      {/* 归属信息 */}
      <section style={{ background: colors.bg.muted, padding: space.md, borderRadius: radius.md, marginBottom: space.lg, fontSize: font.sm, color: colors.text.secondary }}>
        <UserIcon size={14} style={{ verticalAlign: "middle" }} /> 归属用户：
        <strong>{data.username ?? "(已注销)"}</strong>
        {data.user_id && <span style={{ color: colors.text.tertiary }}> (id={data.user_id})</span>}
        {data.user_name && <> · 昵称：{data.user_name}</>}
        {data.user_email && <> · 邮箱：{data.user_email}</>}
        <br />
        创建：{data.created_at ? new Date(data.created_at).toLocaleString("zh-CN") : "—"}
        {" · "}最近更新：{data.updated_at ? new Date(data.updated_at).toLocaleString("zh-CN") : "—"}
        {data.thread_id && <>{" · "}thread_id：<code style={{ fontSize: font.xs }}>{data.thread_id}</code></>}
      </section>

      {/* raw_idea */}
      {data.raw_idea && (
        <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.lg, padding: space.lg, marginBottom: space.lg }}>
          <h2 style={{ margin: `0 0 ${space.sm}`, fontSize: font.lg }}>原始想法</h2>
          <div style={{ color: colors.text.secondary, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
            {data.raw_idea}
          </div>
          {data.budget_min !== null && data.budget_max !== null && (
            <div style={{ marginTop: space.sm, fontSize: font.sm, color: colors.text.tertiary }}>
              预算范围：¥{Math.round(data.budget_min).toLocaleString()} - ¥{Math.round(data.budget_max).toLocaleString()}
            </div>
          )}
        </section>
      )}

      {/* 方案 */}
      {plan ? (
        <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.lg, padding: space.lg, marginBottom: space.lg }}>
          <h2 style={{ margin: `0 0 ${space.md}`, fontSize: font.lg }}>方案（只读）</h2>

          <h3 style={{ marginTop: 0, fontSize: font.base }}>{plan.project_name}</h3>
          {plan.one_liner && (
            <p style={{ color: colors.text.secondary, fontSize: font.sm, marginTop: space.xs }}>
              {plan.one_liner}
            </p>
          )}

          <Block title="业务摘要">{plan.business_summary}</Block>

          {plan.core_business_modules?.length > 0 && (
            <Block title="核心业务模块">
              <ul style={{ paddingLeft: space.lg, margin: 0 }}>
                {plan.core_business_modules.map((m, i) => (
                  <li key={i} style={{ marginBottom: space.xs }}>
                    <strong>{m.name}</strong>{" "}
                    <span style={{ color: colors.text.tertiary, fontSize: font.sm }}>
                      [{m.priority}]
                    </span>
                    <br />
                    <span style={{ color: colors.text.secondary, fontSize: font.sm }}>
                      {m.description}
                    </span>
                  </li>
                ))}
              </ul>
            </Block>
          )}

          <Block title="技术架构">{plan.tech_architecture}</Block>

          {plan.tech_stack?.length > 0 && (
            <Block title="技术栈">
              <ul style={{ paddingLeft: space.lg, margin: 0 }}>
                {plan.tech_stack.map((t, i) => (
                  <li key={i} style={{ marginBottom: space.xs, fontSize: font.sm }}>
                    <strong>{t.layer}</strong>: {t.choice}
                    <span style={{ color: colors.text.tertiary, marginLeft: space.xs }}>
                      — {t.reason}
                    </span>
                  </li>
                ))}
              </ul>
            </Block>
          )}

          {plan.implementation_phases?.length > 0 && (
            <Block title="实施阶段">
              <ol style={{ paddingLeft: space.lg, margin: 0 }}>
                {plan.implementation_phases.map((p, i) => (
                  <li key={i} style={{ marginBottom: space.xs, fontSize: font.sm }}>{p}</li>
                ))}
              </ol>
            </Block>
          )}

          {plan.key_risks?.length > 0 && (
            <Block title="关键风险">
              <ul style={{ paddingLeft: space.lg, margin: 0 }}>
                {plan.key_risks.map((r, i) => (
                  <li key={i} style={{ marginBottom: space.xs, fontSize: font.sm, color: colors.status.warning }}>
                    {r}
                  </li>
                ))}
              </ul>
            </Block>
          )}
        </section>
      ) : (
        <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.lg, padding: space.lg, marginBottom: space.lg, color: colors.text.tertiary }}>
          暂无方案（项目可能还没生成，或用户尚未完成对话）
        </section>
      )}

      {/* 可行性 */}
      {feas && (
        <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.lg, padding: space.lg, marginBottom: space.lg }}>
          <h2 style={{ margin: `0 0 ${space.md}`, fontSize: font.lg }}>可行性评估</h2>
          <div style={{ marginBottom: space.sm }}>
            <strong>总体：</strong>{feas.overall}
            <span style={{ marginLeft: space.sm, padding: `${space.xxs}px ${space.sm}px`, borderRadius: radius.pill, background: colors.status.warningBg, color: colors.status.warning, fontSize: font.xs, fontWeight: 600 }}>
              风险等级 {feas.risk_level}
            </span>
          </div>
          <Block title="技术评估">{feas.tech_assessment}</Block>
          <Block title="进度评估">{feas.schedule_assessment}</Block>
          <Block title="预算评估">{feas.budget_assessment}</Block>
          {feas.suggestions?.length > 0 && (
            <Block title="建议">
              <ul style={{ paddingLeft: space.lg, margin: 0 }}>
                {feas.suggestions.map((s, i) => (
                  <li key={i} style={{ marginBottom: space.xs, fontSize: font.sm }}>{s}</li>
                ))}
              </ul>
            </Block>
          )}
        </section>
      )}

      {/* 对话历史 */}
      <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.lg, padding: space.lg, marginBottom: space.lg }}>
        <div style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.md }}>
          <Bot size={20} color={colors.brand.primary} />
          <h2 style={{ margin: 0, fontSize: font.lg }}>诊断回放</h2>
          <span style={{ marginLeft: "auto", fontSize: font.sm, color: colors.text.tertiary }}>
            共 {data.messages.length} 条
          </span>
        </div>

        {data.messages.length === 0 ? (
          <p style={{ color: colors.text.tertiary }}>暂无对话</p>
        ) : (
          <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data.messages.map((m) => {
              const isUser = m.role === "user";
              const isSystem = m.role === "system";
              const roleText = isUser ? "用户" : isSystem ? "系统" : "AI";
              const roleColor = isUser ? colors.brand.primary
                              : isSystem ? colors.text.tertiary
                              : colors.status.successStrong;
              const bgColor = isUser ? colors.brand.primaryBg
                            : isSystem ? colors.bg.muted
                            : colors.status.successBg;
              return (
                <li
                  key={m.id}
                  style={{
                    padding: space.md,
                    borderRadius: radius.md,
                    background: bgColor,
                    marginBottom: space.sm,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: space.xs, fontSize: font.xs, color: colors.text.secondary, marginBottom: space.xs }}>
                    <strong style={{ color: roleColor }}>{roleText}</strong>
                    <span style={{ marginLeft: "auto" }}>
                      {m.created_at ? new Date(m.created_at).toLocaleString("zh-CN") : ""}
                    </span>
                  </div>
                  <div style={{ color: colors.text.primary, fontSize: font.base, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                    {m.content}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </main>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  const { colors } = useTheme();
  return (
    <div style={{ marginTop: space.md }}>
      <h4 style={{ margin: `0 0 ${space.xs}`, fontSize: font.sm, color: colors.text.secondary, fontWeight: 600 }}>
        <ListTree size={14} style={{ verticalAlign: "middle" }} /> {title}
      </h4>
      <div style={{ color: colors.text.primary, fontSize: font.base, lineHeight: 1.7 }}>
        {children}
      </div>
    </div>
  );
}