# 单体中间件与业务表边界

本轮沿用 `java-cloud` 模块化单体，按《第三个工作—技术方案》调整可复用的中间件能力；微服务拆分留待单体完成后。业务库保持 **29 张目标表**，不因为接入监控或向量存储增加业务表。

## 29 张表分别保存什么

| 业务边界 | 数量 | 表 |
| --- | ---: | --- |
| 组织、员工与登录身份 | 3 | `organization_department`、`employee`、`users` |
| 设备与使用状态 | 3 | `device_management`、`device_usage`、`device_alert` |
| 检测模型、任务与质检结果 | 7 | `model_management`、`detection_work_unit`、`detection_task`、`detection_input`、`quality_report`、`detection_duplicate_ticket`、`historical_detection_summary` |
| 统一内容与版本 | 4 | `content_asset`、`content_revision`、`content_chunk`、`content_link` |
| 会话与智能体执行 | 4 | `chat_project`、`chat_session`、`chat_message`、`agent_run` |
| 模型接入、配置、额度与用量 | 4 | `agent_connector`、`llm_configuration`、`llm_quota`、`llm_usage` |
| 运行状态、流程、计划与审计 | 4 | `runtime_state`、`workflow_instance`、`scheduled_plan`、`audit_event` |
| **合计** | **29** | |

员工档案与登录账号有不同生命周期，检测输入与结果有不同写入规则，内容与版本需要独立追溯，因此不为少几张表强行合并。当前单企业、多角色、多用户的组织与授权边界保留。

`content_chunk` 保存可恢复的正文片段；Qdrant 索引可由这些片段重建，不能替代正文。索引进度复用 `runtime_state/SEMANTIC_INDEX` 的闭合字段和 CAS 版本，不给每种内容再建状态表，也不向历史版本记录塞入可变的向量状态。

这是目标设计。原业务库与目标库正式切换、整库迁移验收仍须独立完成；29 表源码存在不代表正式 131 表已经切换。

## 中间件各管一件事

| 组件 | 本轮职责 | 数据边界 |
| --- | --- | --- |
| MySQL | 业务事务、权限、额度、执行及审计 | 上述 29 表 |
| Redis | 既有缓存、限流、模型熔断协调 | 不替代业务原始记录 |
| Kafka/KRaft | 检测任务与业务事件 | 保留原幂等、回执和未知结果处理 |
| OSS | 图片、模型和交付文件 | 保留对象引用与授权规则 |
| Qdrant | RAG、知识、个人记忆、已批准经验的语义索引 | 四个独立集合；账号、版本与向量空间隔离 |
| Mem0 | 记忆提炼、检索与治理 | 向量用 Qdrant；历史与回执仍为单写者 SQLite 文件 |
| Resilience4j | 模型并发隔离与现有调用入口的故障处理 | 保留 Redis 熔断栅栏与原子额度扣减，不重放未知计费请求 |
| OpenTelemetry | 脱敏后的智能体、模型、工具和 Worker 追踪 | 有界队列、独立开关；原始业务内容与秘密不出队列 |
| Prometheus / Alertmanager | 私网指标抓取与告警 | 独立运行数据；业务审计仍归 MySQL |
| Langfuse（可选完整栈） | 智能体追踪、评估与调试 | 自有 PostgreSQL、ClickHouse、专用 Redis 与 OSS 前缀 |

Langfuse 的内部表不是 29 张业务表的一部分，但必须纳入实际存储清单和备份。单体不增加 Seata、Nacos、Dubbo、额外 AI 网关、Collector、Jaeger 或第二套日志数据库。

## 默认部署不覆盖旧数据

- Qdrant 由固定源码配方准入官方 1.20.0 Linux/amd64 镜像，消费实际不可变 engine image ID；Docker containerd 的 manifest ID 与 config ID分别核实。
- 新 Qdrant 卷挂 `/data`，包含 `storage/` 与 `snapshots/`。新 Mem0 目标卷为 `doorhandle-mem0-qdrant`；旧 `doorhandle-mem0`、`doorhandle-chroma` 保留为只读恢复来源，不直接挂新运行容器。
- `QDRANT_PRIVATE_DIR` 是 ECS 私有目录，含 `api-key` 与 `server.json`。服务配置的 storage/snapshots 路径分别为 `/data/storage`、`/data/snapshots`；UID/GID 为 `10001:10001`，配置只读挂到 `/run/doorhandle-vector`。
- 可观测秘密目录只读挂 `/run/observability-secrets`；目录组 `10001`、权限 `0550`，文件 `0440`。文件名为 `metrics-token`、`langfuse-public-key`、`langfuse-secret-key`、`identity-hmac-key`。关闭遥测时目录可为空；启用时缺必要文件应拒绝连接，不采用默认令牌。
- Actuator 健康检查仍在后端私网 `8080`。Prometheus 使用独立机器令牌；Nginx 不转发 `/actuator`，不另开管理端口。

## 构建和验收顺序

