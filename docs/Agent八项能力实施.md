# Agent 八项能力统一实施

日期：2026-10-17；分支：`java-cloud`。本轮处于集成与验收阶段，尚未部署 ECS。八项能力共同验收通过后统一发布，不发布中间版本。

## 设计来源与执行框架

参考项目内 DeepSeek Harness `86a40220` 的 Todo、Plan、提问、会话 Fork、子 Agent、后台任务、Token 计量和语义检查点设计。参考项目为 MIT，未复制其运行时。当前执行框架继续使用 AgentScope Java 2.0.4。

- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/tree/86a40220)：按其 README 仍属开发者预览，不能假定其插件接口与 Java 直接兼容。
- [AgentScope 2.0.4 状态接口](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-core/src/main/java/io/agentscope/core/state/AgentStateStore.java)：实现 MySQL 版本控制，不以聊天轨迹 JSON 代替 SDK 状态。

## 功能与边界

| 能力 | 当前接入方式 | 验收重点 |
| --- | --- | --- |
| 计划与任务清单 | 持久任务列表、`/plan`、复杂或不确定任务先提交计划；版本绑定批准、修改反馈和取消 | 未批准前不能启动专业执行、生成文件或执行业务写入；计划批准不代替业务审批 |
| 主动提问 | 单选、多选、文本卡片；回答校验、请求去重、等待状态持久化 | 保存等待状态后释放执行；取消不能猜测答案；回答后继续原逻辑任务 |
| 文件与产物 | 本人上传、列表、文本/图片/PDF 预览、下载、引用和移除；受控 md/csv/json 生成；关联检测图和报告 | 文件路径不对外公开；HTML/SVG 仅源码；业务文件每次由来源模块重新鉴权 |
| 会话分支 | 从已结束助手回复复制历史前缀，保存来源与切点；保留当时资料引用和只读计划快照 | 不继承审批、队列或活动执行；分支采用当前权限；不继承切点之后关联的文件 |
| 可继续子 Agent | 现有专业白名单委派转为持久后台子会话，可追加要求、查询结果、取消 | 子执行使用独立真实运行日志；父取消只影响所属活动子执行；旧尝试不能覆盖新结果 |
| 后台任务中心 | 展示主任务、专业任务、检测及 MCP 安装适配；有界执行、状态读取、等待与取消 | 检测和 MCP 适配只读，取消/重试仍到原页面确认；长任务等待不占用模型执行槽 |
| 用量与上下文 | 按真实供应商尝试编号记录成功、失败、备用调用；主/子 Agent 用量与上下文构成 | 没有供应商用量时显示未知；字符估算不作为账单；刷新不累计重复用量 |
| 检查点与恢复 | MySQL `AgentStateStore`、安全切点快照、工具调用摘要及已完成结果；明确确认恢复 | SDK 自动重放关闭；已完成调用复用结果；未知外部写操作阻止恢复；恢复重新鉴权 |

复杂任务默认先审计划。任务状态由 Agent 声明，工具证据单独关联，不能把任务清单勾选解释为业务已经审批或放行。

执行等待计划、答案或专业结果时，保存检查点并结束当前尝试，逻辑任务继续保留；后续在新尝试中恢复。等待状态与本轮运行终态不同：本轮日志可为 INTERRUPTED，但工作台显示具体等待原因。父任务和子任务共用有界模型请求资源，专业执行最多两条。

## 持久化及接口

- V37：AI 模块拥有工作项、摘要审计、幂等回执、账号锁及 SDK 状态表；私有 SDK/工具结果不进入 HTTP 投影。
- V38：App 模块拥有用户文件元数据、会话文件引用、业务文件引用、分支关系、文件审计及请求回执；文件正文使用既有持久工作卷。
- 两份 SQL 归档在 `sql/mysql/`，AI/App classpath 分别保留对应逐字节副本。依赖 V16 运行日志与 V36 会话队列，不自动应用迁移。
- App 与 AI 通过 contracts 门面交互；业务图片和报告由检测模块通过专用门面授权，不跨模块直写业务表。

主要接口：

