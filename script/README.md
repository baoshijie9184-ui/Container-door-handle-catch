# 项目脚本目录

按用途组织项目开发、部署和运维脚本：

```text
script/
├── docker       Docker Compose、镜像和容器辅助脚本
├── jenkins      Jenkins Pipeline、构建与发布脚本
├── idea         IntelliJ IDEA 运行/调试辅助配置
├── livekit-poc  LiveKit 语音/实时通信原型
├── paper        论文生成与补充脚本，不参与应用部署
└── shell        通用启动、停止、迁移和诊断脚本
```

约定：

- 脚本按幂等方式编写，重复执行不会破坏数据或重复创建资源。
- 真实凭据只通过 `.env`、`deploy/docker.env` 或 CI Secret 注入，不写入脚本。
- 可提交仓库的环境变量只能放在根目录 `.env.example` 或 `deploy/*.env.example`。
- 现有生产部署入口仍在 `deploy/`，迁移脚本时必须同步更新 README、Compose 和 CI 引用。
