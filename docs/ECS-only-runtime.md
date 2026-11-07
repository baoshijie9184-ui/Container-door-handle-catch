# 单体 ECS 运行与测试

2026-11-07 Jenkins #71：固定提交 `6a1baa2f2dad4a492eacaafc36bde06306c88769` 的 Java 源码验证实际为 443 项通过、133 项错误、469 项基础设施条件跳过、0 项断言失败。原始 XML 的新错误集中为 132 项 H2 不支持生成列引用另一生成列，以及 1 项测试 DDL 缺少分号；此前布尔类型错误已消除。已补齐仅用于 H2 夹具的同表前置生成表达式展开，保留无符号 64 位类型、真实生成列及约束，并增加实际 audit_event 表达式回归；这些修改仍待固定提交的 ECS 验证。后续 Python、前端及两类旧数据服务器封存阶段均未执行，原业务容器及 131 张源表未切换。本轮报告已归档，工具清理实际为 `STOPPED`、`remaining=[]`，随后从流水线外回读 ECS `Stopped / StopCharging`；Jenkins 保持运行。

2026-11-07 新一轮 Jenkins #68：固定提交 `754465e15a613ddc07c5266cb5e5b3abbcf798d9` 的 Java 源码验证实际为 441 项通过、132 项错误、469 项基础设施条件跳过，154 份原始 XML 已归档。旧 `UNSIGNED` 问题已消除；本轮错误为 131 项 JSON 文本与布尔值比较、1 项布尔列与数值比较的 H2 方言兼容问题。后续 Python、前端和旧数据上传阶段均未执行，不据此宣称迁移通过。测试工具清理回执为 `STOPPED`、`remaining=[]`，随后从流水线外回读 ECS `Stopped / StopCharging`，Jenkins 保持运行。两类适配及真实 DDL 约束回归已补齐，13 模块本地跳过测试打包通过，仍须由新的固定提交在 ECS 验证。原业务容器及 131 张源表未切换。

2026-11-07 13:35（北京时间）最新窗口：Jenkins #59 对固定提交 `68ee188164e8cd86dd2f32a45bb67977a5fa2971` 完成部分 Java 源码验证，430 项通过、136 项报错、469 项条件跳过。原始 XML 指向测试夹具中生成列 `VIRTUAL` 的 H2 方言兼容问题，未进入 Python、前端、整库迁移及运行验收。157 份报告已逐项核对摘要并独立留存；工具清理实际回执为 `STOPPED`、`remaining=[]`。随后在流水线外停止 ECS，并回读确认 `Stopped / StopCharging`；本地 Jenkins HTTP 200。原运行版本及 131 张源表未切换，29 张表仍是待验收目标结构。

2026-11-07 12:24（北京时间）测试窗口记录：Jenkins #57 在原 ECS 完成了部分源码验证，结果为 389 通过、137 失败、460 条基础设施条件跳过；失败集中于 AI 模块测试夹具的 MySQL JSON/H2 兼容及旧表名，未执行后续 Python、前端或迁移验收。原始 XML、日志和摘要已收集，本轮工具清理回执为 `STOPPED`、`remaining=[]`。随后从流水线外停止原实例并实际回读 `Stopped / StopCharging`，Jenkins HTTP 200。下一轮应先完成源码修复和构建，再按下方顺序开机验证，不能把本次失败写为重构验收通过。

2026-11-07 恢复执行：原单体实例已启动并通过实例、机器和 SSH 主机密钥核验，公网地址以本轮云端回执为准。此前 `InstanceExpired` / financial 锁记录仅为历史失败。29 表源码编译和本地全模块跳过测试打包通过，实际迁移、恢复及业务验收仍未通过；原线上库继续保留，生产发布及旧库演练门禁关闭。Jenkins #56 完成工具准备后被旧验证目录权限拦下；目录初始化修复已提交推送，由后续固定提交流水线重新验证。

本分支为 `java-cloud`，继续使用 Spring Boot 3.2.4 / Java 17。所有业务运行、开发预览和测试都在北京 ECS `i-2zeieuov2aum486jm1ek` 上执行，私网地址为 `172.29.146.74`。本地仅编辑、编译和打包，不启动数据库、应用、浏览器验收或测试。单元/集成测试全部在 ECS 执行。

