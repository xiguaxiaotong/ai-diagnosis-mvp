# mypy 基线清单（W9 热身）

生成命令：`python -m mypy app`（配置见 `backend/mypy.ini`）

## 策略

- **strict 白名单**：`app/agent/trace.py`、`app/config.py` —— 已清零，后续改动不许新增报错
- **其余模块**：147 条 / 27 文件，只记录基线不阻塞 CI；按模块渐进收编，
  收编一个从下表划掉一个，收编完的模块加进 `mypy.ini` 的 strict 白名单
- 基线是快照不是承诺：只许下降不许上升，新代码建议自带类型标注

## 总量

**147 errors / 27 files**（2026-09-26，mypy 2.3.1，python_version=3.12）

## 按错误码汇总

| 错误码 | 数量 | 说明 | 收编难度 |
|---|---|---|---|
| type-arg | 63 | 裸 `dict`/`Callable` 缺类型参数 | 低（纯标注） |
| no-untyped-def | 55 | 函数缺参数/返回类型标注 | 低（纯标注） |
| union-attr | 23 | `str \| None` 上直接 `.strip()` 等 | 中（要加判空，注意别改行为） |
| arg-type | 6 | 实参类型不匹配 | 中 |
| no-untyped-call | 3 | 调用无类型函数 | 低 |
| has-type / attr-defined / misc / assignment / index / return-value | 各 1-2 | 零散 | 个别看 |
| no-any-return | 3 | 返回 Any | 低 |
| unused-ignore | 2 | 过期的 type: ignore | 低（删掉即可） |

## 按文件明细

| 文件 | 总数 | 主要错误码 |
|---|---|---|
| app/services/case_service.py | 18 | union-attr 17 |
| app/main.py | 17 | no-untyped-def 17 |
| app/api/diagnosis.py | 20 | no-untyped-def 11, type-arg 5 |
| app/infra/model_client.py | 19 | union-attr 5, no-untyped-def 4 |
| app/services/diagnosis_service.py | 10 | type-arg 7 |
| app/services/pdf_service.py | 6 | type-arg 4 |
| app/api/admin.py | 8 | type-arg / no-untyped-def / arg-type |
| app/agent/nodes/confirm.py | 4 | type-arg |
| app/agent/nodes/understand.py | 4 | type-arg |
| app/api/cases.py | 4 | no-untyped-def |
| app/infra/callbacks.py | 6 | type-arg 3 |
| app/agent/nodes/consult.py | 3 | type-arg |
| app/agent/nodes/output.py | 3 | type-arg |
| app/agent/nodes/budget.py | 3 | type-arg 2 |
| app/retrieval/vector_store.py | 3 | type-arg 2 |
| app/agent/nodes/_error.py | 2 | type-arg |
| app/infra/stream_sink.py | 2 | type-arg |
| app/agent/nodes/ask.py | 2 | type-arg |
| app/db/database.py | 2 | no-untyped-def |
| app/agent/budget_tier.py | 2 | type-arg |
| app/agent/graph.py | 2 | no-untyped-def 1 |
| 其余 6 文件（state/force/generate/retrieve/feasibility/project_service） | 各 1 | type-arg / no-untyped-def |

## 已收编（strict 清零）

- [x] app/agent/trace.py（2026-09-26：3 处补标注 + str() 收敛 Any）
- [x] app/config.py（2026-09-26：pydantic-settings 收编，字段全类型化）
