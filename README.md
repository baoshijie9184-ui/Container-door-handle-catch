# 企业级集装箱门把手盖多智能体协同缺陷检测平台

开发入口：[开发总规则](docs/开发规则.md) · [单体开发](docs/monolith/README.md) · [微服务开发](docs/microservices/README.md) · [Agent 开发](docs/agent/README.md)。

当前先在 [实验室 Ubuntu](docs/monolith/配置方案.md) 继续单体开发，恢复 SSH 后再同步代码；开发阶段不用 Jenkins、不跑测试。Windows 只编辑和构建。现有 [ECS 验收与发布](docs/monolith/README.md#ecs-统一验收与发布) 路径及身份门禁保留，不把实验室开发机视为生产目标。

29 表是迁移目标，完整用户功能验收和正式切换尚未完成。此前构建结果只证明对应提交、环境和验收范围，不作为当前版本的发布依据。


本项目面向企业的集装箱门把手盖缺陷检测业务，提供图像采集、模型检测、质检复核、质量追溯和多智能体协同工作台。

## 系统架构

- **前端**：Vue.js + Element Plus；独立 Agent UI 使用 React + Spark Design
- **后端**：Spring Boot + MyBatis Plus
- **数据库**：MySQL
- **AI推理**：原始 PTH + PyTorch CPU worker（Kafka 调度），兼容既有 ONNX Runtime 路径

## AgentScope 单体开发

聊天工具记录支持按消息恢复，纯文本回复的服务端关联及 V66 启用边界见 [消息执行关联持久化](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%B6%88%E6%81%AF%E6%89%A7%E8%A1%8C%E5%85%B3%E8%81%94%E6%8C%81%E4%B9%85%E5%8C%96-20261028.md)。

Agent 前端参照本地 DeepSeek Harness：会话侧栏、居中正文、右侧按需工作面板，集中导航技能/MCP/记忆/执行追溯，并保留窄屏抽屉及键盘操作。两入口实现与验证见 [Harness 布局设计](docs/agent/Agent前端Harness布局设计.md)。

项目功能清单、已开发能力、未完成事项及后续任务见 [开发进展](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E5%BC%80%E5%8F%91%E8%BF%9B%E5%B1%95.md)。

2026-10-27 完成主站与独立 Agent 的 [UI 视觉与交互升级](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/UI%E8%A7%86%E8%A7%89%E4%B8%8E%E4%BA%A4%E4%BA%92%E5%8D%87%E7%BA%A7-20261027.md)：统一导航、页面标题、表格/表单/弹层，重排首页入口与统计层级，并同步聊天阅读与输入布局。124 个 Vue 脚本及原事件绑定保持不变；145 项前端检查、两套生产构建和响应式/交互复核通过，尚未部署。

2026-10-27 已补齐质检知识库、已审批报告 Word/PDF/Excel 交付、每模型额度台账和定时质检日报，并按后续要求开展本地隔离测试，修复并发写入、历史时间读取及按钮样式问题。实际结果见 [隔离测试记录](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E8%B4%A8%E6%A3%80%E5%8A%9F%E8%83%BD%E9%9A%94%E7%A6%BB%E6%B5%8B%E8%AF%95-20261027.md)，能力及启用条件见 [本轮实现及边界](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E8%B4%A8%E6%A3%80%E7%9F%A5%E8%AF%86%E5%BA%93%E6%8A%A5%E5%91%8A%E9%A2%9D%E5%BA%A6%E4%B8%8E%E6%97%A5%E6%8A%A5%E7%BB%AD%E5%BC%80%E5%8F%91-20261027.md)。云端候选升级及生产发布尚未完成。

2026-10-27 已备份并整理实际业务演示数据，归档明确验收夹具，统一实际图片批次、报告草稿及资料名称；保留原图、结果和审批状态。详情及恢复依据见 [业务演示数据整理](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E4%B8%9A%E5%8A%A1%E6%BC%94%E7%A4%BA%E6%95%B0%E6%8D%AE%E6%95%B4%E7%90%86-20261027.md)。

随后按用户要求恢复旧版 353 条、5,077,456 张图片汇总，图片关联留空；新增历史累计大屏源码，尚待统一发布。当前状态见 [历史累计恢复与大屏接入](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E5%8E%86%E5%8F%B2%E7%B4%AF%E8%AE%A1%E6%81%A2%E5%A4%8D%E4%B8%8E%E5%A4%A7%E5%B1%8F%E6%8E%A5%E5%85%A5-20261027.md)。

2026-10-27 继续开发执行证据保护、角色范围、记忆分类 v6 和发布准备参数；本轮按要求不测试、不构建或部署，新增源码待验证，详见 [续开发记录](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E5%8D%95%E4%BD%93%E6%94%B6%E5%B0%BE%E7%BB%AD%E5%BC%80%E5%8F%91-20261027.md)。

2026-10-26 本地收尾修复了 Node 模块加载、后端编译及缓存类型恢复问题，并补齐当前权限、质检、身份回填、MCP 与运维测试夹具。最新验证与云端剩余条件见 [本地收尾验收](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E6%9C%AC%E5%9C%B0%E6%94%B6%E5%B0%BE%E9%AA%8C%E6%94%B6-20261026.md)，本地结果不代表生产已升级。

已实现功能的用途、技术栈、模块划分及交付边界见 [系统功能说明](docs/monolith/系统功能说明.md)。

当前 `java-cloud` 分支用于模块化单体，微服务拆分后置。主站聊天和独立 AG-UI 均使用 AgentScope Java 2.0.5，旧 StateGraph 与独立 DeepSeek 客户端已移除。可用工具由角色、数据范围和功能开关共同决定；检测操作提议需人工确认，报告工具在获准时只能处理本人草稿。见 [Agent 工具权限](docs/agent/README.md#工具权限与执行) 和 [模型平台配置](docs/agent/agentscope-platform-config.md)。

“Agent执行追溯 → 模型路由”可查看实际候选模型、接入标识、耗时、失败分类、备用选择及熔断跳过。主站、独立 Agent 和专业委派按模型请求编号关联，旧历史不从默认配置推断实际模型。实现与验证边界见 [模型调用路由追溯](docs/agent/模型调用路由追溯.md)。

“Agent执行追溯 → 调研来源”支持本人 Fetch 来源的脱敏地址、摘录、哈希、片段范围和回答引用标记，按同一次运行及最终回答精确哈希关联。需 V31 与 `AGENT_RESEARCH_EVIDENCE_ENABLED=true`；抓取或引用不等于结论已核实。见 [调研来源与引用追溯](docs/agent/Agent调研来源与引用追溯.md)。

调研来源可选启用跨运行的账号配额和过期展示内容清理，需 V32；两项默认关闭，清理保留来源身份、哈希、回答引用和审计。配置及保留边界见 [调研证据存储治理](docs/agent/Agent调研证据存储治理.md)。

调研来源支持本人确认后导出当前可查看片段与引用关联，文件哈希与数量记入独立审计；需 V33 和默认关闭的导出开关。见 [来源导出与审计](docs/agent/Agent调研来源导出与审计.md)。

调研来源导出可选启用跨会话/实例的账号固定窗口限额，默认每窗口 60 秒 5 次，超限提示等待时间，失败与审计一起回滚。需 V35，默认关闭，见 [导出限流](docs/agent/Agent调研来源导出限流.md)。

长对话可选启用主 Agent 运行内的结构化摘要压缩，保留近期消息，失败回退，并记录独立模型路由与压缩轨迹。默认关闭，配置和范围见 [上下文压缩](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E9%95%BF%E5%AF%B9%E8%AF%9D%E4%B8%8A%E4%B8%8B%E6%96%87%E5%8E%8B%E7%BC%A9.md)。

跨轮持久摘要、主/子 Agent 共享压缩、完成工具结果私有卸载及 Fork 附件快照已有新增实现，需 V44/V45，独立开关默认关闭。已随当前单体编译与两入口构建通过，专项验收、迁移和部署尚待完成，见 [持久上下文与受控卸载](docs/agent/Agent持久上下文与受控卸载.md)。

Skill 链接新增 skills.sh 源码解析、魔搭原生归档快照及 V46 持久下载配额/租约。已有公开下载、局部 MySQL 与回归结果，完整联调和发布仍待继续，见 [Skill 多来源与配额](docs/agent/Skill多来源与持久下载配额.md)。

固定 Fetch 的排队/执行中安装支持本人确认取消，事务审计后撤销登记并尽力中断，保留已有文件；可重新确认安装。见 [MCP 安装取消](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/MCP%E5%AE%89%E8%A3%85%E5%8F%96%E6%B6%88%E4%B8%8E%E9%98%9F%E5%88%97%E5%9B%9E%E6%94%B6.md)。

已完成的固定 Fetch 安装支持先停用、再本人确认移除登记，保留文件和审计；重新安装使用新的安装编号。见 [MCP 安装登记移除](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/MCP%E5%AE%89%E8%A3%85%E7%99%BB%E8%AE%B0%E7%A7%BB%E9%99%A4.md)。

固定 Fetch 可选启用安装持久队列，等待任务在原确认有效期内支持重启恢复，已领取任务中断后需重新确认。需要 V34，默认关闭，见 [安装持久队列与重启恢复](docs/agent/MCP安装持久队列与重启恢复.md)。

持久安装执行节点在忙碌时也会检查其他实例提交的取消、失效令牌及期限，并请求协作式中断，保留迟到结果与执行槽保护。复用 V34，无新增开关，见 [安装跨实例协作中断](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/MCP%E5%AE%89%E8%A3%85%E8%B7%A8%E5%AE%9E%E4%BE%8B%E5%8D%8F%E4%BD%9C%E4%B8%AD%E6%96%AD.md)。

Agent 对话支持安全切点暂停/继续、本人持久消息排队与逐条引导，更多菜单包含编辑消息与关闭排队；已随八项工作台能力发布。V37/V38 增加 SDK 检查点与用户明确确认后的跨重启恢复，旧执行无检查点不可恢复，未知写结果不自动重放。见 [任务暂停与消息队列](docs/agent/Agent任务暂停与消息队列.md) 和 [八项实施与验收](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E5%85%AB%E9%A1%B9%E8%83%BD%E5%8A%9B%E5%AE%9E%E6%96%BD.md)。

开发/CI 的默认 Eval 不调用收费模型。另有明确启用的 [真实模型路由评测](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E7%9C%9F%E5%AE%9E%E6%A8%A1%E5%9E%8B%E4%B8%93%E4%B8%9A%E8%B7%AF%E7%94%B1%E8%AF%84%E6%B5%8B.md)，核对自主选工具、实际参数、回答事实及唯一执行终态；合成业务场景通过不替代生产业务权限、工作台与综合质量验收。

## 服务器运行与发布

现有 ECS 流程复用本地 Jenkins <http://127.0.0.1:8080/> 和 `doorhandle-local-ci`，通过 SSH/SCP 调度已启动的目标；不新增常驻 ECS Jenkins agent。登录信息位于 Git 忽略的私有文档 `work/jenkins/local-access.md`。ECS 的使用窗口及启停责任见 [项目工作约定](AGENTS.md)，流程见 [统一验收与发布](docs/monolith/README.md#ecs-统一验收与发布)。当前个人服务器开发不触发这条流水线。

当前统一入口为 `Jenkinsfile.ecs-monolith`，在本地 `doorhandle-local-ci` 节点执行控制与打包步骤，通过 SSH 在原单体 ECS 的隔离目录测试；旧 `Jenkinsfile` 的 Windows 本地测试流程已退役。启用任务前须确认统一入口及配套 CI 文件已推送到 SCM 分支，配置记录与最终状态见 CI/CD 文档及回执；ECS 离线或连接资料未配置时预检明确失败，流水线不自动开机或无限等待，告知用户处理目标就绪条件，助手不自动启停 ECS。三机流水线须在部署方案确定后适配，已有发布与回滚背景见 [Jenkins CI/CD](script/jenkins/README.md)。

开发中的新版流水线默认仅验证并关闭生产发布；数据库重构与迁移尚未验收，发布和旧库演练额外受默认未设置的机器环境门禁 `DOORHANDLE_COMPACT_RELEASE_READY` / `DOORHANDLE_COMPACT_REHEARSAL_READY` 限制，不能仅修改页面参数启用。模型治理的 Secret 挂载、独立加密备份与离线恢复证明已有新增代码，尚未验证或启用。见 [模型密钥与发布接入](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E6%A8%A1%E5%9E%8B%E4%B8%BB%E5%AF%86%E9%92%A5%E5%A4%87%E4%BB%BD%E4%B8%8E%E5%8F%91%E5%B8%83%E6%8E%A5%E5%85%A5.md)。

当前单体源码通过 `compose.monolith.yml`、`deploy/compose/compose.cloud.yml` 和 `deploy/compose/compose.detection.yml` 编排应用、中间件、记忆服务和 CPU PTH 检测 Worker。是否已运行、实际使用哪个版本，以目标环境和发布回执为准。

后端 Dockerfile 只负责 Java 镜像；当前源码的 MySQL、Redis、Kafka、Mem0、Qdrant 在 `deploy/compose/compose.cloud.yml`，旧 Chroma 卷仅保留为迁移来源。各 Compose 文件、初始化容器和网关之间的关系见 [容器与配置入口](docs/monolith/docker-monolith-deployment.md#容器与配置入口2026-10-22-整理)。

在项目根目录建立访问隧道并保持终端运行：

```powershell
ssh -F work/cloud/ssh-config -N -L 127.0.0.1:18088:127.0.0.1:8088 doorhandle-bj
```

主站登录地址为 <http://127.0.0.1:18088/#/login>，独立 Agent 页面为 <http://127.0.0.1:18088/agent-ui/>。连接配置与私钥位于本机忽略目录，新克隆仓库需单独配置。使用与排查见 [服务器运行说明](docs/monolith/服务器运行说明.md)，部署验收见 [服务器演示部署记录](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E6%9C%8D%E5%8A%A1%E5%99%A8%E6%BC%94%E7%A4%BA%E9%83%A8%E7%BD%B2%E8%AE%B0%E5%BD%95.md)。

原 `doorhandle-java` 任务曾跟踪远程 `java-cloud`。本机切换分支不会改变 Jenkins 的构建来源；当前数据重构候选尚未迁移验收，不能按旧任务说明推断提交后即可发布，详见 [开发进展](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/%E5%BC%80%E5%8F%91%E8%BF%9B%E5%B1%95.md)。

员工、主管各两个可登录测试账号及密码见 [测试用户账号](docs/monolith/测试用户账号.md)。

两套聊天入口支持本人会话选择 LLM、恢复系统默认、刷新保留和异常后只读核对，使用与验证范围见 [会话模型切换](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E4%BC%9A%E8%AF%9D%E6%A8%A1%E5%9E%8B%E5%88%87%E6%8D%A2.md)。

主管质检分配的提议、人工确认、审计与配置见 [AgentScope 操作确认](docs/agent/agentscope-action-confirmation.md)。

员工读取本人及分派任务、主管读取企业业务数据；聊天、记忆、操作确认仍按账号隔离。开源参考、实现范围和限制见 [多用户权限与数据范围方案](docs/monolith/多用户权限与数据范围方案.md)。

账号与员工、部门关联已支持主管管理、员工查看本人身份、版本冲突和事务审计，入口为“产线资源 → 账号与组织”。新开发库先执行 V20；使用与验收见 [账号员工部门关联](docs/monolith/账号员工部门关联.md)。

“质检追溯 → 报告与审批”已支持个人草稿、冻结提交、另一名主管预览确认、驳回/修订和已审批 Markdown 导出。新开发库先执行 V21；实现与边界见 [报告草稿与独立审批](docs/monolith/报告草稿与独立审批.md)。

报告详情新增“状态同步”，支持 Kafka 交付状态、消费回执、自动重试及主管确认重新发送。需 V30 和 `APP_REPORT_EVENTS_ENABLED=true`，见 [报告事件交付与重试](docs/monolith/报告事件交付与重试.md)。

AgentScope 新增报告专业 Agent，可查询授权报告和保存本人草稿，审批仍到业务页面。V22 保存草稿与原运行的关联，默认 Eval 更新为 30 项 v2 用例；见 [Agent 报告工具接入](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%8A%A5%E5%91%8A%E5%B7%A5%E5%85%B7%E6%8E%A5%E5%85%A5.md)。报告迁移脚本现在同时检查/执行 V21、V22。

Agent 聊天已接通检测任务、质检记录、工作统计、报告草稿、主管设备、检测模型及采集告警结果卡片。主站持久保存文字及资源引用，刷新按当前权限重读业务数据；独立 React UI 接收同一版本的 AG-UI 自定义事件。卡片刷新不重放模型或写操作，详见 [Agent 业务卡片接入](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E4%B8%9A%E5%8A%A1%E5%8D%A1%E7%89%87%E6%8E%A5%E5%85%A5.md)。主管还可按状态、级别、设备游标查询采集告警及读取单条处理状态，见 [设备告警查询](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E8%AE%BE%E5%A4%87%E5%91%8A%E8%AD%A6%E6%9F%A5%E8%AF%A2.md)。

主管模型专业 Agent 可查询检测模型的登记评估指标、发布配置及使用记录，两套界面支持指标卡片和配置展开。登记指标与配置不能视为在线实测或灰度分流生效证据，见 [检测模型指标与发布配置查询](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%A3%80%E6%B5%8B%E6%A8%A1%E5%9E%8B%E6%8C%87%E6%A0%87%E4%B8%8E%E5%8F%91%E5%B8%83%E9%85%8D%E7%BD%AE%E6%9F%A5%E8%AF%A2.md)。

主管还可询问系统健康，资源专业 Agent 读取固定 Actuator 探针的受控摘要，明确检查时间、缓存有效期及未覆盖服务；详情脱敏、总等待和线程数量受限，不执行运维修复，见 [系统健康查询](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E7%B3%BB%E7%BB%9F%E5%81%A5%E5%BA%B7%E6%9F%A5%E8%AF%A2.md)。

“Agent技能演化”已支持本人授权经验来源、Agent 提议私人 Skill 草稿、服务端结构/权限规则 Eval、独立主管审核发布、SDK 原生读取、版本回退、停用及 30/90 天维护。需 V23 和 `AGENT_SKILL_EVOLUTION_ENABLED=true`；真实模型语义质量尚未验收，见 [技能自学习与受控发布](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%8A%80%E8%83%BD%E8%87%AA%E5%AD%A6%E4%B9%A0%E4%B8%8E%E5%8F%97%E6%8E%A7%E5%8F%91%E5%B8%83.md)。

两套聊天界面已支持输入 `/` 选择技能命令；`/skills` 查看当前角色可用技能，`/skill 技能名或skill-id 问题` 先核对并加载发布版本，再由 AgentScope 回答。命令加载有独立运行轨迹和版本审计，新增 `/skills install 链接` 生成页面确认入口；链接安装与卸载由页面明确操作。用法与验证见 [技能斜杠命令](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%8A%80%E8%83%BD%E6%96%9C%E6%9D%A0%E5%91%BD%E4%BB%A4.md)。

主站与独立 Agent 页面已统一后端会话、历史、RAG 与账号范围 Mem0 记忆。React 支持选择、新建及刷新会话，刷新恢复数据库消息，详情见 [会话历史与记忆统一](docs/agent/Agent会话历史与记忆统一.md)。

新增“Agent智能系统 → 个人记忆”：查看本人记忆、控制读取与自动保存、预览确认删除及操作记录。两套聊天入口使用同一账号设置，需 V26 与内部 `MEM0_BRIDGE_TOKEN`；本机迁移脚本已配置。详情见 [个人长期记忆治理](docs/agent/个人长期记忆治理.md)。

个人记忆现已支持编辑原文、预览确认保存、版本冲突后保留草稿并重新核对，以及超过 100 条的连续分页读取。Mem0 保留独立 HTTP 服务边界，新增可选持久数据目录；后续部署准备见 [Mem0 服务器迁移准备](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Mem0%E6%9C%8D%E5%8A%A1%E5%99%A8%E8%BF%81%E7%A7%BB%E5%87%86%E5%A4%87.md)。

固定 Agent 规则评测、实验报告与基线比较见 [Eval 使用说明](docs/agent/agentscope-eval.md)，入口为 `./script/shell/run-agent-eval.ps1`。当前是模型脚本与隔离 H2 的规则评测，真实模型回答质量仍待后续验收。

“Agent智能系统 → 资源市场”收录国内外 11 个来源，支持 Agent/MCP/Skill 分类、搜索及官方入口，见 [资源市场接入](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E8%B5%84%E6%BA%90%E5%B8%82%E5%9C%BA%E6%8E%A5%E5%85%A5.md)。Skill ZIP 上传及上传来源创建流程已移除；技能演化保留业务运行经验提炼、规则 Eval、独立审核与版本治理。第一版公开链接下载已接入，见 [链接下载安装](docs/agent/外部Skill链接下载与受控安装.md)；脚本附件执行和远程 Agent 接入仍未实现，见 [技能自学习](https://github.com/baoshijie9184-ui/Container-door-handle-catch/blob/d363b7dec2230a4a17f51877bf0bff1f74f1baeb/docs/Agent%E6%8A%80%E8%83%BD%E8%87%AA%E5%AD%A6%E4%B9%A0%E4%B8%8E%E5%8F%97%E6%8E%A7%E5%8F%91%E5%B8%83.md)。

Fetch MCP 已接入：“Agent智能系统 → MCP工具”，人工确认版本/许可后主动启用，保留账号隔离与审计。`java-cloud` 新增内网 Higress 与独立容器运行器：Java 通过原生 Streamable HTTP 调用，运行器每次在独立容器内启动固定 Stdio Fetch，公开网页出口经受限代理。需 V25 与 `AGENT_LOCAL_MCP_ENABLED=true`，旧安装需本人重新确认迁移。部署和边界见 [AI 网关与隔离 Fetch](deploy/mcp/README.md)，原 Stdio 模式见 [本地 MCP](docs/agent/本地StdioMCP接入.md)。通用 MCP 和远程 Agent 注册尚未实现。

## 功能特点

- 门把手状态分类（正常、需要维修、需要更换）
- 实时图像检测及结果可视化
- 带有颜色标记的检测框和标签
- 检测历史记录管理
- 模型管理与切换

## 本地编辑与构建

Windows 工作站只编辑源码、编译和打包。实验室 Ubuntu 当前仅用于直接开发和跳测试构建；现有 ECS 测试及正式发布仍走 [ECS 统一验收路径](docs/monolith/README.md#ecs-统一验收与发布)。

### 本地构建工具

- JDK 17 与 Maven
- Node.js 24 与 npm
- 如需编辑或编译 Python 源码，复用已有项目 Python 环境

本机不需要安装或启动 MySQL、Redis、Kafka、Mem0 或检测 Worker，也不复制运行用 `.env`。环境模板中的连接配置由服务器部署注入。

### 后端构建

在项目根目录执行。为本轮选择新的项目内输出目录；`-DskipTests=true` 只编译测试源码，不执行测试：

```powershell
mvn -DskipTests=true clean package -B -ntp -Ddoorhandle.isolated-verification=true "-Ddoorhandle.verification-root=D:/AI/lunwen1/DoorHandleCatch/work/monolith-build-01"
```

构建成功不代表云端验证或发布完成。编译工具沿用 Spring Boot 3.2.4 / Java 17，不复用微服务分支的已编译字节。

### 前端构建

分别在 `frontend` 和 `frontend-agent` 目录安装锁定依赖并构建静态资源：

```bash
npm ci --ignore-scripts
npm run build
```

使用现有 ECS 验证入口时，前端开发服务器和测试必须在 ECS 上启动，并要求显式后端地址与 ECS 身份校验。Windows 工作站不执行 `npm run dev`、`node --test` 或浏览器测试。

### ECS 验证环境

Java/Maven/Python/Node 与浏览器依赖准备在服务器独立测试目录，和既有部署目录分开。[python/environment.yml](python/environment.yml) 保留 Python 依赖清单；已有兼容 Conda 环境需要更新时，只在 ECS 上操作：

```bash
conda env update -n leetcode -f python/environment.yml
```

进入已核验的 ECS 隔离源码目录后，设置 `DOORHANDLE_ECS_INSTANCE_ID`、实际 `DOORHANDLE_ECS_MACHINE_ID` 及工具绝对路径，使用以下入口：

```bash
python3 script/jenkins/verify-ecs.py
```

Jenkins 任务使用 `Jenkinsfile.ecs-monolith`。真实 MySQL 场景需要控制器提供独立数据库和绑定实例身份的私有 JSON，具体参数见运行约定；不能将生产 `deploy/cloud.env` 或业务数据库交给测试脚本。

代码与构建准备完成后，核对已启动 ECS 的身份和连通性，再由 Jenkins 统一测试；目标未就绪时告知用户，不自动开机或改为本地执行。测试完成后仅停止本轮拥有的测试进程和临时资源、保全证据，不停止业务服务或 ECS。ECS 保持开启，由用户自行关闭；助手不在测试前后自动启停，也不安排验收后的关机任务，Jenkins 控制器保持运行。

## 使用指南

完整的业务操作说明请查看：

```text
docs/system-user-guide.md
```

智能助手的统一 Qdrant/RAG/Mem0 配置见 [向量存储说明](docs/agent/middleware/semantic-vector-storage.md)。旧 Chroma 的只读恢复说明保留在：

```text
docs/chroma-rag-setup.md
```

### Java 单体 Docker 部署

当前源码以三个 Compose 文件编排 Java 后端、托管双前端的 Nginx、MySQL、Redis、Kafka、Mem0、Qdrant 和 CPU PTH 检测 worker。中间件调整与验收范围见 [单体中间件](docs/monolith/middleware/monolith-alignment.md)，正式切换仍受迁移验收门约束。`deploy/cloud.env.example` 提供服务器配置模板，现有私有配置继续保留在服务器原运行目录，不能用本机 `.env` 覆盖。

镜像设计见 [Docker 部署说明](docs/monolith/docker-monolith-deployment.md)，已部署服务的日常使用见 [服务器运行说明](docs/monolith/服务器运行说明.md)。应用更新从 Jenkins 发布；同一数据代际沿用原持久卷，Chroma→Qdrant 必须使用候选迁移与独立恢复流程，不能把旧 Mem0 卷直接挂到新运行时。首次部署与已部署实例恢复应分别按对应文档操作。

原 `deploy/compose/compose.nginx.yml` 与 [双实例部署说明](docs/monolith/nginx-compose-deployment.md) 保留为实验入口，不作为当前单体默认方案。

### 图像检测

1. 建立访问隧道，打开 <http://127.0.0.1:18088/#/login>
2. 登录系统。系统不内置默认账号；首次部署时请由数据库管理员向 `users` 表写入使用 BCrypt 加密的企业账号，禁止使用公开的固定密码。
3. 进入"图像检测"页面
4. 上传门把手图像
5. 选择检测模型（可选）
6. 点击"开始检测"按钮
7. 查看检测结果（包含检测框、类别和置信度）

### 检测结果说明

- **绿色框**：正常状态
- **橙色框**：需要维修
- **红色框**：需要更换

## 常见问题解决

### 中文显示乱码

系统默认使用 UTF-8 编码。服务器出现乱码时，检查容器日志和私有部署配置中的 JVM 编码参数，通过正常发布流程应用配置。

### 数据库连接问题

在 ECS 上检查容器私网 MySQL 的健康状态、显式连接地址与专用账号；本机不启动数据库。测试连接必须指向本轮隔离库。

### 图像上传失败

请检查图像格式（支持JPG/JPEG/PNG），并确保文件大小不超过限制（默认5MB）。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
