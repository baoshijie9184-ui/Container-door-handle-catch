# Agent 调研来源与引用追溯

更新日期：2026-10-16。分支：`java-cloud`。入口：Agent智能系统 → Agent执行追溯 → 调研来源。

## 已实现的闭环

本人启用的固定 Fetch MCP 返回文本后，服务端为该次实际调用登记 `src-UUID`。工具返回追加服务端编号与引用标记说明。主 Agent 的最终回答使用 `[source:src-UUID]` 时，服务端只匹配本账号、本运行中仍可查看的已登记来源，不接受其他运行、其他账号或模型编造的编号。

登记、引用和事实核实分开展示：

| 状态 | 表示什么 |
| --- | --- |
| 抓取已登记 | Fetch 已返回非错误文本，并成功保存本次返回片段的来源记录 |
| 回答含来源标记 | 最终回答中发现格式正确且属于本次运行的来源编号 |
| 回答引用位置匹配 | 当前加载的助手消息与保存的最终回答 SHA-256 完全相同，且标记的 UTF-16 起止位置匹配 |
| 结论已核实 | 本轮未实现；抓取、编号关联和文字标记不能证明来源支持某个结论 |

追溯页展示来源卡片、纯文本摘录、抓取时间、工具调用编号、返回片段范围、文本长度与 SHA-256。点击回答中的来源按钮可定位卡片；“查看抓取调用”仅跳转到已加载且明确匹配当前主 Agent、Fetch 工具与 callId 的事件，不推测未加载的调用。没有完全匹配的回答时，保留引用数量并说明原因，不按时间猜测对应消息。

主站与独立 Agent 共用 `AgentScopeConversationService`，均登记最终回答关联；独立入口通过既有执行追溯链接进入同一页面。本轮没有增加聊天消息类型，也没有实现聊天气泡内的来源卡片。

## 数据范围与存储

新增 `agent_research_source` 和 `agent_research_answer` 两张 MySQL 表，业务实现位于 AI 模块 `research` 包。公开编号使用 UUID，聚簇主键沿用递增 BIGINT。来源按账号、运行和工具调用唯一；读取通过运行日志再次校验账号，不存在与其他账号的运行均返回 404。

| 记录 | 内容与限制 |
| --- | --- |
| 来源 | 请求地址的脱敏表示、是否省略查询参数、是否改写地址、标题、最多 1000 UTF-16 单元的摘录、返回文本哈希、文本长度、start_index/max_length、抓取与可查看截止时间 |
| 标题 | 优先取工具文本中的 Markdown 标题，否则显示请求主机名；不等同于经过核实的网页标题 |
| 内容哈希 | 对本次 Fetch 返回的完整文本计算 UTF-8 SHA-256，可能包括 Fetch 工具封装；不是原始网页 HTML 的哈希 |
| 回答关联 | 最终回答哈希、有效来源标记的起止位置、未匹配标记数量；不另存最终回答正文 |
| 容量 | 每个运行最多登记 20 个来源，每个回答最多登记 200 个来源标记；同一次 callId 不允许不同请求或不同返回覆盖原记录 |

网页 URL 的查询参数不持久保存；疑似凭证路径只保留主机与根路径。摘录对常见密钥、Bearer、凭证赋值、电子邮箱和嵌入网址做规则脱敏。这些规则不是完整敏感信息识别系统。正文与标题始终按未受信任纯文本展示，不使用 HTML 或 Markdown 执行其中内容。

未改写的请求地址可以由用户主动打开，使用 `noopener noreferrer` 与 `no-referrer`；改写后的地址没有外链，避免把已省略参数的地址冒充原请求。页面读取、重试、定位和刷新不会再次执行 Fetch 或调用模型。

普通 `agent_run_event` 继续仅存白名单元数据，**不写入 URL、摘录或回答正文**。来源读取是独立、禁止缓存的 GET 接口：`/api/agent/runs/{runId}/sources`。现有“导出轨迹”不包含来源摘录、地址或会话正文。

后续 D35 已补独立“导出来源”入口：本人明确确认后重新读取当前可查看来源，保存 JSON，且先提交文件摘要审计。该功能需 V33 和单独开关，默认关闭，详见 [来源导出与审计](Agent调研来源导出与审计.md)。

## 并发、失败与有效期

