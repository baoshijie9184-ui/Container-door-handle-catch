# Harness 多智能体编排与分层记忆

> 返回总览：[项目亮点与面试指南](../项目亮点与面试指南.md)

## 1. 本章目标

本章独立讲解 Harness Agent 如何使用 StateGraph 将自然语言请求转换为可路由、可恢复、可确认的业务流程，以及 MySQL、Mem0、ChromaDB 分别承担什么记忆职责。

### 1.1 术语翻译与作用

| 英文术语 | 中文名称 | 在本项目中的作用 |
| --- | --- | --- |
| Harness Agent | 智能体编排框架 | 组织多个业务智能体协同处理用户请求 |
| Agent | 智能体 | 负责检测、资源、报表或运维等一种业务能力 |
| StateGraph | 状态图 | 按节点和条件边控制智能体执行流程 |
| Checkpoint | 检查点 | 将会话执行状态持久化，支持中断后恢复 |
| RouterNode | 路由节点 | 识别用户意图并选择目标智能体 |
| SlotFillingNode | 槽位补全节点 | 发现缺失参数并继续向用户追问 |
| HumanConfirmNode | 人工确认节点 | 修改数据前暂停流程并等待用户确认 |
| ResponderNode | 回答生成节点 | 汇总工具结果并组织最终回答 |
| FallbackNode | 降级处理节点 | 在异常或循环超限时生成可解释的兜底回答 |
| RAG | 检索增强生成 | 从项目知识库检索资料后辅助模型回答 |
| SSE | 服务器发送事件 | 后端持续向浏览器推送流式回答 |
| Mem0 | 长期记忆组件 | 按用户保存偏好和跨会话历史信息 |
| ChromaDB | 向量知识库 | 保存并检索项目公共知识 |

## 2. 业务问题

单一大模型直接处理全部业务时容易出现：

- 提示词不断膨胀，检测、资源和报表规则互相干扰。
- 多轮对话丢失任务编号、时间范围等已收集参数。
- 修改操作未经确认直接进入业务服务。
- 路由与槽位补全循环调用，持续消耗模型 Token。
- 回答脱离数据库和企业知识库。

## 3. 模块框架图

~~~text
用户输入问题或操作指令
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤一：装载三层上下文                                      │
│                                                              │
│  MySQL 检查点（Checkpoint）：恢复会话状态与最近消息          │
│  ChromaDB 检索增强生成（RAG）：检索项目知识                  │
│  Mem0 长期记忆：补充当前用户的偏好与历史信息                 │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤二：路由节点（RouterNode）识别意图并选择执行路径        │
│                                                              │
│  检测任务 → 检测智能体          资源调度 → 资源智能体         │
│  报表查询 → 报表智能体          运维诊断 → 运维智能体         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                      参数是否完整？
                           │
                    ┌──────┴──────┐
                    │             │
                   否             是
                    │             │
                    ▼             ▼
           槽位补全节点        进入目标智能体
           追问缺失参数             │
                    │               ▼
                    └───────> 是否属于修改操作？
                                    │
                             ┌──────┴──────┐
                             │             │
                            是             否
                             │             │
                             ▼             ▼
┌───────────────────────────────┐   ┌──────────────────────────┐
│  步骤三A：人工确认            │   │  步骤三B：直接执行      │
│                               │   │                          │
│  保存待确认动作与检查点       │   │  智能体调用业务工具      │
│  中断状态图，确认后恢复执行   │   │  返回结构化执行结果      │
└───────────────┬───────────────┘   └────────────┬─────────────┘
                │                                │
                └───────────────┬────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤四：回答节点统一组织答案并通过 SSE 流式输出             │
│                                                              │
│  异常或循环超限 → 降级节点 → 返回可解释的兜底结果            │
└──────────────────────────────────────────────────────────────┘
~~~

### 3.1 Agent 之间的消息传递与沟通机制

#### 3.1.1 核心结论

项目中的多个 Agent 不通过 Kafka、RPC 或 HTTP 互相发送消息，也不会彼此自由对话。系统采用“中心路由 + 共享状态”的黑板模式：`RouterNode` 负责决定下一步由谁执行，所有节点通过同一个 `AgentState` 读取输入、补充信息并写回结果，`StateGraph` 根据状态中的意图和阶段选择下一节点。

