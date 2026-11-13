# 旧 Mem0 与 RAG 的保全、离线候选和验收

本页记录新增迁移工具的边界和准入条件，不代表已完成 ECS 导入、测试或线上切换。入口为 `script/memory/migrate_legacy_stores.py`，复用项目 2026-11-05 准备的 `migrate_legacy_mem0.py`，适配当前单体桥接口。所有数据库读取、向量重建、测试及运行均在已启动的 ECS，经本地 Jenkins 编排。工作站只编辑、构建，并可进行不打开数据库的逐字节快照与 SHA 核对。

## 必须保留的数据

当前依据是 Git 忽略的 `work/data-migration-20261105/mem0/legacy-inventory.json`。它是源清单，不是迁移完成回执。

| 类别 | 原始位置 | 文件 / 原始大小 | 内容及处置 |
| --- | --- | --- | --- |
| 个人记忆 | `memory_service/chroma_db` | 5 / 833,700 B | 32 条、1024 维，原始 SQLite、HNSW 和队列完整保留 |
| Mem0 历史 | `C:\Users\19771\.mem0\history.db` | 1 / 65,536 B | history 33、messages 26，全量私档；该目录属于全局 Mem0，不能推断所有行均属于本项目 |
| RAG | `work/middlewares/chroma` | 6 / 2,735,098 B | `door_handle_assistant_knowledge` 的 83 条、256 维，含源文档、source/title、全部旧索引文件 |

12 个原文件合计 **3,634,334 B**。工具完整保留原 SHA-256、文件相对路径、纳秒时间、POSIX mode/uid/gid；在 Windows 原地保全时另记录 NTFS SDDL。原权限以私有清单保留，恢复到 ECS 的访问权限统一限制为目录 0700、文件 0600，不把旧 Windows ACL 或外国属主授予 Linux 用户。空目录的原权限同样写入清单。

2026-11-07 增加可选的 `legacy-stores-with-windows-mcp-v1` 闭合保全 profile。原12文件的最小 profile 继续有效；组合 profile 只再接受已核对的 `.agentscope/workspace/users/18/mcp` 原件，5278文件、133,160,774 B。完整组合为5290文件、136,795,108 B，原12文件逐个 SHA 保持一致，旧快照不覆写。成员路径、数量、字节数和完整目录摘要均受核验，新增旁文件或任一内容变化都会拒绝，不按目录名字宽泛信任输入。原始程序只按字节私档恢复，不在 ECS 启动旧 Windows 环境。

后续新增 `legacy-stores-with-windows-mcp-and-kafka-v1`，再保全旧 Kafka 的 309 个原始文件、1,184,990,233 B。完整包为 5,599 文件、1,321,785,341 B；实际 gzip 归档 81,841,366 B，私有清单 6,112,609 B，保留全部原件，不启动旧 Windows 环境或重放 Kafka。

完整字节包已在忽略目录中生成；Jenkins #68 因源码测试失败，尚未进入上传阶段。Jenkins 沿用 `LEGACY_SOURCE_SNAPSHOT`，在同构建源码验证通过后上传两个私有文件，重新恢复并逐成员核对。原最小和 MCP profile 上限仍为 512 MiB 原始内容；包含 Kafka 的 profile 允许 2 GiB 逻辑内容、512 MiB 传输归档，成员上限 8,192、私有清单上限 16 MiB。资源准入按完整展开量、传输归档、清单及 2 GiB＋256 MiB 保底空间计算，不能只按压缩包大小估算。公开归档仅含数量和摘要，不含原路径、SDDL或正文。当前 Linux MCP 安装、个人记忆/RAG 在线合入与检索验收各有独立回执，不能用字节恢复回执替代。

