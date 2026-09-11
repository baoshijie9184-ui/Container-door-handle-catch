# 门把手检测系统 (Door Handle Catch System)

这是一个基于深度学习的门把手状态检测系统，可以自动识别门把手的状态（正常、需要维修或需要更换）。

## 系统架构

- **前端**：Vue.js + Ant Design Vue
- **后端**：Spring Boot + MyBatis Plus
- **数据库**：MySQL
- **AI推理**：ONNX Runtime + OpenCV

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

# 执行 Python 智能体测试
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

### Nginx + Docker Compose 生产部署

项目提供 Nginx Web 服务器、API 反向代理和双 Spring Boot 实例负载均衡配置：

Docker/Compose 使用独立的 `deploy/docker.env`，只覆盖容器访问数据库、Redis、Kafka 和外部服务所需的地址、开关、凭据及 JVM 参数；它与本地开发使用的根目录 `.env` 职责不同。

```powershell
Copy-Item deploy/docker.env.example deploy/docker.env
$env:DOORHANDLE_ENV_FILE = 'deploy/docker.env'
docker compose -f compose.nginx.yml up -d --build
```

请只提交两个 `.example` 模板，真实凭据不得提交。

完整的环境变量、健康检查、SSE、故障切换和回滚说明见：

```text
docs/nginx-compose-deployment.md
```

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
