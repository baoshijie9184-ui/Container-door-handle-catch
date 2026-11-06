# 核心实体空库复制候选

状态：`AUTHORED_NOT_EXECUTED`。脚本和 ECS 隔离迁移用例已编写，未连接数据库、未执行迁移或测试，也不表示当前线上结构已经核实。它属于当前 29 表候选，不修改表数或部署方案。

`sql/mysql/compact/copy/10-core.sql` 将 13 张来源表复制为 12 张目标实体，明确列出 260 个来源字段。独立复查工单使用相邻的 `11-duplicate-ticket.sql`，不重复复制。源字段依据为已保存的 `core-column-map.json`、`schema-inventory.json`、2026-10-14 的 `image_detection_data` DDL，目标依据为当前 `baseline/10-core.sql`。这些历史证据必须在 ECS 验收时与实际结构对照。

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

脚本仅对清单中已声明为可选的历史新增列提供固定分支：列存在时复制，缺失时写 NULL，只有缺失的 `assignment_identity_revision` 写 0。没有 `COALESCE` 替换真实原值，没有姓名回填或生产 SQL 改写。DATETIME 和 DATE 在数据库内直接复制，不做 UTC/北京时间转换；模型训练完成时间等既有本地时间语义也保持原值。JSON 文本列按原字节核对，不重序列化、不去空格。

原 `detection_task.session_id` 是 `VARCHAR(64) utf8mb4_unicode_ci`，当前目标是 `VARCHAR(128) utf8mb4_bin`。这项已知差异单独声明；复制前必须对来源 chat_session 作字节相等检查。旧外键能以不区分大小写方式匹配、但原字符串不同的数据会停止复制，等待可追溯的解决方案，不自动改拼写。原会话删除 SET NULL、主键更新 CASCADE 的动作由最终 `40-relations.sql` 恢复。

外键动作比较只把 InnoDB 中等价的 `NO ACTION` 与 `RESTRICT` 视为同一种立即拒绝行为；省略 ON UPDATE/ON DELETE 时的默认动作也属于这一情况，其他动作不得替换。[MySQL 8.4 外键说明](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html)

复制顺序和事务边界如下：

1. 在停写且已确认恢复路径的迁移窗口，使用不同的源、目标 schema；创建全部目标表并安装 `35-runtime-guards.sql`、`36-identity-guards.sql`，暂不安装 `40-relations.sql`。迁移连接保持 `FOREIGN_KEY_CHECKS=1` 和严格 SQL 模式。
2. 验证 13 张源表及 12 张目标表、列类型/NULL/默认值/字符集/排序规则、原主键和唯一键、已知外键动作及目标空库状态。未知源列、缺失必需列、类型变化、生成列、新触发器/检查约束或未知外键均拒绝。原有引用及稳定用户 ID 的孤儿也拒绝；不删除、过滤或修改源行。
3. 捕获 11 个自增表的真实下一 ID，不能用 `MAX(id)+1` 替代。目标 `ALTER TABLE ... AUTO_INCREMENT` 在行事务之前执行，保留已删除高 ID 的水位。这些 DDL 隐式提交，失败后不宣称水位已回滚；model_management 的原 model_id 不是自增列。
4. 在同一连接内开始行事务，显式复制 12 个实体。原 ID 为 0 时也原样保留。每个目标表核对行数，并按原主键 LEFT JOIN 对全部写入列做 NULL-safe 比较；文本按 BINARY 比较，漏行和缺值都会失败。最后再次核对账号绑定历史数量及自增水位，再提交。
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

9 个已编写用例覆盖全部核心实体、空绑定/版本零、JSON 文本/日期/历史空值、删除高 ID 后的水位、显式 ID 零、可选历史列缺失、未知列和类型变化拒绝、孤儿绑定拒绝、会话字符串差异拒绝、目标中途篡改后全事务回滚，以及装配关系后的删除/更新动作。以上均为待执行测试，不是通过记录。

本脚本没有迁移 `agent_memory_preference`、`detection_identity_binding` 或内容/共享流程/运行态领域；它们不在这份 260 列核心清单中，源表保持原样，仍需各自完整持久化与复制契约。编写器 `script/schema/author_core_copy.py` 只读取已保存证据并输出显式 SQL 和历史源夹具，不访问数据库。最终验收还包括实际源 SHOW CREATE、全域复制顺序、跨域关系、逐行对账和恢复演练。
