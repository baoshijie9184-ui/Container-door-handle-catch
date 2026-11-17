# 本机 Jenkins → 北京 ECS

## 当前约定（2026-11-16）

后续单体与微服务 CI/CD 统一使用现有本地 Jenkins 控制器 <http://127.0.0.1:8080/>，账号 `admin`，密码保存在 Git 忽略的 [项目私有登录文档](../../work/jenkins/local-access.md)。当前入口、启动命令和流程以 [本地 Jenkins CI/CD 约定](../../docs/本地Jenkins-CICD.md) 为准。服务已启动并通过浏览器以 `admin` 登录，本地独立节点和统一任务入口已配置；启用任务前须确认 CI 文件已推送到 SCM 分支，最终启用状态以配置回执为准，不据此宣称已完成项目测试或发布验收。

本地允许运行 Jenkins 控制器并编辑、构建代码；应用、数据、预览及所有测试在 ECS 执行。Jenkins 始终运行；ECS 保持开启，由用户自行关闭；助手不在测试前后自动启停，也不安排验收后的关机任务。本轮自有临时资源仍须收尾并保全报告，不停止业务服务或 ECS。流水线不执行开机、关机或安排限时停止任务。当前统一入口为 `Jenkinsfile.ecs-monolith`，本地专用节点 `doorhandle-local-ci` 沿用 SSH/SCP，在已启动 ECS 的隔离目录执行测试，不新增常驻 ECS Jenkins agent。旧 `Jenkinsfile` 的本地测试流程不可继续使用，生产发布和旧库演练额外受默认未设置的机器环境门禁限制，待数据库重构与迁移验收后再启用。`start-existing.ps1` 的默认端口已统一为 8080。

Python 测试工具需要新装依赖时，固定源码配方沿用 `compose.cloud.yml` 的阿里云 HTTPS PyPI 镜像 `https://mirrors.aliyun.com/pypi/simple`。安装仍使用隔离 pip、固定版本、禁用缓存、原始 pip 下载摘要报告、`pip check` 和实际版本回读；不增加备用源或绕过 TLS 校验。2 GiB 总增长包络、磁盘保底、容器内存限制及 1,800 秒期限保持不变，真实安装和新增命令回归均由后续固定提交在 ECS 验证。

新建工具准备前只读检查 apt 服务和内核包管理锁，活动升级未结束时拒绝开始；原件回读及清理不受此门影响，不停止或禁用系统更新。长轮验证前还须核对实际更新计时器，选择不重叠的窗口。MySQL 内核限额检查失败时分别保存两个控制文件的读数及采样阶段；`lastKernelObservation` 仅代表上次成功探针，不能当作失败现场。限额和失败即停止规则保持不变。

启动完整验证 driver 前，以主机 `MemAvailable` 对照 1 GiB 保底、5888 MiB Python/Java 实际重叠额度、全部自有 fixture 和 watcher 的剩余额度。已启动组件只抵扣身份核验后的匿名驻留内存，不抵扣文件缓存；按 MySQL 3 GiB、Qdrant 512 MiB、Prometheus 512 MiB、Alertmanager 128 MiB、Redis 128 MiB 和 watcher 256 MiB 上限计算。原回执 `fixtureRuntime.memoryAdmission` 保存可用量、各组件观测、所需量和差额；真实内存拒绝且尚未请求启动 driver 时，另记 `driverStart={requested:false,blockedBy:FIXTURE_MEMORY_ADMISSION}`。这不是全程峰值保证，后续原资源监控和失败收尾继续生效。

独立 Java 工具实际硬限额为 1792 MiB，`runtime_limits` 的整数 bytes 同时用于 Docker 创建、owned 检查、公开回执和并发账。Java 使用 `-Xmx1024m`、256 MiB 元空间、直接内存/代码缓存各 128 MiB 及 OOM 立即退出；Maven 仍为原 4 GiB/1536 MiB 堆。完整源 SQL 当前为 13,148,174 B，这一配置仍需完成真实整库复制和双恢复，不能当作任意极端输入的容量保证。原 npm/Python 输出路由未变，生成物回收同时保留新旧两个精确审核配方，已有来源不能因本轮 JVM 限额更新失去准入。

## 完整迁移先于 native Java

带 `wholeMigrationConfig` 的完整 MySQL 验收先执行一次原全量 Python，再执行全部 native Java、普通 Java 回归及前端。这样真实 131→29 复制或双恢复失败会先停止，不必等待约两小时的 native 用例。整库 Java bridge 使用本轮上传的固定候选 JAR，无需先编译测试源码；worker 使用自己预先创建的独立空库。普通 source 和 java-only 入口顺序不变。

用例、fixture 输入、原始 XML 路径和通过门不变；跨语言协议汇总在两种语言完成后进行，Java 输出仍在 Java 结束后清理。迁移、Python 临时物会更早与后续 Java 输出共存，不能将旧顺序的磁盘峰值视为新顺序的容量保证；原实时磁盘保底、资源采样和失败收尾保持生效。

完整自动夹具入口现在在同一次 Python 执行中先完成既有控制模块，再执行其余 Python/整库与 Java；原 `python.xml` 保留全部真实用例，不重复运行一遍独立控制阶段。`--control-gate` 的收集、每例 setup/call/teardown 和原 XML 复核共同构成前置门，身份、owner、包管理、内存和磁盘准入仍在工具/夹具启动前执行。独立 `ACTION=verify-controls` 保留，旧手工局部调用不隐式升级为完整验收。

