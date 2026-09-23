// =====================================================================
// Design Tokens — 全站样式唯一来源（颜色/字号/圆角/间距/触控目标）
//
// 铁律（见 frontend/AGENTS.md）：
//   1. 任何颜色/字号/圆角/间距都必须从这里 import，禁止 inline 硬编码
//   2. 同一 UI 结构出现 2 次以上必须抽到 components/ui/
//   3. 改这里一处 = 全站同步；不要在每个页面里复制色号
//
// 多主题：颜色按「主题注册表」组织（THEMES），由 <ThemeProvider>（lib/theme.tsx）
// 提供当前主题的 colors/borderStyle。非颜色 token（字号/圆角/间距）全局共用。
// 页面取色用 useTheme()，禁止直接 import 具体主题的颜色（会失去换肤能力）。
// =====================================================================

// ---------- 每套主题的颜色：语义命名，避免「蓝色 #2563eb」裸用 ----------

/** 主题颜色结构（三套主题共用；显式接口而非 typeof 推导，
 *  否则 as const 的字面量类型会让不同主题互相不兼容、build 报错） */
export interface ThemeColors {
  brand: {
    primary: string; primaryBg: string; primaryBgPressed: string;
    primaryBorder: string; primaryBorderPressed: string;
    /** 用于正文/边框/链接（落在 bg.page / bg.surface 上）—— 必须满足 WCAG AA 4.5:1
     *  对比度。暗色主题的 primary 偏暗，单独声明一个更亮的可读版 */
    linkText: string;
    /** 用于主色底（primaryBg）上的文字 —— 反色，白底深字，深底白字 */
    onPrimaryBg: string;
  };
  text: { primary: string; secondary: string; tertiary: string; inverse: string };
  status: {
    success: string; successStrong: string; successBg: string; successBorder: string;
    danger: string; dangerStrong: string; dangerBg: string;
    warning: string; warningBg: string; caution: string; cautionBg: string;
  };
  border: { default: string; subtle: string; row: string };
  bg: { page: string; surface: string; muted: string; disabled: string };
  muted: { fg: string; bg: string };
}

/** 暗夜紫：CodeBuddy 控制台风格（默认主题） */
const DARK_COLORS: ThemeColors = {
  brand: {
    primary: "#6d4fe3",           // 主按钮、链接（紫，饱和度压低一档，手机不刺眼）
    primaryBg: "#2b2352",         // 品牌暗底（badge/问号按钮）
    primaryBgPressed: "#382d68",  // 品牌更亮暗底（激活态）
    primaryBorder: "#4c3f8f",     // 品牌边框
    primaryBorderPressed: "#6a58c4", // 品牌亮边框（激活态）
    // 暗色主题下 primary 在 bg.surface 上对比度只有 ~3.7:1（< WCAG AA 4.5:1），
    // 链接/描边按钮在深色上看不清——这里专门给"文字+边框"用的更亮版
    linkText: "#a78bfa",          // purple-400，落在 bg.page/bg.surface 上约 7:1
    onPrimaryBg: "#e8eaf0",       // 落在 primaryBg 上的文字（chip/badge 内），反色白
  },
  text: {
    primary: "#e8eaf0",           // 主标题/正文（近白）
    secondary: "#9aa1ad",         // 次级文字/说明
    tertiary: "#c3c8d2",          // 中性文字（表格内文等）
    inverse: "#fff",              // 反色文字（紫底按钮内文字）
  },
  status: {
    success: "#4ade80",
    successStrong: "#86efac",
    successBg: "#12291d",
    successBorder: "#245c3c",
    danger: "#f87171",
    dangerStrong: "#fca5a5",
    dangerBg: "#2c1414",
    warning: "#fb923c", warningBg: "#2e1c10",
    caution: "#fbbf24", cautionBg: "#2d2410",
  },
  border: {
    default: "#3a3d4a",   // 输入框/普通按钮边框
    subtle: "#2a2d38",    // 卡片/分隔线
    row: "#22242d",       // 表格行分隔
  },
  bg: {
    page: "#0f1016",      // 页面背景（暗夜）
    surface: "#17181f",   // 卡片/输入框（微亮一档）
    muted: "#1d1e26",     // 弱底色（附件预览）
    disabled: "#232430", // 输入框 disabled 状态
  },
  muted: {
    fg: "#6b7280",        // 占位符/disabled 文字
    bg: "#33364a",        // disabled 按钮背景
  },
};

