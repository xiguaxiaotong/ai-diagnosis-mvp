import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { StyledJsx } from "./styled-jsx";
import { ThemeProvider } from "../lib/theme";
import { THEMES } from "../lib/tokens";

export const metadata: Metadata = {
  title: "AI 诊断 MVP",
  description: "AI 需求诊断与方案生成",
};

// 移动端适配：device-width + viewport-fit=cover（配合 safe-area 安全区）
// userScalable:false + maximumScale:1 禁用手势缩放——手机上双击/双指
// 极易误触触发页面缩放，缩放后按钮错位、点击落空（本应用是工具型表单，
// 不依赖捏合缩放读内容，禁掉收益大于无障碍损失）
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  userScalable: false,
  maximumScale: 1,
};

// 首帧内联脚本：hydration 前按 localStorage 主题刷 body 底色，防止
// 浅色用户首屏闪一下默认暗色（SSR 无法读 localStorage，只能这样兜）。
const THEME_BOOT = `try{var t=localStorage.getItem("theme");var m=${JSON.stringify(
  Object.fromEntries(
    Object.entries(THEMES).map(([k, v]) => [k, [v.colors.bg.page, v.colors.text.primary]]),
  ),
)};var p=m[t]||m.light;document.body.style.background=p[0];document.body.style.color=p[1];}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          fontFamily:
            "-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
          // SSR 默认值（经典浅色）；真实主题由首帧脚本 + ThemeProvider 接管
          background: THEMES.light.colors.bg.page,
          color: THEMES.light.colors.text.primary,
          WebkitTapHighlightColor: "transparent",
          WebkitFontSmoothing: "antialiased",
          // 兜底（iOS 老版本不完全尊重 viewport 缩放禁用）：
          // touch-action=manipulation 移除双击缩放手势 + 300ms 点击延迟
          touchAction: "manipulation",
        }}
      >
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        {/* 表单控件（input/textarea）默认用浏览器 UA 颜色（黑字），不继承 body ——
            暗色主题下 = 深底黑字看不清。全局强制继承主题文字色；
            placeholder 用 CSS 变量（ThemeProvider 按当前主题写入 --placeholder）。 */}
        <style dangerouslySetInnerHTML={{ __html: `
          input, textarea, select { color: inherit; }
          input::placeholder, textarea::placeholder { color: var(--placeholder, #8a92a0); opacity: 1; }
          /* 按钮态反馈：变量由 ThemeProvider 按主题写入
             （暗色系 hover 提亮/按下加深，浅色系都加深；禁用键不参与） */
          @media (hover: hover) {
            button:not(:disabled):hover { filter: brightness(var(--btn-hover-bright, 1.05)); }
          }
          button:not(:disabled):active { filter: brightness(var(--btn-press-bright, 0.85)); }
        ` }} />
        {/* styled-jsx 注册器：App Router 下没有它，<style jsx> 不会进 SSR HTML，
            样式要等 hydration 后才生效（手机首帧会闪布局）。包一层即可服务端直出。 */}
        <StyledJsx>
          <ThemeProvider>{children}</ThemeProvider>
        </StyledJsx>
      </body>
    </html>
  );
}
