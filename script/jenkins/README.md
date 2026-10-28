# 本机 Jenkins → 北京 ECS

2026-10-27 源码新增演练参数 `COMPATIBLE_RUNNER_IMAGE`、`REHEARSAL_MEMORY_EXTRACTION_MODEL`，与已有兼容 backend 一起传给隔离演练并核对回执。构建可选 `BUILD_NPM_REGISTRY`（默认 npm 官方源），只传给本次远端进程。按用户要求未运行任何流水线、测试或构建；生产开关仍关闭。参数用途和剩余发布条件见 [本轮续开发](../../docs/单体收尾续开发-20261027.md)。

2026-10-22 源码新增固定 runner 升级与 V60 部署镜像保留，发布/回滚共享同一锁，记录独立尝试并保护当前/上一/过渡镜像。公开 Jenkins 产物只含筛选后的技术字段；私有恢复配置不得归档到公共产物。首次兼容基线及真实验收仍待完成，当前未运行，见 [运行器发布](../../docs/MCP运行器升级与部署镜像保留.md)。

2026-10-22 新增 MCP 原生协议发布/回滚保护接线，包含新执行暂停值快照、持久格式下限与独立元数据回执；本轮没有运行 Jenkins、脚本或云端操作。第一次兼容基线与真实演练仍待完成，见 [实现与边界](../../docs/MCP原生协议发布与回滚保护.md)。

复用已有 Windows Jenkins，不重新安装。`jenkins.war` 是启动包，`JENKINS_HOME` 保存任务、插件与凭据，里面的 `war/` 是解压缓存。不要用备份覆盖较新的任务目录。Jenkins JVM 按版本要求使用 JDK 21/25，项目 Maven 构建仍使用 JDK 17。

本机启动包已核对为 `D:/ruanjian/jenkins.war`（2.541.1），现有数据目录为 `C:/Users/19771/.jenkins`；用户提供的 `C:/Users/19771/JenkinsBackups/jenkins-home-20260831-141128/war` 位于备份，备份比现有目录少一个任务，本轮未恢复或覆盖备份。已使用现有 Java 25 启动在 `http://127.0.0.1:18080/`，避开项目后端 8080。需要重启时使用 `start-existing.ps1` 并明确传入原 WAR、Java 和数据目录；脚本不会创建新 Jenkins Home。进程与启动日志保存在项目 `work/jenkins/`。

## 流水线

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

## 配置任务

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
