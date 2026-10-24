# MCP 进程证明与安装重启核对

后续源码更新：V58 已加入独立的原生安装监督器、双阶段退出核对及安装握手账本，未执行测试或部署，见 [原生安装进程树回执](固定Fetch原生安装进程树回执.md)。下文关于 V49 尚不覆盖 pip 安装树的描述仅适用于未开启 V58 新开关的路径；旧安装不会被自动补造证据。

2026-10-22，UTC+8，`java-cloud`。当前是代码开发记录，未编译、测试、执行迁移或部署。所有新增开关默认关闭，不能据此宣称当前服务器已启用。

## Linux 固定 Fetch Stdio

核对官方 AgentScope Java 2.0.4 与 MCP Java SDK 0.17.2 接口后，保留 `McpClientBuilder.stdioTransport`、工具发现和原 JSON-RPC 调用。SDK 的 `close()` 不向业务返回独立进程身份，因此新增固定启动器 `script/shell/native-fetch-process.py` 与 `NativeFetchProcessClient`，不通过反射读取 SDK 私有字段，也不开放任意脚本执行。

开启 `AGENT_MCP_NATIVE_PROCESS_ENABLED` 后，需要同时启用持久执行回执，且运行在提供 pidfd 的 Linux。Windows 和缺少能力的系统继续保留原路径及未核实提示，不能打开此开关伪造证明。

执行步骤：

1. Java 在 MySQL 预先登记本人执行，再由本地控制器在本人 runtime journal 预留同一编号。
2. SDK 启动固定 Python 入口，建立专属进程会话。启动器持久记录 boot/PID namespace、PID 和启动 ticks 后才进入已审核 `mcp_server_fetch` 模块。
3. 模块使用原 SDK stdin/stdout，启动器参数不传入模块。stderr 和 traceback 不交给业务日志；工具 URL、正文、凭证不写入 journal。
4. 关闭时先撤销编号，核对同一进程代次，用 pidfd 冻结原会话根进程并终止其进程组，再查询实际成员。只确认停止仍有僵尸等待回收时，保持 EXITED；成员清空才确认清理。
5. 无法证明退出时不阻塞等待 SDK 无限关闭，不释放执行占用。后续本人通过已有执行核对接口查询原编号，不重新抓取网页。

脚本只允许 pool、预留、固定运行、停止，以及 SDK 尚未创建时的预启动封存。启动已登记过的执行、撤销编号或替换 pool 都不能重复调用模块。SDK 连接创建前的预留失败可留下撤销墓碑；已经进入连接阶段的未知结果不能用此路径清空。

journal 位于本人 `mcp/fetch/runtime/processes.sqlite3`，在既有 Agent 工作区持久卷内，独立于可清理安装目录。状态与审计使用事务保存，无 URL 或模型正文。JVM 重启且仍在同一 boot/PID namespace 时可继续核对；系统重启、容器命名空间变化或 journal 丢失时不猜测原资源已经消失，保留待核对。

该能力覆盖固定 Fetch 执行进程，不等同于通用 Stdio 工具、Skill 脚本沙箱，也没有宣称解决原生 pip 安装树的全部退出证明。原生安装握手前后的异常边界和不同内核/容器权限仍需后续验收。

## 网关安装写入者证明

新增 `McpInstallWorkerEvidence`。持久安装队列领取成功的同一事务中记录实际 JVM PID、启动时间、节点命名空间摘要及配置摘要；仅 Future 取消、租约到期或 isDone 不形成写入结束证明。实际安装 callable 结束写入后保存 RETURNED；未能保存时继续保留预留。

可用时，在领取前通过既有受信 runner 捕获后端容器的完整 ID、StartedAt 和 runner pool。该只读请求在数据库事务外执行；runner 仅查询固定 Compose 项目的 backend，独立 install-control 范围与 execute 凭证隔离。响应绑定账号、安装、请求 nonce 和目标代次，不返回环境、日志、网络或 Docker 原始详情。

服务重启后的本人核对使用：

`POST /api/agent/mcp/fetch/versions/{installationId}/reconcile-writer`

请求包含 `expectedRevision`、`requestId`、`confirmed: true`，沿用 MCP 管理请求头。先锁本人登记和历史、保存去重与审计，再执行只读核对：

- 已有 RETURNED 写入结束记录，可以确认。
- 同一节点/PID namespace 内，原 JVM 已消失或 PID 的启动代次变化，可以确认原 JVM 内的网关登记写入已经结束。
- 节点命名空间变化时，仅在原容器已停止、消失或 StartedAt 改变且 runner pool 一致的情况下确认原代次结束。
- 没有历史证据、节点不一致且不能取得容器证明、daemon 不可用或原服务仍在运行，继续待核对。

确认后将候选转为 CACHED，按实际文件字节计入额度；清理仍需独立确认，仍校验当前登记、回退保留和工具执行引用。不能由一次核对自动重做安装、启用工具或删除目录。并发核对有租约和版本限制，重复请求只读结果。

## 迁移与开关

V49 给执行记录增加 transport，给历史安装增加核对请求/期限/证据码，并增加 `agent_mcp_install_worker`。保留新增字段、审计和 runtime journal；回滚应用不清空未知占用。

- 执行回执的最新代码需要 V47–V49；按序执行增量迁移，保留 V48 的空历史表亦可，不因此启用生命周期。
- `AGENT_MCP_NATIVE_PROCESS_ENABLED=false`：仅 Linux 固定 Fetch 执行，可选启用。
- `AGENT_MCP_INSTALL_RECONCILIATION_ENABLED=false`：依赖网关生命周期及持久队列，覆盖 JVM 内的登记写入者。
- Linux 自动读取 boot/PID namespace。非 Linux 的网关写入核对需配置仅属于该宿主节点的稳定 `AGENT_MCP_INSTALL_PROCESS_NODE_ID`，不自动猜测节点身份。
- 本地迁移辅助脚本增加 V49 的字段签名核对和只补缺失字段，保留显式 `--apply`；本轮未执行。

Vue 管理页展示 transport 和写入者核对结论，隐藏 PID、容器 ID、节点指纹与系统路径；React 仍复用同一管理入口。时间为 UTC+8，未执行浏览器验收。

## 仍需继续

共享镜像的全账号引用核对与物理回收、原生安装树退出证明、Windows Stdio 的受控进程机制，以及模型、写工具、上下文、身份审计的其他缺口继续保留。统一验证和发布未进行，不将本次代码记录标记为五类全部完成。

接口参考：[AgentScope McpClientBuilder](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-core/src/main/java/io/agentscope/core/tool/mcp/McpClientBuilder.java)、[McpClientWrapper](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-core/src/main/java/io/agentscope/core/tool/mcp/McpClientWrapper.java)、[MCP Java Stdio transport](https://github.com/modelcontextprotocol/java-sdk/blob/v0.17.2/mcp-core/src/main/java/io/modelcontextprotocol/client/transport/StdioClientTransport.java)。本次使用公开接口，没有复制其私有进程实现；既有依赖许可声明保留。
