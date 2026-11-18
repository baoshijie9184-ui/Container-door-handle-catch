# AgentScope 平台配置

主站聊天和独立 AG-UI 共用 `doorhandle-module-ai` 的 AgentScope Java 2.0.4 角色工厂及模型服务。默认不开启 Agent；环境与验收约定见 [Agent 开发](README.md) 和 [开发总规则](../开发规则.md)。

## 从环境变量配置模型

在已批准的服务器环境中，通过 Compose 的私有 `env_file` 注入配置，或通过 `DOORHANDLE_JAVA_ENV_FILE` 显式指定 JVM 可读的绝对路径。Java 不会自动加载工作目录的 `.env`。配置来源及默认值以 [application.yml](../../doorhandle-server/src/main/resources/application.yml) 为准。

最小示例选用 DashScope；替换占位凭据和实际获准的模型后再启用。不要把真实密钥写入项目模板或提交到 Git。

```dotenv
AGENTSCOPE_AI_ENABLED=true
DASHSCOPE_API_KEY=replace-in-private-env
DASHSCOPE_MODEL=qwen-plus
AGENTSCOPE_AI_MODEL=dashscope:qwen-plus
```

| 配置组 | 用途 |
| --- | --- |
| `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` / `DASHSCOPE_MODEL` | 百炼；兼容 Chat Completions 和原生端点按所选地址交由对应适配器处理 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | 独立 DeepSeek 凭据和 Chat Completions 设置，不复用百炼密钥 |
| `OPENAI_API_KEY` / `AGENT_RESPONSES_BASE_URL` / `OPENAI_MODEL` | Responses 适配器；选择 ID 前缀是 `openai-official:`，不等于服务一定由 OpenAI 提供 |
| `AGENTSCOPE_AI_MODEL` | 环境配置模式下的默认模型选择 ID，须匹配已登记的供应商与模型 |

环境配置变更通过受控发布注入并重启服务。不要将示例模型名、免费额度或历史备用顺序当作实际部署设置；以获准的配置版本和本次请求轨迹为准。

## 版本化模型配置

`AGENT_MODEL_CONFIG_ENABLED` 默认关闭。完成迁移、接入私有主密钥并获准启用后，授权主管可通过 `/api/agent/model-config` 建草稿、校验及发布。恢复操作从旧版本建一份新草稿，仍须校验和发布才会生效。普通模型查询和聊天不修改端点或密钥；未启用版本化配置时使用环境配置路径。

版本化配置将供应商、模型、端点、凭据和策略绑定到版本；网关、代理等部署运输设置不写回历史模型版本。主密钥、备份、回退和已批准的模型参数按现有门禁管理。

## 超时、备用与熔断

| 配置项 | 源码默认及含义 |
| --- | --- |
| `AGENT_MODEL_TIMEOUT` / `AGENT_MODEL_FIRST_TOKEN_TIMEOUT` | 候选请求预算 60 秒、首段有效内容预算 15 秒 |
| `AGENT_MODEL_MAX_RETRIES` | 非备用模式下的 SDK 重试设置，默认 2 |
| `AGENT_MODEL_MAX_OUTPUT_TOKENS` | 默认上限 2048 |
| `AGENT_MODEL_FALLBACK_ENABLED` | 环境配置默认关闭自动备用 |
| `AGENT_MODEL_FALLBACK_MODELS` / `AGENT_MODEL_FALLBACK_MODEL` | 有序列表优先，列表为空时才考虑兼容的单候选设置 |
| `AGENT_MODEL_FAILURE_THRESHOLD` / `AGENT_MODEL_CIRCUIT_COOLDOWN` / `AGENT_MODEL_QUOTA_COOLDOWN` | 默认 2 次连续暂时性失败、60 秒短暂冷却、5 分钟额度或凭据类冷却 |
| `AGENT_RESPONSES_STORE` | 请求默认 `false`；不能据此推断兼容平台内部保留策略 |

自动备用只在尚未输出有效内容、失败类型可切换时尝试其他候选。已经输出文字、思考内容或工具调用后不重播操作。普通参数错误、预算耗尽或 Redis 协调不可用不能按网络故障静默切换。环境配置可使用进程内健康状态；治理版本的熔断按版本与模型用 Redis 协调，不能假定重启后状态清零。

## 检查实际接线

- `GET /agui/catalog` 查看当前角色能力；`GET /agui/models` 查看可用模型，实际调用看 [模型路由追溯](模型调用路由追溯.md)，不从默认模型推测历史。
- 业务写入权限、检测提议和报告草稿遵循 [工具权限](README.md#工具权限与执行)。两套聊天入口共用版本和授权规则。
- 日常统一验收使用本地、mock 或脚本化模型。真实模型调用须单独授权，不把旧工作站的 Maven 直跑命令复制为开发步骤。
