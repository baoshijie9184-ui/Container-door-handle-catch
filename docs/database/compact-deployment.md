# 29 表首迁移与部署协议

源码入口已接入 `Jenkinsfile.ecs-monolith`，尚不能据此认定迁移或发布已验收。机器门禁 `DOORHANDLE_COMPACT_RELEASE_READY`、`DOORHANDLE_COMPACT_REHEARSAL_READY` 保持关闭，直到对应 ECS 验收证据完整。CI/CD 由本地 Jenkins 调度；本地不运行测试或业务，ECS 启停不属于流水线。

## 固定验收范围

[compact-acceptance.json](../../script/jenkins/compact-acceptance.json) 是本次验收清单，摘要随源码和每份执行回执绑定。v2 夹具清单为 56 个自包含 JDBC、迁移、权限及业务服务类分别建立独立 schema/account 和 Maven 执行，避免各类的空库前置相互冲突。验收器和切库门禁分别解析原始 Surefire XML，逐类核对实际执行、最低用例数及零失败、零跳过；只报告 Java 总通过数不能放行。

同一构建另执行无夹具或付费模型开关的普通 Java 回归，其中 31 个纯逻辑必需类必须实际通过且不跳过；基础设施 opt-in 类在这一轮的预期跳过不充当数据库验证。完整 Python 回归要求所有已登记模块，实际 worker MySQL receipt 并发/重启/未知结果用例及整库复制、旧源恢复、29 表目标恢复都不能跳过。唯一声明的 Linux 预期跳过是 Windows 文件共享语义专用用例。两套前端分别显式执行 23 和 4 个固定测试文件，并核对 TAP 实际用例数及构建成功。

这组矩阵证明数据库和源码回归覆盖，不能代替完整运行验收。清单还保留 9 个生产前必需运行场景：多角色隔离、模型额度闭环、实际 PTH/Kafka worker、新 SDK/工作台恢复、私有 MCP 及未知写保护、报告闭环、技能发布回退、记忆及密钥恢复、候选应用升级恢复。旧 server LocalMysql 用例有共享来源 run、已安装私有 MCP、真实服务等前置，不能机械拆成空库执行，也不能因此取消其业务要求；运行验收器应在同一构建的隔离完整栈执行等价断言并留下真实证据。未取得这些结果前，不认定业务交付完成，不打开生产门禁。真实供应商 Live suites 不在本次范围；模型仅使用本地、mock 或脚本化输出。

## 首次从旧库迁移

Jenkins 动作 `compact-cutover` 必须选择 `mysql` 验证范围，并使用该构建固定提交及源码归档。`PRODUCTION_RELEASE_ENABLED` 和节点环境中的发布门禁同时满足才允许进入首切阶段。控制器与 ECS helper 都核对本轮 MySQL PASS、无跳过的 Java 用例，以及真实执行的整库复制和恢复验收；源码检查结果不能代替这些证据。

1. 流水线验证固定提交，在 ECS 隔离环境执行测试并收集带摘要的报告。
2. `deploy-remote.sh build-only` 展开同一源码归档，构建 backend、nginx、mem0 和新版 detection-worker。backend 封装本地 Jenkins 已编译并用于整库迁移的同一 BootJar，不在 ECS 的 Docker 构建中另跑 Maven；受控构建上下文保留版本化 Dockerfile 的固定 runtime 层、依赖和许可证，只替换唯一 jar COPY。大体积依赖从 ECS 现有已验证 worker 上下文硬链接到本轮目录，当前业务目录不改。制品提取容器仅创建、不启动；从实际候选 backend 镜像提取 jar 再核对本轮计划摘要和字节数。`candidate-build.json` 绑定提交、构建、源码、四类镜像、同一 jar、私有输入及验证回执摘要。
3. `compact-cutover.py prepare` 保存源容器及原重启策略，关闭 nginx 和所有源应用进程，将其重启策略暂设为 `no`。枚举源 app/worker 的实际账号及所有可写旧库身份，拒绝无法证明隔离的额外写者；锁定原运行账号，阻止主机作业复用旧凭据重连。root 维护账号始终保留，不能用作业务运行身份；跨库、全局管理、角色或代理账号不能直接充当可封存的旧业务账号。用管理员权限读取完整源事件目录，拒绝启用中的事件，目录摘要及实际账号锁态进入私有 writer-freeze 证明。创建本轮迁移账号：旧库仅 SELECT、TRIGGER、LOCK TABLES，新目标及两个恢复证明库有对应 schema 授权。观察全部 131 张源表的结构、行、索引与高水位，固定观察摘要。
4. `migrate` 调用整库编排。迁移锁住完整源表集，在全新目标中复制并校验 29 表，实际将旧库和目标备份分别恢复到两个全新证明库，确认一致后才生成 VERIFIED 回执。失败或结果未知时保留源、候选、备份和证据，禁止覆盖重跑。不会关闭外键检查。
5. 同阶段创建彼此独立的 app、worker 账号，只授目标库 SELECT、INSERT、UPDATE、DELETE。原 `cloud.env` 保持原样；目标连接写到私有 `state/compact-connection.override.yml`（JSON 内容也是合法 YAML），并以摘要绑定 `state/compact-connection.json`。
6. `activate` 再次实际读取冻结源和候选，比较迁移快照；验证目标表数、完整结构摘要、触发器目录、两份恢复回执、运行账号权限以及所有协议 reader。目标积压任务须先完成受控处置。保留 assignment/MCP 写暂停、镜像引用保护、MCP 未知结果处理、记忆与模型密钥恢复证明。
7. 候选内部健康检查通过后才开放 nginx。首个兼容 compact reader 是本次候选本身；后续同库回滚指针指向该兼容版本。旧后端只保存在私有源恢复证据中，不作为新库 reader。最终连接 journal 进入 ACTIVE，普通发布门禁才接受该连接。

