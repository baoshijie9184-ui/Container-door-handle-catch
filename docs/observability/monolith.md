# 单体通用中间件：运行追踪、指标与故障隔离

本轮按《第三个工作—技术方案》5.4/5.5调整现有模块化单体，不照搬微服务拓扑。保留 Java 17、Spring Boot 3.2.4、AgentScope Java 2.0.4；MySQL、Redis、Kafka、OSS 继续承担原业务职责。Qdrant/Mem0/经验召回由对应实现接入。业务表仍是已确认的 **29张目标表**；Langfuse 自身 PostgreSQL/ClickHouse 表是独立中间件内部结构，不回填业务库，也不算业务表精简成果。

## 默认路径与可选组件

- Java、检测 Worker、Mem0 直接通过 OTel HTTP/protobuf 向 Langfuse 发出安全追踪；不默认增加 OTel Collector、Jaeger 或 VictoriaLogs。
- Prometheus 抓取业务容器的私有指标端点；Alertmanager 分组与展示告警。默认通知接收者只在本机 UI 展示，**尚未配置外部通知渠道**。
- Langfuse 完整自建栈是单独 `langfuse` profile：Web、Worker、PostgreSQL、ClickHouse、专用 Redis、现有 OSS 的隔离前缀。不能用 MySQL 代替 PostgreSQL，不能省略 ClickHouse，也不能让业务 Redis 的淘汰策略承担 Langfuse 队列。
- 单体不引入 Seata、Nacos、Dubbo、额外业务网关或 Langfuse AI Gateway。保留的分布式历史设计和原数据不因本轮配置调整而删除。

新增入口为 `compose.observability.monolith.yml`；`observability` profile 仅启动 Prometheus/Alertmanager，`langfuse` profile 才包含完整 Langfuse 栈。所有入口都仍由本地 Jenkins 调度 ECS，不能在开发机运行这些 Compose。

本轮验收必要组件 Qdrant、Resilience4j、OTel 和 Prometheus；完整 Langfuse 暂留配置，待资源审定后再部署。OTel 使用真实 SDK 向本轮自有假 HTTP 接收端导出，验证关联、协议、脱敏和失败隔离；该结果不代替后续 Langfuse 存储查询验收。

## 追踪只保留有用且有界的技术事实

`RoleAgentFactory` 为主 Agent、直接专业 Agent、工具委派创建的专业 Agent 安装 AgentScope 原生 `OtelTracingMiddleware`。Reactor 上下文传播运行编号、实际模型、模型配置版本、角色、真实工具策略版本和显式选用的 SOP 版本；同一次模型/工具调用共享 TraceID。异步 Kafka 工作开始独立 trace，通过业务分派编号和安全的来源 TraceID 关联，不把等待人工审批的全过程维持成一个长 span。

导出白名单不包含账号、会话原值、问题、回复、图像、工具参数/结果、OSS key/预签名 URL、异常正文/堆栈、外部 baggage/tracestate。Java 在进入队列前生成独立安全快照，不间接持有原 span；再在出口做一次白名单。Python 的 owner/session/user 仅在提供 HMAC 私钥时导出伪名，缺少私钥则省略。

复用官方 `BatchSpanProcessor`，额外的非等待 admission 同时限制排队和正在导出的条目。Java 默认最多1024条、每批128条、导出超时3秒；SDK 属性最多48项、每项128字符、不保留事件和链接。队列满直接丢弃技术遥测并增加指标，导出失败不阻塞业务、不触发 Agent/工具重试。SDK 原始网络错误日志关闭，失败通过固定 reason 指标查看。

追踪默认关闭。Java 配置在 `doorhandle.observability`：

