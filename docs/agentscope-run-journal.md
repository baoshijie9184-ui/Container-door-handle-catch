# AgentScope 单体运行与事件日志

2026-10-16 界面更新：已提供运行历史、分类时间线、事件详情、父子调用跳转、同运行结果卡片、连续序号补读与受控导出的追溯工作区。实现与数据边界见 [Agent 执行追溯工作区](Agent执行追溯工作区.md)。运行事件不采集提示词或工具输入输出正文；后续的受控网页来源与引用映射写入独立私有表，详见 [调研来源与引用追溯](Agent调研来源与引用追溯.md)。

更新：2026-10-12。阶段 B 的已实施部分。Agent 继续运行在当前 Spring Boot 单体中；本功能不部署新服务，也不重写 SDK 推理循环。

## 实现与边界

两个入口在模型执行前创建持久运行：主站 `/api/chat-assistant/messages` / `messages/stream`，独立 AG-UI `/agui/run`。`RoleAgentFactory` 将同一运行的 `AgentJournalMiddleware` 注册到 Harness 主 Agent 和专业 ReActAgent，利用锁定的 AgentScope Java 2.0.4 的 `onAgent`、`onModelCall`、`onActing` 生命周期记录实际调用。专业委派附带 `parentCallId`，可将专业业务工具与主 Agent 的委派调用关联。依据 [官方 2.0.4 中间件接口](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/middleware.md)，复用 Apache-2.0 SDK，不复制第三方源码。

`agent_run` 保存用户、会话、入口、默认模型、只读策略版本、运行状态、序号、实例与租约；`agent_run_event` 保存顺序事件和白名单 JSON。使用递增 BIGINT 主键，公开运行 ID 使用 UUID 辅助唯一键。事件插入和序号更新在同一个短事务中完成，运行行通过 `FOR UPDATE` 序列化；模型、网络和业务工具查询不在该事务内。

事件只记录 Agent/工具名、调用 ID、父调用 ID、策略与范围、真实返回状态、相对时间/耗时和 SDK 返回的 token 用量。用户问题、提示词、参考资料、工具参数、工具结果、模型回答、思考正文、网络异常正文与凭证不写入这些表。未返回用量时不补造 token 数。`defaultModel` 是配置默认值，不是每次请求的实际备用模型。

2026-10-16 已补齐调用级模型路由元数据：每次模型逻辑请求有独立 `modelRequestId`，记录实际选择的候选接入标识、请求模型名、候选序号、耗时、首段内容时间、脱敏失败分类、备用选择与熔断跳过。复用现有 JSON 字段，无需新增迁移；SDK 内部 HTTP 重试及供应商内部路由未采集，详见 [模型调用路由追溯](模型调用路由追溯.md)。

角色白名单审计在 SDK 工具执行前进行。`AUTHORIZATION_ALLOWED` 表示角色允许注册/调用该工具，业务资源所有权仍由业务 contracts 门面和 SQL 再校验。它不证明任意资源已授权。未登记工具记录 `AUTHORIZATION_DENIED` 后拒绝；日志写入失败阻止工具继续执行。当前工具仍全部只读，没有开放写入或确认绕行。

事件元数据预算为每轮至多 2000 条，超限终止运行，并可追加一条终态事件。日志接口不提供事件修改和删除，但数据库管理员仍能修改表；不能将其称作不可篡改审计、完整业务变更审计或全量模型正文归档。

## 启用与迁移

配置模板默认关闭，以兼容尚未执行迁移的数据库。先在项目实际使用的 MySQL 8 库执行：

```text
sql/mysql/migration-V16-agentscope-run-journal.sql
```

同一脚本随 AI 模块打包在 `classpath:db/migration-V16-agentscope-run-journal.sql`。脚本只创建两张新表，不清空历史聊天，不修改旧状态 JSON 或业务记录。DDL 不自动随应用启动执行；执行前确认连接的是当前项目数据库。

迁移后设置 `.env` 或部署环境：

```dotenv
AGENT_RUN_JOURNAL_ENABLED=true
```

