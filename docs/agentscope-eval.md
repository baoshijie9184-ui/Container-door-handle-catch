# AgentScope 单体离线规则评测

2026-10-13 报告工具更新：默认数据集升级为 `eval/agent/dataset-v2.json`，fixture 为 `synthetic-business-h2-v2`，共 30 项必测。新增员工/主管报告查询、无审批工具、身份与参数校验、真实 SDK 草稿委派八项；报告业务端口在 Eval 中仍为合成 fixture。原 v1 的 22 项和验证证据作为历史记录保留，下文第一版说明不表示默认仍运行 v1。同版本比较需使用 v2 报告，旧基线会被拒绝，不能自动提升为生产批准。真实业务 MySQL 联调另见 [Agent 报告工具接入](Agent报告工具接入.md)。

实施日期：2026-10-13；分支：`java`。本轮完成第一版固定数据集、规则评分、逐例报告、完整性门槛和可选基线比较。评测入口属于本地开发与 CI，不开放给业务用户，也不需要新增评测微服务。

## 参考与实现选择

沿用项目锁定的 AgentScope Java 2.0.4，实际运行 Harness → 专业 ReAct → 业务工具的执行链，并复用已有确认事务。官方框架提供权限和 Middleware 扩展点；本项目的评分契约和报告是应用侧实现。[AgentScope Java](https://github.com/agentscope-ai/agentscope-java)、[锁定版本 Middleware 设计](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/middleware.md)。

参考 Langfuse 对 Dataset、Experiment、Task 和 Evaluator 的组织方式，将测试输入、实际观测和评分条件分开，并按用例比较结果。[官方实验数据模型](https://langfuse.com/docs/evaluation/experiments/data-model)。

本次没有部署 Langfuse、复制其源码或增加 SDK 依赖。已核对其许可证：非企业目录主体采用 MIT，指定企业目录采用独立许可证，不能把整个仓库视为统一 MIT；未来实际接入时核对选定版本和目录。[Langfuse LICENSE](https://github.com/langfuse/langfuse/blob/main/LICENSE)。当前 Java 工程没有直接移植 Python/JS 评测 SDK。

## 运行

在项目根目录执行：

```powershell
./script/shell/run-agent-eval.ps1
```

脚本复用已有 Java/Maven，不安装环境，不启动业务服务，不读取 `.env`，不访问业务 MySQL 或付费模型。报告写入独立目录：

```text
work/agent-eval/{时间戳}-{随机后缀}/
  report.json   元数据、逐例实际观测、评分及门槛
  report.md     可读结果表
  maven.log     编译和执行日志
```

需要指定现有 Maven 时使用 `-MavenCommand`。与经人工选定的同版本报告比较：

```powershell
./script/shell/run-agent-eval.ps1 -Baseline './work/agent-eval/已有实验目录/report.json'
```

不自动把当前结果提升为质量基线。用于开发验证的报告比较不等同于经过人工评审的发布批准。

脚本运行 `AgentContractEvalTest` 与 `AgentEvalRulesTest`。普通 Maven verify 也执行这些测试，报告默认写入 AI 模块的 `target/agent-eval`；单独脚本还传入 Git commit 和工作区是否有未提交修改。直接 Maven 未传入版本属性时会明确标为 `UNKNOWN`，不伪造提交号。

## 数据集与范围

固定数据集为 [dataset-v1.json](../eval/agent/dataset-v1.json)，含 22 个必测用例、六类覆盖：

| 分类 | 当前检查 |
| --- | --- |
| TOOL_AUTHORIZATION | 员工不能注册主管工具集；员工目录没有写提议；伪造身份参数被拒绝；他人确认 ID 被拒绝 |
| TOOL_ARGUMENTS | 零页码、小数页码不进入业务门面 |
| FACTS | 工具返回的固定任务计数、图片数、缺陷数量、时间范围、来源与数据范围 |
| SDK_EXECUTION | 真实 SDK 委派和工具调用；正确绑定账号；主管提议产生 PENDING 且不写业务 |
| CONFIRMATION | 提议、批准、拒绝、取消、过期、重复确认、资源变化、角色变化与原运行取消 |
| RELIABILITY | 异常敏感标记不外泄；必要审计故障回滚已执行的合成业务写入 |

每条用例包含版本关联、合成身份引用、输入、执行场景、工具参数、决策脚本、必测标识和独立期望条件。数据集拒绝未知字段、重复编号、缺少评分条件、缺少必测分类及过大的文件。

合成业务门面提供固定返回值，不是检测模块真实 SQL 数据权限的实现；数据范围标记的比对也不能替代 MySQL 授权验收。固定模型按脚本发出工具调用，不根据中文问题自主决定路由，因此 SDK 用例证明执行链和身份绑定，不证明模型理解或语义路由质量。确认用例使用真实 `AgentActionService` 与隔离 H2 事务，业务端口写入合成表，不操作原业务任务。

每例使用独立 H2 和临时工作区；测试结束关闭资源。不使用真实账号密码、API Key、用户聊天、RAG 文档或长期记忆。

## 评分、报告与门槛

评分使用实际工具名、业务门面调用数、数据库副作用计数、确认状态、必要审计事件和工具 JSON 事实。不同数字表示形式允许等值比较；字段缺失、必要调用缺失、未授权工具、意外业务写入或敏感标记泄露直接失败，不由平均分抵消。

报告区分 `PASS / FAIL / ERROR / SKIPPED / MISSING`，统计声明总数、执行数、必测数及每类状态。未运行或跳过必测用例不能通过；执行异常保存固定错误标记，避免异常正文进入报告。

元数据包括数据集 SHA-256、fixture 版本与源码摘要、评分器版本、SDK/JDK、Git commit、源码摘要、Prompt 所在源码摘要、工具目录摘要、操作策略和测试模式。报告只保存合成实际观测及事件类型，不保存模型 Prompt、思考过程或真实个人资料。缺少供应商用量时 token 和费用为 `null`，不能据此宣称零 token 或零成本。

`contractGatePassed` 表示固定规则集完整通过；`experimentGatePassed` 还包括基线兼容和无逐例退化。基线要求数据集内容、fixture 内容、模式和评分器兼容；用例集合必须一致，不允许缺项或重复。原先 PASS 的用例变为失败、异常、缺失或跳过时记为退化。脚本在构建失败、规则失败或基线不兼容时返回退出码 1。

`productionReleaseApproved` 始终为 false。这一版不替人工发布决策，不证明真实模型质量、业务 MySQL 授权、RAG/记忆提示注入、并发容量或跨进程可靠性。相关真实业务联调记录仍分别保存在 [确认验收](agentscope-action-confirmation.md) 与 [多用户范围验收](多用户权限与数据范围方案.md)。

## 验证与后续

22 项规则用例通过；9 项评分与完整性校验通过，包括非法工具和意外写入、缺失事实/审计、敏感标记、数字等值、无效契约、缺失必测、基线退化/不兼容、重复结果，以及数据集重复编号和缺少分类。脚本实际运行成功；同版本报告比较成功；不兼容基线联调返回 1 并写出失败原因，即使用例本身全通过也不放行。

验收产物位于本机 `work/agent-eval`，不提交实际实验报告。此轮未建立经过人工审核的回答质量基线。后续增加隔离 MySQL 场景、真实模型语义路由和回答依据评测、提示注入样本、跨用户并发与失败恢复，再评估 Langfuse 展示和实验管理接入。

全量单体构建通过：319 项测试中执行 308 项，11 项显式启用的真实数据库/付费模型测试跳过，失败与错误为 0。日志为 `work/agent-eval-full-verify.log`。员工轨迹范围标签另有定向回归通过，日志为 `work/agent-eval-scope-regression.log`。本地六项服务健康检查通过，后端与两套前端已恢复运行。