- 来源与回答登记使用短事务，在当前账号的运行行上 `FOR UPDATE`，校验运行仍为 RUNNING 且租约有效。网络请求在事务外。
- 采用 READ COMMITTED，保证等待运行锁后能看到其他登记事务的最新记录；并发来源登记不会超出 20 条上限。
- 同一 callId、相同请求及相同返回允许幂等重读原来源编号；内容或输入变化返回冲突，不覆盖既有证据。
- 失败、拒绝、中断或空文本不创建来源。AgentScope Java 2.0.4 的 MCP 正常转换结果使用默认 RUNNING，外层工具执行器随后才标为 SUCCESS；登记接在原生 MCP `Mono` 完整返回之后，同时接受这一正常结果和显式 SUCCESS，拒绝 ERROR/DENIED/INTERRUPTED。
- 来源存储失败时，工具向 Agent 返回受控错误，不交付尚未登记的原文；会话与并发许可仍会释放。回答引用登记失败时，不发送运行完成或声称持久化成功。
- 每条来源默认可查看 30 天，使用数据库时间；到期后 API 不再返回地址与摘录。后续 D34 已补齐可选的跨运行账号有效来源配额及过期展示内容清理，需要 V32 与单独开关，默认关闭；清理保留编号、哈希、引用和审计，不删除来源行，见 [存储治理](Agent调研证据存储治理.md)。备份、元数据保留期和完整物理归档仍未完成。
- 已终止或租约过期的运行不能追加来源或引用，读取历史不会恢复工具执行。

## 启用、迁移与回退

默认关闭以兼容现有数据库。在目标 MySQL 8 库确认已有 V16 运行日志及 V25 本人 MCP 注册表后，备份并执行：

```sql
SOURCE /path/to/sql/mysql/migration-V31-agent-research-evidence.sql;
```

同一 SQL 同步打包至 AI 模块 `classpath:db/migration-V31-agent-research-evidence.sql`。脚本只创建新表，不修改原消息、事件或业务数据，不由应用启动时自动执行。

部署环境启用：

```dotenv
AGENT_RUN_JOURNAL_ENABLED=true
AGENT_LOCAL_MCP_ENABLED=true
AGENT_RESEARCH_EVIDENCE_ENABLED=true
```

重启后端后仍需账号本人确认安装并启用 Fetch；此开关不会替用户安装或启用工具。缺少运行日志或 V31 表时启动会报明确信息。

回退将 `AGENT_RESEARCH_EVIDENCE_ENABLED=false` 并重启后端。已有表和数据保留，页面显示登记功能未启用。后端与前端应成套发布；现有旧服务器还没有该来源 API。本轮未在 ECS 执行 V31、改写私有配置或发布应用。

## 开源参考

实现继续使用 Apache-2.0 的 [AgentScope Java 2.0.4 MCP 工具](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/agentscope-core/src/main/java/io/agentscope/core/tool/mcp/McpTool.java)与原生工具返回结构，兼容当前 SDK 版本。参考 MIT 的 [LangChain Document 数据模型](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/documents/base.py)中稳定编号、文本与来源元数据分离的思路。已核对相关许可证和固定 SDK 接口；[LangChain 仓库状态](https://api.github.com/repos/langchain-ai/langchain)显示未归档且近期仍有提交。本轮不新增这些项目依赖、不复制其源码，也不替换 AgentScope。

界面延续项目原有 Vue/Element Plus 与此前参考 DeepSeek Harness 的追溯布局，采用现有开源图标；出处和许可保留在既有文档与参考仓库。

## 验证与尚未覆盖

定向测试使用隔离 H2、真实 AgentScope Harness 推理循环、脚本模型及模拟的已完成 MCP 返回，不访问付费模型。覆盖脱敏、UTF-16 引用偏移、哈希匹配、跨账号/运行拒绝、重复调用、并发配额、过期、终态、接口缓存控制与存储错误。原生 SDK 闭环验证工具返回含登记编号、后续模型能看到编号、最终回答保存对应引用。SQL 根目录与 classpath 副本做逐字节一致性检查。

完整验证结果：

| 检查 | 结果 |
| --- | --- |
| Maven `clean verify` | 515 项：492 通过、23 个可选验收跳过、0 失败/错误；13 个模块构建成功，启动包已生成 |
| 主站 / 独立聊天 Node | 80 / 5 项通过 |
| 追溯浏览器 / 原界面回归 | 60 / 30 项通过，JavaScript 页面错误为 0 |
| 主站生产构建 | 通过 |
| 迁移副本 SHA-256 | 根目录与 classpath 副本一致 |
| `git diff --check` | 通过，只有既有换行提示 |

浏览器验收覆盖新来源卡片、引用定位、HTML 文本化、脱敏外链、失败清理重试、手机及旧记录降级；临时前端预览进程已停止。真实 MySQL 和付费生成模型验收未在本轮运行。

日志：`work/research-*.log`；截图：`work/agent-trace/research-sources-desktop.png`、`research-sources-mobile.png`；浏览器结果：`work/agent-trace/results.json`。

尚未完成：真实 MySQL 与供应商模型的云端联调、重定向最终地址采集、完整网页快照、精确引文核验、结论与证据的语义支持评测、元数据物理归档及审计留存治理。D34 的可选账号配额和过期内容清理、D35 的来源导出验证见各自文档。不能将本功能称为完整事实核查系统。