本地完全清退还需补齐两类路径：一是后续 CI 直接引用已核验的 ECS 私有封存包并在服务器重新独立恢复，避免继续依赖本地业务包；二是完整包之外的历史模型、备份、日志和上传路径。已另行逐 SHA 盘点其中 36 文件、465,240,718 B，仍处于新增封存接线开发阶段。扩大文件名盘点还发现旧测试数据库、重复模型及归档候选，须继续按来源和摘要核实，不能把上述 36 文件视为项目全部剩余数据。无 ECS 恢复回执、实际业务检索或所需路径证明时，均不得宣称本地清退完成。

全局 `.mem0` 根中的 `config.json` 不在原业务清单内，可能包含供应商凭据。仅对 `legacy_history` 明确允许排除此名称，并在私有 manifest 记录理由、大小和流式 SHA；不解析、解码、输出或归档配置正文。任何新增数据库 sidecar（WAL/SHM）、其他额外文件、缺失文件、原 SHA 或原修改时间变化仍会阻止封存。

原文件参考 SHA-256：

- 个人 `chroma.sqlite3`：`0367802e259b90712aec1efac486eeb59f2b910f4dfa6d248a62c6bb84d22f2c`
- 全局 `history.db`：`8186b581830adf0d36cedc89baf6a9587f77073dcc578e77bd2ad97656351d60`
- RAG `chroma.sqlite3`：`dca48a4f7927c87a11a8eec11141b2a4a5dda2b654f18ce472f8256c36d13f8c`

既有 `private-legacy-export.json` 仅覆盖个人 32/33/26，不能替代 RAG 导出，也不能替代原始索引快照。旧 1024 维向量及 RAG 256 维向量均私档保全，不修改维度标志后混入不同的在线索引。

## 账号和项目归属

单体桥接口只接受 `doorhandlecatch:user:<正整数>`，不接受 tenant 前缀。沿用既有明确归属：旧 `admin` 23 条映射当前用户 1，旧 `doorhandlecatch:user:18` 7 条映射用户 18。旧 `integration-user` 的 2 条只归档。由这 30 条活跃记忆匹配的 history 30 行、已证明账号的 messages 25 行可进入候选；其余 history 3 行、message 1 行仍留在完整私档，不复活历史残留记录。

每个源账号都必须有明确 import/archive 决定及理由。旧调用代码的用户名传参、原账号证明和原始 source/agent 元数据是归属依据，不能通过新建测试账号接管未知记忆。实际导入前必须刷新当前 ECS 账号证明，绑定实例、machine-id、核实时间和清单 SHA；CLI 拒绝超过 2 小时的账号证明。

RAG 没有账号字段。83 条须逐 ID 明确 import/archive，并绑定固定集合、导出 SHA、项目归属证据、当前嵌入配置与应用提交号。带其他 agent 或 user_id 的记录拒绝作为全局项目知识导入。默认保持旧 ID；冲突时必须审核并提供显式 oldId → targetId 映射，不能覆盖 ECS 现有同 ID 内容。

## 当前 Qdrant 目标

四类数据使用独立集合：RAG `doorhandle_rag_bge_m3_v1`、受管知识 `doorhandle_knowledge_bge_m3_v1`、经验 `doorhandle_experience_bge_m3_v1`、个人 Mem0 `doorhandle_memories_bge_m3_v1`。统一固定 BGE-M3/1024、`utf8-newline-space-v1` 预处理和 `qdrant-bge-m3-v1` 存储代际。旧 Chroma、旧 256 维 hashing 和旧 1024 维向量只作恢复来源，必须保留，不因维度相同就视作同一模型。

Qdrant Cosine 会归一化向量。私档分别保留 provider 原始 FLOAT32 指纹和目标首次读回的 stored FLOAT32 指纹，先检查归一化后的数值一致，再用首存指纹严格检查重启与独立恢复；不能要求两种原始字节相等。逻辑 ID 不变，物理 UUID 使用 `doorhandle-vector-sha256-v8-v1`，按集合与逻辑 ID 派生。

history/messages、回执、生命周期和模型配置仍为单写者 SQLite；Qdrant 副本不会复制这份历史，也不新增业务 MySQL 表。

