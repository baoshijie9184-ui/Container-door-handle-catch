# Kafka、OSS 与 Python Worker 异步检测

> 返回总览：[项目亮点与面试指南](../项目亮点与面试指南.md)

## 1. 架构目标

将 Web 请求、图片存储、模型推理和结果回写解耦，避免长耗时推理占用 Spring Boot 请求线程，并允许 Python Worker 独立部署和水平扩容。

### 1.1 为什么检测链路选择 Kafka，而不是 RPC

检测任务需要依次完成 OSS 下载、ONNX 推理、标注图与结果 JSON 生成、OSS 上传，可能持续数秒甚至更久。它属于耗时、可排队、允许异步返回的计算任务，而 RPC 更适合低延迟、调用方必须立即得到结果的同步操作。

| 对比项 | RPC 同步调用 | Kafka 异步消息 | 本项目收益 |
| --- | --- | --- | --- |
| 请求生命周期 | Spring Boot 持续等待工作进程 | 创建任务后立即返回任务编号 | 不长期占用 Web 请求线程和连接 |
| 工作进程故障 | 超时或连接异常直接导致调用失败 | 消息保留，恢复后继续消费 | 推理工作进程短暂故障不会直接丢失任务 |
| 流量高峰 | 请求直接冲击推理实例 | Kafka 暂存任务并按能力消费 | 批量任务削峰，形成背压缓冲 |
| 水平扩容 | 依赖服务发现与负载均衡 | 消费者组增加工作进程实例 | Python 推理服务可以独立扩容 |
| 失败恢复 | 调用方自行实现重试和去重 | 消息重投与手动提交消费位点 | 配合业务幂等实现至少一次处理 |
| 技术栈耦合 | Java 维护 RPC 客户端和服务地址 | Java/Python 只约定事件结构 | 两端独立开发、部署和升级 |

如果直接采用远程过程调用（RPC），调用超时后还可能无法判断工作进程是“没有执行”，还是“已经执行但响应丢失”，重试时仍然需要额外的任务编号和幂等机制。Kafka 将任务可靠地暂存在消息系统中，更符合检测业务的执行模型。

### 1.2 Kafka 与 RPC 的使用边界

Kafka 用于检测主链路的任务派发和结果回传；RPC 或 HTTP 更适合健康检查、配置查询、模型元数据读取等需要即时响应的操作。选择 Kafka 并不代表天然获得端到端只执行一次，本项目实际采用的是：

~~~text
Kafka 至少一次投递
        +
dispatchId 隔离旧派发
        +
eventId 拦截重复事件
        +
数据库事务与行锁
        =
最终业务状态幂等
~~~

### 1.3 术语、字段与状态翻译

| 英文术语或字段 | 中文名称 | 在本项目中的含义 |
| --- | --- | --- |
| Kafka | 分布式消息平台 | 持久化检测任务和完成事件，负责削峰与异步解耦 |
| RPC | 远程过程调用 | 像调用本地方法一样同步调用远程服务，本项目不用于检测主链路 |
| OSS | 对象存储服务 | 保存原图、标注图和检测结果文件 |
| Worker | 工作进程 | 独立运行的 Python 推理消费者 |
| ONNX | 开放神经网络交换格式 | Python 工作进程加载的跨框架模型格式 |
| Broker | 消息代理节点 | 接收、保存并投递 Kafka 消息的服务器 |
| Topic | 主题 | Kafka 中对消息进行分类的逻辑通道 |
| Consumer Group | 消费者组 | 多个工作进程共同分担同一主题中的任务 |
| Offset | 消费位点 | 记录消费者已经处理到哪一条消息 |
| taskId | 任务编号 | 标识整个检测任务，重试时保持不变 |
| dispatchId | 派发编号 | 标识某一次任务执行，防止旧结果覆盖新结果 |
| eventId | 事件编号 | 标识一条完成事件，防止同一消息被重复处理 |
| UPLOADING | 正在上传 | 任务已创建，等待原图上传完成 |
| PENDING_DETECTION | 等待检测 | 图片上传完成，等待工作进程执行推理 |
| COMPLETED | 已完成 | 所有图片检测成功 |
| PARTIAL_FAILED | 部分失败 | 部分图片失败，但保留已成功的结果 |
| FAILED | 失败 | 整个任务无法完成 |

