# Docker 脚本

当前 Java 单体入口为根目录 `compose.monolith.yml`，镜像文件位于 `deploy/backend/` 与 `deploy/nginx/`。构建、配置、持久化和网络边界见 [单体 Docker 部署](../../docs/docker-monolith-deployment.md)。

原 `compose.nginx.yml` 保留为双实例实验，不作为当前单体默认启动入口。本目录用于后续构建、发布、健康检查和回滚辅助脚本。

- `configure-registry-mirror.sh`：合并并校验 Docker Hub 镜像代理配置，重启 Docker 后拉取运行 hello-world；应在维护窗口或首次部署前执行。
- `restore-demo-snapshot.sh`：在服务器项目根目录运行，仅向空的云演示库导入 SQL gzip，可同时恢复上传文件和工作区；拒绝覆盖非空数据库。

云端完整单机环境叠加 `compose.cloud.yml`，凭据模板 `deploy/cloud.env.example`。实际验收与权重路径见 [服务器演示部署记录](../../docs/服务器演示部署记录.md)。
