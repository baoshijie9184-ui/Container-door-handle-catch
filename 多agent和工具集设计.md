# 多 Agent 和工具集设计

## 1. 设计目标

面向检测部门员工和检测部门主管分别提供一个主 Agent，并为每类角色配置最多四个专业 Agent。主 Agent 负责意图识别、权限校验、任务编排、结果汇总和调用链路记录；专业 Agent 负责具体业务。查询类操作可直接执行，创建、修改、删除、发布、回滚等写操作必须二次确认。

统一调用链：`用户问题 → 主 Agent → 专业 Agent → Skill → MCP 工具 → 数据源/业务服务 → 主 Agent 汇总 → 对话与轨迹展示`。

## 2. 检测部门员工 Agent

### 2.1 主 Agent：员工工作助手 Agent

负责识别检测任务、质检、设备、个人统计和系统帮助意图；只访问当前员工可见的数据；多轮对话中保留任务上下文；将每次调用记录为 Turn、Call 和耗时；对写操作展示确认卡片。

### 2.2 专业 Agent

| Agent | 工作范围 | 典型问题 |
|---|---|---|
| 检测任务 Agent | 上传图片、创建检测任务、查询进度、查看结果图和缺陷证据、重试自己的失败任务 | “检测这张图片”“查看最近任务状态” |
| 质检复核 Agent | 查看待复核任务、确认缺陷、提交处置、发起返工和复检 | “有哪些待复核任务” |
| 设备采集 Agent | 查看绑定设备、在线状态、相机/PLC/采集状态和采集告警 | “我的设备是否在线” |
| 个人工作数据 Agent | 统计个人检测量、缺陷率、复核量、处理时长，生成图表和工作报告 | “生成本周工作报告” |

员工 Agent 禁止跨部门查询、修改模型配置、发布模型、查看其他员工隐私数据。

## 3. 检测部门主管 Agent

### 3.1 主 Agent：主管工作台 Agent

负责全局业务意图识别、部门范围权限校验、跨专业 Agent 编排、异常解释和管理决策摘要；支持按部门、区域、设备、人员、模型和时间范围过滤。

### 3.2 专业 Agent

| Agent | 工作范围 | 典型问题 |
|---|---|---|
| 检测质检管理 Agent | 全部门任务、缺陷、待复核、返工、复检、失败任务和质量闭环 | “统计本周返工原因” |
| 资源管理 Agent | 设备台账、人员信息、设备绑定、使用记录和维护记录 | “哪些设备长期离线” |
| 模型运营 Agent | 模型版本、评估指标、默认模型、灰度、A/B、发布和回滚 | “查看当前模型灰度状态” |
| 运营报表与工作分析 Agent | 部门趋势、人员工作量、设备利用率、模型表现、质量处置统计和报告导出 | “生成本月部门质量报告” |

主管写操作仍需确认，并记录操作者、影响范围、前后值和审计结果。

## 4. 工具集

### 4.1 员工工具

- 检测：`create_detection_task`、`get_my_detection_tasks`、`get_task_status`、`get_detection_result`、`get_result_image`、`retry_my_detection_task`
- 质检：`get_my_quality_queue`、`confirm_defect`、`submit_disposition`、`request_rework`、`request_reinspection`
- 设备：`get_my_devices`、`get_device_status`、`get_capture_alerts`
- 数据：`get_my_work_metrics`、`draw_my_work_chart`、`generate_my_work_report`、`export_my_work_report`

### 4.2 主管工具

- 检测质检：`search_detection_tasks`、`get_quality_queue`、`get_failure_statistics`、`get_rework_statistics`
- 资源：`list_devices`、`list_employees`、`get_device_bindings`、`get_device_usage_records`
- 模型：`list_models`、`get_model_metrics`、`get_release_status`、`publish_model`、`rollback_model`
- 报表运维：`draw_department_chart`、`generate_department_report`、`export_report`、`get_oss_health`、`get_kafka_health`、`get_worker_health`

所有工具统一返回 `data`、`source`、`traceId`、`status`、`error`，并支持超时、重试、幂等键和分页。

## 5. MCP 工具服务器

