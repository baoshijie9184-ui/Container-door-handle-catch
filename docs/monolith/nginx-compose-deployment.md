# 单机双后端 Compose 实验

日常单体入口仍是[单体 Docker 部署](docker-monolith-deployment.md)。这份配置在一台已批准的隔离服务器上运行一个 Nginx 和两个 Spring Boot 实例，用于检查代理、SSE 和实例故障；不是微服务，也不证明跨主机高可用。不要在 Windows 工作站启动它。

## 准备网络和配置

在隔离服务器的项目根目录复制私有配置模板：

```bash
cp deploy/docker.env.example deploy/docker.env
export DOORHANDLE_ENV_FILE="$(pwd)/deploy/docker.env"
```

填入容器实际可达的独立 MySQL、Redis、Kafka、可选 Mem0 等服务地址，以及隔离环境自己的凭据。此 Compose 不部署中间件，也没有 `host-gateway` 映射；容器中的 `127.0.0.1` 不是宿主机。不要提交环境文件。

此实验配置默认把 Nginx 映射到宿主机 80 端口，没有指定回环绑定；启动前确认所在隔离网络只向获准用户开放，并选择空闲端口。若只允许回环访问，优先用默认回环绑定的单后端 Compose，不把双后端实验端口开放到校园网或公网。

## 启动并查看结果

保持工作目录为项目根目录，显式指定项目目录以解析构建上下文。示例使用不与正式单体冲突的端口：

```bash
export NGINX_PORT=8089
export COMPOSE_PROJECT_NAME=doorhandlecatch-nginx-lab
docker compose --project-directory . -f deploy/compose/compose.nginx.yml up -d --build
docker compose --project-directory . -f deploy/compose/compose.nginx.yml ps
curl -fsS http://127.0.0.1:8089/nginx-health
```

若服务器使用独立 Compose 命令，可替换为：

```bash
docker-compose --project-directory . -f deploy/compose/compose.nginx.yml ps
```

Nginx 等待两个后端健康后启动，两个后端都不发布宿主机端口。通过获准的入口登录，用真实业务请求检查 API 代理；SSE 在浏览器 Network 面板核对输出是否分段到达，不只检查最终响应。Nginx 对 `/api/chat-assistant/messages/stream` 关闭代理缓冲并设置 300 秒读写超时。

## 故障切换与收尾

仅在本轮拥有的隔离栈中临时停止 `backend-1`，通过实际请求确认流量能由 `backend-2` 处理，再恢复 `backend-1`。请求失败或连接中断照实记录，不能由配置推断请求一定无感恢复。

```bash
docker compose --project-directory . -f deploy/compose/compose.nginx.yml stop backend-1
docker compose --project-directory . -f deploy/compose/compose.nginx.yml start backend-1
```

收尾只停止本轮隔离栈，保留命名卷。不把 `up -d --build` 当作滚动升级保证，不在开发工作区切换旧提交来回退正式数据。正式更新和恢复走[单体发布流程](README.md#ecs-统一验收与发布)。
