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
| model_management | model_management | 原 model_id、验证发布状态及实测指标；来源存在内部 id 时保留原值及自增水位，model_id 仍为业务主键 |
| detection_work_unit | detection_work_unit | 原工作单元及可选 V19 字段；没有原值时不捏造项目关系 |
| detection_task | detection_task | 原任务与稳定身份字段；不含历史汇总类型 |
| detection_work_unit_image | detection_input | 保留原 ID/image_id/工作单元、对象位置、运行及状态；新增可空 content_asset_id/content_version，只有可靠映射时才填充 |
| detection_quality_report | quality_report | 原报告 ID、草稿、冻结提交、独立审批与修订关系 |
| detection_duplicate_ticket | detection_duplicate_ticket | 独立专表，原 20 列与 ID/NULL/JSON/历史引用/时间逐项保留，版本 CAS、ticket 唯一键与分派统计继续直接访问 |
| image_detection_data | historical_detection_summary | 独立历史 ID、16 个原字段、INT 计数与 DECIMAL(5,2)；不转成当前任务 |

直接改名的实体注解、Mapper/XML、JDBC 查询和对应测试引用已同步。员工入职日期改为文本映射，正常 HTTP 日期仍为 `YYYY-MM-DD`；历史非标准文本可读取和原样保留，只有新增或主动修改日期时校验日历日期。表单将历史原文与日期控件分开显示。旧迁移文件作为源证据不修改；新目标采用空库完整复制，不使用兼容视图或运行时 SQL 重写。

`detection_image_fingerprint` 不在核心 13 张表里。内容身份迁到 `content_asset` 的 DETECTION_IMAGE 类型和 `content_revision`，最新检测投影迁到 `runtime_state` 的 DETECTION_FINGERPRINT namespace。hash 统一小写，并在迁移时检查归一化冲突；原字符串 owner 原样保留在严格 V1 来源信息中，不猜测数字账号。原 ID 只是来源标识，不能充当内容或流程主键。复查工单中的原始摘要与人员证据不随此投影归一化而改写。

普通检测任务不用类型过滤拦截器。历史聚合与当前任务即使数字 ID 相同，CRUD 也操作独立表。`Core12PersistenceMySqlTest` 使用真实核心建表脚本和历史 Mapper XML，覆盖此隔离以及同内容多次输入的独立状态；测试只接受明确绑定 ECS 的空验证库配置；此前固定候选已通过原生数据库检查，新增领用状态与缓存修复仍须统一复验。

逐列清单位于 `work/schema-reduction-20261105/core-column-map.json`，实际来源变体位于 `script/schema/compact_core_source_variants.json`。用户已确定删除员工/设备后保留领用历史：`40-relations.sql` 移除领用的两条父外键，原父编号及快照均保留；已观测无外键来源的历史悬空编号也原样迁入。当前设备的员工关系采用来源的 `ON DELETE SET NULL / ON UPDATE CASCADE`。新建或改变领用关联时，由服务事务校验当前父对象；历史展示不依赖活父表。正式切库仍须完整 ECS 验收。此前没有外键的报告/任务、输入/工作单元关系仍须逐行审查孤儿数据。

复查工单的独立复制脚本包含原 20 列核对和源 AUTO_INCREMENT 高水位保留，具体边界见 [独立复查工单](compact-duplicate-ticket.md)。其余 12 个核心实体的 [空库复制候选](compact-core-copy.md) 识别 13 张来源表、261 个来源列，执行显式复制/比对、绑定历史及自增水位保护。CoreCopy 现有 29 项回归，覆盖内部模型编号、已观测结构、无会话父外键来源及父删除/改键后的历史保全，已在 #381 通过；整轮验收结果见 Jenkins 当前回执。全域复制、约束安装、源/目标双恢复和正式切库仍是独立验收条件。遇到未知源列、归一化冲突或约束不兼容时停止复制，不过滤源行。

## 领用状态与缓存一致性

设备侧解绑显式写入 `employee_id=NULL`，同时关闭匹配的当前领用回执，并由原复合审计事务记录两者。没有匹配回执时只释放当前分配，不改旧历史；重复解绑不改历史归还时间。维修员工分配后设备保持 `MAINTENANCE`，领用回执仍表示未结束的 `IN_USE`；任一设备或回执写入失败均回滚。

改变设备状态的 9 个领用写入口统一失效 `device`、`dashboard` 缓存，沿用 transaction-aware Redis 管理器，在外层事务提交后生效，回滚保留暖缓存。新增 8 项真实 MySQL 检查与 21 项真实 Redis 缓存/事务检查；Redis 测试使用独立合成实例和随机键前缀，不清正式缓存。实现和测试源码已整合，实际通过情况以固定提交 ECS 原始报告为准。
