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
    primary: string; primaryHover: string; primaryPressed: string;
    primaryBg: string; primaryBgPressed: string;
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
  /** 卡片浮起阴影：浅色主题柔和投影（页面浅灰托白卡），深色主题分层靠背景亮度差、给 none */
  shadow: { card: string };
}

/** 暗夜紫：高端/神秘/年轻/夜间。高级感关键：底色带紫调不纯黑，
 *  页面 #14121C → 卡片 #1D1A28 → 悬浮/输入 #252133 亮三档分层 */
const DARK_COLORS: ThemeColors = {
  brand: {
    primary: "#7c5cfc",           // 主按钮（亮紫，深底上足够跳）
    primaryHover: "#8d70ff",      // 桌面 hover：亮一档
    primaryPressed: "#6a4ae0",    // 按下：暗一档
    primaryBg: "#2a2350",         // 品牌染色暗底（chip/约束横幅）
    primaryBgPressed: "#3a2f6e",  // chip 选中染色底
    primaryBorder: "#4a4266",     // 品牌边框 = 次按钮描边（雾紫）
    primaryBorderPressed: "#7c5cfc", // 激活态边框直接用主色，选中更醒目
    // 暗色主题下 primary 在 bg.surface 上对比度不足 AA，
    // 链接/描边按钮文字用专门的可读亮版
    linkText: "#a78bfa",          // purple-400，落在新深底上 ≥ 4.5:1
    onPrimaryBg: "#f2f0f7",       // 染色底上的文字（近白）
  },
  text: {
    primary: "#f2f0f7",           // 主文字（带紫调的近白）
    secondary: "#a79fb8",         // 次文字（紫灰）
    tertiary: "#c9c2d9",          // 中性文字（表格内文等）
    inverse: "#fff",              // 反色文字（紫底按钮内）
  },
  status: {
    success: "#34d399",           // 成功徽章：亮绿（深底上醒目）
    successStrong: "#6ee7b7",
    successBg: "#12291d",
    successBorder: "#245c3c",
    danger: "#f87171",
    dangerStrong: "#fca5a5",
    dangerBg: "#2c1414",
    warning: "#fb923c", warningBg: "#2e1c10",
    caution: "#fbbf24", cautionBg: "#2d2410",
  },
  border: {
    default: "#4a4266",   // 输入框/次按钮描边（雾紫）
    subtle: "#2c2740",    // 卡片边/分隔线（紫调）
    row: "#251f36",       // 表格行分隔（比 subtle 再暗半档）
  },
  bg: {
    page: "#14121c",      // 页面底（带紫调的深黑）
    surface: "#1d1a28",   // 卡片（亮一档）
    muted: "#252133",     // 输入框/悬浮（再亮一档，三档分层）
    disabled: "#2c2839",  // disabled 再亮半档
  },
  muted: {
    fg: "#6e6780",        // 占位符/disabled 文字（紫灰）
    bg: "#3a3450",        // disabled 按钮背景（紫调）
  },
  shadow: { card: "none" }, // 深色分层靠背景亮度差，不加投影
};

/** 经典浅色：干净/专业/白天通用（给老板看的主力主题）。
 *  页面浅灰 #F6F7F9 托纯白卡片 + 柔和投影让卡片「浮」起来；主色经典蓝（可信） */
const LIGHT_COLORS: ThemeColors = {
  brand: {
    primary: "#2563eb",           // 主按钮（经典蓝，专业可信）
    primaryHover: "#1d4ed8",      // hover：加深
    primaryPressed: "#1e40af",    // 按下：再加深
    primaryBg: "#eff6ff",
    primaryBgPressed: "#dbeafe",
    primaryBorder: "#c7d2e4",     // 次按钮描边（蓝灰，比纯灰柔和）
    primaryBorderPressed: "#93c5fd",
    // 浅色主题下 primary 在白底上对比度 5.3:1（≥ AA 4.5:1），无需单独声明
    linkText: "#2563eb",
    onPrimaryBg: "#1e3a8a",       // 浅色主色底上的文字（深蓝）
  },
  text: {
    primary: "#1f2329",           // 主文字
    secondary: "#6b7280",         // 次文字
    tertiary: "#374151",          // 中性文字
    inverse: "#fff",
  },
  status: {
    success: "#16a34a",           // 成功徽章
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
    default: "#c7d2e4",   // 输入框/次按钮描边（蓝灰）
    subtle: "#e5e7eb",    // 卡片边/分隔
    row: "#f0f1f4",       // 表格行分隔
  },
  bg: {
    page: "#f6f7f9",      // 页面浅灰（托住白卡）
    surface: "#ffffff",   // 卡片纯白
    muted: "#f9fafb",     // 弱底色（附件预览，白上加极浅灰区分）
    disabled: "#eef0f3",
  },
  muted: {
    fg: "#9ca3af",        // 占位符
    bg: "#e5e7eb",        // disabled 按钮背景
  },
  shadow: {
    // 柔和双层投影：让白卡在浅灰页面上「浮」起来（主力主题的质感来源）
    card: "0 1px 2px rgba(16,24,40,.04), 0 2px 8px rgba(16,24,40,.06)",
  },
};

/** 深空蓝：冷静/护眼/长时间（技术/工作室、夜间）。
 *  底是深蓝黑 #0B1420 不是纯灰黑；卡片/输入框亮两档；主色亮青 */
const OCEAN_COLORS: ThemeColors = {
  brand: {
    primary: "#38bdf8",           // 主按钮（亮青）
    primaryHover: "#5ccbfa",      // hover：亮一档
    primaryPressed: "#2aa3d9",    // 按下：暗一档
    primaryBg: "#0c2733",         // 青调染色暗底
    primaryBgPressed: "#123a4d",  // chip 选中染色底
    primaryBorder: "#2c4257",     // 次按钮描边（青调灰蓝）
    primaryBorderPressed: "#38bdf8", // 激活态边框用主色
    // 亮青在深蓝黑底上对比度充足；链接用更柔的天蓝
    linkText: "#7dd3fc",
    onPrimaryBg: "#e8f0f8",
  },
  text: {
    primary: "#e8f0f8",           // 主文字（带蓝调近白）
    secondary: "#93a5b8",         // 次文字（蓝灰）
    tertiary: "#b9cbdc",          // 中性文字
    inverse: "#04141d",           // 亮青底上用深蓝黑字（反色）
  },
  status: {
    success: "#34d399",           // 成功徽章：亮绿
    successStrong: "#6ee7b7",
    successBg: "#0d291f",
    successBorder: "#1f5c3c",
    danger: "#f87171",
    dangerStrong: "#fca5a5",
    dangerBg: "#2c1414",
    warning: "#fb923c", warningBg: "#2c1c10",
    caution: "#fbbf24", cautionBg: "#2b2310",
  },
  border: {
    default: "#2c4257",   // 输入框/次按钮描边（青调）
    subtle: "#1e3043",    // 卡片边/分隔
    row: "#16283a",       // 表格行分隔
  },
  bg: {
    page: "#0b1420",      // 页面底（深蓝黑）
    surface: "#111e2e",   // 卡片（亮一档）
    muted: "#182839",     // 输入框/悬浮（再亮一档）
    disabled: "#1e3145",
  },
  muted: {
    fg: "#5c6e80",        // 占位符（蓝灰）
    bg: "#2c4257",        // disabled 按钮背景
  },
  shadow: { card: "none" }, // 深色分层靠背景亮度差
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
