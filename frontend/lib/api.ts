// 后端 API 基础地址（.env.local 里可配 NEXT_PUBLIC_API_URL 覆盖）
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

// 统一的请求封装：失败时抛出可读错误
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API ${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}