| 配置项 | 默认值/用途 |
| --- | --- |
| `tracing-enabled` | false |
| `endpoint` | 无默认；必须是完整 `/api/public/otel/v1/traces` HTTP(S) 地址 |
| `public-key-file`, `secret-key-file` | 私有挂载文件，不接受示例账号口令 |
| `service-name` | doorhandle-monolith |
| `sample-ratio` | 0.1；按 TraceID 比例决定，不信任外部 sampled flag 强制全采样 |
| `queue-size`, `batch-size`, `timeout-millis` | 1024、128、3000；启用时校验上下限 |
| `metrics-token-file` | 空则 `/actuator/prometheus` 一律401 |

单一 SDK 同时供 Micrometer 和 AgentScope 使用；不要再安装并行 Java agent/global SDK。Langfuse 接收 HTTP JSON/protobuf，不接受 OTLP gRPC，`localhost:4317` 不是有效的 Langfuse 接入地址。请求带 Basic 项目密钥及 `x-langfuse-ingestion-version: 4`。Python 的生命周期接口、私有指标端口和精确环境名见 [Python运行遥测](python-runtime.md)。

## 指标和权限保持原入口契约

后端继续在私有 Docker 网络 `backend:8080` 提供 `/actuator/health`，不为指标迁移原健康入口。只有精确 `/actuator/prometheus` 使用高优先级机器 Bearer 链；令牌从私有文件读取、常量时间比较，只接受 GET，不接收 query token，不授予业务权限。其他 Actuator 保留原业务认证；Nginx 拒绝对外代理 Actuator。Worker/Mem0 分别用容器私有9464/9465端口，不发布公网。

Prometheus 配置使用只读 token 文件和有界 scrape sample/label 数；不以 run/task/trace/session/user/动态模型编号做 label。指标包括 JVM、HTTP、业务 readiness、有限操作耗时、遥测积压、丢弃和导出失败。规则覆盖应用不可达、worker未就绪、遥测失败/丢弃、JVM堆压力和所在文件系统余量。

运行凭据目录只读挂载到`/run/observability-secrets`，文件为`metrics-token`、`langfuse-public-key`、`langfuse-secret-key`、可选`identity-hmac-key`。ECS上由Jenkins私有凭据准备步骤设置共享只读组（`OBSERVABILITY_SECRET_GID`默认10001）、目录0550和文件0440；Prometheus通过附加组读取，不改变上游默认运行UID。不要将真实凭据、展开后的Compose或带短期URL的夹具加入制品归档。

Prometheus 保存7天并设512MB TSDB保留目标；WAL、head和压缩过程仍需额外空间，512MB**不是整个目录硬限额**。新指标栈建议另留至少3GiB，实际以镜像、WAL和磁盘余量回读为准。

## Resilience4j 复用原治理门面

- 本地 `ModelCircuit` 使用 Resilience4j 2.4.0 CircuitBreaker 作为实际计数/许可引擎；门面保留连续失败、AUTH/QUOTA立即开路及长冷却、一个真实请求半开探测、代次栅栏和取消票据。没有额外付费探测调用。
- 版本化配置仍使用原 `RedisModelCircuit` Lua 原子协调；Redis不可用时保留失败，不回退进程内“假健康”，不削弱跨实例单探测或额度账本。
- 所有 `ManagedAgentModel` 路由实际接入非等待 Resilience4j Bulkhead。`agentscope.models.max-concurrent-calls` 默认32，满额在发出供应商请求前拒绝；取消后释放。部署限制同步用于旧配置版本客户端。
- 保留原首字/总超时、仅在尚未输出且原策略允许时选择备用、未知付费结果结算、工具确认/幂等和业务审计。没有包装整段 Agent 的 Retry，也不将配额或审计改为“遥测尽力写入”。

## Langfuse 完整自建需要先过资源门

官方v4列出的各组件生产最低资源合计 **9 vCPU / 21.5GiB内存**，不含对象存储和本项目业务。此处逐项生产容器限制沿用该内存下限，额外预留操作系统、业务和突发余量。当前16GiB ECS不能默认同时承载完整生产栈。

