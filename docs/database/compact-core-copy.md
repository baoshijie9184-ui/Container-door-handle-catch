# 核心实体空库复制候选

状态：`SESSION_HISTORY_FIX_PENDING_ECS`。模型内部编号、四表 24 处声明差异和领用历史保全的现有 23 项核心隔离用例已在 #366 全部通过；该轮整库复制在核心来源外键检查处停止：脚本要求 `detection_task.session_id` 的父外键，而 #341/#366 冻结来源均未声明此关系。本轮补齐明确的无外键来源分支及会话历史保全，新增回归和完整迁移、双恢复待 ECS 统一验收；正式库尚未切换，目标仍为 29 张表。

`sql/mysql/compact/copy/10-core.sql` 将 13 张来源表复制为 12 张目标实体，明确列出 261 个可识别来源字段（含可选历史 `model_management.id`）。独立复查工单使用相邻的 `11-duplicate-ticket.sql`，不重复复制。源字段依据为已保存的 `core-column-map.json`、`schema-inventory.json`、2026-10-14 的 `image_detection_data` DDL，以及 #341 冻结来源备份中的模型表结构；目标依据为当前 `baseline/10-core.sql`。

| 来源 | 目标 | 保真要求 |
| --- | --- | --- |
| organization_department、employee、device_management、model_management、detection_work_unit、detection_task | 同名专表 | 原 ID、业务字段、NULL、版本和时间值逐列复制 |
| users + account_employee_binding | users | 按明确的 user_id 关联；不按姓名、手机号或员工编号推测 |
| device_usage_record | device_usage | 保留设备和员工快照及领用区间 |
| device_capture_alert | device_alert | 保留确认、处理信息及设备删除后的 SET NULL 行为 |
| detection_work_unit_image | detection_input | 保留工作单元、图片、对象 key 和运行状态；两个新内容引用字段暂为 NULL |
| detection_quality_report | quality_report | 保留报告、正文、来源 JSON 文本、审批与修订字段 |
| image_detection_data | historical_detection_summary | 原 16 列，原始整数、DECIMAL(5,2)、空值和路径；不转成任务 |

账号没有旧绑定行时，新值为 `employee_id=NULL / binding_version=0 / binding_history_present=FALSE`。存在旧绑定行时，保留原 employee_id 和 version，并设置历史标记；即使原 employee_id 为 NULL、version 为 0，历史标记仍为 TRUE。目标 `36-identity-guards.sql` 保持原绑定行对用户删除和改 ID 的限制，并阻止清除历史或版本倒退；目标员工外键维持 RESTRICT。

模型表准入两种已知结构：原 `PRIMARY(model_id)` 无内部编号版本，以及 #341 观测到的 `id BIGINT AUTO_INCREMENT PRIMARY KEY`、`UNIQUE(model_id)` 版本。后者的 12 行来源数据分配水位为 46。目标仍以 `model_id` 作为业务主键，另设唯一自增 `id` 保存内部行编号；存在来源 `id` 时逐行复制（包括 0）并保留真实分配水位，无此列时只生成新的内部编号，不冒称原值。模型 API、外键及历史引用继续使用 `model_id`。未知 `id` 类型或不同键结构仍拒绝，不调用会删除旧 `id` 的历史 V2 迁移。

四表的已观测声明保存在 `script/schema/compact_core_source_variants.json`，只有完整匹配该变体或原 schema 声明的来源才能复制；不能任意混合可空性、宽度、默认值和键约束。实际员工表没有 `id_card`，该分支目标写 NULL，原带此列来源仍逐值复制。实际 `users.role` 默认值为 `OPERATOR`，复制保留真实行值，不映射为其他角色；新账号的目标默认仍为 `INSPECTOR`，登录权限另按已有显式治理规则处理。

