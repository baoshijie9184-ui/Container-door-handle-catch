# Python runtime telemetry

Detection Worker 和 Mem0 共用项目根目录的 `runtime_telemetry.py`。导入不启动 HTTP、线程或导出；由应用启动和关闭时管理生命周期。默认全部关闭，不改变已有业务可用性。

```python
from runtime_telemetry import RuntimeTelemetry

telemetry = RuntimeTelemetry.from_env("doorhandle-mem0", default_metrics_port=9465)
with telemetry.span("mem0.search", {"run.id": run_id, "owner.id": owner_id}) as span:
    result = existing_search()  # 不由遥测重试
    span.set_attributes({"result.count": len(result)})
telemetry.close(timeout_seconds=3)
```

## Dependencies and source closure

Python 3.12 环境固定为：

```text
opentelemetry-api==1.45.2
opentelemetry-sdk==1.45.2
opentelemetry-exporter-otlp-proto-http==1.45.2
prometheus-client==0.26.0
```

Worker 和 Mem0 镜像构建上下文均需包含 `runtime_telemetry.py`，不是只添加环境开关。OpenTelemetry 使用 Apache-2.0；Prometheus client 使用 Apache-2.0 AND BSD-2-Clause。保留安装包自带的许可证文件。版本/API依据：[OpenTelemetry 1.45.2](https://github.com/open-telemetry/opentelemetry-python/releases/tag/v1.45.2)、[官方 Prometheus client](https://pypi.org/project/prometheus-client/)。

## Explicit private configuration

| Variable | Meaning / default |
| --- | --- |
| `OTEL_ENABLED` | `false`；显式开启 traces |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | 完整的内部 HTTP(S) `/api/public/otel/v1/traces`；无默认 Collector |
| `LANGFUSE_PUBLIC_KEY_FILE` / `LANGFUSE_SECRET_KEY_FILE` | 挂载的私有密钥文件；不读明文凭据环境变量，不写入日志 |
| `TELEMETRY_ID_HMAC_KEY_FILE` | 至少 32 字节私钥；owner/session/user 先 HMAC；缺失则不导出这些标识 |
| `TELEMETRY_TRACE_SAMPLE_RATIO` | `1`；范围 0–1 |
| `TELEMETRY_MAX_PENDING_SPANS` | `256`；范围 8–4096，包含队列和正在导出的 span |
| `TELEMETRY_BATCH_SIZE` | `32`；1–pending 上限 |
| `TELEMETRY_BATCH_DELAY_MS` | `500`；100–10000 |
| `TELEMETRY_EXPORT_TIMEOUT_SECONDS` | `2`；0.1–5 秒；只限制遥测 HTTP，业务不等待导出 |
| `TELEMETRY_METRICS_ENABLED` | `false` |
| `TELEMETRY_METRICS_HOST` | `127.0.0.1`；仅私有/回环/容器内 `0.0.0.0` IPv4；容器不得发布到公网 |
| `TELEMETRY_METRICS_PORT` | Worker `9464`、Mem0 `9465`；1024–65535 |
| `TELEMETRY_METRICS_TOKEN_FILE` | 至少 24 字节机器 token；即使回环也必需 |
| `TELEMETRY_EVENTS_ENABLED` | 当 traces 或 metrics 开启时默认 `true`；安全结构化事件队列上限 128 |

Prometheus 仅抓取 `GET /metrics`，使用 `Authorization: Bearer <token>`，token 从私有文件提供。URL query token 不接受。不得将 metrics 端口映射为公共服务。缺依赖、无效配置和导出失败均记录固定 failure code，不打印原异常或凭据，不影响检测结果、Mem0结果或 readiness；上层部署验收须要求已启用端点和真实导出成功，不能以“业务仍健康”代替遥测接入验收。

OTLP 使用官方 HTTP/protobuf exporter，Basic public key / secret key 和 `x-langfuse-ingestion-version: 4`。参考：[Langfuse OTel 接入](https://langfuse.com/docs/opentelemetry/get-started)。此模块不负责启动 Langfuse；完整可选自建栈及资源门由部署配置负责。

## Data and execution boundaries

- span 名称有限白名单；未知名称变为 `runtime.operation`。attributes 只接收任务/分派/事件/run/model/config/SOP 版本等有界标识、计数、有限枚举及安全错误类名。owner/session/user 不导出原值。不得把用户名、邮箱等放入 run/task/version 字段。
- 不导出 prompt、回复、图像、OSS key、预签名 URL、工具参数、原始异常、堆栈和捕获信息。SDK span 在进入队列前再做白名单快照，删除全部事件、link attributes 和 status description；任意 `OTEL_RESOURCE_ATTRIBUTES` 不纳入本管道。
- SDK provider 为此 runtime 私有，不接管全局 provider。复用成熟 `BatchSpanProcessor`；非阻塞 admission 上限覆盖 queued + in-flight，因此满载直接丢弃并增加计数。网络失败只在后台处理。
- Kafka 输入只解析单个严格 W3C v00 `traceparent`；重复/非法 header、baggage 和 tracestate 不传播。默认开始独立异步 trace，以 `source.trace_id` 关联来源。仅受信内部调用显式 `trusted_parent=True` 才延续远端 trace。
- 检测消费、推理、发布分别形成 span。结果只新增 Kafka `traceparent` header；原有 JSON、receipt hash、执行栅栏、未知结果 reconciliation 和“先确认消息投递、后提交 offset”保持不变。
- 关闭停止 admission，并在默认 3 秒的有界预算内关闭自有服务器、导出和事件线程；超时只记录 `shutdown_timeout`，不阻塞业务无限退出。未导出的遥测可丢失，不承担业务审计和恢复职责。

## Metrics and unified ECS acceptance

| Metric | Labels / meaning |
| --- | --- |
| `doorhandle_runtime_ready` | 无动态 label；业务 runtime readiness，不是 exporter 健康 |
| `doorhandle_runtime_operations_total` | `operation,outcome`，均为固定枚举 |
| `doorhandle_runtime_operation_seconds` | `operation`，固定 histogram buckets |
| `doorhandle_telemetry_failures_total` | `reason` 固定枚举，例如 queue_full / export_failed / config_invalid |
| `doorhandle_telemetry_pending_spans` | 已接纳的 queued + in-flight 数量 |
| `doorhandle_telemetry_tracing_enabled` | exporter 已配置；**不代表真实导出已成功** |

Prometheus 不使用 task、run、trace、owner、session、模型动态 ID 作为 label。结构化事件仅含固定 service/operation/outcome 和 trace/span ID，异步有界队列输出。

固定应用提交`7cef3094`的#312已由本地Jenkins在ECS执行完整Python回归，其中`test_runtime_telemetry.py`的23项、真实Prometheus鉴权抓取1项全部通过，既有Worker golden/receipt及header/commit顺序测试随整轮通过。OTel使用真实SDK向测试专属HTTP接收端导出，覆盖脱敏、队列和故障隔离；不调用正式模型。原始报告已在#315完整补收，见[当前CI/CD回执](../本地Jenkins-CICD.md)。

用户已将完整Langfuse实际部署延后至资源审定。其真实trace查询仍留在后续完整栈验收，不能由上述SDK协议结果替代；当前不因此拉取或启动Langfuse。本地未运行任何测试。
