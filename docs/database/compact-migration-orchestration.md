# 131 张源表到 29 张业务表的整库迁移与恢复

当前交付是迁移、恢复及验收入口源码。尚未在 ECS 执行本轮整库迁移、两份恢复和业务验收，不能据此打开生产发布门禁。正式切换由 [部署协议](compact-deployment.md) 中的本地 Jenkins 流水线负责；本文件的 CLI 不切换应用连接、不启动应用、不管理 ECS 启停。

## 入口与范围

`script/schema/migrate_compact.py` 提供 `observe`、`migrate`、`verify` 三个阶段。`script/schema/restore_compact.py` 提供单独的备份恢复验证。共享实现为 `script/schema/compact_migration_runtime.py`，Workbench 的受控 Java 入口为 `CompactWorkbenchMigrationCli`，实际调用现有 `WorkbenchLegacyMigration.copy` 和 `verifyCommitted`。

源表全集来自 `compact-schema-contract.json` 的 131 张表；目标必须是契约规定的 29 张 InnoDB 实体表，没有兼容视图。复制计划核对当前目录中每一个 SQL 文件及其 SHA，拒绝缺段、额外段、依赖环、未知占位符和未覆盖的源表。源库还必须实际具有精确的 131 张表，并且不能是没有业务记录的空库。

执行顺序由生产者依赖决定。`12-chat-and-fingerprints.sql` 先复制项目、消息和图像指纹；`43-workspace.sql` 生产完整会话后，才运行 `24-chat-evidence.sql`。Workbench 在会话、运行、模型及 SDK checkpoint 已就绪后调用 Java，立即核对已提交结果；之后才运行依赖它的报告、上下文和 MCP。`49-digests.sql` 复制 V65 的五张日报表，`50-owner-locks.sql` 复制研究与技能下载 owner 锁。计划覆盖数是实际输入关系集合校验，不是仅填写一份映射清单。

## ECS、连接与私有配置

所有命令只能在已启动的单体 ECS `i-2zeieuov2aum486jm1ek` 上运行，实际 IMDS 身份及 `/etc/machine-id` 都须与私有配置、执行环境匹配。本地仅编辑和构建。ECS 未就绪时直接失败，不转本地运行，不在这些脚本中启动或停止实例。

私有 JSON 必须为本 checkout 的 `work` 内规范绝对路径、当前 Unix 用户所有且权限 0600。输出目录必须全新。配置没有环境变量中的数据库默认值，不读取旧本机连接。

| 字段 | 要求 |
| --- | --- |
| `version` | 整数 `1` |
| `scope` | `production-migration` 或 `ecs-disposable-migration` |
| `instanceId`、`machineId` | 实际 ECS 固定身份 |
| `serverUuid`、`sourceSchema` | 已复核的实际 MySQL 8.4 UUID 与旧库名 |
| `targetSchema` | 全新 `doorhandle_compact_candidate_<10位hex>`，与旧库不同 |
| `connection` | 明确的 `host`、`port`、`username`、`password` |
| `client` | 现有原生客户端或精确的现有 Docker MySQL 容器 |
| `sourceOffsets` | 每个复制域已复核的历史固定 UTC 偏移 |
| `sourceCollations` | 全部 131 张实际源表的完整 `table → collation` |
| `workbench` | 已构建候选 BootJar 和 SHA、已有 Java 17 可执行文件 |
| `recoverySchemas` | 两个全新的源库和目标库恢复证明 schema |
| `reviewedSourceSnapshot`、`reviewedSourceSnapshotSha256` | `observe` 输出的私有观察文件及实际文件 SHA；`migrate` 必填 |

生产容器连接采用 `client={"kind":"docker","executable":"<规范绝对路径docker>","containerId":"<完整64位容器ID>"}`。Python 从该容器内的客户端执行 SQL；Java 使用同一已核对容器的私有 bridge IP 和 3306。两端分别核对容器身份、运行状态、实际 server UUID；不重建 MySQL、不发布公网端口。生产也可以使用原容器已有的本机 loopback 映射。

原生方式为 `client={"kind":"native","executable":"<规范绝对路径mysql>","mysqldump":"<规范绝对路径mysqldump>"}`，仅允许 ECS 本机 loopback。密码只进入 owner-only 配置或通过 stdin 写入容器临时 owner-only options 文件，不进入命令参数或公开日志。

隔离验收 scope 还要求源名 `doorhandle_migration_verify_<10位hex>`、`doorhandle_legacy_verify_<10位hex>` 或 `doorhandle_agent_verify_<10位hex>`、非 3306 的明确 loopback 端口，以及 `dataDirectory` 真实位于配置同目录以下。Docker 的 `3306/tcp` 必须精确映射该 loopback 端口，`/var/lib/mysql` 必须 RW bind 到该私有目录，实际 `@@datadir` 和 UUID 也须一致。原生夹具同样核对实际数据目录。隔离证明不能当作生产迁移证明。

