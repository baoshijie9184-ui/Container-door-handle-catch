# Shell 脚本

用于存放跨环境通用的启动、停止、数据库迁移、日志和诊断脚本。脚本应支持显式参数，并在执行破坏性操作前进行目标校验。

本地 Windows 单体统一从项目根目录 `start-local.cmd` / `start-local.ps1` 启动，`stop-local.cmd` / `stop-local.ps1` 停止。使用说明见 [本地单体启动](../../docs/local-monolith-startup.md)。

- `start-local-project.ps1`：启动后端、中间件和两套前端，记录进程身份并等待健康状态。
- `start-local-middlewares.ps1`：复用已有环境，启动 MySQL、Redis、项目内 Kafka、Chroma、Mem0，可选后端。
- `ensure-local-kafka-topics.py`：只为本地 Kafka 创建缺失的项目主题。
- `check-local-services.py`：读取 `.env` 并检查六项服务，不调用模型。
- `stop-local-project.ps1`：核对进程身份后停止本项目记录的进程，保留共享 MySQL、Redis 服务和数据。
- `run-agent-eval.ps1`：运行固定 Agent 规则数据集、生成 JSON/Markdown 报告，并可与指定基线逐例比较；不调用付费模型。见 [Eval 使用说明](../../docs/agentscope-eval.md)。
### 本机组织身份迁移

`migrate-local-organization.py --apply` 执行 V20 的新增表、部门 ID 与外键；不带参数只检查状态。脚本只读取项目 `.env` 中的本机 `doorhandledb`，不自动关联账号，也不更改任务归属。新后端启动前须完成迁移，详情见 [账号员工部门关联](../../docs/账号员工部门关联.md)。
### 报告流程迁移

`migrate-local-reports.py --apply` 依次执行五张报告流程表 V21 及 Agent 草稿来源表 V22；不带参数只检查。本机限定为项目 `.env` 的 `doorhandledb`，不会创建报告或修改任务。部署见 [报告流程](../../docs/报告草稿与独立审批.md) 和 [Agent 报告工具](../../docs/Agent报告工具接入.md)。

`migrate-local-skills.py --apply`：显式幂等执行 V23 演化五表，只允许项目配置的本机 `doorhandledb`，先核对归档 SQL 与 classpath 副本；不带参数只检查。功能默认关闭，需要 `AGENT_SKILL_EVOLUTION_ENABLED=true` 及持久运行日志。详见 [技能演化说明](../../docs/Agent技能自学习与受控发布.md)。
