# Workbench 持久化迁移设计

**状态：源码已实现，未运行测试、未迁移ECS。** WorkbenchStore/Service已直接访问workflow_instance、audit_event和runtime_state，SDK写入绑定持久claim/fence；旧三表只在显式离线迁移器中读取。新增ECS-only真实29表工作台及双schema迁移用例源码。共享DDL由统一baseline维护，最终可运行性须以完整构建和ECS验收为准。

本轮不启动数据库、应用或ECS，不在本地执行测试。没有把源码完成或旧测试历史当作新结构通过验收。

## 1. 实际来源与边界

本切片的三张来源表共 **23 列**，均来自 `sql/mysql/migration-V37-agent-workbench.sql`。V37 未声明表级 collation，迁移时必须读取实际元数据；不能从环境默认值推测。

| 来源 | 全部原列 | 关键约束 |
| --- | --- | --- |
| `agent_workbench_item`，10 列 | `id` unsigned bigint；`item_id` varchar64 bin；`user_id` bigint；`session_id` varchar128 bin；`kind` varchar32；`status` varchar40；`revision` bigint；`payload` LONGTEXT；`created_at`、`updated_at` datetime6 | 数字主键自增；`item_id` 全表唯一；owner/session/id 与 kind/status/id 查询索引；revision 默认 0；两个时间默认 CURRENT_TIMESTAMP6；无 FK/CHECK |
| `agent_workbench_request`，5 列 | `id` unsigned bigint；`user_id` bigint；`request_id` varchar128 bin；`request_sha256` char64；`result_json` LONGTEXT | `(user_id,request_id)` 跨所有工作台命令唯一；没有任何创建或完成时间列；无 FK/CHECK |
| `agent_workbench_audit`，8 列 | `id` unsigned bigint；`user_id` bigint；`session_id` varchar128 bin；`item_id` varchar64 bin；`action` varchar48；`revision` bigint；`payload_sha256` char64；`created_at` datetime6 | 只有数字主键唯一；不能新增 `(item,revision)` 唯一后假设历史没有重复；无 FK/CHECK |

V37 还有 owner 锁与 SDK state 两表，其当前访问已分别使用 `runtime_state` 的 WORKBENCH 锁和 SDK_CHECKPOINT。本文不重新迁它们，也不凭本切片宣布它们的历史复制已验收。

现有工作项至少有 14 类，主执行的实际 kind 是 **EXECUTION**，不是 RUN。使用统一生命周期容器有真实依据：它们共享稳定 item ID、owner/session 隔离、版本 CAS、创建时间、列表排序和工作台审计。但不同类型的状态、数据和权限仍必须分别定义，不能把现有 `Map<String,Object>` 原封不动变成一个万能载荷。

## 2. 推荐落点

保持现有 **29 张目标表**。已在 `workflow_instance` 中注册以下14个明确的工作项协议，另有命令回执与独立逻辑任务协议；原变更审计写 `audit_event`。kind 数量不是新增表数。