共同目标为历史可空员工字段、设备字段和领用快照保留 NULL；`employee.hire_date` 使用 `VARCHAR(20)` 保存实际源文本，原 DATE 来源保留其 `YYYY-MM-DD` 表示；`device_usage.remarks` 扩至 500 字符，防止原 500 字符字段被截断。员工部门/类型仍保留较宽的目标 100/50 字符，以兼容原 schema 来源。其余 DATETIME 在库内直接复制，不做 UTC/北京时间转换；模型训练完成时间等既有本地时间语义也保持原值。

来源键型检查同步区分实际员工无身份证唯一键、设备无序列号唯一键、设备员工关系 `ON UPDATE CASCADE`、领用表无外键的结构。序列号目标唯一约束保持，重复序列号会触发目标拒绝并回滚；如果实际数据冲突，须单独处理，不能丢行或忽略错误。

**用户已确定保留领用历史**：目标 `device_usage` 不再声明设备/员工父外键。删除或修改父对象主键后，领用原记录、原 `device_id`/`employee_id`、全部快照和时间字段均保留，不执行级联删除或 SET NULL。已观测无外键来源中的历史悬空 ID 也原样迁入；原有外键来源仍须满足其声明的源关系。当前设备的员工关联采用 `ON DELETE SET NULL / ON UPDATE CASCADE`，与已观测来源一致。新业务领用记录继续由服务事务校验当前设备和员工，历史展示读取保存的快照，不用当前父对象覆盖旧证据。

脚本仅对清单中已声明为可选的历史新增列提供固定分支：列存在时复制，缺失时写 NULL，只有缺失的 `assignment_identity_revision` 写 0；模型内部 `id` 的 NULL 输入由目标自增机制分配，按上段单独核验。没有 `COALESCE` 替换真实原值，没有姓名回填或生产 SQL 改写。JSON 文本列按原字节核对，不重序列化、不去空格。

原 `detection_task.session_id` 是 `VARCHAR(64) utf8mb4_unicode_ci`，当前目标是 `VARCHAR(128) utf8mb4_unicode_ci`。#341/#366 实际来源有此列但没有会话父外键；这一路径原样保留历史会话 ID，包括已删除会话的 ID、与现存会话仅大小写不同的字符串及 NULL，不推测父记录、不自动改拼写。复制后的逐列 BINARY 读回仍要求文本原字节一致。

另一已知来源版本声明 `session_id → chat_session.session_id ON DELETE SET NULL / ON UPDATE CASCADE`。该版本仍须完整匹配原单列、同 schema、父表/父列和动作，并保持既有的逐字节父引用检查；缺父记录或仅大小写不同的关联会停止复制。这个来源分支不会使其他外键变为可选。

**目标统一保留检测任务的历史会话 ID**：`40-relations.sql` 不再为此字段添加父外键，删除会话或修改会话主键均不改写任务及其原 `session_id`。对当前实际无外键来源，这是保留旧行为；对上述有外键来源，这是明确改为保留历史，目标不再执行原 SET NULL/CASCADE。业务创建仍原样保存可空会话 ID，任务读取不依赖会话 JOIN，不新增父存在前置条件。

外键动作比较只把 InnoDB 中等价的 `NO ACTION` 与 `RESTRICT` 视为同一种立即拒绝行为；省略 ON UPDATE/ON DELETE 时的默认动作也属于这一情况，其他动作不得替换。[MySQL 8.4 外键说明](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html)

复制顺序和事务边界如下：

