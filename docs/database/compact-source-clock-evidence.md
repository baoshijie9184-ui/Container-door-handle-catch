# 旧库转换时钟证据

## 2026-11-07 ECS 实际数据补证

实例恢复后，本轮已只读核对实际源表及工作区文件。`binding`、`export`、`research` 对应的五张历史表精确为空；其余十二个条件域存在实际历史行，仍不能自动采用统一偏移。私有现场证据保存在 `work/ecs-resume-20261107/source-clock-provenance.json`，SHA-256 为 `50198c415df1a1cd835d53aca8ee9863cf3e0dbad0fa3afac41c36fa06a46221`。

实际工作区 `artifacts/users` 中 21 个文件的大小和内容摘要全部匹配原表。将对应 `created_at` 按 UTC 解释，与 Unix 文件修改时刻相差约 0.54～2.62 毫秒，覆盖 10 月 17 日与 25 日；历史 producer 的顺序是先创建文件再插入元数据。这支持这些记录按 UTC 写入的判断，也表明不能将本域整批减去八小时。该证据只适用于已核对的这些字段和记录，不能扩展至其他表、字段或整个域。

下文是更早完成的源码审计，表中的 `f95 producer` 配置描述不等于真实旧服务器逐行时钟事实。实际迁移继续拒绝未经核实的全域偏移；无法证明绝对时刻的历史数据需要明确的未知时钟协议，保留原始值及来源，不能伪造 UTC 时间。

本次只读审计以历史提交 `f95f09d78a0234a2f507bd452220d89b823ae05e` 为准，未启动或查询 ECS，未运行数据库、应用或测试。当前代码已改用 UTC，不能用它说明旧数据的写入语义。本文核对 22 个 `__SOURCE_*_OFFSET__` 模板域及 Workbench，共 23 域；保留原值的核心专用表不因此增加时区转换。

结论有三个层次：日报的历史 producer 明确写 UTC；另外 22 域在该提交对应配置下写 UTC+8 墙钟。其间 8 域的全部受转换表首次引入于时钟配置固定之后，另 15 域有更早的表，必须区别核实历史数据来源。更早存在表不等于更早存在数据，也不能据此认定实际已有混时区行。

## 证据基准与历史配置

以下行号都指 **f95f09d7 中的文件**，不指当前工作树。复查方式为 `git show f95f09d7:<文件路径>`。

| 证据 | 历史内容与含义 |
| --- | --- |
| `deploy/backend/entrypoint.sh:5–6` | `TZ=Asia/Shanghai`，Java 命令显式 `-Duser.timezone=Asia/Shanghai`；无参 `LocalDateTime.now()` 为该 JVM 墙钟 |
| `compose.monolith.yml:16` | backend `TZ: Asia/Shanghai` |
| `compose.cloud.yml:32,36` | MySQL `TZ: Asia/Shanghai`，启动参数 `--default-time-zone=+08:00` |
| `doorhandle-server/src/main/resources/application.yml:24` | Hikari 每个连接初始化 `SET time_zone = '+08:00'`；SQL `CURRENT_TIMESTAMP` 及 DATETIME 默认值按这个会话生成 |
| `deploy/cloud.env.example:28` | JDBC 示例 `serverTimezone=Asia/Shanghai`；这是跟踪的示例配置，不是对实际旧环境变量的现场证明 |
| `detection_worker_receipts.py:54` | Python worker 的 MySQL 连接明确 `init_command="SET time_zone = '+08:00'"` |

统一配置是在 `deca201920fc3b10a2bac5cf7b8f16c61758a1e5`（2026-10-18 00:29:00 +08:00）加入的。该提交同时增加 JVM/Compose TZ、MySQL默认 `+08:00` 和 Hikari session `+08:00`。它的父提交仅有 `SET NAMES utf8mb4`，Java入口没有 `-Duser.timezone`，MySQL Compose 没有默认时区参数。因此不能把此后的配置反推为此前所有实际 producer 的时区；也不能仅凭基础镜像通常采用 UTC，就断言此前实际写入一定是 UTC。

只读私有证据 `work/closeout-20261029/production-final-state.json` 记录旧运行 release 为 `ci-43-9347e8ae8e0e`；`work/data-migration-20261105/cutover/migration-cutover-audit.json` 同样记录这个最后观察 release。`git diff 9347e8ae8e0e f95f09d7` 中本文核对的Java producer和 `detection_worker_receipts.py` 没有变更；Kafka入口及环境读取另有ECS配置整理，但上述写时钟规则未变。这支持最后观察版本的代码对照，仍不是逐行历史写入证明。

