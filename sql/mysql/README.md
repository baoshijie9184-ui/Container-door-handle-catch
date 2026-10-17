# 检测记录与业务预置数据导入说明

本文档介绍如何向数据库中导入检测记录和业务预置数据。项目中的种子 SQL 统一按真实业务数据处理，可直接用于工单、批次、质检、模型、设备等模块的联调和展示。

## 文件说明

- `business-seed-new-features.sql`: 新功能业务预置数据，覆盖模型评估、设备采集、质检队列、缺陷证据等模块。
- `business-seed-more-features.sql`: 扩展业务预置数据，覆盖更多设备状态、告警、工单流转和复核处置场景。
- `business-seed-trace-rich.sql`: 工单追溯与批次追溯业务预置数据，用于验证追溯链路。
- `migration-V13-business-seed-data-normalization.sql`: 历史数据归一化脚本，用于清理已导入库里的旧标记和旧编号。
- `migration-V14-security-reliability-hardening.sql`: 安全与幂等迁移，增加用户角色、检测调度标识和助手动作错误字段；升级现有数据库时必须先执行。
- `migration-V18-test-users.sql`: 本地开发的员工、主管各两个测试账号；执行时会更新同名账号的密码和角色。账号及密码见 [测试用户账号](../../docs/测试用户账号.md)。
- `migration-V19-agent-confirmation.sql`: 主管质检分配的持久确认与审计表，只新增表，不恢复执行旧助手动作。
- `migration-V31-agent-research-evidence.sql`: 依赖 V16，新增本人运行的网页来源与回答引用关联表；需显式开启调研来源登记，见 [调研来源与引用追溯](../../docs/Agent调研来源与引用追溯.md)。
- `migration-V32-agent-research-storage.sql`: 依赖 V31，只新增账号配额锁与过期内容清理审计表；存储治理、清理默认关闭，不随迁移清空内容，见 [调研证据存储治理](../../docs/Agent调研证据存储治理.md)。
- `migration-V33-agent-research-export.sql`: 依赖 V31，新增私有来源导出摘要审计表；导出默认关闭，用户确认且审计成功后交付 JSON，见 [来源导出与审计](../../docs/Agent调研来源导出与审计.md)。
- `migration-V35-agent-research-export-limit.sql`: 依赖 V33，新增账号固定窗口计数表；限流默认关闭，额度和导出审计同事务提交，见 [导出限流](../../docs/Agent调研来源导出限流.md)。
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

V37 `migration-V37-agent-workbench.sql` 增加 AI 工作台状态、请求/审计及 SDK 检查点；V38 `migration-V38-agent-workspace.sql` 增加 App 文件引用、分支及审计。分别对应 AI/App classpath 副本，依赖 V16/V36。开发集成中，默认关闭，不自动应用到真实库，统一发布要求见 [八项能力实施](../../docs/Agent八项能力实施.md)。

V36 `migration-V36-conversation-inbox.sql` 增加对话输入、账号锁及摘要审计三表，依赖既有会话表及 V16 运行日志；App classpath 副本保持一致。默认关闭，执行迁移后显式配置 `AGENT_CONVERSATION_CONTROL_ENABLED=true` 并保持运行日志开启，重启生效。不自动重放已领取消息或恢复 SDK 断点，见 [任务暂停与消息队列](../../docs/Agent任务暂停与消息队列.md)。

V34 `migration-V34-mcp-install-queue.sql` 新增固定 Fetch 安装持久队列，先执行 V25，AI classpath 副本逐字节一致。功能默认关闭，需显式配置 `AGENT_MCP_DURABLE_INSTALL_ENABLED=true`；仅恢复确认有效期内等待任务，已领取任务不自动重放，不自动迁移或删除历史。见 [持久安装队列](../../docs/MCP安装持久队列与重启恢复.md)。

当前单体组织身份、报告审批和 Agent 草稿来源需依次执行 `migration-V20-account-employee-department.sql`、`migration-V21-quality-report-approval.sql`、`migration-V22-agent-report-origin.sql`。classpath 副本位于 App 模块，启动脚本不自动执行。V20 回填已有部门 ID、不猜测账号员工关联；V21、V22 新增报告流程及来源表。配置及回退边界见 [组织身份](../../docs/账号员工部门关联.md)、[报告审批](../../docs/报告草稿与独立审批.md)、[Agent 报告工具](../../docs/Agent报告工具接入.md)。

阶段 B 新增 `sql/mysql/migration-V16-agentscope-run-journal.sql`，classpath 副本在 AI 模块的 `src/main/resources/db` 中。该脚本只创建 agent_run 和 agent_run_event，不加入业务 seed 自动导入。先在项目业务库执行，再开启 AGENT_RUN_JOURNAL_ENABLED。接口、回退与验证见项目 `docs/agentscope-run-journal.md`。

V23 `migration-V23-agent-skill-evolution.sql` 新增本人来源授权、技能与不可变版本、规则 Eval、操作审计五表。开启演化前显式执行 `script/shell/migrate-local-skills.py --apply`，默认不启用功能；不自动删除历史或回滚表。见 [技能演化](../../docs/Agent技能自学习与受控发布.md)。
