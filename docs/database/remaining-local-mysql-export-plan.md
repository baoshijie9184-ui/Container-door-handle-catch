# 剩余本机项目库只读导出准备

此文件是待审阅方案，不是已执行、已上传、已恢复或可删除本机库的证明。当前完整 native 流水线不因此改变发布源或数据库。

## 已有覆盖与缺口

2026-11-07 管理员只读清单 `work/jenkins/local-runtime-admin-20261107T102203Z/inventory-private.json` 记录：

| 固定项目库 | 物理表文件 | 文件总大小 | 现有逻辑恢复证明 |
|---|---:|---:|---|
| `doorhandle_agent_verify_ef8d5844c1` | 2 个 `.ibd` | 376,832 字节 | 未找到 |
| `doorhandle_model_verify_22e4bc5566` | 5 个 `.ibd` | 622,592 字节 | 未找到 |

这是旧时点的物理目录清单，不能证明库为空、表当前仍相同或可以删除。Agent 库被项目文档明确保留；模型库五个已观察文件涉及配置命令、配置控制、模型配置、JSON 探针和吊销记录，也不能仅据名称认定无价值。

现有获准逻辑导出与 ECS 双恢复只覆盖 `doorhandledb`：`work/data-migration-20261107/local-mysql-export-20261107T112707Z-958ab7d6/public-manifest.json` 的 `sourceSchema=doorhandledb`，封存 profile 为 `local-mysql-export45-v1`。旧源、36 项补充、两批冷存储及 86 项补充 catalog 中，未找到这两个固定库的逻辑 SQL 导出和独立恢复证明；86 项中的三个 `private-data-archive.zip` 也没有这两个库名或 SQL 条目，不能替代它们的逻辑备份。

## 准备的最小执行范围

使用 [固定两库批次脚本](../../script/jenkins/export-remaining-local-mysql.ps1)，在新许可覆盖的**一次管理员会话**里顺序调用现有 [只读导出实现](../../script/jenkins/export-legacy-local-mysql.ps1)。默认只处理上述两个固定库；`-IncludeLegacyBusinessSource` 可追加一次 `doorhandledb` 新鲜重导，但该项也必须明确包含在新许可内。

- 仅读取已运行的 Windows `MySQL83`、`127.0.0.1:3306`；不启动或停止共享服务，不更改全局配置、权限或源库，不执行 `DROP`、恢复或本地测试。
- 复用原有进程、端点、安装路径、服务器 UUID、数据目录、MySQL 8.3 客户端及受保护凭据文件核验。新 worker 只有三个精确 schema 的闭合白名单，默认 `doorhandledb` 行为保留。
- 每库使用 `mysqldump --single-transaction --skip-lock-tables`，只接受 InnoDB 基表；保留前后身份、表目录、行数和 DDL 观察、完整 SQL、gzip 及解压字节 SHA。前后行数观察不等于导出事务内快照，沿用原 manifest 的明确边界。
- 凭据仅放在项目内现有受保护文件及临时私有 option 文件中；不进入进程命令行、终端日志或永久制品，临时 option/login 文件在结束时删除。完整 SQL 可能含历史密钥或业务字段，必须保持私有，不进入普通 Jenkins 制品。
- 每库输出在 D 盘项目的 `work/data-migration-20261107/local-mysql-export-<UTC>-<nonce>` 私有目录；批次授权及结果位于 `work/jenkins/remaining-local-mysql-export-<UTC>-<nonce>`，ACL 仅当前用户与 SYSTEM。失败保留部分结果，不自动重试。

示意调用（只供审阅，尚未执行；不在命令中填写密码）：

```powershell
pwsh -NoProfile -File .\script\jenkins\export-remaining-local-mysql.ps1 `
  -PrivateEnvFile '<项目内现有私有凭据文件的绝对路径>' `
  -UserAuthorizationReference '<本次新许可的记录编号>' `
  -AcknowledgeRemainingSchemasReadOnlyExport
