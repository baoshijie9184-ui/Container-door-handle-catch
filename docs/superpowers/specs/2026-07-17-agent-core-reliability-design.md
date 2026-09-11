# Agent 核心可靠性完善设计

## 1. 背景与目标

当前 StateGraph 已具备路由、专业 Agent、人工确认、Checkpoint 和 Fallback，但核心执行链存在三个问题：

1. `CompiledGraph` 在节点包装器更新 `current_node` 之前读取重试配置，导致 Router 的重试次数可能作用到后继节点。
2. Detection、Resource、Report、Ops 等专业节点自行设置 `exit_reason=COMPLETE`，执行循环会在路由到 `ResponderNode` 之前结束。
3. `AgentExecutionResult` 生成后直接写入共享状态，没有统一、确定性的结果完整性检查。

本次改造的目标是修正节点重试语义，建立统一的结果质量门禁，并保证所有普通回答由 `ResponderNode` 统一结束流程。

## 2. 范围

### 2.1 本次包含

- 重试配置严格绑定目标节点名称。
- 新增确定性的 `ResultQualityNode`。
- 专业 Agent 和槽位追问结果经过质量门禁后再进入 `ResponderNode`。
- 只有 `ResponderNode` 为正常回答设置 `exit_reason=COMPLETE`。
- 质量检查不通过时进入现有 `FallbackNode`。
- 为重试、质量门禁和完整执行链增加自动化回归测试。

### 2.2 本次不包含

- 不增加基于大模型的 Judge/Critic Agent。
- 不实现服务重启后的后台任务自动扫描与续跑。
- 不实现跨 MySQL、Kafka、OSS 的统一事务补偿。
- 不调整现有业务 Agent 的提示词和业务查询逻辑。
- 不为写操作增加新的自动重试，避免非幂等操作被重复执行。

## 3. 方案选择

采用“独立确定性质量门禁”方案。相较于仅在 `ResponderNode` 中增加判断，该方案将“结果是否合法”和“如何向用户结束本轮回复”拆分为两个单一职责节点；相较于使用 LLM 评审，结果可重复、延迟更低，也不会增加模型费用。

## 4. 目标执行链

```text
用户请求
   │
   ▼
Router ──需要补充参数──> SlotFilling
   │                         │
   │                         └──生成追问──┐
   ▼                                     │
专业 Agent                               │
Detection / Resource / Report / Ops      │
   │                                     │
   └─────────────────┬───────────────────┘
                     ▼
             ResultQualityNode
                     │
              结果是否合格？
               ┌─────┴─────┐
               │           │
              否           是
               │           │
               ▼           ▼
           抛出异常     ResponderNode
               │           │
               ▼           ▼
          FallbackNode  COMPLETE
```

人工确认仍保持独立中断语义：`HumanConfirmNode` 在等待确认时设置 `PENDING_CONFIRMATION`；确认后恢复图并执行目标专业 Agent，随后进入质量门禁。

## 5. 组件设计

### 5.1 节点名称感知的重试执行

将内部调用从：

```java
executeWithRetry(Node node, AgentState state)
```

改为：

```java
executeWithRetry(String nodeName, Node node, AgentState state)
```

重试次数直接使用 `nodeMaxRetries.getOrDefault(nodeName, 0)` 获取，不再依赖状态中可能滞后的 `current_node`。

`.setNodeRetry("router", 2)` 的确定含义为：Router 首次执行失败后最多再执行两次，总尝试次数最多为三次。现有指数退避策略保持为 500ms、1s。

本次只修正重试绑定关系，不扩展重试范围。未配置重试的专业 Agent、质量门禁、Responder 和 Fallback 均只执行一次。

### 5.2 ResultQualityNode

新增 `ResultQualityNode`，读取共享 `AgentState` 并执行以下确定性检查：

1. 状态中不存在 `error`。
2. `result_content` 是非空白字符串。
3. `result_type` 是允许的类型：`TEXT`、`BUSINESS_CARD` 或 `PENDING_ACTION`。
4. `intent` 是非空白字符串。

普通专业 Agent 和槽位追问可以产生 `TEXT`，检测与运维 Agent 还会产生 `BUSINESS_CARD`；`PENDING_ACTION` 由人工确认节点直接中断，不进入质量门禁，允许该类型是为了保持状态契约兼容。

检查通过时节点不设置 `exit_reason`，让图继续进入 `ResponderNode`。检查失败时抛出 `StateGraphException`，由 `CompiledGraph` 统一记录错误、设置 `EXIT_ERROR`、执行 Fallback 并保存 Checkpoint。

