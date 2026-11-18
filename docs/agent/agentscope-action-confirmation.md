# AgentScope 质检分配与人工确认

阶段 C 第一项，实施日期：2026-10-13，分支：`java`。当前只开放主管的质检任务分配；上传、检测重试、复核结论、模型发布仍未作为 Agent 写工具开放。

## 当前流程

主管向助手提出明确的任务编号、质检站点和责任人员工账号。主 Agent 委派 `detection-quality`，专业 Agent 的 `propose_quality_assignment` 工具只保存分配提议，返回 `PENDING`，不修改检测任务。提议绑定服务端账号、会话、原运行和 SDK 调用编号。

在主站聊天抽屉的确认卡片或菜单“助手操作确认”中核对参数，再点击确认分配、拒绝或取消。独立 Agent UI 同样能提出分配提议，通过“查看并确认操作”进入共用的主站确认页。已有会话刷新后从数据库读取提议，不重新调用模型。

运行轨迹页也按所选 runId 展示关联提议及审计。运行事件和确认审计分别持久化，通过原运行及 SDK 调用编号关联，尚未统一为完整 Turn/Call 图。

确认请求只允许决策和操作版本。服务端加载已存参数，检查所属权、当前主管角色、员工账号、原运行状态、策略版本、有效期及任务快照，再在同一事务中执行分配和审计。客户端不能提供新的工具名、责任人、业务参数或成功结果。聊天中说“批准”不代替确认卡片。

任务必须已完成检测或部分检测失败，且尚未最终关闭。责任人必须是系统中已有的员工账号，不将模型提供的姓名直接视为账号或员工绑定关系。现有业务页面的分配接口也限定主管角色。

原有通用异常处理会把方法权限拒绝包装为 HTTP 200；现已增加系统模块的权限异常处理，返回 HTTP 403 和统一错误码，不输出内部策略信息。

## 框架与业务边界