| 英文术语 | 中文名称 | 项目中的含义 |
| --- | --- | --- |
| Blackboard Pattern | 黑板模式 | 多个节点围绕同一份共享状态协作 |
| AgentState | 智能体状态 | 一次请求在各节点之间传递的统一数据容器 |
| RouterNode | 路由节点 | 判断意图、目标 Agent 和是否需要确认 |
| Conditional Edge | 条件边 | 根据状态字段决定下一个执行节点 |
| Checkpoint | 检查点 | 把状态保存到 MySQL，支持跨请求恢复 |
| Slot | 槽位/业务参数 | 任务编号、设备编号、时间范围等执行条件 |

#### 3.1.2 消息传递框架

~~~text
用户输入自然语言消息
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤一：编排服务创建 AgentState                             │
│                                                              │
│  写入用户输入、用户身份、会话编号和页面上下文                │
│  恢复最近消息、会话摘要、已收集槽位和中间结果                │
│  注入 ChromaDB 公共知识和 Mem0 用户长期记忆                  │
└──────────────────────────┬───────────────────────────────────┘
                           │ 同一个 AgentState
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤二：RouterNode 生成路由决定                             │
│                                                              │
│  targetAgent：目标智能体                                     │
│  intent：查询或修改意图                                      │
│  confirmationRequired：是否需要人工确认                      │
│  slots / missingSlots：已有参数和缺失参数                    │
└──────────────────────────┬───────────────────────────────────┘
                           │
                     参数是否完整？
                           │
                    ┌──────┴──────┐
                    │             │
                   否             是
                    │             │
                    ▼             ▼
             槽位补全节点       查询还是修改？
             生成追问消息           │
                              ┌─────┴─────┐
                              │           │
                             查询         修改
                              │           │
                              ▼           ▼
                       目标专业 Agent   人工确认节点
                              │           │
                              │      保存待确认动作和检查点
                              │           │
                              │      用户确认后恢复状态图
                              │           │
                              └─────┬─────┘
                                    ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤三：专业 Agent 读取状态并调用业务服务                   │
│                                                              │
│  检测 Agent / 资源 Agent / 报表 Agent / 运维 Agent           │
│  将执行内容、结果类型、意图和退出原因写回 AgentState         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤四：编排服务读取结果                                    │
│                                                              │
│  保存聊天消息和最新检查点                                    │
│  普通接口返回文字或业务卡片，流式接口通过 SSE 持续输出       │
└──────────────────────────────────────────────────────────────┘
~~~

#### 3.1.3 AgentState 传递的关键信息

| 状态键 | 中文含义 | 主要写入者 | 主要读取者 |
| --- | --- | --- | --- |
| `user_input` | 当前用户输入 | 编排服务 | 路由节点、专业 Agent |
| `username` | 当前用户身份 | 编排服务 | 专业 Agent、确认节点 |
| `thread_id` | 会话编号 | 编排服务 | 检查点、确认节点 |
| `recent_msgs` | 最近多轮消息 | 上下文恢复逻辑 | 路由节点、专业 Agent |
| `summary` | 会话摘要 | 上下文构建器 | 路由节点 |
| `rag_context` | 公共知识检索结果 | 编排服务 | 各专业 Agent |
| `route_decision` | 路由决定 | RouterNode | StateGraph、确认节点 |
| `intent` | 查询或修改意图 | RouterNode | 条件边、专业 Agent |
| `slots` | 已收集业务参数 | 路由节点、槽位节点 | 后续专业 Agent |
| `missing_slots` | 缺少的业务参数 | RouterNode | SlotFillingNode |
| `intermediate` | 多轮中间结果 | 各业务节点 | 后续节点 |
| `confirmed` | 是否已经人工确认 | 恢复流程 | 确认节点、专业 Agent |
| `pending_action_id` | 待确认动作编号 | HumanConfirmNode | 编排服务、前端 |
| `result_content` | 最终内容 | 专业 Agent 或回答节点 | 编排服务 |
| `result_type` | 文本、业务卡片等结果类型 | 专业 Agent | 编排服务、前端 |
| `error` | 节点执行异常 | 状态图执行器 | FallbackNode |

`AgentState` 为每次请求单独创建。虽然内部使用 `ConcurrentHashMap` 为将来的并行节点预留线程安全基础，但当前 `CompiledGraph` 仍按循环逐个执行节点，因此现阶段是顺序编排，不是多个 Agent 同时讨论。

