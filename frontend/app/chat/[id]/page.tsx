"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE } from "../../../lib/api";
import { getToken, handle401, useRequireAuth } from "../../../lib/auth";
import { useTheme } from "../../../lib/theme";
import { useSwipeBack } from "../../../lib/useSwipeBack";
import { font, lineHeight, radius, space, touch } from "../../../lib/tokens";
import { Check, Cog, History, Lightbulb, Paperclip, PenLine, Pin, Target, X } from "lucide-react";

type Msg = { role: "user" | "assistant"; content: string };

/** 历史消息里的文件上传消息 → 摘要显示（文件全文太长，不直接渲染） */
function fileTagOf(content: string): string | null {
  const m = content.match(/^\[用户上传文件「(.+?)」（提取 (\d+) 字）\]/);
  return m ? `附件：${m[1]}（AI 已读取 ${m[2]} 字）` : null;
}

/** 追问消息（ask 节点固定格式：引导句 + 编号问题列表）→ 旁白小框渲染 */
function clarifyBubbleOf(content: string): { lead: string; items: string[] } | null {
  const m = content.match(/^(为了给您[^：\n]*：)\s*\n((?:\s*\d+\..+\n?)+)\s*$/);
  if (!m) return null;
  const items = m[2]
    .split("\n")
    .map((s) => s.replace(/^\s*\d+\.\s*/, "").trim())
    .filter(Boolean);
  return items.length ? { lead: m[1], items } : null;
}

interface ReqProfile {
  requirements?: { missing_info?: string[]; question_details?: { question: string; examples: { label: string; note: string }[] }[] };
  clarify_questions?: string[];
  question_details?: { question: string; examples: { label: string; note: string }[] }[];
  pain_points?: string[];
  confirmed_pain_points?: string[];
  budget_tier?: { tier: string; label: string; recap: string } | null;
}

interface ProjectDetail {
  id: number;
  title: string;
  raw_idea: string | null;
  status: string;
  solution: Record<string, unknown> | null;
  req_profile?: ReqProfile | null;
  messages: { id: number; role: string; content: string }[];
}

const STATUS_TEXT: Record<string, string> = {
  diagnosing: "需求诊断中",
  plan_generated: "方案待确认",
  confirmed: "方案已确认",
  delivering: "交付中",
  done: "已完成",
};

