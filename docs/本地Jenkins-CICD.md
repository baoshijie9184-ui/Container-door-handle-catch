# 本地 Jenkins CI/CD 约定

更新：2026-11-06，北京时间。此约定适用于后续单体及微服务 CI/CD。

用户最新确定：本地 Jenkins 保持运行。ECS 在测试前从流水线外启动，测试完成后再从流水线外节省停机；开机、关机及限时停止任务都不属于 Jenkins CI/CD 阶段。本轮已配置本地独立节点及统一任务入口；启用任务前必须确认对应 CI 文件已提交推送到任务的 SCM 分支，真实 ECS 验收尚未进行。

## 后续开发的默认工作流程

用户已确定：后续构建、集成验证、制品管理、部署与发布失败处置统一由本地 Jenkins 自动流水线编排。开发仍在本地完成，流水线定义和脚本随代码维护；日常交付不再靠逐条手工执行测试或部署命令。此要求已写入仓库 [工作约定](../AGENTS.md)。

目标流程为：

1. 完成分支开发和本地跳过测试的构建，提交并推送代码；准备测试时先在流水线之外启动 ECS 并确认就绪。
2. Jenkins 检测受信任分支的新提交，检出固定提交，核对分支与提交号；未提交的修改不进入发布。
3. 流水线构建并记录制品摘要，检查已启动 ECS 的连通性、实例和执行节点身份。未就绪时明确失败，不自动开机，也不转为本地测试。
4. 在 ECS 隔离环境执行单元、集成和必要的业务验收，归档真实报告。测试失败或必要报告缺失时阻止部署。
5. 通过后按已配置的分支和环境规则自动部署 ECS，记录部署版本，执行健康检查；失败时按兼容策略恢复已验证的旧应用制品。数据库恢复另按迁移方案处理，不随应用回滚自动降级。
6. 无论成功、失败或取消，流水线都收集本轮证据并清理拥有的测试资源。测试工作结束后，再由流水线外的操作执行 ECS 节省停机，回读 `Stopped / StopCharging`；Jenkins 控制器保持运行，不在流水线中安排限时停止任务。

以上流程按阶段配置和验收。本轮提交推送范围限于 CI 相关文件，不包含数据库重构等其余工作区修改；配置、提交推送不等于已运行项目测试或完成生产发布。

## 固定入口与登录信息

- 统一使用现有本地 Jenkins 控制器：<http://127.0.0.1:8080/>。
- 登录账号：`admin`。用户提供的密码记录在项目私有文档 [本地登录信息](../work/jenkins/local-access.md)，不写入版本库、流水线脚本或构建产物。
- 不另建 ECS Jenkins 控制器，不重新安装或覆盖已有 Jenkins Home。本地专用节点标签为 `doorhandle-local-ci`，沿用 SSH/SCP 调度 ECS 中的隔离测试目录和部署目标，不新增常驻 ECS Jenkins agent 或为此安装额外 JRE。
- `18080` 是旧记录中的地址；历史构建链接保留原样，不作为当前入口。

2026-11-06 最新核验：已按用户要求使用现有 WAR、Java 和 Jenkins Home 启动本地 Jenkins，`http://127.0.0.1:8080/login` 返回 HTTP 200，版本 2.541.1；Jenkins 自身配置的根地址也已从历史 18080 同步为 8080。已用用户提供的 `admin` 账号经浏览器登录成功，显示名为 `jevain`，可以查看工作台和 `doorhandle-java` 项目。

本轮配置操作记录：Jenkins 先以暂停构建调度（quiet mode）运行，避免执行旧本地测试；随后配置并验证本地独立节点，控制器恢复正常调度（`quietingDown=false`）并保持运行。`doorhandle-java` 的 Script Path 已改为 `Jenkinsfile.ecs-monolith`；替换期间先禁用项目任务，完成校验并确认 CI 文件已推送到 SCM 分支后再启用，最终状态以配置回执为准。尚未启动 ECS、触发项目测试或应用发布。原地址配置、旧启动日志和启动回执保存在 Git 忽略的 `work/jenkins/startup-*`；临时启动保护脚本已自行移除，没有留下永久的启动钩子。

