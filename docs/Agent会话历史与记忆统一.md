# Agent 会话历史与记忆统一

更新日期：2026-10-13。适用于 `java` 分支的模块化单体。

## 实现范围

同一账号在 Vue 主站和 React Agent 页面共用服务端会话、消息历史、RAG 检索以及 Mem0 长期记忆。打开同一会话可接续对话；新建会话只带入自己的聊天历史，仍可检索该账号的长期记忆。不同用户的私人会话、记忆、运行及确认继续隔离，主管的企业业务范围不包含员工私人聊天。

React 已增加会话选择、新建和刷新，支持 `?sessionId=已有会话编号`；切换会话时同步更新地址，刷新保留所选会话。页面刷新后从数据库恢复文字和受控业务卡片，不调用模型或重新执行业务工具。回到 React 页面会刷新当前会话；主站重新打开助手或回到窗口时刷新当前会话，正在回答时不覆盖流式内容。

## 服务端流程

1. 两个入口核对登录账号及会话所属权。
2. 读取 MySQL 中当前会话最近文本，最多保留 38 条历史，再加入本轮问题。已保存的卡片只将回答文字加入模型历史。
3. 普通问题使用相同的 RAG 和 Mem0 检索；`/` 命令沿用跳过检索与自动记忆提取的规则。
4. 经 contracts 门面调用 AgentScope 原生 Harness、角色工具集、模型及运行日志。
5. 保存本轮用户消息和成功回答，保留业务卡片引用，再返回完成事件。失败或取消不保存成功助手回答。

`AgentChatSessionApi` 是 app 模块提供的内部持久会话门面，AI 模块通过它适配 AG-UI；app 调用 `AgentConversationApi` 执行原生 AgentScope。双方只依赖 contracts，不相互引用实现、Mapper 或数据库实体。未增加新的 Agent 引擎或第三方依赖，沿用 AgentScope Java 2.0.4 和现有开源 UI。

`/agui/run` 的 `threadId` 现在必须是本人已有的数据库会话编号，可通过 `/api/chat-assistant/sessions` 创建。客户端仍可提交兼容格式的文本列表，后端只采用最后一条用户问题；客户端伪造的历史、系统消息、工具、状态和恢复指令不能替代服务端上下文。旧版仅存在浏览器中的随机 thread 不自动导入，也不会创建同名会话。

## 长期记忆范围

记忆写入保留 `user_id=doorhandlecatch:user:{稳定用户ID}`、`agent_id=doorhandlecatch` 和来源 `run_id=会话编号`，历史记忆不需要迁移。Java 的 `searchAccountMemories` 请求 Python 桥接层使用 `scope=ACCOUNT`：检索过滤始终包含账号和应用，去掉当前会话过滤，以便跨会话使用同一账号的长期记忆。

原 `scope=SESSION` 仍是 Python 搜索接口的默认值，兼容旧客户端。范围只接受 `SESSION` 或 `ACCOUNT`，拒绝空身份、未知范围及过大的检索数量。Mem0 健康接口的 `memory_scopes` 用于确认运行中的服务已经更新。

记忆和 RAG 内容仍作为不可信参考资料，不能扩大工具权限、替代人工确认，或把旧任务状态作为当前业务事实。后续个人记忆治理已增加本人查看、读取/保存设置、确认删除及审计，见 [个人长期记忆治理](个人长期记忆治理.md)。继续沿用成功对话后的异步提取，不增加企业共享记忆。删除聊天会话不会自动删除已经提炼的长期记忆。

## 隔离、重复请求与取消

两个入口共用 app 会话互斥和 AgentScope 运行锁，避免同一账号、同一会话同时生成。AG-UI 请求键保留 `AGUI` 来源：已保存请求在检索前返回 409；数据库唯一键继续处理并发竞争，不重新生成或追加重复用户消息。未开启持久日志时不提供跨重启的请求去重保证。

流式通道关闭或超时会取消实际运行，释放会话锁。AG-UI 的 `RUN_FINISHED` 在回答持久化后发送，失败发送脱敏 `RUN_ERROR`；受控卡片通过既有 `doorhandle.business-cards.v1` 事件发送。运行轨迹仍保存元数据，不保存历史、记忆正文或工具原始结果。私人会话及 AG-UI 接口使用 `Cache-Control: no-store`。

## 验证

- 完整 `mvn -B verify -Dagent.sessions.local.mysql=true` 通过：436 项中 418 项通过，18 项可选联调跳过，0 失败或错误。日志 `work/session-unification-full-verify.log`。
- `AgentSessionLocalMysqlTest` 使用真实会话 Mapper、MySQL、运行日志和 AgentScope Harness，验证主站到 AG-UI 的历史接续、伪造历史忽略、请求去重、新会话隔离以及其他员工/主管拒绝访问。结果 `work/session-unification-local-mysql.json`。
- 模型与 Mem0 响应在该测试中使用替身；Java HTTP 桥接测试和 Python 范围测试分别验证实际请求字段及检索过滤。Python 5 项通过，记录 `work/session-unification-python-tests.log`。
- Vue 49 项、React 5 项检查及两套生产构建通过，保留既有前端包体积提示。日志为 `work/session-unification-vue-*` 和 `work/session-unification-react-*`。

真实浏览器记录由 `scripts/diagnostics/session_unification_browser_acceptance.py` 写入 `work/session-unification-browser-acceptance.json`。它使用实际登录、MySQL 历史和 `/` 命令，避免调用收费模型；页面恢复、跨入口接续和手机布局以该记录为准。

最终九项浏览器/HTTP 检查通过，页面 JavaScript 异常为 0；桌面和手机截图已复核。项目已通过统一脚本重新启动，MySQL、Redis、Kafka、Chroma、Mem0 与后端六项健康检查通过，两套前端可用。启动记录 `work/session-unification-start.log`，Mem0 健康接口已实际确认支持 `ACCOUNT` 范围。

上述检查不证明真实模型语义质量或 Mem0 提炼效果已经验收。本人查看/删除和读取/保存设置已在后续治理阶段完成；记忆编辑、冲突与自动过期治理、SDK 断点恢复和长上下文压缩仍需后续开发。

## 启动与部署

没有新增数据库表、迁移脚本或环境依赖。更新 Java 后端和 React/Vue 前端后通过 Jenkins 发布；如果修改 `memory_service/main.py`，还需单独构建和更新 Mem0 镜像，当前应用流水线不会自动更新它。部署时同时代理 `/agui` 和 `/api` 到同一个后端，并保留原 HttpOnly 登录 Cookie 的同源策略。当前访问入口见 [服务器运行说明](服务器运行说明.md)。
