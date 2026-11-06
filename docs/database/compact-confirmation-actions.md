# 人工确认动作迁移

本切片将两套人工确认流程分别存入 `workflow_instance`，将 Agent 原审计及旧聊天动作的新状态变更存入 `audit_event`。不新增业务表，也不合并两套权限或状态机。代码与迁移候选已编写，包含 Unicode 和服务器测试适配的 [clean test-compile 08](../../work/schema-reduction-20261105/compact29-test-compile-08.log) 于 2026-11-06 02:29:35 通过；ECS MySQL 用例尚未执行，生成 SQL 和编译均不代表迁移已执行。

## 来源和落点

| 来源 | 原字段数 | 目标与保留方式 |
| --- | ---: | --- |
| V19 `agent_pending_action` | 19 | `AGENT_ACTION` 工作流；原动作 ID、用户、run、session、摘要、状态、版本、有效期、确认时间为明确列；call、操作、资源版本、三个 JSON 原文及策略属于版本化 proposal/result |
| V19 `agent_action_audit` | 12 | `AGENT_ACTION` 审计；原动作、用户、run、事件、摘要、策略、结果及发生时间为明确列；角色、业务资源、原因、原 ID 和原时间为 `AuditV1` |
| 原 `schema.sql` 的 `chat_pending_action` | 9 | `LEGACY_CHAT_ACTION` 工作流；原动作 ID、状态及确认时间为明确列；原动作类型、任意 LONGTEXT、错误、原 ID、原会话拼写和原时间为 `PendingV1` |

Agent 工作流 ID 为 `agent-action:<action_id>`。导入旧聊天动作的工作流 ID 为 `legacy-chat-action:<原数字 id>`，运行时新聊天动作使用新 UUID。两来源即使动作 ID 相同也不会争用全局工作流 ID。旧数字 ID 放在来源证据中；API 的记录游标属于目标全局序列，不能把原数字 ID 当作新游标。

Agent 原 `(user_id, run_id, arguments_digest)` 唯一性由明确生成列与唯一键保留。摘要原文保持不变：原摘要来自 Java 命令序列化，不用 MySQL JSON 的排版重新计算。导入使用原 JSON 列的完整文本，SQL NULL 与 JSON `null` 区别保留。新 result wrapper 的哈希只核对该 wrapper 自身存储字节。

旧聊天动作没有 JSON 有效性约束，故不解析或修复 `action_payload_json`，也不移除原错误文字或尾空格。原 `action_id` 的 `utf8mb4_unicode_ci` 全局唯一性由 `chat_action_id` 生成列保留。

## 状态、权限和事务

Agent 保留提议、审批、驳回、取消、过期、失效、执行中及人工复核状态。审批仍按 run、动作、业务资源锁顺序执行；业务写入、版本 CAS、结果及审计在同一事务。创建检测只在审批事务内预留，外部执行结果通过原回执收敛；`EXECUTING` 或 `NEEDS_REVIEW` 不会自动再次执行。Workbench 卡片只读取对应 `AGENT_ACTION` 工作流，不能代替人工批准。

旧聊天动作保留独立协议。现有公共确认接口批准请求仍返回 410，取消功能继续可用。鉴权先锁住并读取真实 `chat_session` 的当前归属，不依赖导入时记录的历史 owner。取消状态、审计和接口的确认消息必须同事务提交。

`chat_action_session_id` 是普通外键列，由 `39-workflow-guards.sql` 限定只能属于精确的 `LEGACY_CHAT_ACTION`，`40-relations.sql` 保留原 session 改键、删除双 CASCADE。旧 child 的 unicode_ci 拼写可能与 parent 字节不同：迁移引用精确的 parent 主键，原 child 文本保留在 `legacySessionId`。导入前必须已迁入同一个 parent 键和 owner，否则整体中止。独立审计没有 session/user/run 删除级联，历史审计也不要求当前动作或 run 存在。

## 时间与未知事实

必须提供有证据的固定来源偏移 `__SOURCE_ACTION_OFFSET__`，例如 `+08:00`；不能依赖测试连接或服务器时区猜测旧数据语义。复制既检查 `CONVERT_TZ` 非空，也检查实际微秒差等于该偏移，拒绝 MySQL 对超范围日期不转换却原值返回的情况。

