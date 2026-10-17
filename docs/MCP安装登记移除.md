# 固定 Fetch MCP 安装登记移除

更新：2026-10-16，`java-cloud`。本次继续完善 P09，增加固定 Fetch 的账号安装登记移除；适用于现有本地 Stdio 和内网网关模式。

## 使用方式

在“Agent 智能系统 → MCP 工具”先停用本人 MCP，再点击“移除安装登记”。确认框说明只影响本账号，已有文件、许可证和审计保留，不释放磁盘空间。选择“保留登记”不发请求。

移除后显示“已移除登记”，不再显示启用、探测或移除按钮，原安装不再用于 Agent 调用。页面仍显示审计和重新安装入口；再次安装需要重新确认来源、固定版本和许可证，生成新的安装编号并默认保持未启用。

已启用的安装必须先停用，页面解释按钮不可用的原因。即使旧运行环境需要迁移，已启用的记录也允许先停用，再移除登记。尚在安装的任务使用 [取消安装](MCP安装取消与队列回收.md)，不能通过本功能跳过取消。

## 接口与状态

`POST /api/agent/mcp/fetch/registration/remove`，要求登录、`X-MCP-Action: update` 和显式确认，响应不缓存。

```json
{
  "operationId": "00000000-0000-0000-0000-000000000001",
  "expectedRevision": 2,
  "confirmed": true
}
```

服务端重新查询有效账号，锁定本人 Fetch 注册行，检查安装编号、版本、`INSTALLED` 状态及已停用条件。主管不能移除其他账号的登记。安装编号变更、版本冲突、仍启用或未安装完成均拒绝，不猜测用户意图。

事务中将状态改为 `UNINSTALLED`，禁用并清空活动清单、清单摘要、租约和错误，递增版本，同时写 `REMOVE_REGISTRATION / SUCCEEDED` 审计。保留注册行、原安装编号、原请求编号及历史审计。审计仅记录 `registrationRemoved/filesRetained` 等元数据，不记录文件正文。审计失败时整个事务回滚。

相同安装编号已处于 `UNINSTALLED` 时重复请求返回当前状态，不再次递增版本或审计。重新安装生成新编号，旧移除请求不能影响新登记。启用与移除共用注册行锁及版本检查，两者并发时最多一个成功；已移除状态不能被普通启用接口恢复。

提交后再尝试关闭本进程登记的活动连接，复用现有客户端回收机制。每次 Fetch 调用仍重新检查本人安装和启用状态；即使此前工具已注册在运行内，也不能继续通过已移除的登记发起新调用。

## 页面容错与兼容

打开确认时捕获安装编号与版本，停止旧的只读刷新，防止确认对象漂移。响应失败时提示核对实际状态，不自动重发写请求；响应丢失但服务端实际完成时，可通过只读刷新确认结果。离开页面会关闭未提交的移除确认，后续不发送请求。

状态接口新增 `registrationRemovalSupported: true`。新版页面仅在服务端明确支持、安装编号存在且状态合适时提供按钮，旧服务端不会暴露不可用入口。

沿用 V25 字符串状态列及既有审计表，无新增迁移、配置开关或依赖。部署需配套发布前后端；回退旧版时旧页面可能不识别新状态，应恢复支持 `UNINSTALLED` 的版本后重新安装，保留文件和历史记录。

## 文件和执行边界

当前是固定 Fetch 的登记移除，不执行 `pip uninstall`，不删除 `users/{id}/mcp/fetch/installs/{uuid}`，不删除共享网关镜像、许可证、日志、调研来源或运行历史。因此没有磁盘空间回收，也不保证其他进程、远端网关中的旧执行在响应返回前已经退出。停用及现有调用取消/超时回收机制继续适用。

通用 MCP 升级/卸载、物理包清理、持久队列恢复、跨实例物理取消，以及真实 MySQL/云端验收仍在 P09；没有将移除操作开放为 Agent 工具。模型继续只能提出固定安装的待确认提议。

## 开源参考

开发前检索并核对官方 [Fetch 源码与 MIT 说明](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) 及 [AgentScope Java MCP 工具文档](https://github.com/agentscope-ai/agentscope-java/blob/main/docs/v2/zh/docs/building-blocks/tool.md)。官方项目保持维护，当前项目仍固定 Fetch `2026.10.10` 与 AgentScope Java `2.0.4`，直接复用现有 SDK 客户端生命周期；没有升级 SDK 或复制其他项目代码。账号登记、确认和事务审计属于本系统业务层，不能用 SDK 工具注销代替持久授权撤销。

## 验证记录

定向 Java 33 项通过，包括原取消安装回归及新增的登记移除、文件保留、启用前置条件、权限/确认/版本、账号失效、审计回滚、重新安装隔离、安装中拒绝、过期/摘要异常清单移除和双服务启用竞争。使用隔离 H2 和受控运行时，没有下载安装包或访问用户真实目录。日志 `work/mcp-registration-remove-target.log`。

主站/独立聊天 Node 分别 91/5 项通过，主站生产构建成功。新增隔离 API 浏览器 35 项及原安装取消回归 24 项通过，JavaScript 错误为 0；覆盖响应丢失后只读核对、旧接口兼容、手机布局和离开页面不提交。结果与截图保留在 `work/mcp-registration-remove/`，对应脚本 `script/diagnostics/mcp-registration-remove-acceptance.py`。

完整 Maven `clean verify` 620 项：597 通过、23 个可选集成检查跳过、0 失败/错误，13 个模块构建成功，日志 `work/mcp-registration-remove-full-verify.log`。主站 Node/生产构建、独立聊天 Node、浏览器及取消回归日志分别为 `work/mcp-registration-remove-vue-node.log`、`work/mcp-registration-remove-vue-build.log`、`work/mcp-registration-remove-react-node.log`、`work/mcp-registration-remove-browser.log` 和 `work/mcp-registration-remove-cancel-regression.log`。

桌面/手机确认弹窗截图已复核；临时预览进程已停止，现有 ECS 访问隧道保留。`git diff --check` 通过。本轮未提交、推送或发布 ECS，未移除任何真实账号的 MCP 登记或文件；真实 MySQL、云端网关和跨实例执行回收仍待验收。