| 原 kind / 建议协议后缀 | 需要保留的行为 | 专用载荷内容，不含任意附加字段 |
| --- | --- | --- |
| EXECUTION | 主任务运行、等待、恢复、取消、完成后新建逻辑任务 | 当前逻辑任务、角色快照、模型选择/配置版本/历史、计划要求、批准计划、续执行提示、结果、释放等待标记 |
| CHILD | 排队、抢占、执行、等待、取消、追加与结果核对 | 父 item/父逻辑任务、specialist、问题、最多四条排队追加、角色与模型快照、当前尝试、结果 |
| PLAN | PENDING → APPROVED / CHANGES_REQUESTED / CANCELLED | 标题、计划正文、任务清单、修改意见、父任务及原 run |
| QUESTION | PENDING → ANSWERED / CANCELLED | TEXT/SINGLE/MULTIPLE 的独立回答结构、选项、问题、父任务及原 run |
| TASKS | 同一个逻辑任务的 ACTIVE 清单可更新 | 有类型的条目数组：标题、状态、已核实的 evidenceCallId/evidenceRunId |
| TOOL | UNKNOWN → COMPLETED；未知写操作禁止自动重发 | 工具名、call ID、输入摘要、readOnly/idempotentMetadata、实际 AgentState 结果文本、父任务与尝试 |
| CHECKPOINT | SAVED 索引可更新 | phase、父任务、逻辑任务、run、已成功保存的sdkRevision；真实SDK state仍在runtime，不复制状态正文 |
| MODEL_SELECTION | ACTIVE 版本选择 | modelId；保留客户端旧版本 CAS 和模型配置重查 |
| TURN | 消息切点的不可变工作台快照 | throughMessageId、当时 PLAN/TASKS 的有类型快照；保留当时状态，不把未完成轮次伪称完成 |
| FORK_SNAPSHOT | REFERENCE_ONLY，不继承执行许可 | sourceSessionId、throughMessageId、原快照内容 |
| ARTIFACT | 文件创建后的结果记录 | fileId、filename、原任务/run；文件本体与当前文件授权仍属于工作区域 |
| USAGE | 每次模型尝试的观测记录 | 模型、供应商、候选顺序、状态、输入/输出/缓存用量、时延、purpose、估算依据；未知保持 NULL |
| CONTEXT | 压缩开始/完成/失败/取消的观测 | 明确事件、before/after 统计、policy/purpose、依据；具体字段须按 AgentContextCompaction 发出者建立白名单 |
| TOOL_TIMING | 一次工具批次的时延观测 | durationMs、MEASURED_BATCH、父任务/run；不是供应商 token 用量 |

实现使用 `WORKBENCH_EXECUTION`、`WORKBENCH_CHILD` 等明确kind，域内注册版本化 record 和状态转移，不放入公共默认协议注册表。不可变观测仍保留工作项身份，是为了保留原 `item_id` 跨全部类型的唯一性、顺序与引用；若将一部分移到 audit/content 而不保留统一身份，就会放宽原全局唯一约束。

统一 identity 设计：

- `resource_type='WORKBENCH_ITEM'`，`resource_id` 保留原 item ID；生成 `workbench_item_id`，只对上述 14 类非空，并加全局唯一键。
- 工作流自己的 `workflow_id` 与外部 item ID 分离：导入可用 `wb-item:<原数字 id>`，新行用 UUID，避免旧 64 字符 item ID 加前缀后超过公共列长度，也避免与其他域撞号。
- 原 `item_id` 继续作为 API ID，不能改成公共数字游标。原数字 id 放在来源证据中；按原 id 顺序插入，维持工作台内部相对排序，调度游标使用新全局 id。
- owner/session/item identity 创建后不可由运行 API 改写。旧来源没有用户、会话、父 item FK；不新增级联删历史的关系，也不能因当前父对象缺失而过滤旧行。

ItemV1包含schemaVersion=1、固定多态data record、presentFields和可空legacy证据；载荷具有固定record、版本、必需键与类型校验，使用独立 `ObjectMapper.copy()` 和 `Include.ALWAYS`，不继承 Web 的 NON_NULL 配置。原 LONGTEXT `payload` 是已有单列证据：保留其精确文本作为明确的 legacy 证据字段，同时把运行所需字段解码为专用协议。不能把整张旧表打包塞入 JSON；遇到不支持的 kind、未知载荷字段或无法安全解析的内容应整批中止并列出原因，不能删字段、猜类型或跳过记录。

## 3. SQL 查询字段和索引

以下参与调度、归属、权限或恢复的字段应具有明确 SQL 列，不再通过 Java 全表过滤或 `payload LIKE` 判断。现有列可复用，只有确有查询需要才增加专用生成列：

- 现有 `owner_user_id/session_id/run_id/status/revision`；claim_token/fence/lease_expires_at 承载新的尝试租约。
- `workbench_item_id`：全类型全局唯一；`workbench_parent_item_id` 和 `workbench_parent_task_id`：父子取消、唤醒和同一轮逻辑任务筛选。
- `workbench_logical_task_id`：隔离同一个复用主 item 的不同逻辑任务；不能只比较 parent ID。
- `workbench_specialist`、`workbench_role`：实际运行 specialist 写权限核查；不得把角色放在自由 JSON 后省略当前账号复核。
- `workbench_yield_ready`：NULL/false/true 区分，替换原文本 LIKE；`workbench_instance` 如用于进程归属判断，也应有明确类型。

