# Java 单体 Docker 部署

## 2026-10-15 CPU PTH 检测补充

服务器现已启用 `compose.detection.yml`，以 Python/PyTorch `2.5.1+cpu` 直接加载 `best_stg2.pth`。模型编号 105 已发布并设为默认，正常图片和 Missing 缺陷图片各完成一条真实上传、Kafka 推理、OSS 结果、Java 入库任务；八项服务 healthy。本节更新优先于下方 2026-10-14 的“worker 关闭”历史记录。服务器页面仍待恢复本机 SSH 隧道后验收，API 验收不能替代页面验收。

在能连接官方 PyTorch 下载源的构建机，准备 Linux / Python 3.12 的 CPU wheel 和隔离上下文：

```powershell
python -m pip download torch==2.5.1+cpu torchvision==0.20.1+cpu --index-url https://download.pytorch.org/whl/cpu --platform linux_x86_64 --python-version 312 --implementation cp --abi cp312 --only-binary=:all: --no-deps --dest work/cloud/pth-cpu-wheels
python script/shell/prepare-pth-worker.py --source-zip wacga_shrinkage_seed42_60e_code_20261014.zip --wheels work/cloud/pth-cpu-wheels --archive work/cloud/pth-worker-build.tar.gz
```

归档仅包含运行器、匹配的训练源码、许可与 wheel，不包含 PTH、数据库或凭据。解压到服务器发布目录的 `work/cloud/pth-worker-build`；将上下文 `deployment/manifest.json` 以 640、原文件所有者复制到 `/srv/doorhandle/models/manifest.json`。清单只适用于已核验的这份 WACGA 权重，不适用于任意 PTH。许可文件来自项目内 `deploy/worker/licenses`，不依赖开发机其他工程路径。

服务器私有 `deploy/cloud.env` 已配置 `DETECTION_MODEL_ID=105`、`DETECTION_MODELS_DIR=/srv/doorhandle/models`、`DETECTION_MODEL_GID=1000`、`DETECTION_CPU_THREADS=2`。其他环境的模型编号须取该环境实际登记并发布的编号。权重与清单只读挂载；worker 以 UID 10001 运行，附加文件组 1000，不放宽模型目录为全员可写。

```bash
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml -f compose.detection.yml build detection-worker
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml -f compose.detection.yml up -d --no-build --pull never
```

仅在源码/镜像有变更时重新构建；普通恢复启动使用第二条命令。构建时 `docker.m.daocloud.io` 返回 HEAD 502，本轮改用显式代理前缀及官方核对的 Linux amd64 摘要：`m.daocloud.io/docker.io/library/python@sha256:2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe`。需要复用时，将 `DETECTION_PYTHON_BASE_IMAGE` 设为该值；后续更新版本需重新核对官方摘要。

