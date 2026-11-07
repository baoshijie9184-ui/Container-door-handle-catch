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

组合字节包已在忽略目录中生成；截至本次记录尚未上传 ECS。Jenkins 沿用 `LEGACY_SOURCE_SNAPSHOT`，在同构建源码验证通过后上传两个私有文件，重新恢复并逐成员核对。上限为512 MiB原始内容、8192成员、16 MiB私有清单；公开归档仅含数量和摘要，不含原路径、SDDL或正文。当前Linux MCP安装、个人记忆/RAG在线合入与检索验收各有独立回执，不能用字节恢复回执替代。

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

## 阶段与产物

| 命令 | 位置与作用 | 完成证据 |
| --- | --- | --- |
| `snapshot` | 可在原文件所在工作站做纯字节操作；3 个源根必须显式指定并符合原清单，拒绝链接、变更、额外文件和错误时间 | owner-only `originals.tar`、`snapshot.json`，状态 COMPLETE |
| `snapshot-verify` | 流式验证归档每个成员及总摘要；指定 `--restore` 时只准 ECS 且只能恢复到全新私有目录 | SNAPSHOT_VERIFIED 或 RESTORED_VERIFIED、恢复文件逐个 SHA、原权限清单 |
| `export` | ECS 读取已恢复的个人 SQLite；仅接受能够独立证明全部原向量的 add-only 队列 | 32/33/26 私有 JSON、原向量和正文 SHA |
| `plan` | 无数据库操作，核对个人归属和隔离数 | 30 活跃、2 私档；history30/messages25 |
| `reembed` | ECS 使用已核实的目标 Mem0 provider；最多 30 条、每批 8 条、无自动重试；不运行提取 LLM | COMPLETE embedding journal、模型、维度、调用/用量记录、原/新向量 SHA |
| `merge` | ECS 离线完整 Mem0 卷副本，持有 writer.lock，加入缺少的旧 ID 和原生 history/messages | MERGED_VERIFIED，保留原 ECS 记忆、历史和生命周期/密钥状态 |
| `verify-bridge` | 候选实际运行后，只读测试认证、分页、正文/原时间、跨用户 404 和归档不可见 | BRIDGE_VERIFIED；无模型调用、无写入 |
| `rag-export` | ECS 从一次新的、已核实恢复副本读取 Chroma 的 83 条；Chroma 版本升级只影响可丢弃副本 | 独立 RAG 私档，含全部旧向量、source/title、原 archive/manifest SHA |
| `rag-plan` | 无数据库操作，检查每个 RAG ID 的处置与目标 ID | 活跃及私档数、完整映射 |
| `rag-reembed` | ECS 使用现有 Java source-file launcher 执行固定源码中的真实 `LocalTextEmbeddingService` | 绑定 Java 源码 SHA 的 COMPLETE 向量文件，无收费模型调用 |
| `rag-merge` | ECS 离线 Chroma 卷副本，禁止不同维度混合，加入无冲突的新 ID，保留已有内容 | MERGED_VERIFIED、oldId 映射、已有内容 SHA 和实际自检索 |
| `rag-verify-http` | 固定提交的应用完成启动及知识初始化后，读取真实 Chroma v2 HTTP API，再逐条检索 | RAG_HTTP_VERIFIED、正文/元数据/向量 SHA、原 ID 映射 |

原始 RAG 队列含多次更新，不能直接把第一条或最后一条队列记录当作每个活跃文档的正确向量。工具通过真实 Chroma 读取恢复副本，保全原 HNSW、SQLite、pickle 字节；不反序列化 pickle。

RAG 当前使用本地 hashing；Java 的 UTF-16 字符切片、Locale.ROOT 和 float 运算与 Python 并不完全相同。因此工具从固定提交的真实 Java 类生成仅移除 Spring/Lombok 外壳的独立源码，在 ECS 已有 JDK 运行，不仿写算法，不安装额外 JRE。Jenkins Python 工具容器可通过受制品清单约束的 Java wrapper 接入，环境变量为 `DOORHANDLE_MIGRATION_JAVA`。wrapper 必须支持 `java <source.java> <dimension>` 及 stdin/stdout，不泄露正文；底层 JDK 必须与应用 Java 17 相容。应用源码路径受限，SHA 必须等于私有 policy，维度和 local-hashing 名称必须来自当前目标运行配置。

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
  "restoreProofPath": "<当前完整卷恢复验证回执绝对路径>"
}
```

RAG 的 scope 改为 `rag-offline-candidate`。当前卷恢复回执必须真实取得，至少包含 `status=RESTORED_VERIFIED`、相同 `archiveSha256`、`identity={instanceId,machineId}`、`fullVolume=true`。工具会回读并核对实际备份文件 SHA；只有 marker 的声明不够。**完整当前卷冻结、备份、恢复演练、候选容器接线及切换仍需接入 Jenkins；此工具不会替外部步骤生成成功证明。**

候选合并前记录原云端每个 ID 的 SHA；同 ID 必须正文、元数据、向量完全相等，否则写入前失败。中断重入继续使用最初 baseline，不能重定义保全范围。Mem0 生命周期中已删除/排除的 ID 不自动复活。候选新增后必须再次逐 ID 读回并真实向量检索。

## ECS 验收和切换条件

`tests_python/test_legacy_store_migration.py` 提供 17 个测试方法，需要在 ECS 的现有 Chroma 环境执行。其中包含真实 Chroma 的 83 条导出、实际 Java Unicode 重嵌入和真实向量候选查询。Mem0 provider 的预算/断点测试使用合成替身，不调用收费服务；这些单元测试不替代真实桥接口或真实启动后的 HTTP 验收。当前仅完成源码 AST 静态检查，未运行这些测试。

Jenkins 还必须完成：固定提交构建、原始快照传输后 SHA 回读、当前卷冻结/完整备份与恢复、运行本文件测试、独立候选导入、实际候选服务启动、认证/角色与桥接口验证、应用启动后 RAG HTTP 验证、正式切换及恢复回执归档。生产门禁不得因源码齐备或单元测试通过而解锁。

尤其需要注意，`RagKnowledgeService` / `ChromaRagStoreService` 在应用启动时会按 source 删除再索引内置文档。离线合并成功不等于 83 条在启动后仍在；`rag-verify-http` 必须在该初始化完成后执行，缺少任何已准入 ID、原正文/元数据或新向量即失败。出现 source/ID 冲突应先审核知识来源或调整明确映射，不能用改 expectedCount 或删除源私档来通过。

本工具不验证工作区、uploads、模型、MySQL、Kafka、MCP journal 已齐全。这些仍须由各自的数据清单、目标路径和摘要回执核对。此前本地 uploads 的 6 个小文件尚未与云端逐路径比对；不能据此删除。所有私档/账号证明/provider 配置/bridge token 留在 Git 忽略的私有目录，不提交或作为公开 Jenkins 制品。测试结束按既有约定从流水线外停止 ECS 并回读 StopCharging，Jenkins 保持运行。
