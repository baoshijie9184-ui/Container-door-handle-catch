# 本机 Jenkins → 北京 ECS

复用已有 Windows Jenkins，不重新安装。`jenkins.war` 是启动包，`JENKINS_HOME` 保存任务、插件与凭据，里面的 `war/` 是解压缓存。不要用备份覆盖较新的任务目录。Jenkins JVM 按版本要求使用 JDK 21/25，项目 Maven 构建仍使用 JDK 17。

本机启动包已核对为 `D:/ruanjian/jenkins.war`（2.541.1），现有数据目录为 `C:/Users/19771/.jenkins`；用户提供的 `C:/Users/19771/JenkinsBackups/jenkins-home-20260831-141128/war` 位于备份，备份比现有目录少一个任务，本轮未恢复或覆盖备份。已使用现有 Java 25 启动在 `http://127.0.0.1:18080/`，避开项目后端 8080。需要重启时使用 `start-existing.ps1` 并明确传入原 WAR、Java 和数据目录；脚本不会创建新 Jenkins Home。进程与启动日志保存在项目 `work/jenkins/`。

## 流水线

1. 从 Git 检出可信 `java` 分支，每 5 分钟轮询，无需向公网开放本机 Webhook。按用户明确要求，用本地 `java` 覆盖原远程 `java`，旧远程提交保留为本地备份引用；不创建额外部署分支。
2. 发布前校验 SSH、公钥、私有配置与 Docker，不可达即失败，不自动启动 ECS。
3. 本机执行 Maven `clean verify`、全部 Python 测试、Vue/React 测试及两套生产构建，失败则阻止发布。
4. 用 `git archive HEAD` 打包提交内容及 SHA-256，通过 SSH/SCP 上传；忽略目录、私钥、权重、真实环境配置不进入归档。
5. ECS 构建后端与 Web 镜像，使用固定 Compose 项目名复用卷；逐项检查健康，失败则尝试恢复实际旧镜像 ID。
6. `ACTION=rollback` 回到上一次成功应用版本；失败会尝试恢复当前版本。不会回滚数据库或 OSS 文件。

需要先把流水线和修改推到远程 `java`，Jenkins 才能获取。首次历史覆盖使用绑定已核对远程提交号的 `--force-with-lease`；之后通常 `git push origin java` 即可，不应每次强推。Jenkins 替代手工测试、构建和发布，不会自动上传未提交的本地修改。

## 配置任务

新建 Pipeline，例如 `doorhandle-java`，选择 **Pipeline script from SCM**：Git 地址为本项目 origin，Branch `*/java`，Script Path `Jenkinsfile`。`job.xml.example` 可用于创建任务，默认禁用，配置完成再启用；不要覆盖原有任务。GitHub 私有库需要另加只读仓库凭据。

需要 Pipeline/Declarative、Git、Credentials Binding、SSH Credentials、JUnit、Timestamper 插件，不需要 Docker Pipeline。不要为本轮配置批量升级已有插件。

Jenkins Credentials 配置：

| ID | 类型 | 内容 |
| --- | --- | --- |
| `doorhandle-ecs-ssh` | SSH Username with private key | 用户 `ecs-user` 和原北京实例私钥 |
| `doorhandle-ecs-known-hosts` | Secret file | 经可信渠道核验的 ECS SSH 主机公钥记录；非默认端口使用 `[主机]:端口` 格式 |

首次执行 `ACTION=verify`。验证通过并确认 SSH 完成认证后使用 `verify-deploy`；回滚使用 `rollback`。

| 参数 | 当前配置 |
| --- | --- |
| `DEPLOY_HOST` | 从控制台核对的当前 ECS 公网 IP，默认空，停机再启动后重新检查 |
| `DEPLOY_PORT` | 已验证的 SSH 端口，默认 22 |
| `REMOTE_ROOT` | `/home/ecs-user/doorhandle-ci`，新版本及状态目录 |
| `REMOTE_RUNTIME` | `/home/ecs-user/doorhandle-release-20261014`，现有私有配置和模型上下文 |
| `BUILD_WORKSPACE` | 专用 D 盘目录，默认项目 `work/jenkins/workspace`，不能填开发源码根目录 |
| `PYTHON_EXE` | 现有隔离测试环境，默认 `D:/ruanjian/anaconda3/envs/leetcode/python.exe` |

节点 PATH 需包含 Git、OpenSSH、Maven、Node/npm，Maven 使用 JDK 17。Python 环境需包含项目 Kafka/OSS、Mem0、ONNX、pytest 等测试依赖。ONNX 测试仅验证现有兼容实现，生产仍直接使用 PTH，不执行转换。真实模型/API 凭据只保留在服务器 `deploy/cloud.env`，不注入测试，不上传为 Jenkins 构件。

## 部署与恢复边界

- 当前自动更新 **Java 后端与两套前端**。Mem0、Chroma、PTH worker 和其他中间件复用已运行镜像，不因应用 tag 变化重建；它们的更新需要单独验收。
- 远端要求八项常驻服务健康；刚开机尚未就绪时稍后重跑。数据库迁移不自动执行，新增 SQL 须先核对兼容性和备份。
- 每个任务禁止并发，服务器另用 `flock` 串行部署。新版本保存在 `REMOTE_ROOT/releases/ci-构建号-提交号`，`state/` 保存当前、上次目录及实际镜像 ID。
- 沿用现有 Dockerfile 与云端源；构建网络失败不会切换应用。发布不执行 `down -v`、卷清理或数据库重建，不自动删除旧镜像或版本。
- 严格核验 SSH 主机公钥；未知/变更公钥、连接重置均阻止发布。“实例运行中”不代表 SSH 或业务健康。
- 这是单实例替换，后端更新可能短暂不可用；健康失败会尝试回滚。中断、服务器重启或回滚也失败时，需检查容器与状态记录，不能宣称零停机或事务回滚。
- 仅本人可信分支可使用发布凭据。现有控制器直接构建只适合个人可信代码；多人接入时按官方建议设置独立构建节点、控制器执行器为 0。

## 开源依据

使用 Jenkins 官方能力与现有 Compose，没有复制第三方模板代码。Jenkins 采用 MIT 许可证，本项目许可证保持原样。

- [Jenkinsfile 与凭据](https://www.jenkins.io/doc/book/pipeline/jenkinsfile/)
- [Pipeline 与 pollSCM](https://www.jenkins.io/doc/book/pipeline/syntax/)
- [控制器隔离](https://www.jenkins.io/doc/book/security/controller-isolation/)
- [MIT 许可证](https://www.jenkins.io/license/)
