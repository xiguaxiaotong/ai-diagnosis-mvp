"use client";

import Link from "next/link";
import { useTheme } from "../lib/theme";
import { font, radius, space, touch } from "../lib/tokens";

/** 顶栏总高度：子页面用它做顶部避让（内容别被悬浮栏盖住） */
export const BACK_BAR_HEIGHT = 52;

/** 面包屑段：href 缺省 = 当前页（不可点） */
export interface Crumb {
  label: string;
  href?: string;
}

/**
 * 全局统一返回栏（移动端返回交互改进 #1）：
 * - 左上角固定悬浮，滚动页面时不消失；暗夜紫深色下文字为浅色（text.primary），
 *   禁止黑字；触摸区 ≥44px（touch.large），:active 有明显高亮反馈；
 * - backHref 是固定的上一级路由（层级路由栈），不依赖浏览器自带返回键；
 * - 可选面包屑（备选方案 A）：适合内容长的方案页，每段可点、直接跳级；
 * - no-print：方案页导出 PDF 时隐藏。
 */
export function BackBar({ backHref, crumbs }: { backHref: string; crumbs?: Crumb[] }) {
  const { colors, borderStyle } = useTheme();
  return (
    <div
      className="no-print"
      style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
        display: "flex", alignItems: "center", gap: space.md,
        height: BACK_BAR_HEIGHT, padding: `0 ${space.xl}px`,
        // 半透明页面底 + 毛玻璃：滚动内容从栏下穿过仍可读
        background: `${colors.bg.page}ea`,
        backdropFilter: "blur(8px)", WebkitBackdropFilter: "blur(8px)",
        borderBottom: borderStyle.card,
      }}
    >
      <style jsx>{`
        a:active {
          background: ${colors.brand.primaryBgPressed};
          opacity: 0.9;
        }
      `}</style>
      <Link
        href={backHref}
        style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          minHeight: touch.large, padding: `0 ${space.md}px`, marginLeft: -space.md,
          color: colors.text.primary, fontSize: font.sm,
          textDecoration: "none", borderRadius: radius.md, whiteSpace: "nowrap",
        }}
      >
        ← 返回
      </Link>
      {crumbs && crumbs.length > 0 && (
        <nav style={{ display: "flex", alignItems: "center", gap: space.sm, minWidth: 0, overflow: "hidden" }}>
          {crumbs.map((c, i) => (
            <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: space.sm, whiteSpace: "nowrap" }}>
              {i > 0 && <span style={{ color: colors.text.tertiary, fontSize: font.sm }}>/</span>}
              {c.href ? (
                <Link href={c.href} style={{ color: colors.brand.linkText, fontSize: font.sm, textDecoration: "none" }}>
                  {c.label}
                </Link>
              ) : (
                <span style={{
                  color: colors.text.secondary, fontSize: font.sm,
                  overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {c.label}
                </span>
              )}
            </span>
          ))}
        </nav>
      )}
    </div>
  );
}
