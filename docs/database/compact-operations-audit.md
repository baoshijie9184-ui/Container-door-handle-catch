# 操作审计与文件交付候选

状态：`AUTHORED_NOT_EXECUTED`。本切片已编写生产适配、双库复制和 ECS 用例，未运行数据库或测试，不能作为已验证迁移记录。表数和部署方案不变。

实际旧表为 `operations_audit`（V40）及 `operations_file_delivery`（V52）。操作审计写入 `audit_event / OPERATIONS`；可变文件交付写入当前公共表 `workflow_instance / FILE_DELIVERY`。没有新建业务表、兼容视图或旧表 SQL 转写层。controller/filter/aspect 的调用接口保持原样。

操作审计保留完整六字段唯一键：`actor_user_id + domain(48) + action(64) + resource_id(160) + request_id(128) + result(40)`，继续使用 utf8mb4_bin 比较。domain、scope、result 从版本化载荷生成类型化字段并用于索引/权限分页；原字符串没有被摘要替代。相同六元组只能重放相同 scope 和 resourceVersion；两者不同会报冲突。重复插入后用 FOR SHARE 当前读核对不可变获胜回执，既避免 REPEATABLE READ 的旧快照漏读，也避免多个重复插入已持共享锁时再升级排他锁。

原 resource_version 没有非负约束，历史 NULL 或负值会保存在载荷 `resourceVersion` 中，不强行塞进公共非负 revision。共享表的数字 ID 是新的分页游标，旧 ID 同时保留在 legacy_source/legacy_key 和载荷中；切流时必须刷新旧分页游标，不能把两个表的自增空间硬合为同一个业务主键。

文件交付载荷保留 scope、domain、fileId、correlationId、resourceVersion、expectedBytes、acceptedBytesLowerBound 和 httpStatus；原 delivery_id 作为 workflow_id/request_id，固定 FILE_DELIVERY 幂等范围保留其原全局唯一性。版本仍使用原 revision 并通过当前读加 revision CAS 更新；状态推进与对应操作审计处于同一事务。

| 状态 | 含义与后续行为 |
| --- | --- |
| AUTHORIZED、HEAD_AUTHORIZED | 已授权，但尚无完整响应证据 |
| STREAMING | 服务端开始写入响应 |
| UNKNOWN | 证据不完整，可接收同一次已授权响应的后续回执；不自动重下文件，不当作成功 |
| SERVER_COMPLETED | 服务端完成 BODY 响应，不证明浏览器完整收到 |
| HEAD_COMPLETED | HEAD 响应完成，不等于文件正文下载完成 |
| INTERRUPTED | 响应中断或 HTTP 失败 |
| REDIRECT_AUTHORIZED | 只证明已授权重定向，不证明远端下载完成 |

后三类完成状态及 REDIRECT_AUTHORIZED 保存 finished_at，其余状态保持 NULL；没有工作器租约或超时重新执行下载。15 分钟协调只把仍未结束的授权/传输标记为 UNKNOWN。字节数始终是服务端已知的接受字节下界，后续较小观测不抹去先前已知下界。完成和协调使用原流程中的已授权 actor，账号注销或撤权后仍可记录这次响应；新的授权和列表读取继续核验当前身份及权限。

旧表没有 HEAD/BODY 标志。历史 AUTHORIZED/STREAMING/SERVER_COMPLETED 可明确标为 BODY，HEAD_AUTHORIZED/HEAD_COMPLETED 为 HEAD，REDIRECT_AUTHORIZED 为 REDIRECT；UNKNOWN 和 INTERRUPTED 保存 `deliveryMode=UNKNOWN`。不能从 expected_bytes 为零猜测 HEAD。

`copy/37-operations-file-delivery.sql` 依据实际 V40/V52 表声明保留两张来源表的全部 26 列；作者脚本只提取相应 CREATE TABLE，不执行 V40 中其他任务表 ALTER。执行需不同的源、目标 schema，源停写，并显式提供已核实的 `__SOURCE_OPERATIONS_OFFSET__`。原 DATETIME(6) 字符串保留在载荷中，公共时间按该来源偏移转为 UTC；列表再转换到北京时间。终态原 updated_at 是最后一次状态修改时间，作为迁移 finished_at；没有给 UNKNOWN 伪造结束时间。

复制门禁核对来源列、类型、NULL、默认值、字符排序规则、完整主键/唯一键及触发器/外键/检查约束变化；未知字段或新约束立即拒绝。V52 scope/domain/state 未在原 DDL 中指定排序规则，候选按 utf8mb4_0900_ai_ci 核验，实际源不同必须先解决契约差异，不能静默转换。源 actor 必须为正、状态/令牌/字节值须满足原应用语义，异常原行保留待处理，不过滤。

目标两个 kind 必须为空；其他已迁移领域可保留。两种数据在同一连接行事务中复制，以原 legacy key LEFT JOIN 做行数、完整载荷和公共字段的 NULL-safe 字节对账。漏字段、错关联、类型差异或任一步错误均停止并由该连接 ROLLBACK，禁止 `--force`；源库不更新、不删除。迁移账号需要已有源 schema 直接 SELECT 和 TRIGGER 权限，后者确保触发器元数据可见，工具不自动扩权。

测试使用 `OperationsMySqlFixture` 和实际 10/20/25/30/35/36/40 目标 DDL。`OperationsAuditServiceTest`、`BusinessMutationAuditTest` 已移除原两套简化 H2 审计表，另有 `FileDeliveryAuditMySqlTest` 和 `OperationsCopyMySqlTest`，合计 22 个待执行用例，覆盖权限隔离、六元组及最大长度、并发旧快照和双重试共享锁、业务/审计原子性、撤权后完成、UNKNOWN/字节下界、重复完成、来源时间/原 ID、原版本空值语义、结构变更拒绝、缺字段和来源尾空格篡改后的回滚。

ECS 验证阶段使用已有隔离配置参数：`doorhandle.operations.mysql.config` 指向目标空验证库，复制用例还需 `doorhandle.operations.source.config` 指向同一已核验实例的另一空验证库。配置必须在该 ECS 项目 work 目录下，并通过 Linux/machine-id/实例 ID/独立端口/server_uuid/datadir/专属账号及库名前缀门禁。夹具不会创建/删除数据库或新增授权，只创建并清理本次记录的表；发现外来对象会停止清理。此处没有本地数据库退路。

仍需在全部开发结束后的 ECS 窗口完成运行验证、当前源结构与时区核实、完整迁移顺序及恢复演练。编译通过也不能替代这些验证。
