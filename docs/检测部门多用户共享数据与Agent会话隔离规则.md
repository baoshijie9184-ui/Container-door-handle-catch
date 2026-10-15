# 检测部门多用户共享数据与 Agent 会话隔离规则

> 2026-10-13 更新：本文的独立审批发布、公共记录及部门关系为规划。当前实施以用户选定的“员工本人及分派任务、主管全企业、私人 Agent 资源按账号隔离”为准，见 [多用户权限与数据范围方案](多用户权限与数据范围方案.md)。不能据本文尚未实现的公共记录方案授予员工读取他人任务的权限。

## 1. 采用的业务模型

当前项目只有一家公司，不需要先实现复杂的 SaaS 多租户。采用“单公司、多用户、部门数据范围、任务私有处理、主管审批发布、公共记录只读”的模型。数据库可以预留 `tenant_id`，当前固定为本公司 ID，为未来扩展多租户保留边界。

核心流程：

```text
员工创建任务 → 独立上传图片并检测 → 提交主管审批
        → 主管审批通过 → 发布为部门公共检测记录
        → 所有检测员工可查询，只有主管可修改
```

## 2. 任务和公共记录的可见性

- 员工只能处理自己创建的 `DRAFT/RUNNING/READY_FOR_REVIEW/RETURNED` 任务，员工 A 和 B 的任务相互隔离、互不覆盖。
- 提交审批前，任务、图片、模型输出和草稿结果仅创建员工与有权限的主管可见。
- 主管审批通过后，系统发布公共检测记录；所有检测部门员工可以查询、筛选、查看图片和统计，但不能编辑、删除或改变状态。
- 公共记录只允许主管部门修改；修改必须经过 RBAC、数据范围、乐观锁和审计。
- 驳回时任务进入 `RETURNED`，只有创建员工可以修改后重新提交；驳回内容不进入公共资源。
- 公共记录的范围是当前公司的检测部门；将来扩展多租户时改为 `tenant_id + department_id`。

批量检测增加预检查步骤：员工上传文件夹后，系统按图片指纹查询历史状态，员工选择 `UNDETECTED_ONLY`（仅检测未成功/失败图片）或 `ALL`（全部重新检测）。预检查只是提示，真正开始检测时必须重新校验状态和指纹；其他任务正在处理的图片不能被重复占用。

建议状态机：

```text
DRAFT → RUNNING → READY_FOR_REVIEW → APPROVED → PUBLIC
                         │
                         └──────────→ RETURNED → READY_FOR_REVIEW
```

`PUBLIC` 表示已发布可查询，不代表所有人可编辑。主管修改公共记录时生成新版本或修订记录，保留原审批快照。

## 3. 本地上传重复处理与 5000 张工作单元

本地电脑离线上传时，员工 A、B 可能在不知道对方已处理的情况下上传相同图片。进入主管审核池后，系统按图片 `SHA-256` 精确分组；必要时用 `pHash` 做疑似相似预警，但不能仅凭 pHash 自动判重。

发现重复后生成 `DUPLICATE_PENDING` 重复工单，记录重复图片的来源任务、员工、检测时间和模型版本。主管指定一名员工执行对比复核，完成后提交主管审批，选择主记录并合并关联记录；所有来源保留，不物理删除。

正常联网时，图片先进入中央 OSS 并登记指纹，使用 `tenant_id + sha256` 唯一约束和任务占用状态，领取任务时即可全局去重。员工也可以提交检测申请，由主管派发或审批后进入任务池。

待完成图片按最多 5000 张拆分为工作单元（`work_unit`）。工作单元可派发、领取、暂停、回收和重试；同一图片同一检测策略只能被一个活动工作单元占用。重复图片单独进入重复工单，不阻塞其他图片。进度分开统计：已完成、待复核、重复待处理、失败可重试。

## 4. 检测链路必须记录的字段

公共检测记录至少保存：