1. 在停写且已确认恢复路径的迁移窗口，使用不同的源、目标 schema；创建全部目标表并安装 `35-runtime-guards.sql`、`36-identity-guards.sql`，暂不安装 `40-relations.sql`。迁移连接保持 `FOREIGN_KEY_CHECKS=1` 和严格 SQL 模式。
2. 验证 13 张源表及 12 张目标表、列类型/NULL/默认值/字符集/排序规则、原主键和唯一键、已知外键动作及目标空库状态。未知源列、缺失必需列、类型变化、生成列、新触发器/检查约束或未知外键均拒绝。原有当前引用及稳定用户 ID 的孤儿仍拒绝；已观测无外键领用来源的历史父 ID、无会话外键来源的任务历史 `session_id` 按上述分支保留。不删除、过滤或修改源行。
3. 捕获原 11 个自增表的真实下一 ID；模型来源存在内部 `id` 时另外捕获它的水位，不能用 `MAX(id)+1` 替代。目标 `ALTER TABLE ... AUTO_INCREMENT` 在行事务之前执行，保留已删除高 ID 的水位。这些 DDL 隐式提交，失败后不宣称水位已回滚；`model_id` 本身仍不是自增列。
4. 在同一连接内开始行事务，显式复制 12 个实体。原 ID 为 0 时也原样保留。每个目标表核对行数，并按原主键或模型的稳定唯一 `model_id` LEFT JOIN 对全部来源列做 NULL-safe 比较；文本按 BINARY 比较，漏行和缺值都会失败。无来源的模型内部编号只要求目标生成，不与不存在的原值比较。最后再次核对账号绑定历史数量及自增水位，再提交。
5. 完成其他领域复制，包括 chat_session，再安装完整 `40-relations.sql`。若任何关系安装失败，不允许切流。这一步属于整库编排，并非本脚本已完成的工作；测试中的少量聊天行仅用于验证核心外键，不能代替完整智能体领域迁移。

客户端必须遇到第一条错误立即停止，禁止 `--force`；出错后由同一连接 ROLLBACK 并关闭连接，不能在失败会话上续跑或沿用已改变的会话变量。DDL 保留的候选库状态须废弃或重新确认后重建，源库始终保留。首次切流后的新写入回退/恢复方案仍需整库设计和 ECS 验收。

源触发器核验需要可见性，不能把无权限时看不到元数据当作没有触发器。脚本要求迁移账号对源 schema 已有直接的 `SELECT` 和 `TRIGGER` 权限；后者用于查看完整触发器定义。角色或全局权限不替代这个明确门禁，工具不会自动扩权。生产应用账号仍不应拥有 ALTER、DROP、TRIGGER 等迁移权限。

迁移用例位于 `CoreCopyMigrationMySqlTest`，夹具位于 `CoreCopyMySqlFixture`。两份配置必须已存在，分别通过 `EcsIsolatedMysql` 的 Linux、machine-id、ECS 实例 ID、隔离端口、server_uuid、datadir、账号和库名前缀核验；并且属于同一隔离 MySQL 实例、不同的空验证库。夹具不会 CREATE/DROP DATABASE 或 GRANT；只在核验后的空库中创建本次记录的表，结束时删除这些夹具表。发现不属于本次的对象会拒绝清理。

全部开发完成、进入 ECS 验证阶段时，使用已有受控测试入口，并提供以下 JVM 参数（配置路径必须是该 ECS 项目 work 目录下的绝对路径）：

```text
-Dtest=CoreCopyMigrationMySqlTest
-Ddoorhandle.core.copy.source.config=/项目/work/既有来源验证库配置.json
-Ddoorhandle.core.copy.target.config=/项目/work/既有目标验证库配置.json
```

现有 23 项由 #366 执行通过，覆盖核心复制、模型内部编号/水位及真实四表声明与领用生命周期。本轮新增 6 项：无会话外键的历史/大小写/NULL 原值保全、会话删除与改键后任务整行不变、有外键来源仍拒绝孤儿、拒绝未知外键动作、无会话外键不豁免其他关系、历史会话 ID 被篡改时整段回滚，共 29 项。已观测夹具不再补造来源不存在的会话外键，原有外键夹具继续保留；本轮新增及调整范围待 ECS 统一验证。

本脚本没有迁移 `agent_memory_preference`、`detection_identity_binding` 或内容/共享流程/运行态领域；它们不在这份 261 列核心清单中，源表保持原样，仍需各自完整持久化与复制契约。编写器 `script/schema/author_core_copy.py` 只读取已保存证据并输出显式 SQL 和历史源夹具，不访问数据库。最终验收还包括实际源 SHOW CREATE、全域复制顺序、跨域关系、逐行对账和恢复演练。