/** 经典浅色：换肤前的原始主题（浅底蓝字） */
const LIGHT_COLORS: ThemeColors = {
  brand: {
    primary: "#2563eb",
    primaryBg: "#eff6ff",
    primaryBgPressed: "#dbeafe",
    primaryBorder: "#bfdbfe",
    primaryBorderPressed: "#93c5fd",
    // 浅色主题下 primary 在白底上对比度 5.3:1（≥ AA 4.5:1），无需单独声明
    linkText: "#2563eb",
    onPrimaryBg: "#1e3a8a",       // 浅色主色底上的文字（深蓝，更清晰）
  },
  text: {
    primary: "#1f2329",
    secondary: "#646a73",
    tertiary: "#374151",
    inverse: "#fff",
  },
  status: {
    success: "#16a34a",
    successStrong: "#15803d",
    successBg: "#f0fdf4",
    successBorder: "#bbf7d0",
    danger: "#dc2626",
    dangerStrong: "#b91c1c",
    dangerBg: "#fef2f2",
    warning: "#c2410c", warningBg: "#fff7ed",
    caution: "#b45309", cautionBg: "#fffbeb",
  },
  border: {
    default: "#d1d5db",
    subtle: "#e5e7eb",
    row: "#f3f4f6",
  },
  bg: {
    page: "#f5f6f8",
    surface: "#fff",
    muted: "#f9fafb",
    disabled: "#f3f4f6",
  },
  muted: {
    fg: "#94a3b8",
    bg: "#9ca3af",
  },
};

/** 深空蓝：暗色 + 天青品牌色（第三主题） */
const OCEAN_COLORS: ThemeColors = {
  brand: {
    primary: "#38bdf8",           // 天青主按钮
    primaryBg: "#0c2733",
    primaryBgPressed: "#123447",
    primaryBorder: "#155e75",
    primaryBorderPressed: "#0e7490",
    // 深空蓝主题 primary 在 bg.page (~#0a121e) 上约 7:1，无需变更
    linkText: "#38bdf8",
    onPrimaryBg: "#e6edf5",       // 深色主色底上用浅色文字
  },
  text: {
    primary: "#e6edf5",
    secondary: "#8fa3b8",
    tertiary: "#c0cede",
    inverse: "#04141d",
  },
  status: {
    success: "#4ade80",
    successStrong: "#86efac",
    successBg: "#0d291f",
    successBorder: "#1f5c3c",
    danger: "#f87171",
    dangerStrong: "#fca5a5",
    dangerBg: "#2c1414",
    warning: "#fb923c", warningBg: "#2c1c10",
    caution: "#fbbf24", cautionBg: "#2b2310",
  },
  border: {
    default: "#2e3d52",
    subtle: "#1f2c3e",
    row: "#182634",
  },
  bg: {
    page: "#0a121e",
    surface: "#111b29",
    muted: "#16202e",
    disabled: "#1b2637",
  },
  muted: {
    fg: "#64748b",
    bg: "#2b3a52",
  },
};

// ---------- 主题注册表 ----------
export type ThemeName = keyof typeof THEMES;

export const THEMES = {
  dark: { label: "暗夜紫", colors: DARK_COLORS },
  light: { label: "经典浅色", colors: LIGHT_COLORS },
  ocean: { label: "深空蓝", colors: OCEAN_COLORS },
} as const;

/** 每套主题的边框样式预设（避免在多处重复 "1px solid #xxx"） */
export function borderStyleFor(c: ThemeColors) {
  return {
    card: `1px solid ${c.border.subtle}`,
    input: `1px solid ${c.border.default}`,
    row: `1px solid ${c.border.row}`,
  } as const;
}

// ---------- 字号：数字版（最常用） ----------
export const font = {
  xs: 12,   // 注释/版权/小标签
  sm: 13,   // 次级文字/表格头
  base: 14, // 正文
  md: 15,   // 较大正文/CTA
  lg: 16,   // 输入框/按钮（避免 iOS 聚焦放大）
  xl: 17,   // 二级标题
  xxl: 18,  // 大按钮/重点标签
} as const;

// ---------- 字号：流体 clamp 版（响应式标题） ----------
export const fontFluid = {
  hero: "clamp(26px, 7vw, 36px)",     // 首页 hero h1
  section: "clamp(19px, 5vw, 22px)",  // 项目详情 h1
} as const;

// ---------- 圆角 ----------
export const radius = {
  xs: 2,     // 侧边装饰条
  sm: 4,     // 气泡变角（user 气泡右下/assistant 左下）
  base: 6,   // 小标签/小按钮
  md: 10,    // 卡片/标准按钮/输入框
  lg: 12,    // 大输入框/主按钮
  xl: 16,    // 消息气泡/方案卡片（大圆角）
  pill: 999, // 状态徽章（完全圆角）
} as const;

// ---------- 间距（padding/margin/gap，px 值） ----------
export const space = {
  xxs: 4, xs: 6, sm: 8, md: 10, base: 12, lg: 14, xl: 16, xxl: 20, xxxl: 24,
  // 大于 24 的页面级间距：底部留白、容器外边距等，不要在小元素里用
  huge: 48,    // 页面底部留白（如项目详情 main）
  giant: 64,   // 首页 hero 底部留白
  pageTop: 60,     // 列表/中等页面顶部留白
  pageTopLarge: 80, // 错误/空状态页面顶部留白
} as const;

// ---------- 触控目标最小高度（移动端防误触） ----------
export const touch = {
  small: 36,  // 内联次级按钮（重试、取消）
  base: 40,   // 列表项按钮（删除）
  large: 44,  // 主交互按钮（确认/修改/发送）
  cta: 48,    // 首页 CTA
} as const;

// ---------- 文本行高（常用值集中） ----------
export const lineHeight = {
  tight: 1.3,
  normal: 1.6,
  relaxed: 1.7,
  loose: 1.8,
  list: 1.9,
} as const;
