# 质检报告历史迁移

2026-11-06，源码候选。尚未运行 ECS 测试或迁移业务数据。目标业务表仍为 29 张，以下临时检查表只存在于迁移连接中。

## 数据与时间事实

主表 `detection_quality_report` 先由核心复制迁到 `quality_report`，保留原字段与北京时间墙钟值。`copy/34-quality-report-workflow.sql` 再复制以下七类记录；公共存储的时间按有证据的固定 UTC 偏移转换，不使用客户端机器默认时区。

| 原记录 | 目标协议 | 保留内容 |
| --- | --- | --- |
| `detection_report_command` | workflow / REPORT_COMMAND | 原操作者、请求、摘要及响应原文，供幂等重放 |
| `detection_report_confirmation` | workflow / REPORT_CONFIRMATION | token、审批版本、两个摘要、到期时间、实际使用时间 |
| `detection_report_agent_origin` | workflow / REPORT_AGENT_ORIGIN | 原运行、工具调用、请求与报告版本 |
| `detection_report_outbox` | workflow / REPORT_DELIVERY | 原事件字符串、状态、次数、领取令牌、重试/租约/完成时间及错误码 |
| `detection_report_event_receipt` | workflow / REPORT_CONSUMPTION | 原消费摘要和版本、实际消费时间 |
| `detection_report_audit` | audit / QUALITY_REPORT | 原 ID、操作者、前后状态、原因和快照摘要 |
| `detection_report_event_state` | runtime / REPORT_EVENT_STATE | 原版本水位、末次事件与状态 |

V21 的确认表没有创建或更新时间列。迁移后的 `created_at` 为 NULL；`updated_at`、`finished_at` 仅使用实际记录的 `used_at`，未使用时均为 NULL。不能按有效期倒推创建时间，不能用迁移时间填补。公共约束只对来源精确为 `detection_report_confirmation` 且有旧键的 REPORT_CONFIRMATION 放行缺失时间；新建确认仍须具备创建与更新时间。业务过期判断继续使用真实的 `expires_at`。

V21/V22/V30 的日期字段精度为秒，测试不虚构微秒。每个非空来源时间同时检查转换结果和微秒差值是否等于声明偏移，避免把超出转换范围时原样返回的值误标为 UTC；来源 NULL 保持 NULL。[MySQL 日期转换说明](https://dev.mysql.com/doc/refman/8.4/en/date-and-time-functions.html#function_convert-tz)

## 复制与对账

`script/schema/author_report_copy_checks.py` 从实际 V21/V22/V30 建表与 ALTER 语句生成源结构清单，覆盖主表及七个副表的 76 列、原索引、默认值、排序规则与空值规则；未审阅列、索引变化、触发器或新增约束均阻止复制。源库、目标库必须不同，保持严格 SQL 模式及外键检查；来源账号和元数据读取权限须提前准备。

七类复制均保留数量检查，并逐字段比较已赋值内容。未赋值的普通公共列也必须保持预期 NULL 或默认值；自增游标不冒充旧 ID。字符串采用二进制比较，响应和事件原文不经重新序列化。对应字段的语义仍须由原 DDL、生产读取代码及独立 ECS 用例共同核对，生成器本身不能证明业务正确。

所有业务插入与尾对账在同一事务、同一连接完成。执行器必须遇错停止并回滚，不使用 `--force`；源库只读取。当前脚本只负责这一切片，完整迁移的停写、核心表复制、其他切片顺序与全库恢复仍需总编排。

## ECS 验证入口与当前边界

`ReportWorkflowMigrationMySqlTest` 使用 `ReportMigrationFixture`：源库加载真实八表，目标库加载完整 29 表、十个保护触发器及最终外键。私有配置属性为 `report.copy.source-config` 和 `report.copy.target-config`；两库均须为同一已准入 ECS MySQL 上预置的独立空库，使用 `doorhandle_detection_verify_` 前缀和专用权限。缺少目标配置即拒绝，不回退到业务库或本机库。

源码中的场景包括：原响应重放、消费去重、北京时间展示、用过/未用过确认的缺失时间、十一处历史时间的越界拒绝、零偏移与负半小时时区、源结构变化、七类目标额外字段注入、错误归属和虚构时间、租约回收后旧领取者拒绝回写，以及失败全回滚。普通报告业务夹具只装目标表；历史表只在专用源库中建立。

本地仅编辑、静态检查和 `test-compile -DskipTests=true`。源码生成成功或 Java 编译通过均不能记作这些用例通过；待整体开发完成后按 ECS 运行约定执行并保存实际结果。