## 本地与 ECS 的职责

本地允许编辑、编译、打包和运行 Jenkins 控制器。流水线在独立本地 agent 的专用标签 `doorhandle-local-ci` 上执行固定提交检出、源码打包、SSH/SCP 调度、报告收集和发布协调。控制器执行槽为 0；本地 agent 为一个执行槽、`EXCLUSIVE` 模式，通过 WebSocket 只连接 `http://127.0.0.1:8080/`，工作目录位于项目 D 盘 `work/jenkins/local-agent/`。该节点已由配置回执及 Jenkins `/computer/` API 确认在线，回执保存在 Git 忽略的 `work/jenkins/configuration-receipt.json`。

本地 agent 复用已有 Java 25，是与控制器分开的本机进程；不是在 ECS 新装的 agent，也不需要在 ECS 添加常驻控制进程或额外 JRE。本地构建仍跳过测试；不在本地运行应用、数据库、前端预览或测试。

所有测试、应用运行、业务数据和测试数据都放在 ECS。当前单体目标为 `172.29.146.74`，实例 `i-2zeieuov2aum486jm1ek`；未来三机方案须完成节点准入适配，不能直接绕过当前实例校验。本地通过已有 SSH/SCP 连接，在 ECS 的独立 checkout 调用验证和部署脚本，ECS 不运行额外的常驻 Jenkins agent。目标离线或连接资料缺失时，预检明确失败，不自动开机、不无限等待、不转为本地执行。

开发完成后，提交并推送分支 → 本地 Jenkins 检出固定提交 → 编译打包 → 在已经启动的 ECS 隔离环境测试 → 收集报告和制品 → 按已启用的发布规则在 ECS 部署及检查。没有通过测试的提交不能发布。测试完成后清理本轮拥有的测试资源，再从 Jenkins 流水线之外调用 `StopInstance` 并指定 `StoppedMode=StopCharging`，回读确认 `Status=Stopped` 和 `StoppedMode=StopCharging`；保留云盘仍有存储费。Jenkins 不持有 ECS 启停阶段，不因为流水线结束就关闭服务器。

当前统一入口为 `Jenkinsfile.ecs-monolith`，在本地节点 `doorhandle-local-ci` 执行控制步骤，固定受信任的 `java-cloud` 完整提交。本地源码打包后通过 SSH/SCP 传入隔离 checkout，再在 ECS 执行测试；原先要求 `doorhandle-monolith && doorhandle-ecs` 常驻 agent 的方案已替换，旧 `Jenkinsfile` 的 Windows 本地测试流程已退役。启用前确认统一入口和配套脚本已推送到任务的 SCM 分支；已有源码、配置回执或页面登录不代表完整自动发布验收。三机流水线仍需按最终部署方案适配。

数据库重构和迁移尚未验收，生产发布及旧库演练保持关闭。除页面动作参数外，还必须具备对应的机器环境门禁 `DOORHANDLE_COMPACT_RELEASE_READY` / `DOORHANDLE_COMPACT_REHEARSAL_READY`；两者默认不设置，不能只在 Jenkins 页面勾选参数就进入旧库发布或演练。

## 当前源码能力与待完成接线

