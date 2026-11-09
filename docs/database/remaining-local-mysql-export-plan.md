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

## 导出后的验收与边界

本机成功最多产生 `LOCAL_EXPORTS_COMPLETE_ECS_RESTORE_PENDING`。随后需要由固定提交的本地 Jenkins 将私有包传至 ECS，在新建且隔离的 MySQL 中核验每库表结构、逐表实际行数、内容摘要、约束及独立恢复，并保留原始回执。这两个新 schema 不属于现有仅接受 `doorhandledb` 的 45 表恢复协议，不能冒用其旧回执或把参数改名视为验收完成。

只有新鲜原件与 ECS 恢复证据闭合后，才能进一步提出本机对应库的清退。导出脚本始终报告 `backupRestoreVerified=false`、`retirementAllowed=false`，不包含源库删除、共享服务停机、全局 Redis/MySQL 清理或其他项目库操作。