```

脚本本身不请求 UAC、不替用户授权。旧许可是已使用的一次 `doorhandledb` 只读导出，不能扩展为当前两个库的读取许可；额外 acknowledgement 仅记录新许可。启动本脚本必须在新许可后由操作者从外部进入管理员会话。

## 普通用户只读模式（开发待验证）

新增显式 `-NonAdministratorReadOnlyExport` 参数集，管理员模式仍是默认值。此模式不接受 `PrivateEnvFile`，要求本次新的只读迁移授权、三个精确 schema 和 `-IncludeLegacyBusinessSource` 同时选定；源服务必须已运行，实际执行由操作者独立批准。当前仅完成代码开发和静态检查，没有运行客户端或实际导出。

新路径只读取固定 `work/model-mysql.private.json` 的 234 字节、完整 SHA；以同一只读句柄核当前用户所有权、单链接、最终路径、非 reparse、前后文件身份和原字节，不修改原文件内容或 ACL。凭据仅进入内存和 D 盘新私有目录中的短时 defaults 文件，结束时删除；不新建永久 dotenv，不向参数、日志或 Python metadata validator 发送用户名或密码。

来源仍需每次客户端启动前重新读取 `MySQL83` 服务、服务进程及固定端口 owner PID、进程创建时间和父子关系。普通权限读不到必要信息即拒绝；可见的完整路径和命令行必须匹配原固定安装。原始 TCP 状态 0 继续明确记为 UNKNOWN owner-bound，不冒充 LISTEN；真实连接随后必须匹配已认证 UUID、数据目录、版本、端口、系统主机名和认证账号，再核本次 schema 的直接读取、事件和触发器权限。历史身份 pin 不是现场身份。

已在清退前从四份原件逐一认证 SHA、对照 remaining86 清单和 #179 原始恢复回执，生成不含凭据或业务行的私有 bundle：`work/jenkins/nonadmin-local-export-assessment-20261109T230447Z/source-pins-20261109T232421Z-f085d724/history-pins-private.json`，SHA `1b7e580828c50d815d5d470461681a313867d07e9ef69c26e4b9b07371c3d530`。validator 只接受这一精确路径和摘要；原四份后续清退不会要求重新读取受保护的 C 盘目录，也没有任意路径或网络 fallback。

新模式使用 `--defaults-file` 仅读取自行生成的私有配置，同时保留空 login-file 隔离；不读取 C 盘全局 option 或数据目录。保留原单事务、InnoDB 基表、GTID_PURGED=OFF、跳过锁表和 tablespace、routines/events/triggers、前后身份/DDL/行数及压缩解压摘要核验。[MySQL 官方 option-file 说明](https://dev.mysql.com/doc/refman/8.0/en/option-file-options.html)支持该配置隔离；[mysqldump 官方说明](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html)要求 `--routines` 具有全局 SELECT，因此仅有 SHOW_ROUTINE 不足以通过本模式。

只供后续审阅的调用形状如下，不能将 acknowledgement 当成实际授权：

```powershell
pwsh -NoProfile -File .\script\jenkins\export-remaining-local-mysql.ps1 `
  -NonAdministratorReadOnlyExport -IncludeLegacyBusinessSource `
  -UserAuthorizationReference '<本次新的普通用户只读迁移授权记录>' `
  -AcknowledgeRemainingSchemasReadOnlyExport
```

新导出使用独立 `doorhandle-nonadmin-local-mysql-export` / schemaVersion 2，批次使用 `doorhandle-nonadmin-remaining-local-mysql-export`，始终 `restorePending=true`、`backupRestoreVerified=false`、`retirementAllowed=false`。原 `local-mysql-export45-v1` 接收器不接受此证明；待实际产生固定 SQL、manifest 和摘要后，须单独扩展既有 ECS 独立恢复器的精确三库 profile，不能冒认原 45 表恢复成功。原件和临时失败产物保留，不自动重试或清退。

## 导出后的验收与边界

本机成功最多产生 `LOCAL_EXPORTS_COMPLETE_ECS_RESTORE_PENDING`。随后需要由固定提交的本地 Jenkins 将私有包传至 ECS，在新建且隔离的 MySQL 中核验每库表结构、逐表实际行数、内容摘要、约束及独立恢复，并保留原始回执。这两个新 schema 不属于现有仅接受 `doorhandledb` 的 45 表恢复协议，不能冒用其旧回执或把参数改名视为验收完成。

只有新鲜原件与 ECS 恢复证据闭合后，才能进一步提出本机对应库的清退。导出脚本始终报告 `backupRestoreVerified=false`、`retirementAllowed=false`，不包含源库删除、共享服务停机、全局 Redis/MySQL 清理或其他项目库操作。
