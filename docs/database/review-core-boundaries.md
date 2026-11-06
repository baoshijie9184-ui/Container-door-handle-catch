# 核心业务表边界复审

历史记录：本文评审的是已撤回的第一版方案，文中的“当前草案”和暂停状态指当时。现行候选已采用 [29 表模型](compact-schema-proposal.md)，核心专表为 13 张，源码实现中、未完成 ECS 验证。

状态：只读设计复审，2026-11-05。**30 是全库上限，不是需要凑齐的数量。原 9 个 core 表及其 30 表组合不是已通过的终态设计。** 本文依据现有业务代码，先判断职责、生命周期、事务和查询，再记录数量影响；没有修改表数或执行 SQL。

## 结论

账号与员工、部门、设备、模型分别保留实体身份是合理的。账号的当前员工绑定可以嵌入账号；不能因此把员工档案与账号合并。工作单元与检测任务不是已经证明的一对一对象，也不能直接合并。

原方案有三个主要问题：历史汇总被包装成检测任务、图片资产/工作单元中的图片/上传动作被包装成一种图片记录、审批报告/日报执行/消费投影被包装成一种文档记录。它们有共同字段，但当前代码没有共同生命周期、权限和查询协议。多加一个 `kind` 并不能自动建立合理聚合。这些合并应退出“已确定方案”，保留为待论证候选。

仅复原原 core9 所覆盖的业务，下面的保守职责清单得到 **12 个关系候选**，不是最终表数，也不是最少数量证明。此前藏在 `operation_job` 中的设备领用、告警、重复复查和日报计划还各有独立业务实体；重新归位可能增加领域关系，或在后续真正的公共业务能力设计中得到自然合并。此时不能承诺全库仍是某个精确数字，更不能为抵消这里的拆分去强行压缩其他领域。

## 原 core9 的职责复审

| 建议职责/暂定关系 | 存什么 | 不存什么及理由 | 代码证据 |
| --- | --- | --- | --- |
| `users` | 登录账号、凭据、账号角色、显式员工关联、关联版本/历史存在标志 | 不覆盖员工在岗状态、员工编号、设备领用历史。解绑不删除账号；停用员工不应隐式改变账号权限 | [AccountIdentityService.java:53](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-system/src/main/java/com/ruanzhu/doorhandle/module/system/service/AccountIdentityService.java:53) 在账号锁、员工锁、版本 CAS、审计事务内绑定；第 66 行允许关联为空 |
| `employee` | 员工稳定身份、员工编号、姓名、在岗状态、部门、人员类型、资料版本 | 不能与账号强制共用 ID；员工可独立新增，账号绑定另有资格验证。当前设备分配依赖员工实体 | [EmployeeServiceImpl.java:106](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-device/src/main/java/com/ruanzhu/doorhandle/module/device/service/impl/EmployeeServiceImpl.java:106) 独立新增员工；第 120、153 行有独立版本更新与删除规则 |
| `organization_department` | 部门稳定 ID、唯一名称及部门主数据 | 不把部门改成员工行中的任意字符串。部门可先于员工创建，多个员工共享一个部门 | [OrganizationDepartmentService.java:25](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-system/src/main/java/com/ruanzhu/doorhandle/module/system/service/OrganizationDepartmentService.java:25) 独立创建和重名检查；第 34 行要求选择已有部门 |
| `device_management` | 设备编号、类型、当前运行状态、心跳、当前保管员工、设备资料版本 | 不在一行反复覆盖多次领用/归还历史或多条告警。设备实体与模型版本也无共享身份 | [DeviceServiceImpl.java:285](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-device/src/main/java/com/ruanzhu/doorhandle/module/device/service/impl/DeviceServiceImpl.java:285) 心跳；第 314、343、358 行单独查询、确认及解决告警 |
| `model_management` | 检测模型名称/版本、验证结果、发布状态、默认选择、推理参数与指标、当前文件引用 | 不把上传失败/保留文件记录塞进模型 JSON；文件可先于模型注册存在，保留历史不等于当前模型状态。这里也不是 LLM 供应商配置/用户 token 额度 | [ModelRegistrationService.java:32](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-model/src/main/java/com/ruanzhu/doorhandle/module/model/service/ModelRegistrationService.java:32) 上传验证后才注册模型；[ModelFileJournal.java:54](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-model/src/main/java/com/ruanzhu/doorhandle/module/model/service/ModelFileJournal.java:54) 先保留文件位置，第 74、83 行分别注册、保留文件 |
| `detection_task` | 一次检测任务的业务 ID、调度 ID、模型引用、当前执行结果、复核/处置、稳定操作者身份 | 不接收没有 task ID、调度或权限归属的历史统计行。任务重试使用新的 dispatch ID，但不代表工作单元实体消失 | [DetectionTaskServiceImpl.java:140](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/impl/DetectionTaskServiceImpl.java:140) 创建；第 255 行确认上传并准备调度 |
| `detection_work_unit` | 申请/派发的工作量、申请人、负责人、策略、图片数量、提交状态、独立版本 | 不当成推理运行记录。可在尚无推理结果时申请、分配、回收；提交要求其图片明细全部进入终态 | [DetectionWorkUnitServiceImpl.java:28](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/impl/DetectionWorkUnitServiceImpl.java:28) 申请；第 44、61、71、89 行分别提交、派发、回收、CAS |
| 图片资产/指纹关系 | 内容 SHA-256 唯一身份、对象位置、最近检测状态和最近 task 引用 | 不对工作单元出现记录强加 SHA 全局唯一。当前预检查按 hash 跨工作单元查找资产。资产信息是否可直接采用未来统一文件目录，仍可研究 | [DetectionBatchPrecheckServiceImpl.java:27](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/impl/DetectionBatchPrecheckServiceImpl.java:27) 按 hash 查已知状态；[migration-V15-detection-fingerprint-work-unit.sql:2](/D:/AI/lunwen1/DoorHandleCatch/sql/mysql/migration-V15-detection-fingerprint-work-unit.sql:2) 唯一 hash |
| 工作单元图片/检测输入明细关系 | 图片出现 ID、工作单元、对象引用、运行引用、该次处理状态、版本；可引用资产 | 不与内容唯一身份共用主键和唯一性；一个内容可在多个工作单元再次处理。工作单元明细状态不是 OSS 上传回执 | [DetectionWorkUnitServiceImpl.java:96](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/impl/DetectionWorkUnitServiceImpl.java:96) 每次绑定生成 image ID；[DetectionWorkUnitImage.java:12](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/entity/DetectionWorkUnitImage.java:12) 保存 workUnitId、detectionRunId、status、version |
| 人工质检报告关系 | 私有草稿、任务依据快照、提交冻结摘要、独立审批、版本及修订链 | 不能被日报运行/消费投影覆盖状态。一个任务可有不同报告及修订，不宜直接嵌入任务单行 | [QualityReportService.java:78](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/QualityReportService.java:78) 创建，第 97 行提交冻结，第 113 行修订创建新草稿，第 133 行独立审批 |
| 日报运行/统计快照关系 | 所属计划、日期、去重请求、执行租约、执行结果、冻结统计快照及摘要 | 没有人工报告的 DRAFT/SUBMITTED/APPROVED 状态，也没有单 task FK；其成功输出可接公共文件目录，但执行记录不能因此消失 | [QualityDigestService.java:43](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/QualityDigestService.java:43) 排队，第 48 行租约，第 51 行跨任务统计，第 52 行主管本人下载 |
| 历史检测汇总关系 | 原 ID、原模型引用、原计数/NULL、日期、目录与结果路径；只代表历史聚合事实 | 不补造图片明细或任务归属，不混入当前任务数量、审批和工作量。不为了去一张表引入整个任务域强制类型过滤 | [HistoricalDetectionSummaryService.java:27](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/HistoricalDetectionSummaryService.java:27) 企业管理账号专用统计；第 34、43 行全量/年度汇总，无 task 关联 |

