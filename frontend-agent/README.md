# 企业级集装箱门把手盖多智能体协同缺陷检测平台 · 多智能体工作台

独立的 React + Spark Design 对话入口，连接后端 AgentScope Java AG-UI。

```bash
npm install
npm run dev
```

先在同一主机名的业务前端登录，再打开此页面，登录态通过 HttpOnly Cookie 携带。

默认请求 `/agui/run`，开发服务器将 `/agui` 代理到单体后端 `http://127.0.0.1:8080`，可用 `DOORHANDLE_API_TARGET` 覆盖代理目标。可通过 `VITE_AGENT_API_URL` 覆盖完整运行接口地址，通过 `VITE_BUSINESS_LOGIN_URL` 覆盖登录链接。部署时需为 `/agui` 和 `/api` 配置同源反向代理。页面从 `/agui/models` 获取已登录用户可见的脱敏模型配置，每 30 秒更新默认模型、备用顺序及冷却状态。“默认模型”表示配置优先级，不能据此判断某次回复实际来自哪个模型。

页面从 `/agui/catalog` 获取当前登录角色的实际能力，支持业务查询和开启持久运行日志后的本人报告草稿保存。报告提交与审批通过侧栏的“报告与审批”进入业务页面。服务端会检查角色，修改前端 Agent ID 无法获得主管权限。

开启质检分配确认时，主管目录为 `CONFIRMABLE`，可以保存待确认提议；通过页面的“查看并确认操作”链接进入主站共用确认页，批准后才执行分配。报告草稿启用时员工目录为 `DRAFTS`，准确能力还需读取 `reportsEnabled`、`reportDraftsEnabled`。详情见 `../docs/agentscope-action-confirmation.md` 和 `../docs/Agent报告工具接入.md`。

流式协议测试：`node --test src/aguiClient.test.js`。完整实施状态见 `../docs/agent-role-toolkit-progress.md`。

业务卡片使用项目自定义事件 `doorhandle.business-cards.v1`，展示实际工具生成的任务、质检、工作统计和报告引用。卡片通过 `/api/agent/cards/resolve` 只读刷新当前登录账号的数据，不调用模型或写工具；Vite 已代理 `/api` 并允许读取与主站共用的卡片校验模块。两个入口共用数据库会话，页面刷新恢复保存的文字和卡片引用。实现与验收见 [Agent 业务卡片接入](../docs/Agent业务卡片接入.md)。

会话选择、新建和刷新通过 `/api/chat-assistant/sessions`。`/agui/run` 只发送本轮问题，threadId 必须是本人数据库会话编号；可用 `?sessionId=编号` 打开指定会话。后端共用 RAG 和账号范围 Mem0 检索，保留私人数据隔离。详见 [会话历史与记忆统一](../docs/Agent会话历史与记忆统一.md)。
