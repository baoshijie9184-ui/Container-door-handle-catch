# 持久上下文六表迁移设计

状态：`SOURCE_IMPLEMENTED_ECS_NOT_RUN`。六表的生产调用已改接明确的runtime/content/audit协议，原始V44复制候选和ECS限定测试源码已编写，公共DDL由主集成阶段统一维护。当前项目保持29张目标表，不增加上下文替身表或旧表fallback。本轮仅编辑、SQL源码生成及静态检查；未执行数据库、应用、任何测试或ECS操作。旧compile08不覆盖本次新增实现，统一Maven结果以主集成最新记录为准。

## 来源与范围

依据为 [V44 原始 DDL](../../sql/mysql/migration-V44-agent-durable-context.sql)、[DurableContextStore](../../doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/context/DurableContextStore.java) 及 [现行目标契约](compact-schema-contract.json)。六张表共 60 列，全部来自 V44。V45 的 `agent_workspace_turn_snapshot` 属于已编写的独立消息证据切片，不是这六张表的增补字段。

V44 还有五列的 `agent_context_turn`，已由独立 `MESSAGE_CONTEXT_SOURCES` 证据协议承接，本切片不重复复制或恢复旧表。相关边界见 [消息证据独立保留](compact-chat-evidence-migration.md) 和 [工作区迁移](compact-workspace-migration.md)。

| 原表 | 全部原字段 | 目标 |
| --- | --- | --- |
| `agent_context_head`（5） | user_id、session_id、agent_scope、revision、summary_id | `runtime_state` / `CONTEXT_HEAD` |
| `agent_context_bootstrap`（8） | user_id、session_id、logical_task_id、agent_scope、history_through、initial_state、initial_sha256、initialized | `runtime_state` / `CONTEXT_BOOTSTRAP` |
| `agent_context_summary`（19） | id、summary_id、user_id、session_id、agent_scope、revision、status、covered_through、history_sha256、summary_json、summary_sha256、message_state、sources_json、policy_version、run_id、before_chars、after_chars、original_state、created_at | `content_revision` 为主；配套独立 `content_asset` 保存该摘要身份与可变状态 |
| `agent_context_origin`（8） | user_id、session_id、agent_scope、call_key、logical_task_id、run_id、sources_json、sources_sha256 | `content_link` / `TOOL_SOURCE` |
| `agent_context_offload`（12） | id、offload_id、user_id、session_id、agent_scope、call_id、file_id、content_sha256、byte_length、sources_json、sources_sha256、created_at | `content_link` / `CONTEXT_SOURCE` |
| `agent_context_audit`（8） | id、user_id、session_id、agent_scope、resource_id、action、content_sha256、created_at | `audit_event` / `CONTEXT` |

上述目标与现行契约主路由一致。摘要的配套asset与revision形成明确内容身份和生命周期；所有新写入直接访问目标结构。公共契约、形状约束及保护触发器由主集成维护，不增加业务表、兼容视图或旧表替身。

## 目标协议与原唯一范围

### 当前 head 与任务 bootstrap

`CONTEXT_HEAD` 使用 `owner_id=user_id`、`session_id=原session_id`、`state_key=原agent_scope`、`revision=原revision`、`current_ref=原summary_id`。head 只保存当前指针及竞争版本，不承担摘要正文和历史证据存储；没有当前摘要的历史 head 仍保留，不伪造摘要补齐引用。

`CONTEXT_BOOTSTRAP` 使用 `owner_id=user_id`、`session_id=原session_id`、`state_key=原logical_task_id`、`counter_value=原history_through`。原 initialized 的 0/1 对应限定的 RESERVED/INITIALIZED 状态；其他原值先停止迁移核对，不能按真假强制转换。`ContextBootstrapV1` 固定保存 agentScope、initialState 原文、initialSha256 和 legacySource。初始 SDK 状态及摘要一旦绑定不得被重试覆盖，初始化状态可在 checkpoint 成功提交时推进。