## 私有设置与凭据

`COMPACT_CUTOVER_SETTINGS` 指向 ECS 上已审阅的 0600 JSON，与本轮夹具准备复用同一文件，严格包含五项：`version: 1`、`sourceMysqlContainerId`（原正式 MySQL 完整 64 位容器 ID）、`sourceSchema`（实际旧业务库名）、`java`（已有 Java 17 可执行文件的规范绝对路径）、`sourceOffsets`。构建候选前即回读原部署的容器及数据库身份，避免昂贵构建后才发现输入不符。`sourceOffsets` 必须逐项填写所有复制域的历史时间偏移：action、agent、binding、chat、context、detection、digest、export、identity、inbox、infra_log、mcp、memory、model_file、model_log、model、operations、report、research、sdk、skill、workspace、workbench。digest 是原 V65 的 UTC DATETIME，必须为 `+00:00`；其他项必须依据旧字段历史约定核对，不能用当前 MySQL 时区推断全部字段。脚本从固定源码取得需要的域集合，缺项、额外项或无效偏移都会拒绝。

迁移、应用和 worker 密码由 ECS helper 随机生成，仅保存在本轮 `release/work` 和 `state` 的私有文件中。Jenkins 只收集不含凭据和业务行的构建及切换摘要。数据库 dump、原始诊断、连接 overlay、迁移私有配置不得归档至 Jenkins。

## 失败与恢复边界

`prepare → migrate → activate` 是持久化阶段；未知结果不能以重跑覆盖。迁移账号不会得到全局 ALL 或自动补充 definer 权限；无法原样恢复旧触发器时，在创建候选前拒绝继续。

候选启动前，`recover` 先重新核对完整旧源快照，再恢复原账号锁态、原容器及其重启策略，最后开放旧 nginx。候选一旦开始启动，即使没有用户 HTTP 请求，也可能由调度器、worker 或协议持久化产生目标新写入。此后禁止自动退回旧源；失败时再次冻结所有应用与入口，保留候选数据，使用 compact 目标恢复或前向修复。不会将新库数据丢给旧后端。停止、恢复或重锁账号任一步未能实际回读确认时，状态为 NEEDS_REVIEW，不会声称已冻结。

普通 `verify-deploy`、回滚及同 schema 应用演练读取 ACTIVE 连接 overlay，并核对实际 29 表 metadata 与完整迁移/恢复回执摘要链。旧 V39–V66 增量迁移不再被当作 compact 验收，也不会在应用启动时执行旧业务 seed 来重建旧表。完整整库迁移说明见 [迁移与恢复](compact-migration-orchestration.md)。

## 验证状态

本轮只允许源码编辑和静态解析。新增或适配的失败场景用例须由 Jenkins 在 ECS 实际执行；本地 AST、PowerShell 语法和 Bash 语法检查不属于迁移、健康或业务验收。没有真实 PASS 和迁移/恢复回执，不打开生产发布门禁。

## 完整候选运行验收

