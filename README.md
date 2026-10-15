# 门把手检测系统 (Door Handle Catch System)

这是一个基于深度学习的门把手状态检测系统，可以自动识别门把手的状态（正常、需要维修或需要更换）。

## 系统架构

- **前端**：Vue.js + Element Plus；独立 Agent UI 使用 React + Spark Design
- **后端**：Spring Boot + MyBatis Plus
- **数据库**：MySQL
- **AI推理**：原始 PTH + PyTorch CPU worker（Kafka 调度），兼容既有 ONNX Runtime 路径

## AgentScope 单体开发

项目功能清单、已开发能力、未完成事项及后续任务见 [开发进展](开发进展.md)。

当前 `java` 分支先完善模块化单体，再考虑微服务拆分。主站聊天和独立 AG-UI 均使用 AgentScope Java 2.0.4，旧 StateGraph 与独立 DeepSeek 客户端已移除。员工使用角色限定的只读工具；启用确认功能时，主管可提出质检分配提议并通过人工确认执行。模型配置与自动备用见 [平台配置](docs/agentscope-platform-config.md)，迁移边界、真实轨迹与验证记录见 [实施进度](docs/agent-role-toolkit-progress.md)。

## 本地单体一键启动

双击项目根目录的 `start-local.cmd`，或执行 `./start-local.ps1`，启动中间件、Spring Boot 后端和两套前端。主站登录地址为 http://127.0.0.1:3001/#/login，打开主站根地址也会进入登录页，登录成功后进入首页。Agent UI 为 http://127.0.0.1:3003。停止使用 `stop-local.cmd` 或 `./stop-local.ps1`，共享 MySQL、Redis 服务保持运行。

环境要求、重新构建参数、数据目录及日志排查见 [本地单体启动说明](docs/local-monolith-startup.md)。

员工、主管各两个可登录测试账号及密码见 [测试用户账号](docs/测试用户账号.md)。

主管质检分配的提议、人工确认、审计与配置见 [AgentScope 操作确认](docs/agentscope-action-confirmation.md)。

员工读取本人及分派任务、主管读取企业业务数据；聊天、记忆、操作确认仍按账号隔离。开源参考、实现范围和限制见 [多用户权限与数据范围方案](docs/多用户权限与数据范围方案.md)。

账号与员工、部门关联已支持主管管理、员工查看本人身份、版本冲突和事务审计，入口为“产线资源 → 账号与组织”。新开发库先执行 V20；使用与验收见 [账号员工部门关联](docs/账号员工部门关联.md)。

“质检追溯 → 报告与审批”已支持个人草稿、冻结提交、另一名主管预览确认、驳回/修订和已审批 Markdown 导出。新开发库先执行 V21；实现与边界见 [报告草稿与独立审批](docs/报告草稿与独立审批.md)。

报告详情新增“状态同步”，支持 Kafka 交付状态、消费回执、自动重试及主管确认重新发送。需 V30 和 `APP_REPORT_EVENTS_ENABLED=true`，见 [报告事件交付与重试](docs/报告事件交付与重试.md)。

AgentScope 新增报告专业 Agent，可查询授权报告和保存本人草稿，审批仍到业务页面。V22 保存草稿与原运行的关联，默认 Eval 更新为 30 项 v2 用例；见 [Agent 报告工具接入](docs/Agent报告工具接入.md)。报告迁移脚本现在同时检查/执行 V21、V22。

Agent 聊天已接通检测任务、质检记录、工作统计和报告草稿结果卡片。主站持久保存文字及资源引用，刷新按当前权限重读业务数据；独立 React UI 接收同一版本的 AG-UI 自定义事件。卡片刷新不重放模型或写操作，详见 [Agent 业务卡片接入](docs/Agent业务卡片接入.md)。

“Agent技能演化”已支持本人授权经验来源、Agent 提议私人 Skill 草稿、服务端结构/权限规则 Eval、独立主管审核发布、SDK 原生读取、版本回退、停用及 30/90 天维护。需 V23 和 `AGENT_SKILL_EVOLUTION_ENABLED=true`；真实模型语义质量尚未验收，见 [技能自学习与受控发布](docs/Agent技能自学习与受控发布.md)。

