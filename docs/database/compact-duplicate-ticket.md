# 独立重复图片复查工单

2026-11-05。状态：源码已补齐，**未执行 MySQL、迁移或 ECS 验证**。当前全库候选为 29 张，核心领域 13 张；30 仍是上限，其他表没有为抵消本表而被删除。

`detection_duplicate_ticket` 保留专表。它有独立 `ticket_id`、两侧任务与证据、分派和审批状态，而通用流程表的 owner、请求去重、领取租约并不是这份业务实体的身份。现有生产 Mapper 已直接访问此表，因此保留同名表，既不改名为 workflow，也不创建兼容视图。

依据是 [V15 原始 DDL](../../sql/mysql/migration-V15-detection-fingerprint-work-unit.sql)、[复查服务](../../doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/impl/DetectionDuplicateTicketServiceImpl.java) 和 [核心边界复审](review-core-boundaries.md)。现存表清单的行数为估计值，不能据此证明源表为空；当前线上 `SHOW CREATE TABLE`、排序规则及所有写入入口仍需在正式迁移前核验。

## 字段与独立边界

目标保留原来的 20 列，不把整行放入 JSON，也不新增虚构账号归属。

| 内容 | 原样保留的字段 | 规则 |
| --- | --- | --- |
| 工单身份 | `id`、`ticket_id` | 原数字主键和完整业务唯一键；保留已删除 ID 对应的自增高水位 |
| 图片依据 | `sha256` | 原摘要和大小写保留；按摘要查询，不对摘要强加工单唯一性 |
| 对比双方 | `left_task_id`、`right_task_id` | 保留原字符串，不能把两侧关系变成单个通用 resource_id |
| 历史人员与目录 | `left_employee_id`、`right_employee_id`、`left_folder_name`、`right_folder_name` | 保留空值与原字符串，不根据姓名推测账号 ID |
| 图片证据 | `left_images_json`、`right_images_json` | 保留原 JSON 值及 SQL NULL；不重排、重建或扩充源证据 |
| 分派与人工判定 | `assigned_to`、`comparison_result`、`resolution`、`status` | 分派仍按现有账号字符串查询；结论为 ACCEPT_LEFT、ACCEPT_RIGHT、REDETECT |
| 审批事实 | `approved_by`、`approved_at` | 已解决工单必须有结论、非空审批账号和审批时间 |
| 并发与时间 | `version`、`created_at`、`updated_at` | 非负版本 CAS；保留原 DATETIME 墙上时间，不按公共 UTC 流程表重写历史时间 |

状态集合为 OPEN、ASSIGNED、COMPARING、PENDING_APPROVAL、RESOLVED。新的 CHECK 会拒绝未知状态、非法摘要或不完整的已解决记录；迁移遇到这类源行应停止并查明原因，不能过滤或自动补审批人。

保留原 `ticket_id` 唯一键与摘要索引；状态索引扩展为 `(status, created_at, id)`，服务列表增加同一时间下的 ID 稳定排序；增加 `(assigned_to, status)` 支持本人工作量统计。一个任务对或同一个摘要可以产生不同历史工单，不新增任务对/摘要的唯一约束。

源表没有任务、员工或图片外键。目标继续保留这项历史引用语义，避免删除来源时连带清理工单，也避免通过新 FK 丢弃已有孤儿证据。未来如新增完整关联，需要独立证明数据完整性和删除规则；本轮不猜测关系，也不让表数约束决定业务删除行为。

## 复制与回滚边界

[目标 DDL](../../sql/mysql/compact/baseline/10-core.sql) 与 [复制脚本](../../sql/mysql/compact/copy/11-duplicate-ticket.sql) 只用于新的隔离目标库。来源与目标必须是两个不同数据库，源库停写且仍保留原表；应用最终只访问目标业务库，不将源库作为运行时查询备用。

复制脚本先要求目标空表，检查源表引擎、全部 20 列的类型/空值/默认值/更新属性/字符集/排序规则、原主键与唯一键。V15 未显式声明排序规则，当前候选为 `utf8mb4_0900_ai_ci`；如果当前源列不是同一规则则中止，不能仅因现有值没有冲突就默默改变将来的身份比较语义。未知新增列、外键、CHECK 或触发器也中止，先查明其业务语义。

源 `AUTO_INCREMENT` 高水位先在空目标上预留，该 ALTER 在复制事务之外；之后显式复制每一列，并用行数和 LEFT JOIN 下逐列 NULL-safe 比较核对。JSON 比较按 MySQL 的原生 JSON 表示，字符串按字节、日期不做时区变换。所有源记录都进入目标，包括历史任务已删除、人员字段为空的记录。

执行器必须遇错立即停止，并在同一连接 ROLLBACK，不能使用 `--force`。复制事务失败时目标行回滚；空目标的自增预留可能仍存在，不能把这个目标视为已验收或切流。正式切换前源库保持只读且备份可恢复，应用仍可留在原库；切换后若已产生新写入，则必须使用整库的新写入恢复方案，不能盲目切回旧库。本脚本不删除源数据、不提供未经验证的跨版本双写或反向覆盖。

## 生产访问与待验证项

生产实体、Mapper、主管复查 API 和工作量统计继续直接访问专表。处理结论在原版本和未解决状态下执行条件 UPDATE，竞争失败返回冲突；不会因为解决复查工单而自动改写任务推理结果。说明长度按原 VARCHAR(2000) 限制，审批时间显式使用北京时间。

`Core12PersistenceMySqlTest` 沿用原测试类名，表清单已扩为核心 13 表，并补充专表证据保留、约束及竞争更新用例；本轮只编写。仍需在 ECS 核验实际源 DDL、完整复制/高水位/失败回滚、并发处理与接口权限、索引执行计划以及整库新写入恢复。现有源码未发现工单自动生成入口，本轮不凭表结构宣称已实现批量生成；正式切流必须核对外部写入者及实际使用路径。
