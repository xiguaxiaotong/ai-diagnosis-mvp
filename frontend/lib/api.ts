// 后端 API 基础地址（.env.local 里可配 NEXT_PUBLIC_API_URL 覆盖）
// 用 ?? 而非 ||：生产 Docker 构建传 NEXT_PUBLIC_API_URL=""（空串）= 同域相对路径
// （Nginx 反代 /api → 后端），本地 dev 默认走 localhost:8000
import { getToken, handle401 } from "./auth";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Project {
  id: number;
  title: string;
  raw_idea: string | null;
  status: string;
  budget_min: number | null;
  budget_max: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 从后端错误响应提取可读文案：{"detail": "..."} → detail；HTML/纯文本截断。
 *  500 等 FastAPI 未捕获异常时不裸抛 TypeError，落到「服务器开小差」兜底文案。 */
function extractApiError(status: number, text: string): string {
  try {
    const parsed = JSON.parse(text);
    const detail = parsed?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return `（HTTP ${status}）${detail}`;
    }
    // FastAPI 校验错误的 detail 是数组 → 取 msg 拼接
    if (Array.isArray(detail)) {
      const msgs = detail.map((d: { msg?: string }) => d?.msg).filter(Boolean);
      if (msgs.length) return `（HTTP ${status}）${msgs.join("；")}`;
    }
  } catch {
    // 非 JSON（HTML 500 页等）→ 走截断兜底
  }
  if (status >= 500) return `服务器开小差了（HTTP ${status}），请稍后重试或联系管理员`;
  const clipped = text.length > 160 ? text.slice(0, 160) + "…" : text;
  return `请求失败（HTTP ${status}）${clipped ? "：" + clipped : ""}`;
}

// 统一的请求封装：自动带登录 token；401 清会话跳登录页
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    // 网络层失败（后端没起 / 断网）——fetch 直接 reject TypeError，给出可读文案
    throw new Error("无法连接服务器，请检查网络或后端服务状态");
  }
  if (resp.status === 401) {
    handle401();
    throw new Error("未登录或登录已过期");
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(extractApiError(resp.status, text));
  }
  return resp.json() as Promise<T>;
}

/**
 * SSE 对话流专用 fetch：EventSource 不支持自定义 header，走 fetch + ReadableStream。
 * 已登录才应调用（调用方负责守卫）；401 时跳登录。
 */
export async function apiStream(
  path: string,
  body: unknown,
): Promise<Response> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (resp.status === 401) {
    handle401();
    throw new Error("未登录或登录已过期");
  }
  return resp;
}

/** PDF 导出等需要 Authorization 的下载：fetch blob → 触发浏览器下载。 */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (resp.status === 401) {
    handle401();
    throw new Error("未登录或登录已过期");
  }
  if (!resp.ok) throw new Error(`下载失败 HTTP ${resp.status}`);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
