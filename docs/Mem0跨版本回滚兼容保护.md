# Mem0 跨版本回滚兼容保护

2026-10-18，UTC+8；`java-cloud` 单体。真实 ECS 上的隔离 Docker 保护演练 21 项通过，已修复实际容器 ID 与只读 WAL 探测问题；生产版本激活、完整 Jenkins 发布/回滚与最终统一发布仍待完成。

## 保留的约束

回滚后端和网页不能撤销本人已经设置的记忆停用、有效期、清理状态，也不能丢失提炼回执的去重语义。本轮复用原 Jenkins、Compose 和 Mem0 服务，不添加常驻网关、第二个数据库或新的云实例。

桥接协议分为 0（原有接口）、1（持久提炼回执）、2（逐条生命周期）。新镜像声明 `io.doorhandle.memory-protocol=2`，实际健康接口也报告协议、回执、生命周期及私有认证配置状态；不能只依赖镜像标签。

私有 SQLite 增加单行 `bridge_protocol_floor`：接受提炼请求时同事务至少升为 1，保存生命周期控制时同事务至少升为 2，之后不自动降低。既有回执/控制记录可推导最低要求；新代码发现超过自身版本的要求，会在修改遗留运行状态或初始化 SDK 前拒绝启动，不按旧格式继续执行。

## 激活和回滚顺序

1. 发布助手持有原 `deploy.lock`；Jenkins 上传当前可信提交的 `memory-compat.py`，回滚到旧目录时仍使用当前助手，不执行历史目录中的旧部署逻辑。
2. 固定目标镜像摘要并记录原容器身份，先停止后端，再停止 Mem0。停止后检查容器身份及运行状态，避免在探测最低要求后仍有写入提升协议，或后端读取尚未核实的新桥接。
3. 使用已有 Mem0 镜像中的 Python 标准库，以非 root、禁用网络、禁止拉取镜像、只读根文件系统和只读指定命名卷运行探测。只读取回执 SQLite；不启动 SDK、不注入 API 凭据、不调用模型。SQLite 即使使用 `mode=ro` 也可能需要创建 WAL 辅助文件，因此先只读复制已静止的数据库及 WAL 到私有临时内存目录，在副本上以普通 `mode=ro` 核对，不用可能忽略 WAL 的 immutable 模式。临时内存上限 256 MiB，源文件合计上限 192 MiB，容器内存 384 MiB、1 CPU、64 进程；超限、非普通文件、链接或复制期间身份/大小/修改时间变化均拒绝激活，原卷始终只读。损坏、不确定的存储不视作空库；已有写入锁而回执文件丢失、截断或缺失必要表时停止激活，运行时也不自动重建一个空回执库。
4. 在 `state/memory-minimum.json` 保存已观察到的最高最低要求和卷身份。后续尝试不能因为新容器错误挂到空卷而降低要求；卷变化必须核对。
5. 目标镜像满足要求时正常替换 Mem0；目标过旧时保留原兼容 Mem0 容器，直接启动原容器，保留其环境、挂载、网络及身份，只回滚后端和网页。没有兼容镜像时保持后端停止，要求选用兼容恢复版本；不能启动不受控旧桥接来伪装恢复成功。
6. 等待 Mem0 健康，再检查实际镜像摘要、卷、保留时的容器身份、真实健康协议及能力。确认后才启动后端、网页并运行原健康检查。

发布失败恢复和手动 `ACTION=rollback` 使用同一路径。手动回滚允许后端、网页或 Mem0 不健康，以便恢复故障应用；MySQL、Redis、Kafka、Chroma 和 PTH worker 仍需满足原门槛。恢复失败不删除卷、不清空回执、不自动重放提炼或未知清理。

这是单机替换，停止后端会中断当前连接；沿用既有会话中断恢复，不承诺零停机。直接运行旧部署脚本或管理员手动启动旧镜像不属于本保护路径。

## 旧客户端与记录

新 Java 客户端发送 `X-Doorhandle-Memory-Protocol: 2`。新版 Mem0 仅向声明协议 2 的本人列表/单条读取响应增加生命周期字段，旧客户端继续获得原六字段 DTO，避免 Jackson 严格反序列化失败。已核对原线上提交 54e59613408f 的 Item/Page 和 ObjectMapper 实现。检索与提炼对既有记忆的停用/到期过滤始终生效，不随请求头降级。旧界面不提供新控制入口，管理这些设置需要新版界面。

旧客户端没有请求编号时仍用兼容指纹去重。处理中返回 503 且标明操作已开始，不能让旧客户端把 202 当作添加成功；完成后相同内容只读取原回执，不再执行 SDK。

