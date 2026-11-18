# 单体开发

当前开发主线是 `java-cloud`。先完成单体的 29 表迁移、真实 Redis 和业务整合，再统一验收；微服务方案不进入本轮实现。通用约定见 [开发总规则](../开发规则.md)。

## 代码放在哪里

| 任务 | 修改入口 |
| --- | --- |
| HTTP、业务流程和存储 | Spring Boot 按领域放在 `doorhandle-module-*`，模块间通过 `doorhandle-contracts` 交互；启动与装配在 `doorhandle-server` |
| 主站和独立聊天 | `frontend`（Vue）与 `frontend-agent`（React）；涉及共同的会话、权限或消息协议时，两端一起检查 |
| 异步检测 | [Python Worker](../../python/worker/)，通过 Kafka 接收任务、读取 OSS 原图并返回结果；保留派发编号、回执与提交顺序，见 [检测执行回执](检测执行回执与事务消息.md) |
| MySQL 与 Redis | 业务事实以 MySQL 为准；Redis 是缓存和协调组件。写操作一起检查事务提交、缓存失效及旧数据的读取边界 |
| Agent | 按 [Agent 开发](../agent/README.md) 修改工具、会话和执行边界，业务事实与授权仍由各领域负责 |

业务范围见 [系统功能说明](系统功能说明.md)。人员、设备解绑等基础数据修改不得级联删除应保留的领用或业务历史；表结构、映射和迁移要一起查。

## 开发环境与构建

- Windows 本地仅编辑、编译和打包，可编译测试源码但不运行测试或启动业务。Java 从仓库根目录使用 `mvn -DskipTests=true clean package`。
- 实验室 Ubuntu 按 [配置方案](配置方案.md) 复用同一个 `java-cloud` 工作区。先确认实际 SSH 连通性和主机密钥，再同步固定版本；开发阶段先不用 Jenkins，不占用主机已有 Redis。
- 镜像构建和挂载遵循 [单体 Docker 部署](docker-monolith-deployment.md)：从项目根目录使用 `compose.monolith.yml`，按需叠加 [Compose 配置](../../deploy/compose/)。不同验收环境使用各自的项目名、数据卷和私有配置。
- 显式配置数据库地址、账号及密码，不回退本机 root 连接。宿主机的 `DOORHANDLE_ENV_FILE` 与容器内 Java 的 `DOORHANDLE_JAVA_ENV_FILE` 不是同一个入口。私有文件不写入 Git。

## 切表和恢复

确认新旧表映射及读写方，保留原始 SQL 和恢复点，在隔离环境完成整库迁移和双恢复。脚本、校对边界和正式门禁见 [29 表迁移与部署协议](../database/compact-deployment.md)；应用回滚不能只换镜像，应确认数据仍可由目标版本正确读取与写入。已有正式数据或切换可能产生新写入时，按协议决定同目标恢复或前向修复，不让旧库重新成为写者。

## ECS 统一验收与发布

现行 Jenkins 路径下，单元/集成测试全部在 ECS 执行。实验室目前只作为直接开发目标；正式统一验收若改用实验室，先按 [配置方案](配置方案.md) 确认准入和执行入口，不绕过原 ECS 身份检查。

1. 整合代码、前后端接线、迁移、夹具、取消和恢复后，再做跳测试构建。提交推送前核对 SCM 触发；同一固定提交只安排一轮完整验收。
2. ECS 路径复用本地 Jenkins `http://127.0.0.1:8080/` 和 `doorhandle-local-ci`，只使用 [Jenkinsfile.ecs-monolith](../../Jenkinsfile.ecs-monolith)。核对远端 `java-cloud` 与 `TRUSTED_COMMIT` 一致。流水线通过 SSH/SCP 调度既有 ECS；[验证脚本](../../script/jenkins/verify-ecs.py) 用 `DOORHANDLE_ECS_INSTANCE_ID`、`DOORHANDLE_ECS_MACHINE_ID` 核验实例和机器身份。目标为 `Status=Stopped`、`StoppedMode=StopCharging` 或身份不匹配时停止，不启动实例、不转为 Windows 测试。
3. 使用本轮专属目录、凭据与隔离数据库。真实 MySQL、Redis、Worker 及业务运行必须按 [固定验收清单](../../script/jenkins/compact-acceptance.json) 和 [29 表协议](../database/compact-deployment.md) 消费实际服务与证据，不用源码检查替代运行结果。
4. 验收通过并确认同一候选后才能发布。生产与旧库演练门禁默认关闭；没有对应结果不得打开 `DOORHANDLE_COMPACT_RELEASE_READY` 或 `DOORHANDLE_COMPACT_REHEARSAL_READY`。测试结束回收本轮临时资源，不关闭 ECS 或停业务。若测试已结束且原报告已保全，只缺本地收证时使用 `ACTION=collect-existing-evidence`，用 `EXISTING_EVIDENCE_BUILD` 指定原构建号，不重跑同一轮测试。

常用运维和数据检查见 [服务器运行说明](服务器运行说明.md) 与 [备份恢复](单体备份恢复与运维检查.md)。过程报告留存于各轮原件目录，本页不复制历史验收结果。
