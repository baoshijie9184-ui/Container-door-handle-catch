# 在线诊断脚本

本目录保存需要人工触发的在线检查脚本。它们不属于默认的 `pytest` 测试集，因此运行
`./scripts/run-python.ps1 -m pytest tests_python -q` 时不会被收集，也不会意外访问本地服务。

这些脚本可能访问本机正在运行的前端或后端，并可能创建会话、发起查询或填写登录信息。
请确认依赖的服务已启动后再手动执行，不要将它们加入自动化单元测试。

## 脚本说明

### 智能体在线冒烟检查

`agent_live_smoke.py` 登录员工或主管测试账号，检查 AgentScope 只读模式、文本问答持久化和最新一轮 SDK 事件摘要。它会创建聊天会话并调用真实模型，默认只发起一次查询，不执行业务写操作。它不是防幻觉评测或人工确认验收。执行前需要启动后端、数据库及模型服务。

```powershell
$env:AGENT_SMOKE_USERNAME="你的测试账号"
# 密码默认交互输入，也可通过 AGENT_SMOKE_PASSWORD 临时注入
./scripts/run-python.ps1 scripts/diagnostics/agent_live_smoke.py --question "查询最近的检测任务"
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
### 账号员工关联验收

`organization_local_acceptance.py` 在 V20 迁移和后端启动后执行实际 MySQL/HTTP 验收，创建并保留 `org-fixture-*` 数据；只操作这些测试账号的关联。结果写入 `work/organization-local-acceptance.json`。不调用模型，原有账号密码、角色、关联与业务任务不修改。浏览器脚本 `organization_browser_acceptance.py` 使用该结果验证管理与员工页面。
### 报告审批验收

`report_local_acceptance.py` 需要 V21 和已启动后端，只插入并操作 `report-fixture-*` 任务与测试报告，保留审计；不调用模型。报告在 `work/report-local-acceptance.json`。随后运行 `report_browser_acceptance.py` 验证主管预览确认、员工创建/提交、跨账号隔离和 Markdown 下载，产物写入 `work/report-browser-*`。这些脚本不属于默认 pytest，详情见 [报告流程](../../docs/报告草稿与独立审批.md)。
### Agent 报告来源页面验收

先显式运行 `AgentReportLocalMysqlTest` 生成 `work/agent-report-local-mysql.json`，再执行 `agent_report_browser_acceptance.py`。后者只读真实能力目录、报告及来源轨迹，验证账号隔离和两套前端链接，不调用模型、不执行业务写入。测试使用现有本地演示账号和标记 fixture，结果 `work/agent-report-browser-acceptance.json`。SDK/MySQL 命令和范围见 [Agent 报告工具](../../docs/Agent报告工具接入.md)。

`agent_cards_browser_acceptance.py`：先显式执行 `AgentCardsLocalMysqlTest`，再启动单体。脚本读取实际保留会话与卡片，检查主站历史恢复、只读刷新、重新分派隐藏、报告链接、标题文本渲染、手机布局和跨账号拒绝；React 仅替换模型流，卡片 API 仍连接真实 MySQL，不调用付费模型。证据在 `work/agent-cards-browser-acceptance.json`。

`skill_evolution_browser_acceptance.py`：先显式运行 `SkillEvolutionLocalMysqlTest` 保留来源、实际 SDK 提议/读取轨迹与第三版待审样本，再启动单体。脚本实际操作独立主管的审核确认、发布、回退和停用，检查来源隔离、审计和无模型重放；仅变更 `fixture-progress-*` 样本，完成后停用，保留全部版本。结果 `work/skill-evolution-browser-acceptance.json`。

`skill_evolution_layout_acceptance.py`：在上面流程之后只读检查桌面和手机弹窗，验证正文内部滚动、无裁切和隐藏当前发布状态，写入 `work/skill-evolution-layout-acceptance.json` 与截图，不重复发布。
