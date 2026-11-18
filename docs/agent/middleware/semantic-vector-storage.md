# 单体的统一向量存储

本轮把系统 RAG、用户知识资料、Mem0 和已发布经验的派生向量统一接入 **Qdrant + BGE-M3 / 1024 维**。MySQL 中的 29 张业务表不增不减；`content_chunk` 继续保存可定位、可授权、可恢复的 SQL 文字段落，向量索引不能替代它。

源码接入与真实数据验收是两件事。实际投用以固定提交对应的本地 Jenkins → ECS 回执为准；本地不运行这些服务或测试。

## 四个集合分别授权

| 集合默认名 | 内容来源 | 查询前过滤与查询后复核 |
| --- | --- | --- |
| `doorhandle_rag_bge_m3_v1` | 系统公共说明、旧 83 条知识的已验证目标副本 | 系统范围、当前 generation、ACTIVE；保全启动核对完整目录与存储向量指纹 |
| `doorhandle_knowledge_bge_m3_v1` | MySQL 的当前知识资料版本及 `content_chunk` | 本人或企业可见；再从 SQL 读取当前版本、生命周期、文字及引用，不使用向量返回的正文冒充源资料 |
| `doorhandle_memories_bge_m3_v1` | Mem0 用户长期记忆 | 固定 user/app/session 预过滤；再次检查账号、生命周期、内容版本；公有记忆编号和历史编号保持不变 |
| `doorhandle_experience_bge_m3_v1` | 当前已审核、已发布且来源和规则评测有效的经验 | 当前角色、共享/私人来源；再核对发布指针、所有者、内容摘要、来源和评测 |

普通任务可语义召回少量经验；`/skills` 和明确的 `/skill` 仍使用完整的当前授权目录，不因语义 top-K 未命中而消失。召回不记为使用，只有实际 SDK 读取才产生使用记录。

所有集合都校验 profile、model、dimensions、preprocessing、storage generation、Cosine 距离和 ID protocol。未知或不同标记的既有集合即使维度相同也拒绝接入，不自动覆写、混用或切回 Chroma。

## 一份嵌入能力、独立的 Mem0 LLM

Java 通过现有 Mem0 内部桥接的 `POST /internal/embeddings` 获取向量，使用原有专属 token。它与 Mem0 共享同一个 `FreeBgeEmbedder`、OpenAI-compatible 客户端、零自动重试、单并发和每分钟请求上限；Java 不再保存另一份 embedding API Key 或选择付费兜底模型。

请求有明确的 `purpose`、账号、请求编号与输入边界。一次最多 64 条，每条最多 8000 UTF-8 字节；BGE 传输按每批最多 8 条执行。新内容先按 Unicode 码点无损切分，不截断原文；预处理仅将换行变为空格。提供方原始向量先完整校验，再写入目标。嵌入鉴权不允许读取其他业务数据。

Mem0 的提炼 LLM 仍由原有模型配置与凭据治理管理，和 embedding 的模型、额度、密钥互不替代。仅因为改用 Qdrant，不会更换该 LLM。

## SQL 文字就绪不等于向量就绪

`content_revision.index_state=READY` 仍表示 **SQL 文字段落已保存**。新增的向量就绪投影放入已有 `runtime_state` 的闭合命名空间 `SEMANTIC_INDEX`：

- 主键绑定内容种类、所有者与源编号，`current_ref` 绑定 `id@v版本`。
- CAS `revision` 防止旧任务把新版本误标为 READY。
- claim、完成和重新确认均在短 SQL 事务中调用内容所属模块的 source fence：锁定当前源，核对版本/发布指针、生命周期、摘要和权限范围，再更新投影。旧快照不能在新版本发布或归档后回写 READY；网络调用仍在事务之外。
- `payload_version=1` 的明确字段保存源版本、内容摘要、权限范围、集合及完整模型空间身份；不复制正文，不复用凭据摘要字段。
- 状态为 PENDING、INDEXING、READY、FAILED。后台每轮处理有限条目，写入与回读成功后才更新 READY；失败保留原文并重试。
- ACTIVE 资料没有实际 `content_chunk` 时标记 FAILED，不把“没有要写的向量”记作成功。历史或归档版本在读取接口显示 INACTIVE，不参与当前向量检索。
- 重新启动后会继续核对当前源；周期性真实回读也能发现向量卷丢失，不永久相信 SQL 中上一次的 READY。

网络与 embedding 调用不放在内容发布事务里。归档或更新后，即使旧向量尚未回收，也不能绕过 SQL 当前指针与授权复核。知识页面分别显示 SQL 文字状态和向量状态；向量不可用时可明确降级关键词检索，不显示向量验收通过。

## Qdrant 不替代 SQLite 历史

Mem0 使用 native Qdrant provider 和官方 Python SDK。自定义的 `LogicalQdrantStore` 只负责稳定 ID 兼容、账号分页及向量读取，不重写 Mem0 的提炼算法。

历史、写入回执、生命周期/重复复核、加密模型配置仍放在 ECS 的持久 `/data` 中，由已有操作系统文件锁、单进程、`--workers 1` 约束单写者。它们没有因为 Qdrant 而获得多节点历史高可用。

`/data/vector-space.json` 是独立于 memory protocol 的向量回滚下限。旧卷已有 history/Chroma 而没有该文件时，运行启动拒绝直接绑定一个空 Qdrant 集合；必须先走候选迁移与恢复验证。不得把旧 Chroma-only 镜像直接挂载到已启用新代际的数据上。