| MCP Server | 能力 | 安全约束 |
|---|---|---|
| MySQL MCP | 任务、人员、设备、模型、质检和统计查询 | 参数化 SQL；员工自动注入 `employee_id`；主管自动注入 `department_id`；默认只读 |
| Redis MCP | 会话、幂等键、任务锁、限流、短期指标缓存 | TTL、命名空间和锁续期；禁止返回密钥 |
| Kafka MCP | 创建任务、状态事件、失败重试和死信 Topic | 消息带 `event_id`；生产幂等；失败进入 DLQ |
| OSS MCP | 原图、结果 JSON、结果图、报告上传和签名 URL | 私有桶、最短有效期、路径按租户/部门隔离 |
| Mem0 MCP | 保存和检索用户偏好、任务上下文和工作记忆 | 按用户和部门隔离；敏感字段脱敏 |
| RAG MCP | 检索用户手册、业务规则、模型说明和 SOP | 返回引用来源和版本 |
| Chart MCP | 将结构化指标生成 ECharts/Vega-Lite 配置 | 只接收聚合数据；限制点数和查询范围 |
| Report MCP | 生成 Markdown/HTML/PDF/Excel 报告并上传 OSS | 模板版本化；记录生成者和数据快照 |
| Observability MCP | trace、Turn、Call、指标、日志和导出 | 全链路审计；禁止记录 API Key 和原图内容 |

## 6. Skills

员工主 Agent 使用：`intent-routing`、`employee-scope-check`、`detection-task-workflow`、`quality-review-workflow`、`device-status-query`、`safe-text-to-sql`、`chart-generation`、`personal-report-generation`、`trace-export`。

主管主 Agent 使用：`intent-routing`、`department-scope-check`、`detection-quality-analysis`、`resource-management`、`model-mlops`、`safe-text-to-sql`、`department-chart-generation`、`report-generation`、`ops-health-check`、`trace-export`。

Skill 必须声明输入 Schema、输出 Schema、权限范围、可调用 MCP、超时和失败策略。SQL Skill 只允许白名单字段和聚合查询，禁止拼接用户输入。

## 7. 工作数据与报告 Agent

这是每类角色的第四个专业 Agent。它先调用指标查询工具，再调用 Chart MCP 和 Report MCP，返回统一结构：

```json
{
  "type": "analytics-result",
  "title": "本周个人检测工作量",
  "summary": "完成 128 个任务，缺陷率 6.3%",
  "table": {"columns": ["日期", "任务数", "缺陷数"], "rows": []},
  "charts": [{"library": "echarts", "option": {}}],
  "report": {"format": "html", "ossUrl": ""},
  "source": ["mysql:detection_tasks"],
  "traceId": ""
}
```

前端使用 ECharts 或 Vega-Lite 绘制图表，Element Plus 展示表格；报告生成后上传 OSS，并在对话和轨迹页面提供下载链接。轨迹页应展示选中会话的完整历史，而非只展示一轮：顶部显示 Duration、Turns、Calls、Export；左侧显示 System、User、Context、Assistant、Tool；点击某个 Turn/Call 后，右侧显示 Summary、Payload、Result、Schema、Timing。

## 8. 开源方案调研与选型

