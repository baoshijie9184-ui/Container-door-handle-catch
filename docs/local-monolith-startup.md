# 本地单体启动

在 `java` 分支使用项目根目录的 `start-local.cmd`，双击即可启动，也可在 PowerShell 执行：

```powershell
.\start-local.ps1
```

脚本启动或复用 MySQL、Redis、Kafka、Chroma、Mem0、Spring Boot 单体后端、Vue 主站和独立 Agent UI。后台进程隐藏运行，启动完成前检查数据库、缓存、Kafka 主题及 HTTP 健康状态。重复启动复用已经运行的服务；前端端口被其他程序占用时明确报错。

| 服务 | 本机地址 |
| --- | --- |
| Vue 主站登录页 | http://127.0.0.1:3001/#/login |
| Agent UI | http://127.0.0.1:3003 |
| 后端健康检查 | http://127.0.0.1:8080/actuator/health |
| MySQL | 127.0.0.1:3306 |
| Redis | 127.0.0.1:6379 |
| Kafka | 127.0.0.1:9092 |
| Chroma | http://127.0.0.1:8000/api/v2/heartbeat |
| Mem0 | http://127.0.0.1:8081/health |

## 参数

```powershell
# Java 代码修改后重新打包：先停止应用，再构建启动
.\stop-local.ps1 -ApplicationsOnly
.\start-local.ps1 -BuildBackend

# 仅启动后端及中间件
.\start-local.ps1 -NoFrontend -NoAgentUI

# 启动完成后打开主站登录页
.\start-local.ps1 -OpenBrowser

# 使用其他已有环境
.\start-local.ps1 -PythonPath 'D:/envs/project/python.exe' -KafkaHome 'D:/software/kafka' -JavaHome 'D:/software/jdk-17' -MySqlService 'MySQL80' -RedisService 'Redis'
```

默认复用本机已有 JDK 17、`leetcode` Python 环境、Kafka 4.2.0 和 Windows 的 `MySQL83`、`Redis` 服务。路径默认值写在 `script/shell/start-local-project.ps1` 参数中，可通过根目录入口的上述参数覆盖。更换 Kafka 发行版需与脚本的 KRaft 配置及命令兼容。启动 Windows 服务需要当前账号具备相应权限；已运行时直接复用。

需要 Node.js 位于 PATH，两个前端目录已安装依赖，Python 环境已具备 Uvicorn、Mem0、Chroma、python-dotenv、PyMySQL、Redis、requests 和 confluent-kafka。启动入口不会自动下载安装环境。后端 Jar 缺失或指定 `-BuildBackend` 时调用 PATH 中的 `mvn.cmd` 打包，常规启动使用已有 Jar。前端始终运行开发服务器，无需重新打包。

## 配置和数据

主站根地址默认进入登录页，已有会话也不会将登录页自动跳转到首页。登录成功后进入首页；未登录直接访问首页或其他工作区页面时，会先进入登录页。

本机已准备员工、主管各两个账号，用户名、密码和验证说明见 [测试用户账号](测试用户账号.md)。

当前后端还需 V20 账号员工部门关联、V21 报告审批、V22 Agent 草稿来源迁移，本机已完成。其他开发库先运行 `script/shell/migrate-local-organization.py --apply` 和 `script/shell/migrate-local-reports.py --apply`，报告脚本同时执行 V21、V22。详情见 [组织身份](账号员工部门关联.md)、[报告审批](报告草稿与独立审批.md) 和 [Agent 报告工具](Agent报告工具接入.md)。健康检查核对新增表；启动入口不会自动执行迁移。

启用 `AGENT_ACTION_CONFIRMATION_ENABLED=true` 前执行 V19 确认/审计迁移并启用运行日志。主管分配提议通过主站确认卡片或菜单“助手操作确认”决策，详见 [人工确认说明](agentscope-action-confirmation.md)。

后端与 Mem0 读取项目根目录 `.env`。启动前检查重复键，避免 Java 配置加载失败；本地 Kafka 要求 `APP_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092`。三个检测主题缺失时创建，已有主题和消息保留。

Kafka KRaft 数据、Chroma 服务数据、进程记录及日志放在项目 `work/middlewares/`，Mem0 继续使用原有 `memory_service/chroma_db` 记忆目录。Kafka 仅在全新数据目录初始化存储，重启保留集群身份。数据库使用 `.env` 指定的业务库；启动脚本不创建业务库、不执行数据库迁移，也不导入种子数据。本机已经应用 V16 并启用运行日志，详情见 [运行日志说明](agentscope-run-journal.md)。

Mem0 模型通过 `MEM0_LLM_MODEL` 显式配置，未配置时使用 `DASHSCOPE_MODEL`，不继承 AgentScope 的其他供应商模型名。健康检查不调用付费模型。

检测任务执行沿用项目现有 worker 配置。此入口不启动独立 Python 检测 worker，不检查远端 worker 是否在线；如需运行独立 worker，应按项目 README 的 worker 启动方式配置对应 Kafka 地址。

## 停止与排查

双击根目录 `stop-local.cmd`，或执行：

```powershell
.\stop-local.ps1
```

默认停止本入口记录的两套前端、后端、Mem0、Chroma 和 Kafka。停止前核对进程 ID、创建时间及可执行文件，防止 PID 被其他程序复用后误停。共享 MySQL、Redis Windows 服务保持运行，数据保留。使用 `-ApplicationsOnly` 只停止两套前端与后端。启动前已经运行且没有项目进程记录的外部服务不由停止脚本管理。

日志位于 `work/middlewares/<服务名>.out.log` 和 `<服务名>.err.log`。健康检查结果保存为 `work/middlewares/services-health.json`。启动报错后可以单独执行检查：

```powershell
& 'D:/ruanjian/anaconda3/envs/leetcode/python.exe' script/shell/check-local-services.py
```

检查只查询健康状态，不发送检测任务、不调用模型。

技能演化需显式 V23/V24 迁移和 `AGENT_SKILL_EVOLUTION_ENABLED=true`，并开启运行日志。启动检查技能五表及版本来源类型列，不自动迁移。本机迁移入口 `script/shell/migrate-local-skills.py --apply` 核对并执行两份脚本。规则与原生读取见 [技能自学习](Agent技能自学习与受控发布.md)。ZIP 上传已移除，V24 仅保留历史兼容元数据。

本地 Fetch MCP 需显式 V25、`AGENT_LOCAL_MCP_ENABLED=true` 和已有 Python 的绝对路径 `AGENT_LOCAL_MCP_PYTHON`。迁移入口 `script/shell/migrate-local-mcp.py --apply`，统一启动检查两表，不自动迁移。安装在本人 Agent workspace 下，不新增全局 Python 环境。页面“Agent智能系统 → MCP工具”；安装、启用、原生 Stdio 与审计见 [本地 Stdio MCP 接入](本地StdioMCP接入.md)。

个人记忆治理需显式执行 `script/shell/migrate-local-memory.py --apply`，添加 V26 两表及本机内部桥接密钥，再更新后端并重启 Mem0。新健康检查验证两表和已认证桥接，密钥不输出、不进入浏览器。原聊天记录和 Mem0 数据保留，见 [个人长期记忆治理](个人长期记忆治理.md)。

报告事件交付需先运行 `script/shell/migrate-local-report-events.py --apply`，再开启 `APP_REPORT_EVENTS_ENABLED=true`。启动入口补齐报告 topic 并检查 V30 两表及六列；关闭开关暂停交付但保留数据。见 [报告事件交付与重试](报告事件交付与重试.md)。
