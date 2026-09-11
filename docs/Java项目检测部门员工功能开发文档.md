# Java 项目检测部门普通员工功能开发方案

## 1. 模块归属

普通员工功能落在 `doorhandle-module-detection`，AI 辅助能力落在 `doorhandle-module-ai`；用户、角色、菜单和数据范围落在 `doorhandle-module-system`。`doorhandle-server` 仅引入模块和提供启动配置。

推荐包结构：

```text
com.ruanzhu.doorhandle.module.detection
├─ controller/employee
├─ service/employee
├─ dal/mapper/employee
├─ dal/dataobject/employee
├─ api/employee
├─ dto/employee
└─ convert/employee
```

AI 模块只依赖 detection 的 `api`/Facade，不引用 detection 的 Mapper、DO 或 Controller。

## 2. 业务功能

### 2.1 任务工作台

- 分页查看本人/本部门授权任务，按状态、日期、设备和批次筛选。
- 查看任务详情、图片数量、处理进度、失败原因和最近操作。
- 支持继续检测、取消本人未开始任务（若业务允许），不提供删除他人任务。

### 2.1.1 批量图片预检查与检测策略

员工上传文件夹后，系统先执行预检查，不立即启动模型。预检查按照“文件名 + 文件内容 SHA-256”建立图片指纹，返回本批次每张图片的历史状态：

```text
NEW                 从未检测
DETECTED            已有成功检测结果
RUNNING             其他任务正在检测
FAILED              上次检测失败，可重试
APPROVED_PUBLIC     已检测且已通过主管审批并发布公共记录
```

前端展示预检查汇总：总数、未检测数、已检测数、检测中数、失败数，并提供两种策略：

- `UNDETECTED_ONLY`：只提交 `NEW/FAILED` 图片；`DETECTED/APPROVED_PUBLIC` 跳过，`RUNNING` 提示稍后重试。
- `ALL`：本次批次全部提交检测，即使已有成功结果也重新检测；系统生成新的 `detection_run_id` 和结果版本，不覆盖历史结果。

员工确认策略后才创建检测子任务。预检查结果需要短时有效的 `precheck_token`，执行时服务端重新校验指纹和状态，防止预检查后文件被替换或被其他任务抢先处理。

建议接口：

```text
POST /api/detection/employee/batches/precheck
POST /api/detection/employee/batches/{batchId}/start
```

预检查响应示例：

```json
{
  "batchId": "batch-1001",
  "precheckToken": "短时令牌",
  "summary": {"total": 100, "new": 60, "detected": 35, "running": 3, "failed": 2},
  "items": [
    {"imageId": "img-1", "fileName": "A001.jpg", "sha256": "...", "status": "DETECTED", "lastRunId": "run-9"}
  ]
}
```

`ALL` 策略也必须保留历史结果，公共记录以 `image_id + detection_run_id + result_version` 区分；主管审批时明确审批的是哪一次运行结果。

### 2.2 结果查看与人工复核

- 查看缺陷汇总、单图结果、标注图和置信度。
- 对低置信度或疑似误检结果添加复核意见。
- 提交复核申请，支持幂等和附件引用；员工不能直接修改原始检测结果。

### 2.3 报告草稿与知识检索

- 生成个人报告草稿，保存草稿版本和引用任务。
- 检索检测标准、缺陷字典和操作手册，并展示文档版本。
- 草稿只能本人编辑，提交主管复核后变为只读快照。

### 2.4 待完成图片与工作单元

员工可以从“待完成图片池”提交检测申请，也可以领取主管派发的工作单元。一个工作单元最多 5000 张图片，员工只处理绑定给自己的图片。工作单元完成后提交主管审核；本地上传产生的重复图片由主管重复工单流程处理。

新增接口：

```text
POST /api/detection/employee/work-units/apply
GET  /api/detection/employee/work-units/pending
POST /api/detection/employee/work-units/{workUnitId}/submit
```

## 3. API 设计

建议接口前缀 `/api/detection/employee`：

```text
GET  /tasks
GET  /tasks/{taskId}
GET  /tasks/{taskId}/results
GET  /tasks/{taskId}/images/{imageId}/signed-url
POST /tasks/{taskId}/reviews
GET  /reviews/mine
POST /reports/drafts/generate
POST /reports/drafts
PUT  /reports/drafts/{draftId}
POST /reports/drafts/{draftId}/submit
GET  /knowledge/search
```

请求/响应使用 `*ReqVO/*RespVO` 或项目现有 DTO 规范；不得返回数据库实体。所有列表接口使用分页包装，详情接口返回 `taskId、tenantId、departmentId` 等审计所需字段但不暴露内部路径。

## 4. RBAC 与数据权限

建议菜单/权限码：

```text
detection:employee:task:query
detection:employee:result:query
detection:employee:review:submit
detection:employee:report:draft:read
detection:employee:report:draft:write
detection:employee:knowledge:search
```

Controller 使用 `@PreAuthorize`，Service 再执行 `EmployeeDataScope`：`tenantId` 必须匹配，任务的部门必须属于当前用户授权部门，草稿作者必须是当前用户。前端传入的 `userId/departmentId` 一律忽略，以安全上下文为准。

## 5. 数据模型和事务

建议新增或确认以下表（以现有数据库命名规则为准）：

- `detection_employee_review`：复核申请、任务/图片 ID、意见、状态、幂等键、审计字段。
- `detection_report_draft`：草稿版本、作者、任务快照、内容、提交状态。
- `detection_report_draft_revision`：草稿历史版本和变更摘要。
- `detection_image_fingerprint`：图片 ID、原文件名、SHA-256、文件大小、最近检测状态和最近运行 ID。
- `detection_run`：批次检测运行、创建者、检测策略（`UNDETECTED_ONLY/ALL`）、模型版本和状态。

图片指纹建议唯一约束 `tenant_id + sha256`；若业务明确保证文件名全局唯一，可额外建立 `tenant_id + original_file_name` 索引，但不能只依赖文件名判断文件内容是否相同。文件被替换时 SHA-256 改变，应视为新图片版本。

复核提交和草稿提交使用单模块事务；对象存储文件只保存签名引用，不把二进制写入事务表。复核创建使用唯一键 `tenant_id + request_id`，重复提交返回原结果。

## 6. Agent 工具接入

AI 模块通过 `DetectionEmployeeApi` 提供：`listTasks`、`getTaskDetail`、`getResultSummary`、`getResultItems`、`createReview`、`saveDraft`。API 接收 `EmployeeContext`，内部重新执行数据权限。工具层不得接受模型传来的身份字段，写工具需要 `confirmed=true` 和一次性确认令牌。

## 7. 测试与验收

- Controller 权限测试：无权限 403，跨部门资源 404/无数据，不能通过改 ID 越权。
- Service 测试：复核幂等、草稿版本冲突、签名 URL 过期、状态机非法转换。
- Agent 工具测试：普通员工白名单可调用，主管专用工具不可发现；敏感路径/API Key 被拦截。
- 集成测试覆盖 MySQL、Redis（如启用）、对象存储适配器和 AG-UI 会话隔离。

完成标准：员工可以完成“查询任务→查看结果→提交复核→生成草稿→提交主管”的闭环，且所有操作可由 `userId、taskId、traceId` 追溯。