使用 `(kind,status,id)` 调度索引，`(owner,session,parentItem,parentTask,id)` 子项查询索引，以及实际 run/specialist 权限索引。不得把列表上限 180/200 用于“是否仍有未完成子任务”或用量汇总，否则会忽略旧项。子项查询可以分页或定向 exists；用量聚合必须分别记录已报告数量，任何缺失用量仍使对应总额未知。

原 status 列是 varchar40，公共目标目前为 varchar32。实现时应选择兼容的明确方案，推荐扩到 varchar40，再由各协议限定合法状态；不得静默截断。角色、逻辑 ID 等从原 JSON 提取的列长度也应先审实际发出者和旧数据，不能靠 CAST 截断后通过。

## 4. 主执行、子执行与租约

有两处容易误判成永久终态：

1. 主 EXECUTION 的稳定 ID 按 owner/session 生成，COMPLETED 或 CANCELLED 后会以新 `logicalTaskId` 再次 RUNNING。
2. CHILD 已 COMPLETED 仍允许 `child-message` 追加，回到 QUEUED；运行中追加最多四条，完成当前调用后有追加则继续 QUEUED。

因此这两类不能照搬通用“COMPLETED 永远终态、完成后禁止变化”的协议。新开始要清除上一轮 finished 标记并更新尝试身份，历史完成事实由不可变审计保留。PLAN/QUESTION 和 TOOL 等类型才分别使用自身的不可逆终态规则。

原实现只有owner锁、revision、runId与本机心跳。当前源码改为90秒数据库UTC租约和独立token/fence，local liveExecutions仅记录本进程尝试；它不能替代数据库执行权。源码完成以下边界，仍须ECS故障与竞争验收：

- owner 锁后对工作项做当前读，再按 revision、当前逻辑任务、run、claim token/fence CAS 抢占或完成。主 prepare 和子 dispatch 都必须持有明确尝试身份。
- 心跳仅续当前 claim 的 `lease_expires_at`，不能让旧进程续活新的尝试，也不能让已取消 worker 写回结果。
- 等待项只有在 SDK 检查点成功保存后才能设置 yieldReady；释放 claim 与等待标记同事务。模型/工具/网络调用始终在短数据库事务之外。
- 过期 RUNNING 收敛为 NEEDS_REVIEW，不自动重新执行未知写操作。恢复前继续核对原业务回执、当前角色、模型配置和 SDK 状态。
- 保留取消的父子传播、对进行中线程的中断及结果 fencing。主任务重开后，旧 logicalTaskId 的取消、子结果和心跳不得影响新任务。

旧行从来没有 claim token，迁移不得凭空制造执行身份。原 updated_at 转 UTC 并原样留证据；旧运行行进入核对流程，不能因为目标机刚启动便重新授权执行。

## 5. 命令幂等与审计

`agent_workbench_request` 对所有命令共享 owner/request 唯一范围。实现一个永久 `WORKBENCH_COMMAND` 回执kind，scope `OWNER:<id>`，保留原 request ID 与原 request_sha256，不按 approve/cancel/select-model 拆唯一范围。变更 item/parent/必要审计与回执在同一事务，重复同签名返回原结果，不同签名返回 409。

目前调用结果只有 `AgentWorkbenchApi.Item` 与 `ModelSelection` 两种。新结果用明确的 resultType 与有类型结果；历史 `result_json` 原文保留，按这两种真实结果形状校验。原表没有操作名、输入正文和任何时间，不能从结果猜原命令或制造创建时间。需要仅限精确 legacy_source 的 created/updated/finished NULL 特例，新回执使用真实 UTC 时间。

审计使用独立 `WORKBENCH` kind：owner、session、原 item ID、action、revision、原 payload_sha256、occurred_at 明确落列；原 id/created_at/sourceUtcOffset 保留在固定载荷。旧审计只有当时 payload 的摘要，没有历史完整 payload：不能拿当前 item payload 来重算替代旧摘要，也不能声称可恢复每次历史正文。旧 actor 无数值字段，保持 NULL；新操作记录真实 actor。保持原允许重复版本的事实，不新增历史不存在的唯一键。