## 真实 Redis 验证

固定源码的完整 ECS 验证由现有 `verify-remote.py` 创建一个合成 Redis fixture，仅复用正式 Redis 的 immutable image，不读取正式凭据或数据。临时服务映射随机回环端口、无持久卷，内存硬上限 128 MiB、Redis 数据上限 64 MiB；监督器负责就绪检查、运行观察、失败收尾和原始回执。现有 25 项真实 Redis 用例仅操作少量合成缓存条目或固定字段熔断 Hash；保留 64 MiB `maxmemory`、`noeviction` 和无 AOF/RDB，容器的额外 64 MiB 用于进程及客户端开销，不减少用例或宿主保底。

fixture 将 `DOORHANDLE_CACHE_REDIS_TEST_HOST/PORT/DATABASE` 及 `DOORHANDLE_REQUIRE_REDIS_TESTS=true` 传给现有测试工具。原缓存真实 put/get 和 3 项跨客户端熔断检查必须实际执行，另有 21 项领用缓存提交/回滚检查；缺失、条件跳过或失败不能通过完整验收。未提供该隔离环境的既有独立调用仍保持原选择规则，不启用生产服务。`reports/redis-fixture.json` 与实际 Java XML 一起归档，PASS 还要求自有 Redis 已 STOPPED。

## 已结束的 15 个历史 MySQL 副本

**本批已由 #380 完成，15 项清单已消费，不得再次执行。** 实际回收 4,004,081,664 B；下文保留入口与原件核对方法。

既有 `ACTION=reclaim-build-outputs`、`DOORHANDLE_CI_SCOPE=source` 可选择精确策略 `NATIVE_RETENTION_POLICY=DerivedMysqlHistorical15`，仅处理 #154/#160/#162/#166/#168/#173/#187/#188/#189/#195/#198/#201/#204/#223/#224 的派生 MySQL 目录。所有其他选择器及 `finishedOutputsManifest` 保持空值，生产发布关闭，不先执行通用历史清理。

私有清单位于 `work/table-switch-20261115/historical-derived-mysql-15-manifest.json`。本地先核对全部原件 custody，再上传原 build.xml、release.json 和既有用户授权；远端重新核对完整源 SQL、固定源码、原 owner/STOPPED、目录身份和全部活动引用，经原 plan/apply 执行。原始 SQL、源码、报告、业务库和保护恢复点保留。本批受控计量与删除回执均为 4,004,081,664 B，15 项全部移除。

## 应用 runtime 启动前的精确输出维护

`manifest-pre-runtime-outputs-v1` 继续只按独立私有清单处理已结束轮次的两份未发布 JAR 和派生 MySQL，源 SQL、源码和报告保留。#389 的原失败发生在 watcher 就绪前；`post` 的 Generated 收尾随后复制了 `verify-remote.py`，该文件存在不代表验证 driver 已启动。

这一形状仅在原源码中的 preparer/verifier 匹配审核过的 a351 字节、原 Jenkins 为 FAILURE、原 failure 记录 `FIXTURE_WATCH_START_FAILED_STOP_CONFIRMED`、parent owner 按原异常路径移除了 `fixtureWatch`（独立 watch-owner 原件仍保留）、owner 和 cleanup 一致确认同一进程组已停止，并且 ready、claim、driver、验证回执和上传标记全部不存在时准入。实际容器退役同样读取原 watcher 的 `FAILED/watchStopped=false` 和父取消原件，确认原进程已不存在后才接受父确认停止，不要求伪造 driver 报告。保留原失败回执，不补造退出码；任一未知生产者、启动标记或未闭合收尾仍拒绝。原无 helper 的 NOT_STARTED 路径以及 SQL 完整、主机/目录身份、全 UID 引用和原件绑定门保持不变。源码支持不等于本批已回收，实际清理仍须统一控制验证后经 Jenkins 执行一次精确清单。

完整迁移先于原生测试执行时，`runtime-migration.json` 是整库复制、双恢复、拒绝重放及读回全部通过后产生的下一阶段输入，不是应用已启动回执。Finished 入口只在固定源码中的该生产者、归档 Python 原 XML、driver 汇总、公开 migration 摘要及同一 owner 的私有迁移/双恢复原件全部绑定时接受此输入；后续原生失败仍保持 FAILURE。真实 runtime/candidate-build/发布路径及活动引用继续拒绝，plan、每次删除边界和收尾重新验证原件。该输入、reviewed config、迁移/恢复报告及原 SQL 均保留，删除集合仍只有清单中的两份未发布 JAR 和派生 MySQL。

## 同一 29 表候选的人工验收

`ACTION=verify-runtime`、`DOORHANDLE_CI_SCOPE=mysql` 且生产发布关闭时，可设 `MANUAL_ACCEPTANCE_ENABLED=true`、`MANUAL_ACCEPTANCE_MINUTES=30`（可选 15/30/60）。默认关闭，仍按原自动验收后立即收尾。此入口不使用 `rehearse` 或 `REHEARSAL_KEEP`，不开放生产和旧库演练门。

