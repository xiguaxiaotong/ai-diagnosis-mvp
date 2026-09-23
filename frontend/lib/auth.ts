// Day4 账户系统：token 存取 + 401 统一处理
// token 存 localStorage（MVP 最简；XSS 风险在自用 MVP 阶段可接受）
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const TOKEN_KEY = "diag_token";
const USER_KEY = "diag_user";

export interface AuthUser {
  id: number;
  username: string;
  name: string;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** 401 时清会话并跳登录页（带回跳地址）。避免在 SSR/循环里反复跳。 */
export function handle401(): void {
  clearSession();
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
}

/** 页面级登录守卫：未登录跳 /login。返回是否已登录（null = 还在检查）。 */
export function useRequireAuth(): boolean | null {
  const router = useRouter();
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
      setAuthed(false);
      return;
    }
    setAuthed(true);
  }, [router]);
  return authed;
}

/** 非跳转版登录检查：首页游客可浏览介绍，点「开始诊断」才引导注册（null = 还在检查）。 */
export function useAuthed(): boolean | null {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, []);
  return authed;
}
