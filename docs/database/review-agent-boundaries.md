# Agent 存储边界复审

历史记录：本文针对已撤回的第一版 Agent 17 表分配，不是现行建库清单。现行候选见 [29 表模型](compact-schema-proposal.md)，已有部分源码实现但尚未完成整库和 ECS 验证。

2026-11-05。记录已经核实的设计问题；原 17 表不是确定配额。本轮未运行应用、数据库或测试，尚未形成最终 Agent 表数。

| 数据 | 已核实的边界 | 修订方向 |
| --- | --- | --- |
| 项目、会话、消息 | 项目可独立存在；一个会话有多条消息；消息删除规则与运行证据保留不同 | 保留各自身份和所有者，不能把消息堆成会话中的无界数组 |
| 消息的执行关联、附件快照、上下文来源快照 | 对应指定消息的一对一附属内容 | 可以内嵌消息，但先落实删除正文时的证据保留，不随会话级联丢弃历史 |
| 对话输入队列 | 有独立输入 ID、领取状态、活跃槽和过期处理 | 归真正的持久队列，不混入已发送的消息 |
| 工作台主执行状态、逻辑任务、运行尝试 | `AgentWorkbenchService.mainId` 在同一用户/会话下固定；新任务会生成新的 `logicalTaskId` 并覆盖当前工作项中的值 | 当前工作台行不是每个逻辑任务的历史实体；不能将按逻辑任务保留的 bootstrap 直接覆盖到这行。先设计真实任务身份，再决定历史附属状态是否内嵌 |
| 上下文摘要、SDK 检查点 | 摘要有历史版本；SDK 检查点是可覆盖的 CAS 当前状态 | 不以都有 state JSON 为由机械合并，明确当前指针与历史版本的关系 |
| 工具结果来源、卸载内容回执 | `DurableContextStore` 卸载前要求同账号、会话、作用域、调用键的来源唯一匹配 | 有依据研究同一来源行保存可选卸载回执；fork 的历史来源例外需要保留，不能直接统一到任意资源引用 |
| 技能及其版本 | 有角色、审核、发布指针、回滚、工具权限和验证结果 | 技能业务状态独立。与知识资料可以研究共享内容存储，但不能只把两套字段拼起来 |
| 知识资料及版本、检索片段 | 有私有/企业可见性、历史原文件、当前版本和片段查询 | 保留版本与片段的一对多关系；文件目录只负责文件身份，不代替资料权限 |
| 工作区文件、检测模型文件、模型文件保留凭据 | 文件可能先于业务登记存在，删除模型后清理凭据仍需存在 | 统一文件身份时明确每种引用和保留规则，上传/清理执行状态应归对应操作 |
| LLM 配置、额度、使用记录 | 配置涉及密钥和启用验证；额度是可并发扣减状态；使用记录含预留、结算及重试事实 | 分开业务职责，个人额度缺省仍保留已有使用权限。用户额度申请及审批不能由一次模型调用记录代替 |

关键源码依据：

- `doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/workbench/AgentWorkbenchService.java`：`mainId`、`execute` 中 `logicalTaskId` 更新及按逻辑任务取消/恢复的条件。
- `doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/context/DurableContextStore.java`：来源核对、卸载及摘要/恢复写入。
- `doorhandle-module-app/src/main/java/com/ruanzhu/doorhandle/module/app/service/knowledge/QualityKnowledgeService.java`：按账号和可见性查询、不可变版本读取、原文件摘要校验、逐版本检索片段。
- `sql/mysql/migration-V23-agent-skill-evolution.sql`、`migration-V36-conversation-inbox.sql`、`migration-V37-agent-workbench.sql`：技能版本、独立输入队列、工作台状态的原始键和约束。

后续要先确定这些职责的统一模型，再写实际表结构、仓储和数据转换。上述关系并不要求逐项一张物理表，也不能直接相加宣称最终数量。
