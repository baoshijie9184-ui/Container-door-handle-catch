# Agent 设备告警查询

更新：2026-10-16，分支 `java-cloud`。本轮补齐 P11 中设备采集告警的只读查询及两套聊天界面卡片，沿用 Java 模块化单体和 AgentScope Java 2.0.4。

## 已实现能力

主管主 Agent 通过 `delegate_resource_management` 委派设备资源专业 Agent，新增以下工具。员工的工具目录不包含这些工具，无法指定专业 Agent 绕过角色检查。

| 工具 | 参数 | 行为 |
| --- | --- | --- |
| `list_device_alerts` | `status`、`level`、`deviceId`、`beforeId`、`size` | 查询最新入库告警的状态摘要，按数据库主键降序分页 |
| `get_device_alert` | `alertId` | 按告警数据库主键读取当前状态摘要 |

可以向助手提出“查看当前未处理的采集告警”“查询设备主键为 9 的紧急告警”“查询告警主键 7 的处理状态”。实际工具选择仍由模型决定，不能把脚本化 SDK 测试视为真实模型语义质量证明。

列表默认 `status=OPEN`、`level=ALL`、`size=20`；状态可选 `ALL/OPEN/ACKNOWLEDGED/RESOLVED`，级别可选 `ALL/MINOR/MAJOR/CRITICAL`。设备主键可省略，明确查询设备时须使用真实主键，不能把设备编号或名称当成主键。

返回 `items + hasMore + nextCursor + queriedAt`。下一页使用上一页 `nextCursor` 作为 `beforeId`，保持其他筛选条件一致；每次读取 1–100 条，最多向数据库读取 `size+1` 条，不使用深层 OFFSET 或额外 COUNT。没有下一页时游标为 null。游标不代表冻结快照，查询期间状态变更可能改变后续匹配范围。

“最新”指主键递减的入库顺序，不推定设备发生时间严格有序。不返回或推算告警总数，不将一页结果当作全企业全部告警。

## 数据、权限和审计边界

读取链路：`AgentScope 原生工具 → ResourceAgentReadApi → 设备模块 Mapper → device_capture_alert`。AI 模块只引用 contracts，不能直接访问设备实体、Mapper 或实现类。

摘要限定以下字段：

- `alertId`：告警数据库主键，十进制字符串。
- `alertCode`：业务告警编号，对应表内 `alert_id`，不能代替数据库主键。
- `deviceId`：关联设备主键字符串；原设备删除后可为 null。
- `deviceCode`：告警发生时的设备编号快照，不保证与设备当前编号一致。
- `type/level/status/createdAt/updatedAt`：告警类型、级别、处理状态、发生时间和记录更新时间。

SQL 仅选择这些摘要列，不读取或发送自由文本告警说明、完整运行快照、OSS Key、文件路径、人员及处理备注。具体异常文案和处置记录尚未在 Agent 摘要开放。

筛选使用枚举白名单与参数绑定，主键限定正整数 Long 范围的规范十进制字符串，拒绝前导零、浮点数、指数、数值类型、溢出和路径字符。身份由服务端闭包绑定，不接受 `userId/role` 等参数。查询及单条读取门面都先检查主管身份，系统当前仍是单企业范围。

启用持久运行日志时，复用现有授权、工具开始/完成/错误事件及父子调用关联；不记录查询参数或告警正文。授权审计写入失败会阻止工具执行。这是查询轨迹，不是业务告警状态变更审计。

两个工具均为只读，不能确认、关闭、删除或重新开启告警；没有新增业务写入口、自动处置或聊天口头审批。现有 HTTP 处置接口不因本轮开发改变。

## 聊天卡片

实际成功工具结果生成 `DEVICE_ALERTS` 引用，保存告警主键及工具名，沿用版本 1 `AGENT_CARDS` 信封和 `chat_message`，不新增表或迁移。每轮八张、每张五条引用的限制保持一致。模型虚构的编号、文字或组件不会形成引用。

主站 Vue 和独立 React 均展示类型、级别、处理状态、发生/记录更新时间及设备编号快照。业务告警编号作为纯文本渲染，未知状态安全降级；有效设备关联提供固定设备详情链接，关联缺失时保留告警记录并提示关联已不可用。卡片不提供告警处置按钮。

刷新通过 `POST /api/agent/cards/resolve` 重新读取账号当前角色及每条告警；降权后返回通用不可用提示且不进入设备查询。对象删除或无权访问隐藏该记录；读取失败清空旧视图，不暴露异常详情。刷新不重放模型、分页查询或任何业务写入。原筛选条件不会被重新执行，卡片显示的是原选中记录的最新状态。

告警处理状态与设备实时健康是不同信息：“已确认”不等于异常已修复，“已解决”仅表示该告警记录已关闭。卡片明确显示这一边界。本轮没有新增实时事件推送、心跳超时检测或自动生成离线告警，查询只能反映数据库已有记录。

## 开源与兼容性

开发前核对 [AgentScope Java v2.0.4 工具接口](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/tool.md)、[版本发布记录](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.4) 和 [Apache-2.0 许可证](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。复用已安装 SDK 的 `AgentTool/Toolkit`，不按 main 分支接口替换锁定版本；没有新增依赖或复制第三方代码。

查询复用既有 V10 告警表及主键；已有状态/级别/设备相关索引不变。游标消除深分页 OFFSET，但组合筛选在大量数据下的执行计划仍需真实 MySQL 的 EXPLAIN 验证，不能由单元测试推断生产容量；本轮没有无证据地添加新索引。

## 验证与未完成事项

新增门面测试覆盖筛选与主键游标绑定、LIMIT、列裁剪、空列表、最后一页、孤立设备、当前状态、字段排除和角色限制；工具测试覆盖默认值、参数白名单、数值与溢出拒绝、身份防伪及异常脱敏。实际 SDK Harness → 专业 Agent → 注册工具 → 收集器链路已加入告警卡片用例；另验证旧卡片降权/删除后不返回旧数据，授权审计失败阻断执行。

完整 Maven `clean verify` 共 533 项：510 通过、23 项可选真实模型/数据库联调跳过，0 失败/错误，13 个模块构建及后端打包成功，日志 `work/device-alerts-full-verify.log`。

主站 Node 84 项、独立聊天 Node 5 项及两套生产构建通过，React 保留既有大包提示；日志为 `work/device-alerts-{vue,react}-{tests,build}.log`。扩展 `script/diagnostics/agent-resource-cards-acceptance.py`，使用隔离 API 样本完成原设备/模型及新增告警共 78 项浏览器检查，0 JavaScript 异常；结果 `work/resource-cards/results.json`，日志 `work/device-alerts-browser.log`，截图 `work/resource-cards/{vue,react}-alerts-{desktop,mobile}.png` 已复核。测试临时前端进程已关闭。

本轮未发布 ECS，未连接本地数据库或调用付费模型。真实云端告警数据、实际供应商工具选择、数据库执行计划和容量仍待验收；模型灰度/指标与系统健康专业查询继续列在 P11。
