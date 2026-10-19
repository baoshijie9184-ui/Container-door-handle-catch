# AgentScope Responses I/O 兼容桥接

`doorhandle-module-ai/src/main/java/io/agentscope/extensions/model/openaiofficial/OpenAIResponsesIoBridge.java` 的模型请求部分改编自 Apache-2.0 许可的 AgentScope Java 2.0.4 `OpenAIResponsesChatModel.java`。保留原作者版权声明；许可证全文见项目根目录 `LICENSE`。

上游：[AgentScope Java](https://github.com/agentscope-ai/agentscope-java)，源码制品为 `io.agentscope:agentscope-extensions-model-openai-official:2.0.4:sources`。本次下载副本仅保存在项目 `work/upstream-agentscope-2.0.4/`，没有修改 Maven 缓存或覆盖上游类。

桥接复用原 SDK 的映射器、解析器、流组装器、异常翻译和重试策略，只把 Responses 的阻塞 I/O 放入独立的四线程、32 条等待上限的执行器。为访问这些包内辅助类，桥接有意位于 SDK 扩展包，使用新的类名，不替代原 SDK 类型。升级当前固定的 AgentScope 版本时必须重新检查其编译和行为兼容性。

取消时登记取消标记，迟到的回复直接关闭，迟到错误不再向已取消的订阅者发送。响应头返回前的 SDK 阻塞调用仍可能持续到自身请求超时；这段时间的供应商用量未知，不能解释为零或保证未计费。备用只重发尚未输出的模型请求，不重做 Agent 和业务工具。资源由模型服务关闭时释放；执行器容量不足按可切换的临时故障处理。

验证需包含原 Responses 工具往返、请求头与存储策略、余额不足、多备用，以及“主请求一直不返回响应头，备用先完成”的真实 SDK 本地 HTTP 场景。原失败回执不得以新结果覆盖。
