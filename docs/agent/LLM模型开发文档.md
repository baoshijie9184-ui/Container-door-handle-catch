# LLM 模型开发文档

## 对话模型切换

本文是 DoorHandleCatch 单体的开发方案，基于 AgentScope Java 2.0.4。目标是在同一段对话中切换模型。例如，检查人员先用 GPT 分析检测结果，再选 Qwen 追问其中一项缺陷。两条消息属于同一会话，第二个任务使用 Qwen，两个任务各自保留模型和用量记录。

### 当前实现与问题

在评审提交 `a28f863` 上，8081 的 `GET /agui/models` 能返回 17 个登记模型，服务默认模型为 `openai-official:gpt-6.2-sol`。登录后打开对话，工作台能力和会话模型偏好两个请求都返回业务码 404，选择器显示“模型选择尚未就绪”。登记数量反映本站配置，供应商项目的实际授权需要独立核对。

现有后端已经能按账号和会话保存模型偏好、校验修改版本，并在创建工作台任务时读取偏好。问题在于接口和服务一同受 `AGENT_WORKBENCH_ENABLED` 控制，而普通聊天在没有工作台执行上下文时取系统默认模型。因此，解耦必须同时覆盖**保存选择**和**执行时采用选择**两条路径。[模型选择接口](../../doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/api/ConversationModelController.java) · [工作台任务实现](../../doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/workbench/AgentWorkbenchService.java) · [角色 Agent 工厂](../../doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/agent/RoleAgentFactory.java)

### AgentScope 的设计依据

