# Agent 技能自学习与受控发布

当前 `java` 单体已实现第一版经验提炼与技能演化：本人授权来源 → Agent 提议或人工编写私人草稿 → 服务端结构与权限规则 Eval → 主动提交 → 独立主管人工审核 → 按角色读取发布版本 → 加载审计、版本回退与周期维护。

Skill ZIP 上传及上传来源创建流程已移除。成功业务运行仍是经验提炼来源；新增 LINK 来源通过受控链接下载、固定版本与文件许可核验后创建私人草稿，见 [链接下载安装](外部Skill链接下载与受控安装.md)。历史上传版本和版权、审计记录保留供查看及停用，不再发布、回退启用或加载。V24 的版本来源列保留用于识别历史记录，不删除既有数据。

这套流程学习的是通用业务方法，不修改底层模型权重，不自动训练检测模型。自动规则检查不代表真实模型理解、经验有效性或提示注入防御已验收。

## 开源实现与适配

开发前核对项目固定版本 [AgentScope Java 2.0.4 的 Skill 文档](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/harness/skill.md) 与 [Apache-2.0 许可证](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。官方提供 `propose_skill`、技能审核 Gate、Curator 及 `AgentSkillRepository`、`load_skill_through_path`。后两个 SDK 接口用于本项目的真实技能读取。

项目已有多用户权限、MySQL 业务事务、浏览器人工确认和持久运行记录，因此提议、审批和维护接入应用自己的服务与数据库，而非开启 SDK 可自由编辑、删除技能文件的 `skill_manage` 或直接自动发布。项目工具名为 `propose_learned_skill`，不把它称为官方原生 `propose_skill`。SDK 官方文件 Gate 与 Curator 未直接启用，应用层提供对应受控流程。

保持原 SDK 框架，没有增加另一套 Agent 引擎、ReMe 依赖或开放 shell、任意文件读写。只有单份 `SKILL.md` 内容，没有脚本、引用附件或新工具分组；发布后的技能是经验参考，不能修改工具白名单、主 Agent 身份和业务审批规则。

## 页面与操作

入口：“Agent智能系统 → Agent技能演化”，路径 `/agent/skills`。

1. 员工或主管选择本人已完成运行，点击“授权提炼此运行”，在弹窗明确授权。只有确有成功业务工具调用的运行可以授权；未完成、失败、取消和他人私人运行均不可作为来源。
2. 可在页面编写草稿，或向助手明确要求从已授权运行提炼经验。助手工具不能创建来源授权，也不能评测、提交或发布。
3. 草稿选择目标角色、适用场景、脱敏步骤及来源成功工具。员工只能创建员工技能；主管可选择两类角色。角色、运行身份、草稿所属权始终由服务器检查。
4. 点击“运行规则 Eval”，通过后本人可以提交独立审核。草稿、规则通过版本仍为私人资料，主管不能提前读取其他人的草稿。
5. 另一名主管核对版本正文、适用场景、脱敏证据和 Eval，勾选业务适用性、隐私权限核对项并填写意见，再在二次弹窗确认发布或驳回。主管不能审核自己的技能。
6. 发布后目标角色的后续运行获得该审核版本。原版本永久保留；创建新版本不替换当前发布版本。待审版本不能修改，驳回后可创建修订版本重新评测。
7. 主管可以选择此前已审核且当前规则有效的版本回退，或停用技能。操作需要修订号、原因和页面明确确认。

页面显示实际技能加载次数与操作审计。加载次数说明 SDK 读取或斜杠命令明确加载了技能，不代表任务成功率、质量提升或 Agent 必然遵循了经验。

两套聊天界面已支持 `/help`、`/skills`、`/skills info 名称` 和 `/skill 名称或skill-id 问题`，也可用 `/技能名 问题` 简写。命令目录和加载仅针对当前角色的发布版本，加载时重新核对状态、摘要与证据；应用层明确读取记录为 `COMMAND_LOAD`，SDK 读取仍为 `LOAD`。用法、边界与验证见 [Agent 技能斜杠命令](Agent技能斜杠命令.md)。

## 来源隔离与内容完整性

授权保存 `user_id + run_id`，证据只包含成功业务工具名、完成时间、框架和入口类型；不保存原聊天正文、工具参数、检测图片、报告正文或其他账号资料。读取来源、生成提议均校验账号；提议还必须绑定实际 SDK `RUNNING` 运行、主 Agent、未到期租约及 callId。

相同来源授权幂等；相同提议运行与完整参数生成稳定请求编号，重复调用不再创建另一份草稿。人工页面保存沿用请求编号；不同参数使用同一编号会冲突。状态操作由数据库行锁及 expectedRevision 防止重复提交，客户端失败不自动重放写请求，先刷新核对实际状态。

提交后，主管仅查看本人主动提交的脱敏技能内容与证据。原运行编号只向技能本人显示；实际加载审计中其他人的 runId/callId 对当前访问者隐藏。共享技能不会赋予主管访问员工私人对话的权限。员工可以看到已审核的同角色技能，但不能看到其他人的未审核版本。

技能正文、角色、名称、工具清单 SHA-256 和来源证据 SHA-256 用于冻结、评测、提交、发布及运行读取完整性校验。内容异常则拒绝加载，不能用过去的 Eval 结果放行被修改的正文。

用户仍需在提交前去掉具体业务对象、姓名、商业资料等。本版只能识别有限危险与密钥模式，无法证明任意文字已自动脱敏；主管核对是发布条件。禁止把私人聊天批量转成共享技能。

## Eval 的实际边界

每次 Eval 的服务端报告绑定 `skill_id + version_no + content_sha256 + suite_version`，规则套件 `skill-structural-policy-v1`。

| 规则 | 检查 |
| --- | --- |
| ROLE_TOOL_ALLOWLIST | 技能工具属于目标角色已经注册的业务工具 |
| SOURCE_SUCCESSFUL_TOOLS | 所选工具确实出现在授权来源的成功业务工具事件中 |
| CONTENT_BOUNDS | 描述、步骤、工具数量满足边界 |
| NO_EXECUTABLE_OR_SECRET_PATTERNS | 拒绝脚本代码块、外部地址、部分密钥及绕过权限审批的明显模式 |
| NO_ADDITIONAL_TOOLS | 不允许技能管理、shell、自动审批等额外工具 |
| SDK_SKILL_METADATA | 符合真实 SDK 技能元数据及空资源约束 |

报告明确标注 `STRUCTURAL_POLICY_ONLY`、`semanticQualityEvaluated=false`、`paidModelsCalled=false`。发布还重新执行当前规则并核对当前版本的合格报告，旧版本、旧规则或旧内容摘要不能替代。

项目原有固定 Eval v2 继续用于整体 Agent 回归。新增测试走真实 Harness、原生技能读取、提议工具和业务事务；模型响应脚本化。真实候选模型的技能选择、回答质量、长期收益、对抗性注入、灰度与发布效果比较仍需后续语义评测。

## 运行时与维护

`RoleAgentFactory → SkillEvolutionService.repository(actor) → SkillSnapshotRepository → HarnessAgent.skillRepository → load_skill_through_path`。

只将目标角色、已人工审核、当前发布指针和当前规则合格的版本注入单轮只读快照。技能读取仍走 SDK 原生生命周期，中间件在实际读取前重查当前角色、发布状态及 `SKILL.md` 路径；拒绝其他资源路径。角色变更、回退或停用后旧快照不能继续加载已失效版本。

SDK 会在运行前刷新技能加载工具，因此授权与加载审计放在原有 Middleware 生命周期中，避免用被框架覆盖的工具包装器统计。实际 `ToolResultEndEvent SUCCESS` 才增加读取次数和 LOAD 审计。运行日志记录工具名、callId、权限策略与结果，不写技能正文。正文已经载入某轮上下文后，停用不抹除该轮已有文本；后续读取重新检查。

每轮最多加载仓库中的三十个已发布技能，列表目前最多五十项；这些边界不是生产容量承诺。技能供主 Agent 读取并指导已有专业委派；专业 ReAct 不自行扩展工具或技能权限。

每日 03:20 应用维护任务依据上次实际加载时间，未曾读取时依据发布时间：超过 30 天标记 STALE，仍允许读取；超过 90 天清空发布指针并自动停用。读取 STALE 技能恢复 ACTIVE。维护保留所有审核版本与审计，不调用模型、不编辑内容、不删除资料。自动维护使用系统审计 actor=0；恢复需主管明确回退到有效审核版本。

## 配置与迁移

默认关闭 `AGENT_SKILL_EVOLUTION_ENABLED=false`。开启前需运行日志 `AGENT_RUN_JOURNAL_ENABLED=true`、既有 V16 运行表及 V23 五张演化表；启动不自动执行 DDL，不创建默认技能。

V23 根 SQL 与 App classpath 副本一致，新增：`agent_skill_source`、`agent_learned_skill`、`agent_skill_version`、`agent_skill_eval`、`agent_skill_audit`。只新增表，不改原检测任务、用户或报告。本机已显式迁移并在忽略的 `.env` 开启，凭证不输出。

```powershell
& 'D:/ruanjian/anaconda3/envs/leetcode/python.exe' script/shell/migrate-local-skills.py --apply
```

省略 `--apply` 仅检查；脚本限制本机 `doorhandledb`，迁移副本不一致会拒绝。DDL 不能宣称事务自动回滚；应用回退先关闭功能开关，保留五张表、历史版本及审计，不删表。开启后统一启动健康检查检查 V23 就绪。

## 验证与诊断

`SkillEvolutionTest` 使用隔离 H2 和真实 SDK，验证来源授权、私人草稿、规则失败、发布前冻结、审计失败事务回滚、新版本不影响在用版本、回退停用、角色隔离、实际原生加载审计及 30/90 天维护。接口检查来源操作头、人工核对校验、匿名拒绝及不缓存。

本机显式 `SkillEvolutionLocalMysqlTest` 使用真实业务 MySQL、账号、运行日志和事务，从已保留的本人运行取脱敏来源，通过实际 Harness 提议工具创建草稿，评测、独立发布、原生读取、加载审计、修订、回退与停用。模型响应使用脚本，不访问模型供应商；样本名称 `fixture-progress-*`，保留历史，并在验收后停用以免干扰实际助手。

```powershell
$env:JAVA_HOME='C:/Program Files/Java/jdk-17'
& 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd' -B -pl doorhandle-server -am test '-Dtest=SkillEvolutionLocalMysqlTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dagent.skills.local.mysql=true' '-Dagent.report.project=D:/AI/lunwen1/DoorHandleCatch'
```

该测试读取上一轮 `work/agent-cards-local-mysql.json` 的实际运行，没有伪造成功来源。如果没有样本，先按业务卡片说明运行本机验收。结果 `work/skill-evolution-local-mysql.json` 和 `work/skill-evolution-live-mysql.log`。

随后 `scripts/diagnostics/skill_evolution_browser_acceptance.py` 通过实际登录、业务接口和浏览器核对待审冻结内容、主管二次确认、回退停用、本人来源链接与审计，不发起付费模型请求。

最终验证（2026-10-13）：全量 Maven `verify` 成功，398 项中 383 项执行通过、15 项可选联调默认跳过；包含新增十项 H2/SDK 技能测试、两项 HTTP 流程测试、一项仅开启技能草稿能力时的模式状态回归，以及原有三十项 Eval v2。实际业务 MySQL 测试另行执行通过，验证真实提议与原生加载工具、来源隔离、独立发布、两版切换、回退和停用；模型响应均脚本化，未调用供应商。证据 `work/skill-evolution-full-verify.log`、`work/skill-evolution-live-mysql.log`。

主站 47 项现有检查及最终生产构建通过。浏览器与真实 HTTP 共十五项流程检查通过，无 JavaScript 异常或模型重放，结果 `work/skill-evolution-browser-acceptance.json`；保留的 `fixture-progress-*` 技能最终均已停用，历史版本及 LOAD 审计保留。此前失败试验的样本仅停用并保留，未删除原始记录。另有两项只读桌面/手机布局检查通过，弹窗挂载到页面主体、限制正文高度并内部滚动，标题、正文和操作可正常查看。结果 `work/skill-evolution-layout-acceptance.json`，最终截图 `work/skill-evolution-browser-desktop.png`、`work/skill-evolution-browser-mobile.png` 已复核。

更新后端与主站已通过统一脚本启动，本机演化开关开启、V23 五表健康，MySQL、Redis、Kafka、Chroma、Mem0 与后端六项检查通过，结果 `work/skill-evolution-services-health.json`。仍未实现真实模型技能收益评分、灰度比例投放、自动经验语义合并、共享知识脱敏自动判定、ReMe 接入或模型权重训练。

2026-10-14 更新：LINK 来源复用上述评测和独立审核流程，发布后只对本人匹配角色开放；来源完整性依据固定提交清单及实际文件，而非成功运行证据。包内脚本和附件仅存档，不执行；详细边界见链接下载安装文档。
