# AgentScope 平台配置说明

后端的 AgentScope Java 2.0.1 适配位于 `doorhandle-module-ai`，通过 `doorhandle-server` 暴露 AG-UI 接口。角色网关直接使用 AG-UI 扩展的请求处理器，先绑定登录身份再执行异步 Agent，不使用通用 Starter Controller。仓库只提交 `.env.example`，真实密钥请复制为根目录 `.env` 后手动填写，或交给部署平台的 Secret 管理。

## 最小启动配置

```dotenv
AGENTSCOPE_AI_ENABLED=true
DASHSCOPE_API_KEY=你的阿里云百炼Key
AGENTSCOPE_AI_MODEL=dashscope:qwen-plus
```

启动后接口为 `POST /agui/run`，需要检测系统登录态；`GET /agui/catalog` 返回当前角色能力。未开启 `AGENTSCOPE_AI_ENABLED` 时不装配角色网关和 Agent 工厂。Agent 按请求创建，避免不同用户共用单例对话状态。

两类角色的实际工具范围及未完成事项见 [实施进度](agent-role-toolkit-progress.md)。当前接口超时为三分钟，只支持文本只读查询；Starter 的 server-side-memory、reasoning、state-events、run-timeout 等配置尚不由此网关读取，不能通过打开旧配置启用这些能力。

## 配置分组

| 配置组 | 用途 | 默认状态 |
| --- | --- | --- |
| `AGENT_MODEL_*` | 模型路由、超时、重试；支持 DashScope、DeepSeek、GLM 的预留配置 | DashScope |
| `AGENT_EVENT_BRIDGE_*` | EventBridge/异步事件适配预留 | 关闭 |
| `AGENT_A2A_*` | A2A Agent 协作服务地址与密钥 | 关闭 |
| `AGENT_RESPONSES_*` | OpenAI Responses API 兼容接入 | 关闭 |
| `AGENT_MEMORY_*` | Redis、Mem0 长期记忆 | 关闭 |
| `AGENT_VECTOR_*` | Milvus 等向量数据库 | 关闭 |
| `AGENT_WORKSPACE_*` | Agent 工作区与沙箱策略 | 本地工作区 |
| `OTEL_*`、`LANGFUSE_*` | OpenTelemetry、Langfuse 可观测性 | 关闭 |

这些开关只是基础设施配置契约；对应 SDK/连接器在实际业务使用前再加入相应模块，避免启动时强制依赖外部服务。

## 安全约束

- 不要把 `.env`、云厂商 Secret 或生产配置提交到 Git。
- 生产环境优先使用容器编排平台 Secret 注入环境变量。
- `AGENT_WORKSPACE_ROOT` 应指向专用目录，不要指向用户家目录或项目源码根目录。
- 开启 AG-UI 跨域时，仅填写明确的前端域名，并保持 `AGENTSCOPE_AGUI_CORS_ENABLED=false` 作为默认值。