- [Databao Agent](https://github.com/JetBrains/databao-agent)：Apache-2.0，支持自然语言转 SQL、MySQL、表格、Vega-Lite 交互图表和多轮追问，最适合作为工作数据 Agent 的查询与图表参考实现。
- [Lumen](https://github.com/holoviz/lumen)：BSD-3-Clause，支持 SQL、图表、仪表盘、报告、RAG 和自定义 Agent，适合作为独立报表服务或原型方案。
- [Insight Orchestra](https://github.com/laban254/insight-orchestra)：多 Agent 数据清洗、假设生成、辩论和 Plotly 可视化，适合参考分析编排流程。
- [nao](https://github.com/getnao/nao)：Apache-2.0，提供数据库无关的分析 Agent、上下文构建、可视化和透明推理，适合参考自托管分析架构。

建议优先复用 Databao 的安全查询和可视化思路，在现有 Spring Boot 服务中通过 Chart/Report MCP 接入；Lumen 作为后续独立报表服务备选。

## 9. 权限与确认矩阵

| 操作 | 员工 | 主管 | 是否确认 |
|---|---|---|---|
| 查询本人数据 | 允许 | 允许 | 否 |
| 查询部门数据 | 拒绝 | 允许 | 否 |
| 创建检测任务 | 允许 | 允许 | 是 |
| 提交质检处置 | 允许 | 允许 | 是 |
| 修改人员/设备绑定 | 拒绝 | 允许 | 是 |
| 发布或回滚模型 | 拒绝 | 允许 | 是 |
| 生成和导出报告 | 允许本人 | 允许部门 | 是（导出） |

## 10. 轨迹与可靠性

每次调用记录：`actor`、`role`、`mainAgent`、`agent`、`skill`、`mcpServer`、`tool`、`payload`、`result`、`status`、`startedAt`、`durationMs`、`traceId`。任务使用 Redis 分布式锁和幂等键；结果文件采用临时文件写入后原子改名；Kafka 配置最大重试次数、指数退避和死信 Topic；完成事件发送成功但 offset 提交失败时复用已存在结果。

## 11. 实施顺序

1. 固化角色、权限、Agent 和工具注册表。
2. 实现主 Agent 意图识别与专业 Agent 路由。
3. 接入 MySQL、Redis、Kafka、OSS、Mem0 MCP。
4. 实现 Chart/Report MCP 和 `analytics-result` 前端渲染。
5. 接入完整 trace、Turn、Call、Export 轨迹页。
6. 为写操作、重试、死信、锁和权限边界补充联调与审计验证。

## 12. Agent 注册配置

Agent 采用配置驱动注册，避免在业务代码中写死路由。每个 Agent 至少声明 `id`、`role`、`description`、`skills`、`tools`、`readScopes`、`writeScopes` 和 `confirmationRequired`。

```yaml
agents:
  - id: employee-main
    role: INSPECTOR
    skills: [intent-routing, employee-scope-check, trace-export]
    delegates: [detection-task, quality-review, device-status, personal-analytics]
  - id: supervisor-main
    role: SUPERVISOR
    skills: [intent-routing, department-scope-check, trace-export]
    delegates: [detection-quality, resource-management, model-ops, department-analytics]
```

主 Agent 只负责决策和编排，不能绕过专业 Agent 直接执行高风险写操作。专业 Agent 只能调用注册表中声明的 MCP 和工具。

## 13. 意图识别与工具调用协议

主 Agent 先输出结构化意图，再执行工具调用：

```json
{
  "intent": "PERSONAL_WORK_REPORT",
  "targetAgent": "personal-analytics",
  "entities": {"timeRange": "THIS_WEEK"},
  "operation": "READ",
  "requiresConfirmation": false,
  "traceId": "trace-uuid"
}
```

工具调用统一使用以下字段：

```json
{
  "tool": "get_my_work_metrics",
  "requestId": "request-uuid",
  "idempotencyKey": "user-task-operation",
  "actorId": "employee-001",
  "scope": {"departmentId": "D01", "employeeId": "E01"},
  "arguments": {"from": "2026-09-01", "to": "2026-09-07"}
}
```

工具返回失败时，Agent 应说明失败原因、是否自动重试、下一步建议和 `traceId`，不能用模拟数据伪装成功。

## 14. 导航与轨迹页面约束

左侧导航只展示模块概况和功能名称，不展示“全局态势”“待复核与处置闭环”等二级描述文案。Agent 智能系统下保留两个入口：`智能对话助手` 和 `Agent 调用链路`。

调用链路页面按会话展示完整历史。顶部统计 `Duration`、`Turns`、`Calls`，并提供 `Export`；左侧按时间列出 System、User、Context、Assistant、Tool 节点；点击任意 Turn 或 Call，右侧展示 `Summary`、`Payload`、`Result`、`Schema`、`Timing`。切换会话时只加载所选会话的轨迹，不能固定展示第一轮数据。

## 15. 联调验收标准

- 员工询问“我本周完成了多少检测”时，路由到个人工作数据 Agent，并返回表格或图表。
- 主管询问“本月部门缺陷率趋势”时，路由到运营报表 Agent，并应用部门范围过滤。
- “你是什么模型”等通用问题由主 Agent 直接回答，不调用设备或检测查询工具。
- 创建任务、提交处置、发布模型等写操作必须出现确认步骤。
- 重复消费同一事件不会重复创建任务或重复上传结果。
- Worker 崩溃、Kafka offset 提交失败、OSS 上传失败均可恢复，并在轨迹中显示重试和最终状态。
- 导出的轨迹包含完整会话的 Turns、Calls、Payload、Result 和耗时。
