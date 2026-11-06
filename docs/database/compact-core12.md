# 核心 13 表实现候选

这是当前 29 表候选中的核心领域切片。`sql/mysql/compact/baseline/10-core.sql` 现在定义 13 张专用实体表，新增保留独立复查工单；本文件沿用原文件名以保持已有链接。源库没有修改，尚未部署或完成 ECS 验证。

| 来源 | 目标 | 转换 |
| --- | --- | --- |
| users + account_employee_binding | users | 保留账号 ID；按明确 user_id 内嵌 employee_id、binding_version，旧绑定行存在时设置 binding_history_present，包括空绑定和版本零 |
| employee | employee | 原字段、员工 ID、版本与部门关系 |
| organization_department | organization_department | 原 ID 与唯一名称 |
| device_management | device_management | 原设备字段与版本 |
| device_usage_record | device_usage | 仅改表名，保留全部领用/归还区间与历史快照 |
| device_capture_alert | device_alert | 仅改表名，保留告警确认/解决状态 |
| model_management | model_management | 原 model_id、验证发布状态及实测指标 |
| detection_work_unit | detection_work_unit | 原工作单元及可选 V19 字段；没有原值时不捏造项目关系 |
| detection_task | detection_task | 原任务与稳定身份字段；不含历史汇总类型 |
| detection_work_unit_image | detection_input | 保留原 ID/image_id/工作单元、对象位置、运行及状态；新增可空 content_asset_id/content_version，只有可靠映射时才填充 |
| detection_quality_report | quality_report | 原报告 ID、草稿、冻结提交、独立审批与修订关系 |
| detection_duplicate_ticket | detection_duplicate_ticket | 独立专表，原 20 列与 ID/NULL/JSON/历史引用/时间逐项保留，版本 CAS、ticket 唯一键与分派统计继续直接访问 |
| image_detection_data | historical_detection_summary | 独立历史 ID、16 个原字段、INT 计数与 DECIMAL(5,2)；不转成当前任务 |

直接改名的实体注解、Mapper/XML、JDBC 查询和对应测试引用已同步。Java 类型与 HTTP API 保持兼容。旧迁移文件作为源证据不修改；新目标采用空库完整复制，不使用兼容视图或运行时 SQL 重写。

`detection_image_fingerprint` 不在核心 13 张表里。内容身份迁到 `content_asset` 的 DETECTION_IMAGE 类型和 `content_revision`，最新检测投影迁到 `runtime_state` 的 DETECTION_FINGERPRINT namespace。hash 统一小写，并在迁移时检查归一化冲突；原字符串 owner 原样保留在严格 V1 来源信息中，不猜测数字账号。原 ID 只是来源标识，不能充当内容或流程主键。复查工单中的原始摘要与人员证据不随此投影归一化而改写。

普通检测任务不用类型过滤拦截器。历史聚合与当前任务即使数字 ID 相同，CRUD 也操作独立表。`Core12PersistenceMySqlTest` 使用真实核心建表脚本和历史 Mapper XML，覆盖此隔离以及同内容多次输入的独立状态；测试只接受明确绑定 ECS 的空验证库配置，本轮只编写，未执行。

逐列清单位于 `work/schema-reduction-20261105/core-column-map.json`，外键草稿位于 `core-relations.sql`。保留原设备领用外键的级联删除语义；若要改为历史保留策略，需要另作业务变更，不能在减表迁移里悄悄替换。此前没有外键的报告/任务、输入/工作单元关系仅列为待孤儿数据审查的候选。

复查工单的独立复制脚本已补齐原 20 列核对和源 AUTO_INCREMENT 高水位保留，具体边界见 [独立复查工单](compact-duplicate-ticket.md)，尚未执行。其余 12 个核心实体的 [空库复制候选](compact-core-copy.md) 已补齐 13 张来源表、260 个来源列的显式复制/比对、绑定历史及自增水位保护，并编写已核验双 schema 下的 ECS 迁移用例；均未运行。仍需完成共享 workflow/content/runtime 等领域的整库编排、未纳入这份核心逐列清单的记忆偏好和身份绑定适配、新写入回滚方案、当前 ECS SHOW CREATE 对照以及恢复数据后的逐行校验。2026-10-14 的历史汇总 DDL 不代表当前线上结构已被核实。遇到未知源列、归一化冲突或约束不兼容时停止复制，不过滤源行。