全部自动断言及 21 项真实页面检查通过后，原 runtime 保持运行和资源采样，Jenkins 建立有界 SSH 回环转发，并写入 `artifacts/manual-acceptance-ready.json`。其中 `localUrl` 是用户在 Jenkins 所在本机浏览器使用的入口；`privateGuide` 指向项目 Git 忽略的 `work/jenkins/manual-acceptance/<release>/access.md`，包含本轮四个测试账号。账号由已有凭据通道私密传输，不输出控制台或归档。`configure-local.groovy` 维护该私有根路径，不需要新增用户参数。

用户在当前构建的 `manual-candidate-acceptance` input 选择“验收通过”或“发现问题”，也可在聊天告知助手处理同一 input。截止时间由原 runtime 固定，重连不续期；拒绝、取消或超时按原失败路径保全证据并收尾。确认通过后也必须完成原 `STOPPED` 清理及最终证据检查才能得到 SUCCESS。窗口结束关闭本轮入口并删除临时私密账号说明，不关闭 ECS 或原业务服务。READY 只表示可以开始人工操作，不是最终 PASS；模型仍使用隔离脚本/本地配置，不调用付费外部模型。

## 同轮验收、首次切表与失败处置

正式首次发布使用 `ACTION=compact-cutover`、`DOORHANDLE_CI_SCOPE=mysql`、明确完整 `TRUSTED_COMMIT`、`PRODUCTION_RELEASE_ENABLED=true` 和 `MANUAL_ACCEPTANCE_ENABLED=true`。其余封存输入及 `COMPACT_CUTOVER_SETTINGS` 必须与批准的固定输入相同。流水线只执行一次完整自动验收和一次同候选人验；临时候选 `STOPPED`、全部原件核验通过后，直接消费本轮证据切换，不再重跑一轮 runtime，也不跨构建拼接 PASS。此动作的人验 input 明确包含批准正式停写上线；没有用户实际确认、拒绝或过期，均不进入生产。

机器环境的 `DOORHANDLE_COMPACT_RELEASE_READY` 仍默认 `false`。版本化配置仅从本地私有 `local-node.json` 的可选 `compactReleaseAuthorization` 读取 `work/jenkins/compact-release-authorization-<完整40位提交>.json`，默认空；该路径不是 Jenkins 页面参数。授权 JSON 使用 `schemaVersion=1`、`kind=doorhandle-compact-release-authorization`、`scope=first-production-131-to-29`、`job=doorhandle-java`、`branch=java-cloud`，明确 `approved=true`、`revoked=false`、当前用户授权 `approvalReference`、完整 `commit/sourceSha256/identity`，以及 `settingsSha256` 和全部固定 `inputs`。`inputs` 精确键名见 `compact-cutover.py:RELEASE_INPUTS`，未使用项也明确为空字符串；包含源/封存输入、ECS 根与正式运行目录。配置阶段和实际发布阶段分别重新核验，授权文件不提交、不归档。

恢复策略必须明确 `allowPreActivationSourceRestore=true` 与 `afterActivationFailure=FAIL_CLOSED_COMPACT_ONLY`。发布前，控制器用本轮 `runtime-gate-passed.json`、原 runtime 回执和原 `manual-decision.json` 生成无凭据的批准投影；ECS 再核实际固定镜像、候选绑定的源设置字节、完整自动/人工原件后才开始 `prepare → migrate → activate`。MySQL 使用正式停写后的新鲜快照、备份和完整迁移/双恢复，不用数小时前的候选库覆盖正式数据；RAG/Mem0 既有物化来源的未变化门保持。正式流程保全源备份、双恢复及 native 原件，创建29表目标并验证，最后健康检查通过才开放入口。

旧 worker 只有已审核的 immutable Kafka/OSS 镜像、默认实际命令、七个固定代码文件及父目录未被挂载/写层覆盖时，才允许没有独立 SQL 账号；此旧版本仍必须停止并禁用重启，全部源 SQL 写身份仍盘点和冻结。其他 worker 仍须明确可冻结的非 root 账号，新 compact worker 的目标 DML 账号不豁免。

发布错误或中断沿同一 Jenkins `RecoverCutover` 收尾入口消费原 `compact-cutover-execution-request.json`，不重跑未知迁移：

- **新进程从未启动**：确认冻结及旧源未变后调用原 `recover`，逐个核对原容器身份、运行状态和实际健康，只有 `SOURCE_RESTORED/healthVerified=true` 才报告旧服务恢复；原构建仍保留失败结果。
- **新进程已经启动**：保留目标及全部新写，停止入口/写者，锁住本次创建的目标 DML 账号并核无残留会话。输出 `COMPACT_FORWARD_REQUIRED` 和实际冻结状态；它不是恢复成功。责任人为发布负责人，依据归档回执中的原目标、失败阶段及保留私有原件，对 MCP、memory 或对应失败组件做保数据前向修复，不能改 phase 后重跑 copy、恢复旧快照或启动131表旧写者。
- **身份、冻结、连接或原件未知**：保留 `NEEDS_REVIEW`/原错误与原资源，不盲重放。状态、恢复回执与正式数据读回由当前构建归档；私有配置/密码/SQL 不归档。