2026-11-06 固定 CI/CD 控制器：后续统一使用本地 Jenkins <http://127.0.0.1:8080/>，本地专用节点 `doorhandle-local-ci` 通过已有 SSH/SCP 连接调度已启动的 ECS、收集报告，不新增常驻 ECS Jenkins agent 或为此安装额外 JRE。Jenkins 保持运行，ECS 开机与测试后的节省停机均在流水线外操作，不在 Jenkins 中配置开关机或限时停止阶段。登录信息保存在 Git 忽略的 [私有文档](../work/jenkins/local-access.md)，启动和流水线约定见 [本地 Jenkins CI/CD](本地Jenkins-CICD.md)。这一约定不允许恢复本地应用运行或测试。

## 数据库及环境文件

单体入口必须显式设置 `DB_URL`、`DB_USERNAME`、`DB_PASSWORD`，没有本机库和 root 回退。Java 不再自动读取工作目录 `.env`。Compose 部署继续使用 `DOORHANDLE_ENV_FILE` 指定主机上的私有环境文件；Java 若需要读取容器内的文件，使用独立的 `DOORHANDLE_JAVA_ENV_FILE`，且必须是容器内存在的绝对路径。两者不能混用。

`compose.cloud.yml` 中 `mysql`、`redis` 等容器 DNS 指向服务器内部服务，应继续保留。ECS 上的健康检查回环地址也有效。不要把容器内 `mysql:3306` 改成开发机地址，或将服务器数据库暴露到公网。仓库 `.env.example` 与 `deploy/docker.env.example` 中需要明确填写的连接项已留空。

## 执行入口

- 本地构建必须加 `-DskipTests=true`；可以编译测试源码，但不能执行测试。隔离构建输出可用 `-Ddoorhandle.isolated-verification=true -Ddoorhandle.verification-root=<项目内新目录>`。
- 旧 Windows Jenkinsfile 和本机应用启动/测试脚本已退役；历史文档中的本机应用运行命令失效。本地 Jenkins 控制器启动脚本继续使用。Git 历史保留旧实现。
- ECS 上使用 `script/jenkins/verify-ecs.py`。运行前配置 `DOORHANDLE_ECS_INSTANCE_ID=i-2zeieuov2aum486jm1ek`、事先核验的 `DOORHANDLE_ECS_MACHINE_ID`，以及已有 Java/Maven/Python/Node 工具路径。入口通过 IMDSv2 和 `/etc/machine-id` 核验实际实例后才运行测试。
- Jenkins 统一入口为 `Jenkinsfile.ecs-monolith`，本地节点标签 `doorhandle-local-ci`。入口固定受信任的 `java-cloud` 完整提交，本地执行控制和源码打包步骤，再通过 SSH 在 ECS 独立 checkout 调用 `verify-ecs.py`；原先依赖常驻 Linux Jenkins agent 的入口已替换。ECS 离线或连接资料缺失时预检明确失败，不自动开机、无限等待或转为本地测试。启用项目任务前须确认 CI 文件已推送到 SCM 分支；生产发布和旧库演练的机器环境门禁默认关闭，真实迁移验收前不启用。
- Jenkins 为每次构建生成独立的 `work/ecs-ci-<构建号>-<UUID>` 目录，显式传给验证入口；JUnit 和归档步骤只读取本次目录，避免旧失败或旧用例混入当前结果。历史证据和 Maven 缓存保留。
- 前端开发预览也在 ECS 上执行，须显式设置 `DOORHANDLE_DEV_API_TARGET` / `DOORHANDLE_API_TARGET`。构建静态资源仍可在本地完成。

测试使用单独工作目录与隔离数据库，不读取生产 `deploy/cloud.env`，不迁移或重建业务数据。显式真实 MySQL 用例仍需由专用夹具提供隔离连接和账号；普通源码验证不等于生产数据库验收。