## 2. 模块框架

~~~text
Vue 前端创建检测任务
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤一：Spring Boot 任务接入层                              │
│                                                              │
│  创建 detection_task，返回 taskId 与 OSS 预签名 URL          │
│  前端绕过后端，将原图直接上传 OSS                            │
└──────────────────────────┬───────────────────────────────────┘
                           │ 上传确认
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤二：Kafka 异步调度层                                    │
│                                                              │
│  Spring Boot → detection.task.created                        │
│  Kafka 持久化、削峰，并向工作进程组至少一次投递              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤三：Python ONNX 工作进程（Worker）推理层                │
│                                                              │
│  OSS 下载原图 → ONNX 推理 → OSS 上传标注图和结果 JSON        │
│  工作进程 → 检测完成事件（detection.task.finished）          │
└──────────────────────────┬───────────────────────────────────┘
                           │
                     完成事件发送成功？
                           │
                    ┌──────┴──────┐
                    │             │
                   否             是
                    │             │
                    ▼             ▼
             不提交创建消息位点    提交创建消息位点
                    │             │
                    └──────┬──────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤四：Spring Boot 结果落库层                              │
│                                                              │
│  dispatchId 拒绝旧派发，eventId 拒绝重复事件                 │
│  MySQL 保存状态、统计数据、OSS 结果地址和缺陷证据             │
└──────────────────────────────────────────────────────────────┘
~~~

## 3. 时序流程

~~~text
用户选择图片并点击“创建任务”
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤一：创建任务并上传原图（同步）                          │
│                                                              │
│  Vue → Spring Boot：POST /api/detection/tasks                │
│  Spring Boot → MySQL：保存 status=UPLOADING                  │
│  Spring Boot → Vue：返回 taskId + OSS 预签名 URL             │
│  Vue → OSS：直接上传图片                                     │
│  Vue → Spring Boot：POST /{taskId}/uploaded                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤二：派发检测任务（同步确认 + 异步执行）                 │
│                                                              │
│  MySQL：写入 dispatchId、flowStatus=PENDING_DETECTION        │
│  Kafka：发布 detection.task.created                          │
│  Spring Boot：等待 Kafka 消息代理节点确认                    │
│                                                              │
│  ✅ dispatchId 标识本次派发，旧结果不能覆盖新重试            │
└──────────────────────────┬───────────────────────────────────┘
                           │
                  Kafka 消息代理接收成功？
                           │
                    ┌──────┴──────┐
                    │             │
                   否             是
                    │             │
                    ▼             ▼
        记录发送失败并停止     Kafka 至少一次投递
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤三：Python 工作进程执行 ONNX 模型推理                   │
│                                                              │
│  从 OSS 下载原图 → ONNX 推理 → 生成标注图和结果 JSON         │
│  将标注图与结果 JSON 上传 OSS                                │
│  统计 successfulImages / failedImages                       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤四：可靠回传完成事件                                    │
│                                                              │
│  Kafka：发布 detection.task.finished                         │
│  等待 finished 事件发送成功                                  │
│  成功后提交创建消息的消费位点                                │
│                                                              │
│  ✅ 发送失败不提交消费位点，Kafka 后续可重新投递              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤五：后端幂等落库                                        │
│                                                              │
│  SELECT ... FOR UPDATE 锁定 detection_task                   │
│  校验 dispatchId：是否属于当前派发                           │
│  校验 eventId：是否已经处理                                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                   事件有效且未处理？
                           │
                    ┌──────┴──────┐
                    │             │
                   否             是
                    │             │
                    ▼             ▼
              忽略事件，不更新   写入 OSS 结果、统计和缺陷证据
                                  │
                                  ▼
                    COMPLETED / PARTIAL_FAILED / FAILED
                                  │
                                  ▼
                         前端轮询进度和结果