经单独准入的脱敏证据 `work/schema-reduction-20261105/redacted-runtime-clock-evidence-20261107.json` 还记录：10-14缓存 `work/cloud/cloud.env` 和10-19备份的 JDBC `serverTimezone` 都是 Asia/Shanghai；前者未含 `-Duser.timezone`。这里只读取脱敏字段及原文件SHA，没有读取原凭据文件。其mtime不是部署时间，也不能证明该文件生成了所有现有行；它佐证早期JDBC设置，不能补齐早期JVM或MySQL时区事实。

## 23 域逐项核对

下面给出的偏移表示 **f95 producer 的写入合同**。`条件 +08:00` 表示该域有配置固定前已存在的表，不能直接作为旧库所有行的统一设置。首次日期按具体表的 CREATE 首次进入历史 Git 计算，不采用整个 SQL 文件创建日期，也不采用当前文件时间。详细提交号、全部表/列、原始表达式及行号保存在机器可读证据中。

Java 文件的包根分别为 `doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/`、`doorhandle-module-app/src/main/java/com/ruanzhu/doorhandle/module/app/` 以及相应 detection/system/model/infra 模块。

| 域 | 受转换表最早跟踪日期 | 历史 producer / 原表达式 | 建议与限制 |
| --- | --- | --- | --- |
| action | 09-11；Agent确认表10-15 | `ai/action/AgentActionService.java:93,282,310`：查询数据库时间、SQL决定时间；`app/service/impl/ChatSessionServiceImpl.java:278,316`：旧 chat action `LocalDateTime.now()` | 条件 `+08:00`；还须核对 JDBC Timestamp 路径，见下文 |
| agent | 10-15；research answer10-17 | `ai/journal/JdbcAgentJournal.java:82,120,146,165,197`：SQL CURRENT_TIMESTAMP 与 `databaseNow()`；`ai/research/ResearchEvidenceService.java:127`：answer SQL时间 | 条件 `+08:00`；started/ended/heartbeat/lease/event/answer都按来源记录核验 |
| binding | 10-15 | `system/service/AccountIdentityService.java:84`：`audit.setCreatedAt(LocalDateTime.now())` | 条件 `+08:00`；旧观察表估计为0行，不能据估计宣称确实为空 |
| chat | 10-24；V66为10-28 | `app/service/impl/MessageExecutionLinks.java`、`WorkspaceTurnSnapshotService.java`：INSERT省略时间，V45/V66 DDL 默认 CURRENT_TIMESTAMP | `+08:00`；这些是执行关联/快照证据，不是把旧 chat_message 原时间一律重写 |
| context | 10-24 | `ai/context/DurableContextStore.java:79,163,218,248`：summary/offload/audit SQL CURRENT_TIMESTAMP(6)，其他默认时间见 V44 | `+08:00`；表首次在配置固定之后引入 |
| detection | 10-24 | `detection_worker_receipts.py:54,94,143`：明确session +08及SQL时间；`detection/api/DetectionExecutionApiImpl.java:81`；creation/outbox SQL默认/更新 | `+08:00`；七张表的UTC/墙钟判断包含Python producer，不以当前worker新源码代替 |
| digest | 10-28 | `detection/service/QualityDigestService.java:31,37–43,48–50,58,60`：`now()`明确 `LocalDateTime.now(ZoneOffset.UTC)`，cron转换UTC；V65开头也声明UTC DATETIME | `+00:00`；所有SQL DATETIME业务字段均由此UTC时钟写入，report_date是日期，不做时区换算 |
| export | 10-17 | `ai/research/ResearchEvidenceExportService.java:63–67`：省略SQL审计时间，由V33默认值生成；`ResearchExportRateLimit.java:53`：读取数据库墙钟 | 条件 `+08:00`；导出文件中 `Instant.now()` 是另一个带时区的JSON字段，不能对它减8小时 |
| identity | 10-24 | `detection/service/DetectionIdentityReconciliationService.java:29,60,121`：显式 `ZoneOffset.ofHours(8)`；其余 evidence/command/batch 用SQL CURRENT_TIMESTAMP(6) | `+08:00`；无时钟的原行仍应NULL，不因本审计补造时间 |
| inbox | 10-17 | `app/service/impl/ConversationInboxService.java:55,90,156,179`：`SELECT CURRENT_TIMESTAMP(6)`、SQL更新；expires由数据库now加期限 | 条件 `+08:00`；created/updated/expires/audit共用同一旧producer合同 |
| infra_log | 09-11 | `infra/service/impl/OperationAuditServiceImpl.java:50`：`LocalDateTime.now()`；旧 schema 的 operation_audit_log默认时间 | 条件 `+08:00`；历史日志来源不能由现在JVM位置倒推 |
| mcp | 10-15；部分后续表10-24后 | `ai/mcp/LocalMcpService.java:264–266`、`McpExecutionLedger.java:49–50,56,81,100`、`PersistentMcpInstallQueue.java:15,24`、V25/V47等默认值 | 条件 `+08:00`；早期registration/audit/install-job与后期execution/retention不能只按域名一并推定历史时期 |
| memory | 10-15 | `app/service/MemoryPreferenceService.java:26–30,88,95,102`：SQL CURRENT_TIMESTAMP | 条件 `+08:00`；Python Mem0文件回执中的offset ISO字符串不是这些SQL DATETIME列 |
| model | 10-24 | `ai/model/ModelConfigurationService.java:45,82,105,126,147,173`：configuration/command/probe/revoked时间全部SQL CURRENT_TIMESTAMP(6) | `+08:00`；与单独采用UTC的 ModelBudgetService 区分 |
| model_file | 10-24 | `model/service/ModelFileJournal.java:67,77,91–96`：INSERT省略默认时间、更新SQL CURRENT_TIMESTAMP(6)；V53 DDL | `+08:00`；文件内容时间和ISO进程启动身份不属于这两表DATETIME转换 |
| model_log | 09-11 | `model/service/ModelRegistrationService.java:50`、`model/service/impl/ModelServiceImpl.java:276`：operationTime `LocalDateTime.now()` | 条件 `+08:00`；只转换model_operation_log，引用的model_management主表仍按专用表规则原值复制 |
| operations | 10-24 | `system/service/OperationsAuditService.java:23`、`FileDeliveryAuditService.java:36,41,54`：SQL CURRENT_TIMESTAMP(6)，V40/V52默认时间 | `+08:00`；两张受转换表均后于配置固定 |
| report | 10-15 | `detection/service/QualityReportService.java:266`：JVM now；`config/ReportEventConfiguration.java:22`：Clock.systemDefaultZone；`service/report/ReportEventDispatcher.java:64`；`ReportEventInbox.java:24,28–29` SQL时间 | 条件 `+08:00`；审计/命令/确认/outbox/消费回执等须逐来源时期核对，主quality_report原值复制不等于这些附属记录已确认时区 |
| research | 10-17 | `ai/research/ResearchEvidenceService.java:94–104,146`：数据库now及其衍生expires；Storage清理INSERT时间省略走V32默认值 | 条件 `+08:00`；当前历史元数据估计为空，不以估计替代实际空表证明 |
| sdk | 10-17 | `ai/workbench/JdbcWorkbenchStateStore.java:35`：updated_at=CURRENT_TIMESTAMP(6)，首次INSERT用V37默认值 | 条件 `+08:00`；checkpoint更新时间不是SDK当前进程的UTC时刻 |
| skill | 10-15；lease表10-24后 | `ai/evolution/SkillEvolutionService.java:53,74,160,195,203,301`；`SkillLinkService.java:63`；`SkillDownloadLeases.java:24–27`：SQL CURRENT_TIMESTAMP及其期限 | 条件 `+08:00`；下载进程的带offset ISO身份字段原值保留，不作为SQL时钟转换 |
| workspace | 10-17 | `app/service/impl/AgentWorkspaceService.java`：file/ref/audit/request/fork INSERT省略时钟；V38 SQL DEFAULT CURRENT_TIMESTAMP | 条件 `+08:00`；新创建fork/request表与早期file/ref表分别列在机器证据中 |
| workbench | 10-17 | `ai/workbench/WorkbenchStore.java:45,49`：INSERT默认值与SQL更新；`AgentWorkbenchService.java:260–261` heartbeat和数据库now；V37 | 条件 `+08:00`；调用真实迁移helper时也必须传这个经证据确定的偏移 |