验证和应用 runtime 取消分别使用原 helper 的 `cancel`：严格绑定 release、attempt/executionId、固定源码、ECS 和 PID/startTicks，随后原 `observe` 等到终态才清理自有资源。正式切表同样先 exact cancel → 原 finally 终态及维护锁释放 → settle；取消持久化后仅向绑定的 supervisor 发一次 TERM，迁移子会话收到正常中断且必须退出、无剩余迁移 SQL 会话后才允许恢复旧服务。子进程或锁仍未知则保留维护状态，不杀数据库/业务容器来伪造退出。SSH 255 重连仍只观察，不当作用户取消；Jenkins 已取消后不在归档期间再次 `/stop`。

## 生成物收尾与独立维护

常规流水线默认在 `post always` 停止本轮测试工具、归档原始证据后，执行 `CleanupGeneratedArtifacts`。SUCCESS、UNSTABLE、FAILURE 和 ABORTED 均可进入；不等待当前 Jenkins 构建离开 post，也不以业务测试 PASS 作为回收前提。收尾失败不会跳过原始证据归档。

可丢弃生成物完成后保留 **0 轮**，异常残留预算 **512 MiB**。每轮归档 `generated-cleanup-plan.json`、`generated-cleanup-receipt.json`、`generated-cleanup-journal.jsonl` 和控制回执；`retention.scope=DISPOSABLE_GENERATED_OUTPUTS`，`SATISFIED` 仅表示该授权范围内的收尾完成，不表示整个 checkout 已清空。授权生成物仍缺证据、存在未知引用或清理失败时，列明路径、原因和 UNKNOWN 容量判断，并令收尾失败，不计入已释放量。实际空间采用回收前后磁盘读数；各阶段磁盘保底继续生效。

MySQL 组合验证的 `tmp/pytest` 不适用纯 source 合成目录删除规则。只有同一构建的原件及身份已认证、MySQL scope 与执行记录完整，且原执行器明确记录 `pythonTemporaryCleanup.status=RETAINED_NATIVE_EVIDENCE` 时，才将该准确路径列入 `preservedEvidence`，原样保留而不作为收尾失败。其未测容量标记 `NOT_MEASURED`，不计作零占用或已释放空间，也不计入可丢弃生成物的预算。缺报告、重复 Python 命令、非法字段或身份不符仍阻断；不按 `PYTEST_SOURCE_SCOPE_REQUIRED` 原因码整体豁免。业务验证的原始 PASS/FAILED 不变，真正的收尾及收证失败仍使流水线失败。

独立历史维护可用 `SYNTHETIC_PYTEST_CASE` 精确选择其中已证明的普通合成测试副本。目前仅登记 #337/#341/#366/#375/#381/#383/#396/#401/#404/#411/#413 的固定源码及审核过的 22 个控制测试模块，要求原 XML 对应测试全部 PASS、源码函数与 pytest 目录前缀无歧义，并重新绑定原 runner、executor、conftest、模块及该来源新增的直接夹具。整轮 Python 有其他失败不豁免选中 case 的 PASS 要求。它只删除 `tmp/pytest` 下一层明确列出的 case 目录，不删除父根、失败/跳过/未知 case、真实迁移 SQL 或原始报告；任何符号链接、特殊节点、多链接文件或不安全权限都拒绝。自动 native 保留和 source-only 整根规则不变。

这类纯 case 清单每历史轮最多 1,536 项；混合清单与旧类别仍最多 128 项，全局目标 JSON 16 MiB、plan 32 MiB 和实际磁盘保底保持原值。三份清单位于 `work/table-switch-20261115/native-synthetic-pytest-ci-{337,341,366}.json`，已在同一固定提交的 #369 控制验收后由 #370–372 依次消费，实际回收 1,115,832,320 B，清单不得重放。#375 的独立 1,536 项清单已由 #378 消费，回收 395,694,080 B，同样不得重放。#383/#396/#401/#404 的四份 1,536 项清单已由 #407–410 消费，回收 1,565,519,872 B，不得重放。#381/#411/#413 只追加同一模块集合的精确来源，后两轮绑定与 #404 相同的两份额外合成夹具，未新增模块或夹具类型。后续维护仍须独立精确清单，由原 plan/apply 逐项认证原件、UID1000 进程及全容器无活动引用和实时容量；拒读 PID 仍须通过原绑定探针，不能当作无引用；私有清单及新来源登记不代表已经删除。真实整库迁移用例、恢复原件和未核实的嵌套 MySQL 目录不在本批选择中。

历史授权清单通过同一 Jenkins 任务运行：

- `ACTION=reclaim-build-outputs`
- `GENERATED_ARTIFACTS_ONLY=true`
- `GENERATED_RETENTION_MANIFEST` 指向本地私有精确清单
- `NATIVE_RETENTION_POLICY=FailedNative`，两个 `FAILED_*` 参数留空；新选择器直接进入生成物维护，不调用旧 native/MySQL 批次
- `DOORHANDLE_CI_SCOPE=source`，业务、候选、fixture 输入留空，生产发布关闭

清单独立用 SCP 传输，SSH 参数只携带字节绑定，避免 Windows 命令行长度限制。`configure-local.groovy` 与 Jenkinsfile 同步维护参数。先以 `ACTION=verify-controls`（生成物参数保持默认空值）在 ECS 执行轻量控制回归，不先制造数据库克隆。

