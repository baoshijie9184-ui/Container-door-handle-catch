# 公共持久化实现状态

2026-11-06：当前为 29 表候选的源码实现阶段，尚未完成 ECS 建库、迁移和业务验收。旧版 `operation_job/operation_item/coordination_state` 方案已撤回，现行建表来源为 `sql/mysql/compact/baseline/`；边界依据见 [公共持久化评审](review-runtime-boundaries.md)。

## 已接入的公共机制

`workflow_instance` 保存注册类型的请求身份、流程状态、领取令牌与版本；载荷采用明确版本的协议。`scheduled_plan` 保存周期计划。`audit_event` 保存只追加的事件与不可变证据。`runtime_state` 保存有明确命名空间和范围的状态、检查点与事务锁。

已开展对话输入、报告命令与投递、模型配置操作、技能下载、额度账户/流水与个人申请、记忆治理、来源导出、操作/文件交付审计、账号关联审计、工作区、模型文件治理及人工确认的代码适配。工作台仅部分状态已接入，仍有旧表查询。这不表示所有旧表访问已经清理完成。旧建表脚本和局部复制脚本不能作为新库的完整初始化入口。

运行日志事件的 `owner_user_id/journal_run_id` 通过复合外键关联同用户的 `agent_run`，拒绝跨用户或不存在的运行引用；不能仅凭运行编号相同追加事件。

消息执行关联、附件切点和上下文来源已改为独立 `audit_event` 证据与 `chat_message` 当前投影：投影通过账号和证据 ID 引用保留事实；删除消息、会话或用户不删除原证据，修改当前会话编号也不改写历史身份。V44 没有记录发生时间的旧来源保留 NULL，不能以导入时间或消息时间冒充。该切片包含在 11 月 6 日 01:26 的源码编译中，双库复制和业务行为仍待 ECS 验证。

工作区永久 fork 回执已进入 workflow，当前子会话只保存投影。迁移时对全部非 fork 会话字段先快照后核对，并显式保留原 `updated_at`，防止自动更新时间被迁移覆盖；详见 [工作区迁移](compact-workspace-migration.md)。报告确认没有来源创建时间，迁移保留 NULL，结构检查与完整尾对账见 [报告历史迁移](compact-report-migration.md)。

## 模型配置与永久状态

| 旧记录 | 目标 | 保留要求 |
| --- | --- | --- |
| `agent_model_configuration` | `llm_configuration` | 原 revision、请求摘要、配置正文及两份密文；加密用途和 revision 关联不变 |
| `agent_model_config_control` | `runtime_state` / `MODEL_CONFIG_CONTROL` | 唯一全局生效指针与递增版本计数；已有配置缺控制记录时拒绝初始化 |
| `agent_model_revoked_key` | `runtime_state` / `MODEL_KEY_REVOCATION` | 供应商、密钥指纹、首次撤销者与请求、记忆端传播状态；不设 TTL |
| `agent_model_config_command` | `workflow_instance` / `MODEL_CONFIG_COMMAND` | 操作者范围内的永久幂等回执，原大小写语义与动作/目标冲突判断 |
| `agent_model_json_probe` | `workflow_instance` / `MODEL_JSON_PROBE` | 同配置/请求只创建一次，结果未知时保留 STARTED，不自动重新请求供应商 |

`ModelConfigurationService` 的事务明确采用 READ_COMMITTED。`startProbe` 还核对返回的 workflow ID 是否由本次创建；共用存储在唯一键竞争后返回已有记录，不构成再次调用供应商的许可。外部检查在开始记录提交后调用，完成结果另行提交。

`copy/26-model-configuration.sql` 要求迁移执行器明确提供来源库和实际时间偏移，原密文逐字节核对。旧探测没有保存操作者和完成时间，迁移保留 NULL；只有带准确旧来源标识的历史终态允许缺少完成时间，新记录仍须填写。源配置创建者缺失而无法确定探测归属时停止迁移，不指定默认用户。目标 `updated_at` 表示本次导入时间，不冒充旧事件发生时间。

同一事务中的复制尾校验核对数量、身份、字段、摘要和时间；失败时执行器必须在同一连接上回滚。尚未实现完整迁移编排和整库恢复验证，不能直接在活动业务库执行局部脚本。

## 数据库保护与适用边界