数量推导仅为：人员组织 3 + 设备/模型主数据 2 + 任务/工作单元 2 + 图片资产/出现 2 + 人工报告/日报运行/历史汇总 3 = 12。**这是本轮职责候选清单，尚未决定所有职责必须各占一张物理表。**

## `operation_job` 中需要重新归位的内容

不能因为都有 `status`、`owner`、`revision` 就认为它们使用同一业务模型。目前不存在一个真正统一并验证过的业务工作流引擎来执行这些状态机。

| 内容 | 边界建议 | 依据 |
| --- | --- | --- |
| 设备领用记录 | 回归设备域的领用关系。查询主体是设备/员工/时间区间，且有历史姓名编号快照；不是后台执行作业 | [DeviceUsageRecord.java:13](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-device/src/main/java/com/ruanzhu/doorhandle/module/device/entity/DeviceUsageRecord.java:13) 明确历史快照语义；[DeviceUsageRecordServiceImpl.java:262](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-device/src/main/java/com/ruanzhu/doorhandle/module/device/service/impl/DeviceUsageRecordServiceImpl.java:262) 归还操作 |
| 设备采集告警 | 回归设备域告警关系。多次产生、人工确认、解决是产品功能，不是已发送消息或审计日志 | DeviceServiceImpl 第 314、343、358 行 |
| 重复图片复查工单 | 回归质检域工单。保留左右任务、图片证据、负责人、结论、审批人和 CAS；它既不是执行 command，也不是 task 的一对一属性 | [DetectionDuplicateTicketServiceImpl.java:23](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/impl/DetectionDuplicateTicketServiceImpl.java:23) 支持 ACCEPT_LEFT/ACCEPT_RIGHT/REDETECT 与并发版本验证 |
| 日报计划 | 先保留质量域计划。它是用户可命名、启停、改 Cron、按所有者管理的持续资源，与每次运行是一对多 | QualityDigestService 第 34—47 行；[migration-V65-quality-digests.sql:4](/D:/AI/lunwen1/DoorHandleCatch/sql/mysql/migration-V65-quality-digests.sql:4) 独立计划 ID 与运行 FK |
| 检测创建/传输核对 | 领域语义仍由检测域拥有。其幂等接收/租约可以使用公共执行机制；批准内容、对象清单、只读核对与 FINALIZE/ABANDON 不能交给无领域规则的通用重试器。是否最终与任务的 PREPARING 阶段合并需要单独重构论证 | [DetectionCreationService.java:97](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/detection/DetectionCreationService.java:97) 先预留 task ID；[DetectionCreationReview.java:30](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/detection/DetectionCreationReview.java:30) 核对/完成/放弃；[DetectionCreationTransfers.java:18](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/detection/DetectionCreationTransfers.java:18) 先持久化清单再上传 |
| 报告消费投影 | 从 `quality_document` 移出。可使用有明确 namespace 的投影状态关系；不能覆盖人工报告。收件回执与最高已消费版本必须同事务 | [ReportEventInbox.java:21](/D:/AI/lunwen1/DoorHandleCatch/doorhandle-module-detection/src/main/java/com/ruanzhu/doorhandle/module/detection/service/report/ReportEventInbox.java:21) 校验 outbox 后收件，不要求权威报告行存在；不能未经验证强加权威报告 FK |