#### 3.1.4 三种典型沟通链路

查询链路：

~~~text
“查询 TASK-1001 的检测结果”
  → RouterNode 写入 DETECTION_QUERY
  → StateGraph 选择 DetectionAgentNode
  → DetectionAgentNode 查询任务并写回 result_content
  → 编排服务将结果保存并返回前端
~~~

参数补全链路：

~~~text
“开始检测”
  → RouterNode 发现缺少 taskId
  → phase=COLLECTING，missing_slots=[taskId]
  → SlotFillingNode 生成“请提供任务编号”
  → 下一轮恢复已有状态并合并用户补充的 taskId
  → 参数完整后进入 DetectionAgentNode
~~~

写操作确认链路：

~~~text
“把 TASK-1001 标记为返工”
  → RouterNode 写入 DETECTION_ACTION
  → HumanConfirmNode 保存待确认动作
  → MySQL 保存 AgentState Checkpoint 并暂停
  → 用户点击确认，恢复时写入 confirmed=true
  → 根据 route_decision 进入 DetectionAgentNode
  → 执行返工并返回结果
~~~

#### 3.1.5 持久化与实时输出

- MySQL `Checkpoint` 保存可序列化的 `AgentState`，用于跨请求、应用重启和人工确认后的恢复。
- `chat_message` 保存用户可见的完整聊天历史，它与机器执行状态不是同一类数据。
- ChromaDB 提供项目公共知识，Mem0 提供按用户隔离的长期记忆，两者作为上下文注入，不承担 Agent 节点调度。
- SSE 流式消费者只在当前 HTTP 请求中有效，被标记为临时字段，不会写入 Checkpoint。
- Kafka 只用于 Spring Boot 与 Python 推理 Worker 之间的检测任务消息，不参与 Java 内部 Agent 通信。

#### 3.1.6 当前能力边界

当前实现属于中心路由型多 Agent，而不是多个 Agent 自主讨论型架构：

- 一次路由通常只选择一个专业 Agent 执行。
- Agent 之间没有点对点消息通道。
- 没有多个 Agent 并行回答后投票或仲裁。
- 没有 Supervisor Agent 汇总多个专业 Agent 的不同意见。
- 协作信息必须写入 `AgentState`，不能依赖某个 Agent 的进程内私有变量。

### 3.2 主 Agent 与子 Agent 如何协同

#### 3.2.1 项目中的“主 Agent”是什么

本项目没有实现一个可以自由思考、再和多个子 Agent 讨论的 Supervisor 大模型。这里所说的“主 Agent”是逻辑上的编排层，由三个组件共同承担：

| 组件 | 主 Agent 职责 |
| --- | --- |
| `AgentOrchestratorServiceImpl` | 校验用户和会话、恢复上下文、注入 RAG 与 Mem0、启动状态图、保存最终消息 |
| `CompiledGraph` | 按节点和条件边执行、保存检查点、执行重试、运行守卫和异常降级 |
| `RouterNode` | 识别意图、目标 Agent、已有槽位和是否属于修改操作 |

检测、资源、报表和运维节点是专业子 Agent。子 Agent 只处理自己负责的业务，不负责决定整张图的执行顺序，也不能绕过编排层直接调度另一个子 Agent。

`SlotFillingNode`、`HumanConfirmNode`、`ResponderNode` 和 `FallbackNode` 属于控制节点：它们负责补参数、人工确认、统一回答和异常兜底，不属于专业业务子 Agent。

#### 3.2.2 主从协同框架

~~~text
用户发送消息
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  逻辑主 Agent：AgentOrchestratorServiceImpl                  │
│                                                              │
│  校验租户和会话 → 限流 → 恢复 Checkpoint                   │
│  注入最近消息、RAG 公共知识和 Mem0 用户记忆                 │
│  创建本轮唯一的 AgentState                                  │
└──────────────────────────┬───────────────────────────────────┘
                           │ 共享 AgentState
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  主 Agent 调度内核：CompiledGraph + RouterNode              │
│                                                              │
│  写入 intent、targetAgent、slots、currentNode                │
│  通过条件边选择一个专业子 Agent                              │
└──────────────────────────┬───────────────────────────────────┘
                           │
             ┌─────────────┼─────────────┬─────────────┐
             │             │             │             │
             ▼             ▼             ▼             ▼
       检测子 Agent   资源子 Agent   报表子 Agent   运维子 Agent
             │             │             │             │
             └─────────────┴──────┬──────┴─────────────┘
                                  │ 写回同一个 AgentState
                                  ▼
