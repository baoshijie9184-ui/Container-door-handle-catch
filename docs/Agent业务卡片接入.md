# Agent 业务卡片接入

当前 `java-cloud` 模块化单体已接通 AgentScope 工具结果卡片。模型回复保持文字，卡片引用由后端观察实际业务工具返回生成；不解析模型生成的 JSON、HTML、布局、链接或操作指令。

## 已接入范围

| 卡片 | 工具 | 交互 |
| --- | --- | --- |
| 检测任务与进度 | `get_task_detail`、`get_my_detection_tasks`、`search_detection_tasks` | 显示当前状态、处理图片、缺陷数量、设备名称和复核状态；进入检测工作台 |
| 质检记录 | `get_my_quality_records`、`get_quality_records` | 展示本次查询选中记录；不解释为仅待办队列 |
| 工作统计 | `get_my_work_metrics`、`get_department_work_metrics` | 当前权限及时间范围下的任务数、图片数、已处理图片、缺陷数量；不把缺陷数换算成不良图片率 |
| 报告查询 | `list_quality_reports`、`get_quality_report` | 显示当前标题、状态、版本、任务及报告入口，不展示正文和依据全文 |
| 报告草稿结果 | `create_report_draft`、`edit_report_draft` | 返回实际报告引用；私人草稿明确标注尚未提交或审批，提交、审批仍在独立业务页面进行 |
| 设备运行状态 | `list_devices` | 主管查看使用、在线、PLC、相机、采集状态，按设备主键进入设备详情 |
| 检测模型 | `list_models` | 主管查看名称、版本、发布状态及默认标记，进入模型详情抽屉；与 LLM 供应商目录区分 |
| 采集告警 | `list_device_alerts`、`get_device_alert` | 主管查看当前告警处理状态、级别、类型和时间；有效关联进入设备详情，关联失效保留历史记录 |
| 模型指标与发布配置 | `get_model_operations` | 主管查看登记指标、展开发布配置和使用记录，进入已有模型详情；不执行评估、发布或回滚 |

既有主管质检分配确认卡片继续使用 `AgentActionList` 和持久 PendingAction，不使用业务结果卡片执行写操作。旧 `ChatBusinessCard` 仅兼容历史记录，旧 PendingAction 不能恢复图引擎执行。

## 执行与持久化

`Harness → 专业 ReAct → 注册的业务工具 → 每轮 AgentCardCollector → 引用快照 → 聊天适配器 → chat_message`。

收集器随单轮执行创建，并传给专业工具包装器，不跨用户、会话或运行共享。只接受已返回的成功业务 `status=OK` 和与注册工具一致的 `source`，排除错误、拒绝、中断、挂起和非法资源编号。AgentScope Java 2.0.4 的 `ToolResultBlock.text` 在 Toolkit 标记终态前是 `RUNNING`，这里观察的是已返回的 Mono 工具结果；该状态与 `SUCCESS` 都需继续通过上述业务成功校验，不能单独作为成功依据。

每轮最多八张卡片，每张资源卡片最多五条引用，相同引用去重；不是完整查询结果导出。没有工具依据、查询失败或模型只返回文字时保持普通文字消息。用户、模型或知识内容中的伪造卡片不会形成业务引用。

主站消息类型 `AGENT_CARDS` 使用版本 1 信封：`version + text + runId + cards`。引用字段限定为 `type + tool + ids + days`，无业务结果正文、URL、凭证或任意组件。沿用原 `chat_message.content` 存储，不增加数据库表或迁移。SSE `done` 返回已保存的同一消息，重新打开会话或刷新页面从原数据库恢复。下一轮模型历史仅提取信封文字，不带入卡片 JSON、资源引用和运行编号；Mem0 同样仅使用文字。

会话列表预览只提取文字摘要，非法或未来版本消息显示通用卡片提示，不暴露协议 JSON 或资源引用。原消息内容保留，进入会话仍读取完整信封。

主站和独立 React UI 共用卡片引用校验与固定业务路由。React 从 AG-UI 版本化自定义事件 `doorhandle.business-cards.v1` 读取引用；事件在 `RUN_FINISHED` 前发送，客户端仅在运行完整结束后呈现结果。正文解析不混入工具参数或卡片引用，后续文本历史也不发送 React 组件或引用。

2026-10-13 已统一两个入口的数据库会话和服务端历史；React 刷新恢复已保存的文字及卡片引用，后端历史不再由客户端文本列表决定，见 [会话历史与记忆统一](Agent会话历史与记忆统一.md)。新增 Vite `/api` 代理，卡片查询沿用登录 Cookie。

## 当前权限与只读刷新

`POST /api/agent/cards/resolve` 只读解析引用，不调用模型、草稿写工具或确认审批。顶层仅接受 `cards`；逐卡拒绝未知字段、非法类型、工具、重复编号、越界数量、非整数天数及路径字符。身份来自认证上下文，系统门面重新读取当前账号角色；主管降权后不能借旧卡片读取企业统计。