新增 `deploy/observability/resource_preflight.py` 在 **任何新镜像拉取之前**由 Jenkins 在 ECS 执行，只读取内存和目标文件系统，不购买、扩容或清理资源：

| 门 | 整机内存 | 当前可用内存 | 额外自由磁盘 |
| --- | --- | --- | --- |
| production | ≥32GiB | ≥24GiB | ≥30GiB + 原业务/恢复保留预算 |
| isolated-smoke | ≥8GiB | ≥6GiB | ≥12GiB + 原业务/恢复保留预算 |

磁盘是本项目保守启动预算，不是厂商容量保证，包含镜像、各数据目录初期增长和压缩瞬时余量；运行后仍需持续监测。调用必须显式提供业务保留预算和输出回执，并设置匹配的审核值 `LANGFUSE_RESOURCE_APPROVED=production-reviewed` 或 `isolated-smoke-reviewed`。Compose 内第二道 gate 再检查内存/磁盘、私有配置和初始化信息；它不能替代拉镜像前的原生预检。

隔离 smoke 另叠加 `compose.observability.smoke.yml`，使用完整相同版本组件，只降低资源限制并限制为少量合成事件。它只用于验证接入、异常和恢复，不代表高可用、生产吞吐或性能SLO，更不能暗中取代生产配置。即便设置了 profile，没有独立审核和足够资源也不启动；本轮未授权新增ECS/磁盘/EE/SaaS。

免费自建核心的自动 Data Retention 不可假定存在：官方将自建自动保留策略列为 Enterprise Edition，免费核心默认永久保存。长期启用前须审定可恢复的独立保留/删除流程及增长预算；本实现不填一个7天参数冒充已获得付费能力，也不自动删除既有业务资料。

## OSS 兼容性必须实测完整路径

Langfuse 将 OSS 归为社区支持的 S3-compatible 选项。模板隔离 `langfuse/events/`、`langfuse/media/` 前缀，禁用批量导出；RAM 凭据只授予对应前缀必要权限，不复用业务全桶权限。Bucket/region/签名风格/CORS由实际服务器和浏览器行为决定，不能仅用endpoint可连认定兼容。

已提供可重复使用的验收夹具：

1. `deploy/observability/oss-compatibility.mjs prepare <私有manifest> <回执>`：在选定的 Langfuse Worker 镜像内复用它随附的 AWS SDK，对随机自有前缀验证服务端写入/读回、签名PUT/GET，生成5分钟的私有浏览器夹具。
2. ECS既有浏览器工具执行 `oss-browser-compatibility.py`，从真实 Langfuse origin 用原生浏览器 fetch 验证预签名PUT/GET和CORS。不开`disable-web-security`，不拦截替换请求。私有manifest不得归档或打印。
3. `finally`执行同一mjs的`cleanup`，只删除manifest里该UUID的三个固定对象，抹掉短期URL，保留安全回执；准备失败也使用预先写下的归属manifest收尾。
4. 通过真实OTLP摄入，再从Langfuse项目查询同一TraceID和运行/模型版本，确认Web→Redis→Worker→OSS→ClickHouse路径，而不是只检查Web健康页。

任何步骤未通过，OSS/Langfuse正式接入仍未验收。用户文件、模型数据和已有OSS引用不属于这些夹具的清理范围。

## 构建后统一在 ECS 验收

新代码完成整合后再由固定提交的本地Jenkins执行：

- Java：脱敏、安全快照、异步导出故障/容量释放、Agent原生关联、机器采集鉴权、原ModelCircuit/Redis/额度/路由回归及新增Bulkhead取消/拒绝；Python：真实SDK假HTTP摄入、无敏感内容、队列满、停机、metrics授权、Worker golden/commit顺序、资源门边界。
- ECS有限合成烟测：真实Prometheus抓取、401/405拒绝、告警实际触发/解除和Alertmanager分组；配置外部通知后才验证送达。
- 全Langfuse需先独立资源审核和预检，随后完整栈健康、项目初始化、跨运行追踪查询、OSS上述完整链路、exporter故障不影响业务、组件重启后历史可读。未满足资源不拉镜像、不删业务缓存凑数。
- 收集脱敏回执、清理本轮自有夹具，由流水线外执行StopInstance/StopCharging并回读；Jenkins继续运行。正式并发/容量压测仍按用户决定后置。

