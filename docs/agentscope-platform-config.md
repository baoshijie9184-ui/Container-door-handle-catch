# AgentScope 平台配置说明

后端的 AgentScope Java 2.0.4 适配位于 `doorhandle-module-ai`，通过 `doorhandle-server` 暴露 AG-UI 接口。角色网关在进入异步运行之前绑定登录身份；模型由 `AgentModelService` 统一创建，主 Agent 和专业 Agent 使用相同的模型选择。仓库只提交 `.env.example`，真实密钥保存在被 Git 忽略的根目录 `.env` 或部署环境中。

升级依据：[AgentScope 2.0.4 Release](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.4) 新增官方 Responses 适配器，本项目复用该实现处理灵算协议、流式事件和工具调用。

## 最小启动配置

```dotenv
AGENTSCOPE_AI_ENABLED=true
DASHSCOPE_API_KEY=你的阿里云百炼Key
DASHSCOPE_MODEL=qwen-plus
AGENTSCOPE_AI_MODEL=dashscope:qwen-plus
```

启动后接口为 `POST /agui/run`，需要检测系统登录态；`GET /agui/catalog` 返回当前角色能力；`GET /agui/models` 返回当前选中模型及三个供应商的配置状态，要求合法员工或主管身份，不返回密钥、地址与自定义请求头。未开启 `AGENTSCOPE_AI_ENABLED` 时不装配这些入口。Agent 按请求创建，模型客户端共享不可变连接设置，会话和 Toolkit 仍隔离。

## 统一模型管理

| 供应商 | 当前本地模型 | AgentScope 选择 ID | 协议 |
| --- | --- | --- | --- |
| DashScope / 阿里云百炼 | kimi-k3 | `dashscope:kimi-k3` | 当前使用百炼 OpenAI-compatible Chat Completions |
| DeepSeek | deepseek-flash | `deepseek:deepseek-flash` | Chat Completions + DeepSeek Formatter |
| 灵算 OpenAI-compatible | gpt-6.1-sol | `openai-official:gpt-6.1-sol` | 原生 Responses |

当前 `.env` 设置 `AGENTSCOPE_AI_MODEL=openai-official:gpt-6.1-sol`，角色主 Agent 与专业 Agent 都实际通过统一模型服务选择该模型。`openai-official:` 表示使用官方 Java SDK 的 Responses 适配器，不表示接口供应商是 OpenAI 官方。助手 React 页面展示当前模型和其他已配置模型；“已配置”仅表示配置中有凭证，不等于每个模型均已完成真实业务验收。

更换模型时同时核对供应商模型名和选择 ID，例如 `OPENAI_MODEL=gpt-6.1-sol` 与 `AGENTSCOPE_AI_MODEL=openai-official:gpt-6.1-sol`，修改 `.env` 后重启后端。当前不提供浏览器任意修改端点/密钥的接口；默认模型未登记或缺少凭证时启动失败，避免悄悄使用另一家供应商。

模型连接从 Spring Environment 显式绑定到 `agentscope.models`，支持 `.env` 和部署环境的正常优先级，不再依赖 SDK 直接从进程环境猜测密钥。供应商凭证分别绑定，不共享密钥。主站聊天和 AG-UI 均使用同一角色工厂与模型服务；旧 `DeepSeekClient`、StateGraph 和独立专业 Agent 服务已移除。RAG 的查询改写与重排也经 contracts 的 `AgentTextApi` 调用 AgentScope，不再直接请求模型 HTTP 接口。

2026-10-12 实际 SDK 验证：`gpt-6.1-sol` 通过纯文本流式测试，随后完成一次只读验证工具调用与结果回传，最终回复包含工具实际返回的标记。测试读取真实 application.yml 与 `.env`，没有连接业务数据库或执行业务写入。本机 Java SDK 必须显式使用已有代理；初期直连/TLS 重置和一次上游流式复位失败经过诊断后，单独重测的文本与工具闭环通过。该结果不替代真实业务数据库和浏览器联调，也不能宣称上游永远稳定。