┌──────────────────────────────────────────────────────────────┐
│  resultContent + resultType + intent + exitReason            │
│  → ResponderNode 统一结果                                    │
│  → 主 Agent 保存消息和 Checkpoint                            │
│  → HTTP 或 SSE 返回前端                                      │
└──────────────────────────────────────────────────────────────┘
~~~

协作过程中没有“子 Agent A 直接给子 Agent B 发消息”。如果检测子 Agent 产生的信息需要后续节点使用，它必须写入 `AgentState`；状态图再根据条件边把状态交给下一个节点。这样可以记录每次路由、统一持久化，也避免专业 Agent 形成不可观察的私有调用链。

#### 3.2.3 一次协同执行的六个步骤

1. 编排服务从登录态构建 `TenantContext`，校验会话属于当前用户。
2. 编排服务从 MySQL Checkpoint 选择性恢复允许跨轮保留的字段，再注入本轮输入。
3. `RouterNode` 把路由决定写入 `AgentState`，自己不直接执行检测、资源或报表业务。
4. `CompiledGraph` 根据 `intent`、会话阶段和确认状态选择控制节点或一个专业子 Agent。
5. 子 Agent 调用受限的业务 Service，把结构化结果写回 `AgentState`，不直接向前端返回。
6. 回答节点和编排服务统一保存结果，通过普通 HTTP 或 SSE 输出。

当前 `CompiledGraph` 顺序执行节点。`AgentState` 使用线程安全 Map 是为了保证状态容器的可扩展性，不表示四个专业子 Agent 会在当前版本中同时并行执行。

### 3.3 如何保证 Agent 执行流程安全

#### 3.3.1 五层安全边界

| 安全层 | 项目措施 | 解决的问题 |
| --- | --- | --- |
| 身份入口 | `TenantPrincipal` 转换为 `TenantContext`，并校验会话所有者 | 防止越权使用别人的会话 |
| 状态传播 | `tenant_user_id` 写入 `AgentState`，缺失时 `requireTenantContext()` 直接失败 | 防止节点脱离真实身份执行 |
| 参数完整性 | Slot Filling 收集任务号、工单号等必需参数 | 防止基于不完整参数调用业务服务 |
| 高风险操作 | 修改意图必须经过 `HumanConfirmNode`，先预览、再确认 | 防止模型直接执行返工、放行、报废等操作 |
| 运行边界 | 轮数、耗时、节点访问次数和重复路由守卫 | 防止死循环和资源无限占用 |

~~~text
用户请求
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1：身份与会话校验                                     │
│  requireTenant + verifySessionOwner + 每用户请求限流         │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2：路由与参数校验                                     │
│  参数不完整 → 只追问，不调用专业子 Agent                    │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
                    查询还是修改？
                     ┌─────┴─────┐
                     │           │
                    查询         修改
                     │           │
                     ▼           ▼
               专业子 Agent   保存待确认动作
                                 │
                                 ▼
                         用户明确确认后恢复
                     └─────┬─────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 3：运行守卫                                           │
│  轮数、时间、节点访问和重复路由任一超限 → Fallback          │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
             保存 Checkpoint、审计状态并返回结果
~~~

#### 3.3.2 高风险动作的并发保护

第一次进入 `HumanConfirmNode` 时只生成操作预览和 `PENDING` 动作，不执行真实修改。用户确认时，数据库使用条件状态更新抢占执行权：

~~~text
PENDING
   │ 用户确认，且 expectedStatus=PENDING 更新成功
   ▼
EXECUTING ──────执行成功──────> COMPLETED
   │
   └────────执行异常──────────> FAILED

PENDING ───────用户取消────────> CANCELLED
~~~

两个确认请求同时到达时，只有一个能够把 `PENDING` 改为 `EXECUTING`；另一个会收到“正在处理或已处理”，从而降低重复点击造成重复业务写入的风险。

#### 3.3.3 运行守卫的真实参数