固定提交`7cef30943e928e2fac57001bad2275c23c8faa5a`的#312已在ECS通过指标抓取和下述告警闭环；Windows长路径收证错误已修复，#315完整补收原265份报告，未重跑项目测试，原#312仍为FAILURE。实际OSS兼容性、外部告警送达和真实Langfuse查询仍按上述独立条件验收。

### 用真实 Prometheus 验收 Java 和 Python 指标

现有 source 验证由 `script/jenkins/observability-fixture.py` 的 `Fixture(checkout, context)` 创建本轮自有 Prometheus 3.16.0 与 Alertmanager 0.35.0。它复用受管 OCI 镜像准备接口，不调用 daemon pull；仅绑定随机 `127.0.0.1` 端口，以 UID1000、只读根文件系统和固定 CPU/内存限额运行。Alertmanager 只接收本轮合成规则，接收者 `owned-null` 不发送外部消息。

镜像准备前及容器启动前要求实际可用内存至少 **9.125GiB**、自由磁盘至少 **3GiB**。内存按串行工具6GiB、Qdrant512MiB、单个测试MySQL1GiB、Prometheus512MiB、Alertmanager128MiB和主机保留1GiB相加；运行中保留2.25GiB磁盘。既有工具和数据库自己的更高资源门仍生效。

- Java `PrometheusScrapeIntegrationTest.realPrometheusScrapesAuthenticatedActuatorCountersAndHistogram` 启动最小 Spring/Actuator 应用，不扫描业务模块或连接数据库。真实计数器和直方图经原 `/actuator/prometheus` 机器认证端点被 Prometheus 抓取。
- Python `tests_python.test_observability_scrape.test_real_prometheus_scrapes_authenticated_python_counter_and_histogram` 使用共享 `RuntimeTelemetry` 的真实 HTTP 服务和指标注册表，不创建模型客户端。
- 两端都必须实测缺失/错误令牌401、正确令牌200，经 file-SD 登记随机端点，并从真实 Prometheus API 读到 `up`、计数器及直方图。最终收尾再次独立查询历史样本。
- 告警闭环使用同一 attempt 的两条合成告警，核对真实 Prometheus 规则状态与 Alertmanager 的两条告警、一个分组；随后只修改本轮规则并重载自有 Prometheus。只有规则变为 inactive、Alertmanager 告警和分组消失，且实际 resolved 接收计数至少增加2，才记为解除成功。每阶段保留实际 HTTP 响应，不以容器停止或自然过期充当解除证明。#312实际完成两条同组告警及解除，接收计数从0增至2，`alertLifecycle.status=PASS`。

`prepare()` 返回五项 `DOORHANDLE_` 环境变量：`TEST_PROMETHEUS_URL`、`TEST_ALERTMANAGER_URL`、`TEST_OBSERVABILITY_TARGETS`、`TEST_OBSERVABILITY_TOKEN_FILE`、`REQUIRE_OBSERVABILITY_TESTS=true`。令牌只存私有文件，不进入容器命令行、环境变量值或安全回执。

`stop()` 即使指标验收失败也逐个停止自己的容器，保全实际 inspect、stdout/stderr、查询和告警原件后再移除容器；仅清理本轮令牌及合成 TSDB/静默数据。安全回执区分 `metricsAcceptance` 与 `cleanupConfirmed`，清理成功不能冒充指标通过；镜像导入终态未知时保留原件并拒绝确认完成。查询原件留在本轮 `work/observability-fixture/evidence`，通用归档仅收录安全 `observability-fixture.json` 引用。