两套聊天界面已支持输入 `/` 选择技能命令；`/skills` 查看当前角色可用技能，`/skill 技能名或skill-id 问题` 先核对并加载发布版本，再由 AgentScope 回答。命令加载有独立运行轨迹和版本审计，新增 `/skills install 链接` 生成页面确认入口；链接安装与卸载由页面明确操作。用法与验证见 [技能斜杠命令](docs/Agent技能斜杠命令.md)。

主站与独立 Agent 页面已统一后端会话、历史、RAG 与账号范围 Mem0 记忆。React 支持选择、新建及刷新会话，刷新恢复数据库消息，详情见 [会话历史与记忆统一](docs/Agent会话历史与记忆统一.md)。

新增“Agent智能系统 → 个人记忆”：查看本人记忆、控制读取与自动保存、预览确认删除及操作记录。两套聊天入口使用同一账号设置，需 V26 与内部 `MEM0_BRIDGE_TOKEN`；本机迁移脚本已配置。详情见 [个人长期记忆治理](docs/个人长期记忆治理.md)。

个人记忆现已支持编辑原文、预览确认保存、版本冲突后保留草稿并重新核对，以及超过 100 条的连续分页读取。Mem0 保留独立 HTTP 服务边界，新增可选持久数据目录；后续部署准备见 [Mem0 服务器迁移准备](docs/Mem0服务器迁移准备.md)。

固定 Agent 规则评测、实验报告与基线比较见 [Eval 使用说明](docs/agentscope-eval.md)，入口为 `./script/shell/run-agent-eval.ps1`。当前是模型脚本与隔离 H2 的规则评测，真实模型回答质量仍待后续验收。

“Agent智能系统 → 资源市场”收录国内外 11 个来源，支持 Agent/MCP/Skill 分类、搜索及官方入口，见 [资源市场接入](docs/Agent资源市场接入.md)。Skill ZIP 上传及上传来源创建流程已移除；技能演化保留业务运行经验提炼、规则 Eval、独立审核与版本治理。第一版公开链接下载已接入，见 [链接下载安装](docs/外部Skill链接下载与受控安装.md)；脚本附件执行和远程 Agent 接入仍未实现，见 [技能自学习](docs/Agent技能自学习与受控发布.md)。

本地 Fetch MCP 已接入：“Agent智能系统 → MCP工具”，按账号下载固定包、创建隔离 Python 环境、保存版本/许可文件，人工安装确认后主动启用，由 AgentScope 原生 Stdio 握手和调用。需 V25 与 `AGENT_LOCAL_MCP_ENABLED=true`；其他 MCP、远程 Agent 尚未实现；公开链接 Skill 下载已有首版，见 [本地 Stdio MCP 接入](docs/本地StdioMCP接入.md)。

## 功能特点

- 门把手状态分类（正常、需要维修、需要更换）
- 实时图像检测及结果可视化
- 带有颜色标记的检测框和标签
- 检测历史记录管理
- 模型管理与切换

## 安装步骤

### 前提条件

- JDK 17+
- Maven 3.6+
- Node.js 14+
- MySQL 8.0+
- Conda + Python 3.10（统一使用 `leetcode` 环境）

### Python 环境

项目内的 Playwright 测试、Kafka 检测 worker 和 Python 测试统一使用
`leetcode` Conda 环境。首次配置可执行：

```powershell
conda env create -f environment.yml
conda run -n leetcode python -m playwright install chromium
```

如果本机已经存在 `leetcode` 环境，可按清单更新：

```powershell
conda env update -n leetcode -f environment.yml
```

项目提供统一入口，避免当前终端误用 Conda base：

