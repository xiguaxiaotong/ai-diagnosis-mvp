# 诊断 API 文档（M2，tag: m2-api）

基础地址：`http://localhost:8000`（后端启动方式见 README）。
交互式文档：http://localhost:8000/docs（FastAPI 自动生成）。

## 接口总览

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/chat` | 对话诊断（SSE 流式回复） |
| GET | `/api/project/{id}` | 项目详情：状态 + 完整方案 + 对话记录 |
| POST | `/api/project/{id}/confirm` | 确认循环：confirm / revise / reject |
| GET | `/api/projects` | 项目列表（M0） |
| POST | `/api/projects` | 创建项目（诊断前先建项目拿 id） |
| GET | `/api/health` | 健康检查 |

## 诊断会话生命周期

```
POST /api/projects                → 创建项目，得到 project_id
POST /api/chat（发想法）          → phase=clarify，AI 追问
POST /api/chat（回答追问，可多轮）→ phase=clarify … 直至信息补全
POST /api/chat（信息补全后）      → phase=confirm_wait，返回完整方案
POST /api/project/{id}/confirm    → confirm → done / revise → confirm_wait / reject → 结束
GET  /api/project/{id}            → 任意时刻可拉取最新方案与对话记录
```

## POST /api/chat

请求体：

```json
{ "project_id": 1, "message": "我想做个点单小程序" }
```

响应：`text/event-stream`（SSE）。事件格式 `data: <JSON>\n\n`，顺序为
`meta` → 多个 `delta` → `done`：

```json
data: {"type": "meta", "phase": "clarify", "questions": [...], "revision_round": 0}

data: {"type": "delta", "content": "为了给您"}
data: {"type": "delta", "content": "出准确的方案"}

data: {"type": "done"}
```

meta 事件字段：

| 字段 | 说明 |
|---|---|
| `phase` | `clarify`（追问中）/ `confirm_wait`（方案已生成待确认）/ `done`（已确认）/ `reject`（已放弃） |
| `questions` | 追问问题列表（仅 `clarify` 阶段） |
| `revision_round` | 当前方案修改轮次（`confirm_wait` 阶段） |

前端消费方式（fetch 流式读取，非 EventSource，因为要 POST）：

```ts
const resp = await fetch(`${API}/api/chat`, { method: "POST", body: JSON.stringify(body) });
const reader = resp.body!.getReader();
const decoder = new TextDecoder();
let buf = "";
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  // 按 "\n\n" 切分，解析 "data: {...}" 渲染 delta
}
```

错误：项目不存在返回 `404 {"detail": "项目不存在"}`。

## POST /api/project/{id}/confirm

仅在 `phase=confirm_wait` 时调用。

```json
{ "action": "confirm" }                                    // 确认方案 → done
{ "action": "revise", "feedback": "去掉营销活动" }          // 要求修改 → 重新生成方案，revision_round +1
{ "action": "reject" }                                     // 放弃诊断
```

响应（JSON）：

```json
{
  "phase": "confirm_wait",
  "reply": "已按要求修改方案…",
  "revision_round": 1,
  "solution": { "requirements": {}, "plan": {}, "budget": {}, "feasibility": {}, "final_output": {} }
}
```

- `revise` 必须带非空 `feedback`，否则 `422`
- `solution` 结构见下

## GET /api/project/{id}

```json
{
  "id": 1,
  "title": "扫码点单",
  "raw_idea": "…",
  "status": "plan_generated",
  "budget_min": 65000.0,
  "budget_max": 119000.0,
  "solution": {
    "requirements": { "…": "结构化需求（功能模块/用户角色/约束）" },
    "plan":         { "summary": "…", "modules": [], "tech_stack": [], "phases": [], "risks": [] },
    "budget":       { "total_min": 0, "total_max": 0, "line_items": [], "assumptions": [], "budget_match": "…" },
    "feasibility":  { "overall": "可行", "risk_level": "低", "suggestions": [] },
    "final_output": { "…": "面向商业计划书的最终汇总" }
  },
  "messages": [ { "id": 1, "role": "user", "content": "…", "created_at": "…" } ]
}
```

## curl 联调示例

```bash
# 创建项目
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" -d '{"title": "点单小程序"}'

# 发起诊断（-N 关闭缓冲，流式看到逐块输出）
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1, "message": "我想做个点单小程序"}'

# 确认方案
curl -X POST http://localhost:8000/api/project/1/confirm \
  -H "Content-Type: application/json" -d '{"action": "confirm"}'
```
