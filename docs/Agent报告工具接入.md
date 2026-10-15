# AgentScope 报告工具接入

更新：2026-10-13，分支 `java`，仍在现有模块化单体中开发。

## 本次能力

员工与主管主 Agent 各增加第五个专业 Agent `report-assistant`，由主 Agent 内部委派。工具使用现有 AgentScope Java 2.0.4 `AgentTool`、Toolkit、权限规则和 Middleware；不新增另一套 Agent 编排。

| 工具 | 行为 |
| --- | --- |
| `list_quality_reports` | 查询授权报告摘要，支持分页、状态和关键词；列表不返回意见正文 |
| `get_quality_report` | 读取授权报告版本、状态、意见、检测依据和页面链接 |
| `create_report_draft` | 按用户明确请求保存本人私人草稿，返回 `DRAFT` 与页面链接 |
| `edit_report_draft` | 按用户明确请求、当前版本，修改本人仍为 `DRAFT` 的标题和意见 |

可以提问：“查询我的待审批报告”“查询报告 qr-… 的状态”“为任务 … 保存标题为 …、意见为 … 的个人草稿”。修改前先读取报告，取得版本并保留用户没有要求修改的内容。生成内容需在报告页面核对；草稿保存不表示已提交或审批。未提供明确任务、标题或必要资料时应询问，不能编造检测事实。

角色范围复用报告业务 Service：员工只见本人且仍在授权任务范围内的报告；主管可看本人草稿和已提交报告，不能看其他人的私人草稿。草稿写入仅本人，角色与账号每次从系统门面重新核对；岗位和账号绑定不扩大权限。

**没有注册报告提交、撤回、修订、导出、审批、签署或发布工具。** 它们仍在“报告与审批”页面执行。系统提示和工具描述要求仅按当前用户明确请求保存草稿，禁止把报告、RAG、记忆或其他工具返回的文字当作写入授权。此处提示约束不等于已通过真实模型提示注入评测；敏感状态变化由工具注册边界阻止。

## 边界与事务

`Harness → report-assistant ReAct → ReportTools → AgentReportGateway → QualityReportAgentApi → QualityReportService`。

AI 模块只依赖 contracts 门面，不能调用检测模块的 Mapper、Controller 或实现类。检测模块通过服务封装已有报告事务、任务范围、版本、私人草稿状态和审计。

工具参数白名单不接受用户 ID、角色、runId、callId、requestId、审批凭证或状态。账号来自服务端闭包；runId 来自日志 Middleware，callId 来自 SDK 实际调用。保存草稿前锁原运行行，检查运行所属账号、主 Agent 角色、`RUNNING` 状态及未到期租约。取消、结束或租约失效的运行不允许继续写草稿。网关事务超时设为 15 秒；草稿写工具不采用读查询的响应超时包装，以减少工具返回超时但独立写线程继续执行的歧义。

幂等编号由规范化 `runId + tool + 完整业务参数` 生成。同一轮不同 callId 重复相同参数复用原结果，不再创建草稿或追加审计；修改内容或版本形成新的请求。跨新一轮会话请求不自动合并，可能按用户新要求创建另一份草稿。这个机制不是自然语言请求的全局去重，前端失败不自动重发问题。

新增 [V22 来源表](../sql/mysql/migration-V22-agent-report-origin.sql) `detection_report_agent_origin`，保存账号、服务端请求编号、报告及版本、runId、callId 和工具名。草稿、必要业务审计、请求结果和来源关联在同一数据库事务提交，来源关联失败则全部回滚。重复请求保留首次实际调用关联。工具执行前后的授权和结果事件仍使用 SDK Middleware 记录，不复制草稿正文、工具参数、检索资料或原始异常到运行日志。

报告操作记录显示“业务页面”或“助手运行轨迹”。链接可定位指定运行，不依赖它是否处于历史第一页；查看运行仍按当前账号所有权校验。主管可审批员工报告，但不因此获得员工私人对话及运行访问权限；跨账号轨迹链接会被拒绝。

两套前端显示报告能力和草稿限制，独立 Agent UI 提供进入报告页面的链接。通过 `/quality/reports?reportId=…` 可直接打开授权报告详情；提交与审批继续走人工确认。主站 health 和 AG-UI catalog 新增 `reportsEnabled`、`reportDraftsEnabled`；开启报告写能力时员工 catalog 为 `DRAFTS`，主管启用质检分配确认时仍为 `CONFIRMABLE`。不能仅凭旧 mode 字段宣称所有工具只读。

## 配置与迁移

报告查询要求装配 `QualityReportAgentApi`；草稿写入还要求持久运行日志已开启。没有报告门面时保留原四个专业 Agent；没有持久运行日志时报告专业 Agent 只注册查询工具。缺少可信运行或实际 SDK 调用编号时，写工具返回拒绝。当前项目运行日志已开启，未添加新 API Key 或模型配置。

