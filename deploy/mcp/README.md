# 单机 AI 网关与隔离 Fetch

本配置用于 `java-cloud` 的同一台 Linux ECS，保留模块化单体。Nginx 处理登录、业务 API 和两套页面；Higress 仅在 Docker 内网接收模型及 MCP 请求。没有新增公网端口，也没有把数据库、检测服务改成微服务。

```mermaid
flowchart LR
  UI[浏览器] --> N[Nginx]
  N --> J[Java 单体 / AgentScope]
  J --> H[Higress 内网 AI 网关]
  H --> L[模型供应商]
  H --> R[签名身份 MCP 运行器]
  R --> C[每次调用的 Fetch 容器]
  C --> P[受限出口代理]
  P --> W[公开网页]
```

## 已采用的开源实现

- [AgentScope Java 2.0.4](https://github.com/agentscope-ai/agentscope-java/tree/v2.0.4)，Apache-2.0。使用现有 SDK `streamableHttpTransport` 和 Toolkit 工具发现，保留 `mcp__fetch__fetch` 工具名。
- [Higress standalone 2.2.5](https://github.com/higress-group/higress-standalone)，Apache-2.0。镜像固定 digest，使用无 Kubernetes 模式及镜像内置 `key-auth` 2.0.0。路由遵循[官方重写说明](https://higress.io/en/docs/latest/user/annotation-use-case/)。
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)，MIT。镜像固定 1.29.0，符合 Fetch 包要求的 `>=1.29.0,<2`。HTTP 调度和 Stdio 握手均走官方协议实现。
- [Fetch](https://pypi.org/project/mcp-server-fetch/2026.10.10/)，MIT。沿用既有固定发布和 SHA-256；所有 wheel、依赖版本、哈希和包内版权文件保存在镜像 `/opt/fetch/`，再以 `--no-index --require-hashes` 安装。
- Squid 采用 Ubuntu 24.04 包，遵循其 GPL 许可；系统包的 `/usr/share/doc` 版权文件保留在镜像内。不把第三方程序改标为本项目许可证。

构建不修改宿主机 Python 环境。模板沿用已存在的 Ubuntu/Temurin 基础镜像，避免再引入无法从 Docker Hub 获取的新 Python 基础镜像。ECS 构建从阿里云 PyPI 镜像下载，固定 Fetch wheel 仍须匹配原 PyPI 发布摘要；安装器仅允许官方索引及该固定镜像，不接受任意索引。构建后的 Fetch 和出口镜像均使用本机不可变 `sha256:…` ID；包更新需重新构建和验收。

## 权限与执行边界

用户仍须登录自己的账号，在 MCP 页面确认固定版本与许可证，安装后主动启用。网关模式在本人 `users/{id}/mcp/fetch/installs/{uuid}` 保存 `gateway-registration.json` 和 `manifest.json`；运行包及完整许可集中保留在经过核对的只读镜像。旧 Stdio 安装或不同镜像的记录需要本人重新确认迁移，不能自动复用。

Java 对用户、运行、启用状态、版本和 URL 的现有检查保留。发往运行器的 HMAC-SHA256 凭证绑定账号 ID、安装 ID、install/execute 范围、随机调用编号和最长 60 秒有效期；模型不能传入身份、命令、镜像或挂载。Higress 对 MCP 路由额外检查服务密钥，运行器再验证签名；不接受浏览器的账号声明代替后端授权。

每次网页调用启动独立非 root 容器：固定 Python 命令，只读文件系统、临时 `/tmp`、去除 capabilities、禁止提权，限制 CPU、内存、PID 和并发。容器没有用户工作区、数据库、OSS、模型密钥或 Docker socket。执行只连接专用 internal 网络，通过 Squid 访问公网 80/443；出口拒绝私网、回环、元数据、特殊地址和 ECS 自身公网 IP，阻断绕开应用层 DNS 检查的直接出口。调用结束、异常和取消会销毁容器，运行器还定期回收超时容器。

**运行器属于受信任基础设施**：只有它挂载 Docker socket 和宿主 Docker CLI。Docker socket 等价于宿主机控制权限，固定命令接口和服务鉴权不能替代虚拟机级隔离。因此当前仅支持已审核的 Fetch，不支持任意 shell、用户 Docker 参数或未审核 Skill 脚本。这不是通用沙箱池。

网关访问日志仅记录路由、状态码、耗时和请求编号；不记录 URL 查询、请求正文、Authorization 或 AI 内容。用户 MCP 操作继续写入既有审计表，关联原 runId/callId；网页地址只记录摘要。

## 服务器首次部署

先备份并核对 V25 表、现有服务和数据卷。从当前代码的服务器副本执行，参数分别是已有私有配置目录和当前成功发布目录：

```bash
# 在 deploy/cloud.env 中设置经核实的 ECS 公网 IP，不能填整个网段
MCP_SERVER_PUBLIC_IPS=101.201.227.35

bash script/shell/provision-ai-gateway.sh \
  /home/ecs-user/doorhandle-release-20261014 \
  "$(cat /home/ecs-user/doorhandle-ci/state/current-directory)"

python3 deploy/mcp/acceptance.py \
  /home/ecs-user/doorhandle-release-20261014/deploy/cloud.env
```

上面的 IP 行是配置内容示例，应写入服务器私有 env 文件。脚本构建两份镜像、生成随机服务密钥和签名密钥，先启动三项新基础服务；不会重启业务后端或替用户启用 MCP。私有配置自动保留一份权限为 0600 的备份，不能加入 Git。验收脚本验证网关鉴权、两个身份的真实 Fetch、内网拒绝、取消后凭证拒绝及容器清理，不调用收费生成模型。

通过后创建显式发布标记，再由本机 Jenkins 发布：

```bash
touch /home/ecs-user/doorhandle-release-20261014/deploy/ai-gateway.enabled
```

`deploy-remote.sh` 在标记和本次源码的 `compose.ai-gateway.yml` 同时存在时合并 overlay。应用发布仍只替换 backend/nginx；网关、运行器和出口镜像单独按本节升级。没有 overlay 的旧成功发布仍按原直连方式回滚，不自动删除网关资源。

模型工厂通过 `AGENT_MODEL_GATEWAY_BASE_URL=http://higress:8080` 接入，保留原供应商 API 路径、Bearer 和 Responses 附加头。余额不足、首响应超时、故障切换及熔断继续由现有模型管理执行，不再叠加网关重试。配置生成器只读取上游地址和 MCP 服务密钥，不把供应商密钥写入网关资源。

## 尚未覆盖

当前只桥接固定 Fetch 的 Stdio→Streamable HTTP；外部 HTTP/SSE 服务的通用注册、任意 MCP 安装、Skill 脚本执行、工作区挂载与配额、多实例任务调度、容器逃逸防护和完整对抗评测仍需开发。停机后 Docker 重启会恢复常驻服务；临时 Fetch 容器无重启策略，由运行器回收。