```text
public_record_id              公共记录 ID
task_id                       原检测任务 ID
image_id                      图片 ID
original_file_name            原始图片文件名
object_storage_key            对象存储 Key
creator_user_id               检测员工 ID
creator_user_name_snapshot    检测员工姓名快照
department_id                 检测部门 ID
model_id/model_version        使用的模型及版本
detection_started_at          检测开始时间
detection_time                检测完成时间
submitted_at                  提交审批时间
approved_by/approved_at       主管审批人和审批时间
published_at                  公共发布时间
version                       公共记录版本号
sha256                       图片内容指纹
detection_run_id             本次检测运行 ID
result_version               同一图片的结果版本
sha256                       图片内容指纹
detection_run_id             本次检测运行 ID
result_version               同一图片的结果版本
```

`creator_user_id` 用于真实关联，`creator_user_name_snapshot` 保存当时姓名，避免员工改名后历史记录无法追溯。原始图片和原始模型输出不可覆盖，只能新增修订或复核记录。

## 5. 员工 A/B 同时修改的处理

员工自己的检测任务可以并行处理，因为任务按创建者隔离。对同一任务内部的图片建议按 `image_id` 分片处理，避免两个操作覆盖同一图片结果。

公共记录和报告等可编辑聚合使用乐观锁：读取返回 `version=7`，更新必须携带 `expectedVersion=7`。数据库更新影响行数为 0 时返回 HTTP 409 `DATA_VERSION_CONFLICT`，前端重新加载最新版本并展示差异，用户确认后再次提交。

```sql
UPDATE detection_public_record
SET content = ?, version = version + 1, updated_by = ?, updated_at = NOW()
WHERE id = ? AND version = ? AND deleted = 0;
```

不建议使用“最后保存覆盖前面修改”。设备占用、审批最终提交等极少数短事务可以使用短时业务锁，但不在用户打开页面期间长期持有数据库锁。

## 5. 修改后的同步

业务更新采用：

```text
Service 事务更新 → Outbox 事件 → WebSocket/SSE/轮询通知 → 客户端重新查询最新版本
```

通知只发送 `resourceId、version、eventType`，前端收到后重新调用权限接口获取数据。Redis 可以做缓存和通知，但不能作为唯一数据源。事件按 `eventId` 幂等，失败进入重试/死信队列。

## 6. Agent 对话完全隔离

共享业务记录和 Agent 对话必须分开：

- 员工 A、B 可通过授权工具读取同一个 `PUBLIC` 检测记录。
- A、B 不能互相读取 Agent 消息、隐藏提示词、工具中间结果、未提交草稿和工作区文件。
- AI 生成内容只有在员工显式提交为复核意见或报告草稿后，才转为可授权的共享业务资源。

会话主键使用 `tenantId + userId + sessionId`，工作区目录使用：

```text
.agentscope/workspace/{tenantId}/{userId}/{sessionId}/
```

Redis 键建议：

```text
agent:session:{tenantId}:{userId}:{sessionId}
agent:message:{tenantId}:{userId}:{sessionId}:{messageId}
agent:run:{tenantId}:{userId}:{sessionId}:{runId}
```

`userId、tenantId、departmentId` 必须从 Spring Security 上下文生成，不能相信前端或模型传入的值。读取工作区前必须校验路径在当前用户目录内，拒绝绝对路径、`..`、符号链接逃逸、`.env` 和其他用户目录。

## 7. 最终权限规则

| 资源 | 普通员工（本人任务） | 普通员工（公共记录） | 主管 |
| --- | --- | --- | --- |
| 创建/处理检测任务 | 可操作 | 不适用 | 可按业务授权 |
| 查看未审批任务 | 仅创建者 | 不可见 | 可查看待审批 |
| 提交审批 | 可提交本人任务 | 不适用 | 不适用 |
| 查询审批通过记录 | 可查询部门公共记录 | 只读 | 可读写 |
| 修改公共记录 | 不允许 | 不允许 | 允许，版本控制 |
| 审批/驳回 | 不允许 | 不允许 | 允许，人工确认 |
| Agent 对话 | 仅本人 | 不共享 | 仅本人 |

这套规则适合当前单公司项目，也保留了未来增加多租户时所需的字段和模块边界。
