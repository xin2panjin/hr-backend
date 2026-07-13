# HR 招聘助手 SSE 流式输出改造计划

## 1. 目标与边界

为已完成的“招聘助手会话管理”补充流式交互：用户发送消息后，前端可实时看到模型文本、人才检索和候选人详情/对比等工具过程，而不是等待一次性响应。

本次只改造 HR 招聘助手。候选人邀约 Agent、邮件流程和普通人才库检索接口不接入 SSE。

保留现有同步接口：

```text
POST /assistant/conversations/{conversation_id}/messages
```

新增流式接口：

```text
POST /assistant/conversations/{conversation_id}/messages/stream
Accept: text/event-stream
```

## 2. SSE 事件协议

| 事件 | 数据 | 前端行为 |
| --- | --- | --- |
| `message_start` | `conversation_id`、`user_message_id` | 创建本轮助手占位消息 |
| `content_delta` | `content` | 追加渲染模型文本增量 |
| `tool_start` | `tool`、`display` | 显示“正在检索人才库”等过程状态 |
| `tool_end` | `tool`、`display` | 显示工具完成状态 |
| `message_end` | `message_id`、`answer`、`artifacts`、`candidate_ids` | 固化本轮消息与候选人卡片 |
| `error` | `code`、`message` | 结束加载并展示可理解的错误 |

事件数据均使用 JSON；不得通过事件发送模型内部推理过程、Token 用量明细、候选人联系方式等敏感数据。

## 3. 实施待办

- [x] 3.1 在 `HRAssistantAgent` 增加 LangGraph `astream` 封装和最终 State 获取能力。
- [x] 3.2 在 `HRAssistantConversationService` 增加流式发送方法：先持久化用户消息，转换 LangGraph 事件，结束后持久化助手消息和工具审计摘要。
- [x] 3.3 提取同步/流式共用的消息持久化和候选人产物解析逻辑，防止两条链路行为漂移。
- [x] 3.4 在 `/assistant` 增加 `messages/stream` 路由，使用 FastAPI `StreamingResponse` 输出标准 SSE。
- [x] 3.5 为流式 Service 与路由补充单元测试：事件顺序、文本累积、工具事件、异常、所有权和归档会话。
- [x] 3.6 在前端 API 层用 `fetch + ReadableStream` 实现 SSE 解析器，携带现有 Bearer Token。
- [x] 3.7 改造 HR 助手页面：实时追加文本、显示工具进度、在 `message_end` 渲染 artifacts；保留会话切换和历史回放。
- [x] 3.8 执行后端完整测试、前端类型检查和生产构建；清理构建产物。

## 4. 关键实现约束

1. 外部模型调用不能包在数据库事务中。用户消息先用短事务落库，流结束后再用短事务写入助手消息和工具摘要。
2. 客户端断开不应写入伪造的“成功助手消息”；服务端记录日志并让 LangGraph checkpoint 保持真实执行状态。
3. SSE 完成前不把临时 token 写入 `assistant_messages`；只在 `message_end` 后写入最终回答。
4. `tool_start` / `tool_end` 只使用工具名和脱敏展示文案。候选人详情仍仅在最终 artifact 中以已授权的脱敏字段返回。
5. 同步接口继续保留，便于非浏览器调用方和故障降级。

## 5. 验收清单

- [ ] HR 或超级管理员可通过流式接口收到 `message_start`、至少一个 `content_delta`、`message_end`。（单元测试覆盖；待使用 HR 账号进行真实模型验收）
- [ ] 发起人才检索时，前端依次看到 `search_talent_pool` 的开始和完成状态，并在结束后渲染候选人卡片。（事件与页面逻辑已覆盖；待浏览器联调）
- [ ] 发送候选人详情、候选人对比请求时，工具进度和最终 artifact 正常显示。（共用工具事件与 artifact 渲染逻辑；待浏览器联调）
- [ ] 刷新页面或切换会话后，能从数据库恢复最终消息与 artifacts；不展示临时流式状态。（待浏览器联调）
- [ ] 非 HR 用户仍被前端路由和后端 403 双重限制。（代码已实现；待浏览器联调）
- [ ] 已归档会话返回 409，不建立流式模型调用。（Service 预校验；待接口联调）
- [x] 流式模型异常时，客户端收到 `error`，不会产生伪造的助手成功消息。
- [x] 后端完整测试通过；前端类型检查和生产构建通过；无新增构建产物进入 Git。

## 6. 完成记录

已完成：

```text
后端：.venv/bin/python -m pytest -q
结果：93 passed

前端：npm run type-check && npm run build-only
结果：通过（仅有 Vite bundle size 提示，不影响构建）
```

真实模型、Milvus 与浏览器 SSE 联调仍需使用具备 HR 权限的账号执行一次人工验收。