全部源码整合后，本地仅跳测试构建；固定提交推送后，由现有本地 Jenkins `Jenkinsfile.ecs-monolith` 调度 ECS。既有 `verify/source` 增加真实 Qdrant 专属夹具，分别通过 Java gRPC 与 Python SDK 验证，不依赖尚未完成的正式数据库切库。

夹具只接收合成数据，使用随机私网端口、独立密钥和独立集合；要求原生 SDK 用例实际运行且零跳过。失败时保留原件，收尾先停止工具、保存容器状态和日志，再清理本轮夹具。提供方调用数为零，不能把这一段写成 BGE 生产激活证明。

真实 83 条 RAG 与 30 条业务记忆的 BGE 重建、归一化、重启及独立恢复另有候选回执。原有数据、恢复点、生产发布与正式切库门保留。细节见 [向量存储](semantic-vector-storage.md) 与 [可观测部署](../observability/monolith.md)。

2026-11-14 用户确定本轮先完成 Qdrant、模型故障隔离、OTel、Prometheus 的接入验收；Langfuse 保留完整部署配置，待资源审定后再启用。本轮不拉取或启动 Langfuse，也不增加付费资源。OTel 的真实 SDK/HTTP 协议验收与 Langfuse 实际运行状态分别记录。

## 固定镜像由本地 Jenkins 中继，不依赖 ECS 访问 Docker Hub

`#297` 在启动测试前访问 Docker Hub 失败；当次镜像尚未下载、导入或创建容器。ECS 到认证和 registry 两个官方域均不可达，而本地既有网络可以到达。后续沿用已有 BuildKit 公共构建输入链：本地 Python 只下载官方固定 OCI 字节，受管 SCP 发布到 ECS，ECS 原量测器验证后才导入。没有增加代理、镜像平台、常驻服务或本地容器。

三组件的官方 linux/amd64 manifest、config 和版本仍由固定提交的 `compact-build-resources.py` 决定。`fetch-buildkit-build-input.py --component` 只允许 `buildkit`、`qdrant`、`prometheus`、`alertmanager`；省略参数继续原 BuildKit 入口和缓存契约。Qdrant 官方重复空层保留原有顺序与每一位置的 DiffID，仅对相同 digest、大小、media type 的 blob 去重下载和传输；重复 tar 成员、冲突 descriptor 或额外未引用数据仍拒绝。

代码提交后，可在 ECS 开机前用既有本地 Python 预取（不是运行测试）：

```powershell
Set-Location D:/AI/lunwen1/DoorHandleCatch
foreach ($component in 'qdrant','prometheus','alertmanager') {
    python -I -B script/jenkins/fetch-buildkit-build-input.py `
        --component $component `
        --resources-source script/docker/compact-build-resources.py `
        --output-dir "D:/AI/lunwen1/DoorHandleCatch/work/jenkins/build-deps/middleware/$component"
    if ($LASTEXITCODE -ne 0) { throw "固定镜像输入下载失败：$component" }
}
```

本地缓存位于该组件目录下的完整 manifest digest 子目录，保留原始 manifest、blob 和 `<component>-oci.tar`。已有完整包会重新核验固定图和字节后复用，不再访问 registry。真实下载和完整 DiffID/导入验收各有回执，不能用预取成功代替 ECS 测试。

现有 `PrepareTools` 步骤在固定 source 上传后调用同一下载及传输接口，不增加 Jenkins stage。ECS 共享输入为 `<CI_ROOT>/build-inputs/<component>/<archive-sha256>.tar`；每次发布只写一个本 release 的 `<component>-image-input.json`，绑定 release、commit、sourceSha256、实际 ECS identity 和闭合的 `{file, sha256, bytes}`。组件 fixture 必须消费该指针；缺失或不匹配直接失败，不退回 ECS 下载路线。原 BuildKit `buildkit-v0.34.2` 路径、`buildkitArchive` 回执及原请求前提保留。

磁盘不按“镜像已下载”视为零成本。三镜像层的声明压缩大小合计 **232,888,217 B**，完整 OCI 包还包含配置、manifest 与 tar 块；每包仍不超过原128MiB，三个共享包的上界为384MiB。传输按顺序测实际剩余空间，预留2.25GiB主机底线、当前完整上传大小和元数据；先前缓存和另外两包已反映在实际余量中。ECS 从同一个受持有 FD 校验的不可变包直接量测和导入，不为每次构建再复制全部 layer 或生成第二份导入 tar；daemon ingest 和实际新层展开仍按原 Supervisor 阶段预算准入。

成功导入后保留共享原始包、官方原始 manifest、层量测、engine config/manifest ID、资源采样和安全传输回执，仅清理本轮拥有的上传暂存及派生拷贝。导入终态未知时保全原件并阻止完成。原始 OCI 包不放入 Jenkins `artifacts`，三个有界的 `<component>-image-input-transport.json` 记录下载、同文件传输、发布和清理结果。

当前单体 ECS 为 16 GiB 内存；完整生产 Langfuse 栈的资源预检必须先于其任何镜像拉取，当前主机达不到既定生产内存门槛。ECS 启停仍在流水线之外，测试后必须实际回读 `Stopped / StopCharging`；保留的云盘仍计存储费。
