# 本机旧库与 ECS 原库的快照分类

[`classify-local-mysql-source.py`](../../script/jenkins/classify-local-mysql-source.py) 读取同一固定提交、同一 ECS 构建的 45 表双恢复 JSON 及 131 表源备份清单，按完整列向量、主键顺序、行数与行链摘要、索引、DDL、排序规则和自增高水位逐表分类。此工具不连接数据库，不读取 SQL 内容，不修改业务数据。

| 分类 | 含义 |
| --- | --- |
| `MATCH` | 两份完整表快照一致 |
| `DIFFERENT` | 可比较，但一个或多个完整快照字段不同 |
| `NOT_COMPARABLE` | 完整列向量或行链的主键顺序不同 |
| `MISSING` | 表未出现在其中一份已经认证的目录内 |

分类器必须取得当前实际 MySQL 范围 PASS、45 表双恢复、131 表 `fixture-origin-copy` 以及固定 131→29 契约的摘要链。CLI 需要验证回执、45 表 owner、131 表 fixture owner 及契约四个原始 SHA 锚点；这些锚点须由已认证的 Jenkins SSH 调用取得并绑定固定源码，离线 JSON 自报摘要不能证明真实性。缺少同构建回执、恢复不独立、字段或摘要漂移时拒绝执行。

报告明确保持 `coverageVerified=false`、`targetDataCompared=false`、`productionMerged=false`、`retirementAllowed=false`。`MATCH` 只表示完整表快照一致；本工具没有重读 `data.sql`，没有比较 schema 级对象、触发器、例程、事件、逐主键包含关系及 29 表数据。存在差异后，应在 ECS 补充真实只读逐行对账，再决定合入方式，不用行数或共同列代替无损证明。

入口暂为开发中的独立 CLI，尚未接入流水线，也未取得真实 45↔131 分类结果。[验收清单](../../script/jenkins/compact-acceptance.json) 登记至少 90 例合成测试、不允许跳过；静态编译与代码复核通过，实际测试仍须由固定提交在 ECS 执行。原数据和本地原件未据此删除。