```text
GET  /api/agent/workbench/capabilities
GET  /api/agent/conversations/{session}/workbench
POST /api/agent/conversations/{session}/workbench/{item}
POST /api/agent/conversations/{session}/files
GET  /api/agent/conversations/{session}/files/{file}/content
POST /api/agent/conversations/{session}/files/{file}/remove
POST /api/agent/conversations/{session}/business-files
POST /api/agent/conversations/{session}/fork
GET  /api/agent/business-files/{kind}/{resource}/{file}
```

工作项操作包含请求编号、预期版本、操作名及受控输入；POST 要求 `X-Agent-Action: workbench` 并拒绝跨站操作。不同内容复用请求编号被拒绝，未决结果不会自动重试。本人读接口设置 no-store；文件响应禁用内容嗅探，文本预览不执行 HTML。

子 Agent 继续沿用业务工具白名单及确认流程，不开放 Shell、通用外部 Agent、任意文件路径或 Skill 脚本执行。其临时身份只由服务端稳定账号和当前角色构造。

## 配置与发布准备

```dotenv
AGENT_RUN_JOURNAL_ENABLED=true
AGENT_CONVERSATION_CONTROL_ENABLED=true
AGENT_WORKBENCH_ENABLED=true
AGENT_WORKBENCH_MAX_FILE_BYTES=26214400
AGENT_WORKBENCH_QUOTA_BYTES=524288000
```

主开关默认 false。`agentscope.workbench` 下 plans、questions、files、forks、children、jobs、usage、recovery 可分别控制。已启用但缺少运行日志、会话控制或必要表时应启动失败。

默认每文件 25 MiB、账号文件元数据配额 500 MiB；读取文本展示有截断上限。移除当前会话引用不会破坏其他分支引用，文件保留治理与实际空间回收需单独核对，不能把移除一条引用报告为已释放磁盘。

统一发布前备份业务库与工作卷，再按顺序补齐未应用迁移。Jenkins 只在全部检查通过后发布，回滚保留新增数据，不删表、不重放未知操作。新增检查点只覆盖启用后的执行，历史未保存 SDK 状态的运行不可恢复。

## 验证记录

完整 Maven `clean verify` 已通过 746 项检查（25 项可选联调跳过），包含状态 CAS、请求幂等、审计回滚、账号权限、文件配额/摘要及分支切点；后续工作台专项检查 25 项，22 通过、3 项按配置留给真实 MySQL。两套前端 Node 检查 105 / 5 项、生产构建通过；Python 73 项及 6 个子测试通过。新增工作台浏览器检查 27 项，原暂停/排队、追溯工作区和页面回归分别 37 / 39 / 30 项通过，无 JavaScript 错误，桌面/手机截图已复核。

真实 ECS MySQL 使用单独的 `doorhandle_wb_verify_*` 数据库验证，不覆盖业务库。文件及接口检查 11 项通过；最新重点复验 7 项通过，涵盖 SDK CAS、子 Agent 历史/活动取消、旧交互隔离、调用编号跨任务重复和两类进程中断。另有 4 项独立 JVM `Runtime.halt` 演练通过，覆盖模型请求前、工具副作用之前、等待用户及专业子执行中。进程在副作用后中断时保持未知写结果并拒绝重放；已完成的工具结果可从持久状态复用。

AgentScope 2.0.4 的最终保存仍可能携带调用初始版本。工作台按执行尝试追踪自己产生的检查点版本，数据库 CAS 始终对比本尝试最后保存的版本，拒绝其他写入者及无版本覆盖；不使用 SDK 默认 OVERWRITE 处理并发冲突。计划、问题、工具回执和取消回调同时绑定逻辑任务或执行尝试，旧卡片不能改变新任务。取消等待中的子问题会结束该子执行并唤醒父任务，不猜测回答。

文本预览上限通过 `AGENT_WORKBENCH_PREVIEW_BYTES` 配置，默认 64000 字节；截断会明确标注。汇总覆盖会话全部已记录请求尝试，而非只累计界面当前显示的记录；缺失供应商数据保留未知，并分别显示已报告部分、摘要调用、工具批次耗时及压缩记录。

这些记录不等于业务云端验收。数据库、Agent 文件卷及部署配置已备份到服务器私有目录；后续统一发布结果以本文件与 `开发进展.md` 更新为准，不把本地通过视为已经上线。Jenkins 当前任务已暂时禁用自动触发，待发布准备完成后手动执行一次统一发布。
