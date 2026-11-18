# Shell 脚本

2026-11-05 运行约定：本地仅编辑和构建，运行与测试全部在 ECS `172.29.146.74` 执行，结束后确认 `Stopped / StopCharging`。旧本机运行命令失效，当前入口见 [ECS 运行约定](../../docs/monolith/README.md#ecs-统一验收与发布)。


`native-fetch-install.py`：Linux 固定 Fetch 安装监督与持久回执，命令仅接受固定目录及 pool 身份，不执行市场安装命令。供默认关闭的 V58 能力调用，尚未执行或测试，不是通用脚本沙箱。详见 [原生安装进程树回执](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E5%9B%BA%E5%AE%9AFetch%E5%8E%9F%E7%94%9F%E5%AE%89%E8%A3%85%E8%BF%9B%E7%A8%8B%E6%A0%91%E5%9B%9E%E6%89%A7.md)。

用于存放跨环境通用的启动、停止、数据库迁移、日志和诊断脚本。脚本应支持显式参数，并在执行破坏性操作前进行目标校验。

`java-cloud` 使用 ECS 上的 Docker Compose 服务，本地一键启停脚本已移除。连接、运行检查和发布边界见 [服务器运行说明](../../docs/monolith/服务器运行说明.md)。本目录中名称含 `local` 的迁移和诊断工具仍仅面向本机开发库，不可直接用于服务器业务库。

- `ensure-local-kafka-topics.py`：只为本地 Kafka 创建缺失的项目主题。
- `check-local-services.py`：读取 `.env` 并检查六项服务，不调用模型。
- `run-agent-eval.ps1`：运行固定 Agent 规则数据集、生成 JSON/Markdown 报告，并可与指定基线逐例比较；不调用付费模型。见 [Eval 使用说明](../../docs/agent/agentscope-eval.md)。
### 本机组织身份迁移

`migrate-local-organization.py --apply` 执行 V20 的新增表、部门 ID 与外键；不带参数只检查状态。脚本只读取项目 `.env` 中的本机 `doorhandledb`，不自动关联账号，也不更改任务归属。新后端启动前须完成迁移，详情见 [账号员工部门关联](../../docs/monolith/账号员工部门关联.md)。
### 报告流程迁移

`migrate-local-reports.py --apply` 依次执行五张报告流程表 V21 及 Agent 草稿来源表 V22；不带参数只检查。本机限定为项目 `.env` 的 `doorhandledb`，不会创建报告或修改任务。部署见 [报告流程](../../docs/monolith/报告草稿与独立审批.md) 和 [Agent 报告工具](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%8A%A5%E5%91%8A%E5%B7%A5%E5%85%B7%E6%8E%A5%E5%85%A5.md)。

`migrate-local-skills.py --apply`：显式幂等执行 V23 演化五表，只允许项目配置的本机 `doorhandledb`，先核对归档 SQL 与 classpath 副本；不带参数只检查。功能默认关闭，需要 `AGENT_SKILL_EVOLUTION_ENABLED=true` 及持久运行日志。详见 [技能演化说明](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%8A%80%E8%83%BD%E8%87%AA%E5%AD%A6%E4%B9%A0%E4%B8%8E%E5%8F%97%E6%8E%A7%E5%8F%91%E5%B8%83.md)。
