# 公共持久化模型审查

历史记录：以下 HOLD、逐字段草案及暂停说明针对已撤回的第一版方案，不是现行开发状态。当前以 [29 表候选](compact-schema-proposal.md) 和 contract 为准，公共协议仍须完成迁移与 ECS 验证。

状态：`DESIGN_REVIEW_HOLD`。2026-11-05 静态审查，未连接数据库、未运行应用或测试。本文是设计取舍，不是迁移完成证明。`30-operations.sql` 与 `operation-column-map.json` 是逐源字段收集的草案，目前不应据此切库。

不应继续把所有带 `command`、`audit`、`job` 名称的旧表合并为字段并集。30 张是上限，表数应由一致性边界、查询和生命周期推导。本轮暂停新增 DAO 和新增公共字段。

## 当前草案的问题

以下是生成器输出的静态数量，包含虚拟列，不是 ECS 实际建表结果。

| 草案 | 列数 | 二级索引数 | 问题 |
|---|---:|---:|---|
| `coordination_state` | 35 | 5 | 将互斥锁、用户偏好、进程退出证据、额度窗口放在一起 |
| `operation_job` | 205 | 50 | 将队列、永久幂等回执、设备借用、告警、周期计划、确认令牌混在一起 |
| `operation_item` | 65 | 20 | 同时承载租约、导入回执、身份关系和报告来源；并不存在统一父任务语义 |
| `audit_event` | 85 | 23 | 大量只用于展示的旧字段被升为公共列；也混入参与业务准入的事实 |

这些数量本身不是失败判据，但代码已经证明其类型和生命周期不同。静态索引数低于数据库上限，也不能说明该结构合理。原字段有不同排序规则、删除策略和独立唯一键，简单统一成 `utf8mb4_bin` 或复制旧字段会改变语义。原始 DDL 中未声明排序规则的表仍需 ECS 元数据确认。

## 建议公共能力：四类，先定职责再定名称

| 公共能力 | 适合保留的结构化字段 | 适合版本化内容 | 核心约束 |
|---|---|---|---|
| 幂等操作回执 `command_receipt` | 操作种类、主体、请求号、请求摘要、资源标识/版本、状态、创建和完成时间 | 原请求中不参与 SQL 筛选的参数、稳定返回结果 | 原始请求唯一范围；同号不同摘要必须拒绝；资源删除不能释放请求号 |
| 后台工作 `background_task` | 工作种类、外部编号、主体、状态、版本、领取令牌、租约、重试次数、下次执行时间、会话/任务等实际查询键 | 不参与筛选的输入参数和执行证据 | 状态领取 CAS、旧执行者不能越过 fence 更新、到期不等于退出、每类工作独立的幂等键 |
| 追加事件 `audit_event` | 事件种类、主体、对象、请求/运行号、序号、时间、必要版本和摘要 | 不可变的旧值/新值、展示细节、原始快照 | 原有事件序号/请求唯一键；独立保留期限；不可把可变状态伪装成审计 |
| 协调状态 `coordination_state` | namespace/owner/scope、revision、计数/窗口、必要状态和时间 | 小型已注册配置；不承载进程或业务对象快照 | 精确复合 PK、真实事务行锁、命名空间隔离、计数非负；原始高水位不可重置 |

这是公共区建议的四类能力，不是要求最终库恰好 30 张。具体列和索引仍应从保留的查询逐个推导；不为凑数承诺全项目最终张数。可以沿用已有名称减少迁移，但名称不能掩盖职责混合。

建议的字段边界如下。这是审查范围，不是尚未验证的精确列数承诺。

- 回执：`id, namespace, operation_kind, owner_user_id, request_id, request_sha256, resource_type, resource_id, resource_revision, status, payload_version, request_payload, result_payload, result_sha256, created_at, completed_at`，再保留确有独立唯一范围的事件号或 task/dispatch 等类型化键。永久请求登记不跟资源级联，不以 TTL 自动释放。若操作有多个外部副作用状态，则保留显式状态机和 CAS，而非一条成功日志。
- 后台工作：任务号、种类、owner、关联资源/会话、状态、revision、claim token、fence、lease deadline、attempts、next attempt、expiry、created/updated/finished，以及严格注册的输入/结果版本。对话队列的 active slot、执行容量/字节预留、退出确认是确有查询和并发含义的少量类型化扩展，不为所有旧快照逐项添加列。正文清除与摘要留存分别处理。
- 追加事件：事件号、kind、owner/actor、资源类型与 ID、request/run/session/message 等真实读取维度、sequence、revision、发生时间、payload 版本/原文/摘要。只有同类事件需要的单调链摘要、验证状态等字段才进入结构；日志清理按事件类型执行，不能顺带删除模型启用依据或身份链证据。
- 协调状态：`namespace, owner_id, scope_key, revision, state_code, counter_value, window_started_at, window_ends_at, created_at, updated_at` 为候选最小范围；锁只使用前三列。租约若归执行工作则不在锁表重复维护。允许用户/全局作用域，但每个 namespace 的 owner=0 或 owner>0 规则显式校验。用户偏好和进程身份移出后，不需要现草案的 35 列。