两个 namespace 的 `scope_key` 可使用明确、无歧义的长度前缀编码后 SHA-256，以适应现有主键长度；完整身份必须同时保留在有类型列中。真实唯一范围分别保持 `(owner,session,scope)` 与 `(owner,session,logicalTask)`，查询和更新核对这些原分量，哈希碰撞必须冲突中止，不能命中另一份上下文。

所需窄改为：`runtime_state.state_key` 从 128 扩至 160；仅两个新 namespace 加入 session/state_key 使用协议，保持 SDK 原字段长度限制；复合唯一键继续使用完整分量。head 的 `ContextHeadV1` 只记录准确 legacySource，bootstrap 的 legacySource 同样受固定记录类型约束，用于区分原无时间历史与新写入事实。不能仅为允许 NULL 而普遍放宽所有 runtime 类型。

### 每个摘要独立资产、固定内容版本

每个原 summary_id 建立独立的 `CONTEXT_SUMMARY` asset，例如内部 asset_id 使用固定命名空间前缀加原 summary_id，`identity_key` 保存原 summary_id。全局 summary_id 唯一性继续保留，不能因为改为共享内容实体而允许不同账号重复使用原身份。

该 asset 固定只有 `content_revision.version=1`，`current_version=1`，不使用 published_version。原 `agent_context_summary.revision` 是 BIGINT，并非这个内容版本号；将它保留为摘要 manifest 的整数事实及独立 BIGINT 派生列，不扩大其他内容领域的 INT version。asset 的并发修改版本同样与原摘要修订号区分。

asset.lifecycle 承担原 ACTIVE/INVALIDATED 可变状态；失效只修改状态及 head 竞争版本，不覆写已保存正文或来源。源出现当前运行协议未识别的状态时中止迁移核对，不静默改为 ACTIVE。原 id 保存为 revision 的 legacy provenance，源创建时间用于 asset/revision 的创建事实；源没有最后状态修改时间，不能由 created_at 推出它。

revision 的 `content_text` 保存原 summary_json 字串，`content_sha256` 保存原 summary_sha256，`sources_json` 保存原来源文本，`source_run_id` 保存原 run_id。此 kind 的原 SHA 是整个摘要组合的摘要，不是单独 summary_json 的 SHA；读取必须沿用原组合算法，不能套用其他内容 kind 的正文摘要算法。源没有 creator 字段，迁移不补造 creator_user_id。

`ContextSummaryV1` 是严格登记的固定字段记录：schemaVersion、sessionId、agentScope、contextRevision、coveredThrough、historySha256、messageState、policyVersion、beforeChars、afterChars、originalState、createdAtSource、sourceUtcOffset。原 JSON/SDK 状态分别作为完整原字串保留，不因外层记录编码而重新整理其内部空白、键序或转义。manifest 可能包含多个 MEDIUMTEXT 来源，须采用足够容量的 LONGTEXT；迁移前还须核验实际载荷、连接包大小与导入容量，不能截断以适配现有列。

为该 kind 添加有类型的 session、scope、BIGINT contextRevision、coveredThrough 派生列及形状约束。重建原 `(owner,session,scope,revision)` 唯一范围，以及 `(owner,session,scope,coveredThrough)` 分支查询索引。其它 kind 的对应派生值为 NULL。只保留外层固定字段，不提供任意 Map、自由 SQL 字段或未登记 payload 的持久化入口。

### 来源快照与卸载回执

`TOOL_SOURCE` 保存 origin 的 owner/session/scope/call/task/run 普通列，`call_id` 保留原 call_key，`target_type=CONTEXT_TASK`、target_id 保留原 logical_task_id。这个目标是原逻辑任务身份，不要求伪造一个当前 workflow 父行。`OriginEvidenceV1` 只承载 sourcesJson 原文与原 sourcesSha256。