| 配置项 | 实际行为 |
| --- | --- |
| `AGENT_MODEL_TIMEOUT` | 每个候选模型的总执行预算，默认 60 秒；持续输出也不会重置总预算 |
| `AGENT_MODEL_FIRST_TOKEN_TIMEOUT` | 首段有效内容超时，默认 15 秒；文字、思考内容或工具参数算有效内容，空元数据不算 |
| `AGENT_MODEL_MAX_RETRIES` | 关闭自动备用时的 SDK 重试次数，默认 2；开启自动备用时每个候选只尝试一次 |
| `AGENT_MODEL_MAX_OUTPUT_TOKENS` | 模型输出预算，默认 2048 |
| `AGENT_MODEL_PROXY_URL` | 可选 HTTP/SOCKS5 代理；本机使用已存在的 `http://127.0.0.1:7897`，部署时设置当地有效代理或留空 |
| `AGENT_MODEL_FALLBACK_ENABLED` | 是否启用自动备用；模板默认 false，当前本地已开启 |
| `AGENT_MODEL_FALLBACK_MODELS` | 逗号分隔的有序备用列表，非空时覆盖单备用字段；当前本地为 `deepseek:deepseek-flash,dashscope:kimi-k3` |
| `AGENT_MODEL_FALLBACK_MODEL` | 兼容原单备用字段，列表为空时使用，默认 `deepseek:deepseek-flash` |
| `AGENT_MODEL_FAILURE_THRESHOLD` | 连续暂时性故障达到此次数后暂停使用，默认 2；完整成功会清零 |
| `AGENT_MODEL_CIRCUIT_COOLDOWN` | 暂时性故障冷却时间，默认 60 秒 |
| `AGENT_MODEL_QUOTA_COOLDOWN` | 余额/额度不足或凭证故障立即暂停使用，默认冷却 5 分钟 |
| `AGENT_RESPONSES_STORE` | Responses 的 store 参数，默认 false |
| `AGENT_RESPONSES_ACTOR_AUTHORIZATION` | 灵算要求的额外请求头，空值时不发送 |

当前本地切换顺序为 **灵算 gpt-6.1-sol → DeepSeek deepseek-flash → DashScope kimi-k3**。修改 `.env` 后需要重启后端；不会由模型自动修改配置。所有备用 ID 和凭证在启动时校验，重复候选和与主模型重复的项自动去重；未登记或缺少凭证会使启动失败。

切换条件包括网络异常、首段内容超时、总超时、空回复、HTTP 408/409/429/5xx、401/403 凭证或授权故障，以及 HTTP 402 或明确的余额/额度错误标识。可识别 `insufficient_quota`、`insufficient_balance`、`Arrearage`、欠费等供应商错误，包括异常包装与 Responses 流内错误。普通 HTTP 400 参数/工具 schema 错误、未知本地异常不切换，避免掩盖实现错误。余额状态来自供应商的失败响应，不额外查询账户余额；未登记的私有错误格式需增加适配。

只有在尚未向 Agent 输出有效内容时才尝试下一个模型；已输出文字、思考内容或工具调用后失败，只结束当前模型请求，不重放工具或整个 Agent。首段超时取消当前订阅，进入下一个候选；本地取消不能保证供应商停止处理或计费。每个候选至多尝试一次，所有候选失败或冷却中时返回统一脱敏错误。主 Agent 与专业 Agent 使用同一共享健康状态，但请求的消息、工具及用户权限仍隔离。

健康状态在单体进程内按模型共享：`CLOSED` 可尝试，`OPEN` 冷却中跳过，`PROBE_READY` 冷却已到期，`HALF_OPEN` 有一个实际业务请求正在恢复探测。冷却后通过下一次请求探测，不启动定时付费请求；其余并发请求继续使用备用。探测完整成功后恢复主模型，失败重新冷却；取消会释放探测名额。健康状态在后端重启时清空，未来多进程部署需要共享状态或各实例独立治理。

`GET /agui/models` 额外返回备用顺序、首段超时，以及各模型的健康状态、失败类别、剩余冷却秒数。助手页面每 30 秒刷新这些状态，“默认模型”表示配置优先级，不代表当前回复实际来自该模型。路由日志记录切换前后模型 ID、失败类别及 HTTP 状态；错误正文只用于内存分类，不保存或返回密钥及原始异常。旧 `AGENT_MODEL_PROVIDER`、`AGENT_MODEL_FALLBACK_PROVIDER` 已从配置模板移除，不控制模型服务。