本节点不判断自然语言是否“足够优美”，也不凭概率判断事实是否正确。关键业务事实仍必须来自数据库、RAG 或业务服务；质量门禁只检查程序能够可靠验证的输出契约。

### 5.3 专业 Agent 节点

以下节点继续负责调用对应业务服务，并写入 `result_content`、`result_type` 和 `intent`，但不再设置 `exit_reason=COMPLETE`：

- `DetectionAgentNode`
- `ResourceAgentNode`
- `ReportAgentNode`
- `OpsAgentNode`

这保证执行循环不会在专业节点后提前停止。

### 5.4 SlotFillingNode

槽位仍不完整时，`SlotFillingNode` 负责生成追问内容并保持 `phase=COLLECTING`，但不再直接设置 `COMPLETE`。该结果路由到 `ResultQualityNode`，检查通过后由 `ResponderNode` 完成本轮回复。

槽位完整时继续按原有意图路由到专业 Agent 或人工确认节点。

### 5.5 ResponderNode

`ResponderNode` 继续承担正常流程的唯一终止职责：

- 保留防御性空内容兜底，避免未来新增路径绕过质量门禁时产生空回复。
- 缺失 `result_type` 时仍使用 `TEXT`。
- 设置 `exit_reason=COMPLETE`。

Fallback、Guard Break 和 Pending Confirmation 保留各自已有的退出原因，不由 Responder 覆盖。

## 6. 路由调整

图边调整为：

```text
detection  ─┐
resource   ─┤
report     ─┼──> qualityGate ──> responder
ops        ─┤
slotFilling（需要追问）─┘
```

`slotFilling` 槽位完整后的条件路由、`confirm` 恢复后的目标 Agent 路由保持不变。

## 7. 错误处理与状态保存

### 7.1 重试成功

节点在配置次数内成功后，使用成功返回的同一个 `AgentState` 继续执行，并在节点结束后保存 Checkpoint。

### 7.2 重试耗尽或质量检查失败

`CompiledGraph` 统一完成：

1. 写入 `error`。
2. 设置 `exit_reason=ERROR`。
3. 执行 `FallbackNode` 生成安全回复。
4. 保存包含错误原因、当前节点和执行轨迹的 Checkpoint。
5. 返回 Fallback 内容，不继续执行后续业务节点。

### 7.3 安全边界

本次不改变“重试使用同一个内存状态对象”的行为，也不宣称具备事务回滚能力。由于只为 Router 配置重试，当前修复不会引入专业写操作重复执行的新风险。

## 8. 测试设计

### 8.1 CompiledGraph 重试测试

- Router 前两次失败、第三次成功时，断言 Router 共执行三次并继续到后继节点。
- Router 成功而后继节点失败时，断言后继节点不会继承 Router 的两次重试。
- Router 三次均失败时，断言进入 Fallback，并保存 `ERROR` 和错误内容。

测试将退避等待抽离为可替换策略或使用零延迟测试配置，避免单元测试真实等待 1.5 秒。

### 8.2 质量门禁测试

- 完整的 `content/type/intent` 通过检查。
- 空白 `result_content` 被拒绝。
- 缺失或非法 `result_type` 被拒绝。
- 缺失 `intent` 被拒绝。
- 已存在 `error` 的状态被拒绝。

### 8.3 完整执行链测试

- 专业 Agent 返回有效结果后，执行轨迹包含“专业节点 → qualityGate → responder”，最终为 `COMPLETE`。
- 专业 Agent 返回空内容后，执行轨迹进入 `qualityGate → fallback`，最终保留 `ERROR`。
- 槽位不足生成追问后，追问经过质量门禁和 Responder 返回。
- 人工确认仍能以 `PENDING_CONFIRMATION` 中断，不会错误进入质量门禁。

### 8.4 回归验证

运行现有 StateGraph、AgentOrchestrator、专业 Agent 服务及项目 Maven 测试，确保路由守卫、Checkpoint、多租户上下文和人工确认行为不回退。

## 9. 完成标准

- 重试次数只作用于配置的节点。
- 所有普通专业 Agent 回答经过 `ResultQualityNode` 和 `ResponderNode`。
- 空白或契约不完整的回答不会直接返回给用户。
- 正常回答只有在 Responder 执行后才标记为 `COMPLETE`。
- 等待确认、错误和运行守卫的退出语义保持不变。
- 新增测试通过，现有 Maven 测试无回归。