~~~

阅读时从上到下看五个步骤即可。两个分支分别说明 Kafka 发送确认和后端幂等校验；最关键的可靠性顺序是：工作进程先确认完成事件（`finished`）发送成功，再提交创建消息（`created`）的消费位点（Offset）。

## 4. 核心数据库字段

| 字段 | 含义 | 可靠性作用 |
| --- | --- | --- |
| task_id | 对外任务编号 | Kafka 消息 Key |
| workflow_uuid | 工作流编号 | Agent 与追溯引用 |
| status / stage | 执行状态 | 前端进度与重试判断 |
| dispatch_id | 当前派发标识 | 拒绝旧派发结果 |
| last_finished_event_id | 最后完成事件 | 重复事件幂等 |
| total_images | 总数 | 进度分母 |
| processed_images | 已处理数 | 进度 |
| successful_images | 成功数 | 部分失败保留 |
| failed_images | 失败数 | PARTIAL_FAILED 判断 |
| source_oss_prefix | 原图前缀 | Python 工作进程的输入位置 |
| result_oss_prefix | 结果前缀 | 结果定位 |
| result_json_oss_key | 结果 JSON | 完整结构化输出 |
| preview_image_keys_json | 标注图列表 | 前端预览 |
| error_message | 错误摘要 | 失败诊断 |

### 4.1 dispatchId：派发批次标识

`taskId` 标识整个检测任务，`dispatchId` 标识该任务的某一次执行。每次重新派发或重试时，系统为同一个 `taskId` 生成新的 `dispatchId`，并把它同时写入数据库和 Kafka 事件。

~~~text
第一次派发：taskId=TASK-1001，dispatchId=DISPATCH-A
        │
        ├── 工作进程 A 尚未返回
        │
        └── 任务重新派发
                │
                ▼
第二次派发：taskId=TASK-1001，dispatchId=DISPATCH-B
                │
                ▼
数据库当前 dispatchId = DISPATCH-B

工作进程 A 延迟返回第一次派发结果 DISPATCH-A
                │
                ▼
DISPATCH-A != DISPATCH-B → 旧派发结果，直接忽略
~~~

该字段解决“旧任务结果晚到并覆盖新重试结果”的问题。一个 `taskId` 可以对应多个 `dispatchId`，但只有数据库当前记录的派发标识有权更新任务。

### 4.2 eventId：事件唯一标识

工作进程（Worker）每次发布完成事件时生成唯一的事件编号（`eventId`）。Kafka 的至少一次语义意味着同一条事件可能被重复投递，因此后端处理成功后，将其记录在 `last_finished_event_id` 中。

~~~text
第一次收到 EVENT-9001
    → 保存检测结果
    → 更新任务状态
    → last_finished_event_id = EVENT-9001

再次收到 EVENT-9001
    → 已经处理过
    → 忽略，不重复写入结果和统计
~~~

该字段解决“同一完成事件重复消费”的问题，避免结果重复保存、统计重复累计以及后续动作重复触发。

### 4.3 三个标识的关系与校验顺序

| 标识 | 标识对象 | 生命周期 | 主要作用 |
| --- | --- | --- | --- |
| `taskId` | 一个检测任务 | 创建后保持不变 | 定位业务任务，也是 Kafka 消息 Key |
| `dispatchId` | 一次任务派发 | 每次重试重新生成 | 拒绝旧派发产生的过期结果 |
| `eventId` | 一条业务事件 | 每次发布事件生成 | 拒绝 Kafka 重复投递的同一事件 |

