# Mem0 的 ECS 运行与迁移准备

当前单体通过 `Mem0Client` 访问本项目带专属认证、账号范围、摘要和写入回执的 Python 桥接；浏览器只访问 Java。运行和测试都在 ECS，由本地 Jenkins 调度，本地只编辑和构建。

向量统一方案见 [单体的统一向量存储](middleware/semantic-vector-storage.md)。源码默认接入 native Mem0 Qdrant provider，嵌入为独立凭据的 SiliconFlow `BAAI/bge-m3` / 1024；Mem0 提炼 LLM 仍由原有模型配置治理独立管理。不能用向量模型或 Java 主 Agent 模型覆盖 Mem0 LLM。

## 持久化边界

- Qdrant 保存派生的用户记忆向量和原 payload，和系统 RAG、用户知识、经验集合分开。
- `MEM0_DATA_DIR` 必须为 ECS 的绝对持久目录，保存 `history.db`、桥接回执、生命周期、重复复核和加密模型配置。
- OS 文件锁、单进程与 `--workers 1` 保持单写者；Qdrant 不替代 SQLite 历史，也不使历史自动具备集群高可用。
- `/data/vector-space.json` 绑定后端、集合和完整模型/存储身份。旧目录存在 history 或 Chroma 而没有新下限时，运行启动拒绝直接绑定空 Qdrant，必须先完成候选迁移证明。
- 不自动加载本机 `.env`，没有本机 Chroma/历史目录兜底。私有真实配置和凭据不能提交或归档。

## 必需配置由现有部署入口注入

| 配置 | 作用 |
| --- | --- |
| Java `mem0.service-url` / `MEM0_SERVICE_URL` | 现有 Python 私网桥接地址，运行使用 Compose 服务名/内网端点 |
| `MEM0_BRIDGE_TOKEN` | Java 与 Python 专属内部认证；不是浏览器公共 token |
| `MEM0_DATA_DIR` | ECS 历史、回执、配置持久目录，必填 |
| `MEM0_VECTOR_BACKEND=qdrant` | 固定新运行后端，旧 Chroma 只作为只读迁移输入 |
| `QDRANT_HOST/PORT/TLS/API_KEY_FILE` | 远程 Qdrant；密钥通过只读私有文件挂载，不使用嵌入式本机模式 |
| `MEM0_QDRANT_COLLECTION` | 已准入的记忆集合，默认 `doorhandle_memories_bge_m3_v1` |
| `MEM0_STORAGE_GENERATION` | 实际 profile 对应的存储代际，生产 BGE 为 `qdrant-bge-m3-v1` |
| `EMBEDDING_PROFILE/API_KEY_FILE/MODEL` | embedding 的独立身份、凭据与模型；不回退 LLM Key |
| `DASHSCOPE_API_KEY` / `MEM0_LLM_MODEL` | Mem0 LLM 的启动配置，后续沿用已有加密配置/撤销协议 |

受保护的 `POST /internal/embeddings` 与 Mem0 共用一个客户端和请求预算，供 Java 三类语义检索复用。内部凭据不能替代资料权限；Java 和 Mem0 查询都有当前账号/版本/生命周期复核。

## 候选迁移和放行

保留旧 32 条记忆及原生历史/消息、旧向量和 Chroma 原件。业务合入为 30 条记忆、30 条历史、25 条消息；2 条测试记忆、3 条历史、1 条消息归档。不能删除原件后再证明恢复。

迁移沿用仓库的来源封存、候选合入、独立恢复和真实桥接核验路径。目标先做模型空间准入，再做真实 BGE 原始/归一化向量证明、完整内容目录、SQLite 历史和回执恢复验证；既有记忆公有 ID、所有者、来源会话和历史 ID 不变。

隔离 app 验收使用 `explicit-openai-compatible` / `qdrant-explicit-test-v1` 和独立测试集合，不访问提供方；真实 BGE 数据另行验收。通过健康接口不能替代真实 30/25 历史核对和业务合入，生产门槛没有齐全时不启用切库或发布。

回滚必须同时满足桥接协议、模型配置格式和向量存储代际，见 [跨版本兼容保护](Mem0跨版本回滚兼容保护.md)。测试完成后保全报告、清理本轮拥有的隔离资源，再从 Jenkins 流水线外将 ECS 停到 `Stopped / StopCharging`；Jenkins 控制器保持运行，云盘存储仍计费。