其中前四项是 4 个额外领域关系候选。若都独立，加上前述 12 得到 16；这仍不是全库推荐最终数量。创建流程、文件生命周期和现有 Agent/LLM 数据还需跨域评审，不能先减去一个固定“公共表预算”。

## 可以继续研究的自然合并

1. **当前账号绑定并账号**：有明确的一账号至多一员工、一个员工至多一个账号约束，绑定版本随账号保存合理；保留旧绑定历史存在标记和删除保护，不靠姓名猜绑定。当前已实现片段仍需 ECS 上的迁移和并发验证。
2. **审计合并**：各域不可变审计可共用追加日志关系，保留资源类型、动作、操作者、请求 ID、版本和领域摘要链。可变收件/确认/租约状态不能伪装成不可变审计。
3. **幂等命令回执、outbox/inbox、锁的共用机制**：这些有真实技术共性，但不是所有业务实体共享一张几百列作业表的理由。先定义各自生命周期与保留策略，再决定共享粒度；共用物理存储也必须由所属领域 repository 限定读写范围。
4. **文件目录与传输条目**：规范化文件资产可服务检测图像、模型、报告导出；其所有者/权限/内容 hash/存储位置明确。一次传输的 upload token、ETag、请求回执属于操作明细，不是内容唯一身份。工作单元图片是使用关系，不能把三者合成一个状态字段。
5. **任务准备阶段**：创建作业已有 UNIQUE(task_id)，有资格研究将批准后的准备阶段纳入任务整体生命周期。但必须先解决未发布任务的可见性、权限、统计、不可重放上传以及核对证据；当前代码未完成这套统一，不能直接宣布已自然合并。
6. **通用调度计划**：只有在日报、其他自动化共同采用同一个已实现的 Cron/时区/权限重验/配额/执行幂等协议后，才把日报计划放进真正的调度关系。当前仅共用 `next_fire_at` 不足以证明。
7. **结构化快照**：原代码已经冻结的报告正文、统计结果、请求/响应证据可以保持 JSON；可查询的日期、状态、所有者、额度、外键、唯一键、版本和租约必须是明确列。不能将实体整体装入 JSON 来压表数。

## 当前工作区状态与后续核实

最新暂停指令之前，历史汇总合并切片只写了专用 `ImageDetectionDataMapper` repository、删除旧 mapper XML、增加 `DetectionTaskKindInterceptor` 并挂到插件链、为 DetectionTask 添加固定 TASK 字段。全体查询尚未适配，006 迁移与对应测试尚未完成。**复审撤回该合并方向后，已逐文件核对差异并撤销以上 5 个文件的本切片改动，恢复原历史表 Mapper/XML，删除新拦截器，避免半成品改变现有运行行为。** 早先账号绑定等独立改动保持不动。旧 30 表基线仅为待重设草案，不能部署。未执行测试、SQL、应用运行或 ECS 开机。

历史 `image_detection_data` 的字段依据是 2026-10-14 备份中真实 CREATE TABLE；还没有验证当前在线 DDL。指纹表现有源码主要读路径已核实，写入责任和实际数据覆盖还应在后续完整核实后再决定是否把它视为可重建投影。不能以本地没有发现某条写路径或某表行数少为由删数据、删功能。

下一步先让全库领域清单、关系基数、保留策略和常用查询通过审查，再汇总数量；如果仍超过 30，应找真实重复数据或可复用机制，或者明确说明实现这些业务所需的代价，不能继续倒推万能表。