| 记录 | 内容 |
| --- | --- |
| `state/memory-transition.json` | PREPARED、QUIESCED、DECIDED、VERIFIED 或 FAILED；原/目标/实际镜像、容器、卷、协议与 UTC+8 时间，不含私人记忆、凭据或环境值 |
| `state/memory-minimum.json` | 只升不降的协议要求及原卷身份 |
| `state/memory-activation-images.yml` | 实际采用的不可变 Mem0 摘要；纳入镜像保留保护 |
| Jenkins `artifacts/memory-transition.json` | 发布成功后读取的核实记录 |
| Jenkins `artifacts/deployment.json` | 健康结果、最低协议及是否保留兼容桥接 |

记录以私有临时文件写入并 fsync 后原子替换；Linux 同步父目录。保留模式不会更改原容器配置。Jenkins 最后读取记录失败时，不伪造完整部署构件；应用可能已完成切换，应核对服务器状态，不能仅凭此类网络错误重复发布。

## 依据、验证和边界

使用现有 Docker CLI/Compose，依据 [Docker run 的挂载、网络、只读及入口参数](https://docs.docker.com/reference/cli/docker/container/run/)、[Docker stop 的终止行为](https://docs.docker.com/reference/cli/docker/container/stop/) 和 [SQLite WAL 的只读要求](https://sqlite.org/wal.html#read_only_databases)；未复制第三方实现或增加 Python 依赖。

本地验证使用真实 SQLite/WAL/进程及有状态 Docker 协议替身，覆盖升级、旧镜像回滚保留容器、无数据时允许旧桥接、最高要求不降低、原卷变化、存储损坏、协议谎报、容器身份变化、核实前后端提前启动、未来协议拒绝、旧 DTO 字段和待定保存不报成功，以及保留镜像的清理保护。Bash 实际执行检查激活顺序、失败短路、保留时不重建 Mem0，以及故障应用回滚和数据库门槛。单体 Java 检查包含私有 HTTP 协议头。

这些不是 Docker 守护进程、容器只读权限、Linux 锁继承或真实生产回滚的验证。当前未运行本机 Docker、未启动 ECS、未发布中间版本。真实云端演练仍是放行条件；跨会话语义重复、真实长期记忆质量及七项整体任务继续推进。

最终本地结果：Python 全量 173 项及 6 subtest 通过，包含实际缺失/截断/缺表、未来协议、WAL 和旧客户端检查；日志 work/memory-compat-python-final.log。独立目录完整 Maven clean verify 786 项中 759 通过、27 项可选联调跳过、0 失败/错误，13 个模块构建成功；日志 work/memory-compat-maven.log。Java 与配置逐项比对当前源码一致。Bash、PowerShell 语法及 Python 编译检查通过。前端源码本轮未变，沿用上一轮对应测试与构建，不把重复检查当作新功能验收。

## 真实 Docker 保护演练补充

使用 `script/diagnostics/memory-rollback-docker-drill.py` 与明确隔离的原生 SDK fixture，在现有 ECS 运行 21 项检查通过。随机项目、新命名卷、无网络、无端口、非 root 与资源上限；本机既有依赖镜像上仅复制当前桥接源码，不下载软件或传入生产凭据。所有测试数据均为合成数据，不挂载生产卷。

演练实际运行原 `memory-compat.py` 的 CLI 与继承锁描述符，仅把模块内项目选择改为本次随机测试项目。桥接为真实 FastAPI、已安装 Mem0/Chroma、SQLite 回执和生命周期；模型/Embedding 为确定性离线替身。后端用可停止的占位进程验证门控，不把它当作完整 Java 应用或 Jenkins 生产回滚。

覆盖空卷升级、实际健康协议核实、旧目标保留原容器/镜像/卷、协议最低值保持 2、旧 DTO、停用/到期检索过滤、相同请求重启后原生写入仅一次、后端提前启动被停止、镜像标签与真实协议不符被拒绝、换错空卷被拒绝及原卷恢复。另保持真实未检查点 WAL 打开，使用同一只读 Docker 探测器读取已提交记录，源数据库/WAL/辅助文件哈希不变。

实际检查发现并修复两项原协议替身未覆盖的问题：`docker ps -aq` 默认只给短 ID，现显式 `--no-trunc` 并在替身模拟默认截断；只读卷上 SQLite 创建 WAL 辅助文件失败，现使用上述有界私有副本。容器查询行为依据 [Docker CLI 文档](https://docs.docker.com/reference/cli/docker/container/ls/)。早期失败演练保留，不重写为成功。

最终私有报告为服务器 `verification/memory-rollback-20261018/run-f/result.json`，本地镜像副本与日志为 `work/memory-rollback-docker-drill-20261018-result.json`、`work/memory-rollback-docker-drill-20261018-f.log`。新建容器、三个测试卷和测试镜像已清理；生产全部容器身份/镜像/运行状态前后相同，11 项常驻服务 healthy。完整 Python 203 项及 6 subtest、其中运维/回滚/发布定向 62 项通过；本轮无 Java/前端业务源码变化，未重复运行 Maven 或前端构建。完整 Jenkins 真实应用升级/回滚、生产新协议启用及统一发布仍保留验收门槛。
