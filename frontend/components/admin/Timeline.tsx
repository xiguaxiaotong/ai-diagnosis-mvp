"use client";

// W7 Day8：从 leads 详情页抽出的跟进时间线组件。
// 铁律（frontend/AGENTS.md）：同一结构 ≥2 次必须抽组件——leads 详情与
// 工单详情现在共用，字段名对齐后端（lead_notes / worksheet_notes 同构）。
import { useTheme } from "../../lib/theme";
import { font, space } from "../../lib/tokens";

// 与后端 _note_to_dict / _ws_note_to_dict 字段名对齐（lead_id/worksheet_id 差异字段组件不关心）
export interface TimelineNote {
  id: number;
  note_type: string;   // manual / status_change / system
  content: string;
  admin_username: string | null;
  created_at: string | null;
}

export function Timeline({ notes }: { notes: TimelineNote[] }) {
  const { colors } = useTheme();

  const noteTypeColor = (t: string): string =>
    // 系统记录（status_change + system）默认中性色；手动跟进用主题色突出
    t === "manual" ? colors.brand.primary : colors.text.tertiary;

  if (notes.length === 0) {
    return (
      <p style={{ color: colors.text.tertiary, textAlign: "center", padding: space.lg }}>
        暂无记录
      </p>
    );
  }

  return (
    <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {notes.map((n) => (
        <li
          key={n.id}
          style={{
            borderLeft: `2px solid ${noteTypeColor(n.note_type)}`,
            paddingLeft: space.md,
            marginLeft: space.xs,
            paddingBottom: space.md,
            marginBottom: space.md,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: space.xs,
              fontSize: font.xs,
              color: colors.text.tertiary,
              marginBottom: space.xxs,
            }}
          >
            <span
              style={{
                fontWeight: 600,
                color: noteTypeColor(n.note_type),
              }}
            >
              {n.note_type === "manual" ? "手动跟进"
                : n.note_type === "status_change" ? "状态变更"
                : "系统记录"}
            </span>
            {n.admin_username && (
              <span>by @{n.admin_username}</span>
            )}
            <span style={{ marginLeft: "auto" }}>
              {n.created_at ? new Date(n.created_at).toLocaleString("zh-CN") : "—"}
            </span>
          </div>
          <div style={{ fontSize: font.base, color: colors.text.primary, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
            {n.content}
          </div>
        </li>
      ))}
    </ol>
  );
}