`verify-ecs.py` 默认运行普通源码测试，记录真实通过、失败和条件跳过数量。`--java-only` 仅要求现有 Maven/Java，不要求 Node/npm。需要真实 MySQL 用例时，控制器先准备独立数据库及绑定 ECS 身份的私有 JSON，再传显式类名和清单，例如 `--java-only --java-tests EcsMysqlFixtureTest --fixture-property doorhandle.ecs.mysql.config=/absolute/checkout/work/attempt/private-server.json`。工作台使用 `workbench.mysql.config`，模型、技能和检测分别使用 `agent.model-config.mysql-file`、`agent.skill.mysql-file`、`detection.command.mysql-file`。脚本不会自动读取生产连接、创建数据库或清空业务库；启用夹具的用例若仍被跳过，将判为失败。

Feature MySQL 套件使用显式 `doorhandle.feature.mysql.config`，库名为 `doorhandle_feature_<12位随机十六进制>`，账号为 `ecsit_<同一后缀>`；不再使用固定 13363 端口、root 或空密码。其他旧集成用例也复用 ECS 隔离校验，必须核对机器身份、MySQL UUID、端口和本轮数据目录后才执行迁移或测试数据清理。

Python worker 的真实 MySQL 测试由控制器单独启用 `DOORHANDLE_WORKER_MYSQL_TESTS=1` 和绝对路径 `DOORHANDLE_WORKER_MYSQL_CONFIG`；普通验证不会隐式启用它。清单须位于独立 checkout 的 `work` 内，使用 `scope=ecs-disposable-mysql`、已核实的 `instanceId` / `machineId`、`serverUuid`、非 3306 的 `port`、本轮 `dataDirectory`、`database=doorhandle_worker_verify_<10位随机十六进制>`、`username=ecsit_<同一后缀>` 和非空密码。`url` 为该 ECS 回环端口及数据库的显式 JDBC URL，参数固定为 `?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai`。控制器预先创建空数据库和限定账号；测试核对真实服务身份后迁移 V42，不读取 `.env`，不创建或删除数据库，清理由拥有该隔离实例的控制器负责。

`script/shell/install-local-fetch-mcp.py` 是被 Docker 构建和 ECS 受控安装器复用的依赖构建工具，保留原来的制品校验与许可证收集逻辑；它本身不启动 Fetch 服务，不属于应退役的工作站运行入口。

Journal 的真实 MySQL 用例通过 `--java-tests MysqlAgentJournalTest --fixture-property agent.journal.mysql-file=/absolute/checkout/work/attempt/private-journal.json` 启用，清单使用 `doorhandle_agent_verify_<10位随机十六进制>` 与 `ecsit_<同一后缀>`。ModelFacts 使用 `--java-tests ModelFactsMySqlTest --fixture-property doorhandle.ecs.mysql.config=/absolute/checkout/work/attempt/private-server.json`，复用 `doorhandle_ecsit_<10位随机十六进制>`；入口分别设置 `agent.journal.mysql=true` 与 `model.facts.mysql=true`，不再读取根 `.env` 或回退到 root/空密码。

## 流水线之外的 ECS 启停顺序

1. 先完成代码修改与本地构建。在 Jenkins 流水线之外，通过云 API 或控制台核对实例 ID 与私网地址，保留实际状态回执。
2. 测试前从流水线外启动 ECS，等待系统、网络和执行环境就绪；流水线不调用开机、关机 API，也不安排限时停止任务。
3. 启动后重新查询公网 IP，通过既有 SSH 主机密钥验证连接；不能沿用历史公网 IP。需要 TLS 时，同时验证 `doorhandle-ssh.local` 证书。
4. 由 Jenkins 核对已启动目标的连通性与执行身份，在服务器隔离目录运行测试，保存源码/构建摘要、原始报告及清理回执。目标未就绪时明确失败，不自动开机，也不改为本地执行。
5. 测试结束关闭本轮拥有的测试进程并收回证据，再在流水线之外调用 ECS `StopInstance`，指定 `StoppedMode=StopCharging`。随后实际回读 `Status=Stopped` 和 `StoppedMode=StopCharging`；本地 Jenkins 控制器保持运行。

单纯执行操作系统 shutdown 不满足该要求。实例和云盘保留；StopCharging 停止计算资源计费，保留存储按原规则计费。不查询账单或卡券，不在此流程中发布生产、迁移数据或切流。
