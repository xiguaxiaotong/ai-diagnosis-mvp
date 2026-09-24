"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { useEffect } from "react";
import { api, apiDownload } from "../../../lib/api";
import { isGuest, stashGuestToken, useRequireAuth } from "../../../lib/auth";
import { useTheme } from "../../../lib/theme";
import { useSwipeBack } from "../../../lib/useSwipeBack";
import { BackBar, BACK_BAR_HEIGHT } from "../../../components/BackBar";
import { font, fontFluid, lineHeight, radius, space, touch, type ThemeColors } from "../../../lib/tokens";
import {
  Check, ClipboardCopy, FileDown, Image as ImageIcon, Lightbulb,
  PenLine, Pin, Save, Share2, Target, TriangleAlert, X,
} from "lucide-react";

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
interface Detail {
  id: number;
  title: string;
  status: string;
  budget_min: number | null;
  budget_max: number | null;
  solution: {
    requirements: { summary?: string };
    confirmed_pain_points?: string[];
    budget_tier?: { label?: string; recap?: string; tier?: string } | null;
    plan: {
      project_name: string;
      one_liner?: string;
      business_summary: string;
      core_business_modules: Module[];
      tech_architecture: string;
      tech_stack: TechChoice[];
      glossary?: { term: string; explanation: string }[];
      implementation_phases: string[];
      key_risks: string[];
    };
    budget: {
      total_min: number;
      total_max: number;
      line_items: BudgetItem[];
      assumptions: string[];
      budget_match: string;
    } | null; // 免费思路版没有预算（不报价）
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

/** W7 Day4：对接申请（留资） */
interface Lead {
  id: number;
  project_id: number;
  name: string;
  phone: string;
  company: string | null;
  note: string | null;
  // W7 Day5：5 态跟单状态机（与后端 Lead.ALL_STATUSES 一致）
  status: "pending" | "contacted" | "quoted" | "won" | "closed";
  created_at: string | null;
  updated_at: string | null;
}

const PRIORITY_STYLE = (c: ThemeColors): Record<string, { bg: string; fg: string; text: string }> => ({
  P0: { bg: c.brand.primaryBg, fg: c.brand.primary, text: "P0 核心" },
  P1: { bg: c.status.warningBg, fg: c.status.warning, text: "P1 重要" },
  P2: { bg: c.status.successBg, fg: c.status.successStrong, text: "P2 可选" },
});

const RISK_STYLE = (c: ThemeColors): Record<string, { bg: string; fg: string }> => ({
  低: { bg: c.status.successBg, fg: c.status.successStrong },
  中: { bg: c.status.cautionBg, fg: c.status.caution },
  高: { bg: c.status.dangerBg, fg: c.status.dangerStrong },
});

// 可行性结论/风险等级 → 大白话（产品规则 #二：不给用户看评估报告腔）
const FEAS_TEXT: Record<string, string> = {
  可行: "能做成",
  有条件可行: "基本能做成，但要注意几个点",
  风险较高: "做之前要想清楚，坑不少",
};
const RISK_TEXT: Record<string, string> = {
  低: "风险小",
  中: "有些地方要注意",
  高: "坑比较多，要想清楚",
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

/** 方案未生成且仍在诊断中：直接跳对话页（消灭「继续诊断」中间页） */
function RedirectToChat({ id }: { id: number }) {
  const router = useRouter();
  const { colors } = useTheme();
  useEffect(() => {
    router.replace(`/chat/${id}`);
  }, [id, router]);
  return (
    <main style={{ maxWidth: 860, margin: `${space.pageTopLarge}px auto`, textAlign: "center", color: colors.text.secondary }}>
      正在进入诊断对话…
    </main>
  );
}

/** 方案 → 可读纯文本（复制用，微信发送/粘贴到备忘录都友好） */
function solutionToText(d: Detail): string {
  const s = d.solution;
  if (!s) return "";
  const { plan, budget, feasibility } = s;
  const L: string[] = [];
  L.push(`《${plan.project_name}》AI 需求诊断方案`);
  L.push(`生成于 ${s.generated_at}${d.budget_min != null && d.budget_max != null ? ` · 预算区间 ¥${yuan(d.budget_min)} ~ ¥${yuan(d.budget_max)}` : ""}`);
  // 三段式大白话总结（与方案页顶部一致）
  L.push("", "【大白话总结】");
  if (plan.one_liner) L.push(`一句话总结：${plan.one_liner}`);
  L.push(`① 能干啥：${plan.business_summary}`);
  const solves = s.confirmed_pain_points?.length
    ? s.confirmed_pain_points
    : plan.core_business_modules.filter((m) => m.priority === "P0").map((m) => m.description);
  L.push(`② 能解决的麻烦：`);
  solves.forEach((p) => L.push(`  ✓ ${p}`));
  if (budget) {
    L.push(`③ 花多少钱、多长时间：预算约 ¥${yuan(budget.total_min)} ~ ¥${yuan(budget.total_max)}`
      + (plan.implementation_phases?.length ? `，建议分 ${plan.implementation_phases.length} 步走` : ""));
  } else {
    L.push("③ 下一步怎么做：免费思路版，先用现成免费工具跑起来；想知道花钱开发的价格随时问");
  }
  if (s.requirements?.summary) {
    L.push("", "【需求确认】", s.requirements.summary);
  }
  L.push("", "【业务方案】", plan.business_summary);
  L.push("核心模块：");
  plan.core_business_modules.forEach((m) => {
    L.push(`  · [${m.priority}] ${m.name}——${m.description}`);
    if (m.example) L.push(`    例如：${m.example}`);
  });
  if (plan.glossary?.length) {
    L.push("", "【术语解释】");
    plan.glossary.forEach((g) => L.push(`  · ${g.term}：${g.explanation}`));
  }
  if (budget) {
    L.push("", "【预算明细】");
    budget.line_items.forEach((b) => L.push(`  · ${b.item}：¥${yuan(b.min_amount)} ~ ¥${yuan(b.max_amount)}（${b.basis}）`));
    L.push(`  合计：¥${yuan(budget.total_min)} ~ ¥${yuan(budget.total_max)}`);
    if (budget.assumptions?.length) L.push(`测算假设：${budget.assumptions.join("；")}`);
    L.push(budget.budget_match);
  }
  if (feasibility) {
    L.push("", "【可行性评估】", `总体结论：${feasibility.overall}（风险${feasibility.risk_level}）`);
    L.push(`技术：${feasibility.tech_assessment}`);
    L.push(`工期：${feasibility.schedule_assessment}`);
    L.push(`预算：${feasibility.budget_assessment}`);
    if (feasibility.suggestions?.length) {
      L.push("落地建议：");
      feasibility.suggestions.forEach((g, i) => L.push(`  ${i + 1}. ${g}`));
    }
  }
  if (plan.key_risks?.length) {
    L.push("", "【关键风险提醒】");
    plan.key_risks.forEach((r) => L.push(`  · ${r}`));
  }
  L.push("", "分期实施：");
  plan.implementation_phases.forEach((p, i) => L.push(`  ${i + 1}. ${p}`));
  return L.join("\n");
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params.id);
  const router = useRouter();
  const { colors, borderStyle } = useTheme();
  useRequireAuth(); // Day4：未登录 → /login
  const PRIORITY = PRIORITY_STYLE(colors);
  const RISK = RISK_STYLE(colors);
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviseMode, setReviseMode] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [banner, setBanner] = useState<string | null>(null);
  // W7 Day4：留资 / 工作台
  const [lead, setLead] = useState<Lead | null>(null);
  const [leadLoaded, setLeadLoaded] = useState(false); // 区分「加载中」和「真没有」
  const [leadForm, setLeadForm] = useState({ name: "", phone: "", company: "", note: "" });
  const [showLeadForm, setShowLeadForm] = useState(false);
  const [leadFormErr, setLeadFormErr] = useState<string | null>(null);
  const [submittingLead, setSubmittingLead] = useState(false);
  // 保存/复制相关
  const planRef = useRef<HTMLDivElement>(null);
  const [saved, setSaved] = useState<string | null>(null); // 「已复制」等即时反馈
  // 方案图片预览浮层（dataURL）：微信内置浏览器禁止网页下载文件，
  // 长按图片存相册是唯一通用路径（H5 分享海报的标准做法）
  const [previewImg, setPreviewImg] = useState<string | null>(null);

  // 移动端右滑返回（辅助手势）：固定回该项目诊断对话页（层级路由栈，不跨项目）
  // replace 而非 push：方案→聊天来回穿梭不产生重复历史，浏览器返回不绕圈
  useSwipeBack(useCallback(() => {
    if (d) router.replace(`/chat/${d.id}`);
  }, [d, router]));

  /** 复制纯文本方案（clipboard API + 老 API 兜底） */
  async function copySolution() {
    if (!d) return;
    const text = solutionToText(d);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // iOS 老浏览器兜底：临时 textarea + execCommand
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setSaved("已复制 ✓ 可粘贴到微信 / 备忘录");
    } catch {
      setSaved("复制失败，请长按方案文字手动复制");
    }
    setTimeout(() => setSaved(null), 2500);
  }

