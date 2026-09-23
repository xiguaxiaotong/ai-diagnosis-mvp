# AGENTS.md — AI 协作铁律（前端）

> 本文件是 **AI 编程助手** 在本项目开工前必须读的规则。
> 每次开新会话，先把本文件内容贴进 system prompt（或告诉 AI 自己读）。
> 改这里的任何规则前，请确认团队一致；规则一旦写入，所有 AI 行为自动照办。

---

## 1. 样式唯一来源：`lib/tokens.ts`

**铁律**：颜色 / 字号 / 圆角 / 间距 / 触控目标 / 行高 / 边框 一律从 `lib/tokens.ts` 导入。

```tsx
// ✅ 正确
import { colors, font, radius, space } from "../../lib/tokens";
<button style={{ background: colors.brand.primary, fontSize: font.base, borderRadius: radius.md, padding: `${space.base}px` }}>

// ❌ 错误：任何形式的硬编码
<button style={{ background: "#2563eb", fontSize: 14, borderRadius: 8, padding: "12px" }}>
```

**为什么**：
- 项目零组件库，inline-style 满天飞。AI 写新页面时随手 `#1d4ed8`、`12px`、`10px`，半年后全站散架。
- 改 token 一处 = 全站同步；改 5 个文件里的色号 = 永远改不齐。

**token 速查**（详见 `lib/tokens.ts`）：
- `colors.{brand,text,status,border,bg,muted}` — 按语义分桶，不要 `#xxxxxx` 裸用
- `font.{xs,sm,base,md,lg,xl,xxl}` — 12/13/14/15/16/17/18；响应式用 `fontFluid.hero/section`
- `radius.{xs,sm,base,md,lg,xl,pill}` — 2/4/6/8/10/12/999
- `space.{xxs,xs,sm,md,base,lg,xl,xxl,xxxl}` — 4/6/8/10/12/14/16/20/24
- `touch.{small,base,large,cta}` — 36/40/44/48（按钮 minHeight 必须从这里选）
- `lineHeight.{tight,normal,relaxed,loose,list}` — 1.3/1.6/1.7/1.8/1.9
- `borderStyle.{card,input,row}` — 预制 `1px solid #...`

---

## 2. 复用规则：同一结构出现 2 次必须抽组件

**铁律**：看到同一 UI 结构（按钮 / 卡片 / 输入框 / 徽章 / 空状态）出现 ≥2 次，立刻抽到 `components/ui/<Name>.tsx`。

**示例**（当前项目高频候选）：
| 出现位置 | 抽到 |
|---|---|
| 「主按钮」在首页 CTA / 确认方案 / 项目详情确认 | `components/ui/Button.tsx`（变体：primary/success/ghost） |
| 「卡片」在项目详情业务/技术/预算/可行性 | `components/ui/Card.tsx` |
| 「优先级徽章 P0/P1/P2」在表格里反复渲染 | `components/ui/Badge.tsx` |
| 「空状态」在历史列表 | `components/ui/EmptyState.tsx` |
| 「文件预览条」在聊天页 | `components/ui/FileChip.tsx` |

**为什么**：组件化是 AI 一致性的命门——没有它，AI 每次写都会"凭手感"，按钮一会儿圆角 8 一会儿 10。

---

## 3. 组件优先于内联样式

**铁律**：JSX 里写 `style={{...}}` 只用于**一次性布局**（flex 间距、容器宽度）。**可复用视觉**（按钮配色、徽章、卡片样式）必须走组件。

```tsx
// ✅ 一次性布局用 inline style
<div style={{ display: "flex", justifyContent: "space-between", gap: space.base }}>

// ✅ 可复用视觉走组件
<Button variant="primary" onClick={...}>开始新诊断</Button>

// ❌ 把所有样式都堆 inline（最容易让 AI 跑偏）
<button style={{ background: "#2563eb", color: "#fff", padding: "12px 36px", borderRadius: 10, ... }}>
```

---

## 4. 改本文件前必须同步的事项

1. **任何 token 字段重命名 / 删除** → 全站 grep 替换，PR 里附 `frontend/lib/tokens.ts` 改动 + 受影响文件清单。
2. **新增 token 字段**（如阴影 `shadow.md`）→ 优先复用业界命名（sm/md/lg），不要自创 `shadow1/shadow2`。
3. **新增通用组件** → 必须放到 `components/ui/<Name>.tsx`，**不要**直接堆到 `app/某页面/page.tsx`。
4. **业务组件**（如方案卡片、聊天气泡）放 `components/` 根目录；通用 UI 放 `components/ui/`。**两套不要混**。

---

## 5. 项目结构速查

```
frontend/
├── app/                       # Next.js App Router 页面
│   ├── layout.tsx             # 全站 layout（背景色 / 字体）
│   ├── page.tsx               # 首页：想法输入 + CTA
│   ├── chat/[id]/page.tsx     # 聊天页：SSE 流式对话
│   ├── projects/page.tsx       # 历史项目列表
│   └── project/[id]/page.tsx  # 方案详情：业务/技术/预算/可行性
├── components/                # 业务组件（按页面拆）
│   └── ui/                    # 通用 UI（待按规则 2 抽离）
├── lib/
│   ├── api.ts                 # 后端请求封装 + Project 类型
│   └── tokens.ts              # ⭐ 设计令牌唯一来源
└── AGENTS.md                  # ⭐ AI 协作铁律（本文件）
```

---

## 6. 验收 checklist（每次 AI 写完前端代码自查）

- [ ] 新加的 inline style 里没有任何 `#xxxxxx` / `rgb(...)` / `12px / 14px` 这种数字字面量
- [ ] 新加的按钮 `minHeight` 从 `touch` 取
- [ ] 新加的卡片 / 徽章 / 空状态如果之前出现过 → 已抽到 `components/ui/`
- [ ] 没有新建 `components/SomeButton.tsx` 这种结构式命名（应该 <Name>.tsx 不带前缀）
- [ ] `next build` 通过、TS 无错（`pnpm tsc --noEmit` 或 `npx tsc --noEmit`）

---

**本文件位置：`frontend/AGENTS.md`**
**最近更新：2026-09-22（破甲后第 1 天，落地 P0 最小骨架）**