`verify-runtime` 在同一构建的 MySQL 矩阵通过后，执行候选构建和 `compact-runtime-acceptance.py run`；不要求打开生产发布门禁，也不切换正式连接。运行器只接受原夹具的五项私有设置，并从该构建 `runtime-migration.json` 索引、原始矩阵摘要及完整迁移/双恢复回执取得实际目标。它重新核对同一 server UUID、实际非 3306 内外端口、同路径 datadir、29 表快照，以及固定源码/Jar/镜像摘要。不能手工填写另一份自洽回执替代本轮结果。

完整栈有独立 Compose 项目、网络、卷、Redis/Kafka、Mem0、用户及 app/worker DML 账号；复用本轮已拥有的测试 MySQL，不重建或重标记正式 MySQL。模型可执行进程只加入实际读回为 internal 的自有网络，所有环境模型凭据均为合成值；通过草稿、真实 JSON 协议校验和发布 API 启用一个本地脚本模型，保留原加密历史。当前运行场景使用 DeepSeek 的 Chat Completions 兼容路径，不把它表述为 OpenAI Responses 或原生 DashScope 协议验收。真实 PTH、OSS 上传、Kafka 消费及 worker durable receipt 重放仍执行实际服务，不直接插入成功事实。OSS 出站适配器只允许本轮随机对象前缀与固定真实阿里云 bucket，拒绝通用代理、跳转和不支持的签名；模型进程不会因此取得外网权限。

模型配置中的 provider、model、base URL、API key、策略与版本属于冻结的业务配置。gateway/proxy 是本次部署的运输设置，版本 client 在独立副本上应用当前设置，空值明确清除旧部署路由，不修改已封存文档。Mem0 只通过可选 `MEM0_MODEL_GATEWAY_BASE_URL` 在构造 LLM client 时改变运输路径，原 envelope 的 base URL 与密钥校验保留，embedding 设置不会随 LLM 网关改变。这也支持正式部署在网关拓扑变化后继续读取旧版本，而不是为测试改写历史供应商身份。

9 个场景必须全部产生独立实际断言证据；复杂 SDK 工作先持久化计划并通过实际 HTTP 批准，再继续原逻辑任务，不能关闭计划来通过。独立运行验收还核对私有安装/取消/Fetch、工作台 parent-child、SDK checkpoint、额度真实扣减、报告 SDK origin 与审批/下载/Kafka、技能版本发布/加载/回退、Mem0 排除与密钥、业务写入后的真实备份恢复。运行结束只回收本轮拥有的对象和进程，逐容器核对停止与网络解绑，保留私有数据库/卷和原始证据。失败或未知结果保留 NEEDS_REVIEW，不声称 STOPPED。

未知结果验证必须实际触发。worker 在独立真实任务完成 PTH/OSS 写入后，由仅命中该任务的临时目标库触发器拒绝成功 receipt 提交；核对实际 MySQL SIGNAL、worker 退出和 NEEDS_REVIEW，撤除触发器并原样恢复观测设置，再向同一 Kafka 分区重放原消息。原 receipt、实际结果字节/时间和未提交 offset 必须保持，不能把正常重启当作丢结果验证。MCP 则在确认唯一真实 Fetch writer 的 nonce/pool 后暂停真实 runner；控制请求超时必须保留待核对状态并拒绝新安装，恢复 runner 后通过既有 reconcile 核对同一进程树确已退出。故障时间窗未观察到时验收失败，不以模块 XML 替代运行故障证明，也不清除未知业务结果来获得 PASS。这些故障只发生在本轮拥有的测试数据库、进程和对象中。

公开的 `runtime-acceptance.json` 绑定固定构建、模型隔离实际观察、9 份场景文件及 cleanup 摘要；不含凭据、dump 或业务正文。首切的 prepare 和 activate 再核对全部摘要、同一矩阵迁移目标及确实 STOPPED 的清理结果。仅配置完成、模块矩阵 PASS 或 `paidModelCalls=0` 字段本身都不能打开生产门禁。本轮这些运行器仍需由 Jenkins 在可启动的 ECS 上实际执行。

失败时另写 `runtime-failure.json`，只记录固定构建上下文、异常类型、失败阶段、已完成场景摘要和实际清理引用，不归档异常原文或私有日志。cleanup 即使失败也返回 NEEDS_REVIEW 与实际生成文件的 SHA，并以非零状态退出；Jenkins 先收集可核对的失败/清理证据，再判定流水线失败。原正式容器配置、进程代次及 MySQL UUID/schema/表数在运行前后实际读回比较，清理摘要不能用固定 false 声称源资源未变。