| 机制 | 官方设计及项目中的用法 |
| --- | --- |
| 模型目录 | SDK 的 `ModelRegistry` 可以按名称或 `provider:model` 解析模型。项目沿用已有 `AgentModelService` 的登记 ID 和供应商适配器，前端展示名称，后端解析 ID。[官方模型文档](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/zh/docs/building-blocks/model.md) |
| 会话历史与本次调用 | SDK 可通过 `RuntimeContext` 中的 `userId` 和 `sessionId` 定位持久化会话状态。官方路由示例在 `onModelCall` 中保留消息、工具和生成参数，把本次选中的模型交给下一层。项目负责持久化用户的选择，下一条消息可以沿用原会话历史。[官方 Agent 文档](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/zh/docs/building-blocks/agent.md) · [官方路由示例](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-extensions/agentscope-extensions-judge/agentscope-extensions-jev/src/main/java/io/agentscope/extensions/judge/jev/example/JevModelRouterMiddleware.java#L103-L115) |
| 故障切换 | SDK 提供重试、备用模型和切换监听。项目已有首段输出判断、备用候选顺序和调用流水，继续由现有路由层执行。故障切换的结果记入本次任务，用户保存的偏好继续用于下一项任务。[官方容错说明](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/zh/docs/building-blocks/agent.md#模型容错) · [项目模型路由追溯](模型调用路由追溯.md) |

### 用户如何选择模型

1. **打开对话。** 选择器读取本站模型目录和当前会话的偏好。新会话显示“系统默认”及模型名。选项展示厂家和模型名，区分通过百炼接入的 DeepSeek 与 DeepSeek 直连。
2. **选择或恢复默认。** 用户选中模型后，服务端保存成功才更新当前选项。刷新页面或从另一聊天入口打开同一会话时，显示相同选择。选择“系统默认”后，下一个新任务采用当时生效的默认模型。
3. **开始任务。** 接受发送请求时，服务端解析并固定这项任务的首选模型。启用版本化配置时同时固定配置版本。任务运行、暂停等待确认或恢复期间沿用原选择。任务结束或取消后，用户可以为下一项任务切换模型。
4. **处理不可用状态。** 加载时显示“正在读取模型”。功能关闭时显示“当前环境未启用对话模型切换”。读取失败时提供“重新读取”。已选模型下线时保留原名称并提示重新选择。保留文字草稿，两个标签页修改冲突时显示服务端最新选择，由用户决定是否再改。

### 后端与前端接线

| 环节 | 实施方案 |
| --- | --- |
| 独立启用 | 将会话偏好读写和任务模型解析从工作台服务中提取，供普通聊天与工作台共用。为模型选择提供独立的能力状态。工作台、运行日志或会话控制关闭时，模型选择仍可按部署配置启用。已有工作台环境继续读取原有偏好记录。 |
| 读取与保存 | 沿用 `GET /agui/models` 和 `GET/POST /api/agent/conversations/{sessionId}/model-selection`。保存字段沿用 `modelId`、`revision`、`requestId`，空模型 ID 表示恢复默认。服务端校验登录身份、会话归属和有效模型。沿用现有来源校验、版本冲突响应和同请求重试语义。 |
| 发送与恢复 | 选择变更和新任务启动按同一会话确定先后顺序。后端从已保存偏好解析本次模型，将结果传入角色 Agent 工厂。工作台开启时沿用任务快照。关闭时普通聊天也须把已解析模型传入执行路径。恢复已有任务读取原快照。旧会话没有偏好记录时使用系统默认。 |
| 两套界面 | 主站 Vue 的全屏对话和助手抽屉，以及独立 React AG-UI，共用模型目录、偏好读写与状态文案。模型列表的加载独立于附件上传和其他工作台能力。主站与独立页均以服务端保存回执更新选项。[共用请求逻辑](../../frontend/src/utils/composerResources.js) · [Vue 输入框](../../frontend/src/components/chat/ChatComposer.vue) · [React 工具栏](../../frontend-agent/src/ComposerToolbar.jsx) |

### 模型选择与额度

打开目录、保存偏好和切回默认均不产生模型费用。发送前可提示“尚未分配个人限额”“厂家余额不足”或“模型单价待登记”。真正发起每次供应商调用前，后端仍需按登录账号和实际候选模型检查额度并预留，避免页面读到的余额在并发调用后过期。

| 实际调用的模型 | 厂家与个人的计量范围 |
| --- | --- |
| OpenAI 接入的模型 | 同一接入账户共享美元预算。同一人的 OpenAI 模型共享其 USD 限额。 |
| 阿里云百炼接入的模型 | 每个模型单独核算 token。同一人的某个模型限额仅对该模型生效。 |
| DeepSeek 直连模型 | 同一接入账户共享人民币预算。同一人的直连模型共享其 CNY 限额。 |

主管可直接给自己分配限额，员工使用主管分配的限额。启用备用策略时，每次实际尝试均使用其对应的厂家和个人账本。界面分别展示用户首选模型与实际调用的模型。已产生有效输出后出现失败时保留既有结果。用量不确定时按原回执待核对，同一回执重复到达只结算一次。[厂家与员工额度](厂家与员工额度.md) · [受管模型调用](../../doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/model/ManagedAgentModel.java)

### 8081 评审验收

| 场景 | 通过条件 |
| --- | --- |
| 独立开关 | 工作台关闭、模型选择开启时，两套聊天界面均可读写偏好。关闭模型选择后能看到准确原因，普通聊天仍按该环境的默认配置运行。 |
| 真实执行 | 在同一会话先用 GPT，再切换到 Qwen 追问前文。用隔离供应商测试端点核对两次请求的模型 ID 和第二次请求携带的历史消息。刷新后、从另一入口进入后都显示 Qwen。 |
| 隔离与并发 | 主管和检查人员只能修改本人的会话。同一账号的另一个会话保留原选择。两个标签页从相同版本提交不同选择时，一次成功，一次收到冲突，已提交结果可读回。 |
| 任务边界 | 对运行中或等待确认的任务尝试切换时，服务端说明锁定原因。继续执行沿用原模型。任务结束后可以切换。恢复默认、模型下线和读取失败都有对应提示。 |
| 扣费与恢复 | 只切换模型时两份账本均无扣减。用可控回执验证主管、员工、跨厂家的备用尝试、超限拦截和重复回执。每笔消耗都能对应到实际尝试。 |

本轮实施按评审分支固定提交在 8081 验收。用户确认效果后，再将同一候选版本合并到 `java-cloud` 并更新 8080。[单体评审与发布规则](../开发规则.md)

### 单机配置与核查入口

评审 Compose 的后端设置 `AGENT_MODEL_SELECTION_ENABLED=true`。其他环境可单独设置这个开关，省略时沿用 `AGENT_WORKBENCH_ENABLED`。关闭开关后，已登录用户读取偏好接口会得到 `{"enabled":false}`，再次启用时能读回已有选择。会话偏好和命令回执复用 compact 库的 `workflow_instance`。主管和检查人员分别以当前登录账号核验会话归属。

在「执行追溯 → 实际模型调用」核对本次首选、各厂家候选与执行结果。完整运行日志关闭时，会话保存最近一次执行的有限事件摘要。更早的逐请求核对依赖已启用的运行日志及额度流水。费用和 token 结算继续使用各实际尝试的用量回执。