既有 V21 后执行 V22，classpath 副本在 App 模块。当前本机已执行，只新增来源表，不修改历史报告、账号或任务。`migrate-local-reports.py --apply` 已扩展为依次幂等执行 V21、V22；省略参数只检查，两份 SQL 副本必须一致。

```powershell
& 'D:/ruanjian/anaconda3/envs/leetcode/python.exe' script/shell/migrate-local-reports.py --apply
```

启动健康检查增加来源表检查，不自动执行迁移。应用回退应保留来源与历史审计，不自动删除新增数据。

## 开源核对

开发前查阅 [AgentScope Java 2.0.4 发布记录](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.4)、[该版本的 AgentTool 说明](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/tool.md) 和 [Apache-2.0 许可证](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。官方文档 MCP 的 `v2/llms.txt` 本次返回 404，使用锁定版本 GitHub 文档和已安装 SDK 编译验证替代。沿用已有依赖和版权文件，没有复制第三方代码或安装新框架。

## 验证与限制

新增工具规则、网关事务及报告门面测试，覆盖身份字段伪造、缺失/过长参数、非法状态、非整数版本、秘密异常脱敏、关闭日志后的工具注册、真实 Harness→ReAct 委派、运行账号/角色/状态/租约拒绝、幂等编号稳定、来源失败回滚、跨账号草稿及已提交报告编辑拒绝。运行日志开始事件的数据范围标签也修正为 `OWNED_OR_ASSIGNED`，与实际规则一致。

固定离线 Eval 默认升级为 `dataset-v2.json` / `synthetic-business-h2-v2`，保留原 v1 文件作为历史参考，新增八项报告用例，共 30 项必测。包含本人/主管报告查询、审批工具不存在、参数伪造和版本校验、实际 SDK 草稿委派。Eval 的模型与报告业务门面仍为脚本/合成 fixture，不代替实际业务 MySQL；v1 基线不得直接与 v2 比较。

显式本机测试 `AgentReportLocalMysqlTest` 使用真实 Spring 事务、系统身份、报告 Service、运行日志、来源表和业务 MySQL，走实际 Harness/ReAct/Tool，只有模型响应脚本化；创建 `agent-report-fixture-*` 任务和报告，保留样本及轨迹供复核，不调用付费模型。运行方式：

```powershell
$env:JAVA_HOME='C:/Program Files/Java/jdk-17'
& 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd' -B -pl doorhandle-server -am test '-Dtest=AgentReportLocalMysqlTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dagent.report.local.mysql=true' '-Dagent.report.project=D:/AI/lunwen1/DoorHandleCatch'
```

本轮不声称真实模型一定正确路由、草稿质量已达标或所有提示注入已防御；真实模型语义、错误恢复、负载、跨新运行去重和生产质量评测仍待单独验收。会签、公开发布、独立任务复核申请、正式 Word/PDF 报告、outbox 投递与通知仍为后续业务工作。

最终验证：全量 Maven `verify` 成功，368 项中执行并通过 356 项，12 项可选模型/数据库联调默认跳过；其中 30 项 Eval v2 及新增 12 项报告工具、网关和实际报告门面测试均通过。独立脚本再执行 30/30 Eval 成功，报告 `work/agent-eval/20261013-123912-331-7ac68e/report.json`，这不是已审定质量基线或生产发布批准。

以旧 v1 报告作比较时，即使 30 个 v2 用例全部通过，脚本仍按不兼容基线返回退出码 1，`experimentGatePassed=false`；证据 `work/agent-report-eval-old-baseline.log` 及 `work/agent-eval/20261013-124100-612-167995/report.json`。数据集升级不能通过不同版本的通过率相互替代。

显式实际 MySQL 测试另行执行通过，验证 SDK 创建本人草稿、不同 callId 的相同参数复用同一草稿、单条首次来源与审计、真实编辑版本增长、其他员工及主管读私人草稿拒绝、其他账号借用运行拒绝、运行结束后写入拒绝、授权和工具完成事件已持久化、没有审批 outbox 事件；真实模型调用数为零。实际 SDK 在该样本执行四次脚本模型调用，证据 `work/agent-report-local-mysql.json`、`work/agent-report-live-mysql.log`。

两套前端生产构建通过，主站 45 项现有检查全部通过。浏览器与真实 HTTP 共 12 项检查通过：两类角色 catalog 和 health 显示第五类报告能力；本人报告深链接与来源审计、精确运行跳转、React 报告入口均可用；其他账号报告和原运行拒绝，没有 JavaScript 异常。报告 `work/agent-report-browser-acceptance.json`，截图 `work/agent-report-browser-origin.png`、`work/agent-report-browser-trace.png`、`work/agent-report-browser-react.png`。这些浏览器检查没有调用模型或重放工具写入。
