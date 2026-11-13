# 旧 Chroma RAG 的来源保全

当前单体的向量运行方案为 [Qdrant + BGE-M3](middleware/semantic-vector-storage.md)。本页保留旧数据的识别与迁移要求；Chroma 不再是默认运行库，也不是 Qdrant 故障时的自动兜底。

旧系统集合通常为 `door_handle_assistant_knowledge`，tenant/database 为 `default_tenant` / `default_database`；使用 `doorhandle-local-hashing-v1`、256 维本地确定性向量。旧知识记录、原始文本、元数据、历史和向量都要保留在只读来源/归档中。

`LocalTextEmbeddingService`、`ChromaRagStoreService` 和旧 `RagPreservationManifest` 保留用于明确的旧来源核验及回归测试，不能把其通过结果当成 BGE-M3 的运行验收。默认 `chat-assistant.chroma-enabled=false`，不提供本机地址或自动探测本机库。

## 旧 83 条知识如何进入新目标

1. 通过既有迁移脚本在 ECS 读取已封存来源，核对完整原始目录、文本、元数据及原向量证据。
2. 按明确的系统公共知识归属策略生成目标文本；真实 BGE 重嵌入遵循已有免费调用授权和封闭资源边界。
3. 写入独立 Qdrant 目标，不改旧来源；保留原始 embedding 和第一次实际存储的归一化向量两份证明。
4. 对完整目录、ID、文本、元数据、权限范围和自检索逐条验证；独立空节点恢复后对照第一次存储指纹。
5. 生成新协议的私有、固定提交/SHA 绑定目标凭证，Java `PRESERVE_EXISTING` 只连接该经过核对的目标。

新目标凭证是 `schemaVersion=2`、`kind=QDRANT_RAG_TARGET`，不是修改旧 Chroma 凭证的模型名。不同维度不能拼接，不同模型的 1024 维向量也不能直接混用。

所有服务与测试在 ECS，由本地 Jenkins 编排；本地只编辑、编译、打包。生产启用仍须真实候选、恢复、业务与发布门槛全部满足。隔离 mock 集合只验证接入和授权行为，不构成 83 条真实数据已完成迁移的证据。
