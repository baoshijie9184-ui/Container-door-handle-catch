# Java 项目检测部门主管功能开发方案

## 1. 模块归属与边界

主管业务功能仍属于 `doorhandle-module-detection` 的 `supervisor` 子域；审批审计和角色配置依赖 `doorhandle-module-system` API；AI 主管 Agent 位于 `doorhandle-module-ai`。禁止把主管业务实现放入 `doorhandle-server`。

```text
com.ruanzhu.doorhandle.module.detection
├─ controller/supervisor
├─ service/supervisor
├─ dal/mapper/supervisor
├─ dal/dataobject/supervisor
├─ api/supervisor
└─ dto/supervisor
```

## 2. 业务功能

### 2.1 部门质量看板

- 部门/班组/设备/时间窗口维度的任务数、完成率、缺陷率、复核率和趋势。
- 支持下钻到已授权任务明细，导出前显示数据范围和脱敏提示。
- 指标固定统计口径和数据截止时间，避免 AI 或前端自行计算。

### 2.2 复核审批

- 查看待复核申请、证据图片、原始结果、员工意见和历史操作。
- 批准、驳回、退回补充材料；支持批量但必须预览影响范围。
- 乐观锁防止多人同时审批覆盖，审批完成后发送领域事件供通知/报告模块消费。

### 2.3 复检与报告发布

- 创建复检计划，分配授权人员、设备和优先级。
- 生成正式报告候选稿，比较草稿版本，检查未关闭风险。
- 发布前需要主管确认和质量签署权限；AI 只能提供建议和校验清单。

### 2.4 重复工单与待完成图片池

- 审核员工批次时按 SHA-256 聚合同一图片，A/B 批次重复时生成重复工单。
- 主管指定员工进行对比复核，核对两次检测时间、模型版本、缺陷框和置信度。
- 对比结果提交主管审批后选择主记录，保留所有来源及合并原因。
- 待完成图片按最多 5000 张生成工作单元，主管可派发，也可审批员工的检测申请。
- 工作单元支持回收、重新派发、部分完成和失败重试，重复图片不阻塞其他图片。

## 3. API 设计

接口前缀建议 `/api/detection/supervisor`：

```text
GET  /dashboard/summary
GET  /dashboard/trends
GET  /reviews/pending
GET  /reviews/{reviewId}
POST /reviews/{reviewId}/approve
POST /reviews/{reviewId}/reject
POST /reviews/batch-preview
POST /reinspection-plans
GET  /reports/candidates/{taskId}
POST /reports/{reportId}/publish-prepare
POST /reports/{reportId}/sign
```

写接口统一接收 `requestId、expectedVersion、confirmationToken`。返回审批编号、当前版本、审计编号和事件状态，不返回内部异常堆栈。

## 4. 角色与权限

建议权限码：

```text
detection:supervisor:dashboard:query
detection:supervisor:review:query
detection:supervisor:review:approve
detection:supervisor:review:reject
detection:supervisor:reinspection:create
detection:supervisor:report:prepare
detection:supervisor:report:sign
detection:supervisor:export
```

主管账号仍需绑定检测部门数据范围。`report:sign` 可单独设置为更高等级权限；两名及以上主管场景可配置会签策略（例如至少两人同意），不能用单个主管 Agent 绕过。

## 5. 数据模型、事件和事务

建议表：

- `detection_review_approval`：申请、审批人、动作、理由、版本和时间。
- `detection_reinspection_plan`：计划、任务范围、负责人、设备、状态和截止时间。
- `detection_quality_report`：报告候选稿、数据快照、版本、发布状态和签署信息。
- `detection_quality_report_sign`：签署人、签署顺序、签署时间和审计哈希。
- `detection_work_unit`：最多 5000 张图片的派发单元、负责人、进度和状态。
- `detection_work_unit_image`：工作单元与图片关系、占用状态和检测运行 ID。
- `detection_duplicate_ticket`：重复图片来源、对比负责人、处理结论和审批记录。

审批状态：`PENDING → APPROVED/REJECTED/RETURNED`；报告状态：`DRAFT → PREPARED → SIGNING → PUBLISHED/REVOKED`。状态转换必须由 Service 控制，禁止 Controller 直接修改状态字段。

领域事件建议：`detection.review.approved.v1`、`detection.review.rejected.v1`、`detection.reinspection.created.v1`、`detection.report.published.v1`。事件包含 `eventId、aggregateId、tenantId、occurredAt、operatorId、schemaVersion`，消费者按 `eventId` 幂等。

## 6. 主管 Agent 接入

`SupervisorDetectionApi` 向 AI 模块提供部门汇总、待审列表、复检创建和报告校验门面。AI Agent 只获得聚合数据和必要证据；审批/发布工具必须返回“建议”或进入确认流程，不能直接调用 Repository。工具调用和人工操作共用同一 Service、权限和事务，确保行为一致。

## 7. 并发、安全与审计

- 审批采用 `@Version` 或显式版本号；版本不一致返回业务错误 `REVIEW_VERSION_CONFLICT`。
- 批量审批先生成预览快照，确认后校验快照未过期。
- 导出默认脱敏并限制行数、频率和时间范围，记录下载审计。
- 报告签署使用服务端生成的确认令牌，不把签名凭据交给模型或浏览器。
- 所有主管操作记录 `tenantId、departmentId、operatorId、role、resourceIds、traceId、before/after 状态`。

## 8. 测试与验收

- 权限矩阵测试覆盖员工、主管、无权限、跨部门和会签未完成场景。
- 并发测试验证两个主管审批同一申请只有一个成功，另一个得到版本冲突。
- 事务测试验证审批、事件 outbox 和审计记录的一致性。
- Agent 测试验证主管 Agent 可读取部门聚合、不能调用系统管理工具；发布请求必须出现人工确认。
- 接口契约测试保证未来拆分检测服务后 DTO、事件版本和错误码兼容。
- 重复工单测试验证 SHA-256 精确去重、本地批次合并和 5000 张工作单元拆分。

完成标准：主管可以完成“部门看板→复核审批→创建复检→报告准备→会签发布”的闭环，普通员工不能访问主管接口，所有关键决定都保留可追溯的人工签署记录。