后端收到 `detection.task.finished` 后，必须按顺序校验：

~~~text
收到完成事件
        │
        ▼
根据 taskId 锁定 detection_task
        │
        ▼
dispatchId 与数据库当前值一致？ ──否──> 忽略旧派发
        │是
        ▼
eventId 等于 last_finished_event_id？ ──是──> 忽略重复事件
        │否
        ▼
保存结果 + 更新状态 + 记录 eventId
        │
        ▼
在同一个数据库事务中提交
~~~

先检查 `dispatchId` 是为了确认事件属于当前执行批次，再检查 `eventId` 是为了确认当前批次的这条事件尚未处理。两者解决的问题不同，不能互相替代。

## 5. 核心代码

### 5.1 OSS 预签名直传

~~~java
URL putUrl = ossStorageService.generatePutUrl(
        objectKey,
        contentType,
        Duration.ofMinutes(expireMinutes));
~~~

后端只生成限时 URL，不中转图片内容，降低 Java 服务的带宽、内存和线程压力。

### 5.2 Kafka 发送确认

~~~java
kafkaTemplate.send(topic, taskId, event)
        .get(sendTimeoutMs, TimeUnit.MILLISECONDS);
~~~

只有 Kafka 消息代理节点（Broker）确认发送成功后，业务才认为事件已经进入消息系统。

### 5.3 工作进程手动提交消费位点

文件：kafka_detection_worker.py

~~~python
producer.produce(
    topic=topic,
    key=key,
    value=payload,
    callback=delivery_callback,
)
remaining = producer.flush(timeout_seconds)
if remaining != 0 or delivery_error:
    raise RuntimeError("finished event delivery failed")
consumer.commit(message=source_message)
~~~

enable.auto.commit=false。结果事件发送失败时不提交 created 消息，Kafka 后续可以重新投递。

### 5.4 后端幂等

~~~java
boolean staleDispatch =
        StringUtils.hasText(task.getDispatchId())
        && !Objects.equals(task.getDispatchId(),
                event.getDispatchId());
boolean duplicateEvent =
        StringUtils.hasText(event.getEventId())
        && Objects.equals(task.getLastFinishedEventId(),
                event.getEventId());
if (staleDispatch || duplicateEvent) {
    return;
}
~~~

## 6. 故障场景

| 场景 | 处理 |
| --- | --- |
| 创建事件发送失败 | 不把任务错误标记为已派发 |
| 工作进程推理失败 | 生成“失败”或“部分失败”完成事件 |
| 结果事件发送失败 | 不提交创建消息的消费位点 |
| 工作进程重复消费 | 允许重复计算，后端保证结果幂等 |
| 任务重试后旧结果到达 | dispatchId 不匹配，直接忽略 |
| 相同完成事件重复投递 | eventId 等于 last_finished_event_id，忽略 |
| 单张图片失败 | 保留成功结果并标记 PARTIAL_FAILED |

## 7. 测试证据

- DetectionTaskEventPublisherTest：发送成功、超时和异常。
- DetectionTaskFinishedEventListenerTest：完成事件监听。
- DetectionTaskServiceImplTest：旧事件、重复事件和状态更新。
- tests_python/test_kafka_detection_worker.py：发送失败时不提交。
- tests_python/test_kafka_event_models.py：事件序列化和推理结果。

## 8. 面试问答

### Kafka 能保证只消费一次吗？

默认更接近至少一次。项目接受消息可能重复，通过 eventId、dispatchId 和数据库状态判断保证最终业务状态不被重复污染。

### 为什么先发布完成事件，再提交创建消息的消费位点？

如果先提交，之后 finished 发布失败，任务会永久缺失完成通知。当前顺序优先避免结果丢失。

### 重复消费会不会重复推理？

可能会，所以这是“最终状态幂等”，不是“计算只执行一次”。后续可结合结果对象存在性或分布式锁减少重复计算。
