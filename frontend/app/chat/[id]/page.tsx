"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE } from "../../../lib/api";

type Msg = { role: "user" | "assistant"; content: string };

/** 历史消息里的文件上传消息 → 摘要显示（文件全文太长，不直接渲染） */
function fileTagOf(content: string): string | null {
  const m = content.match(/^\[用户上传文件「(.+?)」（提取 (\d+) 字）\]/);
  return m ? `📎 ${m[1]}（AI 已读取 ${m[2]} 字）` : null;
}

interface ProjectDetail {
  id: number;
  title: string;
  raw_idea: string | null;
  status: string;
  solution: Record<string, unknown> | null;
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
  const [reviseMode, setReviseMode] = useState(false);
  const [confirmBanner, setConfirmBanner] = useState(false);
  const [stage, setStage] = useState<string | null>(null); // 后端图执行阶段提示
  const [waitSec, setWaitSec] = useState(0); // 已等待秒数
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef(false); // raw_idea 自动首发守卫（StrictMode 双执行防重）
  const loadedForRef = useRef<number | null>(null); // 每个项目只加载一次（防二次执行覆盖 msgs）

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
  async function send(text: string, opts?: { explicitConfirm?: boolean }, file?: File | null) {
    const message = text.trim();
    if ((!message && !file) || busy) return;
    setError(null);
    setBusy(true);
    setInput("");
    setQuestions([]);
    setStage(null);
    setMsgs((m) => [
      ...m,
      { role: "user", content: file ? `📎 ${file.name}${message ? `\n说明：${message}` : ""}` : message },
    ]);
    setStreamBuf("");

    let lastPhase = "";
    try {
      const resp = await fetch(file ? `${API_BASE}/api/chat/upload` : `${API_BASE}/api/chat`, {
        method: "POST",
        ...(file
          ? { body: (() => {
              const fd = new FormData();
              fd.append("project_id", String(projectId));
              fd.append("note", message);
              fd.append("file", file);
              return fd;
            })() }
          : {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ project_id: projectId, message }),
            }),
      });
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
        } else if (type === "stage") {
          setStage(evt.label as string); // 图节点阶段：「正在生成方案…」等
        } else if (type === "delta") {
          acc += evt.content as string;
          setStreamBuf(acc);
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
    }
  }

  /** 确认循环动作：与普通消息同走 SSE 通道（意图由后端关键词分类）。
   *  用户消息立即上屏、回复流式输出，不再是长时间黑盒等待。 */
  function confirmAction(action: "confirm" | "revise", feedback?: string) {
    const text = action === "confirm" ? "确认，就这样" : (feedback ?? "").trim();
    if (!text) return;
    setReviseMode(false);
    send(text, { explicitConfirm: action === "confirm" });
  }

  /** 组装输入并发送：有「当前问题」时自动带上问题上下文（AI 能对号入座）；
   *  有附件时优先走上传通道（输入文字作为附件说明） */
  function submitInput() {
    const text = input.trim();
    if (!text && !file) return;
    const f = file;
    setFile(null);
    if (f) {
      send(text, undefined, f);
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

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "0 16px", height: "100dvh", display: "flex", flexDirection: "column" }}>
      <style>{`
        @keyframes blink { 0%,80%,100% { opacity: .25 } 40% { opacity: 1 } }
        .dot { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; display: inline-block; animation: blink 1.2s infinite; }
        .dot:nth-child(2) { animation-delay: .2s }
        .dot:nth-child(3) { animation-delay: .4s }
      `}</style>

      {/* 顶栏 */}
      <header style={{ padding: "14px 0", borderBottom: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ fontSize: 17, margin: 0 }}>{title}</h1>
          <span style={{ fontSize: 12, color: "#646a73" }}>
            {STATUS_TEXT[phase === "clarify" ? "diagnosing" : phase === "confirm_wait" ? "plan_generated" : "done"]}
          </span>
        </div>
        <Link href="/projects" style={{ fontSize: 13, color: "#2563eb", textDecoration: "none" }}>
          ← 历史项目
        </Link>
      </header>

      {/* 消息区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px 0" }}>
        {!loaded && <p style={{ color: "#646a73", textAlign: "center" }}>加载中…</p>}

        {msgs.map((m, i) => (
          <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", marginBottom: 12 }}>
            <div
              style={{
                maxWidth: "85%",
                padding: "10px 14px",
                borderRadius: 12,
                fontSize: 14,
                lineHeight: 1.7,
                whiteSpace: "pre-wrap",
                background: m.role === "user" ? "#2563eb" : "#fff",
                color: m.role === "user" ? "#fff" : "#1f2329",
                border: m.role === "user" ? "none" : "1px solid #e5e7eb",
                borderBottomRightRadius: m.role === "user" ? 4 : 12,
                borderBottomLeftRadius: m.role === "user" ? 12 : 4,
              }}
            >
              {fileTagOf(m.content) ?? m.content}
            </div>
          </div>
        ))}

        {/* 流式输出中的助手气泡 */}
        {streamBuf !== null && (
          <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12 }}>
            <div style={{
              maxWidth: "85%", padding: "10px 14px", borderRadius: 12, fontSize: 14,
              lineHeight: 1.7, whiteSpace: "pre-wrap", background: "#fff",
              border: "1px solid #e5e7eb", borderBottomLeftRadius: 4,
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
            margin: "4px 0 12px", padding: "12px 16px", borderRadius: 10,
            background: "#f0fdf4", border: "1px solid #bbf7d0", fontSize: 14, color: "#15803d",
          }}>
            ✓ 方案已确认，我们会尽快联系您——正在打开方案页…
          </div>
        )}

        {/* 追问快捷选择：点击设为「当前问题」，输入框留给用户自由作答 */}
        {phase === "clarify" && questions.length > 0 && !busy && (
          <div style={{ margin: "4px 0 12px" }}>
            {questions.map((q, i) => (
              <button
                key={i}
                onClick={() => setActiveQuestion((v) => (v === q ? null : q))}
                style={{
                  display: "block", margin: "0 0 8px", padding: "10px 12px", maxWidth: "85%",
                  minHeight: 40,
                  background: activeQuestion === q ? "#dbeafe" : "#eff6ff",
                  color: "#2563eb", border: `1px solid ${activeQuestion === q ? "#93c5fd" : "#bfdbfe"}`,
                  borderRadius: 8, fontSize: 13, cursor: "pointer", textAlign: "left",
                }}
              >
                {activeQuestion === q ? "📌" : "💡"} {q}
              </button>
            ))}
            <span style={{ fontSize: 12, color: "#94a3b8" }}>点击问题设为「当前问题」，可往上翻聊天记录，想好再答</span>
          </div>
        )}

        {/* 方案确认栏 */}
        {phase === "confirm_wait" && !busy && (
          <div style={{ margin: "8px 0 16px", display: "flex", gap: 10 }}>
            <button
              onClick={() => confirmAction("confirm")}
              style={{ minHeight: 44, padding: "9px 20px", background: "#16a34a", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              ✓ 确认方案
            </button>
            <button
              onClick={() => setReviseMode(true)}
              style={{ minHeight: 44, padding: "9px 20px", background: "#fff", color: "#2563eb", border: "1px solid #2563eb", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              ✏️ 需要修改
            </button>
          </div>
        )}

        {/* 完成引导 */}
        {phase === "done" && !busy && (
          <Link
            href={`/project/${projectId}`}
            style={{ display: "inline-block", margin: "4px 0 16px", padding: "9px 20px", background: "#2563eb", color: "#fff", borderRadius: 8, fontSize: 14, textDecoration: "none" }}
          >
            查看完整方案 →
          </Link>
        )}

        {/* 等待状态行：图执行阶段 + 计时（正文开始流式后隐藏） */}
        {busy && !streamBuf && (
          <p style={{ fontSize: 12, color: "#94a3b8", margin: "0 0 12px" }}>
            ⚙ {stage ?? "后端处理中…"}（已等待 {waitSec} 秒）
          </p>
        )}

        {error && <p style={{ color: "#dc2626", fontSize: 13 }}>出错了：{error}</p>}
        <div ref={bottomRef} />
      </div>

      {/* 输入区（safe-area 兜底 iPhone 底部横条） */}
      {/* 当前问题提示条：用户可看着问题、翻聊天记录，再自由作答 */}
      {activeQuestion && phase === "clarify" && !busy && (
        <div style={{
          margin: "0 0 8px", padding: "8px 12px", background: "#eff6ff",
          border: "1px solid #bfdbfe", borderRadius: 8, display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{ flex: 1, fontSize: 13, color: "#2563eb" }}>
            📌 当前问题：{activeQuestion}
          </span>
          <button
            onClick={() => setActiveQuestion(null)}
            style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 14, cursor: "pointer", padding: "4px" }}
            aria-label="取消当前问题"
          >
            ✕
          </button>
        </div>
      )}
      {/* 待发送附件预览 */}
      {file && !busy && (
        <div style={{
          margin: "0 0 8px", padding: "8px 12px", background: "#f9fafb",
          border: "1px solid #e5e7eb", borderRadius: 8, display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{ flex: 1, fontSize: 13, color: "#374151", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            📎 {file.name}（{Math.max(1, Math.round(file.size / 1024))} KB）
          </span>
          <button
            onClick={() => setFile(null)}
            style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 14, cursor: "pointer", padding: 4 }}
            aria-label="移除附件"
          >
            ✕
          </button>
        </div>
      )}
      <div style={{ borderTop: "1px solid #e5e7eb", padding: "12px 0 calc(12px + env(safe-area-inset-bottom))", display: "flex", gap: 10, alignItems: "flex-end" }}>
        <label
          style={{
            minHeight: 44, minWidth: 44, display: "flex", alignItems: "center", justifyContent: "center",
            border: "1px solid #d1d5db", borderRadius: 10, fontSize: 18, cursor: inputDisabled ? "not-allowed" : "pointer",
            background: inputDisabled ? "#f3f4f6" : "#fff", userSelect: "none",
          }}
          title="上传数据文件（txt/docx/pdf/图片），AI 会根据内容调整方案"
        >
          📎
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
          value={input}
          onChange={(e) => setInput(e.target.value)}
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
            flex: 1, padding: "10px 12px", fontSize: 16, border: "1px solid #d1d5db",
            borderRadius: 10, resize: "none", outline: "none", fontFamily: "inherit",
            background: inputDisabled ? "#f3f4f6" : "#fff",
          }}
        />
        <button
          onClick={() => (reviseMode ? confirmAction("revise", input) : submitInput())}
          disabled={inputDisabled || (!input.trim() && !file)}
          style={{
            minHeight: 44, padding: "0 22px", fontSize: 15, borderRadius: 10, border: "none",
            background: inputDisabled || !input.trim() ? "#9ca3af" : "#2563eb",
            color: "#fff", cursor: inputDisabled || !input.trim() ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "…" : "发送"}
        </button>
      </div>
    </main>
  );
}