## 公有 ID 与实际向量证明

Qdrant 物理点使用 `doorhandle-vector-sha256-v8-v1`：对协议前缀、集合名、公有逻辑 ID 的分隔串取 SHA-256 前 16 字节，再设置 UUIDv8 和 RFC variant 位。这是自定义 UUIDv8 协议，不是标准 UUIDv5。原逻辑 ID 保留在 payload 中，并逐次核对物理/逻辑对应；Mem0 对外仍接受原来的 1–64 位字母、数字、下划线、连字符 ID。

Qdrant 的 Cosine 上传会归一化向量，因此分开保留：

1. 提供方原始 embedding 的 float32 little-endian 指纹及原始输入证据。
2. 首次实际存储后的归一化向量指纹，并检查归一化数值与源向量方向一致。
3. 重启和独立空节点恢复后，逐条对照首次存储指纹、ID、文本、元数据和完整集合目录。

不要求第 1 项与第 2 项字节摘要相同。旧 hash256 或其他 1024 维向量始终是独立只读来源，不能因维度相同直接标成 BGE。

## 验收分为隔离功能和真实数据两段

**隔离功能段**使用四个测试专属集合及 `explicit-openai-compatible` / `qdrant-explicit-test-v1`，LLM、embedding 是明确的 mock transport。它验证 native Qdrant、Java/Mem0 调用、授权、当前版本、生命周期、回执、重启和恢复，不消耗模型额度，也不充当 BGE 生产证明。

**真实候选段**保留原 Chroma、旧向量、83 条知识及 32 条记忆档案。只合入 30 条业务记忆、30 条历史和 25 条消息；2 条测试记忆、3 条历史、1 条消息单独归档。真实 BGE 重嵌入、原始/归一化证明、独立恢复和业务合入必须有独立回执；费用和调用授权不足时，不激活生产别名或切库。

本轮沿用用户已明确选择的免费 BGE 路线。2026-11-14 再次核对 [SiliconFlow 官方定价](https://www.siliconflow.cn/pricing)：精确 `BAAI/bge-m3` 仍标为免费，`Pro/BAAI/bge-m3` 为另一个收费模型。全部代码整合、构建后，真实候选只能在 Jenkins/ECS 的封闭阶段使用 `https://api.siliconflow.cn/v1` + `BAAI/bge-m3`、已有批准的凭据机制、零 SDK 重试；LLM 调用数必须为 0，禁止 Pro/付费回退。定价不构成免费限流、可用率或延迟保证。

主要配置由根 Compose/环境模板维护；Java 使用 `app.semantic.*`，桥接复用 `mem0.service-url` / `mem0.bridge-token`。Python 使用 `MEM0_VECTOR_BACKEND=qdrant`、`QDRANT_HOST/PORT/TLS/API_KEY_FILE`、`MEM0_QDRANT_COLLECTION`、`MEM0_STORAGE_GENERATION`。真实密钥和真实环境文件不入库、不归档。

### 源版本 fence 单独使用空 MySQL 验证

`script/jenkins/semantic-mysql-fixture.py` 为现有 `verify/source` 创建一次性的 MySQL，不先克隆旧 131 表或启动整库迁移。它只读取正式 Compose MySQL 的镜像 ID 与归属标签，复用 ECS 已有不可变镜像；不读取正式凭据，不连接或挂载正式库。实际启动必须是 MySQL 8.4.x。

测试服务器以 UID 1000、1 GiB 内存上限和只读根文件系统运行；数据目录在本轮 checkout 的 `work/semantic-mysql-fixture/data`，容器内外实际路径相同。随机非 3306 端口只发布到本机回环。随机密码通过私有文件传入，FeatureMySql 配置保持 0600，不进入命令行或公开制品。

Java 的 `CompactMySqlFixture` 在空库安装当前 29 表结构。流水线先显式执行 `QualityKnowledgeMySqlTest` 的 14 个真实 MySQL 用例，要求 XML 中无跳过、失败或错误，再执行不带 SQL 配置的普通源码回归。它验证当前版本与归档的并发 source fence、授权和空段落处理；该结果不替代旧数据迁移对账或真实 BGE 验证。

监督器先移除本轮测试工具容器，再停止该 MySQL。停止前后保留原始 inspect 和有界完整日志，确认容器已停止并移除、其他容器无祖先或子路径挂载引用、合成数据全部由 UID 1000 持有且无链接或特殊文件后，才清理本轮数据与密码。未知归属、UID 999 或仍有引用时保留数据并报告清理失败，不申请管理员递归删除。

## 复用与版本

- [Qdrant Java client 1.20.0](https://github.com/qdrant/java-client/tree/v1.20.0)、[Python client 1.20.0](https://pypi.org/project/qdrant-client/1.20.0/)，Apache-2.0；服务端匹配 1.20.0。
- [Mem0 native Qdrant provider](https://github.com/mem0ai/mem0/blob/v2.0.19/mem0/vector_stores/qdrant.py)，沿用项目固定 Mem0 2.0.19。新建 dense-only 集合，避免隐式下载 BM25/FastEmbed 模型。
- [BGE-M3 模型说明](https://huggingface.co/BAAI/bge-m3)，MIT，固定 dense 1024 维。
- [Qdrant 集合与 Cosine 归一化](https://qdrant.tech/documentation/manage-data/collections/)；旧数据通过独立目标和完整证明迁移，不能只替换容器名。
