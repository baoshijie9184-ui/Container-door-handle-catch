# V64 旧模型额度迁移

状态：`AUTHORED_NOT_EXECUTED`。源码和 ECS 双库用例已编写，尚未在 MySQL 执行。本文不代表生产迁移、隔离验收或部署完成。保持 29 张目标表，没有新增旧额度专表。

## 来源与字段去向

依据是 `sql/mysql/migration-V64-model-budget.sql` 的四张实际源表，共 33 列。保存的源 inventory 只有 `estimatedRows`；估计为零不能用于跳过导入或校验。源代码对旧开始、结束、策略更新和核对时间使用 UTC `LocalDateTime`，核对时间先转 UTC，导入不加减八小时。

| 源表与列数 | 原字段 | 目标保留方式 |
| --- | --- | --- |
| `agent_model_budget`，8 | `model_id,total_tokens,warning_percent,free_only,expires_at,version,updated_by,updated_at` | `llm_quota` 的 MODEL/TOTAL 账户逐列保留；`owner_user_id=NULL`。目标新增 `created_at` 为本次导入 UTC 时间，不伪称旧业务创建时间。 |
| `agent_model_budget_attempt`，9 | `id,attempt_id,model_id,status,input_tokens,output_tokens,cached_tokens,started_at,finished_at` | 每行一条 `audit_event/LLM_LEGACY_ATTEMPT`，完整 `AttemptV1` 快照，`legacy_source+legacy_key` 保留原表与原主键；原请求编号进入 `request_id`，原状态进入 `outcome`。 |
| `agent_model_budget_observation`，9 | `id,model_id,remaining_tokens,observed_at,source_note,actor_user_id,request_id,request_sha256,created_at` | `MODEL_QUOTA_OBSERVATION`：原主键进入来源键；模型、原 actor、原 request、余额、两个 UTC 时间分别进入审计有类型字段；备注进入 `sourceNote`，保留空白。`content_sha256` 直接保存原 `request_sha256`，不重算。 |
| `agent_model_budget_audit`，7 | `id,model_id,actor_user_id,action_name,version,detail_json,created_at` | `LLM_LEGACY_BUDGET_AUDIT` 完整 `AuditV1` 快照，包括原 action/version 和源 MySQL 输出的 JSON 文本。外层 action 固定 IMPORTED，避免把旧策略审计误认为新命令。 |

源 `detail_json` 是原生 MySQL JSON，原始 HTTP 文本的键顺序或空白从未被源库保留；迁移保留源库仍持有的 JSON 内容和其 `CAST(... AS CHAR)` 表达。快照时间包含六位微秒，SQL NULL 显式保存为 JSON null。快照校验使用整份 JSON 的 NULL-safe 字节比较，缺字段不能冒充空值。

旧 attempt 没有 owner。所有旧 attempt 的 `owner_user_id` 和 `actor_user_id` 均为 NULL，不使用默认主管、用户 0 或时间接近推断归属。旧 observation/audit 的 actor 按原值保留，即使其账号已不在 `users` 中。策略的 `updated_by` 同样保留历史原值。源表不要求这些历史 actor 外键，迁移不补造此限制。

## 账本与未知用量

每条旧 attempt 产生一条 MODEL `llm_usage/IMPORTED_USAGE`，包括完全没有用量数据的行。账本通过 `source_audit_event_id` 引用完整来源快照；`root_operation_id`、`operation_id` 和 `actor_user_id` 均为 NULL。不虚构新工作流、预留记录或已授权供应商调用，不回放供应商请求。

导入消耗为 `COALESCE(input_tokens,0)+COALESCE(output_tokens,0)`，这是已知消耗的下界，保留旧准入累计已知分量的语义。cached 是 input 的分量，不重复加到总额。原分量的 NULL 仍保留，合计为零不能解释为确认免费调用。所有旧消耗只进入 MODEL 账户，不给 USER 账户追扣。

满足以下任一条件的旧 attempt 计入 `unreconciled_legacy_attempts`：

- 状态不是 `COMPLETED`，包含 FAILED/CANCELLED 即使已经有两个用量值和结束时间。
- 缺少 `finished_at`。
- 缺少 input 或 output 任一分量。

有限总额且未核实数大于零时，`QuotaAccountStore` 在修改任何账户前阻断新准入。无限额账户维持已有权限，但保留未知记录与提示。界面 `available_tokens=NULL`；`total-knownSpent-reserved` 只作为 `remaining_upper_bound`，即剩余额度上界，不当作可用额度。概览把旧 attempt 总数、旧 STARTED 数和未核实数纳入显示，原供应商核对记录仍可查看。

