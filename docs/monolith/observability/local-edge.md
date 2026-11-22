# 本机 Higress 和 OpenTelemetry

8080 由 Higress 接收 HTTP 流量。容器网络中的 Nginx 负责前端文件、OSS 上传代理和业务路由。Higress 控制台、Nginx 和 OTLP 接收端口都留在容器网络。单机镜像使用 Higress gateway 模式，关闭自带的指标和日志组件。

Higress 通过 OTLP gRPC 导出入口跨度。Java 和 Mem0 沿用既有 OTLP HTTP 埋点，经 Collector 转发到 Langfuse。HTTP 与排队的 Agent 输入之间只保存 W3C `traceparent`。工作台继续执行和专业 Agent 复用原任务的追踪上下文。请求头里的账号凭据、正文和完整 URL 不进入导出的跨度。Prometheus 从原有的业务和 Worker 指标端点采集数据。

## 单机部署与验收

在现有本机 Compose 启动器的参数末尾叠加 `deploy/compose/compose.local-edge.yml`。使用当前提交构建 Higress 与后端镜像并记录镜像摘要。将 Higress 镜像摘要设为 `LOCAL_HIGRESS_IMAGE`，将 Collector 镜像设为 `LOCAL_OTELCOL_IMAGE`。本机验收使用 Collector `0.144.0`，摘要为 `sha256:213886eb6407af91b87fa47551c3632be1a6419ff3a5114ef1e6fc364628496f`。将 `LOCAL_OTELCOL_ENV_FILE` 指向 Git 忽略的私有环境文件，文件内配置 `OTELCOL_LANGFUSE_AUTHORIZATION`，值为 `Basic` 加现有 Langfuse 项目密钥对的 Base64 编码。

先追加 `compose.local-edge-stage.yml`，保留现有 Nginx 入口。用 `LOCAL_HIGRESS_PORT` 指定临时验收端口，在同一个单体项目内更新 Collector、Nginx、Higress、后端和 Mem0。核对首屏、会话鉴权、HTTP 流式响应以及真实检测与 Agent 工具调用。到 Langfuse 查询同一个 trace ID 下的 Higress、业务 HTTP 和 Agent 模型、工具跨度。检查 Prometheus 的现有采集目标在线。通过后移除临时叠加层，重建内部 Nginx，释放宿主机 8080，再将 Higress 切换到 8080。所有容器继续使用原来的 Docker 网络和数据库。

回滚入口时停止 Higress，移除入口叠加层，使用原本机 Compose 和固定镜像恢复 Nginx、Java、Mem0。按 8080 首页和后端健康端点核对恢复结果，再停止 Collector。

参考 [Higress tracing 配置](https://higress.io/docs/latest/user/configmap/#tracing-配置说明)、[OTLP Receiver](https://github.com/open-telemetry/opentelemetry-collector/tree/main/receiver/otlpreceiver) 和 [Langfuse OTLP 接入](https://langfuse.com/docs/compatibility)。
