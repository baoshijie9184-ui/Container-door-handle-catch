# 固定 Fetch 执行回执与重启核对

实施日期：2026-10-22，UTC+8。分支：`java-cloud`。

状态：执行登记、网关回执、本人核对接口和管理页面已加入代码，尚未编译、测试、迁移或部署。按本轮要求先开发，不将此前其他版本的成绩作为本轮通过证据。固定版本升级、失败回退、存储统计和缓存清理仍需继续开发，五类整体任务未完成。

## 启动前登记

新增 AI 自有 V47 `agent_mcp_execution`、`agent_mcp_execution_command`，根目录与 classpath 保存同份 SQL。只保存账号、安装/执行编号、运行配置摘要、运行器存储身份、状态、版本和关联运行编号，不保存 URL、网页正文、Bearer、系统路径或模型凭证。

启用时先获取固定运行器的 poolId，再在 MySQL 同事务保存执行占用和审计，失败不继续连接。execute 凭证绑定执行编号及 poolId。每账号至多两项未清理执行；runner 的持久 journal 继续约束全局两项容量，未知结果不释放。

runner SQLite journal 放在命名卷 `doorhandle-mcp-executions`，保存容器身份、账号/安装/nonce、启动器代次和审计。工具容器仍不挂载 Docker socket，只有固定控制运行器能操作宿主 daemon。

## 状态及证明

| 状态 | 含义 |
| --- | --- |
| OPENING / RUNNING | 已登记，正在连接或执行 |
| STOPPING | 已收到一次本人终止与核对请求 |
| NEEDS_REVIEW | 退出、启动器收尾、daemon 结果或审计无法确认 |
| EXITED | 已确认停止，尚未确认清理，继续占用 |
| REMOVED | 已确认启动器收尾和容器不存在，可释放占用 |

`docker rm` 返回成功、HTTP 200、客户端连接关闭或超时，均不能单独作为退出证明。删除前核对完整容器 ID、不可变镜像和账号/安装/执行/pool 标签，删除后再次查询固定 daemon。启动器仍可能迟到启动时，即使暂时没有容器，也保持待核对。

SDK 进程正常收尾后记录启动器已结束；取消时沿用同一外层 AnyIO 作用域保护收尾，避免在 SDK task group 退出时插入另一个作用域。异常收尾不伪造成功。

## 重启和本人核对

重启不重做网页抓取。旧 worker 的启动尚未收尾时，必须核实旧控制容器已停止、消失或启动代次改变；无法证明时继续保留。后台只清理本池登记资源。

后端从 MySQL 恢复显示。超过期限的 OPENING/RUNNING/STOPPING 在读取 DTO 中显示待核对，不自动重放。核对接口为：

`POST /api/agent/mcp/fetch/executions/{executionId}/reconcile`

请求带 `expectedRevision`、`requestId`、`confirmed: true` 和既有 `X-MCP-Action: update`。重新鉴权、锁本人记录；陈旧版本拒绝，同编号不同内容拒绝，重复编号只读结果，不再次执行远端请求。新核对只能撤销和检查原执行，不启动抓取。

核对签发新的短期 control 凭证，不复用过期 execute 凭证。运行配置变化或 poolId 不匹配时保持待核对，不能把新库没有旧记录当作已退出。回执及审计先提交，再清理本机引用；审计失败保留原占用。

停用先提交配置及审计，再逐一关闭本机连接，一个失败不阻止其他连接关闭。存在未清理执行时拒绝更换安装、重新启用和移除安装登记。网页返回与执行清理分别审计。

## 页面和部署

Vue MCP 页面增加执行卡片、退出/清理标记、本人核对按钮，时间统一 UTC+8，并支持减少动态效果。React 继续通过既有 MCP 资源链接复用同一管理页。

`AGENT_MCP_EXECUTION_RECEIPTS_ENABLED=false` 默认关闭。最新 V49 代码补充 transport 与进程证据，当前启用需 V47–V49、匹配后端及相应 journal。GATEWAY 使用 runner 持久卷；Linux 固定 Stdio 可另开启 `AGENT_MCP_NATIVE_PROCESS_ENABLED`，其他原生路径仍显示未启用退出证明。当前未迁移、测试或部署；详见 [进程与安装重启核对](MCP进程证明与安装重启核对.md)。

备份须包含 MySQL 与 runner journal；执行中不能用历史 journal 抹除活动资源。丢卷后新 poolId 与 MySQL 记录不匹配，保持待核对。恢复历史备份前先停用 MCP，由运维核对 daemon 中的相关资源。

回滚保留新增表、审计和卷；旧版应用不会读取 V47，回滚期间保持 MCP 停用，恢复匹配版本后核对旧占用。不能通过删卷或删未核对记录释放容量。

## 仍需补齐

- 固定包和运行镜像登记版本、升级失败回退与引用关系。
- 存储统计、未引用包清理和清理回执。
- Linux 固定 Stdio 进程证明已有新增代码，实际兼容与异常验收仍待完成；原生安装树的完整退出证明继续待补。
- Secret、迁移和 Jenkins 最终发布接入及专项/统一验收；本轮按要求不运行测试。

继续使用官方 MCP Python SDK 和 Docker 身份接口，不引入新的 Agent 框架；既有许可证和版权声明保留。
