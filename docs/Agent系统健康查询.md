# Agent 系统健康查询

更新：2026-10-16，分支 `java-cloud`。主管可在主站聊天或独立 AG-UI 中询问“检查系统健康”“数据库和 Redis 的探针状态是什么”。这是一项只读查询，结果由现有聊天回答与执行轨迹呈现。

## 工具与模块边界

主管的 `resource-management` 专业 Agent 新增 `get_system_health`，通过原主 Agent 委派执行。工具不接受参数，拒绝 `url`、`command`、`userId`、`force` 等字段；不允许选择任意探针、地址或运维命令。

AI 模块只依赖 contracts 中的 `SystemHealthReadApi`。App 模块已有 Spring Boot Actuator 与工业平台健康配置，在该模块实现健康读取门面，按需通过 `ObjectProvider<HealthEndpoint>` 获取现有端点。没有在 Server 中新增业务逻辑，没有跨模块访问实体或实现类，也没有新增依赖、数据库表或迁移。

App 门面在读取和缓存命中前都校验主管身份；员工工具目录不注册该查询，无法直接指定专业 Agent 绕过角色限制。主站和独立入口共用同一工具工厂。门面未装配时工具返回通用不可用错误，不回退旧聊天助手或编造健康状态。

## 固定检查范围

| 探针 ID | 读取来源 | 边界 |
| --- | --- | --- |
| `livenessState` | Actuator 存活状态 | 应用进程存活状态，不代表依赖均可用 |
| `readinessState` | Actuator 就绪状态 | 应用声明的就绪状态，不替代每项业务验收 |
| `diskSpace` | Actuator 磁盘探针 | 探针自身阈值判断，不返回磁盘路径或容量详情 |
| `db` | Actuator 数据源探针 | 数据源连接检查，不替代查询性能、权限或数据完整性验收 |
| `redis` | Actuator Redis 探针 | 未启用或未注册时明确返回未知 |

只读取上述组件路径，不读取根健康聚合中的所有组件。现有 `industrialPlatform` 指标包含启用配置、消费者组和存储路径，且其根状态固定为 UP；本工具不会把它当成 Kafka、Worker 或存储服务的实际可用证明，也不将其原始详情交给模型。

`notMonitored` 显式列出当前未提供实际探针的 Kafka、检测 Worker、Mem0、OSS、Higress、MCP 网关、Chroma、LLM 供应商。不会为验证这些服务而发起付费模型请求、SSH、Shell、Docker 或任意外网调用。

当前应用配置默认 `management.health.redis.enabled=${REDIS_HEALTH_ENABLED:false}`。关闭时 Redis 探针不出现会返回 `UNKNOWN/NOT_REGISTERED`，不能解释为 Redis 故障，也不能显示为健康；本轮不修改该开关或云端配置。

## 返回值与解释

工具成功返回 `status=OK` 仅表示查询完成，真实摘要位于 `data`：

- `status`：仅对固定五项探针结果汇总，按 DOWN、OUT_OF_SERVICE、UNKNOWN、UP 的优先级处理，不覆盖 `notMonitored`。
- `components`：固定探针 ID、规范状态和证据类型，不包含 details。
- `notMonitored`：当前未覆盖的服务标识。
- `checkedAt/expiresAt`：这一轮检查完成时间与缓存到期时间，使用带 UTC 标识的 Instant；不能把读取缓存的时刻当成重新检查时间。

证据类型 `ACTUATOR` 表示探针返回状态；未注册、读取失败、超时、繁忙和取消分别为 `NOT_REGISTERED/CHECK_FAILED/TIMED_OUT/BUSY/INTERRUPTED`，其状态统一为 UNKNOWN。未知自定义状态也映射为 UNKNOWN，不回显原始状态文案、异常、连接串、凭证、主机名、磁盘路径或其他 Actuator details。

即使五项状态均为 UP，也只能说明这些已监测项的检查结果，不能回答“所有中间件都正常”。健康检查结果不是根因诊断，也不证明后续检测、文件上传、事件投递或模型推理一定成功。

## 时限、缓存与资源

一次检查的同步等待总预算为 2 秒。独立固定线程池最多三个工作线程、三个排队任务；超时取消任务并清理队列，线程不随请求无限增长。并发主管读取合并为一次检查周期，摘要缓存 30 秒，缓存保留原检查与到期时间，不能请求强制刷新绕过限制。

底层 JDBC 或健康检查可能不响应中断；总等待超时不表示底层调用已终止。这些调用仍受到线程和队列上限约束，后续无法调度时显示 BUSY/UNKNOWN；应用关闭时关闭执行器，不宣称强制杀死底层连接。跨进程共享缓存、多实例协调及生产容量不在本轮完成范围。

## 权限、审计与交互

工具标记只读，只有主管能注册并调用。启用持久运行日志时，授权、工具调用状态、耗时和父子关联沿用当前中间件；授权审计失败阻止执行，不记录检查正文或用户问题。

本轮通过已有聊天回答和执行追溯使用，不新增修复按钮、资源控制入口或匿名诊断接口，不自动重启容器、修改配置或启动/停止 ECS。现有 Actuator HTTP 暴露与认证策略保持原状，不能把本工具的裁剪视为其他接口已完成脱敏审计。

## 开源与验证

开发前核对项目已用的 [Spring Boot 3.2.4 Actuator Health API](https://docs.spring.io/spring-boot/docs/3.2.4/actuator-api/htmlsingle/#health) 和 [Apache-2.0 许可证](https://github.com/spring-projects/spring-boot/blob/v3.2.4/LICENSE.txt)，并用本机已安装 Jar 核对 `HealthEndpoint.healthForPath` 接口；复用现有 AgentScope Java 工具实现，没有引入新监控平台或复制第三方代码。

测试使用真实 Actuator Endpoint 和注册的内存健康指标验证固定探针与详情裁剪；覆盖缺失/失败/未知状态、主管缓存与员工拒绝、并发读合并、慢且不响应中断的探针不突破总等待和线程上限。工具测试验证无参数输入、不可用门面和异常脱敏，真实 SDK Harness → 专业 Agent → 健康门面链路验证调用与摘要审计；不调用供应商或云端服务。

本轮完整 Maven `clean verify` 共 548 项：525 通过、23 项可选真实模型/业务 MySQL 联调跳过，0 失败/错误，13 个模块构建及后端打包成功。其中健康门面 6 项、健康工具 3 项均通过，日志 `work/system-health-full-verify.log`；`git diff --check` 通过。前端未因健康工具修改，本轮没有重复执行或声称完成健康功能的浏览器验收；上一轮模型卡片的 92 项 Node 检查、120 项浏览器检查和两套构建记录继续见对应文档。

真实 ECS 探针数据、故障注入、生产并发容量以及未覆盖服务的实际探针仍待验收或开发。本轮没有发布或修改云端资源。