检测对象每次通过 `DetectionAgentReadApi.task(actor,id)` 重读当前范围，报告通过 `QualityReportAgentApi.get(actor,id)` 重读当前所属权和状态。其他账号及主管均不能从引用读取员工私人草稿。删除、重新分派或权限撤销后隐藏该对象，显示通用不可用提示，不区分不存在和无权限，不回显隐藏对象编号或异常详情。服务异常只返回通用提示。响应 `Cache-Control: no-store`，客户端开始刷新即清空上次视图，失败不继续展示旧业务数据。

统计按引用中的天数重新计算当前范围，不恢复旧时刻的统计快照。报告卡片只返回明确的 Summary 字段，不能从旧标题、保存工具名或模型说法推定当前审批状态。卡片中只有固定业务页面链接和只读刷新按钮；页面内实际操作继续接受现有鉴权、版本、确认和审计规则。

设备和检测模型卡片分别经 `ResourceAgentReadApi.device`、`ModelAgentReadApi.model` 重读，两个门面均要求主管身份；账号降为员工后，旧卡片立即在下次加载或刷新时返回通用不可用结果，不调用资源查询。设备主键以十进制字符串传递，覆盖 Java Long 正整数范围且不丢失 JavaScript 精度，不能使用可变的设备编号代替；模型主键限定为 Java Integer 正整数。引用禁止前导零、指数、小数、负数、越界和路径或查询字符。设备编号、模型名称及各状态仅在刷新响应内展示，引用不保存这些字段或内部路径。

模型详情链接为 `#/models?modelId=<id>`，支持首次打开和当前列表页内切换。抽屉清空旧数据再读取，缺失或拒绝访问显示错误提示；关闭、离开或切换对象时使旧请求失效，延迟响应不能覆盖新对象。卡片不提供发布、切换默认模型、下载或删除按钮。这一轮复用既有表与版本 1 信封，不新增迁移。

权限检查发生在加载和手动刷新时，不宣称页面持续实时接收权限撤销推送。文字回答和历史资源引用依然属于原用户私人聊天；本次没有清除历史聊天文字或重写既有记录。

采集告警引用使用 `DEVICE_ALERTS` 与规范 Long 主键，经 `ResourceAgentReadApi.alert` 重读；没有告警处置按钮，告警状态不能推断设备实时健康。列表分页、默认筛选、摘要字段与审计边界见 [Agent 设备告警查询](Agent设备告警查询.md)。浏览器脚本现已扩展为设备、检测模型和告警共 78 项隔离 API 检查；下文 42 项是此前设备/模型扩展的历史验证记录。

模型指标与发布配置引用为 `MODEL_OPERATIONS`，经主管模型门面读取当前登记值，异常值隐藏并提示核对，零值和缺失值分别展示。两套界面共用格式化规则，固定模型详情链接；配置记录不证明实际分流，见 [检测模型指标与发布配置查询](Agent检测模型指标与发布配置查询.md)。浏览器脚本已继续扩展该卡片，78 项是此前告警扩展时的历史检查数量。

## 联调发现并修复的兼容问题

主站会话格式包含账号名，例如 `sess_inspector.demo_ab12cd34`。持久运行日志此前拒绝点号，导致带点号账号不能发起主站运行及按会话查询运行历史。已同步修正 begin/list 的会话校验，保留路径、查询字符拒绝及账号所有权校验。会话统一后 AG-UI 的 threadId 也允许点号，以兼容数据库会话编号；runId 仍保持原有严格格式，账号所有权继续校验。

## 开源核对与前端