`workbench` 配置为 `{"java":"<已有Java17规范绝对路径>","applicationJar":"<候选jar绝对路径>","applicationJarSha256":"<64位SHA>"}`。通过 Boot `PropertiesLauncher` 运行受控 helper，不启动 Spring 应用。仅隔离源码验证可显式提供完整 `classpath` 数组；不会从环境猜测 classpath。迁移账号须对源库有直接 schema 的 `SELECT`、`TRIGGER`、`LOCK TABLES` 授权，对三个新 schema 有建表、复制和恢复所需权限；不需要源库 DML 授权。

`recoverySchemas` 分别为 `source: doorhandle_legacy_restore_<10位hex>`、`target: doorhandle_compact_restore_<10位hex>`，与源、候选互不相同。即使为空，任何已存在目标或恢复 schema 也会被拒绝，不覆盖未知结果。

## 历史时区与停写证明

`sourceOffsets` 必须包含 action、agent、binding、chat、context、detection、digest、export、identity、inbox、infra_log、mcp、memory、model、model_file、model_log、operations、report、research、sdk、skill、workspace、workbench。偏移来源是原字段历史约定与已审阅部署资料，不能用当前 MySQL 会话时区推断。V65 日报的原 DATETIME 明确为 UTC，因此 `digest` 只能为 `+00:00`；报表日历及 cron 的业务时区仍是 Asia/Shanghai。

生产配置额外包含 `freezeEvidenceFile`、`freezeEvidenceSha256`。私有文件须为：

```json
{
  "schemaVersion": 1,
  "kind": "doorhandle-source-writer-freeze",
  "ecs": {"instanceId": "<实际实例>", "machineId": "<实际机器ID>"},
  "serverUuid": "<实际MySQL UUID>",
  "sourceSchema": "<实际旧库>",
  "writerContainers": ["<所有旧writer与入口的完整容器ID>"],
  "sourceAccounts": [{"user": "<旧运行账号>", "host": "<对应Host>", "locked": "Y"}],
  "eventCatalog": [],
  "eventCatalogSha256": "<完整事件目录canonical JSON SHA>",
  "routineCatalog": [],
  "routineCatalogSha256": "<完整存储过程和函数目录canonical JSON SHA>"
}
```

此模板不能直接执行。首切 helper 用现有管理连接读取完整事件及存储过程/函数目录、锁定原运行账号，并在每阶段独立回读；受限迁移账号看不到元数据时返回的零行不构成无对象证明。CLI 校验完整目录结构、目录 SHA、账号锁证明与冻结文件 SHA，并逐一独立 inspect 所有 writer 都已停止且重启策略为 `no`。本入口支持表与触发器恢复，源 SQL event 和 routine 目录必须实际为空；即使发现 DISABLED event 也停止，须另行完成相应恢复设计，不能悄悄遗漏。隔离夹具须有显式 source EVENT、EXECUTE 元数据可见授权才能独立核对目录，不向生产迁移账号添加这两项权限。

迁移期间另由独立长连接持有全部 131 张源表的 `LOCK TABLES ... READ`。各 copy 段、Java helper 和 dump 使用其他连接，避免段内 `START TRANSACTION` 释放源锁。每段前及最终验证检查该锁连接仍存活。会话中的 `@compact_*_source_frozen=1` 只传递已成立的冻结状态，不作为停写证据。

## 实际执行阶段

以下为 ECS 上的阶段命令，正式执行由 Jenkins 调度；示例路径需换成该固定提交 checkout 的真实绝对路径。

```bash
python3 -B script/schema/migrate_compact.py observe \
  --config /ecs/checkout/work/attempt/config.json \
  --output /ecs/checkout/work/attempt/observe

# 将 observe/source-observation.json 的规范路径和实际文件 SHA 写入私有配置。
python3 -B script/schema/migrate_compact.py migrate \
  --config /ecs/checkout/work/attempt/config.json \
  --output /ecs/checkout/work/attempt/migrate

python3 -B script/schema/migrate_compact.py verify \
  --config /ecs/checkout/work/attempt/config.json \
  --receipt /ecs/checkout/work/attempt/migrate/migration-receipt.json \
  --output /ecs/checkout/work/attempt/readback
```

`observe` 在冻结源锁内读取所有表、所有列、原 NULL、微秒时间、原密文/文本字节、索引、完整 DDL 和 AUTO_INCREMENT，生成逐行 SHA 链及完整源快照。`migrate` 再次读取并要求与已复核观察完全一致，保存可恢复源备份后创建候选，先装表及完整保护触发器，再按依赖实际运行全部 SQL 和 Workbench Java。外键统一延后到所有领域复制结束添加，逐条实际校验；始终保持 `FOREIGN_KEY_CHECKS=1`，孤儿会阻止完成。

V65 日报固定保存 run 原 15 字段、command 原 5 字段和 audit 全部原 detail JSON 文本。原 snapshot JSON 和 SHA、原 request SHA 均保留；NULL 发生时间不使用导入时间替代，源微秒直接保留。新的 typed payload 只供新协议读取，不能替代完整原记录。已结束运行残留 claim/lease 留在原记录证据中；RUNNING 的有效 claim/lease 同时复制到当前协议字段。源全部高水位前后对账，相关目标序列也保留历史上界。