export default function ChatPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);
  const { colors, borderStyle } = useTheme();
  useRequireAuth(); // Day4：未登录 → /login

  const [title, setTitle] = useState("诊断对话");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamBuf, setStreamBuf] = useState<string | null>(null); // 流式中的助手回复
  const [phase, setPhase] = useState<string>("clarify");
  const [questions, setQuestions] = useState<string[]>([]);
  const [activeQuestion, setActiveQuestion] = useState<string | null>(null); // 当前正在回答的追问
  const [file, setFile] = useState<File | null>(null); // 待上传附件
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [reviseMode, setReviseMode] = useState(false);
  const [confirmBanner, setConfirmBanner] = useState(false);
  const [stage, setStage] = useState<string | null>(null); // 后端图执行阶段提示
  const [waitSec, setWaitSec] = useState(0); // 已等待秒数
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // P8 约束回顾（预算档位横幅）：后端每轮 meta 事件下发
  const [constraints, setConstraints] = useState<{ recap: string; label: string } | null>(null);
  // A 组交互升级：问题示例点选 + 痛点勾选
  const [questionDetails, setQuestionDetails] = useState<{ question: string; examples: { label: string; note: string }[] }[]>([]);
  // 选项单选状态：{问题: 选中label}——同组替换、跨组独立
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [painPoints, setPainPoints] = useState<string[]>([]);
  const [painChecked, setPainChecked] = useState<Set<string>>(new Set());
  const [painConfirmed, setPainConfirmed] = useState(false);
  const [restored, setRestored] = useState(false); // 重进会话已恢复上次填写（顶部提示条）
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef(false); // raw_idea 自动首发守卫（StrictMode 双执行防重）
  const busyRef = useRef(false); // 双击/重提交同步守卫（React state 异步生效前的 race window）
  const loadedForRef = useRef<number | null>(null); // 每个项目只加载一次（防二次执行覆盖 msgs）

  // 移动端右滑返回（辅助手势）：固定回历史项目列表，发送中停用防误滑中断流
  useSwipeBack(
    useCallback(() => router.push("/projects"), [router]),
    !busy,
  );

  // 初始加载：历史消息 + 根据 solution 恢复阶段
  useEffect(() => {
    if (!projectId || loadedForRef.current === projectId) return;
    loadedForRef.current = projectId;
    api<ProjectDetail>(`/api/projects/${projectId}`)
      .then((d) => {
        setTitle(d.title);
        setMsgs(
          d.messages
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({ role: m.role as Msg["role"], content: m.content })),
        );
        if (d.solution) {
          setPhase(d.status === "diagnosing" ? "confirm_wait" : "done");
        }
        // 重进历史会话：从 req_profile 快照恢复选项卡/痛点卡/约束横幅
        // （此前这些只在 SSE meta 里下发，刷新后选项卡直接消失）
        const rp = d.req_profile;
        if (rp && d.status === "diagnosing" && !d.solution) {
          const qs = rp.clarify_questions?.length
            ? rp.clarify_questions
            : rp.requirements?.missing_info ?? [];
          if (qs.length) setQuestions(qs);
          // 优先用快照顶层的 question_details；旧快照退回 requirements 内的
          const qd = rp.question_details?.length
            ? rp.question_details
            : rp.requirements?.question_details ?? [];
          if (qd.length) setQuestionDetails(qd);
          if (rp.pain_points?.length) {
            setPainPoints(rp.pain_points);
            setPainChecked((prev) => (prev.size ? prev : new Set(rp.pain_points)));
          }
          if (rp.confirmed_pain_points?.length) setPainConfirmed(true);
          if (rp.budget_tier?.recap) {
            setConstraints({ recap: rp.budget_tier.recap, label: rp.budget_tier.label });
          }
          if (qs.length || rp.confirmed_pain_points?.length) setRestored(true);
        }
        setLoaded(true);
        // 关键：首页收集的想法还没进过对话 → 自动作为第一条消息发给 AI，
        // 否则用户会以为 AI 在诊断、实际在干等（首条对话为空且从未发过才触发）
        if (!autoSentRef.current && d.raw_idea && d.messages.length === 0) {
          autoSentRef.current = true;
          send(d.raw_idea);
        }
      })
      .catch((e) => {
        setError(String(e));
        setLoaded(true);
      });
  }, [projectId]);

  // 新消息/流式输出时滚到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, streamBuf, busy]);

  // 等待计时：busy 期间每秒 +1，让用户知道系统在响应而非卡死
  useEffect(() => {
    if (!busy) return;
    setWaitSec(0);
    const t = setInterval(() => setWaitSec((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  /** 解析 SSE 字节流，逐事件回调 */
  async function readSSE(resp: Response, onEvent: (evt: Record<string, unknown>) => void) {
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(part.slice(6)));
        } catch {
          // 忽略不完整事件
        }
      }
    }
  }

  /** 发送一条消息（走 /api/chat 或带文件的 /api/chat/upload，SSE 流式）
   *  opts.explicitConfirm：用户主动点「确认方案」→ 完成后展示横幅并跳方案页；
   *  满轮强制收尾等非主动确认的 done 不跳页（不擅自替用户当作已确认）。
   *  file：附件（txt/docx/pdf/图片），后端提取文本后作为消息上下文。 */
  const send = useCallback(async (text: string, opts?: { explicitConfirm?: boolean }, file?: File | null) => {
    const message = text.trim();
    // busyRef 是同步 ref，挡住 React state 异步生效前的双击 race window
    if ((!message && !file) || busy || busyRef.current) return;
    busyRef.current = true;
    setError(null);
    setBusy(true);
    setInput("");
    setQuestions([]);
    setRestored(false); // 发送后撤掉「已加载上次填写」提示条
    setStage(null);
    setMsgs((m) => [
      ...m,
      { role: "user", content: file ? `附件：${file.name}${message ? `\n说明：${message}` : ""}` : message },
    ]);
    setStreamBuf("");

    let lastPhase = "";
    try {
      const token = getToken();
      const resp = await fetch(file ? `${API_BASE}/api/chat/upload` : `${API_BASE}/api/chat`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        ...(file
          ? { body: (() => {
              const fd = new FormData();
              fd.append("project_id", String(projectId));
              fd.append("note", message);
              fd.append("file", file);
              return fd;
            })() }
          : {
              headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
              body: JSON.stringify({ project_id: projectId, message }),
            }),
      });
      if (resp.status === 401) {
        handle401();
        throw new Error("未登录或登录已过期");
      }
      if (!resp.ok || !resp.body) {
        throw new Error(`API ${resp.status}: ${await resp.text()}`);
      }

      let acc = "";
      await readSSE(resp, (evt) => {
        const type = evt.type as string;
        if (type === "meta") {
          lastPhase = evt.phase as string;
          setPhase(evt.phase as string);
          setQuestions((evt.questions as string[]) ?? []);
          if (evt.constraints) setConstraints(evt.constraints as { recap: string; label: string });
          // A 组：问题示例 + 痛点候选（首次 meta 时初始化勾选为全选，确认一键完成）
          if (evt.question_details) {
            setQuestionDetails(evt.question_details as { question: string; examples: { label: string; note: string }[] }[]);
            // 新一轮问题 → 清空旧选中（问题变了，旧选择不再对应）
            setSelected({});
          }
          if (evt.pain_points) {
            const pts = evt.pain_points as string[];
            setPainPoints(pts);
            setPainChecked((prev) => (prev.size ? prev : new Set(pts)));
          }
          if (evt.confirmed_pain_points) setPainConfirmed(true);
          if (evt.phase === "busy") {
            // 服务端流内锁失败（并发请求被挡），展示一条系统消息但不写入对话历史
            setError("当前项目正在处理中，请不要重复提交，请等待本次任务完成");
            setBusy(false); // 没真发出去，立刻解锁
            busyRef.current = false;
            return;
          }
        } else if (type === "stage") {
          setStage(evt.label as string); // 图节点阶段：「正在生成方案…」等
        } else if (type === "delta") {
          acc += evt.content as string;
          setStreamBuf(acc);
        } else if (type === "reset") {
          // 机密兜底替换：后端替换了已流出的内容，前端清空重绘
          acc = "";
          setStreamBuf("");
        }
        // done 事件在下面统一收尾
      });
      setMsgs((m) => [...m, { role: "assistant", content: acc }]);
      if (!acc) {
        // 流结束但没有任何内容：静默失败必须显式提示，不能让界面看似卡死
        setError("连接中断，后端没有返回内容。请重新发送或稍后重试。");
      }
      if (lastPhase === "done" && opts?.explicitConfirm) {
        // 确认收尾 → 展示联系承诺横幅，稍后跳方案展示页
        setConfirmBanner(true);
        setTimeout(() => router.push(`/project/${projectId}`), 2500);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setStreamBuf(null);
      setBusy(false);
      busyRef.current = false;
    }
  }, [busy, projectId, router]);

  /** 确认循环动作：与普通消息同走 SSE 通道（意图由后端关键词分类）。
   *  用户消息立即上屏、回复流式输出，不再是长时间黑盒等待。 */
  function confirmAction(action: "confirm" | "revise", feedback?: string) {
    const text = action === "confirm" ? "确认，就这样" : (feedback ?? "").trim();
    if (!text) {
      setError(action === "revise" ? "先说说需要修改哪里，再点发送" : "请输入内容再发送");
      inputRef.current?.focus();
      return;
    }
    setReviseMode(false);
    send(text, { explicitConfirm: action === "confirm" });
  }

  /** 组装输入并发送：
   *  - 有点选答案（selected）→ 每题一行「问题：答案」发送（AI 能对号入座）+ 手打补充
   *  - 有「当前问题」→ 带问题上下文
   *  - 有附件时优先走上传通道（输入文字作为附件说明） */
  function submitInput() {
    const text = input.trim();
    const selectedEntries = Object.entries(selected);
    if (!text && !file && !selectedEntries.length) {
      // 空发送不再静默：提示 + 聚焦（移动端「点了没反应」体验最差）
      setError("先点选答案或输入内容再发送");
      inputRef.current?.focus();
      return;
    }
    const f = file;
    setFile(null);
    if (f) {
      send(text, undefined, f);
      return;
    }
    if (selectedEntries.length) {
      // 点选答案逐行排版（不堆一起），补充文字放最后
      const lines = selectedEntries.map(([q, a]) => `${q}：${a}`);
      if (text) lines.push(text);
      setSelected({});
      send(lines.join("\n"));
      return;
    }
    if (activeQuestion) {
      const q = activeQuestion;
      setActiveQuestion(null);
      send(`「${q}」我的回答：${text}`);
    } else {
      send(text);
    }
  }

  const inputDisabled = busy || phase === "done";

  /** A 组选项单选：同组点新选项 → 替换旧选择；跨组互不干扰。
   *  选中项实时显示在输入框上方的「已选」条里（逐题排版，不堆在一起）。 */
  function pickExample(question: string, label: string) {
    setSelected((prev) => ({ ...prev, [question]: label }));
  }

  /** 取消某题的点选 */
  function clearSelected(question: string) {
    setSelected((prev) => {
      const next = { ...prev };
      delete next[question];
      return next;
    });
  }

  /** A 组：痛点勾选切换 */
  function togglePain(p: string) {
    setPainChecked((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  }

  /** A 组：确认勾选的痛点 → 发送【痛点确认】消息（后端代码级解析，全程引用） */
  function confirmPain() {
    const checked = painPoints.filter((p) => painChecked.has(p));
    if (!checked.length) {
      setError("至少勾选一条痛点，或直接回答下面的问题");
      return;
    }
    setPainConfirmed(true);
    send(`【痛点确认】${checked.join("；")}`);
  }

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: `0 ${space.xl}px`, height: "100dvh", display: "flex", flexDirection: "column" }}>
      <style>{`
        @keyframes blink { 0%,80%,100% { opacity: .25 } 40% { opacity: 1 } }
        .dot { width: 7px; height: 7px; border-radius: 50%; background: ${colors.muted.fg}; display: inline-block; animation: blink 1.2s infinite; }
        .dot:nth-child(2) { animation-delay: .2s }
        .dot:nth-child(3) { animation-delay: .4s }
      `}</style>

      {/* 顶栏：左上角返回入口固定在此（对话页是 100dvh 布局，消息区独立滚动，
          顶栏天然常驻，无需悬浮栏）。返回目标 = 历史项目列表（层级路由栈） */}
      <header style={{ padding: `${space.md}px 0`, borderBottom: borderStyle.card, display: "flex", alignItems: "center", gap: space.md }}>
        <style jsx>{`
          a.back-chat:active { background: ${colors.brand.primaryBgPressed}; opacity: .9; }
        `}</style>
        <Link
          href="/projects"
          className="back-chat"
          aria-label="返回历史项目列表"
          style={{
            display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0,
            minHeight: touch.large, padding: `0 ${space.md}px`, marginLeft: -space.md,
            color: colors.text.primary, fontSize: font.sm,
            textDecoration: "none", borderRadius: radius.md, whiteSpace: "nowrap",
          }}
        >
          ← 返回
        </Link>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: font.xl, margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</h1>
          <span style={{ fontSize: font.xs, color: colors.text.secondary }}>
            {STATUS_TEXT[phase === "clarify" ? "diagnosing" : phase === "confirm_wait" ? "plan_generated" : "done"]}
          </span>
        </div>
      </header>

      {/* 约束回顾横幅（P8）：预算已锁定时全程展示，用户随时知道方案往哪走 */}
      {constraints && (
        <div style={{
          display: "flex", alignItems: "center", gap: space.sm,
          padding: `${space.xs}px ${space.base}px`,
          margin: `${space.xs}px 0`,
          background: colors.brand.primaryBg, borderRadius: radius.md,
          border: `1px solid ${colors.brand.primaryBorder}`,
          color: colors.brand.onPrimaryBg, fontSize: font.xs,
        }}>
          <span style={{ display: "flex", alignItems: "center", gap: space.xs }}>
            <Pin size={13} strokeWidth={1.5} style={{ flexShrink: 0 }} />
            {constraints.recap}
          </span>
        </div>
      )}

      {/* 重进会话恢复提示：告知选项卡已回填可继续修改 */}
      {restored && !busy && (
        <div style={{
          display: "flex", alignItems: "center", gap: space.sm,
          padding: `${space.xs}px ${space.base}px`, margin: `${space.xs}px 0`,
          background: colors.bg.muted, borderRadius: radius.md,
          fontSize: font.xs, color: colors.text.secondary,
        }}>
          <span style={{ display: "flex", alignItems: "center", gap: space.xs }}>
            <History size={13} strokeWidth={1.5} style={{ flexShrink: 0 }} />
            已加载上次填写的需求：下方选项可直接点选修改，改完发送即可继续生成方案
          </span>
        </div>
      )}

      {/* 消息区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: `${space.xl}px 0` }}>
        {!loaded && <p style={{ color: colors.text.secondary, textAlign: "center" }}>加载中…</p>}

        {msgs.map((m, i) => {
          const clarify = m.role === "assistant" ? clarifyBubbleOf(m.content) : null;
          if (clarify) {
            // 追问消息：引导句旁白 + 独立问题小框（不混进聊天气泡，视觉上「旁白感」）
            return (
              <div key={i} style={{ textAlign: "center", margin: `0 0 ${space.base}px` }}>
                <div style={{ fontSize: font.xs, color: colors.text.secondary, margin: `0 0 ${space.sm}px` }}>
                  {clarify.lead}
                </div>
                <div style={{
                  display: "inline-block", textAlign: "left", maxWidth: "92%",
                  background: colors.bg.muted, border: borderStyle.card, borderRadius: radius.md,
                  padding: `${space.md}px ${space.lg}px`,
                }}>
                  {clarify.items.map((q, j) => (
                    <div key={j} style={{ fontSize: font.sm, color: colors.text.primary, lineHeight: lineHeight.relaxed, padding: `${space.xxs}px 0` }}>
                      {j + 1}. {q}
                    </div>
                  ))}
                </div>
              </div>
            );
          }
          return (
            <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", marginBottom: space.base }}>
              <div
                style={{
                  maxWidth: "85%",
                  padding: `${space.md}px ${space.lg}px`,
                  borderRadius: radius.xl,
                  fontSize: font.base,
                  lineHeight: lineHeight.relaxed,
                  whiteSpace: "pre-wrap",
                  background: m.role === "user" ? colors.brand.primary : colors.bg.surface,
                  color: m.role === "user" ? colors.text.inverse : colors.text.primary,
                  border: m.role === "user" ? "none" : borderStyle.card,
                  borderBottomRightRadius: m.role === "user" ? radius.sm : radius.xl,
                  borderBottomLeftRadius: m.role === "user" ? radius.xl : radius.sm,
                }}
              >
                {fileTagOf(m.content) ?? m.content}
              </div>
            </div>
          );
        })}

        {/* 流式输出中的助手气泡 */}
        {streamBuf !== null && (
          <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: space.base }}>
            <div style={{
              maxWidth: "85%", padding: `${space.md}px ${space.lg}px`, borderRadius: radius.xl, fontSize: font.base,
              lineHeight: lineHeight.relaxed, whiteSpace: "pre-wrap", background: colors.bg.surface,
              border: borderStyle.card, borderBottomLeftRadius: radius.sm,
            }}>
              {streamBuf || (
                <span>
                  <span className="dot" /> <span className="dot" /> <span className="dot" />
                </span>
              )}
            </div>
          </div>
        )}

        {/* 确认收尾横幅：「我们会尽快联系您」 */}
        {confirmBanner && (
          <div style={{
            margin: `${space.xxs}px 0 ${space.base}px`, padding: `${space.base}px ${space.xl}px`, borderRadius: radius.lg,
            background: colors.status.successBg, border: `1px solid ${colors.status.successBorder}`, fontSize: font.base, color: colors.status.successStrong,
          }}>
            {/* 免费思路版：确认 = 保存结束，没有对接环节，文案跟着变（产品规则 #六） */}
            {constraints?.label === "免费思路版"
              ? "✓ 方案已保存，本次诊断完成——正在打开方案页…"
              : "✓ 方案已确认，我们会尽快联系您——正在打开方案页…"}
          </div>
        )}

        {/* 追问快捷选择（A 组升级：问题卡 + 示例点选 + 痛点勾选） */}
        {phase === "clarify" && questions.length > 0 && !busy && (
          <div style={{ margin: `${space.xxs}px 0 ${space.base}px` }}>
            {/* 痛点确认卡：AI 识别的痛点 → 勾选确认（不适用就不勾），确认后方案逐条回应 */}
            {painPoints.length > 0 && !painConfirmed && (
              <div style={{
                margin: `0 0 ${space.base}px`, padding: `${space.md}px ${space.base}px`,
                background: colors.bg.surface, border: `1px solid ${colors.brand.primaryBorder}`, borderRadius: radius.md,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: space.xs, fontSize: font.sm, color: colors.text.primary, marginBottom: space.sm, fontWeight: 600 }}>
                  <Target size={15} strokeWidth={1.5} style={{ color: colors.brand.linkText, flexShrink: 0 }} />
                  我识别到你这些痛点，勾选确认（不对的取消勾选）：
                </div>
                {painPoints.map((p) => (
                  <label key={p} style={{
                    display: "flex", alignItems: "center", gap: space.sm,
                    padding: `${space.xs}px 0`, cursor: "pointer",
                    fontSize: font.sm, color: colors.text.primary, userSelect: "none",
                  }}>
                    <input
                      type="checkbox"
                      checked={painChecked.has(p)}
                      onChange={() => togglePain(p)}
                      style={{ width: 18, height: 18, accentColor: colors.brand.primary, cursor: "pointer" }}
                    />
                    <span>{p}</span>
                  </label>
                ))}
                <button
                  onClick={confirmPain}
                  style={{
                    marginTop: space.xs, minHeight: touch.base, padding: `0 ${space.lg}px`,
                    background: colors.brand.primary, color: colors.text.inverse,
                    border: "none", borderRadius: radius.md, fontSize: font.sm, cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: space.xs,
                  }}
                >
                  <Check size={15} strokeWidth={2} /> 确认这些痛点
                </button>
              </div>
            )}

            {/* 问题卡（每组一题）：选项为「label + 大白话说明」小卡，
                同组单选（点新替旧）、跨组互不干扰；选中加深底色 */}
            {questions.map((q, i) => {
              const details = questionDetails.find((d) => d.question === q);
              const examples = details?.examples ?? [];
              return (
                <div key={i} style={{
                  margin: `0 0 ${space.lg}px`, padding: `${space.md}px ${space.base}px`, maxWidth: "92%",
                  background: colors.brand.primaryBg, borderRadius: radius.md,
                  border: `1px solid ${activeQuestion === q ? colors.brand.primaryBorderPressed : colors.brand.primaryBorder}`,
                }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: space.sm }}>
                    <button
                      onClick={() => setActiveQuestion((v) => (v === q ? null : q))}
                      style={{
                        display: "block", flex: 1, textAlign: "left", minHeight: touch.base,
                        background: "transparent", border: "none", cursor: "pointer",
                        color: colors.brand.onPrimaryBg, fontSize: font.sm, fontWeight: 600, padding: 0,
                      }}
                    >
                      <span style={{ display: "inline-flex", alignItems: "center", gap: space.xs, verticalAlign: "-2px" }}>
                        {activeQuestion === q
                          ? <Pin size={14} strokeWidth={1.5} aria-hidden />
                          : <Lightbulb size={14} strokeWidth={1.5} aria-hidden />}
                        {q}
                      </span>
                    </button>
                    {selected[q] && (
                      <span style={{ fontSize: font.xs, color: colors.brand.onPrimaryBg, whiteSpace: "nowrap" }}>
                        已选：{selected[q]}
                      </span>
                    )}
                  </div>
                  {examples.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: space.md, marginTop: space.md }}>
                      {examples.map((e) => {
                        const isSel = selected[q] === e.label;
                        return (
                          <button
                            key={e.label}
                            onClick={() => pickExample(q, e.label)}
                            style={{
                              flex: "1 1 30%", minWidth: 120, textAlign: "left",
                              minHeight: touch.base, padding: `${space.sm}px ${space.md}px`,
                              // 选中态：加深底色 + 高亮边框 + ✓，与未选中明显区分
                              background: isSel ? colors.brand.primaryBgPressed : colors.bg.surface,
                              color: colors.brand.linkText,
                              border: `1px solid ${isSel ? colors.brand.primaryBorderPressed : colors.brand.primaryBorder}`,
                              borderRadius: radius.md, cursor: "pointer",
                            }}
                          >
                            <span style={{ display: "block", fontSize: font.sm, fontWeight: isSel ? 700 : 500 }}>
                              {isSel ? "✓ " : ""}{e.label}
                            </span>
                            {e.note && (
                              <span style={{ display: "block", fontSize: font.xs, color: colors.text.tertiary, marginTop: 2, lineHeight: lineHeight.normal }}>
                                {e.note}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            <span style={{ fontSize: font.xs, color: colors.text.tertiary }}>每个问题点一个选项（点错了再点别的自动替换），也可以点问题标题自由作答</span>
          </div>
        )}

        {/* 方案确认栏 */}
        {phase === "confirm_wait" && !busy && (
          <div style={{ margin: `${space.sm}px 0 ${space.xl}px`, display: "flex", gap: space.md }}>
            <button
              onClick={() => confirmAction("confirm")}
              style={{ minHeight: touch.large, padding: `${space.sm + 1}px ${space.xxl}px`, background: colors.status.success, color: colors.text.inverse, border: "none", borderRadius: radius.md, fontSize: font.base, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: space.xs }}
            >
              <Check size={16} strokeWidth={2} /> 确认方案
            </button>
            <button
              onClick={() => setReviseMode(true)}
              style={{ minHeight: touch.large, padding: `${space.sm + 1}px ${space.xxl}px`, background: colors.bg.surface, color: colors.brand.linkText, border: `1px solid ${colors.brand.linkText}`, borderRadius: radius.md, fontSize: font.base, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: space.xs }}
            >
              <PenLine size={16} strokeWidth={1.5} /> 需要修改
            </button>
          </div>
        )}

        {/* 完成引导 */}
        {phase === "done" && !busy && (
          <Link
            href={`/project/${projectId}`}
            style={{ display: "inline-block", margin: `${space.xxs}px 0 ${space.xl}px`, padding: `${space.sm + 1}px ${space.xxl}px`, background: colors.brand.primary, color: colors.text.inverse, borderRadius: radius.md, fontSize: font.base, textDecoration: "none" }}
          >
            查看完整方案 →
          </Link>
        )}

        {/* 等待状态区：分步阶段 + 计时润色 + 安抚小字 + 超时兜底
           （正文开始流式后隐藏；防「长时间空白像卡死」的焦虑） */}
        {busy && !streamBuf && (
          <div style={{ margin: `0 0 ${space.base}px` }}>
            <p style={{ fontSize: font.sm, color: colors.text.secondary, margin: 0, display: "flex", alignItems: "center", gap: space.xs }}>
              <Cog size={14} strokeWidth={1.5} style={{ flexShrink: 0 }} />
              {stage ?? "正在读取你的项目需求…"}（已处理 {waitSec} 秒，AI 正在分析，请稍候）
            </p>
            <p style={{ fontSize: font.xs, color: colors.text.tertiary, margin: `${space.xs}px 0 0` }}>
              复杂需求评估需要一点时间，不会卡住，请勿重复提交
            </p>
            {waitSec > 25 && (
              <p style={{ fontSize: font.xs, color: colors.text.secondary, margin: `${space.xs}px 0 0` }}>
                ⏳ 评估内容较多，还在生成中，一般不会超过 60 秒
              </p>
            )}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* 输入区（safe-area 兜底 iPhone 底部横条） */}
      {/* 发送引导提示（空发送/连接异常）：贴近操作点，居中醒目 */}
      {error && (
        <p style={{
          color: colors.status.danger, fontSize: font.sm,
          margin: `0 0 ${space.sm}px`, textAlign: "center",
        }}>
          {error}
        </p>
      )}
      {/* 当前问题提示条：用户可看着问题、翻聊天记录，再自由作答 */}
      {activeQuestion && phase === "clarify" && !busy && (
        <div style={{
          margin: `0 0 ${space.sm}px`, padding: `${space.sm}px ${space.base}px`, background: colors.brand.primaryBg,
          border: `1px solid ${colors.brand.primaryBorder}`, borderRadius: radius.md, display: "flex", alignItems: "center", gap: space.sm,
        }}>
          <span style={{ flex: 1, display: "flex", alignItems: "center", gap: space.xs, fontSize: font.sm, color: colors.text.primary }}>
            <Pin size={14} strokeWidth={1.5} aria-hidden />
            当前问题：{activeQuestion}
          </span>
          <button
            onClick={() => setActiveQuestion(null)}
            style={{ background: "none", border: "none", color: colors.muted.fg, cursor: "pointer", padding: space.xxs, display: "flex" }}
            aria-label="取消当前问题"
          >
            <X size={16} strokeWidth={1.5} aria-hidden />
          </button>
        </div>
      )}
      {/* 已选答案预览条：点选的选项逐题实时展示（自动排版不堆一起），✕ 可取消 */}
      {Object.keys(selected).length > 0 && phase === "clarify" && !busy && (
        <div style={{
          margin: `0 0 ${space.sm}px`, padding: `${space.sm}px ${space.base}px`,
          background: colors.brand.primaryBg, border: `1px solid ${colors.brand.primaryBorder}`,
          borderRadius: radius.md, display: "flex", flexWrap: "wrap", gap: space.sm,
        }}>
          {Object.entries(selected).map(([q, a]) => (
            <span key={q} style={{
              display: "inline-flex", alignItems: "center", gap: space.xs,
              padding: `${space.xxs}px ${space.md}px`, borderRadius: radius.pill,
              background: colors.brand.primaryBgPressed, color: colors.brand.onPrimaryBg,
              fontSize: font.sm,
            }}>
              <span style={{ color: colors.text.tertiary, fontSize: font.xs }}>{q}</span>
              <b>{a}</b>
              <button
                onClick={() => clearSelected(q)}
                aria-label={`取消 ${q} 的选择`}
                style={{ background: "none", border: "none", color: colors.brand.onPrimaryBg, cursor: "pointer", padding: 0, lineHeight: 1, display: "flex" }}
              >
                <X size={12} strokeWidth={2} aria-hidden />
              </button>
            </span>
          ))}
          <span style={{ fontSize: font.xs, color: colors.text.tertiary, alignSelf: "center" }}>
            发送时逐题带上答案，下方可补充文字
          </span>
        </div>
      )}
      {/* 待发送附件预览 */}
      {file && !busy && (
        <div style={{
          margin: `0 0 ${space.sm}px`, padding: `${space.sm}px ${space.base}px`, background: colors.bg.muted,
          border: borderStyle.card, borderRadius: radius.md, display: "flex", alignItems: "center", gap: space.sm,
        }}>
          <span style={{ display: "flex", flexShrink: 0, color: colors.text.tertiary }}>
            <Paperclip size={15} strokeWidth={1.5} aria-hidden />
          </span>
          <span style={{ flex: 1, fontSize: font.sm, color: colors.text.tertiary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {file.name}（{Math.max(1, Math.round(file.size / 1024))} KB）
          </span>
          <button
            onClick={() => setFile(null)}
            style={{ background: "none", border: "none", color: colors.muted.fg, cursor: "pointer", padding: space.xxs, display: "flex" }}
            aria-label="移除附件"
          >
            <X size={16} strokeWidth={1.5} aria-hidden />
          </button>
        </div>
      )}
      <div style={{ borderTop: borderStyle.card, padding: `${space.base}px 0 calc(${space.base}px + env(safe-area-inset-bottom))`, display: "flex", gap: space.md, alignItems: "flex-end" }}>
        <label
          style={{
            minHeight: touch.large, minWidth: touch.large, display: "flex", alignItems: "center", justifyContent: "center",
            border: borderStyle.input, borderRadius: radius.lg, fontSize: font.xxl, cursor: inputDisabled ? "not-allowed" : "pointer",
            background: inputDisabled ? colors.bg.disabled : colors.bg.surface, userSelect: "none",
          }}
          title="上传数据文件（txt/docx/pdf/图片），AI 会根据内容调整方案"
        >
          <Paperclip size={22} strokeWidth={1.5} aria-hidden />
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,.csv,.json,.log,.docx,.pdf,.png,.jpg,.jpeg,.bmp,.webp"
            style={{ display: "none" }}
            disabled={inputDisabled}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
        </label>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            if (error) setError(null); // 开始输入即清提示
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (reviseMode) confirmAction("revise", input); else submitInput();
            }
          }}
          placeholder={
            phase === "done"
              ? "本次诊断已完成"
              : reviseMode
                ? "描述需要修改的地方，如：预算砍到 5 万以内…"
                : file
                  ? "为附件补充说明（可选），Enter 发送…"
                  : activeQuestion
                    ? "说说你的情况…（发送时自动带上当前问题）"
                    : "补充你的业务情况…（Enter 发送，Shift+Enter 换行）"
          }
          rows={2}
          disabled={inputDisabled}
          style={{
            flex: 1, padding: `${space.md}px ${space.base}px`, fontSize: font.lg, border: borderStyle.input,
            borderRadius: radius.lg, resize: "none", outline: "none", fontFamily: "inherit",
            background: inputDisabled ? colors.bg.disabled : colors.bg.surface,
          }}
        />
        <button
          onClick={() => (reviseMode ? confirmAction("revise", input) : submitInput())}
          disabled={inputDisabled}
          style={{
            minHeight: touch.large, padding: `0 ${space.xxl + 6}px`, fontSize: font.md, borderRadius: radius.md, border: "none",
            background: inputDisabled ? colors.muted.bg : colors.brand.primary,
            color: colors.text.inverse, cursor: inputDisabled ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "…" : "发送"}
        </button>
      </div>
    </main>
  );
}