`35-runtime-guards.sql` 禁止删除模型控制和撤销记录，禁止改写其身份或把撤销恢复为未撤销。`36-identity-guards.sql` 在账号绑定内嵌后保留原绑定外键的删除及主键修改限制：历史空绑定也受保护，历史标记不能清除、绑定版本不能倒退。

`38-quota-guards.sql` 防止通过删除企业账户、改变身份或减少未核实计数清空旧调用的不确定用量。`37-audit-guards.sql` 保证检测模型日志具有具体模型引用，其他审计类型不能占用此引用。模型引用采用普通列，保留旧表的主键更新和删除级联；MySQL 不允许用生成列实现该更新级联，也不允许对此级联列直接添加 CHECK。[MySQL 外键限制](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html)、[CHECK 限制](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html)

审计服务采用追加写入；检测模型操作日志延续原来随模型删除级联的生命周期，这是明确的例外，不影响其他审计类型。账号关联、调用、审批、文件交付等历史不通过该模型外键删除。

`39-workflow-guards.sql` 限定 `chat_action_session_id` 只属于旧聊天动作协议，由普通列外键保留会话改名/删除级联。旧聊天动作当前权限跟随实际会话拥有者，历史操作者快照不充当授权依据。公共生成器现已包含十个保护触发器。

触发器只能约束普通 DML；应用数据库账号必须没有 DROP、ALTER、TRIGGER 权限。TRUNCATE 不触发 DELETE 触发器，管理员权限和备份回滚仍需单独管理。源码生成器显式注册上述保护文件，CLI 输出使用 DELIMITER，JDBC 夹具按 `$$` 分隔；缺少保护文件或夹带非预期 DDL/DML 时拒绝生成。

## 验证与剩余工作

源码构建只证明建表清单、约束引用和制品能生成，Java `test-compile` 只证明代码可编译。新增模型配置迁移、并发探测、技能跨用户归属和账号历史保护用例均留待 ECS 实际执行；H2 不作为 MySQL 触发器或并发行为的通过依据。

2026-11-06 02:29:35，最新 [clean test-compile 08](../../work/schema-reduction-20261105/compact29-test-compile-08.log) 的十二个模块全部成功，耗时 44.808 秒，显式跳过测试；[源码指纹回执](../../work/schema-reduction-20261105/compact29-source-verification-20261106-08.json)记录 838 个源码、资源及 SQL 文件的摘要。它覆盖工作区、模型文件、报告双库、人工确认、Unicode 历史字段回读及服务器报告/聊天/记忆测试接线。先前 06 在服务器旧 Mapper 引用处失败，已修复；07 与随后包含新增改动的 08 均成功。这些编译记录不表示 MySQL/Kafka、迁移、权限或并发用例已执行。

[建表源码制品 08](../../work/schema-reduction-20261105/compact29-source-build-08/catalog.json) 包含 29 表和十个触发器，workflow/scheduled_plan/audit 的框架资源与 baseline 定义静态一致。报告复制作者重复生成结果一致；工作区原时钟修复与报告 76 列结构清单均经独立静态复核。实际 DDL、完整数据迁移与恢复仍无本轮运行结果。

额度的运行协议和页面边界见 [LLM 模型管理与额度持久化](compact-llm-quota.md)，历史迁移见 [V64 迁移](compact-model-budget-migration.md)；真实双库夹具的变化见 [研究导出与记忆治理](../研究导出与记忆治理双库迁移验收-20261106.md)。原来的逐表归并登记已同步当前历史记录的实际目标位置，但它仍不能证明数据已迁移。

仍需完成上下文/MCP、工作台及检测创建/执行/身份治理等剩余旧表访问，完善未知用量的人工核对协议、完整初始化与复制编排，完成当前源库逐列及文件核对、业务并发与恢复验收。工作区、模型文件和人工确认新增源码已编译，仍须 ECS 验证，不能直接视为交付。整库交付前必须确认应用仅访问目标结构、实际表数不超过 30，并保存可用回滚证据。

`script/schema/inventory_compact_adoption.py` 提供可重复的 Java/Mapper 字面 SQL 清单，额外检查已撤回候选表名；它不执行应用或数据库。11 月 6 日编译 08 后再次扫描 465 个文件仍发现 39 个旧表名，已撤回候选表名命中为零，[清单](../../work/schema-reduction-20261105/compact29-adoption-20261106-03.json)。此清单不覆盖动态 SQL、Python worker 或初始化脚本，不能用命中数降为零替代完整运行验收。
