# 消息证据独立保留

状态：`AUTHORED_NOT_EXECUTED`。主代码、双 schema 复制和 ECS 用例已编写，尚未运行数据库测试。保持 29 表；没有添加聊天证据专表。

## 已落实的存储边界

原证据的账号、会话、消息及 run 身份进入 `audit_event`，没有到 `users`、`chat_session` 或 `agent_run` 的删除外键。`chat_message` 是当前投影，新增三个普通 evidence 指针，通过 `(证据原 owner, evidence id)` 外键指向审计记录，避免绑定别人的证据。读取也校验 kind、原 owner、原 message、载荷版本和原摘要。

`MessageExecutionLinks`、`WorkspaceTurnSnapshotService`、`DurableContextStore` 的消息证据写入使用 `JdbcMessageEvidenceStore`：锁定当前消息及归属，写独立证据，再更新当前投影，两步同事务。证据失败则投影回滚；投影失败则证据回滚。删除时不用补归档，直接 SQL 删除消息、会话或用户、以及外键级联删除均不触碰证据。

证据存储复制应用的 ObjectMapper，并固定 `Include.ALWAYS`，显式保存新记录的 `legacyId:null`。应用响应使用的 `NON_NULL` 策略不被修改；独立证据仍按完整 typed 字段严格回读，避免新快照创建后因省略字段而不可读取。

保留原 `chat_message.session_id` 的 ON UPDATE/DELETE CASCADE；撤去原来的 run、snapshot owner、context owner 三个复合父外键。会话主键改变时，当前消息随之更新，指针仍找到原证据；审计中的原会话键不被改写。执行关联的原 message/run 全局唯一约束落在审计生成列索引上，删除消息不会释放 run 供其他回复绑定。

## 18 个来源字段

| 来源 | 全部原字段 | 新实体 |
| --- | --- | --- |
| V66 `agent_message_execution`（6 列） | `id,user_id,session_id,message_id,run_id,created_at` | `MESSAGE_EXECUTION`；原 owner/session/message/run 为有类型审计字段，原自增 id、原 DATETIME 文本及有证据的 offset 进入 `ExecutionV1`。保留 message 和 run 分别全局唯一。 |
| V45 `agent_workspace_turn_snapshot`（7 列） | `id,user_id,session_id,message_id,snapshot_json,snapshot_sha256,created_at` | `MESSAGE_WORKSPACE_SNAPSHOT`；原 JSON 文本保留在 `WorkspaceSnapshotV1`，原 SHA 不改写，保留 `(owner,session,message)` 原唯一。 |
| V44 `agent_context_turn`（5 列） | `user_id,session_id,message_id,sources_json,sources_sha256` | `MESSAGE_CONTEXT_SOURCES`；原 JSON 文本保留在 `ContextSourcesV1`，原 SHA 不改写，保留 `(owner,session,message)` 原主键语义。 |

V44 原表没有时间：导入记录的 `occurred_at=NULL`。只有该 kind 与精确旧表来源键组合允许这个例外，其他记录仍要求时间；新 context 证据使用实际 UTC 创建时刻。V45/V66 的原 DATETIME 六位微秒文本和显式 offset 同时保留，外层时间据此转换 UTC，不能用消息时间猜测。

复制前同时校验转换结果非 NULL，以及原 DATETIME 与 UTC 结果的实际秒差等于声明的 offset。MySQL 在超出支持范围时可能原值返回；例如 `9999-01-01` 配 `+08:00` 必须中止，不得把未转换的本地时间标记为 UTC。合法的零偏移仍保留原时间，不为 V44 补造时间。

旧自增 id 是旧表内部身份，不是新审计全域游标。两者通过 `legacy_source/legacy_key` 关联，新 `audit_event.id` 独立分配。源 AUTO_INCREMENT 高水位（含删掉高 id 后的空洞）应保留在迁移回执/备份；复制不修改源序列，也不抬高共享审计序列冒充同一编号空间。夹具快照同时比对原行和原序列元数据未改变。

