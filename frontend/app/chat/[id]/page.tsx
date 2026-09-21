"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE } from "../../../lib/api";

type Msg = { role: "user" | "assistant"; content: string };

interface ProjectDetail {
  id: number;
  title: string;
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
  const [reviseMode, setReviseMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // 初始加载：历史消息 + 根据 solution 恢复阶段
  useEffect(() => {
    if (!projectId) return;
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

  /** 发送一条普通消息（走 /api/chat SSE 流式） */
  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setError(null);
    setBusy(true);
    setInput("");
    setQuestions([]);
    setMsgs((m) => [...m, { role: "user", content: message }]);
    setStreamBuf("");

    try {
      const resp = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, message }),
      });
      if (!resp.ok || !resp.body) {
        throw new Error(`API ${resp.status}: ${await resp.text()}`);
      }

      let acc = "";
      await readSSE(resp, (evt) => {
        const type = evt.type as string;
        if (type === "meta") {
          setPhase(evt.phase as string);
          setQuestions((evt.questions as string[]) ?? []);
        } else if (type === "delta") {
          acc += evt.content as string;
          setStreamBuf(acc);
        }
        // done 事件在下面统一收尾
      });
      setMsgs((m) => [...m, { role: "assistant", content: acc }]);
    } catch (e) {
      setError(String(e));
    } finally {
      setStreamBuf(null);
      setBusy(false);
    }
  }

  /** 确认循环动作（走 /api/project/{id}/confirm，非流式） */
  async function confirmAction(action: "confirm" | "revise", feedback?: string) {
    if (busy) return;
    setError(null);
    setBusy(true);
    setReviseMode(false);
    if (action === "revise") setInput("");
    try {
      const r = await api<{
        phase: string;
        reply: string;
        revision_round: number;
      }>(`/api/project/${projectId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ action, feedback }),
      });
      setPhase(r.phase);
      setQuestions([]);
      setMsgs((m) => [...m, { role: "assistant", content: r.reply }]);
      if (r.phase === "done") {
        // 确认完成后跳方案展示页
        setTimeout(() => router.push(`/project/${projectId}`), 1200);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const inputDisabled = busy || phase === "done";

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "0 16px", height: "100vh", display: "flex", flexDirection: "column" }}>
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
                maxWidth: "78%",
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
              {m.content}
            </div>
          </div>
        ))}

        {/* 流式输出中的助手气泡 */}
        {streamBuf !== null && (
          <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12 }}>
            <div style={{
              maxWidth: "78%", padding: "10px 14px", borderRadius: 12, fontSize: 14,
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

        {/* 追问快捷填充 */}
        {phase === "clarify" && questions.length > 0 && !busy && (
          <div style={{ margin: "4px 0 12px" }}>
            {questions.map((q, i) => (
              <button
                key={i}
                onClick={() => setInput((v) => (v ? v + "；" : "") + q)}
                style={{
                  display: "block", margin: "0 0 8px", padding: "8px 12px", maxWidth: "78%",
                  background: "#eff6ff", color: "#2563eb", border: "1px solid #bfdbfe",
                  borderRadius: 8, fontSize: 13, cursor: "pointer", textAlign: "left",
                }}
              >
                💡 {q}
              </button>
            ))}
            <span style={{ fontSize: 12, color: "#94a3b8" }}>点击问题可填入输入框，补充你的情况后发送</span>
          </div>
        )}

        {/* 方案确认栏 */}
        {phase === "confirm_wait" && !busy && (
          <div style={{ margin: "8px 0 16px", display: "flex", gap: 10 }}>
            <button
              onClick={() => confirmAction("confirm")}
              style={{ padding: "9px 20px", background: "#16a34a", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
            >
              ✓ 确认方案
            </button>
            <button
              onClick={() => setReviseMode(true)}
              style={{ padding: "9px 20px", background: "#fff", color: "#2563eb", border: "1px solid #2563eb", borderRadius: 8, fontSize: 14, cursor: "pointer" }}
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

        {error && <p style={{ color: "#dc2626", fontSize: 13 }}>出错了：{error}</p>}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div style={{ borderTop: "1px solid #e5e7eb", padding: "12px 0 16px", display: "flex", gap: 10 }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (reviseMode) confirmAction("revise", input); else send(input);
            }
          }}
          placeholder={
            phase === "done"
              ? "本次诊断已完成"
              : reviseMode
                ? "描述需要修改的地方，如：预算砍到 5 万以内…"
                : "补充你的业务情况…（Enter 发送，Shift+Enter 换行）"
          }
          rows={2}
          disabled={inputDisabled}
          style={{
            flex: 1, padding: "10px 12px", fontSize: 14, border: "1px solid #d1d5db",
            borderRadius: 10, resize: "none", outline: "none", fontFamily: "inherit",
            background: inputDisabled ? "#f3f4f6" : "#fff",
          }}
        />
        <button
          onClick={() => (reviseMode ? confirmAction("revise", input) : send(input))}
          disabled={inputDisabled || !input.trim()}
          style={{
            padding: "0 22px", fontSize: 14, borderRadius: 10, border: "none",
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
