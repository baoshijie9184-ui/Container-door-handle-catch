# Agent 开发

当前 Agent 是 `java-cloud` 单体的一部分。角色入口、专业委派和模型调用在 `doorhandle-module-ai`；主站聊天和独立 AG-UI 共用 AgentScope Java Harness 的 ReAct 执行和同一套应用工作台。SDK 固定为 2.0.5，模型标识仍由应用配置。 [Harness 架构](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/architecture.md) · [2.0.5 发行说明](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.5)

## 从哪里改起

| 要改什么 | 入口 |
| --- | --- |
| 角色、模型或路由 | [平台配置](agentscope-platform-config.md)；修改角色工具登记或模型路由，而不是在页面写死某个账号或供应商 |
| 厂家与员工额度 | [预算、员工分配与调用结算](厂家与员工额度.md) |
| 聊天、追溯、任务队列 | [Harness 布局](Agent前端Harness布局设计.md)、[会话与记忆](Agent会话历史与记忆统一.md)、[暂停与消息队列](Agent任务暂停与消息队列.md) |
| 运行事件和上下文 | [运行日志](agentscope-run-journal.md)、[持久上下文与卸载](Agent持久上下文与受控卸载.md)；按同一账号、会话、运行及消息身份关联 |
| RAG 和长期记忆 | 运行路径见 [Qdrant 向量存储](middleware/semantic-vector-storage.md)，用户范围与治理见 [个人长期记忆](个人长期记忆治理.md)；旧 Chroma 仅作为迁移来源 |
| MCP 和 Skill | [Stdio MCP](本地StdioMCP接入.md)、[安装队列与恢复](MCP安装持久队列与重启恢复.md)、[外部 Skill 受控安装](外部Skill链接下载与受控安装.md) |
| 语音输入 | [ASR 配置](voice-input-asr-setup.md)；识别只填入输入框，不自动执行工具 |

## 工具权限与执行

1. 从真实业务目标出发选工具。身份来自服务端认证主体；会话、资源范围和角色在服务端核对，不信任提示词、前端选项或工具返回里自称的身份。
2. 授权的日常工具直接执行。工具执行前核对当前账号和角色，业务服务再按记录范围和字段白名单返回结果。两种角色都可按权限提出检测创建、重试，主管还可提出质检分派。这些提议走 [人工确认](agentscope-action-confirmation.md)，确认时重新核对账号、资源和版本。报告草稿只能按明确请求在本人范围内创建或修改，提交和审批在 [报告页面](../monolith/报告草稿与独立审批.md) 操作。
3. 长流程把检查点、取消、回执和恢复写成可核对状态。遇到结果未知先查既有回执，不自动再执行；消息、模型尝试、工具事件和来源引用按相同执行关联，不能从默认配置推断历史使用的模型。
4. 外部来源、Skill 文件和模型输出都按不受信任数据处理。按调用范围控制输出，不把密钥、私有正文或完整异常写入日志和观测。导出及限流沿用 [来源审计](Agent调研来源导出与审计.md) 和 [导出限流](Agent调研来源导出限流.md) 的配置边界。

凭据读取为强制拒绝，人工确认不能授予账户密码、密码哈希、访问令牌或密钥的读取权。明确的凭据读取请求在模型、知识检索和记忆提炼前返回拒绝。工具接口仅提供约定的业务能力和字段，未注册的请求直接拦截。Fetch 仅使用用户在当前请求中提供的公开网址，继续由服务端校验实际网络地址。

## AgentScope Java 2.0.5 对照

| 能力 | 当前方案 |
| --- | --- |
| 工具与人工确认 | 用 SDK 工具白名单和运行中间件配合业务授权。分派沿用持久确认卡片。计划评审通过 `/plan` 主动开启，普通查询直接执行。 [权限系统](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/permission-system.md) · [中间件](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/middleware.md) · [计划模式](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/plan-mode.md) |
| 会话与上下文 | 以账号和会话为状态键。模型历史、检查点和分支复核实际来源，聊天原文保存在会话中。工作台共用 MySQL 检查点、租约与版本控制，上下文压缩可选。 [会话状态](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/context.md) · [上下文压缩](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/compaction.md) |
| 专业委派与调度 | 主管和员工拥有不同的业务专业角色。专业子任务使用独立执行记录，父任务可以读取同一逻辑任务的子结果。若子任务已结束、父任务已保存续跑点，调度器能从 MySQL 恢复未送达的通知。 [专业委派](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/subagent.md) · [生产运行](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/others/going-to-production.md) |
| 技能、自进化与 SOP | 用 SDK 技能加载器读取批准版本。当前任务固定读取的版本，续跑和历史引用重新核对发布状态。从本人授权的运行提炼草稿，版本经过结构评测和主管独立审核后发布，外链脚本仅归档。 [技能与自学习流程](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/skill.md) |
| 检索与个人记忆 | Mem0 和 Qdrant 按账号提炼和召回。召回的记忆及受控知识保留原始编号和内容依据，复用时检查当前读取偏好、访问权限和生命周期。Mem0 是唯一长期记忆入口。 [记忆](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/memory.md) |
| MCP 与工作区 | SDK 处理协议与工具发现。应用核对固定 Fetch 安装、启用状态、请求网址和退出回执。8080 使用受控 Stdio 及业务会话文件接口。SDK 文件工具、Shell 和远程沙箱没有暴露给业务 Agent。 [工具与 MCP](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/tool.md) · [工作区](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/workspace.md) · [文件系统](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/filesystem.md) · [沙箱](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/sandbox.md) |
| 模型与用量 | 使用 SDK 模型扩展，应用按实际供应商请求记录模型、额度及用量。模型回退需要显式模型列表和启用配置。 [模型](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/model.md) |
| 渠道与实时事件 | 主站和 AG-UI 共用账号、会话和工作台。AgentScope 的增量事件负责进度，工具进度实时返回，最终回答通过来源与执行回执检查才显示。外部渠道属于独立接入范围。 [消息与事件](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/message-and-event.md) · [渠道](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/harness/channel.md) · [AG-UI](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/integration/protocol/agui.md) |
| 观测与评测 | Higress、Java 和 Mem0 的追踪进入 Langfuse。只有实际模型供应商尝试计入用量，SDK 生命周期保留为追踪。Prometheus 负责运行指标，离线规则评测校验工具权限、写入副作用和业务事实。 [中间件](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.5/docs/v2/en/docs/building-blocks/middleware.md) · [本项目评测](agentscope-eval.md) |

## 接线与验收

同一轮完成角色登记、API 契约、前后端接线、开关与迁移、失败处理和测试代码；两套聊天入口必须保持共同契约。按 [Agent 评测方案](agentscope-eval.md) 准备用例，同时保留真实 MySQL、模型或中间件的验收边界。开发阶段不提前跑测试，统一验收遵循 [开发总规则](../开发规则.md) 和 [单体验收入口](../monolith/README.md#ecs-统一验收与发布)。