| 守卫 | 当前默认值 | 触发后的处理 |
| --- | ---: | --- |
| 最大状态图轮数 | 15 | 设置 `MAX_ITERATIONS` 并进入 Fallback |
| 单轮最大执行时间 | 15000 ms | 设置 `GUARD_BREAK` 并进入 Fallback |
| 单节点最大访问次数 | 4 | 保护性中断，记录触发节点 |
| 同一路由最大连续重复次数 | 3 | 保护性中断，记录重复路由 |
| 节点与路由轨迹保留长度 | 24 | 只保留最近轨迹，控制 Checkpoint 大小 |
| Router 节点重试配置 | 声明 2 次 | 执行器提供 500 ms、1000 ms 指数退避代码路径，但尚缺专门的重试映射回归测试 |

重试能力由状态图按节点配置。当前只对 `RouterNode` 声明了两次重试，其他专业子 Agent 默认不重试；而且现有测试只覆盖运行守卫，没有单独验证 `current_node` 与重试配置的映射，因此本项目不能把“Router 一定重试两次”作为已经验收的强保证。运行时间也是在节点切换边界检查，无法强制中断一个已经阻塞在外部调用中的节点。

### 3.4 Agent 失败后如何恢复

#### 3.4.1 失败处理与恢复框架

~~~text
节点开始执行
    │
    ▼
执行成功？──────────────是──────────────> 保存 Checkpoint → 下一节点
    │
    否
    ▼
该节点配置了重试？
    │
 ┌──┴──┐
 │     │
是     否
 │     │
 ▼     │
指数退避重试
 │     │
仍失败 ┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  写入 error 与 exitReason                                   │
│  执行 Fallback，返回“不基于不完整信息编造结果”的说明       │
│  保存最终 Checkpoint 和节点/路由轨迹                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                  用户稍后重新发起请求
                  或从待确认检查点恢复
~~~

#### 3.4.2 不同失败场景的恢复策略

| 失败场景 | 当前处理 | 恢复方式 |
| --- | --- | --- |
| 配置为可重试的节点发生短暂异常 | 执行器设计为指数退避后再次执行；Router 声明最多 2 次 | 重试路径需要补充专门回归测试后才能作为强保证 |
| 节点最终执行失败 | 写入错误，进入 Fallback，保存检查点 | 用户补充信息或重新发起请求 |
| 死循环或超时 | 运行守卫设置 `GUARD_BREAK` | Fallback 给出原因，避免继续消耗资源 |
| 等待人工确认 | 保存当前节点、状态和待确认动作后暂停 | 用户确认后执行 `resume(tenant, sessionId, confirmed=true)` |
| 应用实例重启 | 状态保存在 MySQL `state_json` | 新实例按租户和会话加载 Checkpoint |
| 确认后的业务执行失败 | 动作从 `EXECUTING` 更新为 `FAILED` 并记录错误摘要 | 用户查看失败信息后重新发起，避免把失败伪装成成功 |
| 普通对话 Checkpoint 读取失败 | 记录警告并创建本轮新状态 | 当前问题仍可继续回答，但旧槽位和执行阶段无法精确恢复 |
| 确认恢复时找不到 Checkpoint | 直接抛出“无法恢复”错误 | 不允许缺少执行状态时继续高风险修改 |

#### 3.4.3 Checkpoint 恢复为什么安全

恢复不是只凭 `sessionId` 读取状态。`MySqlCheckpointer` 使用 `tenant.userId + threadId` 查询和更新，加载成功后还会把当前登录用户的 `userId` 和 `username` 重新写入状态。缺少租户用户 ID 时，节点调用 `requireTenantContext()` 会立即失败，不会退化成只按会话号执行。

~~~java
AgentState state = checkpointer.load(tenant, threadId);
if (state == null) {
    throw new StateGraphException("无法恢复：未找到 checkpoint");
}
state.set(AgentState.KEY_TENANT_USER_ID, tenant.userId());
state.set(AgentState.KEY_USERNAME, tenant.username());
state.setAll(Map.of(AgentState.KEY_CONFIRMED, true));
~~~

#### 3.4.4 当前恢复能力边界