版本化内容必须是每个种类对应明确的 DTO/JSON Schema，例如 `ReceiptV1`、`ConversationInputV1`，并固定 `payload_version`。数据库保留真实 SQL 筛选、JOIN、唯一性、金额/额度、领取和 fence 所需字段。`JSON_VALID` 只能验证 JSON 语法，不能替代类型验证。需要数据库保证的 JSON 属性须显式检查存在性、类型、长度和范围，并拒绝未知版本。历史摘要对应的原始 TEXT 字节必须保留，不能重新序列化后仍沿用旧摘要。

## 根据代码作出的归属判断

| 原数据 | 建议 | 代码依据与不可丢失语义 |
|---|---|---|
| `agent_*_command`、workbench/workspace request、session fork、`detection_execution_command`、report/knowledge/digest command | 公共幂等回执 | `FetchInstallationLifecycle` 按 owner/request 查摘要；`McpExecutionLedger.claim` 重复请求不再次调用网络。fork 回执必须在目标会话删除后继续存在。不能只保留资源当前最后一次请求。 |
| `detection_dispatch_outbox`、`detection_report_outbox` | 公共后台工作可以统一 | 两者都有独立事件号、状态、attempt、due、lease 和重试。`DetectionDispatchOutbox:79` 与 `ReportEventRepository:15-29` 明确按到期/租约领取。接收端 receipt 不能因发送端清理而消失。 |
| `detection_report_event_receipt`、`detection_worker_receipt` | 幂等回执，保留业务键 | `ReportEventInbox:24-25` 按 event ID 查摘要；`DetectionExecutionApiImpl:123` 按 task/dispatch 查结果。不得把两个唯一范围改成单一 owner/request。 |
| `agent_conversation_input` | 独立生命周期的后台工作 | `ConversationInboxService:154-170` 按 owner 分页、按会话检查 STARTED、领取后清空正文；保留 input ID 全局唯一和 `(owner,session,active_slot)` 唯一，过期/取消/失败不自动重放。不能级联跟随消息或会话删除。 |
| `agent_mcp_install_job` | 后台工作 | `PersistentMcpInstallQueue:18-39` FIFO/CAS token，且执行资格联查安装注册行。保留原运行校验，不能仅凭通用 RUNNING 状态允许执行。 |
| `agent_mcp_execution` | 后台执行记录可统一，但必须有具体退出证据结构 | `McpExecutionLedger:39,60-66,90-95` 用未 REMOVED 数量限制容量；`exit_verified`/`cleanup_confirmed` 是单调事实。租约到期不得自动释放资源。 |
| `agent_skill_download` 与 `agent_skill_download_lease` | 同一下载聚合内联一对一租约，取消独立通用 item | `SkillDownloadLeases:20-41` 均按 download ID 定位；持有字节和退出确认必须可计算、保留未知退出占额。内联不表示丢弃原 lease ID/时间或混淆下载状态与租约状态。 |
| `agent_skill_import` | 幂等回执 | 是独立 import/request/摘要与导入载荷记录，不是下载任务的任意子项。 |
| `detection_identity_binding`、mapping item、missing-name evidence | 检测身份领域关系；不应归通用 item | `DetectionIdentityEvidenceService:48-56` 以 task/role/head/event/batch/item/proof 多表一致性关系决定身份可信性。missing-name proof 可内联对应 mapping item，但必须保留原 task/role/source snapshot/target 的同值校验。head 只允许在固定角色的领域聚合内联，不能成为自由键 JSON。 |
| identity reconciliation report/item | 检测身份核对记录 | `DetectionIdentityReconciliationService:75-82,119-124` 有不可变数据集摘要、前次报告、高水位和报告数量限制。报告头与细项是一对多；不能无限数组塞到通用 task 的 payload。 |
| `detection_duplicate_ticket`、creation review | 检测领域工作流程 | 人工判定、任务对、审批人、核对版本是业务状态；只有后台执行部分复用工作能力，不能把整个业务对象当通用调度任务。 |
| `device_usage_record`、`device_capture_alert` | 设备领域实体 | `DeviceUsageRecordMapper:23-46` 按设备/员工/当前使用/时间查询；`StatisticsController:101-110` 直接聚合借用次数。告警有确认、解决过程，设备删除策略与借用历史不同。应由设备领域审查决定是否用受约束 device activity，而非直接装入 job。 |
| `quality_digest_schedule` | 质量域的长期计划或独立调度聚合 | `QualityDigestService:37-49` 同一计划反复更新 next fire 并产生多个 run；计划与一次执行不是同一生命周期。可复用工作队列执行 run，不能只保留最后一次执行。 |
| `operations_file_delivery` | 有状态交付操作，可以归操作执行但不是只追加审计 | `FileDeliveryAuditService:36-47` 会推进 STREAMING/终态和回收失联操作，accepted bytes 是下界而非成功字节；UNKNOWN 在此有真实业务含义，不能拿它替其他种类补缺失状态。 |
| `agent_memory_audit` | 必须拆逻辑类别 | `MemoryPreferenceService:58-102` 中 REVIEW_DECISION/AUTOSAVE 是可变的外部副作用回执；PREFERENCE_CHANGED 是追加事件。表名 audit 不能决定合并去向。 |
| `agent_model_json_probe` | 模型配置域的验证事实/操作结果 | `ModelConfigurationService:109` PASSED 是启用新模型的门禁；revision/model/status 必须可查询，不是只读日志。 |
| `agent_model_budget_observation` | LLM 额度域事实 | `ModelBudgetService:32,43-45` 最新 observed time 的剩余额度直接控制准入。可复用事件存储，但 model/observed_at/remaining_tokens 必须显式有约束和索引，不可藏进不可查询载荷。 |
| `agent_skill_eval` | 技能版本的验证事实 | `SkillEvolutionService:299` 检查 skill/version/content hash/suite/passed 决定可用性。可以复用受约束事件表，保留整组字段和判定；不能仅保留“最近一次通过”标记。 |
| `agent_run_event` | 可复用追加事件 | `JdbcAgentJournal:107,146` 需要 run/sequence 唯一和顺序回放。业务审计按 owner/time 检索，运行事件按 run/sequence 检索，两种访问均保留实际索引。 |
| 删除消息后保留的 execution/snapshot/context 证据 | 追加证据，候选归 `audit_event` 的已注册类型 | 是不可变 owner/session/message/run/摘要/时间和快照，不是 job 子项。保留 `(kind,owner,session,message)` 唯一、原 execution run 唯一及原字节；无会话级联 FK。归档插入与删除正文仍必须同事务。该建议需要与消息领域逐项核实后实施。 |
| 单字段 owner 表 | 公共协调状态 | 原业务只有事务互斥需求，可合为 namespace/owner/scope PK。没有理由为每项功能建 owner 表。 |
| `agent_memory_preference` | 用户偏好聚合 | 按用户一对一，读写开关不是锁状态。可加入现有用户设置的明确类型字段/配置版本，不把个人偏好变成全局锁表的专属列。 |
| `agent_mcp_install_worker` | 安装执行的退出证据 | `McpInstallWorkerEvidence:24-31` 保存进程/容器/节点身份与返回状态，供安全清理判断；不是互斥 owner 行。与对应 install operation 一对一融合前必须确认原唯一键及多次执行历史。 |
| export limit、tenant minute | 计数/额度窗口 | export 次数可用协调计数；tenant held/spent/entry/provider 四个计数参与额度控制，应优先归 LLM 额度域，不用一个含义不明的 counter 替换。 |

