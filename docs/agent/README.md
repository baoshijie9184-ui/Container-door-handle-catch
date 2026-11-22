# Agent 开发

当前 Agent 是 `java-cloud` 单体的一部分。角色入口、专业委派和模型调用在 `doorhandle-module-ai`；主站聊天和独立 AG-UI 使用 AgentScope Java 2.0.4。旧 StateGraph、旧 Router/Checkpoint 和独立 DeepSeek 客户端是历史实现，不作为新功能入口。

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

## AgentScope Java 2.0.4 对照

| 能力 | 当前方案 |
| --- | --- |
| 工具与人工确认 | 用 SDK 工具白名单和运行中间件配合业务授权。分派沿用持久确认卡片。计划评审通过 `/plan` 主动开启，普通查询直接执行。 [权限系统](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/building-blocks/permission-system.md) · [中间件](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/building-blocks/middleware.md) · [计划模式](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/harness/plan-mode.md) |
| 会话、上下文与委派 | 以账号和会话为状态键，沿用 MySQL 检查点、租约与恢复。按角色委派专业 Agent，子任务重新校验账号和工具。可配置上下文压缩。 [会话状态](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/building-blocks/context.md) · [委派](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/harness/subagent.md) · [上下文压缩](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/harness/compaction.md) |
| 技能、自进化与 SOP | 用 SDK 技能加载器读取批准版本。从本人授权的运行提炼草稿，版本经过结构评测和主管独立审核后发布，外链脚本仅归档。 [技能与自学习流程](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/harness/skill.md) |
| 个人记忆 | Mem0 和 Qdrant 按账号提供记忆提炼、召回和生命周期控制。关闭 SDK 文件记忆写入，避免同一信息分散到两套存储。 [记忆](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/harness/memory.md) |
| MCP 与工作区 | SDK 处理协议与工具发现。应用核对固定 Fetch 安装、启用状态、请求网址和退出回执。8080 使用受控 Stdio，通用 Shell 和工作区文件工具关闭。 [工具与 MCP](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/building-blocks/tool.md) · [沙箱](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/harness/sandbox.md) |
| 模型与观测 | 使用 SDK 模型扩展与 OpenTelemetry 生命周期。应用记录模型身份和额度，按白名单输出追踪字段。业务事件通过主站和 AG-UI 展示。 [模型](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/docs/building-blocks/model.md) · [AG-UI](https://raw.githubusercontent.com/agentscope-ai/agentscope-java/v2.0.4/docs/v2/en/integration/protocol/agui.md) |

## 接线与验收

同一轮完成角色登记、API 契约、前后端接线、开关与迁移、失败处理和测试代码；两套聊天入口必须保持共同契约。按 [Agent 评测方案](agentscope-eval.md) 准备用例，同时保留真实 MySQL、模型或中间件的验收边界。开发阶段不提前跑测试，统一验收遵循 [开发总规则](../开发规则.md) 和 [单体验收入口](../monolith/README.md#ecs-统一验收与发布)。
