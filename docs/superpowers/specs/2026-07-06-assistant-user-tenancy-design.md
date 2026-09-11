# 智能助手按用户多租户设计

## 1. 目标

DoorHandleCatch 的企业业务数据继续由所有登录用户共享，但智能助手数据采用“每个登录用户即一个租户”的隔离模型。

隔离范围包括：

- 聊天项目、会话和消息。
- 待确认动作与 Agent Checkpoint。
- Mem0 长期记忆与会话记忆。
- 助手请求限流状态。

公共 RAG 文档以及检测、设备、员工、模型等企业业务数据不做用户级隔离。

## 2. 租户身份

租户主键使用不可变的 `users.id`，用户名仅用于显示和兼容。

- JWT 增加 `userId` 声明。
- 认证成功后创建只读 `TenantContext(userId, username)`。
- TenantContext 只能来自 Spring Security 认证信息。
- 请求体、查询参数和请求头中的 `userId`、`tenantId` 或 `username` 不得覆盖当前租户。
- 用户改名不会改变租户身份，也不会丢失历史会话和 Mem0 记忆。

未登录请求返回 `401`。跨租户访问统一返回 `404`，避免泄露目标资源是否存在。

## 3. MySQL 数据模型

`chat_project` 和 `chat_session` 新增：

```sql
user_id BIGINT NULL
```

迁移完成后建立：

```sql
FOREIGN KEY (user_id) REFERENCES users(id)
  ON DELETE CASCADE ON UPDATE RESTRICT;

CREATE INDEX idx_chat_session_tenant_status_updated
  ON chat_session(user_id, status, updated_at DESC);

CREATE INDEX idx_chat_session_tenant_status_pinned_updated
  ON chat_session(user_id, status, pinned DESC, updated_at DESC);

CREATE INDEX idx_chat_project_tenant_sort_created
  ON chat_project(user_id, sort_order, created_at DESC);
```

`session_id` 和 `project_id` 继续作为全局外部标识。所有访问必须同时匹配外部标识与 `user_id`，不能只凭标识查询。

`chat_message` 与 `chat_pending_action` 通过 `session_id` 关联 `chat_session`，操作前必须完成会话租户校验。Checkpoint 存储于 `chat_session`，使用同一租户条件读写。

`username` 字段在本次迁移中保留并继续写入，用于展示、审计和回滚；读取授权只依赖 `user_id`。

## 4. Mem0 隔离

Mem0 使用三维实体范围：

```text
user_id = doorhandlecatch:user:{users.id}
app_id  = doorhandlecatch
run_id  = chat_session.session_id
```

- 所有新增记忆必须携带 `user_id`、`app_id` 和当前会话 `run_id`。
- 所有搜索必须使用相同范围，禁止无过滤搜索或 `*` 通配符。
- 用户长期偏好可按 `user_id + app_id` 检索，并显式覆盖全部 `run_id`。
- 当前会话记忆按 `user_id + app_id + run_id` 精确检索。
- 删除记忆至少指定 `user_id + app_id`，禁止项目级全量删除。
- Mem0 不保存公共 RAG 文档；公共知识继续由现有 RAG 服务提供。

## 5. 请求流程

```text
JWT 认证
  -> 解析 userId 与 username
  -> 创建 TenantContext
  -> 以 userId 校验项目/会话所有权
  -> 读取租户消息、待确认动作和 Checkpoint
  -> 按 userId + appId + runId 检索 Mem0
  -> 执行 Agent
  -> 保存租户消息、Checkpoint 和 Mem0 记忆
```

`ChatSessionService` 和 `ChatProjectService` 的公共方法接收 TenantContext 或不可变 userId，不再将用户名作为授权主键。

`AgentOrchestratorService` 在发送消息、流式消息和确认动作之前统一校验会话租户。所有 Agent 节点共享同一 TenantContext，不能自行从提示词解析用户身份。

请求限流键使用不可变 userId，使不同用户互不占用额度。

## 6. 数据迁移

迁移按以下顺序执行：

1. 添加可空 `user_id` 字段。
2. 通过 `chat_project.username = users.username` 和 `chat_session.username = users.username` 回填。
3. 检查 `user_id IS NULL` 的记录数量。
4. 如存在无法匹配的记录，迁移停止并输出记录清单，不自动归属。
5. 添加外键和组合索引。
6. 将字段改为 `NOT NULL`。
7. 部署双写 `user_id + username`、仅读 `user_id` 的后端。

本次不删除 username 字段或旧索引。回滚时恢复按 username 查询，新增 user_id 数据可安全保留。

## 7. 错误处理与安全

- 缺少有效 TenantContext：`401`。
- 本租户不存在该项目、会话或动作：`404`。
- Mem0 调用失败：记录脱敏日志，助手继续运行但不使用长期记忆。
- 禁止在日志中输出 Mem0 完整记忆、JWT、密码或用户提示词中的敏感内容。
- 所有异步任务和 SSE 工作线程必须显式传递 TenantContext，不能依赖线程本地安全上下文持续存在。

## 8. 验收测试

- 用户 A 无法列出、读取、重命名、移动、归档或删除用户 B 的项目与会话。
- 用户 A 猜中用户 B 的 sessionId、projectId 或 actionId 时返回 `404`。
- 用户 A 的消息、Checkpoint 和待确认动作不会进入用户 B 的上下文。
- 两名用户发送相同问题时，仅召回各自 Mem0 记忆。
- Mem0 新增、搜索和删除请求包含正确的 user_id、app_id 与 run_id 范围。
- 用户改名后仍可通过不可变 userId 访问历史会话与记忆。
- 用户级限流互不影响。
- 公共 RAG 与企业业务查询仍对所有登录用户可用。
- 存量项目和会话回填后仍由原用户访问。
- 未登录请求返回 `401`。

## 9. 非目标

- 不实现企业级租户、组织成员关系或用户跨租户切换。
- 不隔离检测、设备、员工、模型和统计等企业业务数据。
- 不为每个用户创建独立数据库、表或 Chroma collection。
- 不允许用户共享、转移或协作编辑助手会话。
