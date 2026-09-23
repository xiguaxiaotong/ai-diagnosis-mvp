"use client";

// 多主题运行时：ThemeProvider 下发当前主题的 colors/borderStyle，
// 页面一律用 useTheme() 取色（禁止直接 import 具体主题 → 保留换肤能力）。
// 选择持久化 localStorage("theme")；首帧内联脚本（layout）提前刷 body 底色防闪白。

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  THEMES,
  borderStyleFor,
  type ThemeColors,
  type ThemeName,
} from "./tokens";
import { font, radius, space } from "./tokens";

interface ThemeContextValue {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
  colors: ThemeColors;
  borderStyle: ReturnType<typeof borderStyleFor>;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const v = useContext(ThemeContext);
  if (!v) throw new Error("useTheme 必须在 <ThemeProvider> 内使用");
  return v;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>("light");
  const [open, setOpen] = useState(false);
  const colors = THEMES[theme].colors;

  // 挂载后读取本地保存的主题（首帧 SSR 用默认 dark，防不一致）
  useEffect(() => {
    const saved = window.localStorage.getItem("theme") as ThemeName | null;
    if (saved && saved in THEMES) setThemeState(saved);
  }, []);

  // 主题变化 → 同步 body 底色/文字色（layout 只能写死 SSR 默认值）
  useEffect(() => {
    document.body.style.background = colors.bg.page;
    document.body.style.color = colors.text.primary;
    // placeholder 色（layout 全局 ::placeholder 规则消费此变量）
    document.body.style.setProperty("--placeholder", colors.muted.fg);
    // 按钮 hover/按下反馈（layout 全局 :hover/:active 规则消费）：
    // 暗色系按下变暗、hover 提亮；浅色系都加深（对应各主题 primaryHover/Pressed 的方向）
    const press = theme === "light" ? "0.82" : "0.85";
    const hover = theme === "light" ? "0.92" : theme === "ocean" ? "1.16" : "1.1";
    document.body.style.setProperty("--btn-press-bright", press);
    document.body.style.setProperty("--btn-hover-bright", hover);
  }, [colors, theme]);

  const setTheme = useCallback((t: ThemeName) => {
    setThemeState(t);
    window.localStorage.setItem("theme", t);
  }, []);

  // 点击页面其他地方关闭主题面板
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [open]);

  const value: ThemeContextValue = {
    theme,
    setTheme,
    colors,
    borderStyle: borderStyleFor(colors),
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}

      {/* 全站浮动主题切换按钮（所有页面右上角可见） */}
      <div
        style={{ position: "fixed", top: space.md, right: space.md, zIndex: 500 }}
        onClick={(e) => e.stopPropagation()}
      >
        {open && (
          <div
            style={{
              position: "absolute", top: 0, right: 0,
              background: colors.bg.surface, border: `1px solid ${colors.border.subtle}`,
              borderRadius: radius.md, boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
              overflow: "hidden", minWidth: 128,
            }}
          >
            {(Object.keys(THEMES) as ThemeName[]).map((name) => (
              <button
                key={name}
                onClick={() => { setTheme(name); setOpen(false); }}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: `${space.md}px ${space.lg}px`,
                  background: name === theme ? colors.brand.primaryBg : "transparent",
                  // 选中项 = 紫底紫字（看不清），用 onPrimaryBg（深底白字）
                  color: name === theme ? colors.brand.onPrimaryBg : colors.text.primary,
                  border: "none", fontSize: font.base, cursor: "pointer",
                }}
              >
                {name === theme ? "✓ " : ""}
                {THEMES[name].label}
              </button>
            ))}
          </div>
        )}
        <button
          onClick={() => setOpen((v) => !v)}
          aria-label="切换主题"
          style={{
            width: 44, height: 44, lineHeight: "44px", textAlign: "center",
            background: colors.bg.surface, color: colors.brand.linkText,
            border: `1px solid ${colors.border.default}`,
            borderRadius: radius.pill, fontSize: font.xxl, cursor: "pointer",
          }}
        >
          🎨
        </button>
      </div>
    </ThemeContext.Provider>
  );
}
