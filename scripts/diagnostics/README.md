# 在线诊断脚本

本目录保存需要人工触发的在线检查脚本。它们不属于默认的 `pytest` 测试集，因此运行
`./scripts/run-python.ps1 -m pytest tests_python -q` 时不会被收集，也不会意外访问本地服务。

这些脚本可能访问本机正在运行的前端或后端，并可能创建会话、发起查询或填写登录信息。
请确认依赖的服务已启动后再手动执行，不要将它们加入自动化单元测试。

## 脚本说明

### 智能体在线冒烟检查

`agent_live_smoke.py` 会登录后端，依次检查意图路由、检测与资源查询、追问、操作确认、
多轮会话和防幻觉等能力。执行前需要在 `http://localhost:8080` 启动后端，并准备可用的
本地测试账号及其依赖服务。

```powershell
./scripts/run-python.ps1 scripts/diagnostics/agent_live_smoke.py
```

### 登录页面结构诊断

`login_browser_debug.py` 会使用 Playwright 打开登录页，打印输入框结构并截图。执行前需要
在 `http://localhost:3001` 启动前端，并安装 Playwright 与 Chrome 浏览器。

```powershell
./scripts/run-python.ps1 scripts/diagnostics/login_browser_debug.py
```

### 登录页面 Element Plus 结构诊断

`login_browser_debug_alt.py` 使用 Element Plus 选择器检查可见输入框，适合排查登录组件结构
变化。执行前同样需要启动本地前端，并准备 Playwright 与 Chrome 浏览器。

```powershell
./scripts/run-python.ps1 scripts/diagnostics/login_browser_debug_alt.py
```

### 设备使用状态筛选诊断

`usage_status_browser_debug.py` 会通过浏览器登录系统，进入设备使用记录页面，依次检查“使用中”
和“已归还”筛选并截图。执行前需要启动前端与后端、准备测试数据，并安装 Playwright 与
Chrome 浏览器。

```powershell
./scripts/run-python.ps1 scripts/diagnostics/usage_status_browser_debug.py
```
