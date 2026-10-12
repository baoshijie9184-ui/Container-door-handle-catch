# DoorHandle Agent UI

独立的 React + Spark Design 对话入口，连接后端 AgentScope Java AG-UI。

```bash
npm install
npm run dev
```

先在同一主机名的业务前端登录，再打开此页面，登录态通过 HttpOnly Cookie 携带。

默认请求 `/agui/run`，开发服务器将 `/agui` 代理到 `http://localhost:48080`。可通过 `VITE_AGENT_API_URL` 覆盖完整运行接口地址，通过 `VITE_BUSINESS_LOGIN_URL` 覆盖登录链接。部署时需为 `/agui` 配置同源反向代理。

页面从 `/agui/catalog` 获取当前登录角色的实际能力，支持员工和主管的只读查询。服务端会检查角色，修改前端 Agent ID 无法获得主管权限。

流式协议测试：`node --test src/aguiClient.test.js`。完整实施状态见 `../docs/agent-role-toolkit-progress.md`。
