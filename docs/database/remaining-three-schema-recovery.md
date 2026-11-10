# 剩余本机三库的 ECS 保全和独立双恢复

此入口接收 `export-remaining-local-mysql.ps1 -NonAdministratorReadOnlyExport -IncludeLegacyBusinessSource` 的实际成功 v2 批次。新的一次性只读导出仍待用户批准，尚未执行；没有实际 batch receipt SHA、三个源 SQL SHA、大小或 ECS 恢复结果。原 `local-mysql-export45-v1` 的保全入口、固定原件及默认恢复行为保持。

新入口包含可执行的 `project-mysql-custody.py` 和 `restore-project-mysql.py`。尚未接入 Jenkins 参数或自动调度；不能用示例 SHA、空包或手改参数把它启用。所有 ECS 动作继承现有固定源码、真实同构建项目 PASS、实例/执行身份、私有文件及源归档检查。仅控制预检成功不能授权它运行。

## 实际输入

输入固定为 `doorhandledb`、`doorhandle_agent_verify_ef8d5844c1` 和 `doorhandle_model_verify_22e4bc5566`。每库完整保存 v2 产生的17份原件，批次保存5份原件；另外封存实际 worker、批次脚本、非管理员 source helper 和 policy 的4份源码，共60份。未知文件、缺库、重复库、v1改标签、未完成批次、凭据临时文件、原始 SQL/gzip/DDL/观察摘要变化均拒绝。

调用方先固定实际 `batch-result-private.json` 的 SHA，`pack` 仅复制这些原始字节，不连接数据库。包装结束后固定 `custody.json` 和 `originals.tar.gz` 的实际 SHA 与大小。ECS `prepare` 创建本构建私有接收目录，受控传输后 `restore` 严格按完整闭集头恢复，重新核每个成员、完整源目录、gzip展开、前后DDL、计数和三库共同实际身份；字节恢复与 MySQL 恢复分别出具回执。

Windows producer 原始 CRLF 文件的 SHA 与 ECS Git 源码的 LF SHA 可能不同。包中保留原始 producer 字节，批次/单库回执仍核原始 SHA；另要求这4份源码仅作 CRLF→LF 后与本次固定源码完全一致。不会重写原始文件或把归一化摘要当作原始字节摘要。

## ECS 双恢复

恢复器复用现有原生 MySQL 保全的容器创建、实际 cgroup 观察、停止、归属核验和派生资源清理。每次启动前检查已有拥有实例全停，始终最多一个恢复实例运行。A/B 使用不同真实容器、卷和 MySQL UUID；network none、1536 MiB 内存/零交换、1 CPU、关闭事件调度和二进制日志，不挂载原库、不连接原库、不安装常驻 agent。

A 先创建完整三库、原样导入三个 `schema-before.sql`，保存源DDL基线；随后仅重建该拥有实例的三库，原样导入三个完整 `database.sql`。B 在另一独立实例/卷中导入全部三库。每次所有库恢复后才逐库采集完整列、行摘要、NULL/时间、主键索引、索引、DDL、高水位、约束和存储过程/参数/事件定义；三库间外键实际查询，指向闭集外的外键明确保持未核验。源DDL基线与完整恢复的结构/对象比较、A/B完整证据比较及前后观察计数全部闭合后才出具成功回执。

完整原件、源DDL基线、两次完整恢复及逐键成员、资源观察均进入派生资源删除前的重新核验链。只有该次成功、零OOM、实际退出0、完整原件及双恢复证据仍相符时，才能移除这两套拥有的派生容器/卷。失败时停止拥有实例并保留派生卷和原件，不删除共享卷、本地库或业务原件。

两个 fixture 库始终标记 `FIXTURE_ARCHIVE_ONLY`，不会合入业务库。`doorhandledb` 是后续旧45→131→29对账的业务来源；独立恢复不会自动执行合并或正式切库。导出只有前后计数观察，未提供同事务源行哈希，回执始终 `liveSourceRowHashesVerified=false`。双恢复可证明已接受 SQL 的可恢复性和两次恢复一致，不能冒充活动源库的逐行相等或授权本地退役。

## 当前验证边界

接收器合并后的版本化 profile 已登记此模块24项，并同步提前控制的执行器、控制器及自检集合；下一提交的最低数为20模块1,588项。这些新用例尚未执行，#189使用此前固定提交，只实际运行19模块1,564项，不能把两者混同。

本轮只编写代码及 ECS 用例，并进行源码 AST/PowerShell 解析和差异检查；没有本地执行测试、数据库客户端、导出或 SSH。新增用例覆盖实际完整包装/解析、CRLF原字节保存、外部batch固定、源闭集拒绝、跨库FK查询、串行实例约束和两次恢复的真实差异拒绝。实际合并后须提交推送固定源码，通过本地 Jenkins 在 ECS 执行，再接入该固定输入的阶段；没有恢复回执之前保留全部本地原件。