- Checkpoint 在每个节点执行后保存，异常、守卫中断和等待确认时也会尝试保存。
- Checkpoint 保存失败时当前实现记录警告，不会回滚已经完成的外部业务调用，因此不能宣传为“任意故障都能无损恢复”。
- 项目没有通用的跨 Agent 分布式事务和自动补偿框架。业务修改是否回滚仍由具体 Service 的事务边界决定。
- 普通对话恢复失败可以降级为新状态；高风险确认恢复失败则采用失败关闭，不会猜测原动作继续执行。
- 当前主要恢复粒度是“会话状态图和人工确认动作”，不是对任意节点进行指令级断点续跑。
- 当前测试已覆盖循环守卫、轨迹记录、Checkpoint 和确认恢复，但尚缺“指定节点按配置次数重试”的独立回归测试。

## 4. StateGraph 状态设计

AgentState 是节点之间传递的统一状态容器。核心状态包括：

| 状态 | 含义 |
| --- | --- |
| sessionId / username | 会话与用户上下文 |
| recentMessages | 最近多轮消息 |
| collectedSlots | 已收集业务参数 |
| missingSlots | 尚缺少的参数 |
| intent / targetAgent | 意图和目标智能体 |
| conversationPhase | 收集参数、执行、等待确认等阶段 |
| pendingActionId | 待确认动作编号 |
| currentNode / exitReason | 当前节点与退出原因 |
| ragContext | 公共知识检索结果 |
| user_memories | 用户长期记忆 |

## 5. 数据库存储

### 5.1 chat_session

| 字段 | 作用 |
| --- | --- |
| session_id | StateGraph threadId |
| username | 会话归属用户 |
| state_json | AgentState 序列化内容 |
| checkpoint_version | 检查点版本 |
| checkpoint_node | 保存时所在节点 |
| checkpoint_exit_reason | 中断或退出原因 |
| checkpoint_updated_at | 最近保存时间 |

### 5.2 chat_message

| 字段 | 作用 |
| --- | --- |
| session_id | 关联会话 |
| role | user 或 assistant |
| message_type | TEXT、业务卡片、待确认卡片 |
| content | 用户可见内容 |
| intent | 本轮识别意图 |
| action_id | 对应待确认动作 |

### 5.3 chat_pending_action

动作状态机：

~~~mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> EXECUTING: 用户确认且抢占成功
    PENDING --> CANCELLED: 用户取消
    EXECUTING --> COMPLETED: 业务执行成功
    EXECUTING --> FAILED: 业务执行异常
~~~

## 6. 核心代码

### 6.1 恢复上下文

文件：src/main/java/com/ruanzhu/doorhandlecatch/service/impl/AgentOrchestratorServiceImpl.java

~~~java
AgentState state = AgentState.create(
        sessionId, request.getContent(), username);
AgentState previous = checkpointer.load(sessionId);
if (previous != null) {
    for (String key : CONTEXT_KEYS) {
        Object value = previous.get(key, Object.class);
        if (value != null) {
            state.set(key, value);
        }
    }
}
~~~

代码创建本轮新状态，只恢复允许跨轮保留的字段，避免上一轮临时结果污染本轮执行。

### 6.2 注入知识与记忆

~~~java
String ragContext =
        ragKnowledgeService.retrieveContext(request.getContent());
List<Map<String, Object>> memories =
        mem0Client.searchMemories(username, request.getContent(), 5);
~~~

RAG 面向公共知识；Mem0 面向用户长期事实；Checkpoint 面向工作流状态；chat_message 面向完整聊天历史。

### 6.3 条件抢占待确认动作

~~~java
boolean claimed = chatSessionService.transitionPendingAction(
        sessionId, actionId, "PENDING", "EXECUTING", null);
if (!claimed) {
    throw new BusinessException("待确认动作正在处理或已处理");
}
AgentState result = chatGraph.resume(
        sessionId, Map.of(AgentState.KEY_CONFIRMED, true));
~~~

expectedStatus 条件使并发确认请求只有一个能够进入 EXECUTING。

## 7. 运行守卫

- 最大执行轮数防止状态图无限运行。
- 最大执行时间限制单次请求资源占用。
- 单节点最大访问次数防止节点自循环。
- 相同路由重复阈值防止 Router 与 SlotFilling 反复跳转。
- 节点异常进入 Fallback，返回可理解的失败说明。

## 8. 本地语音输入与中文识别

### 8.1 术语翻译