## 已识别的混时钟风险与精确处理

在 f95 的23个转换域当前 producer 中，没有找到一个普通DATETIME列同时明确用 UTC producer 和 `+08:00` producer 写入的证据。日报是完整独立的 UTC 域，其余22域是上述配置下的墙钟。不能把“配置曾变化”“JSON中有UTC字符串”写成“已经证实同一DATETIME列混时区”。

需要单独核实 action 的三组列：

1. `agent_pending_action.created_at/expires_at` 来自 `AgentActionService.now()` 的 JDBC Timestamp → JVM LocalDateTime 路径。
2. `agent_pending_action.decided_at`、`agent_action_audit.occurred_at` 由SQL会话时间直接生成。
3. `chat_pending_action.created_at/confirmed_at` 来自另一个JVM producer。

实际旧 JDBC `serverTimezone` 与 JVM时区一致时，三组均符合 `+08:00`。若历史 JDBC 与JVM不一致，Timestamp转换可能产生额外偏移；仅读取当前MySQL session无法证明旧的created/expires语义。应先查对应release脱敏连接参数及旧运行/修复记录，再决定是否需要三组独立偏移；不能默许一个 `action` 参数覆盖已证实不一致的组。

另有明确的 producer 代码修复史：`746ff5e2`（2026-10-15 16:46:24 +08:00）把 `JdbcAgentJournal.databaseNow()` 从 `Timestamp.class → toLocalDateTime()` 改为直接读 `LocalDateTime.class`，提交说明是修正run lease与数据库时钟一致。若实际有修复前的 `agent_run` 行，`lease_expires_at` 这一衍生期限须与直接SQL生成的started/heartbeat/ended分别核对。这是有证据的代码路径差异，仍不能据此宣称现库一定留有错误租约或给所有早期行统一指定另一个偏移。