可退役内容限于已证明的编译目录、前端 node_modules/npm 缓存、公共工具下载副本及本轮合成 pytest 临时目录。混放内容、证据未闭合、活动引用或无法确认的 socket 明确保留，不整目录清除 checkout、inbox 或 tool-home。业务库、原始 SQL、源码、报告、#266 恢复点、#117 公共层 keeper、共享 Maven 缓存及运行/待上线候选均保留；#57/#59 私有旧 Maven 另需完整共享 keeper 的逐项字节证明。进程扫描范围为执行用户 UID；Docker 引用检查覆盖所有容器，包括已停止但仍挂载目标的容器。

历史源码测试还会在 `java-suites/suite-001` 留下 Maven `package` 生成物。原六类编译目录规则不删除依赖拷贝和 JAR；新增精确类型 `SOURCE_DEPENDENCIES`、`SOURCE_JAR` 分别只对应 `doorhandle-module-app/dependency` 与 `doorhandle-server/doorhandle-server-0.0.1-SNAPSHOT.jar`。历史清单仅准入 #219/#147/#183；今后已登记轮次的同路径由自动收尾发现。固定源码 POM 必须证明隔离构建和依赖复制位置，原归档日志必须逐文件记录复制或生成，Maven 命令已结束、SOURCE 原报告保全且无引用才可退役。失败 SOURCE 保留 FAILED，不要求伪造 PASS；混入 SQL、目录或未记录文件时保留整个目标。原普通 Verified 合同不变。

这三轮的新精确私有清单为 `work/middleware-alignment-20261113/source-package-retirement-input-20261114.json`，共 6 个目标，实测分配 2,321,580,032 字节；需在包含修复的固定提交通过 ECS 控制验证后，再使用上述 Generated 独立维护参数执行。它不覆盖已消费的原 52 目标清单，也不包含 #83、#225/#229 或此前 7 项权限拒绝对象。源码接线完成不等于这些字节已释放。

本任务失败的 `verify/mysql` 派生库沿原 `FAILED_MYSQL_DATA_BUILDS` 精确编号入口维护，`GENERATED_ARTIFACTS_ONLY=false`，不混入上述六目标清单。数据 plan 同时证明本轮自有 MySQL 容器已停止、源 SQL 和报告完整、无其他引用；apply 先通过既有容器退役方法移除该精确对象，再执行不排除任何容器的原无引用检查和数据回收。两份可再生 JAR 已无不影响这条数据入口，业务容器、原 SQL、报告与 #266 保留。每次 plan/apply/status 原始 stdout/stderr 随维护归档，控制回执记录固定失败码和阶段；收证异常单列，不覆盖原失败，不重放 apply。此修复针对 #324 的停止对象残留，仍须固定提交的 ECS 控制验收和实际回收回执确认完成。

## 历史实施记录

下方为历史环境、流水线及验收记录，其中 `18080` 构建链接保留原地址。本地运行测试、旧 `Jenkinsfile` 与轮询自动发布等旧指令均已失效，不得用于新构建；历史成功不代表当前源码或流水线已验收。

2026-11-05 运行约定：本地仅编辑和构建，运行与测试全部在 ECS `172.29.146.74` 执行，结束后确认 `Stopped / StopCharging`。旧本机运行命令失效，当前入口见 [ECS 运行约定](../../docs/ECS-only-runtime.md)。


2026-10-27 源码新增演练参数 `COMPATIBLE_RUNNER_IMAGE`、`REHEARSAL_MEMORY_EXTRACTION_MODEL`，与已有兼容 backend 一起传给隔离演练并核对回执。构建可选 `BUILD_NPM_REGISTRY`（默认 npm 官方源），只传给本次远端进程。按用户要求未运行任何流水线、测试或构建；生产开关仍关闭。参数用途和剩余发布条件见 [本轮续开发](../../docs/单体收尾续开发-20261027.md)。

2026-10-22 源码新增固定 runner 升级与 V60 部署镜像保留，发布/回滚共享同一锁，记录独立尝试并保护当前/上一/过渡镜像。公开 Jenkins 产物只含筛选后的技术字段；私有恢复配置不得归档到公共产物。首次兼容基线及真实验收仍待完成，当前未运行，见 [运行器发布](../../docs/MCP运行器升级与部署镜像保留.md)。

2026-10-22 新增 MCP 原生协议发布/回滚保护接线，包含新执行暂停值快照、持久格式下限与独立元数据回执；本轮没有运行 Jenkins、脚本或云端操作。第一次兼容基线与真实演练仍待完成，见 [实现与边界](../../docs/MCP原生协议发布与回滚保护.md)。

复用已有 Windows Jenkins，不重新安装。`jenkins.war` 是启动包，`JENKINS_HOME` 保存任务、插件与凭据，里面的 `war/` 是解压缓存。不要用备份覆盖较新的任务目录。Jenkins JVM 按版本要求使用 JDK 21/25，项目 Maven 构建仍使用 JDK 17。

本机启动包已核对为 `D:/ruanjian/jenkins.war`（2.541.1），现有数据目录为 `C:/Users/19771/.jenkins`；用户提供的 `C:/Users/19771/JenkinsBackups/jenkins-home-20260831-141128/war` 位于备份，备份比现有目录少一个任务，未恢复或覆盖备份。历史上曾使用 Java 25 在 `http://127.0.0.1:18080/` 启动；该地址已由上述当前约定替代。需要重启时使用 `start-existing.ps1` 并明确传入原 WAR、Java 和数据目录；脚本不会创建新 Jenkins Home。进程与启动日志保存在项目 `work/jenkins/`。