创建、更新、计划/回答引起的父状态变化，以及命令回执必须使用同一个事务。事务采用当前读或明确 READ_COMMITTED，不能在 owner 锁之后读取早先 RR 快照。统一顺序为 owner 锁 → 按固定顺序的 item 行 → 相关回执/审计；与 context 的锁序单独约定，不在持 context 锁时反向拿 WORKBENCH owner 锁。

## 6. 与 DurableContextStore 的接口约定

已由context包的public ChildProvenanceReader定义、工作台唯一WorkbenchChildProvenanceReader组件实现以下窄契约：

```java
Optional<ChildProvenance> find(long ownerUserId, String sessionId, String itemId);
record ChildProvenance(String id, long ownerUserId, String sessionId,
                       String status, long revision) {}
```

接口位于AI模块context包，由workbench实现类委托新持久化的窄SQL。context使用它替换原两处旧工作项查询：snapshotChildren 与 authorize。只查 `WORKBENCH_CHILD`，同时限制 owner/session/item，不能裸查 ID、不能读取整个载荷、不能回退旧表。它不获取 owner 锁；此窄reader不使用FOR SHARE，避免 context 行锁 → WORKBENCH owner 锁的反序。若后续需要跨域强一致状态验证，必须先共同明确锁顺序。

context 保持原固定 `child:<id>` 来源快照及每次读取/恢复/fork 的资源重授权，防循环及展开限制仍由 context 负责。COMPLETED 且缺少 origin 回执仍应报错；其他状态的无来源行为保持原约定。COMPLETED 可以被追加转 QUEUED，既不是永久完成事实，也不是授权依据。owner/session 身份不可变使单次当前查询不会扩大归属；revision 供状态一致性诊断，不能把未来追加的来源追溯并入旧快照。

## 7. 时间、复制和验证要求

item 的原 created/updated 和 audit 的 created 是独立已知时间，使用有证据的来源偏移转 UTC，同时保留原文本与实际微秒差门禁。原 item.updated_at 可能是心跳，不可等同完成时间；历史 finished_at 保持未知。request 没有时间，明确 NULL。API 延续原北京时间显示，内部租约统一 UTC。

下一轮迁移候选必须是真正双 schema，使用实际 V37 三表及全部 23 列元数据/唯一键检查；原 source 未声明 FK/CHECK，额外约束或触发器应拒绝。原 owner/session 或父引用已不存在的历史必须按原规则保留，不能新增删除级联。所有来源数值 id 作为证据保存，源自增高水位不动；原全局 item ID 与 owner/request 唯一性在目标分别验证。

旧 payload/result LONGTEXT 没有数据库 JSON 约束。复制前须逐类型检验原始数据并明确报告不支持的事实，不准跳过失败行。最终在全部 DML 后对全部目标普通列及固定载荷进行 BINARY NULL-safe 对账，包含原字节文本、未知时间、应为 NULL 的异域字段；目标触发器篡改早先已插入项也应使整批回滚。

必须补的 ECS 用例包括：

- 同 request 并发只产生一个变更；同 key 异内容 409；CAS/审计失败整事务回滚。
- 主任务完成后开始新逻辑任务、子任务完成后追加、排队上限、计划/问题等待保存、父子取消与唤醒。
- 旧 worker 的心跳和完成不能越过新 fence；取消与 finish 竞争不能复活任务；未知写回执未核实时禁止恢复。
- 真实模型配置重选、权限撤销、SDK checkpoint 版本关系保持；CHILD reader 跨账户/会话拒绝，并与 context 固定来源配合。
- 原 item ID 跨全部类型唯一、两种命令结果幂等、原23列/NULL时间/大数字ID/原JSON文本/审计摘要保真，以及目标破坏回滚与 source 未变。

当前AgentWorkbenchServiceTest已移除V37过渡表，只安装真实29表baseline。原WorkbenchExecutionFixture的H2回退也已移除，要求显式ECS隔离MySQL配置；构建/测试代码编译不等于测试执行。

## 8. 当前实现接口与落地边界