### ECS统一Python工具镜像包含完整运行依赖

`script/jenkins/python-test-requirements.txt`现为9个CI包加13个Mem0运行包，共22个固定版本。既有`prepare-ecs-tools.py`从固定源码额外保全`deploy/mem0/requirements.txt`，在创建pip容器前核对13包集合与每个精确版本均包含于22包；真正安装、`pip check`和installed-versions回执覆盖全部22包。sourceFiles与completion原件列表包含第三份`requirements.txt`，read-prepared再次核对；不是给旧工具镜像贴一个新SDK标签。

原9包缓存只有原版本和原生产recipe、完整安装证据匹配时才可复用。请求新13包闭包的准备不能走该缓存路径，仍使用原2GiB增长上限、真实磁盘保留、容器身份、断线只读观察和最终原件验证；空间不足则拒绝，不扩大预算或启动模型下载。

产物`pythonImageId`仍是既有CI工具配置（执行用户UID:GID、WORKDIR `/`、惰性`python --version`），不直接冒充Mem0运行镜像。受管BuildKit候选消费该已安装依赖层，再写入当前13包`/app/requirements.txt`并验证app10001与`/data`，以极小适配层恢复原运行契约；不再pip一套相同依赖。Qdrant服务器镜像使用独立的受管fixture准入，不混入Python安装回执。

## 版本、来源与许可

Java仅引入OTel小BOM 1.61.0和Reactor instrumentation 2.27.0-alpha，与AgentScope2.0.4对齐，不导入其Boot4/Spring7依赖BOM。Micrometer沿用Boot3.2.4管理版本。固定镜像候选：Langfuse Web/Worker4.79.0、ClickHouse26.3.62.3、PostgreSQL17.12-alpine3.24、Redis7.4.12-alpine3.22、Prometheus3.16.0、Alertmanager0.35.0；ECS实际使用前须核定该版本镜像digest及架构，不改成latest。

- [AgentScope2.0.4原生OTel中间件](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-core/src/main/java/io/agentscope/core/tracing/OtelTracingMiddleware.java)、[该版本依赖BOM](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-dependencies-bom/pom.xml)：Apache-2.0。
- [OpenTelemetry1.61.0](https://github.com/open-telemetry/opentelemetry-java/releases/tag/v1.61.0)、[Resilience4j2.4.0](https://github.com/resilience4j/resilience4j/releases/tag/v2.4.0)：Apache-2.0；使用公开SDK API，不复制内部队列实现。
- [Langfuse4.79.0](https://github.com/langfuse/langfuse/releases/tag/v4.79.0)、[官方Compose](https://github.com/langfuse/langfuse/blob/v4.79.0/docker-compose.yml)、[核心/EE许可证边界](https://github.com/langfuse/langfuse/blob/v4.79.0/LICENSE)：核心MIT，EE目录另有许可；本轮不依赖EE。
- [Langfuse资源下限](https://langfuse.com/self-hosting/configuration/scaling)、[OTel接入](https://langfuse.com/docs/opentelemetry/get-started)、[S3兼容Blob配置](https://langfuse.com/self-hosting/deployment/infrastructure/blobstorage)、[自建保留策略许可](https://langfuse.com/docs/administration/data-retention)。
- [Prometheus3.16.0](https://github.com/prometheus/prometheus/releases/tag/v3.16.0)、[Alertmanager0.35.0](https://github.com/prometheus/alertmanager/releases/tag/v0.35.0)、[TSDB保留与空间](https://prometheus.io/docs/prometheus/latest/storage/)：Apache-2.0。
- PostgreSQL为PostgreSQL License；ClickHouse为Apache-2.0；Redis7.4为RSALv2/SSPLv1双许可，限本企业内部部署而非再销售托管Redis服务。镜像保留上游许可证；Redis许可与Langfuse的Redis/Valkey兼容性可在后续替换评估中单独审定，本轮不顺带升级业务Redis。