`CONTEXT_SOURCE` 保存 offload 的 owner/session/scope/call 普通列，`subject_type=CONTEXT_OFFLOAD`、subject_id 保留原 offload_id，`target_type=WORKSPACE_FILE`、target_id 保留原 file_id。`OffloadEvidenceV1` 固定保存 contentSha256、byteLength、sourcesJson、sourcesSha256 和已知原时间/offset；新 fork 回执还需明确来源 lineage，具体字段与实现同步评审。旧表没有 lineage 字段，导入不得猜测它来自哪个工具或父回执。

为这两种 link 添加受 kind 限定的 evidence_version/evidence_json，使用各自登记的固定记录与严格读取。原 sources_json 是授权快照，不是指向会变化的当前来源集合的替代引用。JSON 文本及原 SHA 按原值保存，使用专用 mapper 的显式 NULL 序列化，避免应用层 NON_NULL 设置使严格回读缺字段。

所需列宽调整为 `content_link.agent_scope` 从 128 扩至原 160。保留相互独立的 origin `(owner,session,scope,call_key)` 与 offload `(owner,session,scope,call_id)` 唯一范围，另外保留 offload_id 全局唯一，提供原 `(owner,session,file_id)` 查询索引。生成列仅在对应 kind 生效；原 bin 排序规则、字段长度与 PAD SPACE 比较语义不能在复合键压缩时丢失。

这两种 link 不以 asset_id 外键强制消除历史孤儿。新卸载必须先取得同账号、会话、scope、call 的唯一来源回执，核对来源摘要，再创建或重放文件和回执。首次 origin 的任务、来源和 run 事实保持不变；不同事实复用原调用键应报冲突。

旧 fork 路径会复制 offload，却不创建同调用键的 origin，因此“每条历史 offload 都必须 JOIN 到 origin”并不成立。迁移保留这些历史；新 fork 使用明确继承路径，不能伪造 origin 冒充原工具结果。

### 上下文审计

`audit_event` 的 CONTEXT kind 保存原 owner、session、resource、action、SHA，`ContextAuditV1` 固定保存 agentScope 及原时间/offset。原 action 长度为 64，原 resource_id 长度为 36。源只记录 user_id，不另补造历史 actor；新操作可记录实际 actor。

旧 id 保存为 `legacy_source=agent_context_audit` 与 legacy_key。共享 audit.id 是新游标，不继承旧自增号；旧高水位及已删除 id 空洞留在迁移回执和备份中。所有原审计行均保留，不靠去重相同 action/SHA 合并历史。

## 时间、原值与保留边界

head、bootstrap、origin 原本没有任何时间字段。它们的导入创建/更新时间保持 NULL，只允许精确 kind/namespace、精确 legacySource 及完整身份组合的例外。新记录写真实 UTC 时刻；后续更新不能补猜历史创建时间。content_link.created_at 和 runtime 时间约束需要按该窄例外调整。

summary、offload、audit 只有 `created_at DATETIME(6) NOT NULL`。必须在有来源证据的固定 offset 下转 UTC，同时保存原六位微秒文本及 offset，并验证实际 TIMESTAMPDIFF 微秒差；超范围原值返回不是成功转换。summary 历史状态修改时间未知，asset.updated_at 需保留准确旧摘要来源的 NULL 例外，不能把创建时间、迁移时间、聊天时间或审计中的附近时间当成它。

bootstrap 原 SHA 按原 `[owner,session,scope,task,through,initialState]` 序列化算法核对；summary 原 SHA 按原 `[summaryJson,messageState,sourcesJson,scope,coveredThrough,historySha256,originalState]` 算法核对。原字串与存量摘要必须保留，不能用重序列化后的新 SHA 替换旧 SHA 后宣称一致。SQL JSON_ARRAY 的输出空格不应被假定与 Java 原序列化一致；实现须使用经逐字节验证的原算法。