```powershell
# 验证浏览器
.\scripts\run-python.ps1 frontend\tests\test_browser.py

# 执行前端自动化测试（需先启动前后端）
.\scripts\run-python.ps1 frontend\tests\test_frontend.py

# 执行 AgentScope 在线冒烟检查（需配置测试账号，调用真实模型）
.\scripts\run-python.ps1 scripts\diagnostics\agent_live_smoke.py

# 启动 Kafka 检测 worker
.\scripts\run-python.ps1 kafka_detection_worker.py
```

### 数据库设置

1. 安装MySQL数据库
2. 创建数据库：
```sql
CREATE DATABASE doorhandledb DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 后端设置

1. 克隆代码库
2. 将本地开发环境变量模板复制为 `.env`，并填写数据库、JWT 和外部服务等真实配置。`.env.example` 可提交仓库，`.env` 仅供本机使用并已加入 `.gitignore`：
```powershell
Copy-Item .env.example .env
```
3. 编译项目：
```bash
mvn clean compile
```

### 前端设置

1. 进入前端目录：
```bash
cd frontend
```

2. 安装依赖：
```bash
npm install
```

3. 启动开发服务器：
```bash
npm run dev
```

## 使用指南

完整的业务操作说明请查看：

```text
docs/system-user-guide.md
```

智能助手 Chroma RAG 配置说明请查看：

```text
docs/chroma-rag-setup.md
```

### 启动后端

直接通过主类运行Spring Boot应用程序：

```bash
# 先在项目根目录构建，再启动 Server 空壳
mvn clean package
java -jar doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar

# 调试模式启动
java -Ddebug=true -jar doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar

# 初始化数据库
java -jar doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar --init-database

# 清理图片缓存
java -jar doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar --clean-images
```

在IDE中，可以直接运行`DoorHandleCatchApplication.java`文件，并根据需要添加命令行参数。

### 启动前端（开发模式）

```bash
cd frontend
npm run dev
```

### Java 单体 Docker 部署

当前推荐 `compose.monolith.yml`：一个 Java 后端和一个 Nginx，托管主站与独立 Agent UI，支持 AG-UI/SSE、OSS 上传和用户工作区持久化。MySQL、Redis、Kafka、检测 worker、Mem0 等仍按已有独立服务地址配置。

Docker/Compose 使用独立的 `deploy/docker.env`，只覆盖容器访问数据库、Redis、Kafka 和外部服务所需的地址、开关、凭据及 JVM 参数；它与本地开发使用的根目录 `.env` 职责不同。

```powershell
Copy-Item deploy/docker.env.example deploy/docker.env
$env:DOORHANDLE_ENV_FILE = 'deploy/docker.env'
docker compose --env-file deploy/docker.env -f compose.monolith.yml up -d --build
```

请只提交两个 `.example` 模板，真实凭据不得提交。

默认访问 `http://127.0.0.1:8088/#/login`，Agent UI 为 `/agent-ui/`。环境变量、持久化、公网开放和回滚见：

```text
docs/docker-monolith-deployment.md
```

原 `compose.nginx.yml` 与 [双实例部署说明](docs/nginx-compose-deployment.md) 保留为实验入口，不作为当前单体默认方案。

### 图像检测

1. 访问系统：http://localhost:3001
2. 登录系统。系统不内置默认账号；首次部署时请由数据库管理员向 `users` 表写入使用 BCrypt 加密的企业账号，禁止使用公开的固定密码。
3. 进入"图像检测"页面
4. 上传门把手图像
5. 选择检测模型（可选）
6. 点击"开始检测"按钮
7. 查看检测结果（包含检测框、类别和置信度）

### 检测结果说明

- **绿色框**：正常状态
- **橙色框**：需要维修
- **红色框**：需要更换

## 常见问题解决

### 中文显示乱码

系统默认使用UTF-8编码，如果仍然出现乱码，可以通过添加JVM参数解决：

```bash
java -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 -jar doorhandle-server/target/doorhandle-server-0.0.1-SNAPSHOT.jar
```

### 数据库连接问题

请确认MySQL服务已启动，并检查用户名密码是否正确。

### 图像上传失败

请检查图像格式（支持JPG/JPEG/PNG），并确保文件大小不超过限制（默认5MB）。

## 许可证

MIT 