context 的原复合键同时保留为有类型字段和可读长度前缀来源键，如 `999:7:missing:9000`；其 event UUID 可采用摘要压缩，原身份及唯一性不是只靠哈希。

## 复制入口与范围

入口为 `sql/mysql/compact/copy/24-chat-evidence.sql`，由 `script/schema/author_chat_evidence_copy.py` 从真实 V44/V45/V66 DDL 生成。原同库 `003-chat-aggregate-copy.sql` 已撤回并立即报错，禁止与新入口混用。原基础聊天项目、会话和消息的复制范围不在本证据脚本中；若需要生成当前投影，应先完成基础聊天行复制。

源与目标必须为不同 schema，源停止写入，目标三种证据及消息证据投影均为空。验证 18 列类型、NULL、排序、默认值、生成属性、原唯一键及前缀；拒绝未知列、新 CHECK、外键和触发器。V45 未显式声明的文本列排序规则当前候选按 MySQL utf8mb4 默认 `0900_ai_ci` 校验，实际不匹配时必须核对，不静默转写。V44/V66 及三表 session 字段保留原 bin 规则。

源 JSON 与 SHA 必须一致；原大小写 HEX 摘要均可核对，保存时不替换字串。非法或非正 owner/message 停止迁移待核对；不存在当前 owner/session/message/run 的合法历史不会被过滤，也不会伪造父记录。仅字节相等的原 session、同 message、同 owner 和符合原消息角色的行才能建立当前投影；其他全部作为独立证据保留。

数据插入、投影和最终 NULL-safe 字节对账在同一连接事务中。最终逐行 LEFT JOIN 对账包含所有原字段及载荷、原时间/offset/摘要、来源键；当前投影先固定符合条件的消息集合，避免变更或删除后被 INNER JOIN 漏掉。首错同连接 ROLLBACK，禁止 `--force`。目标 DDL/关系先独立建立；临时表随连接清理；脚本不写源表。

## ECS 验证入口与未完成项

`CompactChatMigrationMySqlTest` 使用 `ChatEvidenceMigrationFixture`：目标配置 `doorhandle.feature.mysql.config`，源配置 `doorhandle.chat-evidence.source.config`。两份配置须预先存在且通过 `EcsIsolatedMysql` 身份、Linux 主机、专属实例/端口/目录、限定账号和空 schema 门禁。夹具不建数据库、不授权；目标对源的 SELECT/TRIGGER 元数据权限须已准备。目标使用真实 29 表 baseline、公共生成列、保护触发器和全部外键。

`MessageExecutionLinksTest` 已切到同一 ECS baseline，不再用 H2 模拟这些约束。新增场景包括原消息/run 全局唯一保留、直接删除消息/会话/用户、session 改键后的指针回读、证据或投影失败整体回滚、跨账号指针拒绝，以及 `WorkspaceTurnSnapshotService.copy` 生成独立证据。迁移场景包括孤儿、多原 owner 对同 message 的合法历史、18 列/原 SHA/未知时间/源序列保留、重复导入拒绝和源/目标破坏回滚。

另已编写 `NON_NULL` 应用 mapper 注入后的三类证据严格写读与幂等重放、快照服务新副本再次回读，以及 V45/V66 各自含 9999 年时间时的拒绝用例。日期门禁失败时迁移执行器在同连接回滚，目标不得新增证据或改动原消息，源行及序列必须保持不变。这些用例尚未执行。

当前未运行 SQL 或 ECS。实际源元数据、MySQL DDL、事务/并发与级联行为仍待 ECS 验证。后续工作区候选已将旧文件/业务引用、永久 fork 回执及快照剩余查询切至共享实体，详见 [工作区迁移](compact-workspace-migration.md)；它同样尚未通过 ECS 验收。其他上下文旧表仍有独立适配工作，本修复不宣称全部服务已可在 29 表环境整体启动。