| 英文术语 | 中文名称 | 本项目中的作用 |
| --- | --- | --- |
| ASR | 自动语音识别 | 将用户说话内容转换为文字 |
| faster-whisper | Whisper 高性能推理实现 | 在本地运行中文语音识别模型 |
| MediaRecorder | 浏览器媒体录制接口 | 获取麦克风音频并生成语音文件 |
| FastAPI | Python 接口框架 | 对外提供本地语音识别接口 |
| VAD | 语音活动检测 | 过滤静音片段，减少无效识别内容 |
| INT8 | 8 位整数计算精度 | 降低 CPU 推理时的内存和计算开销 |
| MIME Type | 媒体类型 | 描述上传音频是 WebM、MP4、OGG 等格式 |
| hotwords | 热词 | 提高“质检、工单追溯、缺陷证据”等领域词汇的识别概率 |
| TTS | 语音合成 | 将文字转换成语音；当前项目尚未实现 |

### 8.2 语音输入框架图

~~~text
用户点击麦克风并开始说话
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤一：浏览器录音                                          │
│                                                              │
│  MediaRecorder 获取麦克风音频                                │
│  自动选择 WebM、MP4 或 OGG 等浏览器支持的格式                │
│  最长录音 60 秒，到达上限后自动停止                          │
└──────────────────────────┬───────────────────────────────────┘
                           │ 上传音频文件
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤二：Spring Boot 接收与安全校验                          │
│                                                              │
│  POST /api/chat-assistant/voice/transcribe                   │
│  校验文件非空、媒体格式和 10 MB 大小上限                     │
│  仅向配置白名单中的语音识别服务转发                          │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤三：本地 faster-whisper 中文识别                        │
│                                                              │
│  FastAPI 服务：127.0.0.1:9001                               │
│  默认模型：base    运行设备：CPU    计算精度：INT8           │
│  启用静音过滤、工业质检提示词和领域热词                      │
└──────────────────────────┬───────────────────────────────────┘
                           │ 返回识别文字
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤四：用户确认                                            │
│                                                              │
│  识别文字只填入输入框，不自动发送                            │
│  用户检查或修改文字后，再手动提交给智能体                    │
└──────────────────────────────────────────────────────────────┘
~~~

### 8.3 为什么采用本地 faster-whisper

| 方案 | 优点 | 局限 | 项目选择 |
| --- | --- | --- | --- |
| 浏览器原生语音识别 | 接入简单 | 浏览器兼容性和服务可用性不可控 | 只使用浏览器录音，不依赖其识别能力 |
| 第三方云语音服务 | 模型成熟、运维成本低 | 音频需要出网，依赖费用和外部服务 | 保留可配置接入能力，不作为默认方案 |
| 本地 faster-whisper | 数据留在本机、可离线、模型可替换 | 需要本地计算资源和独立进程 | 作为当前默认语音识别实现 |

本地服务与 Java 进程分离，避免 Python 原生推理依赖进入 Spring Boot，同时可以独立调整模型大小、运行设备和计算精度。默认采用 `base + CPU + INT8`，优先保证普通开发机器可以运行，并避免与图像检测任务争抢显存。

### 8.4 前端录音核心代码

~~~javascript
mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
mediaRecorder = new MediaRecorder(mediaStream, { mimeType })
mediaRecorder.ondataavailable = event => audioChunks.push(event.data)
mediaRecorder.onstop = handleVoiceRecorded
mediaRecorder.start()
~~~

录音结束后，前端把音频片段组合成 `Blob` 文件，调用 `/api/chat-assistant/voice/transcribe`。浏览器会按支持情况依次选择 WebM + Opus、WebM、MP4 或 OGG + Opus，以兼容不同浏览器。

~~~javascript
const audioBlob = new Blob(audioChunks, { type: selectedVoiceMimeType })
const response = await transcribeChatVoice(audioBlob, `voice.${extension}`)
draft.value = response.data?.data?.text || ''
~~~

识别成功后只更新输入框草稿 `draft`，不会直接调用消息发送方法。

### 8.5 本地识别核心代码

~~~python
model = WhisperModel(
    os.getenv("ASR_MODEL", "base"),
    device=os.getenv("ASR_DEVICE", "cpu"),
    compute_type=os.getenv("ASR_COMPUTE_TYPE", "int8"),
)

segments, _ = model.transcribe(
    audio_path,
    language="zh",
    vad_filter=True,
    initial_prompt=INDUSTRIAL_PROMPT,
    hotwords=INDUSTRIAL_HOTWORDS,
)
~~~