## 不可用表数替代的检查

1. 每个旧唯一键必须有目标明确对应，不能只增加 `legacy_source/legacy_id` 后宣称幂等性已保留；原文字排序规则也属于唯一性语义。
2. 保留租约状态与退出事实差异，尤其 MCP、技能下载和文件交付。已有 UNKNOWN/NEEDS_REVIEW 只按原有含义迁移。
3. 类型 CHECK 必须显式要求必填字段 `IS NOT NULL`，再验证允许值和范围。SQL CHECK 接受 UNKNOWN，不可依靠 `x>0` 单独拒绝 NULL。
4. MySQL CHECK 与外键动作存在兼容限制；特别检查同列的 ON UPDATE CASCADE 与 SET NULL，不能为让 DDL 执行而默改原删除策略。保持 DELETE CASCADE/RESTRICT 的合法边界，最终以 ECS 的 MySQL 8.4 建表验证为准。[官方 CHECK 文档](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html)。
5. 普通审计不可直接删掉参与门禁或追溯的事实；当前没被页面展示不等于不需要持久化。可以消除重复的一对一 sidecar 和单字段锁表，不能删除永久回执、身份来源、对账高水位或不可恢复原始快照。
6. 整体表数在领域审查汇总后计算。若低于 30，不补齐；若超过 30，先找重复聚合和一对一 sidecar，不靠把真实关系移入无限 JSON 数组挤数。

## 现有实现保留与未完成事项

已编写协调锁的事务/复合主键/InnoDB/排序规则预检，以及第二 DataSource 被事务同步绑定但仍自动提交的拒绝回归。源与测试尚待最终统一构建；本轮没有运行它们。前次 12 模块 test-compile 发生在后续改动之前，不能作为这轮通过证明。

既有草案和逐列映射暂保留用于不丢字段的审查，不继续扩宽。下一步先冻结领域归属、保留查询/约束清单和生命周期，再重写 DDL/DAO/迁移，最后在 ECS 做空库建表、迁移对账、并发与重启验证。本地仅编辑、构建和静态审查。
