# 工作区持久化与 V38 迁移

状态：`AUTHORED_NOT_EXECUTED`。主链适配、真实 baseline ECS 用例及双 schema 复制候选已编写，未执行数据库测试或正式迁移。保持 29 张表。

## 运行边界

`AgentWorkspaceService` 的上传、文件列表/读取、解除引用、业务附件、幂等操作、审计及 fork 统一使用 app 域 `WorkspacePersistence`。`WorkspaceTurnSnapshotService` 的 capture/inherit 已切至相同内容引用协议；独立消息快照继续使用 `JdbcMessageEvidenceStore`。两服务已撤去 `agent_workspace_*`、`agent_session_fork` 与撤回的 `operation_job` 访问。

文件元数据使用 `content_asset` 和不可变版本 `content_revision`。原 file_id、文件名、MIME、字节数、原 SHA 与请求号为明确字段；`FileManifestV1` 只承载 folder、原时间文本和来源 offset。私有文件仍按既有 `users/{owner}/{file_id}.bin` 路径读取，未把本地文件或其内容搬入 JSON。原摘要大小写保留，读取字节时按 HEX 摘要核对。

旧文件引用没有文件、账号或会话外键。`WORKSPACE_FILE` 链接使用 `target_type=WORKSPACE_FILE`、`target_id=原file_id`，完整保留合法历史孤儿；不伪造文件资产或账号。新建引用必须在同一事务内核对当前会话及现有文件属于该账号。文件读取仍要求当前账号/会话权限、引用归属、长度及摘要；上下文文件保留额外权限检查。资产与不可变版本的现有外键保护仍保留，解除会话引用不删除私有文件。

文件引用唯一范围为 `(owner,session,file_id)`，bin 排序与 V38 一致；业务引用保留 `(owner,session,kind,resource)`，其中 kind 派生列使用旧 `utf8mb4_0900_ai_ci`，资源身份仍为 bin。原 kind 字串不因唯一索引排序规则而改写。读取业务附件时继续向业务模块核对现时权限。

`WORKSPACE_MUTATION` 与 `WORKSPACE_FORK` 是永久完成回执，无租约或 TTL。原 owner/request bin 唯一性及 fork child 全局唯一性独立于当前会话。子会话删除后，同请求仍返回原结果；不能创建第二个 fork 来替代历史结果。新回执与内容修改、审计在同一个事务内提交。

私有文件创建后，仅在事务回调明确为 `STATUS_ROLLED_BACK` 时清理。若 COMMIT 回执丢失、事务结果为 UNKNOWN，保留唯一文件副本，后续按数据库回执核对；不能因为客户端收到异常就删除可能已经提交的文件。没有实现自动删除未知结果孤儿文件的任务。

## V38 全部 39 列

| 原表 | 原列数与字段 | 目标 |
| --- | --- | --- |
| `agent_workspace_owner` | 1：user_id | `runtime_state` 的 WORKSPACE 互斥身份；原表没有时间，created_at 为 NULL。 |
| `agent_workspace_file` | 10：id、file_id、user_id、request_id、filename、content_type、byte_length、sha256、folder、created_at | `content_asset` + `content_revision`，原 id 为 legacy provenance，原 folder/时间/offset 为 typed manifest。 |
| `agent_workspace_file_ref` | 5：id、user_id、session_id、file_id、created_at | `content_link` WORKSPACE_FILE；包括缺文件、缺当前会话、缺当前用户及原归属不匹配的历史。 |
| `agent_workspace_request` | 4：id、user_id、request_id、signature | `workflow_instance` WORKSPACE_MUTATION；原 signature 同时保留为请求 SHA 和 typed 载荷，不重新计算。 |
| `agent_session_fork` | 6：id、user_id、request_id、source_session_id、through_message_id、fork_session_id | `workflow_instance` WORKSPACE_FORK；仅存在且原 owner/child 字节一致时附加当前 `chat_session` 投影。 |
| `agent_workspace_audit` | 7：id、user_id、session_id、resource_id、action、content_sha256、created_at | `audit_event` WORKSPACE；原行为和摘要字串保留，无当前用户/会话删除外键。 |
| `agent_workspace_business_ref` | 6：id、user_id、session_id、kind、resource_id、created_at | `content_link` WORKSPACE_BUSINESS；原 kind 和资源字串不改写。 |

V38 的四个 created_at 均为 `DATETIME(6) NOT NULL`。复制要求明确的固定来源 offset，并核对 `CONVERT_TZ` 实际秒差。文件与审计保存原六位微秒文本；引用另保存 `legacy_created_at`/`legacy_utc_offset`，只允许精确两个 V38 引用来源成对使用。目标 created_at 使用 UTC，超范围转换原值返回必须拒绝。