## 阶段与产物

| 命令 | 位置与作用 | 完成证据 |
| --- | --- | --- |
| `snapshot` | 可在原文件所在工作站做纯字节操作；3 个源根必须显式指定并符合原清单，拒绝链接、变更、额外文件和错误时间 | owner-only `originals.tar`、`snapshot.json`，状态 COMPLETE |
| `snapshot-verify` | 流式验证归档每个成员及总摘要；指定 `--restore` 时只准 ECS 且只能恢复到全新私有目录 | SNAPSHOT_VERIFIED 或 RESTORED_VERIFIED、恢复文件逐个 SHA、原权限清单 |
| `export` | ECS 读取已恢复的个人 SQLite；仅接受能够独立证明全部原向量的 add-only 队列 | 32/33/26 私有 JSON、原向量和正文 SHA |
| `plan` | 无数据库操作，核对个人归属和隔离数 | 30 活跃、2 私档；history30/messages25 |
| `reembed` | ECS 使用已核实的目标 Mem0 provider；最多 30 条、每批 8 条、无自动重试；不运行提取 LLM | COMPLETE embedding journal、模型、维度、调用/用量记录、原/新向量 SHA |
| `merge` | ECS 已准入私有候选，向明确远端 Qdrant 写入新 BGE 集合，合并原生 SQLite history/messages | MERGED_PENDING_INDEPENDENT_RECOVERY，不能发布；原 Chroma 和治理状态保留 |
| `verify-bridge` | 候选实际运行后，只读测试认证、分页、正文/原时间、跨用户 404 和归档不可见 | BRIDGE_VERIFIED；无模型调用、无写入 |
| `rag-export` | ECS 从一次新的、已核实恢复副本读取 Chroma 的 83 条；Chroma 版本升级只影响可丢弃副本 | 独立 RAG 私档，含全部旧向量、source/title、原 archive/manifest SHA |
| `rag-plan` | 无数据库操作，检查每个 RAG ID 的处置与目标 ID | 活跃及私档数、完整映射 |
| `rag-reembed` | `--provider-config` 指向私有、已核实的固定免费 BGE 配置，复用运行时嵌入传输，不调用 LLM | COMPLETE 原始 provider 向量证明，绑定源文本、policy、模型和 1024 维 |
| `rag-merge` | 向明确准入的远程 Qdrant 新集合写入稳定逻辑 ID，保留源文档 | MERGED_PENDING_INDEPENDENT_RECOVERY；schemaVersion=2 manifest 分开保存 raw/stored 证明 |
| `rag-verify-http` | `--qdrant-config` 明确远端与首次 stored catalogue，只读核对实际目标 | QDRANT_HTTP_READBACK_VERIFIED；不代替独立恢复或业务查询 |

原始 RAG 队列含多次更新，不能直接把第一条或最后一条队列记录当作每个活跃文档的正确向量。工具通过真实 Chroma 读取恢复副本，保全原 HNSW、SQLite、pickle 字节；不反序列化 pickle。

旧 Java hashing 包装器只保留用于核对旧索引，不再生成新运行目标。新 RAG 从原文重嵌入，严格限定 `https://api.siliconflow.cn/v1` 和 `BAAI/bge-m3`，不发送 `dimensions`，不使用 Pro 模型、收费回退或自动重试。

## 离线候选准入

`merge` 和 `rag-merge` 不创建或停止线上容器，也不自动切换数据卷。候选只能是当前云端完整数据卷冻结后的副本，不能直接指向 `/data` 或 Docker volumes。Mem0 必须连同 `bridge_receipts` 的生命周期、协议、密钥封装状态一起复制，不能只换 SQLite。

候选根目录须为当前执行用户所有且权限 0700，根内 `migration-candidate.json` 权限 0600，字段为：