  /** 导出 PDF = 后端 reportlab 生成，前端 fetch blob 触发下载（方案A）：
   *  - 前端 html2canvas 手机端黑屏卡死、window.print() 国产浏览器找不到入口（均实测踩坑）；
   *  - 手机点按钮 → 直接下载/打开现成 PDF 文件，零渲染压力；
   *  - Day4 起 PDF 接口要登录态 → 用 apiDownload（fetch 带 Authorization），
   *    不能再 window.location.href 直跳（跳转带不上 token 会 401）；
   *  - 微信内置 WebView 禁止下载文件 → 检测 UA 给出「在浏览器打开」指引。 */
  function exportPdf() {
    if (!d) return;
    if (/MicroMessenger/i.test(navigator.userAgent)) {
      setSaved("微信内无法直接下载：点右上角 ··· 选「在浏览器打开」，再点本按钮即可保存 PDF");
      setTimeout(() => setSaved(null), 6000);
      return;
    }
    setSaved("正在获取 PDF…如未自动下载，请留意通知栏/下载列表");
    apiDownload(`/api/project/${d.id}/pdf`, `方案-${d.solution?.plan?.project_name ?? d.title}.pdf`)
      .then(() => setSaved("PDF 已下载 ✓ 在浏览器下载列表，可直接发微信"))
      .catch((e) => setSaved(`下载失败：${e}（可先「复制方案」保存文字）`))
      .finally(() => setTimeout(() => setSaved(null), 6000));
  }

  /** 方案内容区截图 → PNG：
   *  - 桌面浏览器：触发下载
   *  - 手机/微信：弹出全屏图片浮层，长按图片存相册或转发
   *    （微信 WebView 禁止网页下载，a[download] 点了没反应还误报成功） */
  async function saveImage() {
    if (!planRef.current || !d) return;
    setSaved("正在生成图片…");
    try {
      const { default: html2canvas } = await import("html2canvas");
      const canvas = await html2canvas(planRef.current, {
        scale: 2, // 高清（微信里转发不糊）
        backgroundColor: getComputedStyle(document.body).backgroundColor || "#ffffff",
        useCORS: true,
      });
      const dataUrl = canvas.toDataURL("image/png");
      setPreviewImg(dataUrl); // 手机：长按浮层里的图片保存
      setSaved(null);
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = `方案-${d.solution?.plan.project_name ?? d.title}.png`;
      a.click(); // 桌面浏览器直接下载；微信里被忽略（走浮层长按）
    } catch {
      setSaved("图片生成失败，可先「复制方案」保存文字");
      setTimeout(() => setSaved(null), 3500);
    }
  }