| 环节 | 当前状态 |
| --- | --- |
| 固定分支、完整提交与 ECS 身份校验 | 本地 `doorhandle-local-ci` 独立节点已在线，控制器执行槽为 0，任务入口已切至统一文件；启用前须确认 CI 文件已推送，固定提交与 SSH/SCP 远端身份保护的真实验收尚待进行 |
| ECS 源码验证及报告 | 已有 Java、Python、双前端验证脚本、独立证据目录及报告归档；通过 SSH 在 ECS 隔离 checkout 验证，不新增常驻 agent，真实联调尚待进行 |
| 提交推送后自动触发 | 已保留 `H/5 * * * *` 轮询，并配置保留 15 次构建、5 次构件；替换期间先禁用任务，校验并确认 CI 文件已推送后再启用，最终状态以配置回执为准 |
| 制品发布、健康检查与失败恢复 | 在历史 SSH/SCP 脚本和统一入口上继续完善；生产发布、旧库演练额外受默认关闭的机器环境门禁保护，必须等待数据库重构、迁移及完整流程验收 |
| ECS 按需启动与节省停机 | 已明确排除在 Jenkins CI/CD 之外；测试前从流水线外启动、测试后从流水线外 StopCharging，流水线只做目标就绪和身份检查 |
| 三机部署 | 现行验证只准入原单体 ECS；须按部署设计补齐成员白名单、执行节点及发布流程 |

后续 CI/CD 工作优先补齐仍属流水线职责的缺口，再按真实结果更新状态。不解除 ECS 执行门禁，不重新启用旧 Windows 本地测试流程，不把 ECS 启停重新编入流水线。

### MySQL 验证的一次性远端预置

`source` 范围无需夹具预置。选择 `mysql` 前，先在目标 ECS 本次 `REMOTE_ROOT/verification/<ci-tag>/` 下仅准备 `.fixtures-ready.json` 和 `checkout/work/`；私有 manifest 与夹具资料放在该 `work` 内，并把 manifest 的绝对路径传给 `DOORHANDLE_CI_FIXTURE_MANIFEST`。预置目录不能带旧源码、旧回执或 `work/ci-evidence`。

marker 必须是无链接的常规文件、属于当前远端 Unix UID，权限恰为 `0400` 或 `0600`；字段只能有 `schema`（整数 `1`）、`kind`（`doorhandle-ci-fixtures`）、`release`（本次 ci-tag）、`commit`（本次完整 40 位提交）、`instanceId`、`machineId`，不接受额外或重复字段，所有值须与本轮目标完全一致。目录同样须归当前 UID 所有，不能由组或其他用户写入。

[远端验证助手](../script/jenkins/verify-remote.py) 校验后以原子 claim 领取该目录；已领取或已有结果的目录不会自动复用，中断后也须换新构建。流程不自动创建数据库，也不从本地上传数据库密码；隔离库、账号和私有清单先在 ECS 按既有夹具约定准备。

## 本机实际配置审查（2026-11-06）

以下为开始本轮完善前的只读审查记录，未运行项目测试；随后已完成页面登录、本地节点和统一入口配置。表中为原始问题，当前操作结果以上方配置记录及最终回执为准：

| 优先级 | 发现与影响 |
| --- | --- |
| P1（原始状态） | 实际 `doorhandle-java` 任务原先仍读取 `Jenkinsfile`，已切换至 `Jenkinsfile.ecs-monolith`。启用任务前必须确认新的 SCM 脚本及配套文件已推送。 |
| P1（原始状态） | 原有远端缓存包含旧 Windows 本地测试流程，不能仅凭本地退役保护判断 SCM 内容。配置时先暂停旧调度并禁用任务，确认已推送的新入口后再启用。 |
| 已调整设计 | 原入口要求 `doorhandle-monolith && doorhandle-ecs` 标签，但当时没有保存的外部节点配置。现已配置本地 `doorhandle-local-ci` 加 SSH/SCP，在远端隔离 checkout 执行测试，不新增 ECS agent；目标离线时预检明确失败。 |
| P1 | 新入口原先只有源码验证，部署、健康检查及失败恢复仍需完善。用户已明确 ECS 启停与限时停止任务不属于 Jenkins CI/CD，缺少这些阶段不再作为配置缺陷；测试后节省停机仍由流水线外操作完成。 |
| P1 | 新入口没有传数据库夹具，验证脚本允许列表也未覆盖新增 context/MCP 迁移配置；这些真实 MySQL 测试默认可被跳过，普通 CI 通过不代表当前数据库重构已验收。 |
| P2 | 每轮产生独立验证目录，但新流水线没有对应历史目录回收及构建保留策略，长期运行会积累磁盘占用。 |

