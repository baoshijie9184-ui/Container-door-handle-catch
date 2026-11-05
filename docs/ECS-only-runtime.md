# 单体 ECS 运行与测试

本分支为 `java-cloud`，继续使用 Spring Boot 3.2.4 / Java 17。所有运行、开发预览和测试都在北京 ECS `i-2zeieuov2aum486jm1ek` 上执行，私网地址为 `172.29.146.74`。本地仅编辑、编译和打包，不启动数据库、应用、浏览器验收或测试。单元/集成测试全部在 ECS 执行。

## 数据库及环境文件

单体入口必须显式设置 `DB_URL`、`DB_USERNAME`、`DB_PASSWORD`，没有本机库和 root 回退。Java 不再自动读取工作目录 `.env`。Compose 部署继续使用 `DOORHANDLE_ENV_FILE` 指定主机上的私有环境文件；Java 若需要读取容器内的文件，使用独立的 `DOORHANDLE_JAVA_ENV_FILE`，且必须是容器内存在的绝对路径。两者不能混用。

`compose.cloud.yml` 中 `mysql`、`redis` 等容器 DNS 指向服务器内部服务，应继续保留。ECS 上的健康检查回环地址也有效。不要把容器内 `mysql:3306` 改成开发机地址，或将服务器数据库暴露到公网。仓库 `.env.example` 与 `deploy/docker.env.example` 中需要明确填写的连接项已留空。

## 执行入口

- 本地构建必须加 `-DskipTests=true`；可以编译测试源码，但不能执行测试。隔离构建输出可用 `-Ddoorhandle.isolated-verification=true -Ddoorhandle.verification-root=<项目内新目录>`。
- 旧 Windows Jenkinsfile 和本机启动/测试脚本已退役；历史文档中的本机运行命令失效。Git 历史保留旧实现。
- ECS 上使用 `script/jenkins/verify-ecs.py`。运行前配置 `DOORHANDLE_ECS_INSTANCE_ID=i-2zeieuov2aum486jm1ek`、事先核验的 `DOORHANDLE_ECS_MACHINE_ID`，以及已有 Java/Maven/Python/Node 工具路径。入口通过 IMDSv2 和 `/etc/machine-id` 核验实际实例后才运行测试。
- Jenkins 源码验证入口为 `Jenkinsfile.ecs-monolith`，节点标签 `doorhandle-monolith && doorhandle-ecs`，必须指定审核过的 `java-cloud` 完整提交。它负责源码验证，不执行生产发布。
- Jenkins 为每次构建生成独立的 `work/ecs-ci-<构建号>-<UUID>` 目录，显式传给验证入口；JUnit 和归档步骤只读取本次目录，避免旧失败或旧用例混入当前结果。历史证据和 Maven 缓存保留。
- 前端开发预览也在 ECS 上执行，须显式设置 `DOORHANDLE_DEV_API_TARGET` / `DOORHANDLE_API_TARGET`。构建静态资源仍可在本地完成。

测试使用单独工作目录与隔离数据库，不读取生产 `deploy/cloud.env`，不迁移或重建业务数据。显式真实 MySQL 用例仍需由专用夹具提供隔离连接和账号；普通源码验证不等于生产数据库验收。

`verify-ecs.py` 默认运行普通源码测试，记录真实通过、失败和条件跳过数量。`--java-only` 仅要求现有 Maven/Java，不要求 Node/npm。需要真实 MySQL 用例时，控制器先准备独立数据库及绑定 ECS 身份的私有 JSON，再传显式类名和清单，例如 `--java-only --java-tests EcsMysqlFixtureTest --fixture-property doorhandle.ecs.mysql.config=/absolute/checkout/work/attempt/private-server.json`。工作台使用 `workbench.mysql.config`，模型、技能和检测分别使用 `agent.model-config.mysql-file`、`agent.skill.mysql-file`、`detection.command.mysql-file`。脚本不会自动读取生产连接、创建数据库或清空业务库；启用夹具的用例若仍被跳过，将判为失败。

Feature MySQL 套件使用显式 `doorhandle.feature.mysql.config`，库名为 `doorhandle_feature_<12位随机十六进制>`，账号为 `ecsit_<同一后缀>`；不再使用固定 13363 端口、root 或空密码。其他旧集成用例也复用 ECS 隔离校验，必须核对机器身份、MySQL UUID、端口和本轮数据目录后才执行迁移或测试数据清理。

Python worker 的真实 MySQL 测试由控制器单独启用 `DOORHANDLE_WORKER_MYSQL_TESTS=1` 和绝对路径 `DOORHANDLE_WORKER_MYSQL_CONFIG`；普通验证不会隐式启用它。清单须位于独立 checkout 的 `work` 内，使用 `scope=ecs-disposable-mysql`、已核实的 `instanceId` / `machineId`、`serverUuid`、非 3306 的 `port`、本轮 `dataDirectory`、`database=doorhandle_worker_verify_<10位随机十六进制>`、`username=ecsit_<同一后缀>` 和非空密码。`url` 为该 ECS 回环端口及数据库的显式 JDBC URL，参数固定为 `?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai`。控制器预先创建空数据库和限定账号；测试核对真实服务身份后迁移 V42，不读取 `.env`，不创建或删除数据库，清理由拥有该隔离实例的控制器负责。

`script/shell/install-local-fetch-mcp.py` 是被 Docker 构建和 ECS 受控安装器复用的依赖构建工具，保留原来的制品校验与许可证收集逻辑；它本身不启动 Fetch 服务，不属于应退役的工作站运行入口。

Journal 的真实 MySQL 用例通过 `--java-tests MysqlAgentJournalTest --fixture-property agent.journal.mysql-file=/absolute/checkout/work/attempt/private-journal.json` 启用，清单使用 `doorhandle_agent_verify_<10位随机十六进制>` 与 `ecsit_<同一后缀>`。ModelFacts 使用 `--java-tests ModelFactsMySqlTest --fixture-property doorhandle.ecs.mysql.config=/absolute/checkout/work/attempt/private-server.json`，复用 `doorhandle_ecsit_<10位随机十六进制>`；入口分别设置 `agent.journal.mysql=true` 与 `model.facts.mysql=true`，不再读取根 `.env` 或回退到 root/空密码。

## 启停顺序

1. 先完成代码修改与本地构建。控制端通过云 API 核对实例 ID 与私网地址，保留实际状态回执。
2. 启动前安排有时限的独立云端停止任务。现有每日零点任务不是本轮及时清理的替代品。
3. 启动后重新查询公网 IP，通过既有 SSH 主机密钥验证连接；不能沿用历史公网 IP。需要 TLS 时，同时验证 `doorhandle-ssh.local` 证书。
4. 在服务器隔离目录运行测试，保存源码/构建摘要、原始报告及清理回执。
5. 测试结束关闭本轮拥有的测试进程并收回证据，由控制端调用 ECS `StopInstance`，指定 `StoppedMode=StopCharging`。随后实际回读 `Status=Stopped` 和 `StoppedMode=StopCharging`。

单纯执行操作系统 shutdown 不满足该要求。实例和云盘保留；StopCharging 停止计算资源计费，保留存储按原规则计费。不查询账单或卡券，不在此流程中发布生产、迁移数据或切流。