重启后端。启用时启动检查日志表，缺表会提示执行迁移。主站的 `agent-health` 返回 `runJournalEnabled`；轨迹页面根据该值显示持久运行历史。关闭时保留已有主站最新轨迹摘要，运行日志 API 返回 503。关闭开关是回退方式，已记录事件保留，回退不删除表或数据。

本机环境核验更新（2026-10-12）：业务库 `doorhandledb` 存在，之前的 1049 结论来自诊断脚本未处理 `.env` 地址外的引号，已纠正。现已向业务库执行 V16 新表迁移并开启 `AGENT_RUN_JOURNAL_ENABLED=true`，后端健康检查通过，迁移前后的原有业务表记录数一致。数据库地址、账号及历史数据保留。另已清理本机 `.env` 重复键，避免 dotenv-java 拒绝加载整份配置。迁移证据位于忽略的 `work/middlewares/database-migration-check.json`。此前隔离验证库 `doorhandle_agent_verify_ef8d5844c1` 仍保留，其信息记录于 `work/stage-b-mysql-fixture.json`。当前分支运行方式见 [服务器运行说明](服务器运行说明.md)。

## 所属权与接口

所有接口复用 HttpOnly Cookie / Spring Security 登录，身份通过 `AgentIdentity` 从 `TenantPrincipal` 与员工/主管角色构造。查询、补读、翻页和取消始终按当前 `user_id` 限定；员工和主管均不能读取其他账号的运行。Supervisor 身份不会授予跨用户日志访问权。

| 接口 | 行为 |
| --- | --- |
| `GET /api/agent/runs?sessionId=...&limit=20&beforeRunId=...` | 当前账号运行列表；可省略 sessionId 查询两个入口的全部运行；按内部递增 ID 向前翻页，limit 为 1–100 |
| `GET /api/agent/runs/{runId}` | 当前账号的单次运行元数据 |
| `GET /api/agent/runs/{runId}/events?after=0&limit=100` | sequence 大于 after 的有序事件，最多 100 条；只读补读不会调用模型或工具 |
| `POST /api/agent/runs/{runId}/cancel` | 使用服务器保存的本实例取消句柄；必须携带 `X-Agent-Action: cancel`，客户端不能提交工具结果、角色或恢复参数 |

这些 AI 接口返回原生 JSON 对象/数组，与 AG-UI 入口风格一致，不是主站 `Result.data` 包装。不存在和不属于本人均为 404；参数无效为 400；未启用或存储不可用为 503；并发/重复提交以及另一实例的取消请求为 409。

取消动作使用自定义请求头，使浏览器跨源请求必须预检，并沿用项目允许源 CORS 策略。普通表单 POST 无法提供该头。该措施只覆盖新增取消入口，不表示已为系统全部业务写接口补齐 CSRF 防护。

## 并发、重复提交与中断

两个入口仍共享本进程 `AgentRunRegistry`。启用日志后，数据库的 `(user_id, main_agent, session_id, active_slot)` 唯一键进一步拒绝同一会话的并发运行；RUNNING 使用 active_slot=1，终态将其设为 NULL，保留多轮历史。此处是数据库运行互斥约束，不是已实现跨实例执行调度或微服务运行平台。

AG-UI 的客户端 runId 作为 request_key；同用户、同入口重复使用该键返回 409，并通过运行历史查看已有结果，不重新调用模型。主站当前由服务端生成每轮请求键，尚未提供完整的客户端幂等重试契约。前端断流后不自动重发问题。

每个运行绑定本机实例与取消句柄；终态为 COMPLETED、ERROR、CANCELLED 或 INTERRUPTED。终态和对应事件在同一事务中提交，重复取消/完成不重复产生终态，也不会将已中断的迟到运行标为成功。

启用时每 30 秒续租，租约为 90 秒，采用数据库时钟；心跳只更新状态，不调用付费模型。过期的 RUNNING 通过行锁再次核对租约后标为 INTERRUPTED，释放活动槽位。重启后可读取已完成记录和过期中断结果；不会重新调用模型、重放工具或自动恢复 SDK 执行。未过期的孤立运行会等待租约到期。