全局历史配置变化也可能使一个仍存活的行具有旧时期created、新时期updated/finished。要核实的是**实际来源记录**，不是只看表存在时间。目前离线集合没有逐行时间范围或写入版本证明，也没有证据证明这些表当时真的已有数据。对配置前已存在但现场确认精确为空的表，无需虚构历史时刻，可以按当前已审阅producer合同设置；InnoDB `estimatedRows=0` 不算这种确认。

若后续证实同列不同时期或同域不同列确实混用时区，应先保留原始DATETIME字符串、NULL、微秒、表/PK、source快照SHA，使用由历史部署/写入证明绑定的列或PK区间规则转换，并逐行记录所用偏移。不能根据当前值看起来像北京时间、文件mtime或未核实的commit日期自动分组。

无法确定绝对时刻时，精确修复方向是给对应legacy协议增加 `clockStatus=UNRESOLVED` 和原值证据，绝对UTC字段保持NULL，旧有效租约/自动调度入口进入需核对状态；只对这些已审阅legacy种类放开相应非空约束。若该领域的当前协议不能表示未知时钟，应先开发只读历史适配或在现有audit关系保存完整历史记录，禁止把它作为可执行的当前任务启动。不得填 `+00:00` 冒充已确认UTC，不补导入时间，不删除原行。此分支**尚未实现**，当前整库入口仍要求单一有证据的域偏移；发现实际混时钟时应停止相应正式迁移，而非只让对账算式自洽。

## 机器可读建议及适用边界

Git忽略的本次证据目录为 `work/compact-source-clock-evidence-20261107/`：

- `historical-clock-inventory.json`：23域、49个历史producer文件的SHA/行表达式、表列DDL及具体CREATE首次提交、当前copy所转换的表达式。只含源码/元数据，不含业务行或凭据。
- `source-offset-recommendations.json`：`supportedProducerOffsets` 为8域；`conditionalF95ProducerOffsets` 为15域；`sourceOffsets` 中未核历史的15域明确为NULL，`readyForAutomaticUse=false`。这是一份建议，**不能直接当ECS settings使用**，也不能把NULL替换成默认值来绕过核实。
- 两个离线作者脚本只调用本机Git读取和已列明元数据文件，便于复查；没有执行历史producer。

“8域支持”指已跟踪producer合同与表引入时期相符，仍应绑定实际源库和release；“15域待来源核实”不等于已经发现错误数据或必须迁移失败。核完真实行来源或精确空表证明后，可将对应有证据偏移写进正式私有设置并保存依据。

此外，历史 `ModelBudgetService.java:26` 与 `QualityKnowledgeService.java:27` 明确采用 `LocalDateTime.now(ZoneOffset.UTC)`，但它们所在copy已按UTC原值处理，不属于这23个参数域。不能因为类名包含Model或Knowledge而把 `sourceOffsets.model` 改成UTC，也不能把13张核心原值保留表一并减8小时。
