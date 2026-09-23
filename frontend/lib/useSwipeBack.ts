"use client";

import { useEffect, useRef } from "react";

/**
 * 移动端右滑返回手势（移动端返回交互改进 #3 方案 B，辅助增强）。
 *
 * ⚠️ 手势只能辅助，不能替代左上角返回按钮（部分手机浏览器不支持/易冲突）。
 * 冲突防护：起点限定屏幕左缘 40px 内，右滑 ≥90px 且纵向偏移 <60px 才触发，
 * 不影响页面横向滚动与其它触摸操作。
 *
 * @param onBack 触发手势后的回调（建议固定跳上一级路由，别用 router.back()）
 * @param enabled false 时整体停用（如对话发送中防止误滑中断）
 */
export function useSwipeBack(onBack: () => void, enabled = true) {
  const start = useRef<{ x: number; y: number } | null>(null);
  const cb = useRef(onBack);
  cb.current = onBack; // 始终拿最新回调，不必重建监听

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const onStart = (e: TouchEvent) => {
      const t = e.touches[0];
      if (t.clientX <= 40) start.current = { x: t.clientX, y: t.clientY };
    };
    const onEnd = (e: TouchEvent) => {
      if (!start.current) return;
      const t = e.changedTouches[0];
      const dx = t.clientX - start.current.x;
      const dy = t.clientY - start.current.y;
      start.current = null;
      if (dx > 90 && Math.abs(dy) < 60) cb.current();
    };
    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchend", onEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchend", onEnd);
    };
  }, [enabled]);
}