实现复用已有 [AgentScope Java 2.0.4](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.4) 模型接口和 [Reactor Flux timeout](https://projectreactor.io/docs/core/3.7.17/api/reactor/core/publisher/Flux.html)，二者均使用 Apache-2.0 许可证，保留依赖原有许可证与版权声明。本次未引入新的运行依赖或复制第三方源代码。

角色请求结束或取消后释放 Harness 实例，专业委派结束后关闭专业 Agent，防止工作区资源和运行句柄泄漏。助手开发代理默认连接单体 `127.0.0.1:8080`，可通过 `DOORHANDLE_API_TARGET` 覆盖。

两类角色的实际工具范围及未完成事项见 [实施进度](agent-role-toolkit-progress.md)。当前接口超时为三分钟，只支持文本只读查询；Starter 的 server-side-memory、reasoning、state-events、run-timeout 等配置尚不由此网关读取，不能通过打开旧配置启用这些能力。

## DashScope 与 DeepSeek 配置边界

2026-10-12：本地已单独配置 DeepSeek 官方接口，密钥只保存在被 Git 忽略的 `.env` 中。可提交的配置示例如下，不能把真实密钥写入本文件或 `.env.example`：

```dotenv
DEEPSEEK_API_KEY=填写本地密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

统一模型服务使用这组配置构建 AgentScope DeepSeek 适配器，并规范化 Chat Completions 基础地址。DeepSeek 配置不再自动复用 DashScope 的凭证或地址，避免混用供应商。模型名称与基础地址依据 [DeepSeek 官方模型说明](https://api-docs.deepseek.com/quick_start/pricing/)。

DashScope 模型名从独立的 `DASHSCOPE_MODEL` 读取，不再复用默认 Agent 模型选择字段。当前百炼地址包含 `/compatible-mode/v1`，统一模型服务使用匹配的 Chat Completions 适配器；若配置原生百炼端点，则使用相应 DashScope 模型扩展。DeepSeek 通过统一模型服务选择，不复用 DashScope 的凭证。

项目启动时从当前工作目录加载 `.env`，部署环境变量与显式启动参数具有更高优先级。配置调整后需要重启后端才会重新绑定。

本次验证：使用 HTTPS 证书校验调用官方 `GET /models`，返回 HTTP 200，模型列表包含 `deepseek-flash`；当时配置加载与客户端流式测试通过；旧客户端已在本轮迁移中移除。模型列表验证不产生聊天推理请求，不等同于真实生成、工具调用或自动备用链路已验收。

## OpenAI-compatible / 灵算 Responses 配置

2026-10-12：根据用户提供的灵算地址和模型更新本地 `.env`；真实凭证只保存在被 Git 忽略的配置中。当前项目使用以下兼容接口参数：

```dotenv
OPENAI_API_KEY=填写本地密钥
OPENAI_MODEL=gpt-6.1-sol
AGENTSCOPE_AI_MODEL=openai-official:gpt-6.1-sol
AGENT_RESPONSES_BASE_URL=https://lingsuan.top/v1
AGENT_RESPONSES_ACTOR_AUTHORIZATION=local-image-extension
AGENT_RESPONSES_STORE=false
```

该凭证此前请求 OpenAI 官方地址返回 HTTP 401；用户随后明确提供灵算兼容地址。按上述地址、Bearer 凭证和 `x-openai-actor-authorization` 请求头测试：`GET /models` 返回 HTTP 200，共 20 个模型，包含 `gpt-5.6-sol` 和 `gpt-6.1-sol`。

初次最小生成测试使用 `gpt-5.6-sol`，返回 HTTP 200、`status=completed`、正文 OK、`store=false`，接口报告输入 22 token、输出 5 token。随后按用户要求将灵算配置切换为 `gpt-6.1-sol`，使用相同的 `POST /responses`、`store=false`、`max_output_tokens=128` 与 OK 输入再次测试，也返回 HTTP 200、`status=completed`、正文 OK、`store=false`；该次接口报告输入 4227 token、输出 5 token。用量为兼容平台响应中的统计，不根据短输入推断其内部计费或上下文构成。模型名是兼容平台返回的标识，不据此认定底层模型来源。

Responses 请求字段参照 [OpenAI 官方 Responses 文档](https://developers.openai.com/api/reference/python/resources/responses/methods/create)。`store=false` 为请求参数，本次响应也返回该值；不将此解释为对兼容平台内部数据保留策略的独立验证。

上述凭证、地址、模型、请求头和 store 设置现已通过 `agentscope.models.openai` 接入 AgentScope 原生 Responses 执行链路。旧 `agent-platform.responses` / `AGENT_RESPONSES_ENABLED` 配置已移除；是否装配角色 Agent 由 `AGENTSCOPE_AI_ENABLED` 决定。

用户提供的 `model_provider`、`review_model`、`features` 等属于 Codex 配置语义，本次仅提取项目 API 所需参数，不将这些字段当作 Spring Boot 或 AgentScope 的原生配置。

## 配置分组

| 配置组 | 用途 | 默认状态 |
| --- | --- | --- |
| `AGENT_MODEL_*` | 实际超时、重试、代理、输出预算、备用链及恢复探测 | 本地灵算 gpt-6.1-sol；备用 DeepSeek、DashScope 已开启 |
| `AGENT_EVENT_BRIDGE_*` | EventBridge/异步事件适配预留 | 关闭 |
| `AGENT_A2A_*` | A2A Agent 协作服务地址与密钥 | 关闭 |
| `AGENT_RESPONSES_*` | Responses 端点、额外请求头与 store 由模型服务消费 | 默认模型实际使用 Responses |
| `AGENT_MEMORY_*` | 未来 AgentScope 存储适配预留 | 关闭 |
| `MEM0_ENABLED`、`MEM0_SERVICE_URL` | 主站会话的已有 Mem0 支持服务 | 模板默认为开启，需要外部服务；不是 Harness 记忆钩子 |
| `AGENT_VECTOR_*` | Milvus 等向量数据库 | 关闭 |
| `AGENT_WORKSPACE_*` | Agent 工作区与沙箱策略 | 本地工作区 |
| `OTEL_*`、`LANGFUSE_*` | OpenTelemetry、Langfuse 可观测性 | 关闭 |

模型管理参数已经实际接入；事件总线、A2A、记忆、向量库和可观测平台等其他开关仍是预留契约，不能仅凭开关存在视为接入完成。

## 验证命令

2026-10-12 验证结果：24 项后端定向回归通过，单体 Server 打包通过；助手前端构建与 2 项协议测试通过；真实灵算 SDK 的文本流式与只读工具回传分别通过。尚未进行真实业务数据库和浏览器端到端验收。SDK 升级后发现的工作区句柄释放问题已修正，测试临时目录由 Surefire 定位到各模块 `target` 内。

同日自动备用补充验证：46 项后端定向回归及单体打包通过，助手前端构建和 2 项协议测试通过。通过本地 HTTP/SSE 模拟接口验证原生 Responses 429 额度错误、DeepSeek 402 余额错误与第三候选成功；HTTP 200 下的 Responses 流内额度错误也能转到 Chat Completions 流。覆盖首段计时、总执行预算、上游订阅取消、部分文字/思考/工具输出不切换、冷却跳过、单请求恢复探测、取消释放、过期并发结果、配置绑定及错误脱敏。未调用付费模型制造欠费或故障，真实三供应商自动切换与浏览器联调仍待运行验收。

正常回归不调用付费模型，覆盖角色权限、协议/工具回传、Spring 凭证绑定、脱敏与备用边界：

```powershell
mvn -pl doorhandle-module-ai -am test '-Dtest=AgentModelServiceTest,AgentModelConfigurationTest,ManagedAgentModelTest,ModelCircuitTest,ModelFailureClassifierTest,RoleAgentFactoryTest,RoleAgentControllerTest,AgentIdentityTest,BusinessToolkitFactoryTest' '-Dsurefire.failIfNoSpecifiedTests=false'
```

可选真实 SDK 工具闭环验证，从指定项目 `.env` 与 application.yml 绑定配置，仅调用只读测试工具，输出限定为 256 token，禁止自动重试。该测试显式关闭备用，只验证选定默认模型，避免将备用成功误报为默认模型成功：

```powershell
mvn -pl doorhandle-module-ai -am test '-Dtest=AgentModelLiveSmokeTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dagent.model.live=true' '-Dagent.model.project=D:/AI/lunwen1/DoorHandleCatch'
```

## 安全约束

- 不要把 `.env`、云厂商 Secret 或生产配置提交到 Git。
- 生产环境优先使用容器编排平台 Secret 注入环境变量。
- `AGENT_WORKSPACE_ROOT` 应指向专用目录，不要指向用户家目录或项目源码根目录。
- 开启 AG-UI 跨域时，仅填写明确的前端域名，并保持 `AGENTSCOPE_AGUI_CORS_ENABLED=false` 作为默认值。

## 2026-10-12 主站助手迁移

主站 Vue 的 `/api/chat-assistant/messages` 和 `/messages/stream` 保留协议，经 `AgentScopeChatServiceImpl → AgentConversationApi → AgentScopeConversationService → RoleAgentFactory` 执行。App 模块维护会话、检索和 SSE，AI 模块负责全部 Agent、模型和业务 Toolkit。没有旧路由、独立 DeepSeek 客户端或旧图编排回退。

主站历史从 MySQL 按会话所有者读取，仅传入 user/assistant 文本，过滤历史业务卡片。每轮创建临时 Agent；聊天文本可跨重启恢复，SDK 工具状态与中断执行不恢复。独立 React AG-UI 入口仍使用客户端提交的文本历史，不宣称它已接入主站的持久会话。

`GET /api/chat-assistant/sessions/{sessionId}/trace` 返回最近一轮真实 SDK 事件摘要。记录框架、runId、状态、更新时间，以及最多 200 条事件类型、Agent 名、工具名和相对开始时间；不保存工具参数、返回正文、思考正文或模型异常。主站执行轨迹页面与抽屉展示此接口，不再计算模拟耗时或展示旧 StateGraph Checkpoint。它是有限事件摘要，不是不可篡改审计、全量子 Agent 轨迹或 OpenTelemetry 链路。

保留现有 `chat_session.state_json` 存放最新摘要，不清空历史聊天，不删除旧数据库列；旧 StateGraph JSON 不当作 SDK 轨迹读取。两个入口共享进程内 `AgentRunRegistry`，以用户、角色入口与会话编号互斥，未提供跨实例锁。取消、异常和正常结束均释放执行资源。

全部业务工具当前只读。历史待确认卡片可以取消；确认执行返回 410，不恢复旧版写动作。新 AgentScope 持久人工确认、写操作幂等、独立审批、Turn/Call 审计和 Eval 平台仍按设计文档后续实施。

## 阶段 B 持久运行开关

阶段 C 第一项使用 `AGENT_ACTION_CONFIRMATION_ENABLED`（模板默认 false），启用前需执行 V19 新表迁移并开启运行日志。允许主管保存质检分配提议，通过受控确认接口执行业务操作，详见 [人工确认说明](agentscope-action-confirmation.md)。

`AGENT_RUN_JOURNAL_ENABLED` 默认 false。执行 V16 迁移后启用两个入口的持久运行与专业工具事件，启动检查缺表时明确失败。读取与取消接口、游标、重复请求规则和 SDK 状态边界见 [运行日志实施说明](agentscope-run-journal.md)。当前本机 `doorhandledb` 已执行 V16 迁移并开启此开关，后端健康检查通过；隔离库验证证据仍保留。
## 2026-10-13 报告能力更新

报告门面装配后，AgentScope 注册第五个专业 Agent `report-assistant`；持久运行日志开启时允许本人报告草稿创建与编辑，提交和审批仍到业务页面。health/catalog 的 `reportsEnabled`、`reportDraftsEnabled` 表示实际能力，不能再将全部工具概括为只读。下文较早“只读、确认和 Eval 待开发”描述是历史状态，当前实施及验证见 [Agent 报告工具接入](Agent报告工具接入.md) 和 [阶段进度](agent-role-toolkit-progress.md)。