```json
{
  "scope": "mem0-offline-candidate",
  "instanceId": "<准入实例>",
  "machineId": "<准入machine-id>",
  "sourceBundleSha256": "<对应私档JSON的规范化SHA256>",
  "sourceQuiesced": true,
  "sourceBackupPath": "<候选目录之外的完整当前卷备份绝对路径>",
  "sourceBackupSha256": "<备份SHA256>",
  "restoreProofPath": "<当前完整卷恢复验证回执绝对路径>",
  "qdrantConfigFile": "<候选目录外的私有远端连接文件绝对路径>"
}
```

RAG 的 scope 改为 `rag-offline-candidate`。当前卷恢复回执必须真实取得，至少包含 `status=RESTORED_VERIFIED`、相同 `archiveSha256`、`identity={instanceId,machineId}`、`fullVolume=true`。工具会回读并核对实际备份文件 SHA；只有 marker 的声明不够。**完整当前卷冻结、备份、恢复演练、候选容器接线及切换仍需接入 Jenkins；此工具不会替外部步骤生成成功证明。**

远端文件只含 `backend=qdrant`、`baseUrl`、`apiKeyFile`，密钥不能进入数据 payload。候选同 ID 正文、归属或历史冲突不覆盖；生命周期墓碑不自动复活。已有写入 receipt 的未知操作不重放，整轮重建使用新的受管候选并保留原输出。候选新增后必须逐 ID 读回并真实向量检索。

## ECS 验收和切换条件

本轮测试源码覆盖旧文件保全、账号/历史、模型拒绝、真实 ECS Qdrant 归一化读回，以及独立恢复和回滚门控。协议替身只证明守卫逻辑，不能记作真实引擎恢复。当前只完成静态检查，尚未统一运行；旧 Chroma 测试回执不作为新 Qdrant 通过证据。

Jenkins 还必须完成：固定提交构建、原始快照传输后 SHA 回读、当前卷冻结/完整备份与恢复、运行本文件测试、独立候选导入、实际候选服务启动、认证/角色与桥接口验证、应用启动后 RAG HTTP 验证、正式切换及恢复回执归档。生产门禁不得因源码齐备或单元测试通过而解锁。

隔离应用使用空的四个测试专属集合、内部 mock 嵌入与 `qdrant-explicit-test-v1`，不挂真实 BGE manifest。真实 83 条 RAG/30 条记忆在独立恢复的 BGE 桥接与 Qdrant 上验证，包括受保护共享 `/internal/embeddings`、实际来源检索和跨账号拒绝。回执明确 `verificationSubject=INDEPENDENT_REAL_BGE_CANDIDATE`、`appRuntimeValidationMode=ISOLATED_MOCK_QDRANT_RUNTIME`，不能互相替代。

完整候选链需要实际创建 Qdrant collection snapshot，在另一空节点恢复并逐点核对；停止候选写者后固定完整文件清单。正式切换再取得源卷新快照、停写且核对无漂移，从原始候选物化新正式卷，不发布测试卷或测试密钥。后端以固定提交及 SHA 绑定的 `QDRANT_RAG_TARGET` manifest 附着，核对原文、元数据、代际过滤数量与首存指纹，不执行启动清空重建。生产门禁默认关闭。

恢复使用 Qdrant 1.20 的 collection snapshot API、只读本地 `file://` 输入及 `priority=snapshot`；返回 checksum 时交由目标节点复核。目标必须是另一个空节点，避免 API 覆盖已有集合。[官方恢复 API](https://api.qdrant.tech/api-reference/snapshots/recover-from-snapshot)

本工具不验证工作区、uploads、模型、MySQL、Kafka、MCP journal 已齐全。这些仍须由各自的数据清单、目标路径和摘要回执核对。此前本地 uploads 的 6 个小文件尚未与云端逐路径比对；不能据此删除。所有私档/账号证明/provider 配置/bridge token 留在 Git 忽略的私有目录，不提交或作为公开 Jenkins 制品。测试结束按既有约定从流水线外停止 ECS 并回读 StopCharging，Jenkins 保持运行。