从其他实例取消当前运行会返回 409，避免把没有确认中断的工作误标为已取消。跨实例取消消息、崩溃点 SDK 状态恢复和外部副作用对账尚未实现。当前只读工具无需恢复业务写操作。

## 前端

主站轨迹页面支持按当前会话或“全部入口运行”选择历史运行，显示调用编号、工具结果与运行相对时间。使用事件游标补读并按 sequence 去重，加载完全部分页才允许 JSON 导出，避免无提示截断。切换会话/运行清空旧事件；其他入口运行不展示当前主站会话的无关消息。

导出的是账号已有的脱敏事件数据，不是业务结果正文。当前客户端导出没有独立 TRACE_EXPORTED 业务审计，后续完整审计阶段再补齐。

## 验证与未完成项

H2 结构模拟测试覆盖事务、事件顺序、分页、重复请求、活动槽位、账号隔离、取消、租约和并发生产者。显式开启的 MySQL 测试在指定验证库执行同一组 JDBC 测试，直接使用原始 MySQL DDL；不依赖 H2 对 JSON、DATETIME 和索引的模拟结论。

SDK 模型和业务门面使用测试替身，验证主 Agent → 专业 Agent → 业务工具的真实 SDK 生命周期、父调用关联、权限拒绝、日志不可用时阻断，以及主站和 AG-UI 的持久终态。浏览器验证使用接口替身；它不是业务数据库/付费模型端到端验收。

仍需后续实施：SDK 状态持久后端、可靠后台任务、写工具持久人工确认与审批、完整 Turn/Call/业务变更审计、实际候选模型及 Prompt/Skill 版本、OTel 导出、Eval 数据集与报告、存储保留期/归档管理。微服务拆分仍在单体验收之后。


本轮验证记录：全模块 `clean verify` 通过，当时 258 项测试中 256 项通过、2 项付费模型检查跳过；其中 7 项 JDBC 用例真实连接 MySQL 8.3 隔离验证库。随后增加实际 SDK 取消与锁释放用例，4 项入口集成定向回归通过。当前报告累计 259 项，257 项通过、2 项跳过，失败/错误为 0。主站 21 项相关检查、生产构建及 7 项浏览器场景通过；浏览器额外验证全部入口开关可用键盘操作。没有运行真实业务数据和付费模型端到端检查。

构建保留现有前端大包体积提示，SDK 快速取消仍可能输出 CancellationException 的取消竞态日志；取消状态和锁释放测试通过，未通过全局错误屏蔽隐藏日志。诊断记录在忽略的 `work/stage-b-final-verify.log`、`work/stage-b-cancellation-tests.log`、`work/stage-b-verification-summary.json` 和 `work/stage-b-browser-result.json`。

手动复核命令：

```powershell
mvn -pl doorhandle-server -am clean verify
mvn -pl doorhandle-module-ai -am test '-Dtest=MysqlAgentJournalTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dagent.journal.mysql=true' '-Dagent.journal.mysql.database=doorhandle_agent_verify_ef8d5844c1' '-Dagent.journal.project=D:/AI/lunwen1/DoorHandleCatch'
```

普通回归不连接隔离 MySQL，真实 MySQL 7 项测试需显式开启，数据库名称必须符合验证库前缀；测试读取本地忽略的 `.env` 凭证，不在命令行写入密码。

2026-10-13 会话统一更新：两个入口共用数据库会话、历史与账号范围记忆，AG-UI 完成事件在回复保存后发送。客户端 runId 去重仍保留，已提交请求在检索前返回 409；并发竞争仍由数据库唯一键处理。详情见 [会话历史与记忆统一](Agent会话历史与记忆统一.md)。

2026-10-16 上下文压缩更新：新增 CONTEXT_STARTED / COMPLETED / FAILED / CANCELLED 元数据事件和前后消息数/字符数；摘要模型有独立请求编号与 CONTEXT_COMPACTION 用途，候选模型、备用及实际用量沿用模型路由采集。日志不保存摘要或历史正文，仍按本人运行授权。角色工厂同时明确关闭 SDK 独立转录，原 MySQL 会话持久化不变。默认不开启压缩，详见 [上下文压缩](Agent长对话上下文压缩.md)。