`38-quota-guards.sql` 禁止删除、减少未核实数或移动仍有未知历史的账户身份。正常额度策略和新调用计数仍可更新。**人工核实、补差及解除门禁协议尚未实现**；不能直接把计数清零，不自动丢弃未完成历史。

源模型账户按旧 `utf8mb4_0900_ai_ci` 等价关系聚合，所以同一原账户的大小写别名落到同一 MODEL 账户；每条快照仍保留原模型字符串。原 attempt 全局唯一和 observation 的 `(actor,request)` 唯一沿用其原排序规则。导入账本另有 `(account_id,source_audit_event_id,entry_key)` 唯一约束，防止同一来源再次记账。

## 导入门禁和事务

`script/schema/author_model_budget_copy.py` 仅从实际 V64 DDL 生成 `sql/mysql/compact/copy/38-model-budget.sql`，不连接数据库。生成结果需人工审阅后再进入 ECS 验证。SQL 要求：

1. 源、目标 schema 不同，源已停写；目标启用外键检查与严格 SQL 模式。目标账户必须预先持有源 schema 的 SELECT 和 TRIGGER 元数据可见权限。
2. 四张来源均为 InnoDB；33 列类型、NULL、默认值、字符排序、生成属性匹配。未知列、缺列、新触发器、外键、唯一键变化或前缀唯一均拒绝。
3. 每项原 CHECK 必须有且仅有一个已启用的语义组成员。允许列表仅覆盖已知括号输出形式，不能用第二个 total CHECK 替代 warning CHECK。真实 MySQL 对 `CHECK_CLAUSE` 的输出兼容性尚待 ECS 验证；不识别则拒绝，不能静默放宽。
4. 模型孤儿、非原规范状态、负分量、非法原哈希或 signed BIGINT 分量和/模型总和溢出均拒绝，不忽略异常行。旧 cached 列原本没有 CHECK；存在负值时须先审阅真实来源，不能擅自变成 NULL。
5. 目标 MODEL 账户、三种来源审计和导入账本必须为空。已有 USER 账户保持不变。第二次执行会拒绝，不重复收费。
6. 目标已安装 quota 历史保护触发器。插入后逐行 LEFT JOIN 对账，比较来源身份、全部快照、原哈希、UTC 时间、账户计数和账本；固定 kind/scope/period/key 等字段也按字节比较，尾空格不能蒙混通过。

本脚本只有会话临时表 DDL。目标业务表、索引、外键、触发器须在数据导入前单独建立，DDL 不在数据回滚承诺中。数据插入和最终对账处于同一事务，首错在**同一连接**立即 ROLLBACK，然后关闭连接；禁用客户端 `--force`。脚本不更新或删除源表。旧自增 id 完整保存为来源键，目标采用独立审计/账本 id 空间，不续用旧自增序列。

## ECS 验证入口

`ModelBudgetMigrationMySqlTest` 使用 `ModelBudgetMigrationFixture`，需要两个**已有、已核验、初始为空**的隔离 schema 配置：

- `doorhandle.feature.mysql.config`：目标配置。
- `doorhandle.model-budget.source.config`：来源配置。

两份配置都经过 `EcsIsolatedMysql`：Linux、实际 machine-id、ECS 实例标识、专属非 3306 端口、限定测试账号及 schema 前缀、真实 server UUID/datadir 全部匹配。随后再核对源目标是同一隔离实例上的不同 schema。配置位于 ECS 项目 work 内绝对路径，口令不写入文档。夹具不 CREATE/DROP DATABASE、不创建账号或授权；目标读取源的最小所需权限必须已经准备好。

每个用例从空 schema 创建原 V64 四表及真实 compact quota 公共 DDL、关系和保护触发器；测试结束只 DROP 此夹具拥有的表。发现不属于夹具的表则拒绝清理。删除测试表是隔离夹具生命周期，不是绕过生产历史删除限制。

用例包含：33 列保留、原 NULL/UTC/哈希/备注/actor、大小写模型别名、匿名账本、个人账户不追扣、FAILED/CANCELLED 未知门禁、无限额准入、旧概览可见、重复导入拒绝、缺规则以重复 CHECK 替代、源列/排序/类型/触发器变化、孤儿、溢出、目标 JSON/哈希/来源尾空格等破坏的整体回滚、来源 FK 与唯一约束，以及真实空来源也执行门禁。

当前仅完成源码静态审阅和 SQL 生成；没有执行上述测试，没有启动 ECS。统一 Java 编译结果由根任务单独记录。待 ECS 实际验证通过前，不得把这份候选脚本用于正式切流。
