# 历史未知时钟协议

本协议保持29张业务表，不推断历史时区，不用导入时间替代历史时间。适用于明确选择 `UNRESOLVED` 的迁移分支；固定偏移分支继续要求原有证据和往返校验。

私有迁移配置中的 `sourceOffsets` 仍须完整列出原来的23个域。无法确认的受支持域显式填 JSON null，同时增加 `legacyClockPolicy`，其结构严格为 `{"version":1,"kind":"doorhandle-legacy-clock-policy","unresolvedDomains":[...]}`。列表必须按字母排序、去重，且与所有 null 域完全一致；不能省略策略后默认为 UTC。当前支持的未知域是 action、agent、chat、inbox、infra_log、mcp、memory、model_log、report、sdk、skill、workbench、workspace，其余域不接受 null。正式设置必须依据原机证据，不直接套用示例偏移。

控制器在生成 COPY SQL 前读取已审阅的完整源观察，并在源锁内再次核对同一快照。迁移回执和最终证据同时记录源时钟策略及其摘要，验证阶段拒绝配置策略改变。Workbench 仅在 workbench 域未知时使用版本2的 CLI 配置；已证固定偏移继续使用原版本1。

若只能证明已审阅的时间输入源表精确为空，策略可额外声明按字母排序的 `emptyDomains`。当前白名单为 binding、context、detection、digest、export、identity、model、model_file、operations、research；只检查各域实际参与时间转换的表，无时间列的控制行继续正常复制。这些域的 `sourceOffsets` 必须为 `+00:00`，仅作为无数据时不使用的占位值，不是 UTC 结论。预备器和整库迁移分别依据本轮完整源快照强制对应全部源表精确零行；缺表、估算零行、NULL 或新产生一行都拒绝迁移。该策略整体写入回执，Workbench CLI 只接收其自身三键未知时钟子协议。其他有数据域仍必须保留独立的历史时钟依据；该空表机制不能替代它们的来源证明。

8张表增加可空 JSON `legacy_clock_json`：`content_asset`、`content_revision`、`content_link`、`agent_run`、`agent_connector`、`runtime_state`、`workflow_instance`、`audit_event`。非空时必须严格包含以下7键，不能省略、增加字段或用字符串`"null"`代替JSON null：

```json
{
  "protocol": "doorhandle-legacy-clock-v1",
  "status": "UNRESOLVED",
  "sourceTable": "原表白名单名称",
  "sourceKey": {"原主键列": "保持原SQL类型的值"},
  "sourceSnapshotSha256": "本轮冻结源快照的64位小写十六进制摘要",
  "sourceRowSha256": "MYSQL_JSON_SHA256_V1的64位小写十六进制摘要",
  "sourceWallTimes": {"原DATETIME列": "CAST(原列 AS CHAR)的完整原值或JSON null"}
}
```

`sourceKey`是原表真实主键对象，不是新表游标、业务自然键或合成来源标签。列名、键集合和SQL类型来自受审的 [源列目录](legacy-clock-source-catalog.json)。例如`agent_memory_preference`为`owner_user_id`，`agent_skill_download_lease`为`download_id`，Workbench item/audit/request为`id`。合成逻辑任务的来源仍是原`agent_workbench_item/id`。

`MYSQL_JSON_SHA256_V1`定义：按目录中的原DDL列顺序，将**完整原行所有列**构造`JSON_OBJECT(列名,值,...)`；DATETIME/TIMESTAMP/DATE/TIME列先`CAST(原列 AS CHAR CHARACTER SET utf8mb4)`；JSON列同样转换成SQL存储表示的字符串，区分SQL NULL与JSON literal null；二进制列用`HEX`；其余列使用原SQL类型。再计算`SHA2(CAST(整行JSON AS CHAR CHARACTER SET utf8mb4),256)`。不得使用部分业务payload、Jackson序列化或Java格式化时间替代此摘要。MySQL对JSON对象的规范化是算法的一部分，完整源快照另有独立摘要。

目录中`sourceFiles`只用于校验受审DDL源码，按显式`UTF8_LF_WITHOUT_BOM`编码计算摘要，避免Windows检出换行与SCM归档换行不同。此规则绝不应用于业务行、payload、原始报告或源数据快照；它们保留各自原字节摘要。

`sourceWallTimes`严格包含该原表全部DATETIME/TIMESTAMP列，值用`CAST(原列 AS CHAR)`，不补时区、不补微秒、不添加Z。原NULL保留为JSON null。原表没有此类列时不制造历史时间。

SQL模板只识别显式sentinel `UNRESOLVED`，`__SOURCE_SNAPSHOT_SHA256__`由迁移控制器绑定本轮实际冻结源快照。`@compact_validation_wall_offset`在未知分支中的零位移只验证原DATETIME值可往返，不是时区结论；它不得写入任何持久化UTC字段或offset证据。未知分支所有历史绝对时间投影为SQL NULL，原`sourceUtcOffset`为JSON null。原始墙钟、状态、PK及完整源行摘要均保留。

Workspace未知文件manifest严格4键：`protocolVersion:2`、原`folder`、`createdAtSource:CAST(原created_at AS CHAR)`、`clockStatus:"UNRESOLVED"`。已知分支原三键V1保持不变。Workbench Item保留原keyset，外层业务`payload_version`仍1，typed envelope的`schemaVersion`为2、`legacy.sourceUtcOffset`为JSON null；来源旁证独立保存在本列。

NULL例外只对完整有效的白名单历史旁证开放；新记录仍按原协议要求UTC时间。旁证不可改写或删除。它保存的是历史源事实，不强制本行所有时间永远NULL：迁移初始NULL由COPY和逐列回读证明；后续用户明确操作可以写真实当前UTC更新时间和新revision，同时保留历史旁证。

原业务status不因迁移改写。未知租约、自动重放、消息投递、过期清理、MCP启用/回收及SDK自动恢复必须由执行方围栏进入需核对状态，不能把NULL解释为已过期、可重试或已核实进程退出。容量预留与外部进程证据不能仅因时钟未知而释放。

单行旁证只能绑定一个原表。当前未知Agent分支明确要求`agent_research_answer`精确0行，未知Skill分支明确要求`agent_skill_download_lease`精确0行；非空则失败关闭，保留原数据，等待多来源证据协议。已证偏移分支保留原有多来源迁移支持。

生成入口为`script/schema/author_legacy_clock_copy.py`，固定偏移源模板保留在`sql/mysql/compact/copy-fixed-clock/`，生成结果位于原copy目录。源码生成和静态编译不代表ECS迁移验收通过。

聊天未知分支保持既有审计 payload 键和版本，原偏移为 JSON null，旁证仍在 audit_event 的独立列。chat_message 不增加侧列；execution/workspace 的 UTC 投影为 NULL，并必须引用同账号、消息、会话、run 和原主键的有效审计旁证。两项投影触发器同时拒绝凭空填入绝对时间或换指针。历史关联继续只读展示，正文日期独立保留，旧关联不自动重绑或重放。直接删除消息不会级联删除独立的原审计旁证。