六表原 DDL 均没有用户、会话、run、消息、文件或摘要父外键。缺失当前父记录的历史须完整导入；不伪造实体，不添加删除级联，也不因缺失当前权限而删除原证据。历史留存不等于访问许可：运行时仍必须核对当前账号、会话和各来源资源的权限。当前 head 指向错误账号或 scope 的摘要时不得加载，原行保留供核对。

原 id 是原表身份，目标共享 id 是独立游标；不抬高共享序列冒充原序列。源行及 AUTO_INCREMENT 元数据须在复制前后快照一致，迁移不写源。

## 权限、切点与事务

摘要、来源与文件按账号和会话隔离。恢复、读取、摘要复用、工具结果重放与 fork 前都重验 ROLE、FILE、业务文件、任务/报告/设备/模型、RESEARCH 及 CHILD 的当前授权和版本；不能把曾经成功执行视为永久授权。

bootstrap 的 initialized 推进、seed 来源及 SDK checkpoint 在同一个实际数据库事务提交。保存摘要时锁定对应 head，校验 expected revision，再插入不可变摘要、推进 head 并写审计；并发失败整笔回滚。失效不得覆盖原摘要正文或释放原 revision 供另一份内容使用。

卸载保留原 16 KiB 触发阈值、2 MiB 上限和受控分段读取边界。文件元数据、首次 offload 回执、来源证据及审计同事务；重放核对原调用身份和内容 SHA。文件字节沿用工作区提交结果处理：明确回滚才清理，COMMIT 结果 UNKNOWN 时保留唯一副本，不能因为异常删除可能已提交文件。

主会话历史摘要继续验证消息切点及 history digest。fork 使用工作区永久回执、准确消息映射和已保存附件边界；只有源摘要 coveredThrough 在原切点内、原历史摘要相符且目标消息映射存在，才能生成目标摘要。不能从文件时间反推消息边界，不能跟随 CHILD 将来的对话扩充已经保存的来源快照。

## ChildProvenanceReader 对齐契约

DurableContextStore的snapshotChildren与authorize已移除旧CHILD表直查，通过ObjectProvider装配工作台提供的唯一ChildProvenanceReader。没有读取器时明确失败，不回退旧表。与工作台切片对齐的接口为：

```java
Optional<ChildProvenance> find(long ownerUserId, String sessionId, String itemId);

record ChildProvenance(String id, long ownerUserId, String sessionId,
                       String status, long revision) {}
```

提供者只读取新 `WORKBENCH_CHILD` 窄协议，使用完整 owner/session/itemId 条件；禁止裸 id 跨账号读取、旧表 fallback 或任意 payload 转交。CHILD 的 owner/session/itemId 身份在运行中不变；COMPLETED 可以因 child-message 追加再次转 QUEUED，不能将其建模为永久终态或授权凭证。

reader 返回一次当前记录，不读取 payload，不获取 WORKBENCH owner 锁。本切片暂不要求 FOR SHARE；不能在持有 context 行锁后另拿 WORKBENCH owner 锁造成相反锁序。若后续确需跨域状态强一致，两个切片须先共同约定锁顺序和事务边界，再实现锁定查询，不能靠隐式加锁解决。

context 自己负责固定 origin 来源及其摘要、递归展开和每次资源重授权。保留当前规则：同 owner/session 的 CHILD 必须唯一；COMPLETED 却没有来源回执时报错；其他状态不能凭空补来源。展开限制继续保留循环检测、32 个 CHILD 与深度 16 的边界，来源集合上限 2000。revision 可用于观测或后续明确的并发核验，不替代原权限校验。

## 实现调用者与依赖

