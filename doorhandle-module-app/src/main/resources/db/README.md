# 检测记录与业务预置数据导入说明

本文档介绍如何向数据库中导入检测记录和业务预置数据。项目中的种子 SQL 统一按真实业务数据处理，可直接用于工单、批次、质检、模型、设备等模块的联调和展示。

## 文件说明

- `business-seed-new-features.sql`: 新功能业务预置数据，覆盖模型评估、设备采集、质检队列、缺陷证据等模块。
- `business-seed-more-features.sql`: 扩展业务预置数据，覆盖更多设备状态、告警、工单流转和复核处置场景。
- `business-seed-trace-rich.sql`: 工单追溯与批次追溯业务预置数据，用于验证追溯链路。
- `migration-V13-business-seed-data-normalization.sql`: 历史数据归一化脚本，用于清理已导入库里的旧标记和旧编号。
- `migration-V14-security-reliability-hardening.sql`: 安全与幂等迁移，增加用户角色、检测调度标识和助手动作错误字段；升级现有数据库时必须先执行。
- `detection_records_500_samples.sql`: 包含500条检测记录的SQL文件。
- `detection_records_generator.js`: 用于生成检测记录数据的JavaScript脚本。
- `import_detection_records.bat`: Windows批处理文件，用于自动导入数据。

## 导入方法

### 方法一：使用批处理文件（Windows）

1. 修改 `import_detection_records.bat` 文件中的数据库连接信息（用户名、密码等）
2. 双击运行 `import_detection_records.bat`

### 方法二：使用MySQL命令行

```bash
# Linux/Mac
mysql -u用户名 -p密码 数据库名 < detection_records_500_samples.sql

# Windows (CMD)
mysql -u用户名 -p密码 数据库名 < detection_records_500_samples.sql

# Windows (PowerShell)
Get-Content detection_records_500_samples.sql | mysql -u用户名 -p密码 数据库名
```

### 方法三：使用MySQL客户端工具

1. 打开MySQL Workbench或其他图形客户端工具
2. 连接到数据库
3. 打开并执行 `detection_records_500_samples.sql` 文件

### 方法四：导入业务预置场景

```bash
mysql -u用户名 -p密码 数据库名 < business-seed-new-features.sql
mysql -u用户名 -p密码 数据库名 < business-seed-more-features.sql
mysql -u用户名 -p密码 数据库名 < business-seed-trace-rich.sql
```

如果数据库曾经导入过旧版本种子数据，请再执行一次归一化脚本：

```bash
mysql -u用户名 -p密码 数据库名 < migration-V13-business-seed-data-normalization.sql
```

升级已有系统时，先执行安全与幂等迁移：

```bash
mysql -u用户名 -p密码 数据库名 < migration-V14-security-reliability-hardening.sql
```

### 方法五：启动时自动导入业务预置数据

业务预置数据默认不会自动写入数据库。需要一键准备演示/验收环境时，可在启动后端前开启：

```bash
set APP_BUSINESS_SEED_ENABLED=true
mvnw spring-boot:run
```

Windows PowerShell 也可以直接运行项目脚本：

```powershell
.\scripts\start-backend-with-business-seed.ps1
```

自动导入会先执行历史数据归一化脚本，再导入三份业务预置 SQL。脚本按幂等方式设计，可重复执行；如果是真实生产库，请保持 `APP_BUSINESS_SEED_ENABLED=false`。

## 数据生成

如果需要生成更多或自定义的数据，可以使用 `detection_records_generator.js` 脚本：

```bash
# 使用Node.js执行脚本
node detection_records_generator.js > new_records.sql

# 然后导入生成的SQL文件
mysql -u用户名 -p密码 数据库名 < new_records.sql
```

## 数据规格

生成的检测记录数据符合以下要求：
1. 时间范围：2021年到2025年
2. 图片漏检率不超过2%
3. 正常类别目标数量不超过2%
4. 更换类别目标数量大于维修类别目标数量
5. 三个类别的目标总数大于图片总数（一张图片可能有多个目标）
6. 检测速度：每秒15张图片
7. 图片总数范围：5000-20000张

## AgentScope 运行日志迁移

阶段 B 新增 `sql/mysql/migration-V16-agentscope-run-journal.sql`，classpath 副本在 AI 模块的 `src/main/resources/db` 中。该脚本只创建 agent_run 和 agent_run_event，不加入业务 seed 自动导入。先在项目业务库执行，再开启 AGENT_RUN_JOURNAL_ENABLED。接口、回退与验证见项目 `docs/agentscope-run-journal.md`。
## 报告及 Agent 草稿来源

V30 增加报告 outbox 租约/重试字段及两张回执表。归档和 classpath 副本一致；显式运行 `script/shell/migrate-local-report-events.py --apply`，本机 helper 检查列和索引后再执行，保留历史。开启 `APP_REPORT_EVENTS_ENABLED` 前完成迁移，详见 `docs/报告事件交付与重试.md`。

当前运行需要根目录 `sql/mysql/migration-V21-quality-report-approval.sql` 与 `migration-V22-agent-report-origin.sql`，classpath 同名副本保持一致。两者只新增表，不由业务 seed 或统一启动入口自动执行。本机迁移脚本 `script/shell/migrate-local-reports.py --apply` 同时幂等执行两份脚本。实现与验证见项目 `docs/Agent报告工具接入.md`。

V23 技能演化五表副本为 `migration-V23-agent-skill-evolution.sql`，归档在根 `sql/mysql`；本地显式执行 `script/shell/migrate-local-skills.py --apply` 并核对副本一致。运行不自动执行，关闭功能应保留版本与审计。

V24 外部技能来源为 `migration-V24-external-skill-import.sql`，新增导入表和版本来源类型/引用，旧记录默认 RUN，不删除或改写历史。上述本机入口同时检查并执行 V23/V24，可重复运行；手工 V24 列变更前检查是否已存在。启用技能演化需两份迁移，ZIP 上传功能已移除；V24 元数据仅用于历史兼容，详见 `docs/Agent技能自学习与受控发布.md`。

V25 `migration-V25-local-mcp.sql` 新增按账号隔离的固定 MCP 注册/安装状态与审计两表；根 SQL 与此副本一致。本机显式 `script/shell/migrate-local-mcp.py --apply`，重复执行不会覆盖已有行；启用 `AGENT_LOCAL_MCP_ENABLED` 时启动检查表。文件安装在用户 workspace，关闭功能保留状态、文件和审计，见 `docs/本地StdioMCP接入.md`。

## V66：聊天消息与执行关联

`migration-V66-chat-message-execution.sql` 仅新增 `agent_message_execution`，供新保存的助手回复在页面刷新后恢复真实工具运行关联。归档和 App 模块 `src/main/resources/db` 副本保持一致。需要既有 V16 运行日志，显式迁移，不由启动或 seed 自动执行；不回填旧消息。未迁移时兼容普通聊天，详见 `docs/Agent消息执行关联持久化-20261028.md`。