原 request/fork 表没有任何时间字段，三项流程时间 `created_at/updated_at/finished_at` 全部保留 NULL。只有精确旧来源与来源键允许该例外；新流程仍写真实 UTC 时刻。fork 原表也没有请求 SHA；新协议使用完整 sourceSessionId/throughMessageId 派生查询摘要，同时保留全部原分量和 resultSessionId，不把派生摘要宣称为源存量字段。

共享目标 id 是新的游标空间，原表自增 id 保留在 legacy_source/id 或 legacy_source/key。脚本不抬高共享序列、不改源序列；源高水位（含已删除高 id）需要存入迁移回执/备份。双 schema 用例会逐表保存原行及 AUTO_INCREMENT 元数据并核对源未改变。

## 复制和验证入口

入口为 `sql/mysql/compact/copy/43-workspace.sql`，由 `script/schema/author_workspace_copy.py` 根据真实 V38 DDL 生成。必须先建立目标 baseline/关系，停止源写入，使用不同源/目标 schema，并渲染有证据的来源 offset。脚本验证 39 列类型、位置、NULL、排序、默认值、生成属性和原唯一键，拒绝未知列、源触发器、新 CHECK/FK、类型或排序变化。目标工作区域必须为空；其他领域数据不会被清除。

元数据复制、当前 fork 投影及逐行 NULL-safe 字节对账在同一事务。源与目标均须停止业务写入。首次业务 DML 前，从实际 `chat_session` DDL 生成临时快照，保存全部会话的所有非 fork 字段，并按原主键 id 固定符合条件的 child 集合。fork 更新显式执行 `updated_at=updated_at`，抑制 `ON UPDATE CURRENT_TIMESTAMP` 对旧更新时间的改写，原 NULL 时间也保留。

尾部对账检查所有原字段、原 JSON 文本、未赋值目标列、来源身份、时刻、载荷及当前投影；会话数量、主键身份及全部非 fork 字段须与迁移前一致，字符串包括大小写、空白与原 JSON 文本均按字节核对。目标会话存在 baseline 未登记列或缺列时预先拒绝，避免漏掉额外的自动更新时间字段。只有固定 child 集合可新增五个 fork 字段，其他会话保持原空投影；改名、改主键或触发器篡改不能被 INNER JOIN 隐藏。遇到首个错误必须在同连接 ROLLBACK 并关闭，不允许 `--force`。原库不执行 DML/DDL。

数据库脚本只迁移私有文件元数据，私有卷复制、实际文件存在性、长度与摘要需要单独核验；本候选未声称已完成这些事项。

`WorkspaceMigrationMySqlTest` 使用 `WorkspaceMigrationFixture`，源配置为 `doorhandle.workspace.source.config`，目标为 `doorhandle.feature.mysql.config`。夹具复用 `DualSchemaCopyMySqlFixture` 与完整 `CompactMySqlFixture`，包含当前公共生成列、保护触发器和全部外键。只允许预先准备且通过 ECS 隔离门禁的两份空 schema，不创建数据库或授权。

迁移用例覆盖 39 列、孤儿/不同原 owner、旧 signature 大小写、三项未知时间、源序列、永久回执重放、未知源形状、四种来源的 9999 年错误转换、缺载荷字段、未赋值字段污染、来源尾空格、审计或 fork 投影破坏后的整体回滚。`AgentWorkspaceServiceTest` 已移除 H2 与 003/004 拼装，使用真实 29 表 baseline；覆盖文件权限/配额、并发幂等、确认回滚清理、已提交却丢失回执时保留文件、当前/已撤除引用及业务来源权限变化。

fork 投影专项用例还覆盖旧于当前时刻的创建/更新时间、合法 NULL 时间、完整非 fork 字段保留，以及目标触发器修改标题尾空格、账号大小写、JSON 空白、checkpoint、日期、会话键或行主键时全事务回滚。用例明确要求失败落在迁移前会话快照对账处，避免被无关约束报错伪装成保护已生效；尚未在 ECS 执行。

精确 fork 边界优先使用消息快照，且仅继承目前仍在原会话中的引用。无快照的历史分支保留“严格早于秒级切点”的保守回退与明确的 legacy 标记。代码中的消息时间来自现有 `ChatSessionServiceImpl` 的 JVM `LocalDateTime.now()`；转换至 UTC 时使用同一 JVM zone 并拒绝时区歧义。上线核验仍须确认历史消息生产时区与当前配置一致；不能用文件时间反推消息时间。

`CompactChatFixture` 的旧入口已明确撤回，不再加载 003/004。本轮没有运行 Maven、SQL 或 ECS；实际源形状、权限、MySQL DDL、并发/故障与私有卷仍待 ECS 验收。