`language="zh"` 指定中文识别；`vad_filter=True` 开启语音活动检测；工业提示词与热词用于增强“质检队列、工单追溯、批次追溯、缺陷证据”等项目词汇。

### 8.6 核心配置

| 环境变量 | 默认值 | 中文说明 |
| --- | --- | --- |
| `ASR_MODEL` | `base` | Whisper 模型规格，可按机器性能调整 |
| `ASR_DEVICE` | `cpu` | 模型运行设备 |
| `ASR_COMPUTE_TYPE` | `int8` | 模型计算精度 |
| `ASR_MAX_UPLOAD_BYTES` | `10485760` | Python 服务允许的最大音频大小，默认 10 MB |
| `CHAT_ASSISTANT_VOICE_TRANSCRIBE_URL` | 空，启动脚本配置本机地址 | Spring Boot 转发语音的目标接口 |
| `CHAT_ASSISTANT_VOICE_TRANSCRIBE_ALLOWED_HOSTS` | 本机地址 | 允许访问的语音服务主机白名单 |
| `CHAT_ASSISTANT_VOICE_CONNECT_TIMEOUT_MS` | `1500` | 建立连接的最长等待时间，单位毫秒 |
| `CHAT_ASSISTANT_VOICE_READ_TIMEOUT_MS` | `15000` | 等待识别结果的最长时间，单位毫秒 |
| `CHAT_ASSISTANT_VOICE_MAX_BYTES` | `10485760` | Java 接口允许的最大音频大小，默认 10 MB |

### 8.7 安全性与业务保护

- 后端只接受 HTTP 或 HTTPS 语音服务地址，并校验目标主机白名单，降低服务端请求伪造风险。
- 默认识别服务只监听 `127.0.0.1`，不直接向局域网或公网开放。
- 前后端同时限制录音时长和文件大小，避免超大音频长期占用内存与推理资源。
- 请求结束后删除临时音频文件，减少用户语音在磁盘上的残留时间。
- 识别文本必须由用户确认后才能发送，避免误识别直接触发返工、放行、隔离或报废操作。

### 8.8 当前能力边界

- 当前只有“语音转文字”的自动语音识别功能，没有“文字转语音”的语音合成功能。
- 默认 `base` 模型在准确率和资源消耗之间取平衡，不代表所有口音和嘈杂环境下都能准确识别。
- 热词只能提高领域词汇的识别概率，不能替代用户确认和业务权限校验。
- 本地语音服务不可用时，系统会返回明确错误，用户仍可使用键盘输入，不影响智能助手其他功能。

## 9. 测试证据

- MySqlCheckpointerTest：检查点序列化、加载和清理。
- AgentOrchestratorServiceImplTest：消息处理、确认与恢复。
- AgentGraphRunMonitorImplTest：运行指标与守卫。
- 各 AgentServiceImplTest：专业智能体业务边界。
- chat-voice-input-contract.test.cjs：录音状态、格式选择、最长时长和识别结果回填。
- SpeechTranscriptionServiceImplTest：文件校验、服务白名单、响应解析和异常处理。
- test_asr_service.py：健康检查、格式处理、文件大小限制和临时文件清理。

## 10. 面试问答

### 为什么 Checkpoint 不直接使用聊天记录代替？

聊天记录只保存用户可见文本，不能表示当前节点、已收集槽位、待确认动作和中间结果。Checkpoint 保存机器执行状态，才能精确恢复中断流程。

### 为什么要拆分多个 Agent？

各业务的数据源、参数和权限不同。专业智能体缩短提示词、限制依赖范围，并能单独测试和扩展。

### 如何避免 Agent 死循环？

状态图同时限制轮数、时间、节点访问次数和重复路由次数；超过阈值后进入 Fallback。

### 为什么语音识别结果不自动发送？

智能助手可以触发返工、放行、隔离和报废等业务动作。语音存在误识别风险，因此项目只把识别结果填入输入框，要求用户确认后手动发送，把语音识别与业务执行之间增加一道人工安全边界。

### 为什么使用本地 faster-whisper，而不是直接使用浏览器语音识别？

浏览器只负责标准化录音，本地 faster-whisper 负责统一识别。这样不依赖不同浏览器的语音服务实现，音频默认不出本机，还可以配置模型大小、计算设备和工业领域热词。