Agent 原 created/expires/decided 与 audit occurred 转为 UTC，原格式和偏移保存在明确证据字段中。V19 没有 updated/completed 列：导入工作流 `updated_at`、`finished_at` 保持 NULL，不能把决定时间伪称完成时间。旧聊天 created 可为 NULL，updated/completed 未知也保持 NULL，confirmed 只承接原确认时间。新运行记录使用真实 UTC 时钟，API 延续北京时间展示。

## 复制候选和准入

生成器是 `script/schema/author_confirmation_copy.py`，输出 `sql/mysql/compact/copy/44-confirmation-actions.sql` 及 AI 模块 `compact/action-source-evidence.sql`。源夹具直接抽取真实 V19 两表及旧 schema 的聊天表，并使用真实 users/chat_session 父表定义；没有把目标表改名伪装成来源。

执行前须准备同一已准入 ECS MySQL 上两个不同空的隔离 schema，既有目标账号具有源 schema 的 SELECT 和 TRIGGER 元数据读取权限。夹具不创建数据库或授予权限，不提供本地回退。替换参数包括源 schema、实际观测到的两张 V19 表 collation 和来源时间偏移。原 Agent 摘要唯一键的目标 collation 为 `utf8mb4_0900_ai_ci`，来源若不同则拒绝，先补充设计而非猜测等价。

复制核对三来源全部 40 列的顺序、类型、NULL、默认值、collation、生成表达式、唯一键及真实聊天双 CASCADE；不接受额外来源 CHECK、FK 或触发器。只有时间默认表达式允许无语义差别的大小写/空括号规范化，`PENDING` 等文本默认仍按字节核对。非法用户、摘要、状态或时间不删行绕过，整批中止。字符长度遵循 MySQL utf8mb4 字符数，合法的非 BMP 字符不因 Java UTF-16 长度翻倍而拒绝读取。

三类 INSERT 位于同一事务，所有尾校验在全部 INSERT 之后执行：逐源 LEFT JOIN 查漏，BINARY NULL-safe 核对所有普通目标列，包括明确应为 NULL 的其他域字段。末尾审计触发器若篡改先写入的 workflow 也必须中止。执行器必须首错停止并在同一连接 ROLLBACK；禁止 `--force`。复制不写来源，也不重置其自增序列。

## 待 ECS 执行的验证

| 测试 | 准入属性 | 验证范围 |
| --- | --- | --- |
| `AgentActionServiceTest` | `doorhandle.action.mysql.config` | 实际 29 表；审批幂等、并发、业务与审计回滚、跨账户隔离、版本/策略失效、创建检测未知结果不重放 |
| `ConfirmationMigrationMySqlTest` | 上述目标属性及 `doorhandle.action.source.config` | 双 schema；40 字段、孤儿审计、原 JSON/任意原文、未知时间、大数字 ID、collation、改键/删除、元数据漂移与触发器破坏整批回滚、源及自增序列不变 |
| `LegacyChatActionStoreMySqlTest` | `legacy.chat.mysql.config` | 当前会话 owner、原文/NULL、CAS、审计失败回滚、全局旧 ID 唯一、外键与两 guard、410/取消接口边界 |
| `AgentContractEvalTest` | `doorhandle.action.mysql.config` | 脚本模型/合成业务门面的动作规则评测；使用真实 ECS MySQL，不访问供应商；fixture 标识已更新，旧 H2 基线不能冒充新结果 |
| `AgentWorkbenchServiceTest` | `workbench.mysql.config` | ECS-only；29 表加仍被 `WorkbenchStore` 使用的 V37 item/request/audit 三表过渡夹具 |

WorkbenchStore 的三张旧表属于尚未完成的另一切片。这个过渡测试不证明整个 Workbench 域已落入 29 表，也不能据此宣布全库可切换。上述用例尚未运行；本地只编辑与构建。测试完成后的 ECS 停机由统一流程执行，本切片未操作云资源。