| 调用者 | 已接入路径与验证边界 |
| --- | --- |
| `DurableContextStore` | 启动校验及六表全部访问已改为DurableContextPersistence；保留原hash、来源授权、摘要失效、回执重放与边界规则，需ECS验证。 |
| `PersistentContextMiddleware` | 联调 bootstrap/checkpoint 原子性、head 修订竞争、历史切点、来源继承及恢复前授权。 |
| `AgentContextDataBridge` | 继续使用已迁移工作区与独立消息证据，核对文件回读、业务来源版本和 fork 消息映射。 |
| `AgentWorkbenchService` | 工具结果 recordResult/offload、turnSaved、forked、read_context_file、views 联调用新存储；由工作台切片提供真实 ChildProvenanceReader。 |
| `RoleAgentFactory` / `AgentScopeConfiguration` | 验证新服务依赖注入与开关组合；不能通过关闭恢复或子任务功能掩盖未迁移的调用路径。 |

主实现应采用 context 域封装的明确读写方法；现有 JdbcContentStore 只提供部分知识内容能力，不能把它当作已经实现摘要和来源 API。共享 runtime/audit DDL、content 的本域窄改、契约附加路由由各文件维护者协调，避免同时覆盖公共 baseline。

## 复制候选与 ECS 验收源码

`script/schema/author_context_copy.py`读取真实V44声明和当前baseline，生成`sql/mysql/compact/copy/45-context.sql`。源/目标必须是同一已核验ECS MySQL上的不同schema，停止双方业务写入，先建立完整29表baseline、保护触发器与外键；由外层迁移协调器按正式冻结证明设置`@compact_context_source_frozen=1`、`@compact_context_target_frozen=1`，替换`__SOURCE_SCHEMA__`和有证据的`__SOURCE_CONTEXT_OFFSET__`。这两个标志本身不证明源已停写。

复制候选核对六表60列的类型、位置、长度、NULL、默认值、排序规则、所有原主键/唯一键/查询索引和源触发器；未知列、额外约束与未经评审的变化会拒绝。源有时间字段须证明精确微秒offset变化，超范围转换不伪装成功。无时间的head/bootstrap/origin保持NULL；summary状态更新时间未知不补猜。旧id保留在原来源字段，目标公共游标独立，源AUTO_INCREMENT元数据前后保持。

bootstrap/summary原SHA仍按原字串保存。SQL不用JSON_ARRAY的格式冒充Java紧凑序列，而使用显式分隔符和JSON_QUOTE构造原序列；ECS专项由Java ContextDigests生成含中文、补充字符、换行、引号、尾空格的原SHA，对照MySQL实际行为。若存在序列化差异则中止核对，不能重算并覆盖旧SHA。

复制、asset/revision指针建立及全部普通目标列的NULL-safe尾对账在同连接事务内执行。尾对账使用源LEFT JOIN检出缺失身份，未赋值目标列也核对NULL/明确默认值，防止触发器污染或只保总数。共享baseline新增普通列后必须重新运行生成器。首错同连接ROLLBACK，不允许--force。原有agent_context_turn已由消息证据复制承接，本脚本不重复导入。

已编写但未运行：

- `CompactContextMySqlFixture`：真实完整baseline与V44来源表，双schema、server UUID/实例身份/账号门禁；不创建数据库、不使用本地默认连接。
- `ContextMigrationMySqlTest`：60列保真、原文/SHA、NULL历史时间、超过INT的修订号、160字符scope、历史孤儿及旧fork、源行/自增不变、未知元数据/坏摘要/溢出时间拒绝、尾对账回滚和严格nullable记录。
- `ContextStoreMySqlTest`：生产Store在真实目标表上的bootstrap/checkpoint/审计事务回滚、摘要CAS与当前权限撤销、offload首次与重放/变更拒绝、不同账号隔离、ChildProvenanceReader与固定来源快照。仅外部授权/工作区facade为替身，不替代整体ECS功能验收。

运行入口使用明确提供的`doorhandle.context.mysql.config`和（迁移用例）`doorhandle.context.source.config`，环境身份门禁由既有EcsIsolatedMysql继续执行。共享源码构建、MySQL DDL执行、真实源结构对照、文件UNKNOWN COMMIT恢复、fork真实消息/附件切点、并发竞争与完整应用路径仍需统一ECS验收；不得根据静态SQL生成或本地编译将这些能力标成已验证。