根地址原先仍为 18080，已在本次启动时修正为 8080，并已通过浏览器登录。登录保护、CSRF、关闭注册和禁止匿名读取均已启用，生产发布参数默认关闭，这些设置可以保留。不将本次配置、页面启动或登录视为项目测试及生产发布验收通过。

## 使用现有环境启动

沿用既有文件和数据目录：

| 项目 | 路径或版本 |
| --- | --- |
| WAR | `D:\ruanjian\jenkins.war`，已核对为 2.541.1 |
| Jenkins Home | `C:\Users\19771\.jenkins`，保留已有任务、插件及凭据 |
| Jenkins Java | 项目 `work/jenkins/runtime/jdk-25.0.5+8-jre/bin/java.exe` |
| 项目 Java | Java 17，与 Jenkins 自身 JVM 分开 |
| 启动日志和 PID | 项目 `work/jenkins/`，Git 忽略 |

确认 Jenkins 尚未运行且 8080 空闲后，从项目目录执行：

```powershell
& '.\script\jenkins\start-existing.ps1' `
  -WarPath 'D:\ruanjian\jenkins.war' `
  -JavaExe 'D:\AI\lunwen1\DoorHandleCatch\work\jenkins\runtime\jdk-25.0.5+8-jre\bin\java.exe' `
  -JenkinsDataDir 'C:\Users\19771\.jenkins' `
  -Port 8080
```

脚本在隐藏后台窗口启动，绑定 `127.0.0.1`；端口占用时停止，不覆盖其他进程。它不安装 Jenkins、不重置账号，也不启动 ECS 或运行项目测试。

### 本地独立 agent 的启动与重启

本地控制器与 `doorhandle-local-ci` agent 是两个独立进程。首次准备时，先运行以下命令，保护 D 盘 agent 目录 ACL，`-PrepareOnly` 不启动进程：

```powershell
& '.\script\jenkins\start-local-agent.ps1' -PrepareOnly
```

然后由已登录管理员执行受信版本的 [本地配置脚本](../script/jenkins/configure-local.groovy)，创建永久节点和项目私有连接文件 `work/jenkins/local-agent/secret`，再正常启动 agent。连接文件按构建身份限制读取权限，属于 Git 忽略目录，不打印、不提交或归档。现有本地 agent 已确认在线，不需要重新安装环境。

控制器启动后，在项目目录运行现有 [agent 启动脚本](../script/jenkins/start-local-agent.ps1)：

```powershell
& '.\script\jenkins\start-local-agent.ps1'
```

该命令复用项目 `work/jenkins/runtime/jdk-25.0.5+8-jre/bin/java.exe`，检查私有连接文件并收紧其 ACL；首次从本机控制器下载 `agent.jar`，通过 WebSocket 连到 `127.0.0.1:8080`，日志与 PID 保存在 `work/jenkins/local-agent/`。已记录的匹配进程仍在运行时返回现有 PID；进程退出后再次执行即可启动。控制器升级后若需要重新获取匹配的 jar，可显式加 `-DownloadAgent`。

启动命令只创建本地 agent 进程，实际在线状态还需在 Jenkins 节点页确认。它不会启动 ECS 或项目测试；所有远端测试仍由流水线通过 SSH/SCP 在已启动 ECS 的隔离目录执行。

执行节点、隔离数据库及启停细则见 [ECS 运行约定](ECS-only-runtime.md)，旧发布证据见 [Jenkins 历史记录](../script/jenkins/README.md)。
