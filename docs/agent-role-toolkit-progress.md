# 两类角色 Agent / Toolkit 实施进度

更新：2026-09-12。本文记录代码已实现的范围，业务设计文档中的完整工具清单仍是后续目标。

## 第一阶段：角色入口与只读工具

- `employee-main` / `supervisor-main` 根据 Spring Security 的 `TenantPrincipal` 和 `ROLE_INSPECTOR` / `ROLE_SUPERVISOR` 选择。
- 兼容默认 `doorhandle-assistant` 入口，以及对应角色的 `employee-assistant` / `supervisor-assistant` 别名。员工指定主管 ID 会被拒绝；专业 Agent 不对外开放直接调用。
- 主 Agent 使用 HarnessAgent，四个委派工具调用各专业 ReActAgent；每次请求、每个专业 Agent 创建独立 Toolkit，身份通过服务端闭包传递。
- AI 模块只依赖 contracts 中的只读 API；检测、设备和模型模块实现门面，返回字段白名单 DTO，不暴露实体、内部路径或存储 Key。
- 使用 AgentScope AG-UI 扩展的请求处理器，由项目 Controller 在进入异步执行前完成鉴权。不再使用通用 AG-UI Starter Controller。

| 角色 | 专业 Agent | 已注册工具 |
| --- | --- | --- |
| 员工 | detection-task | get_my_detection_tasks、get_task_detail |
| 员工 | quality-review | get_my_quality_records、get_task_detail |
| 员工 | device-status | get_task_detail（仅任务记录中的设备名称） |
| 员工 | personal-analytics | get_my_work_metrics |
| 主管 | detection-quality | search_detection_tasks、get_task_detail、get_quality_records |
| 主管 | resource-management | list_devices |
| 主管 | model-ops | list_models |
| 主管 | department-analytics | get_department_work_metrics |

## 当前数据边界

员工任务查询在 SQL 中强制 `created_by = 当前登录用户名`。尚未接入分配给本人但由他人创建的任务、审批后公共记录等扩展可见范围。

现有用户和任务结构缺少完整的租户、部门以及用户与员工绑定关系；主管统计明确标识 `SINGLE_ENTERPRISE`，不可将它称作多租户或多部门隔离。员工设备 Agent 目前只能读取本人任务的设备名称，实时设备状态、本人绑定设备和采集告警尚待身份关联补齐。

质检工具返回有 review_status 的记录，包含历史记录，不能当作仅待办队列。统计工具返回指定创建时间窗口内的任务数、图片数、已处理图片数、缺陷数量；缺陷数量不等于缺陷图片数，不能直接计算不良率。

## 会话与前端

- `GET /agui/catalog` 返回当前身份可见的主 Agent 和专业能力。
- `POST /agui/run`、`POST /agui/run/{agentId}` 接收 AG-UI 文本消息。
- 会话与运行编号由服务端加用户命名空间；每轮新建 Agent，不共享模型历史。当前依赖前端提交最近对话，无重启后的服务端历史恢复。
- 拒绝客户端工具、状态、恢复指令、系统消息及工具消息。只读工具不提供写操作确认绕行入口。
- 同会话并发运行锁仅在本进程生效，尚无 Redis 分布式锁或跨重启幂等。
- 新前端携带 HttpOnly Cookie、复用会话编号并逐块解析正文事件；工具参数不混入回答。

## 待实施

1. 用户—员工—部门关系与公共记录授权，补齐员工实时设备和采集告警工具。
2. 上传、创建、重试、质检处置、主管审批：持久化确认动作、幂等键与版本校验后注册写工具。
3. 图表、报告生成与导出、RAG 和角色专用 Skills。
4. 服务端对话持久化、完整 Turn/Call 审计、跨实例并发控制及故障恢复。
5. 两类角色分别进行真实模型、数据库和浏览器端到端验收。

模型发布/回滚权限在原两份设计中有冲突，本阶段统一不注册这些写工具，不影响现有业务页面。

## 验证方式

```powershell
mvn -pl doorhandle-module-ai,doorhandle-module-detection -am test '-Dtest=RoleAgentFactoryTest,BusinessToolkitFactoryTest,AgentIdentityTest,RoleAgentControllerTest,DetectionAgentReadApiImplTest' '-Dsurefire.failIfNoSpecifiedTests=false'
mvn -pl doorhandle-server -am test -DskipTests
cd frontend-agent
node --test src/aguiClient.test.js
npm run build
```

自动化验证使用模型和业务门面的测试替身，不消耗真实模型额度；不能替代真实数据库和模型联调。

本轮验证结果：后端 14 项定向回归测试通过（包括主 Agent → 专业 Agent → Toolkit → 业务门面的完整调用，以及 MockMvc AG-UI 流式响应）；前端 2 项协议测试通过；Server 全模块编译与前端生产构建通过。前端构建仍有依赖包体积提示，尚未进行真实浏览器和数据库联调。
