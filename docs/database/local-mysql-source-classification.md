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

## Jenkins 最小接线

[`preserve-local-mysql.ps1`](../../script/jenkins/preserve-local-mysql.ps1) 在既有 45 表双恢复、所属临时容器/卷清理，以及原始公开回执 SCP 和 SHA 核验全部成功后，仅在实际验证回执 `scope=mysql` 时运行分类。`source` 范围明确跳过，因为该构建没有完整 131 表 `fixture-origin-copy`；不会借用其他构建的源备份补齐输入。

四个可信锚点按下列来源建立，再作为分类 CLI 的显式参数传入：

| 锚点 | 取值与绑定 |
| --- | --- |
| `verification` | 已通过既有收集校验的当前原始 PASS 回执 SHA，分类前再次检查本地回执未变 |
| `contract` | 固定提交的 `source.tar.gz` 内契约原始字节 SHA，归档读取前后核对源码包 SHA |
| `localOwner` | 通过已固定主机密钥认证的 SSH，现场读取同构建 45 表 owner 原始字节并计算 SHA |
| `fixtureOwner` | 同次现场读取同构建 131 表 fixture owner 原始字节并计算 SHA |

现场读取只访问固定的两个控制 JSON，要求 canonical、当前 Unix 身份拥有、owner-only、无符号链接或硬链接，单文件不超过 16 MiB；读取前后核对同一打开文件及路径的身份、大小、时间和权限。SSH 输出只包含字节数和摘要，不回传 owner 内容。分类连接隔离用户 SSH 配置及全局 known-hosts，仅使用已指定主机密钥文件；分类器自身 SHA 同样从固定源码归档取得，在远端运行前核对。分类 CLI 会重读并验证这些原始字节及其证据链，不能由分类结果自报锚点替代现场读取。

成功后先核对远端原始报告的 owned/canonical/稳定读取、1 MiB 上限和 SHA，再通过 SCP 收集原件，并校验实际大小、SHA、同构建及 ECS 上下文、四个锚点、45 表公开回执 SHA 和不授权字段。任何读取、分类、采集或核验异常均使当前步骤失败，阻止后续阶段。

| Jenkins 制品 | 内容 |
| --- | --- |
| `artifacts/local-mysql-source-classification.json` | ECS 分类报告原件，仅逐表分类与摘要，不含数据库行或 DDL 内容 |
| `artifacts/local-mysql-source-classification-ci.json` | 接线摘要，绑定固定源码、helper/契约、四锚点、双恢复和清理回执、报告大小与 SHA；不包含私有 owner 内容或登录资料 |

接线目前属于新增源码，尚未取得真实 45↔131 分类结果。[验收清单](../../script/jenkins/compact-acceptance.json) 登记至少 90 例合成测试、不允许跳过；实际测试和接线仍须由包含这些改动的固定提交在 ECS 验证，先前或正在运行的旧提交不包含新接线。本轮只做 PowerShell 解析、嵌入 Python AST 及 diff 静态检查，没有在本机运行脚本或测试，原数据和本地原件未据此删除。
