# 账号员工关联审计迁移候选

状态：`AUTHORED_NOT_EXECUTED`。来源结构、复制脚本和 ECS 双库验证用例已编写，尚未执行数据库迁移或测试。源库现状和历史时间偏移仍须在正式验证窗口核实；本文件不是验收记录。

本切片把 V20 的 `organization_binding_audit` 迁入现有 `audit_event / ORGANIZATION_BINDING`，不增加业务表。当前绑定仍由 `users` 中的关联字段维护，这里仅保存每次关联变更的历史证据，不用审计推断当前员工归属。

## 全部十列的去向

| 真实 V20 来源字段 | 目标位置及语义 |
| --- | --- |
| id | `legacy_source='organization_binding_audit'`、`legacy_key`；载荷 `legacyId` 保存十进制字符串，避免大整数精度丢失 |
| user_id | `owner_user_id`，`resource_type='USER'`、`resource_id` 为该账号 ID 的十进制字符串 |
| username | `BindingV1.username`，保留当时原名，不替换为当前账号名、不 trim |
| actor_user_id | `actor_user_id`，保留原操作人数字 ID |
| actor_username | `BindingV1.actorUsername`，保留当时操作人名字 |
| before_employee_id | `BindingV1.beforeEmployeeId`，SQL NULL 转为显式 JSON null |
| after_employee_id | `BindingV1.afterEmployeeId`，SQL NULL 转为显式 JSON null |
| binding_version | `revision`，有效范围为 1 到 Java Integer.MAX_VALUE |
| action | `action`，精确保留 BIND、REBIND、UNBIND |
| created_at | `occurred_at` 按已核实来源偏移转为 UTC；载荷 `legacyCreatedAt` 另保留原 DATETIME 文本，固定六位小数，本来源小数均为零 |

载荷仅含上表明确的六个证据字段，使用 `OrganizationBindingAuditStore.BindingV1` 读回。审计 `event_id` 使用带来源前缀的确定标识；新的共享 `id` 是全局游标，不能当作原审计 ID。原 ID 并未丢失，但切流时应刷新旧分页游标。

V20 审计表唯一键只有主键 id，没有 `(user_id,binding_version)` 唯一约束，也没有账号、操作人或员工外键。因此重复历史版本全部保留；即使当前用户或员工已不存在，也不据此删除历史行，不补造这些外键。此规则不改变当前账号绑定本身的删除保护。

## 来源和数据门禁

作者脚本 `script/schema/author_binding_audit_copy.py` 只从真实 `migration-V20-account-employee-department.sql` 提取该审计表的 CREATE TABLE，生成 `copy/39-organization-binding-audit.sql` 与独立源夹具。不会执行 V20 中的部门建档、员工 ALTER 或账号绑定 SQL；若作者脚本发现来源字段集合不再是这十列，会停止生成。

复制要求来源与目标是同一 MySQL 实例中的不同 schema，来源停写，目标完整 compact DDL 已安装，目标本 kind 和来源标记为空；其他领域的目标数据可以保留。执行账号需预先具有源 schema 的直接 SELECT 与 TRIGGER 权限，以便查询数据及核对触发器元数据。脚本不创建账号、不授予权限、不修改来源数据。

来源结构检查包括精确列集合与顺序、类型和有符号属性、NULL、默认值、extra、生成表达式、字符排序规则、InnoDB/表排序规则、主键及全部唯一键。发现新增触发器、外键或 CHECK 会拒绝未审阅的结构变化，不能仅因名称相同就接受。

用户、操作人、非空员工 ID 必须为正；版本必须在可读范围内；两名字必须非空且最多 50 个 Unicode 码点，与 utf8mb4 VARCHAR(50) 一致。名字的空格、旧名和补充字符不作归一化。动作按字节匹配，并要求 BIND 为 NULL→员工、UNBIND 为员工→NULL、REBIND 为员工→另一员工；前后值相同或都为空均不接受。异常记录保留在来源并阻止整批迁移，不使用 WHERE 过滤后只复制正常行。

必须显式替换 `__SOURCE_SCHEMA__` 和 `__SOURCE_BINDING_OFFSET__`。时间偏移不能从当前 JDBC 时区、主机位置或其他表推断。脚本同时核验 CONVERT_TZ 的结果和实际秒差，防止超出支持范围时原值未转换却被误当 UTC。若历史来源包含不同偏移，须先制定有证据的分段方案；当前候选不猜测逐行时区。

## 事务与精确对账

目标写入及尾部核对在同一连接、同一事务中进行。除总行数，还按来源 ID 逐行 LEFT JOIN，检查完整载荷及所有公共字段；字符串使用 BINARY 和 NULL-safe 比较，避免尾空格、大小写或缺字段被排序规则掩盖。未使用的请求、运行、模型、数量等公共字段必须保持 NULL。载荷中原本存在的 JSON null 字段若被删除，完整载荷比较仍会报错。

任一错误都必须停止，并在同一连接 ROLLBACK；禁止 `--force`。目标原有其他领域数据不随失败回滚删除。MySQL 自增游标可能因回滚产生空洞，这是共享游标的正常行为，不意味着漏迁来源记录。脚本不 UPDATE、DELETE 或 DROP 源表；再次执行会因目标本 kind 非空而停止，不能重复追加历史审计。

## 待执行的 ECS 验证

`BindingAuditMigrationMySqlFixture` 使用既有 `EcsIsolatedMysql` 门禁，要求两个预先准备的空验证库，均绑定 ECS Linux、machine-id、实例 ID、专用账号、隔离端口、server_uuid 与 datadir。参数为 `doorhandle.binding.mysql.config` 和 `doorhandle.binding.source.config`，配置必须位于 ECS 项目 work 目录。夹具没有本地数据库退路，不 CREATE/DROP DATABASE，不扩权；只记录并清理本次创建的表，发现外来表或视图会停止清理。

目标加载实际 10、20、25、30、35、36、37、38、40 DDL；来源仅加载原 V20 审计声明。`OrganizationBindingAuditMigrationMySqlTest` 已编写以下用例，尚未执行：

- 十列完整复制后，通过真实 Store 读回旧名字、前后员工、版本和北京时间；包括已不存在的用户/员工、重复版本、超过 JavaScript 安全整数的旧 ID、50 个补充平面字符名字。
- 明确的零偏移、正偏移和负半小时时区转换；无效偏移及不能可靠转换的旧日期拒绝。
- 未知列、缺列、字符排序规则、有符号类型、NULL/default/精度、额外唯一键/CHECK/FK/触发器变化拒绝。
- 负身份、无效版本、动作与前后值不符、空名字及大小写/尾空格动作拒绝，不丢弃原行。
- 缺失 JSON null 字段、载荷值/类型改变、来源标记和来源键尾空格、资源/操作人/时间异常导致整批回滚；另有仅篡改第四行、验证此前三行也回滚的场景。
- 来源全行与自增序列不变、目标原有其他领域保留、重复复制拒绝。

统一编译和上述用例需由后续 ECS 验证完成；编译通过不能替代真实 MySQL 约束、触发器和事务验收。
