# 智能助手 Chroma RAG 配置说明

系统智能助手已支持 ChromaDB 作为 RAG 向量检索库。启动后端时，系统会加载内置知识库和项目文档，生成本地文本向量，并尝试写入 Chroma collection。

当前链路已包含：

- 助手文档向量化：用户使用手册、智能助手 RAG 说明、Chroma 配置说明和 README 都会作为知识源。
- LLM 查询重写：用户原始问题会被改写成更适合检索的查询。
- Chroma 向量检索：优先使用 Chroma 查询候选片段。
- LLM rerank：对候选片段进行相关性重排。
- 自动回退：Chroma 或 LLM 不可用时回退本地关键词检索和原始顺序。

## 默认行为

默认配置：

```yaml
chat-assistant:
  rag-enabled: true
  rag-query-rewrite-enabled: true
  rag-rerank-enabled: true
  chroma-enabled: true
  chroma-base-url: http://localhost:8000
  chroma-tenant: default_tenant
  chroma-database: default_database
  chroma-collection: door_handle_assistant_knowledge
```

如果 Chroma 服务可用，智能助手会优先使用 Chroma 检索知识片段。

如果 Chroma 服务不可用，系统不会启动失败，会自动回退到本地关键词检索。

## 启动 ChromaDB

可使用 Docker 启动本地 Chroma：

```powershell
docker run -p 8000:8000 -v ${PWD}\chroma-data:/data chromadb/chroma
```

启动后，后端默认连接：

```text
http://localhost:8000
```

## 关键环境变量

```text
CHAT_ASSISTANT_CHROMA_ENABLED=true
CHAT_ASSISTANT_RAG_QUERY_REWRITE_ENABLED=true
CHAT_ASSISTANT_RAG_RERANK_ENABLED=true
CHAT_ASSISTANT_RAG_CANDIDATE_MULTIPLIER=3
CHAT_ASSISTANT_CHROMA_BASE_URL=http://localhost:8000
CHAT_ASSISTANT_CHROMA_TENANT=default_tenant
CHAT_ASSISTANT_CHROMA_DATABASE=default_database
CHAT_ASSISTANT_CHROMA_COLLECTION=door_handle_assistant_knowledge
CHAT_ASSISTANT_CHROMA_TOKEN=
CHAT_ASSISTANT_CHROMA_EMBEDDING_DIMENSION=256
```

## 知识来源

当前默认知识源：

```yaml
rag-sources:
  - classpath:rag/system-user-guide.md
  - classpath:rag/assistant-rag-guide.md
  - file:docs/system-user-guide.md
  - file:docs/chroma-rag-setup.md
  - file:README.md
```

如果要增加新的系统知识，可以新增 Markdown 文档，并加入 `rag-sources`。

## 检索链路

1. 后端启动时加载知识源。
2. 文档按标题和长度切分成知识片段。
3. 使用本地确定性文本 embedding 生成固定维度向量。
4. 将知识片段 upsert 到 Chroma collection。
5. 用户提问时，DeepSeek 先将原始问题改写为检索查询。
6. 系统使用重写后的查询生成向量，并从 Chroma 查询更多候选片段。
7. DeepSeek 对候选片段进行 rerank，选出最相关 TopK。
8. 将 rerank 后的片段注入智能助手 Agent 上下文。
9. Chroma 或 LLM 不可用时回退本地关键词检索和默认排序。

## 注意事项

- 当前 embedding 是轻量本地哈希向量，优点是无需外部 embedding API、部署简单、速度快。
- 查询重写和 rerank 依赖 DeepSeek；如果未配置 `DEEPSEEK_API_KEY`，系统会自动使用原始查询和默认排序。
- 如果后续需要更强语义召回，可以把 `LocalTextEmbeddingService` 替换为专用 embedding 模型服务。
- Chroma 只存放系统知识片段，不存放用户 SSH key、数据库密码或 Token。
- 智能助手已有敏感信息脱敏、请求限流和路径扫描白名单。
- 智能助手已加入防幻觉规则：没有系统数据或知识库依据时，应明确说明缺少依据，不得编造任务、工单、批次、模型、设备、人员或检测结论。