开发前核对 [AgentScope Java 2.0.4 发布记录](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.4)、[该版本工具文档](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/tool.md) 和 [Apache-2.0 许可证](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。保留现有 SDK、Vue/Element Plus 和 React/AgentScope Chat 依赖，无新增第三方运行库或复制开源实现。

2026-10-16 设备/模型扩展继续使用已安装的 `@agentscope-ai/chat` 1.1.72 固定自定义卡片接口；核对 npm 包 `package.json` 的 Apache-2.0 声明和随包 README 的卡片扩展说明，参见 [包发布入口](https://www.npmjs.com/package/@agentscope-ai/chat)。沿用锁定版本与版权声明，没有因新增卡片升级依赖；包 README 中的旧开源计划时间不作为当前维护状态证明。当前仍是受控业务结果卡片，完整 A2UI 协议支持范围待 P08 后续验收。

新卡片沿用白、蓝、黑色和开源按钮图标，正文与标题按文本渲染。Vue 卡片支持出现、移除过渡，按钮支持轻微缩放；两套前端支持 `prefers-reduced-motion`。固定响应式统计布局，不允许模型提供 HTML 或动态组件。

React 使用现有 `@agentscope-ai/chat` 1.1.72 的 `Bubble.cards` 固定组件入口，该安装包声明 Apache-2.0。核对实际安装版本接口及实现后适配，避免把 React 元素交给默认 Markdown 正文渲染成 `[object Object]`。组件代码来自本项目，模型不能选择 component 或 code。

本版本为项目固定业务卡片协议，未宣称实现完整 A2UI 标准。旧 `A2uiSurface.jsx` 仍未接入，本轮没有启用自由界面生成。设备/模型专用卡片已补齐；审批会签卡片、证据图片卡片和完整协议范围仍待后续开发。

## 验证

2026-10-16 设备与检测模型卡片扩展：新增两类引用的边界校验、实际 SDK Harness → 专业 Agent → 业务工具 → 收集器测试，覆盖模型虚构编号不能生成引用、列表仅取前五条、旧角色重新鉴权及删除对象隐藏。两个资源门面的测试覆盖主管限制、主键与设备编号区分、Long 精度、模型文件路径排除和当前发布状态读取。

完整 Maven `clean verify` 共 523 项，500 通过、23 项可选真实模型/数据库联调跳过，0 失败/错误。主站 Node 82 项与独立聊天 Node 5 项通过，两套生产构建成功，React 保留既有大包体积提示。证据 `work/resource-cards-full-verify.log`、`work/resource-cards-{vue,react}-tests.log`、`work/resource-cards-{vue,react}-build.log`。

新增 `script/diagnostics/agent-resource-cards-acceptance.py`，使用完全隔离的 API 样本完成 42 项浏览器检查：两入口从历史引用恢复、文本转义、未知状态安全降级、手机布局、详情路由、刷新失败清空旧数据、权限撤销隐藏链接、重试和刷新恢复、详情抽屉真实打开、缺失与非法编号、延迟请求竞争。0 JavaScript 异常，未调用模型或业务写入。结果 `work/resource-cards/results.json`，桌面/手机截图 `work/resource-cards/{vue,react}-{desktop,mobile}.png` 已复核。测试临时前端进程已关闭。

本轮未启动本地 MySQL、未对 ECS 发布或迁移，浏览器数据是测试样本；不能据此宣称云端真实设备/模型查询、实际 LLM 选工具或完整 A2UI 已验收。此前本机 MySQL 验收保留如下，其日期、范围与本轮区分。

新增卡片收集、实时范围、报告摘要、统计白名单、HTTP 输入及身份、主站信封保存/文字历史恢复、实际 SDK 生成引用、AG-UI 事件顺序和点号会话回归检查。

显式本机 `AgentCardsLocalMysqlTest` 使用真实 SDK Harness/ReAct、业务 Service、Spring 事务、会话 Mapper、运行日志和业务 MySQL；模型响应、RAG 和 Mem0 使用测试替身，不调用供应商。它保留 `agent-card-fixture-*` 检测任务、私人报告及会话，验证实际三类业务卡片落库、重读一致、其他账号拒绝、重新分派后隐藏对象、无审批事件、审计不记录卡片正文。使用：

```powershell
$env:JAVA_HOME='C:/Program Files/Java/jdk-17'
& 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd' -B -pl doorhandle-server -am test '-Dtest=AgentCardsLocalMysqlTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dagent.cards.local.mysql=true' '-Dagent.report.project=D:/AI/lunwen1/DoorHandleCatch'
```

业务库限本机 `doorhandledb`，凭证读取项目忽略的 `.env`，不输出或写入命令。模型响应脚本化，不能据此声称实际模型一定选择正确工具、回答准确或提示注入已完全防御。

浏览器脚本 `scripts/diagnostics/agent_cards_browser_acceptance.py` 读取保留的实际 MySQL 样本。主站使用真实登录、消息恢复与卡片查询；React 仅将模型流替换为测试事件，卡片数据仍走真实接口与 MySQL。验证页面刷新、只读刷新不重放模型或写操作、报告跳转、标题文本渲染、手机布局和其他账号范围。

最终验收（2026-10-13）：全量 Maven `verify` 成功，384 项中执行并通过 370 项，14 项可选模型/数据库联调默认跳过；30 项固定 Eval v2 仍全部通过。证据 `work/agent-cards-full-verify.log`。显式真实业务 MySQL 测试另行通过，实际 SDK 使用 11 次脚本模型响应生成四个业务引用，样本与结果在 `work/agent-cards-local-mysql.json`、`work/agent-cards-live-mysql.log`。不调用付费模型。

主站 47 项、React 3 项前端检查通过，两套生产构建通过，保留既有包体积提示。浏览器及 HTTP 共 17 项检查通过，包含会话列表文字预览；结果 `work/agent-cards-browser-acceptance.json`，截图 `work/agent-cards-browser-vue.png`、`work/agent-cards-browser-mobile.png`、`work/agent-cards-browser-react.png`。主站恢复与刷新没有模型请求，卡片读取不追加报告业务审计；没有 JavaScript 异常。截图已复核，有限动画在截图时完成，不改变减少动态效果设置。

最终更新的后端和两套前端已通过统一脚本重新启动，MySQL、Redis、Kafka、Chroma、Mem0 与后端六项健康检查通过，结果 `work/agent-cards-services-health.json`。本轮没有统一启动 Python 检测 Worker，也没有进行真实推理链路、真实模型语义、负载容量或完整 A2UI 验收。