  const load = () =>
    api<Detail>(`/api/project/${projectId}`)
      .then(setD)
      .catch((e) => setError(String(e)));

  /** 生成公开分享链接并复制（转化优化：老板转给合伙人 = 免费传播，无需注册即可看） */
  async function sharePlan() {
    if (!d || busy) return;
    try {
      const r = await api<{ share_token: string }>(`/api/projects/${projectId}/share`, {
        method: "POST",
      });
      const url = `${window.location.origin}/share/${r.share_token}`;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        // 微信内置浏览器等无 clipboard API：老办法兜底
        const ta = document.createElement("textarea");
        ta.value = url;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setSaved("分享链接已复制，发给朋友即可查看（无需注册）");
    } catch (e) {
      setSaved(`生成分享链接失败：${String(e)}`);
    }
  }

  useEffect(() => {
    if (projectId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // W7 Day4：状态变 confirmed 起加载 lead（plan_generated 不查，避免无谓 404）
  useEffect(() => {
    if (!d) return;
    if (d.status === "confirmed" || d.status === "delivering" || d.status === "done") {
      api<{ lead: Lead }>(`/api/projects/${projectId}/lead`)
        .then((r) => setLead(r.lead))
        .catch(() => undefined) // 404 / 401 等都视为「没留资」
        .finally(() => setLeadLoaded(true));
    }
  }, [d?.status, projectId]);

  async function submitLead() {
    if (submittingLead) return;
    setLeadFormErr(null);
    const name = leadForm.name.trim();
    const phone = leadForm.phone.trim();
    if (!name) return setLeadFormErr("请填写姓名");
    if (!/^\d{11}$/.test(phone)) return setLeadFormErr("手机号必须 11 位数字");
    setSubmittingLead(true);
    try {
      const r = await api<{ lead: Lead; project_status: string; is_new: boolean }>(
        `/api/projects/${projectId}/lead`,
        {
          method: "POST",
          body: JSON.stringify({
            name,
            phone,
            company: leadForm.company.trim() || undefined,
            note: leadForm.note.trim() || undefined,
          }),
        },
      );
      setLead(r.lead);
      setLeadLoaded(true);
      setShowLeadForm(false);
      setLeadForm({ name: "", phone: "", company: "", note: "" });
      setBanner(r.is_new ? "✓ 方案已确认，专人 24 小时内联系你" : "✓ 联系方式已更新");
      await load(); // 刷新 d.status → confirmed
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setLeadFormErr(String(e));
    } finally {
      setSubmittingLead(false);
    }
  }

  // 脱敏展示：手机号 138****0001；姓名保留首字「张*」
  function maskPhone(p: string): string {
    return p.length === 11 ? `${p.slice(0, 3)}****${p.slice(6)}` : p;
  }
  function maskName(n: string): string {
    return n.length <= 1 ? n : `${n[0]}${"*".repeat(Math.min(n.length - 1, 3))}`;
  }

  /** 留资表单（在「下一步」点击或「修改联系方式」时展开）。
   *  注意：使用 ProjectPage 闭包内的 state，避免抽成组件触发 hooks 重排。 */
  function renderLeadForm() {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: space.md, width: "100%" }}>
        <p style={{ margin: 0, fontSize: font.base, color: colors.text.primary, fontWeight: 600 }}>
          填联系方式，专人 24 小时内联系你
        </p>
        <p style={{ margin: 0, fontSize: font.xs, color: colors.text.tertiary }}>
          提交后方案自动确认；联系时优先用电话，记得保持手机畅通
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.md }}>
          <input
            value={leadForm.name}
            onChange={(e) => setLeadForm({ ...leadForm, name: e.target.value })}
            placeholder="姓名 *"
            maxLength={64}
            aria-label="姓名"
            style={{ padding: `${space.md}px ${space.base}px`, fontSize: font.base, border: borderStyle.input, borderRadius: radius.md, outline: "none" }}
          />
          <input
            value={leadForm.phone}
            onChange={(e) => setLeadForm({ ...leadForm, phone: e.target.value.replace(/\D/g, "").slice(0, 11) })}
            placeholder="手机号（11 位）*"
            inputMode="numeric"
            maxLength={11}
            aria-label="手机号"
            style={{ padding: `${space.md}px ${space.base}px`, fontSize: font.base, border: borderStyle.input, borderRadius: radius.md, outline: "none" }}
          />
          <input
            value={leadForm.company}
            onChange={(e) => setLeadForm({ ...leadForm, company: e.target.value })}
            placeholder="公司或团队（选填）"
            maxLength={128}
            aria-label="公司或团队"
            style={{ gridColumn: "1 / span 2", padding: `${space.md}px ${space.base}px`, fontSize: font.base, border: borderStyle.input, borderRadius: radius.md, outline: "none" }}
          />
          <textarea
            value={leadForm.note}
            onChange={(e) => setLeadForm({ ...leadForm, note: e.target.value })}
            placeholder="补充需求 / 期望对接时间（选填，500 字内）"
            maxLength={500}
            rows={2}
            aria-label="补充"
            style={{ gridColumn: "1 / span 2", padding: `${space.md}px ${space.base}px`, fontSize: font.base, border: borderStyle.input, borderRadius: radius.md, outline: "none", resize: "vertical", fontFamily: "inherit" }}
          />
        </div>
        {leadFormErr && (
          <p style={{ margin: 0, fontSize: font.sm, color: colors.status.danger }}>{leadFormErr}</p>
        )}
        <div style={{ display: "flex", gap: space.md, alignItems: "center", flexWrap: "wrap" }}>
          <button
            onClick={submitLead}
            disabled={submittingLead}
            style={{ minHeight: touch.large, padding: `${space.md}px ${space.xxl + 6}px`, background: submittingLead ? colors.muted.bg : colors.brand.primary, color: colors.text.inverse, border: "none", borderRadius: radius.md, fontSize: font.base, fontWeight: 600, cursor: "pointer" }}
          >
            {submittingLead ? "提交中…" : "提交对接申请"}
          </button>
          <button
            onClick={() => { setShowLeadForm(false); setLeadFormErr(null); }}
            style={{ minHeight: touch.large, padding: `${space.md}px ${space.xl}px`, background: colors.bg.surface, color: colors.text.secondary, border: borderStyle.input, borderRadius: radius.md, fontSize: font.base, cursor: "pointer" }}
          >
            取消
          </button>
        </div>
      </div>
    );
  }

  async function confirmAction(action: "confirm" | "revise", fb?: string) {
    if (busy) return;
    // 免登录先体验的最后一道闸：保存 / 申请对接 / 提交修改都是「动真格」的动作，
    // 游客到此先去注册（登录后项目自动过户，回来接着点即可）
    if (isGuest()) {
      stashGuestToken();
      router.push(`/login?next=${encodeURIComponent(`/project/${projectId}`)}`);
      return;
    }
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
      <main style={{ maxWidth: 860, margin: `${space.pageTopLarge}px auto`, textAlign: "center" }}>
        <p style={{ color: colors.status.danger }}>加载失败：{error}</p>
        <Link href="/projects" style={{ color: colors.brand.linkText }}>← 返回历史项目</Link>
      </main>
    );
  }
  if (!d) {
    return <main style={{ maxWidth: 860, margin: `${space.pageTopLarge}px auto`, textAlign: "center", color: colors.text.secondary }}>加载中…</main>;
  }

  const s = d.solution;
  if (!s) {
    // 方案未生成：不再显示「继续诊断」中间页，直接跳对话页（列表入口也已按状态直达）
    if (d.status === "diagnosing") {
      return (
        <RedirectToChat id={d.id} />
      );
    }
    return (
      <main style={{ maxWidth: 860, margin: `0 auto`, padding: `${space.pageTopLarge + BACK_BAR_HEIGHT}px ${space.xl}px`, textAlign: "center" }}>
        <BackBar backHref={`/chat/${d.id}`} crumbs={[{ label: "历史项目", href: "/projects" }, { label: d.title }]} />
        <h1>{d.title}</h1>
        <p style={{ color: colors.text.secondary, margin: `${space.xl}px 0 ${space.xxxl}px` }}>
          方案还没生成——先到对话里完成需求诊断。
        </p>
        <Link
          href={`/chat/${d.id}`}
          style={{ padding: `${space.md}px ${space.xxxl}px`, background: colors.brand.primary, color: colors.text.inverse, borderRadius: radius.md, textDecoration: "none" }}
        >
          继续诊断 →
        </Link>
      </main>
    );
  }

  const { plan, budget, feasibility } = s;
  const isFree = s.budget_tier?.tier === "free";
  const isFinal = d.status === "confirmed" || d.status === "delivering" || d.status === "done";
  const riskStyle = feasibility ? RISK[feasibility.risk_level] ?? RISK["中"] : null;

  const card = (title: string, node: React.ReactNode) => (
    <section style={{ background: colors.bg.surface, border: borderStyle.card, borderRadius: radius.xl, padding: `${space.xxl}px ${space.xxl + 2}px`, marginBottom: space.xl, boxShadow: colors.shadow.card }}>
      <h2 style={{ fontSize: font.lg, margin: `0 0 ${space.lg}px`, display: "flex", alignItems: "center", gap: space.sm }}>
        <span style={{ width: space.xxs, height: space.xl, background: colors.brand.primary, borderRadius: radius.xs, display: "inline-block" }} />
        {title}
      </h2>
      {node}
    </section>
  );

  const th: React.CSSProperties = {
    textAlign: "left", padding: `${space.sm}px ${space.base}px`, fontSize: font.sm, color: colors.text.secondary,
    borderBottom: borderStyle.card, whiteSpace: "nowrap",
  };
  const td: React.CSSProperties = {
    padding: `${space.sm}px ${space.base}px`, fontSize: font.sm, borderBottom: borderStyle.row,
    verticalAlign: "top", lineHeight: lineHeight.normal,
  };

  return (
    <main style={{ maxWidth: 860, margin: `0 auto`, padding: `${space.xxxl + BACK_BAR_HEIGHT}px ${space.xl}px ${space.huge}px` }}>
      {/* 全局返回栏：左上角固定悬浮，返回 = 该项目诊断对话页；面包屑可跳历史列表 */}
      <BackBar
        backHref={`/chat/${d.id}`}
        crumbs={[{ label: "历史项目", href: "/projects" }, { label: d.title }]}
      />
      {/* 打印样式（导出 PDF = window.print 原生方案）：
         隐藏所有操作 UI，只保留方案正文，用户在打印窗口「另存为 PDF」 */}
      <style jsx global>{`
        @media print {
          .no-print { display: none !important; }
          body { background: #fff !important; }
          main { max-width: none !important; padding: 0 !important; }
          section { break-inside: avoid; } /* 卡片不跨页截断 */
        }
      `}</style>
      {/* 方案内容区（截图范围：不含底部确认操作栏） */}
      <div ref={planRef}>
      {/* B 组排版 #7：一句话大白话总结置顶 + 本次约定回顾（不用翻聊天记录） */}
      {(plan.one_liner || s.requirements?.summary || s.budget_tier?.recap) && (
        <div style={{
          marginBottom: space.xl, padding: `${space.base}px ${space.lg}px`,
          background: colors.brand.primaryBg, borderRadius: radius.md,
          border: `1px solid ${colors.brand.primaryBorder}`,
        }}>
          {plan.one_liner && (
            <p style={{ margin: 0, fontSize: font.xxl, fontWeight: 700, lineHeight: lineHeight.loose, color: colors.brand.onPrimaryBg, display: "flex", alignItems: "flex-start", gap: space.sm }}>
              <Lightbulb size={18} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 4 }} />
              {plan.one_liner}
            </p>
          )}
          {(s.requirements?.summary || s.budget_tier?.recap) && (
            <p style={{ margin: `${space.xs}px 0 0`, fontSize: font.xs, lineHeight: lineHeight.loose, color: colors.brand.onPrimaryBg, display: "flex", alignItems: "flex-start", gap: space.xs }}>
              <Pin size={13} strokeWidth={1.5} style={{ flexShrink: 0, marginTop: 3 }} />
              本次约定：{[s.requirements?.summary, s.budget_tier?.recap].filter(Boolean).join("；")}
            </p>
          )}
        </div>
      )}
      {/* 头部：标题 + 状态 + 预算区间 */}
      <div style={{ marginBottom: space.xxl }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h1 style={{ fontSize: fontFluid.section, margin: 0 }}>{plan.project_name}</h1>
          <span style={{
            fontSize: font.xs, padding: `${space.xxs - 1}px ${space.md}px`, borderRadius: radius.pill,
            background: isFinal ? colors.status.successBg : colors.brand.primaryBg,
            // 同 Category 1：紫字配紫底看不清，用 onPrimaryBg（深底白字）
            color: isFinal ? colors.status.successStrong : colors.brand.onPrimaryBg,
          }}>
            {STATUS_TEXT[d.status] ?? d.status}
          </span>
        </div>
        <p style={{ fontSize: font.sm, color: colors.text.secondary, margin: `${space.xs}px 0 0` }}>
          生成于 {s.generated_at}
          {d.budget_min != null && d.budget_max != null && (
            <> · 预算区间 <b style={{ color: colors.text.primary }}>¥{yuan(d.budget_min)} ~ ¥{yuan(d.budget_max)}</b></>
          )}
        </p>
      </div>

      {/* 保存方案：普通人要把方案带走（发微信/留档），必须显式提供出口 */}
      <div className="no-print" style={{ display: "flex", gap: space.md, flexWrap: "wrap", marginBottom: space.xxl }}>
        <button
          onClick={copySolution}
          style={{
            minHeight: touch.large, padding: `${space.md}px ${space.xl}px`,
            background: colors.bg.surface, color: colors.brand.linkText,
            border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.md,
            fontSize: font.base, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: space.xs,
          }}
        >
          <ClipboardCopy size={16} strokeWidth={1.5} /> 复制方案文字
        </button>
        <button
          onClick={exportPdf}
          style={{
            minHeight: touch.large, padding: `${space.md}px ${space.xl}px`,
            background: colors.brand.primary, color: "#fff",
            border: "none", borderRadius: radius.md,
            fontSize: font.base, fontWeight: 600, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: space.xs,
          }}
        >
          <FileDown size={16} strokeWidth={1.5} /> 导出 PDF（推荐）
        </button>
        <button
          onClick={saveImage}
          style={{
            minHeight: touch.large, padding: `${space.md}px ${space.xl}px`,
            background: colors.bg.surface, color: colors.brand.linkText,
            border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.md,
            fontSize: font.base, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: space.xs,
          }}
        >
          <ImageIcon size={16} strokeWidth={1.5} /> 保存为图片
        </button>
        <button
          onClick={sharePlan}
          style={{
            minHeight: touch.large, padding: `${space.md}px ${space.xl}px`,
            background: colors.bg.surface, color: colors.brand.linkText,
            border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.md,
            fontSize: font.base, cursor: "pointer",
            display: "inline-flex", alignItems: "center", gap: space.xs,
          }}
        >
          <Share2 size={16} strokeWidth={1.5} /> 生成分享链接
        </button>
        {saved && (
          <span style={{ fontSize: font.sm, color: colors.status.successStrong, alignSelf: "center" }}>{saved}</span>
        )}
      </div>
      <p className="no-print" style={{ fontSize: font.xs, color: colors.text.tertiary, marginTop: `-${space.lg}px`, marginBottom: space.xl, display: "flex", alignItems: "center", gap: space.xs }}>
        <TriangleAlert size={13} strokeWidth={1.5} style={{ flexShrink: 0 }} />
        手机截图只能截到当前屏幕，长方案会被截断——建议用上方按钮导出完整内容再分享
      </p>

      {banner && (
        <p className="no-print" style={{ background: colors.status.successBg, color: colors.status.successStrong, border: `1px solid ${colors.status.successBorder}`, borderRadius: radius.md, padding: `${space.md}px ${space.lg}px`, fontSize: font.base }}>{banner}</p>
      )}

      {/* B 组排版：大白话三段式总结（置顶，普通人 10 秒看懂方案）
          ① 能干啥 ② 解决哪些麻烦（对应确认过的痛点）③ 花多少钱/多长时间 */}
      {card("大白话总结", (
        <div style={{ display: "flex", flexDirection: "column", gap: space.base }}>
          <div>
            <p style={{ fontSize: font.sm, color: colors.text.tertiary, margin: `0 0 ${space.xs}px` }}>① 这个方案能干啥</p>
            <p style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0 }}>{plan.business_summary}</p>
          </div>
          <div>
            <p style={{ fontSize: font.sm, color: colors.text.tertiary, margin: `0 0 ${space.xs}px` }}>② 能帮你解决的麻烦</p>
            {(s.confirmed_pain_points?.length
              ? s.confirmed_pain_points
              : plan.core_business_modules.filter((m) => m.priority === "P0").map((m) => m.description)
            ).map((p, i) => (
              <p key={i} style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0, display: "flex", gap: space.sm }}>
                <span style={{ color: colors.status.successStrong, flexShrink: 0 }}>✓</span>
                <span>{p}</span>
              </p>
            ))}
          </div>
          <div>
            <p style={{ fontSize: font.sm, color: colors.text.tertiary, margin: `0 0 ${space.xs}px` }}>
              {isFree ? "③ 下一步怎么做" : "③ 花多少钱、多长时间"}
            </p>
            {budget ? (
              <p style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0 }}>
                预算约 <b>¥{yuan(budget.total_min)} ~ ¥{yuan(budget.total_max)}</b>
                {plan.implementation_phases?.length > 0 && <>，建议分 <b>{plan.implementation_phases.length}</b> 步走（第一步先做好最核心的功能，其他以后再加）</>}
              </p>
            ) : (
              <p style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0 }}>
                免费思路版，不涉及开发报价。先用上面推荐的现成免费工具跑起来，够用就不花钱；
                想知道花钱开发大概要多少钱，回对话里直接问我
              </p>
            )}
            {s.budget_tier?.recap && (
              <p style={{ fontSize: font.sm, color: colors.text.secondary, margin: `${space.xs}px 0 0`, display: "flex", alignItems: "center", gap: space.xs }}>
                <Target size={14} strokeWidth={1.5} style={{ color: colors.brand.linkText, flexShrink: 0 }} />
                {s.budget_tier.recap}——本方案已按该预算裁剪设计
              </p>
            )}
          </div>
        </div>
      ))}

      {/* B 组排版：术语小白卡（默认折叠，看不懂再点开）——
          普通用户扫一眼卡片标题就知道有这个词典，不读不打扰 */}
      {plan.glossary && plan.glossary.length > 0 && card("看不懂的词？点开看大白话解释", (
        <details style={{ fontSize: font.base }}>
          <summary style={{ cursor: "pointer", color: colors.brand.linkText, fontSize: font.sm, userSelect: "none" }}>
            共 {plan.glossary.length} 个词的解释，点开/收起
          </summary>
          <dl style={{ margin: `${space.base}px 0 0` }}>
            {plan.glossary.map((g) => (
              <div key={g.term} style={{ marginBottom: space.md }}>
                <dt style={{ fontSize: font.base, color: colors.text.primary, fontWeight: 600 }}>{g.term}</dt>
                <dd style={{ margin: `${space.xs}px 0 0`, fontSize: font.sm, lineHeight: lineHeight.loose, color: colors.text.secondary }}>
                  {g.explanation}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      ))}

      {/* 需求确认摘要 */}
      {s.requirements?.summary &&
        card("需求确认", <p style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: 0 }}>{s.requirements.summary}</p>)}

      {/* 业务方案 */}
      {card("业务方案", (
        <>
          <p style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: `0 0 ${space.lg}px` }}>{plan.business_summary}</p>
          <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 480 }}>
            <thead>
              <tr>
                <th style={{ ...th, width: 90 }}>优先级</th>
                <th style={{ ...th, width: 150 }}>模块</th>
                <th style={th}>功能描述</th>
              </tr>
            </thead>
            <tbody>
              {plan.core_business_modules.map((m, i) => {
                const ps = PRIORITY[m.priority] ?? PRIORITY.P1;
                return (
                  <tr key={i}>
                    <td style={td}>
                      <span style={{ background: ps.bg, color: ps.fg, fontSize: font.xs, padding: `${space.xxs - 2}px ${space.sm}px`, borderRadius: radius.base }}>{ps.text}</span>
                    </td>
                    <td style={{ ...td, fontWeight: 600 }}>{m.name}</td>
                    <td style={td}>
                      {m.description}
                      {m.example && (
                        <span style={{ display: "block", marginTop: space.xxs, fontSize: font.xs, color: colors.text.tertiary }}>
                          例如：{m.example}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </>
      ))}

      {/* 技术方案：普通用户默认不看 → 折叠（原生 details，零 JS 成本） */}
      {card("技术方案（技术细节，可点开查看）", (
        <details style={{ fontSize: font.base }}>
          <summary style={{ cursor: "pointer", color: colors.brand.linkText, fontSize: font.sm, userSelect: "none" }}>
            展开技术细节（给技术同学看的，不影响方案使用）
          </summary>
          <p style={{ fontSize: font.base, lineHeight: lineHeight.loose, margin: `${space.base}px 0 ${space.lg}px` }}>{plan.tech_architecture}</p>
          <div style={{ overflowX: "auto", marginBottom: space.lg }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
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
                  <td style={{ ...td, color: colors.text.secondary }}>{t.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <p style={{ fontSize: font.sm, margin: `0 0 ${space.xs}px`, color: colors.text.secondary }}>分期实施</p>
          <ol style={{ fontSize: font.sm, lineHeight: lineHeight.list, margin: `0 0 ${space.base}px`, paddingLeft: space.xxl }}>
            {plan.implementation_phases.map((p, i) => <li key={i}>{p}</li>)}
          </ol>
        </details>
      ))}

      {/* 关键风险：从技术卡里提出来——风险提醒是用户最该看的内容，不折叠 */}
      {plan.key_risks?.length > 0 && card("关键风险提醒", (
        <ul style={{ fontSize: font.base, lineHeight: lineHeight.list, margin: 0, paddingLeft: space.xxl }}>
          {/* 产品规则 #八：风险提示加粗（尤其本地部署数据丢失类警告，力度不能弱） */}
          {plan.key_risks.map((r, i) => <li key={i} style={{ fontWeight: 600 }}>{r}</li>)}
        </ul>
      ))}

      {/* 预算明细（表格主体）——免费思路版没有预算，整卡隐藏 */}
      {budget && card("预算明细", (
        <>
          <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 480 }}>
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
                  <td style={{ ...td, color: colors.text.secondary, fontSize: font.xs }}>{b.basis}</td>
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
          </div>
          {budget.assumptions?.length > 0 && (
            <p style={{ fontSize: font.xs, color: colors.text.secondary, margin: `${space.md}px 0 0`, lineHeight: lineHeight.loose }}>
              测算假设：{budget.assumptions.join("；")}
            </p>
          )}
          <p style={{ fontSize: font.xs, color: colors.text.secondary, margin: `${space.xxs}px 0 0` }}>{budget.budget_match}</p>
        </>
      ))}

      {/* 可行性评估 */}
      {feasibility && card("可行性评估", (
        <>
          <div style={{ display: "flex", gap: space.sm, marginBottom: space.base }}>
            <span style={{ background: colors.brand.primaryBg, color: colors.brand.onPrimaryBg, fontSize: font.sm, padding: `${space.xxs}px ${space.base}px`, borderRadius: radius.md, fontWeight: 600 }}>
              {FEAS_TEXT[feasibility.overall] ?? feasibility.overall}
            </span>
            <span style={{ background: riskStyle!.bg, color: riskStyle!.fg, fontSize: font.sm, padding: `${space.xxs}px ${space.base}px`, borderRadius: radius.md, fontWeight: 600 }}>
              {RISK_TEXT[feasibility.risk_level] ?? `风险 ${feasibility.risk_level}`}
            </span>
          </div>
          <ul style={{ fontSize: font.sm, lineHeight: lineHeight.list, margin: `0 0 ${space.md}px`, paddingLeft: space.xxl, color: colors.text.tertiary }}>
            <li>技术：{feasibility.tech_assessment}</li>
            <li>工期：{feasibility.schedule_assessment}</li>
            <li>预算：{budget ? feasibility.budget_assessment : "免费思路版，不涉及开发报价"}</li>
          </ul>
          {feasibility.suggestions?.length > 0 && (
            <>
              <p style={{ fontSize: font.sm, margin: `0 0 ${space.xs}px`, color: colors.text.secondary }}>落地建议</p>
              <ol style={{ fontSize: font.sm, lineHeight: lineHeight.list, margin: 0, paddingLeft: space.xxl }}>
                {feasibility.suggestions.map((sg, i) => <li key={i}>{sg}</li>)}
              </ol>
            </>
          )}
        </>
      ))}

      {/* 确认 / 修改 / 留资 操作区 */}
      </div>{/* /planRef（截图范围结束，操作栏不入图） */}
      <section className="no-print" style={{
        position: "sticky", bottom: 0, background: colors.bg.surface, borderTop: borderStyle.card,
        padding: `${space.lg}px 0 calc(${space.lg}px + env(safe-area-inset-bottom))`,
        display: "flex", gap: space.md, alignItems: "center", flexWrap: "wrap",
      }}>
        {isFinal ? (
          // === 工作台视图：status >= confirmed ===
          // 已留资：展示 lead 卡 + 修改 + 回对话；未留资：兜底表单（正常流程不会到这里）
          !leadLoaded ? (
            <p style={{ margin: 0, fontSize: font.sm, color: colors.text.secondary }}>加载联系方式中…</p>
          ) : lead ? (
            <div style={{ display: "flex", flexDirection: "column", gap: space.md, width: "100%" }}>
              {/* lead 状态卡 */}
              <div style={{
                display: "flex", gap: space.lg, flexWrap: "wrap", alignItems: "center",
                padding: `${space.base}px ${space.lg}px`,
                background: colors.status.successBg,
                border: `1px solid ${colors.status.successBorder}`,
                borderRadius: radius.md,
              }}>
                <span style={{ fontSize: font.lg, color: colors.status.successStrong, fontWeight: 600 }}>
                  ✓ 方案已确认，专人 24 小时内联系你
                </span>
                <span style={{ fontSize: font.sm, color: colors.text.secondary }}>
                  {maskName(lead.name)} · {maskPhone(lead.phone)}
                  {lead.company && ` · ${lead.company}`}
                </span>
                <span style={{
                  marginLeft: "auto", fontSize: font.xs, padding: `${space.xxs}px ${space.sm}px`,
                  borderRadius: radius.pill,
                  background: lead.status === "won" ? colors.status.successBg :
                              lead.status === "contacted" ? colors.brand.primaryBg :
                              lead.status === "quoted" ? colors.status.warningBg :
                              lead.status === "closed" ? colors.bg.muted :
                              colors.status.cautionBg,
                  color: lead.status === "won" ? colors.status.successStrong :
                         lead.status === "contacted" ? colors.brand.onPrimaryBg :
                         lead.status === "quoted" ? colors.status.warning :
                         lead.status === "closed" ? colors.text.tertiary :
                         colors.status.caution,
                }}>
                  {lead.status === "pending" ? "待联系"
                    : lead.status === "contacted" ? "已联系"
                    : lead.status === "quoted" ? "已报价"
                    : lead.status === "won" ? "已成交"
                    : "已关闭"}
                </span>
              </div>
              {lead.note && (
                <p style={{ margin: 0, fontSize: font.sm, color: colors.text.secondary, lineHeight: lineHeight.loose }}>
                  <b style={{ color: colors.text.primary }}>补充：</b>{lead.note}
                </p>
              )}
              {/* 操作按钮 */}
              <div style={{ display: "flex", gap: space.md, flexWrap: "wrap", alignItems: "center" }}>
                {!showLeadForm && (
                  <button
                    onClick={() => {
                      setLeadForm({
                        name: lead.name,
                        phone: lead.phone,
                        company: lead.company ?? "",
                        note: lead.note ?? "",
                      });
                      setShowLeadForm(true);
                    }}
                    style={{ minHeight: touch.large, padding: `${space.md}px ${space.xl}px`, background: colors.bg.surface, color: colors.brand.linkText, border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.md, fontSize: font.base, cursor: "pointer" }}
                  >
                    修改联系方式
                  </button>
                )}
                <Link
                  href={`/chat/${d.id}`}
                  style={{ minHeight: touch.large, padding: `${space.md}px ${space.xl}px`, background: colors.bg.surface, color: colors.text.secondary, border: borderStyle.input, borderRadius: radius.md, fontSize: font.base, textDecoration: "none", display: "inline-flex", alignItems: "center" }}
                >
                  查看诊断对话
                </Link>
              </div>
            </div>
          ) : (
            // leadLoaded=true 但 lead=null：兜底（数据库丢了 lead）—— 引导补录
            <div style={{ display: "flex", flexDirection: "column", gap: space.md, width: "100%" }}>
              <p style={{ margin: 0, fontSize: font.base, color: colors.status.warning }}>
                方案已确认，但联系方式未保存，请补录
              </p>
              {showLeadForm ? renderLeadForm() : (
                <button
                  onClick={() => setShowLeadForm(true)}
                  style={{ minHeight: touch.large, padding: `${space.md}px ${space.xl + 2}px`, background: colors.brand.primary, color: colors.text.inverse, border: "none", borderRadius: radius.md, fontSize: font.base, cursor: "pointer" }}
                >
                  补录联系方式
                </button>
              )}
            </div>
          )
        ) : reviseMode ? (
          <>
            <input
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && feedback.trim() && confirmAction("revise", feedback)}
              placeholder="填写修改意见，如：预算砍到 5 万以内、去掉 App 端…"
              style={{ flex: 1, minWidth: 160, padding: `${space.md}px ${space.base}px`, fontSize: font.lg, border: borderStyle.input, borderRadius: radius.md, outline: "none" }}
            />
            <button
              onClick={() => confirmAction("revise", feedback)}
              disabled={busy || !feedback.trim()}
              style={{ minHeight: touch.large, padding: `${space.md}px ${space.xl + 2}px`, background: busy || !feedback.trim() ? colors.muted.bg : colors.brand.primary, color: colors.text.inverse, border: "none", borderRadius: radius.md, fontSize: font.base, cursor: "pointer" }}
            >
              提交修改
            </button>
            <button
              onClick={() => { setReviseMode(false); setFeedback(""); }}
              style={{ minHeight: touch.large, padding: `${space.md}px ${space.lg}px`, background: colors.bg.surface, color: colors.text.secondary, border: borderStyle.input, borderRadius: radius.md, fontSize: font.base, cursor: "pointer" }}
            >
              取消
            </button>
          </>
        ) : showLeadForm && !isFree ? (
          renderLeadForm()
        ) : (
          <>
            {/* 免费思路版：保存方案就够，不引导留资（产品规则 #六） */}
            {!isFree ? (
              <button
                onClick={() => setShowLeadForm(true)}
                disabled={busy}
                style={{ minHeight: touch.large, padding: `${space.md}px ${space.xxl + 6}px`, background: busy ? colors.muted.bg : colors.status.success, color: colors.text.inverse, border: "none", borderRadius: radius.md, fontSize: font.base, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: space.xs }}
              >
                <Check size={16} strokeWidth={2} />
                下一步：填联系方式
              </button>
            ) : (
              <button
                onClick={() => confirmAction("confirm")}
                disabled={busy}
                style={{ minHeight: touch.large, padding: `${space.md}px ${space.xxl + 6}px`, background: busy ? colors.muted.bg : colors.status.success, color: colors.text.inverse, border: "none", borderRadius: radius.md, fontSize: font.base, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: space.xs }}
              >
                <Save size={16} strokeWidth={1.5} /> 保存这份方案
              </button>
            )}
            <button
              onClick={() => setReviseMode(true)}
              disabled={busy}
              style={{ minHeight: touch.large, padding: `${space.md}px ${space.xxl + 2}px`, background: colors.bg.surface, color: colors.brand.linkText, border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.md, fontSize: font.base, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: space.xs }}
            >
              <PenLine size={16} strokeWidth={1.5} /> 修改我的需求
            </button>
            <span style={{ fontSize: font.xs, color: colors.text.tertiary }}>修改后方案与预算会重新生成</span>
          </>
        )}
      </section>

      {/* 方案图片全屏浮层：长按图片 → 存相册 / 转发微信
         （微信 WebView 禁止网页下载文件，长按是移动端唯一通用保存方式） */}
      {previewImg && (
        <div
          className="no-print"
          onClick={() => setPreviewImg(null)}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(0,0,0,0.92)",
            display: "flex", flexDirection: "column", alignItems: "center",
            padding: `${space.xl}px ${space.lg}px calc(${space.xl}px + env(safe-area-inset-bottom))`,
          }}
        >
          <div style={{
            width: "100%", display: "flex", justifyContent: "space-between",
            alignItems: "center", marginBottom: space.md,
          }}>
            <span style={{ color: "#fff", fontSize: font.sm }}>
              长按图片 → 保存到相册 或 转发给朋友
            </span>
            <button
              onClick={() => setPreviewImg(null)}
              aria-label="关闭预览"
              style={{
                minHeight: touch.large, minWidth: touch.large,
                background: "none", border: "none", color: "#fff",
                cursor: "pointer", lineHeight: 1,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              <X size={22} strokeWidth={1.5} />
            </button>
          </div>
          <img
            src={previewImg}
            alt="方案长图（长按保存）"
            onClick={(e) => e.stopPropagation()} // 点图片不关浮层，方便长按
            style={{
              maxWidth: "100%", width: "100%", objectFit: "contain",
              borderRadius: radius.md, maxHeight: "calc(100dvh - 140px)",
            }}
          />
        </div>
      )}
    </main>
  );
}