该 CPU 运行时不会因为安装 CUDA 依赖而获得 GPU 加速。未来更换 GPU 实例后，再单独配置驱动、容器 GPU 支持和 CUDA 版依赖；当前没有创建 GPU 资源。PyTorch 版本组合见 [官方版本安装说明](https://pytorch.org/get-started/previous-versions/#v251)。详细验证见 [六分类检测链路接入](六分类检测链路接入.md)。


当前推荐入口是 `compose.monolith.yml`：一个 Java 模块化单体容器，加一个托管两套前端的 Nginx 容器。数据库、Redis、Kafka、Python 检测 worker、Mem0 和 Chroma 按已有服务边界单独配置；本文件不会自动创建这些服务或迁移数据库。

## 镜像设计

| 文件 | 职责 |
| --- | --- |
| `deploy/backend/Dockerfile` | Maven/JDK 17 多阶段编译全部 12 个模块，只把可执行 JAR 和运行所需文件放进最终镜像 |
| `deploy/backend/entrypoint.sh` | 使用 exec 启动 JVM，转发停止信号，支持 JVM 参数和 Spring Boot 启动参数 |
| `deploy/nginx/Dockerfile` | Node 24 分别构建 Vue 主站和 React Agent UI，Nginx 1.30 托管静态资源 |
| `deploy/nginx/nginx.monolith.conf` | 单后端代理，支持 AG-UI/SSE、OSS 上传及前端路径 |
| `.dockerignore` | 排除凭据、私钥、用户工作区、运行数据、模型、依赖目录和本机构建产物 |

后端使用 Ubuntu Noble/glibc 的 Temurin JRE，包含 ONNX/OpenCV 所需的基础原生库，以及固定 Skill/MCP 安装脚本需要的 Python、venv、pip、Requests、PyYAML。Maven、Node 和前端开发依赖不进入后端运行镜像。后端 UID/GID 为 10001，默认非 root 运行。

镜像不包含业务模型文件、用户技能、已安装 MCP、个人记忆或密钥，也不会自动开启 Agent 写入能力。修改基础镜像版本后需重新验证；需要严格复现时在发布环境将基础镜像固定为已验收的 digest。

## 准备配置

在项目根目录执行：

```bash
cp deploy/docker.env.example deploy/docker.env
```

填写 `deploy/docker.env` 中的 MySQL、Redis、Kafka 地址、JWT 随机密钥、OSS 凭据及所需模型密钥。不要直接复制开发机 `.env`，其中可能有 Windows 路径和仅供本机使用的地址。

`host.docker.internal` 在 Compose 中映射到 Linux 宿主机网关。宿主机上的数据库等服务必须允许容器网段访问；仅监听 `127.0.0.1` 的服务不能通过此映射访问。位于其他容器网络或服务器时，填写实际可达地址。

新库先按 `sql/mysql/README.md` 完成基础表及所需迁移。Agent 功能默认关闭，按已迁移的范围启用 `AGENTSCOPE_AI_ENABLED`、运行日志、人工确认、技能演化及本地 MCP 等开关。Kafka 检测仍需要可用的 Python worker，不会因为 Java 容器已启动而自动获得推理能力。

使用外部 Mem0 时设置 `MEM0_ENABLED=true`、服务地址和双方一致的 `MEM0_BRIDGE_TOKEN`；Chroma 同理。需要把中间件一起部署到本机服务器时，使用下文的 `compose.cloud.yml`，它们分别运行在独立容器中。

## 构建与启动

```bash
docker compose --env-file deploy/docker.env -f compose.monolith.yml config --quiet
docker compose --env-file deploy/docker.env -f compose.monolith.yml build
docker compose --env-file deploy/docker.env -f compose.monolith.yml up -d
docker compose --env-file deploy/docker.env -f compose.monolith.yml ps
```

构建需要能访问 Maven、npm、基础镜像仓库和 Ubuntu 软件源。Docker CE 软件包已经安装，不代表 Docker Hub 必然可达。网络受限时可从有网络的可信构建机 `docker save`，传输后 `docker load`；应核对镜像摘要，不使用来源不明的公共代理镜像。

默认 Nginx 仅绑定服务器 `127.0.0.1:8088`。本地通过 SSH 转发查看：

```bash
ssh -L 8088:127.0.0.1:8088 -i <私钥路径> ecs-user@<服务器IP>
```

浏览器访问：

- 主站与登录：`http://127.0.0.1:8088/#/login`
- 独立 Agent UI：`http://127.0.0.1:8088/agent-ui/`
- Nginx 健康检查：`http://127.0.0.1:8088/nginx-health`

两个前端通过同源 HttpOnly Cookie 共用账号登录态。`/api/` 和 `/agui/` 转发到单体，流式接口关闭缓冲，Actuator 不经 Nginx 对公网代理。

OSS 上传还需将 Compose 变量 `OSS_UPLOAD_HOST` 设为与后端桶一致的完整域名，例如 `<bucket>.oss-cn-beijing.aliyuncs.com`。它是非秘密路由配置，应通过启动环境或独立的 Compose 参数文件传入；后端的 `env_file` 不会参与 Compose YAML 插值：

```bash
OSS_UPLOAD_HOST=<bucket>.oss-cn-beijing.aliyuncs.com docker compose --env-file deploy/docker.env -f compose.monolith.yml up -d
```

需要公网演示时，再将 `NGINX_BIND_ADDRESS=0.0.0.0` 和相应端口传给 Compose，并放行安全组；在 `deploy/docker.env` 将 `APP_CORS_ALLOWED_ORIGINS` 改为浏览器实际使用的源，包含非默认端口。配置 HTTPS 后再启用 `APP_COOKIE_SECURE=true`。

## 持久化与运维

上传图片、标注、结果与模型保存在 `doorhandle-uploads`；账号私有工作区、技能和本地 MCP 保存在 `doorhandle-agent-workspace`。新命名卷继承镜像目录的 10001 用户权限；恢复已有数据时应保持该所有权。已有 Windows MCP 虚拟环境不能直接搬到 Linux，需在 Linux 用户目录重新受控安装。

聊天、审计、权限和版本等数据库记录应备份 MySQL；长期记忆另按 Mem0 数据目录的备份方案处理。仅备份这两个应用卷不足以还原完整系统。

后端默认内存上限 3GiB，JVM 堆最多使用其 60%，为原生推理库与 Python 子进程留出空间。Compose 将容器日志按 10MB、3 个文件轮换，JVM 输出到标准输出。

```bash
docker compose --env-file deploy/docker.env -f compose.monolith.yml logs --tail=100 backend nginx
docker compose --env-file deploy/docker.env -f compose.monolith.yml exec backend python3 -c 'import requests, yaml'
docker compose --env-file deploy/docker.env -f compose.monolith.yml exec backend curl -fsS http://127.0.0.1:8080/actuator/health
docker compose --env-file deploy/docker.env -f compose.monolith.yml down
```

`down` 保留命名卷。不要使用 `down -v` 删除业务数据。可以用 `APP_IMAGE_TAG` 标记每次构建，回退时选择上一个已保存的镜像标签并执行 `up -d --no-build`；涉及数据库升级时应另行核对向前/向后兼容性，不自动降级数据库。

## 原有双实例方案

`compose.nginx.yml` 继续保留作实验入口，其两个后端仍属于同一个单体应用。它不等同于微服务，也不代表跨服务器高可用。当前单机论文演示优先使用这里的单后端方案。

## 服务器完整单机环境

`compose.cloud.yml` 在同一私网加入 MySQL 8.4、Redis 7.4、Kafka 4.2.2、Mem0 2.0.19 和 Chroma 1.5.9。只发布 Nginx 的端口，数据库、队列及记忆服务不映射到公网。Mem0 和 Chroma 复用一个 Python 镜像、使用独立数据卷；固定这些版本是为了避免旧 Chroma 与 Mem0 对 PostHog 的依赖冲突。

```bash
cp deploy/cloud.env.example deploy/cloud.env
chmod 600 deploy/cloud.env
# 编辑并填写凭据；MYSQL_PASSWORD 与 DB_PASSWORD 必须一致。
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml config --quiet
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml build backend nginx mem0
```

云部署构建使用阿里云 Maven/PyPI/Ubuntu 源和 npm 镜像，默认 Dockerfile 仍使用各官方源。这些源仅加速下载，不替换应用架构。首次 Kafka 启动前，`kafka-storage-init` 为数据卷设置官方镜像所需的 UID 1000；`kafka-init` 等待健康后幂等创建四个业务主题。日常进程保持非 root。

Docker Hub 直连失败时，可以在没有业务容器运行的准备阶段执行以下脚本。脚本合并 daemon 配置、校验并重启 Docker，重启可能影响已有容器：

```bash
sudo bash script/docker/configure-registry-mirror.sh
```

脚本采用 DaoCloud 开源镜像代理。此次 hello-world、应用基础镜像、MySQL 和 Redis 已拉取成功；Docker 29 拉取 Kafka 时另遇 referrers 502，使用该项目支持的显式前缀下载，再标记为 Compose 使用的名称：

```bash
docker pull --platform linux/amd64 m.daocloud.io/docker.io/apache/kafka:4.2.2
docker tag m.daocloud.io/docker.io/apache/kafka:4.2.2 apache/kafka:4.2.2
```

本次 Kafka 摘要为 `sha256:1213eb3943d551e5ed1fca7a4e109001cee35770b66a02a0c37a8964efe09b69`，已与 Docker Hub 官方清单核对。公共代理的可用性不作保证；其他发布版本同样应核对官方摘要。后续启动加 `--pull never` 使用已验证的本地镜像。

若复制现有演示数据，先取得源库一致性快照及运行文件归档，保留原始数据；以下恢复脚本仅允许目标库为空，不会覆盖已有表。文件归档使用 `uploads/` 与 `agent-workspace/` 两个顶层目录，不包含 Windows MCP 虚拟环境：

```bash
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml up -d --no-build --pull never mysql redis
sudo bash script/docker/restore-demo-snapshot.sh demo-database.sql.gz demo-runtime-files.tar.gz
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml up -d --no-build --pull never
docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml ps
```

全新库仍需按 SQL 文档初始化业务表；`cloud.env.example` 默认关闭需额外迁移的 Agent 功能，填写真实 LLM/Embedding 配置后再启动 Mem0。已迁移的演示库可按功能范围启用。服务端配置文件、数据库快照和运行文件归档均包含敏感数据，不纳入 Git 或镜像构建上下文。

完整环境另有五个中间件数据卷。停止使用 `down`，保留所有卷；不要使用 `down -v`。Mem0 当前按单进程运行，其内嵌记忆向量库与面向应用 RAG 的 Chroma 服务分别持久化。

## 本轮验证范围（2026-10-14）

北京服务器已通过完整 Maven 17 构建及 Node 24 的 Vue/React 镜像构建，Mem0 镜像构建通过。Docker Hub 代理拉取和 hello-world 运行成功；后端、Nginx、MySQL、Redis、Kafka、Mem0、Chroma 七项常驻服务均 healthy，初始化任务成功退出。容器内 `nginx -t`、Java Actuator UP 及 Python 安装器依赖导入通过。

复制后的 45 张表、340 条检测任务和 11 条模型记录与本地一致，上传文件与账号工作区已恢复。浏览器验证四个测试账号、两种角色、登录默认入口、检测历史、报告页及独立 Agent UI；32 项已登录只读接口请求返回 200，未登录 Agent 接口拒绝访问，无页面脚本异常。真实聊天 SSE 收到 done，回复“连接正常”入库，AgentScope 执行轨迹 COMPLETED。

真实聊天约 63 秒。北京服务器直连自定义默认模型供应商超时，触发了备用模型切换；这不能视为三个供应商均已正常直连。当前仍保留用户配置的默认模型与备用顺序，后续需单独改善默认供应商的服务器连通性。Mem0 已验证启动及本人记忆列表读取，尚未验收真实自动提炼质量，也未迁移开发机原有长期记忆库。

六分类 PyTorch 权重 `best_stg2.pth` 已单独上传并核对 SHA-256，但**尚未接入云端检测推理**。现有模型表路径对应的 ONNX 文件未在本地找到，云端检测 worker 保持关闭，运行状态接口明确返回 `WORKER_DISABLED`。Windows MCP 环境未复制到 Linux，云端本地 MCP 功能暂关闭。当前验收覆盖容器、账号、业务查询与 Agent 基础链路；真实图片检测闭环、MCP 重装和完整业务上线验收仍有待完成。实例与权重记录见 [服务器演示部署记录](服务器演示部署记录.md)。

## 参考

- [Maven 官方镜像源码，Apache-2.0](https://github.com/carlossg/docker-maven)
- [Eclipse Temurin 官方容器](https://github.com/adoptium/containers)
- [Node 官方镜像](https://github.com/nodejs/docker-node)
- [Nginx 官方镜像](https://github.com/nginx/docker-nginx)
- [DaoCloud public-image-mirror，Apache-2.0](https://github.com/DaoCloud/public-image-mirror)
- [Kafka 官方 Docker 入门](https://kafka.apache.org/42/getting-started/docker/)

使用官方镜像及镜像内保留的许可声明，项目自身许可随 JAR 一并复制到运行镜像。