## 历史流水线（已退役）

2026-10-22 续开发分派兼容保护：发布前核对确认 JSON、稳定身份及 V54 数据格式，快照保留分派写入暂停状态；候选可显式选择已有的兼容旧镜像，不能用候选充当自己的回滚证据。新增代码未执行，首次兼容基线与真实验收仍待完成，见 [分派兼容回滚](../../docs/分派数据格式与兼容回滚.md)。

2026-10-22 源码新增模型 Secret 策略式接入和独立加密备份证明，详见 [模型密钥与发布](../../docs/模型主密钥备份与发布接入.md)。当前按“先完整开发、不进行测试”要求未运行流水线，也没有修改线上 Jenkins 作业。新版 `Jenkinsfile` 默认仅 `verify`，`PRODUCTION_RELEASE_ENABLED=false`；SCM 轮询默认不发布，最终验收后显式开启发布/回滚。下方历史发布记录不代表本轮代码已验证。

2026-10-15 已将现有任务切换到 `*/java-cloud`。[第 8 次构建](http://127.0.0.1:18080/job/doorhandle-java/8/)完整发布成功，当前服务器版本为 `ci-8-0b4690a9c72e`；四账号业务查询、八项容器健康及原 100 张检测结果保留检查通过。分支切换、基础镜像缓存处理和验收边界见 [部署记录](../../docs/服务器演示部署记录.md)。

1. 从 Git 检出可信 `java-cloud` 分支，每 5 分钟轮询，无需向公网开放本机 Webhook。任务模板与现有任务配置 Git MessageExclusion，明确包含 `[skip ci]` 的提交不触发轮询构建，手动构建仍可执行。本分支从 `java` 签出；原 `java` 分支保留，切换本机编辑器分支不会改变 Jenkins 的 SCM 配置。
2. 发布前校验 SSH、公钥、私有配置与 Docker，不可达即失败，不自动启动 ECS。
3. 本机执行 Maven `clean verify`、全部 Python 测试、Vue/React 测试及两套生产构建，失败则阻止发布。
4. 用 `git archive HEAD` 打包提交内容及 SHA-256，通过 SSH/SCP 上传；忽略目录、私钥、权重、真实环境配置不进入归档。
5. ECS 构建后端与 Web 镜像，使用固定 Compose 项目名复用卷；逐项检查健康，失败则尝试恢复实际旧镜像 ID。每次开始仅清空构建工作区内的 `artifacts/`，避免仅验证或早期失败的构建归档上次成功发布的状态。
6. `ACTION=rollback` 回到上一次成功应用版本；失败会尝试恢复当前版本。不会回滚数据库或 OSS 文件。

需要先提交并推送到远程 `java-cloud`，Jenkins 才能获取：首次执行 `git push -u origin java-cloud`，之后通常 `git push` 即可。正常发布无需强推。Jenkins 替代手工测试、构建和发布，不会自动上传未提交的本地修改。

## 历史任务配置（已退役）

现有 Pipeline 继续使用 `doorhandle-java` 这个任务名，**Pipeline script from SCM** 的 Git 地址为本项目 origin，Branch 为 `*/java-cloud`，Script Path 为 `Jenkinsfile`。分支校验只允许 `java-cloud` 与 `origin/java-cloud`。切换已有任务时只修改 SCM 分支，保留凭据、参数和构建历史；`job.xml.example` 用于新建任务，默认禁用，不可用整份模板覆盖现有任务。GitHub 私有库需要另加只读仓库凭据。

需要 Pipeline/Declarative、Git、Credentials Binding、SSH Credentials、JUnit、Timestamper 插件，不需要 Docker Pipeline。不要为本轮配置批量升级已有插件。

Jenkins Credentials 配置：

| ID | 类型 | 内容 |
| --- | --- | --- |
| `doorhandle-ecs-ssh` | SSH Username with private key | 用户 `ecs-user` 和原北京实例私钥 |
| `doorhandle-ecs-known-hosts` | Secret file | 经可信渠道核验的 ECS SSH 主机公钥记录；非默认端口使用 `[主机]:端口` 格式 |

首次执行 `ACTION=verify`。验证通过并确认 SSH 完成认证后使用 `verify-deploy`；回滚使用 `rollback`。

| 参数 | 当前配置 |
| --- | --- |
| `ACTION` | 新版源码默认 `verify`；只有最终验收后才选择 `verify-deploy` 或 `rollback` |
| `PRODUCTION_RELEASE_ENABLED` | 新版默认 false；开发阶段禁止生产发布及回滚，实际任务尚未更新 |
| `COMPATIBLE_BACKEND_IMAGE` | 仅隔离演练使用；可选服务器已有的兼容旧版后端 `sha256:` 镜像 ID，需单独验收，不能与候选相同 |
| `DEPLOY_HOST` | 首次为空，配置后保留最近一次地址供 SCM 触发使用；停机再启动后重新检查 |
| `DEPLOY_PORT` | 已验证的 TLS/SSH 入口，默认 443 |
| `SSH_TRANSPORT` | 当前网络使用 `tls`；普通 SSH 可达的网络可选择 `direct` |
| `SSH_TLS_CA_FILE` | 云助手核对的服务器公有证书，默认项目 `work/cloud/ssh-tls/server.crt` |
| `OPENSSL_EXE` | 现有 Git 客户端的 `D:/ruanjian/Git/usr/bin/openssl.exe` |
| `REMOTE_ROOT` | `/home/ecs-user/doorhandle-ci`，新版本及状态目录 |
| `REMOTE_RUNTIME` | `/home/ecs-user/doorhandle-release-20261014`，现有私有配置和模型上下文 |
| `BUILD_WORKSPACE` | 专用 D 盘目录，默认项目 `work/jenkins/workspace`，不能填开发源码根目录 |
| `PYTHON_EXE` | 现有隔离测试环境，默认 `D:/ruanjian/anaconda3/envs/leetcode/python.exe` |

节点 PATH 需包含 Git、OpenSSH、Maven、Node/npm 和本机已有的 PowerShell 7（`pwsh`），Maven 使用 JDK 17。Python 环境需包含项目 Kafka/OSS、Mem0、ONNX、pytest 等测试依赖。ONNX 测试仅验证现有兼容实现，生产仍直接使用 PTH，不执行转换。真实模型/API 凭据只保留在服务器 `deploy/cloud.env`，不注入测试，不上传为 Jenkins 构件。

Windows 下 Jenkins 临时私钥可能继承工作区中的其他账号 ACL，OpenSSH 会拒绝使用；部署脚本在每次凭据绑定后将该临时文件限制为当前构建身份可访问。脚本使用 `pwsh`，避免 Windows PowerShell 5.1 与继承的 PowerShell 7 模块路径冲突。

## 部署与恢复边界

- 当前统一更新 **Java 后端、两套前端与 Mem0 私有桥接**。Mem0 镜像使用固定 SDK 依赖，先暂停后端和 Mem0 并读取持久协议要求，再核实桥接实际健康。回滚目标过旧时保留兼容 Mem0 原容器，只回滚后端和网页；其余情况正常替换桥接。核实通过才恢复后端；不可兼容时保持停止，不撤销记忆停用或回执保护。Chroma、PTH worker 和其他中间件继续复用已运行镜像。桥接回执与向量/历史共用既有卷，未决提炼在重启后只标记待核对，不重放。
- 远端要求八项常驻服务健康；刚开机尚未就绪时稍后重跑。数据库迁移不自动执行，新增 SQL 须先核对兼容性和备份。
- 每个任务禁止并发，服务器另用 `flock` 串行部署。新版本保存在 `REMOTE_ROOT/releases/ci-构建号-提交号`，`state/` 保存当前、上次目录及实际镜像 ID。
- 沿用现有 Dockerfile 与云端源；构建网络失败不会切换应用。发布不执行 `down -v`、卷清理或数据库重建，不自动删除旧镜像或版本。
- 严格核验 SSH 主机公钥；未知/变更公钥、连接重置均阻止发布。“实例运行中”不代表 SSH 或业务健康。
- 这是单实例替换，后端更新可能短暂不可用；健康失败会尝试回滚。中断、服务器重启或回滚也失败时，需检查容器与状态记录，不能宣称零停机或事务回滚。
- 仅本人可信分支可使用发布凭据。现有控制器直接构建只适合个人可信代码；多人接入时按官方建议设置独立构建节点、控制器执行器为 0。

## 当前网络 SSH 连接修复

2026-10-15：校园网下普通 SSH 在握手时重置，服务器同时记录客户端来源的重置，不能归因于密码或密钥。现使用 **本机 OpenSSL → ECS 443/stunnel → 本机回环 22/sshd**：TLS 验证云助手核对的公有证书及 `doorhandle-ssh.local` 名称，内部 SSH 继续严格核对原主机公钥并使用原私钥认证。不依赖 Clash、临时代理进程或新快捷方式。原 22 端口仍保留，443 安全组仅放行已核对的本机公网出口；网络出口变化时需要调整来源。

在项目根目录连接：

```powershell
ssh -F .\work\cloud\ssh-config doorhandle-bj
```

预先核对 `HostName` 与当前公网 IP。以上配置、证书与私钥留在 Git 忽略的 `work/`；证书公钥可以分发，服务端私钥只保存在 ECS `/etc/doorhandle-ssh-tls/server.key`。不得关闭证书验证或 SSH 主机公钥验证。

服务器组件由 `install-ssh-tls.sh` 通过云助手以 root 安装：Ubuntu 官方 `stunnel4` 包、独立 `doorhandle-ssh-tls.service`、最后应用的 `ssh.socket.d/zz-doorhandle-ssh-tls.conf`，明确同时监听 IPv4/IPv6 的 22 端口。脚本保留原配置快照，安装失败尝试恢复原监听。服务端证书有效期 365 天，续期后须通过可信渠道重新核对并更新客户端证书。`ecs-user` 已加入现有 `docker` 组，重新登录后可执行部署所需 Docker 命令。

连接修复阶段验证了严格校验下的 SSH 登录、Docker/Compose 预检、1 MiB SCP 往返 SHA-256 以及错误 TLS 名称被拒绝。后续完整 Jenkins 实跑已通过，见下面的验收记录。

stunnel 为独立系统工具，采用 GPL-2.0-or-later 并有 OpenSSL 例外；本轮没有复制或修改其源码，Ubuntu 包保留原版权声明。参考 [stunnel 手册](https://www.stunnel.org/manual.html)与[认证说明](https://www.stunnel.org/auth.html)。

## 2026-10-15 完整构建发布验收

最终任务 [doorhandle-java #6](http://127.0.0.1:18080/job/doorhandle-java/6/) 为 **SUCCESS**，耗时约 6 分 46 秒，北京时间 13:55 完成发布。提交 `d81f0089d61fea8a8399a89145b38a87aaf03c9c`，当前版本 `ci-6-d81f0089d61f`。真实执行了 GitHub 检出、SSH 预检、全部测试、双前端生产构建、源码归档及摘要校验、SCP 上传、ECS Docker 构建、应用替换和健康检查，并确认旧发布构件在开始时已清除。

首轮任务 [#4](http://127.0.0.1:18080/job/doorhandle-java/4/) 同样成功，耗时约 14 分 10 秒，版本 `ci-4-b33e47b75ca2`；包括较慢的 Node 基础镜像下载。#5 由 SCM 变化自动触发，确认了触发链路；为应用构件清理修复，在其发布前主动取消，由 #6 完整执行最新脚本。

| 检查 | 结果 |
| --- | --- |
| Java Maven clean verify | 486 项，22 项跳过，0 失败/错误 |
| Python pytest | 59 项与 6 个子测试通过，JUnit 记录 65 项 |
| Vue / React Node 测试 | 54 / 5 项全部通过 |
| 本机及服务器双前端生产构建 | 全部成功 |
| Docker 镜像 | 后端与 Web 均成功构建并使用本次版本标签 |
| 服务健康 | 八项常驻服务 healthy，数据库、缓存、队列、记忆与 worker 未重建 |
| 四账号与页面 | 两名员工、两名主管登录及业务接口通过，检测历史、报告和 Agent 页面无脚本错误 |
| 原有数据 | 原 100 张测试任务仍为 COMPLETED，100 成功、0 失败；PTH 摘要未变 |
| 新任务闭环 | #4 后 `det_20261015_054237_b5d631c2`、#6 后 `det_20261015_055612_ed359aa8` 均完成单张上传→Kafka→模型 105 CPU PTH→OSS 标注图/JSON→Java 落库；这些任务不构成推理性能基准 |

前几次实跑暴露并修复了 checkout 返回值未注入分支/提交变量、Windows 临时 SSH 私钥继承过宽 ACL、旧 PowerShell 模块冲突；失败均发生在应用发布前。还保留了部署主机参数供轮询触发使用，并修正 Jenkins 自身地址为 18080，避免生成错误的 8080 链接。

当前目录 `/home/ecs-user/doorhandle-ci/releases/ci-6-d81f0089d61f`；`state/previous-directory` 保留 #4 部署目录，`previous-images.yml` 已核对 #4 实际镜像 ID，最初 demo 镜像和目录也仍保留。**本轮未执行真实回滚切换**，不能将状态保留和脚本失败处理测试当作云端回滚演练。前端仍存在原有 peer dependency / 构建体积警告，不影响本次构建和页面验收；准确率、容量与模型供应商延迟另行评测。

完整控制台日志、前后业务对比、页面截图和服务器核验放在 Git 忽略的 `work/jenkins/`，汇总为 `ci-deployment-acceptance-20261015.json`。这些记录不含私有环境配置或密钥。访问新版本可在项目根目录运行 `ssh -F work/cloud/ssh-config -N -L 127.0.0.1:18088:127.0.0.1:8088 doorhandle-bj`，然后打开 <http://127.0.0.1:18088/#/login>；本次已建立该本机隧道。

## 开源依据

2026-10-18 运维补充：发布前自动生成一致性备份，失败时不替换应用；成功发布后受限保留旧应用镜像。备份会短暂停止单机服务写入，保留数据库和数据卷，并尝试恢复原服务。中断恢复、隔离演练、定时器及验证边界见 [单体备份恢复与运维检查](../../docs/单体备份恢复与运维检查.md)。本轮代码尚未云端验收，不将协议替身测试记为真实恢复。

使用 Jenkins 官方能力与现有 Compose，没有复制第三方模板代码。Jenkins 采用 MIT 许可证，本项目许可证保持原样。

- [Jenkinsfile 与凭据](https://www.jenkins.io/doc/book/pipeline/jenkinsfile/)
- [Pipeline 与 pollSCM](https://www.jenkins.io/doc/book/pipeline/syntax/)
- [控制器隔离](https://www.jenkins.io/doc/book/security/controller-isolation/)
- [MIT 许可证](https://www.jenkins.io/license/)

2026-10-18 回滚兼容保护：发布助手与 memory-compat.py 一同上传；支持故障应用回滚，但保留数据库健康门槛。state 记录实际桥接摘要、卷及只升不降的最低协议，Jenkins 构件记录是否保留桥接；被保留镜像加入清理保护。实际 Linux/Docker/ECS 演练尚未完成，见 [Mem0 跨版本回滚兼容保护](../../docs/Mem0跨版本回滚兼容保护.md)。