- WorkbenchStore的owner锁使用READ_COMMITTED；关键item、命令和逻辑任务读取在事务内使用当前读，防止外层RR快照早于锁。
- 90秒claim使用workflow的claim_token/fence/lease_expires_at。新尝试或撤销推进fence；续租不能复活已过期claim。SDK写入、工具结果、元数据工作项及完成回写都核对该scope捕获的token/fence/run/task；SDK还绑定准确账号及SDK session。
- 复用主EXECUTION时为每个logicalTaskId建立独立WORKBENCH_LOGICAL_TASK行，保留角色/模型初始快照和生命周期；旧逻辑任务不会被新主item覆盖。CHILD追加仍可复用其逻辑任务并重新排队。
- 失联RUNNING进入NEEDS_REVIEW。只有同run/task的CHECKPOINT及真实SDK revision屏障可证明等待已保存，随后释放claim；没有屏障不会猜yieldReady。旧历史没有sdkRevision时同样不补造。
- 用量汇总、未结束child及未知工具扫描采用独立无展示上限查询，不被180/200条页面列表截断。

### 8.1 显式离线复制API

WorkbenchLegacyMigration不是Spring Bean，不会在启动时迁移。整库编排可构造：

```java
var migrator = new WorkbenchLegacyMigration(targetJdbc, targetTransactionManager, mapper);
var admission = new WorkbenchLegacyMigration.Admission(
    instanceId, machineId, sourceSchema, targetSchema, serverUuid,
    sourceUtcOffset, reviewedSourceTableCollations);
var receipt = migrator.copy(admission);
var verification = migrator.verifyCommitted(admission, receipt);
```

Admission要求显式源/目标schema、同一MySQL UUID、三张源表实际collation、有证据的ZoneOffset；运行端强制Linux、/etc/machine-id、DOORHANDLE_ECS_*及阿里云IMDSv2实例ID一致。没有默认连接、本地库回退或环境推断。

复制器拥有独立RR事务，固定顺序对源三表完整主键范围FOR SHARE，核对23原列、类型、NULL、默认值、原唯一键、无额外FK/CHECK/触发器、SHOW CREATE与AUTO_INCREMENT。读源仅需SELECT和明确TRIGGER元数据可见性，不写源。源范围锁只保护本切片，整库仍须统一停写/备份及源身份门禁。[MySQL锁定读](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html)、[范围与间隙锁](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html)

迁移先校验全部kind和闭合载荷，再DML。每张源表当前限50,000行、载荷初始估计64 MiB；超过即停止要求显式流式方案，不跳行。源payload/result_json精确字符串保留，大于Java signed long的原自增ID按十进制legacy_key保留。源请求从无时间，目标三时间显式NULL；原审计SHA不按当前item重算。历史孤儿不补父实体或删除。

旧item只能证明当前logicalTask快照，派生逻辑任务标importedCurrentSnapshot=true，initialRunId及创建/更新时间为未知；不能用旧item创建时间冒充当前任务开始时间。源已被覆盖的旧逻辑任务并不存在可恢复证据，工具不会伪造历史。

目标每一行的全部普通列（包括应为NULL的异域字段）先生成期望值，全部DML后再统一逐字节核对，包含迁移前已有workflow/audit行；后插入审计触发器若破坏前项会整事务回滚。源行摘要、DDL/列/索引摘要及AUTO_INCREMENT在复制前后再次核对。没有兼容视图或旧表写入。

copy返回的Receipt包含完整目标快照SHA及源元数据/行摘要。若COMMIT后端结果无法确认，抛CommitOutcomeUnknown并携带candidate；保留候选和来源，调用只读verifyCommitted检查当前完整快照。它不会重试复制、删库或清理唯一副本。应用仍未开放写入时验证才有意义；一旦已有合法新写入，差异应单独核对，不应自动宣告复制失败。

### 8.2 新增但未运行的ECS用例

WorkbenchMigrationMySqlTest使用workbench.migration.target/source两份已绑定ECS的配置，真正分离V37三表来源与完整29表目标，覆盖23列与未知时间、精确JSON、uint64 ID、高水位、孤儿、原命令幂等、目标后续触发器篡改回滚、未知字段/额外列拒绝，以及只读提交后回读。

AgentWorkbenchServiceTest补充逻辑任务保留、旧scope晚到SDK保存/续租拒绝、CHILD reader跨账号/会话拒绝和超过200个用量事件的完整汇总；原计划、问答、子任务、SDK及进程中断源码已改读新表。所有数据库与进程场景只允许ECS执行，当前仅写完源码。
