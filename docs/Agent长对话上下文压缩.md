# Agent 长对话上下文压缩

更新日期：2026-10-16。分支：`java-cloud`。对应 D36 / P16，原 N10 的部分实现。

## 行为与范围

主站和独立 Agent 共用角色工厂。启用后，主 Agent 在推理前检查当前工作消息数量或估算 Token 量，调用 AgentScope Java 2.0.4 的 `ConversationCompactor` 选择安全切点并生成摘要。近期消息原样保留；系统提示词不参与摘要，并重新放回推理输入。工具调用与返回之间的切点沿用 SDK 配对保护。

摘要使用固定 JSON 结构：`intent`、`facts`、`constraints`、`pending`。服务端校验键、类型、条数、文本长度和重复键，拒绝无效、超长或没有缩小字符数的摘要。被移除消息中的 `src-UUID` 来源编号必须出现在摘要内，否则保留原上下文。编号保留不证明摘要准确、来源支持结论或引用属于本轮新抓取。

摘要模型不提供工具。请求失败、超时、空返回、工具调用、结构不合格、来源编号丢失或没有缩小上下文时，不替换工作状态，继续使用原输入推理。取消会停止进行中的摘要请求，不能继续后续推理。轨迹记录失败则中止本次执行，不应用摘要。

每次运行创建独立主 Agent 和压缩预算，不共享账号的摘要或工作状态。专业委派 Agent 本轮未增加压缩器。摘要是有损参考，不提供新权限，不代替业务查询、草稿提交或人工审批；原角色工具、对象授权与确认流程继续生效。

## 存储边界

| 数据 | 本轮处理 |
| --- | --- |
| MySQL 会话历史 | 原消息仍由会话服务保存，不因压缩删除或改写 |
| 当前运行的工作上下文 | 合格摘要替换较早消息，近期消息保留；不单独持久化摘要 |
| 业务状态和审计 | 以数据库及业务 API 为准，摘要不替代质检、报告或审批状态 |
| Mem0 长期记忆 | 沿用本人设置，不触发 SDK 的额外提炼或写入 |

应用原有的服务器历史窗口和输入长度限制仍生效。窗口外更早的消息不会因此自动加载或补摘要；本轮不包含跨轮摘要持久化。

原生压缩配置明确关闭文件卸载、长期记忆 flush、工具参数截断和返回裁剪。项目中间件调用原生压缩器，校验后才更新工作状态；不直接开启 SDK 默认压缩中间件，避免失败占位摘要覆盖原消息。

测试发现 Harness 转录独立于 `disableSessionPersistence()`。工厂现在明确设置 `disableTranscript()`，配合已有内存状态存储及关闭原生追踪日志；定向测试确认隔离工作区没有新增正文文件。本轮未清理历史文件或服务器已有数据。

## 配置、成本与回退

默认关闭，无需数据库迁移。

```dotenv
AGENT_CONTEXT_COMPACTION_ENABLED=false
AGENT_CONTEXT_TRIGGER_MESSAGES=32
AGENT_CONTEXT_TRIGGER_TOKENS=24000
AGENT_CONTEXT_KEEP_MESSAGES=6
AGENT_CONTEXT_MAX_SUMMARY_CHARS=6000
AGENT_CONTEXT_TIMEOUT_SECONDS=12
AGENT_CONTEXT_MAX_PER_RUN=3
```

参数绑定到 `agentscope.ai.context-compaction`，角色工厂启动时校验：消息触发数 4—200；保留数至少 2 且小于触发数；Token 阈值 1024—1000000；摘要长度 256—12000 个 UTF-16 单元；单次等待 1—30 秒；每运行最多 1—5 次尝试。默认保留最近 6 条，每运行最多尝试 3 次，失败也占用预算。安全切点可能保留更多消息。

摘要使用当前统一模型服务，继承供应商选择、备用和熔断。启用后会增加模型调用，可能产生费用；一次摘要仍可能包含供应商重试或备用调用，不能把“3 次摘要”当作“3 次 HTTP 请求”。摘要等待单独受限，并计入原运行总超时。

Token 量是 SDK 估算，不是实际用量或所有备用模型的容量保证；字符数减少也不保证 Token 一定减少。失败回退保留原输入，不能保证超长输入必然执行成功。

启用时改为 true 并重启后端，关闭并重启即可回退。无需开启 Shell、文件工具或额外记忆工具。本轮未修改私有配置、调用付费模型或发布 ECS。

## 执行追溯

新增 `CONTEXT_STARTED`、`CONTEXT_COMPLETED`、`CONTEXT_FAILED`、`CONTEXT_CANCELLED` 事件，保存前后消息数、文本字符数、耗时、策略和固定结果，不保存原历史、摘要或异常正文。字符数按文本与工具内容的 UTF-16 单元累计，不包含协议开销。

摘要请求有独立 `modelRequestId` 和 `purpose=CONTEXT_COMPACTION`。实际候选、备用、熔断及取消事件关联到该编号，有供应商用量时才记录。模型返回成功后仍可能因校验失败而不采用摘要，两种状态分别记录。

追溯页增加“上下文压缩”分类，详情展示前后消息数/字符数，模型路由标明“上下文摘要”。两个聊天入口使用同一追溯页，仍只允许读取本人运行。

## 开源依据与验证

实现前核对了当前依赖的 Apache-2.0 [AgentScope Java](https://github.com/agentscope-ai/agentscope-java)、2.0.4 的 [压缩配置](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-harness/src/main/java/io/agentscope/harness/agent/memory/compaction/CompactionConfig.java)、[原生压缩器](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-harness/src/main/java/io/agentscope/harness/agent/memory/compaction/ConversationCompactor.java)和本机 JAR 接口。复用现有依赖，不复制算法、不升级 SDK。文档 MCP 的 `llms.txt` 当次返回 404，改用官方仓库与已安装 JAR 核对。

测试使用真实 Harness、脚本模型与隔离 H2，覆盖阈值、近期消息/工具调用对、结构和字符数、来源编号、失败/超时/取消、预算、账号隔离、未新增工具、Spring 配置、模型路由及私人轨迹、无正文文件落盘。前端验收覆盖事件分类、字段裁剪、用途和桌面/手机详情。完整结果见 [开发进展](../开发进展.md) 与 `work/context-compaction-*`。

| 检查 | 本轮结果 |
| --- | --- |
| 完整 Maven `clean verify` | 601 项：578 通过、23 个可选联调跳过、0 失败/错误；13 个模块构建成功 |
| 定向 Java 验证 | 21 项通过 |
| 主站 / 独立聊天 Node | 91 / 5 项通过 |
| 隔离 API 浏览器 | 81 项通过，页面 JavaScript 错误为 0 |
| 主站生产构建 | 通过 |
| `git diff --check` | 通过 |

完整构建日志为 `work/context-compaction-full-verify.log`，浏览器结果为 `work/agent-trace/results.json`，桌面/手机截图为 `work/agent-trace/context-compaction-{desktop,mobile}.png`，均已查看复核。临时前端预览进程已停止，原 ECS 页面访问隧道保留。

真实模型的语义保真、长会话容量、云端发布、跨轮摘要持久化、专业 Agent 策略、受控文件卸载及授权读取仍未完成，P16 保持部分完成。