复制后的候选完整快照与私有备份形成 `migration-evidence.json`（COPY_VERIFIED）。程序随后**实际恢复源 131 表和目标 29 表**到两个新 schema，核对所有行/列/键/DDL/NULL/微秒/原值/高水位，及包含触发器的 metadata。恢复时剥离 dump 的 SET boilerplate，只执行已核对的完整 INSERT，绝不执行 dump 中的外键或唯一约束禁用指令。源有其他 DEFINER 的触发器时，观察阶段即要求明确已复核的 `SET_ANY_DEFINER`（或 SUPER）及 SYSTEM_USER 权限，否则停止；程序不会提升权限。

当前按已审阅历史规模设置有界入口：Workbench 单表不超过 50,000 行且文本总量不超过 64 MiB，identity、digest 等段也有显式行数与聚合字节门禁；私有数据 dump 以 4 GiB 为上限并逐块检查剩余磁盘。超限或长时间无响应时停止，保留源和私有诊断，必须先扩展已审阅的流式方案，不能截断数据、只迁移前一批或报告成功。

只有两次恢复成功、原源及候选均未变化、冻结证据仍成立、锁连接成功结束后，才原子产生最终 `migration-receipt.json`（VERIFIED）。数据快照 SHA 用于首次切换及恢复；独立 `targetMetadataSha256` 与部署 guard 共用同一算法，后续正常业务写入不会被误判为结构升级失败。

## 回执、恢复与未知结果

最终回执包含 ECS/UUID/schema、固定契约及 SQL SHA、复制计划及逐段结果、源/目标完整快照、冻结证据 SHA、`foreignKeysValidated`，以及 `evidence` 与两份 `recovery` 的相对文件名和 SHA。恢复证明绑定不可变 COPY_VERIFIED evidence 的 SHA，最终回执再引用证明，避免循环摘要。部署必须验证整条链，不能仅判断 JSON 中有一个成功布尔值。

单独恢复仍只准新证明 schema：

先把私有配置对应的 `recoverySchemas.source` 设为新的、未使用的证明库名。已完成迁移使用过的恢复 schema 不得覆盖；此配置修改不改变旧库或候选连接。

```bash
python3 -B script/schema/restore_compact.py \
  --config /ecs/checkout/work/attempt/config.json \
  --backup-manifest /ecs/checkout/work/attempt/migrate/private/source-backup/manifest.json \
  --migration-evidence /ecs/checkout/work/attempt/migrate/migration-evidence.json \
  --restore-schema doorhandle_legacy_restore_0123456789 \
  --output /ecs/checkout/work/attempt/additional-restore
```

每个 SQL 段有自己的事务及必要 DDL，会发生已提交段。因此失败后保留源、部分候选、恢复库、备份和私有诊断，写 `FAILED_OR_UNKNOWN_STOPPED`，不能宣称整库事务已成功或盲重放。Workbench 提交未知时保留候选结果并停止，不自动再次复制。程序不删除旧库、不原地恢复、不修改生产连接。是否恢复旧应用或保留新库前向修复，依首次切换 journal 是否已允许候选产生新写入判断，见部署协议。

## ECS 验收与证据限制

`tests_python/test_compact_migration_orchestration_ecs.py` 仅在 `DOORHANDLE_COMPACT_MIGRATION_TESTS=1` 且显式设置 `DOORHANDLE_COMPACT_MIGRATION_CONFIG` 时执行。夹具应预先准备真实完整且有业务记录的 131 表旧库、对应隔离实例和已构建 Java helper；suite 不加载生产 dump、不创建 MySQL 服务、不改变源记录。它实际运行观察、全量复制、两次恢复、已存在候选的重放拒绝及最终活库读回。Jenkins manifest 的 `migrationConfig` 为私有文件路径，不进入 Java 进程参数或公开报告。

日报专项类为 `DigestCopyMigrationMySqlTest`，私有 properties 为 `doorhandle.digest.copy.source.config` 与 `doorhandle.digest.copy.mysql.config`，分别指向两个预置空隔离 schema。使用实际 V65 DDL、完整候选 DDL、实际 49 SQL 及真实业务下载，验证原 JSON/哈希、NULL/微秒、claim、高水位、0900 唯一性、源契约漂移和拒绝重放。

只有以上实际执行全部通过后，suite 才向 `DOORHANDLE_CI_EVIDENCE_DIR/migration.json` 写固定十字段公开摘要，包含 source/target 表数、迁移 SHA、两份快照 SHA、两份恢复回执 SHA。私有配置、原始 SQL、行数据、dump、错误诊断和完整迁移 bundle 留在 ECS 的 owner-only work，不归档到 Jenkins。当前尚无这轮真实 PASS；本地 AST 和源码生成只是静态检查。