沿用 AgentScope Java 2.0.4 的 Harness / ReAct、Toolkit 和权限接口。显式注册允许的委派、只读工具与提议工具，未登记工具由 SDK 权限规则和运行中间件拒绝。提议工具标记为非只读；允许保存提议不意味着允许业务分配。[锁定版本的官方权限设计](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/permission-system.md)、[官方许可证](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。

此次采用“提议结束本轮，用户通过受控接口确认”的应用流程，没有启用 SDK 的 `PERMISSION_ASKING` 快照恢复或客户端自由 resume，不声称已实现任意执行点续跑。确认和拒绝均不再调用模型。

## 配置与迁移

执行增量迁移 `sql/mysql/migration-V19-agent-confirmation.sql`，classpath 副本在 AI 模块 `src/main/resources/db/`。仅新增 `agent_pending_action`、`agent_action_audit`，保留旧 `chat_pending_action` 及原业务数据，旧动作仍不能恢复执行。

```dotenv
AGENT_RUN_JOURNAL_ENABLED=true
AGENT_ACTION_CONFIRMATION_ENABLED=true
```

模板默认关闭确认功能。启用时后端检查运行日志和两张新表，缺少前置条件时启动失败；本地启动脚本不会自动迁移。配置 `APP_CORS_ALLOWED_ORIGINS` 时应包括实际业务前端来源，它也用于确认接口的来源检查。浏览器请求需来自允许来源，并带 `X-Agent-Action`；跨站请求被拒绝。CLI 无 Origin 时仍须有效 Cookie 和指定请求头。

## 状态与原子性

提议有效期为 10 分钟，依据数据库时间判断。未决状态为 `PENDING`；终态包括 `SUCCEEDED`、`REJECTED`、`CANCELLED`、`EXPIRED` 和 `INVALIDATED`。批准、执行中间过程记录在同一事务的审计事件中，不将短暂 `APPROVED` 或 `EXECUTING` 状态单独提交给外部读者。

同一运行、同一规范化参数返回原提议；同一用户对同一任务提出新参数时，旧待确认提议失效。重复确认、重复拒绝及相反决策返回原终态，不产生第二次业务写入。操作版本不匹配返回 409；他人操作 ID 的读取、确认、取消和审计查询返回 404。

确认采用运行、操作、资源的锁顺序，原运行已取消或中断时拒绝执行。任务使用完整资源快照的 SHA-256 摘要比较，确认时锁定任务并重新核对；这是状态快照校验，尚未引入覆盖全部业务写入的单调资源版本列。

分配调用检测模块的业务服务，保留已有业务规则和缓存失效行为，并核对实际保存的站点、责任人、截止时间、备注及流转状态。业务更新、提议终态和必要审计共用一个 MySQL 事务。数据库、审计或结果核验失败时回滚，不写成功状态。当前流程没有 Kafka、OSS 或其他外部写副作用，不将此实现用于外部操作重试或结果未知的对账。

## 接口与审计

| 接口 | 用途 |
| --- | --- |
| `GET /api/agent/actions?sessionId=…&runId=…&limit=50` | 当前账号的最近提议，可按会话和运行过滤 |
| `GET /api/agent/actions/{id}` | 当前账号的提议详情 |
| `POST /api/agent/actions/{id}/confirm` | `{ "decision": "APPROVE"或"REJECT", "version": 1 }`，请求头 `X-Agent-Action: confirm` |
| `POST /api/agent/actions/{id}/cancel` | `{ "version": 1 }`，请求头 `X-Agent-Action: cancel` |
| `GET /api/agent/actions/{id}/audit` | 当前账号的提议审计，按持久编号排序 |

HTTP 没有通用的任意工具执行或提议入口；提议由绑定可信运行上下文的 AgentScope 工具创建。列表最多返回最近 100 条，当前 UI 取最近 50 条，尚未实现全部动作历史的游标分页。

审计记录创建、用户决策、权限判定、执行开始、业务变化和执行结果，关联 action、run、资源、参数摘要、角色及策略版本。审计不记录模型 Prompt、工具结果正文、API Key、Cookie 或 SQL 连接凭证。业务参数和必要前后值仅保存在所属账号可读取的确认记录中。此处不是全业务审计平台或防篡改存储。

## 验证和后续

规则测试覆盖提议不写业务、批准执行、重复及并发确认、拒绝、取消、过期、账号隔离、角色撤销、参数变化、资源变化、策略变化、原运行取消、参数篡改及审计故障回滚。SDK 替身测试走真实 Harness → 专业 ReAct → 提议工具，不调用付费模型。

本机联调使用显式开关 `agent.actions.local.mysql=true`，只新增 `agent-confirm-fixture-*` 测试任务、标记会话及操作记录，数据保留便于复核。原业务任务不用于测试分配，运行标记为 `fixture-no-model-call`，不作为模型端到端通过的证据。验证报告在 `work/stage-c-local-mysql.json`，浏览器报告在 `work/stage-c-browser.json`。

2026-10-13 验收已通过：全量 Maven verify 成功（288 项，执行 277 项，11 项按显式开关跳过）；最终打包与相关规则测试通过；显式开启后，两个真实 MySQL / 后端联调测试均通过。确认链路验证批准、重复确认只写一次、截止时间、拒绝、过期、任务变化、他人操作 ID、请求头、参数篡改及来源拒绝。浏览器六项通过，包括桌面确认与审计、刷新不重放、移动端无横向溢出、独立 Agent UI 链接以及员工看不到主管提议；页面无 JavaScript 错误，确认只发一次 POST，没有付费模型请求。主站生产构建、前端 Node 测试 16 项、记忆隔离测试 3 项通过。

全量构建日志为 `work/task-scope-full-verify.log`；最终打包日志为 `work/task-scope-final-package.log`；真实联调最终日志为 `work/stage-c-final-live.log`。跳过项包括可选运行日志 MySQL 测试、付费模型测试及这两个须显式启用的本机联调测试；本次另外执行了后两项，未执行付费模型验收。

尚待后续阶段完成：用户与员工/部门的完整绑定、其他写工具、独立业务审批、外部副作用 outbox 与对账、统一 Turn/Call 与全业务审计、SDK 状态持久恢复、固定 Eval 数据集和评分报告、长任务与微服务拆分。
