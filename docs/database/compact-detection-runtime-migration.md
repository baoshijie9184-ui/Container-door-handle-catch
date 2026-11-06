# 检测创建、派发和执行回执的紧凑存储

2026-11-06，源码阶段。未启动 ECS、连接数据库、复制业务数据或执行测试。本切片不新增业务表，使用现有 `workflow_instance` 与 `runtime_state`，完整目标仍由29表契约与 baseline 管理。

## 数据归属

| 原表 | 原列数 | 新协议 |
| --- | ---: | --- |
| detection_creation_owner | 1 | runtime_state / DETECTION_CREATION_OWNER，完整 owner 锁 |
| detection_creation_job | 22 | workflow_instance / DETECTION_CREATION，批准内容、任务及原传输执行权 |
| detection_creation_object | 14 | workflow_instance / DETECTION_TRANSFER，每张原图一个目标与一次 PUT 的永久凭据 |
| detection_creation_review | 19 | workflow_instance / DETECTION_TRANSFER_REVIEW，每次只读检查和用户处置一个实例 |
| detection_execution_command | 10 | workflow_instance / DETECTION_COMMAND，CREATE/RETRY 的永久请求回执 |
| detection_dispatch_outbox | 16 | workflow_instance / DETECTION_DISPATCH，原消息的独立可重送发送实例 |
| detection_worker_receipt | 10 | workflow_instance / DETECTION_WORKER，不可自动重领的推理执行凭据 |
| **合计** | **92** | **两张现有共享表，不建立兼容视图** |

批准创建、原图上传、只读核对、业务命令、消息发送和推理是六个独立生命周期，不因为共表而合为同一状态。身份治理的当前绑定、历史映射及核对报告属于另一个切片，不能把本切片完成视作所有检测旧表均已解除。

## 字段与协议

owner/actor、任务或创建命令、dispatch/file、顺序、状态、修订、fence、执行令牌、租约和时间继续保存在有类型的普通列。每类实例有固定 kind、唯一范围和窄读写方法。原外部 event/command 最长128字，不能塞入64字的内部 workflow_id；必要时使用固定前缀和摘要生成内部键，原标识另存并回验，碰撞拒绝而不覆盖。

`DetectionExecutionPersistence` 使用封闭的 `CommandV1` 和 `DispatchV1`；创建部分使用 `JobV1`、`TransferV1`、`ReviewV1`。数据库 CHECK 校验精确字段集合、类型、状态、摘要及原唯一范围。共享 JSON 保存的是原来已有的批准预览、消息、传输清单和核对证据，正文以原字符串保留；不会重排其内部键、空白或数字，再换一个摘要冒充原字节。没有任意 SQL 字段或可扩展 Map 的写入入口。

`DetectionCreationService`、Transfers、Review 的读取投影直接来自新表固定列/登记的字段；这是原生新结构 SQL，不是旧 SQL 改写器或数据库兼容视图。创建命令的权限、模型/文件版本检查、先记上传目标再 PUT、旧执行者令牌检查、人工 ABANDON/FINALIZE 和 UNKNOWN 处理仍分别保留。

发送实例允许在租约过期后重发**同一个事件**，须由永久 worker 凭据防止重新推理。worker 和原图上传的令牌没有可回收租约，RUNNING/UPLOADING 的未知结果不能因时间过去而自动再执行。Python `detection_worker_receipts.py` 与 Java读取共用同一个 `DETECTION_WORKER` 协议，不再访问旧表。

原 worker 无数字账号，target owner=0 且 actor=NULL；不能补造用户。旧上传也无独立账号，能与创建命令核实时继承该命令账号，历史孤儿保留 owner=0、actor=NULL 和精确旧来源。普通应用新写入仍须有真实账号，历史留存不授予访问权限。

## 复制与原值保护

`script/schema/author_detection_runtime_copy.py` 是本地源码构建器，不连接数据库。它生成：

- `sql/mysql/compact/copy/47-detection-runtime.sql`：七来源92列的显式复制与逐列核对。
- `doorhandle-module-detection/src/test/resources/db/compact/detection-runtime-source.sql`：由 V42/V43/V50/V51 原始声明还原的历史源夹具，不能用于应用启动。

复制只允许已核验的两个不同 ECS 隔离 schema。外部编排必须先停止源写入并备份，提供真实源时区偏移和两张未显式声明默认排序规则表的实际 collation；SQL中的确认变量不是停写证明。未知列、列序/类型/NULL/默认值/排序规则变化、未知唯一范围、触发器或外键都先停止，不过滤来源行。

每一列均有明确目标表达式，复制后逐行回读比较。原数字游标进入 legacy_key，不强行充当共享自增号；保留大于 JavaScript 精确整数上限的原编号。原消息/证据字符串、SHA、NULL、文件/事件/任务身份和原源 AUTO_INCREMENT 水位均核对；源行摘要和元数据在尾部再次验证。源始终只读，错误在同一连接回滚整个复制。

时间按有依据的固定 offset 转为 UTC，校验六位微秒及可逆偏移。owner 原来没有任何时间，导入的 created/updated 仍为 NULL；原上传没有 created_at、原命令没有 updated_at/完成时间，也保留精确旧来源下的 NULL 例外。已 CANCELLED 且 owner_token=NULL 的历史创建命令可能仍有旧 lease，不丢弃该原字段。未知的完成时间不拿迁移时间或 updated_at 补造。

## 待在 ECS 执行的验证源码

`DetectionExecutionApiImplTest`、`DetectionDispatchOutboxTest` 已改为显式 ECS 身份门禁和真实完整29表 DDL，移除旧三表 H2 伪装。覆盖事务回滚、两次确认竞争、旧资源版本、未知先前推理、同消息重送以及过期旧发送者不能覆盖新发送结果。

`DetectionRuntimeCopyMySqlTest` 使用两个预置空 schema，检查92列复制、原字节、六位时间、无创建时间、无原账号的孤儿、永久令牌、大整数旧编号、未知列/坏摘要整笔回滚和重复复制拒绝。Python worker 的原 MySQL 专项也改为完整紧凑 DDL，保留双 worker 单次执行、断点重启、丢提交确认、结果摘要保护和不同任务复用 eventId 的拒绝。

这些都是待执行用例，不构成迁移成功证明。统一源码编译、ECS运行/恢复验收、整库初始化与切换由主流程完成；旧库及回滚材料在逐列/文件/业务验收通过前不能清退。
