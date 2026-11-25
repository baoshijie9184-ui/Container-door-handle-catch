# 多智能体协作与开发流程规范（`java-cloud` 单体）

本规范在不修改根目录 `AGENTS.md` 与 `docs/开发规则.md` 的前提下，定义本仓库 7 智能体协作分工、Skill 绑定边界、交接产物与阶段门禁。所有智能体必须无条件遵守根目录 `AGENTS.md` 的分支约定与开发顺序。

## 1. 铁律与红线

1. **分支唯一**：当前仅在 `java-cloud` 单体分支开发，严禁提前拆分或混入微服务专属实现。
2. **开发顺序强制**：严格执行 `全部约定功能及代码整合 → 跳过测试构建 → 固定提交统一测试与验收`。
   - 开发整合阶段仅允许只读排查、静态检查、编译及跳测试打包（`mvn -DskipTests=true clean package`、`npm ci --ignore-scripts && npm run build`），**禁止在任何目标提前跑测试**。
   - 统一验收发现问题后，必须汇总已知失败并集中修复，再按影响范围统一复测，**严禁“修一个、跑一轮”**。
3. **运行环境约定**：本轮直接使用个人 Ubuntu 服务器 Docker 栈（`compose.monolith.yml` + `deploy/compose/compose.cloud.yml` + `deploy/compose/compose.detection.yml` 及按需叠加配置，端口 `8080` 主站 / `8081` 评审站），不依赖云端 ECS 或 Jenkins。
4. **Skill 上限**：每个智能体严格绑定 **≤ 3 个**全局 skills（来源 `~/.gemini/config/skills/`）。
5. **建评分离**：页面视觉与交互去繁评分必须由独立评审智能体基于真实运行截图给出，前端开发智能体不得自评通过。
6. **实测为王**：严禁将预估收益写成实测结果；所有得分、Eval 结果与 Apifox QPS/TPS 必须绑定真实截图、报告或回执。

---

## 2. 7 智能体职责与 Skill 绑定

| # | 智能体角色 | 负责范围与代码/文档边界 | 绑定 Skills（严格 ≤ 3） | 核心交付物 |
|---|---|---|---|---|
| **1** | **业务流程与风险评审智能体** | 员工/主管双角色主流程梳理、功能“去繁就简”裁剪清单、前置风险预演、验收场景矩阵 | `pre-mortem`、`test-scenarios` | 流程精简清单、Pre-Mortem 风险表、双角色验收场景集 |
| **2** | **页面截图与视觉高级感评审智能体** | 对运行中的 Vue 3 主站（`frontend/`）与 React 18 Agent UI（`frontend-agent/`）进行桌面端（1440px）与移动端（390px）截图，按 100 分制量化打分 | `webapp-testing`、`impeccable`、`frontend-design` | 带截图证据的逐页打分表、视觉层次与高级感整改单 |
| **3** | **后端单体开发智能体（`java-cloud`）** | `doorhandle-contracts`、`doorhandle-module-{system,infra,device,detection,model,app}`、`doorhandle-server`、MySQL 8.4（29 表迁移与索引）、Redis 7.4、Kafka 4.2.2、OSS、Python CPU PTH Worker 协议 | `springboot-patterns`、`mysql-patterns`、`redis-patterns` | 后端整合代码、SQL 迁移脚本、跳测试构建产物 |
| **4** | **前端开发智能体（双前端）** | `frontend/`（Vue 3 + Element Plus + ECharts）与 `frontend-agent/`（React 18 + Ant Design + Spark），按视觉评审单执行界面升级与交互减法，维护双端协议一致性 | `frontend-design`、`frontend-patterns`、`webapp-testing` | 双前端整合代码、双端生产构建产物 |
| **5** | **AI Agent 开发智能体** | `doorhandle-module-ai`（AgentScope Java 2.0.5）、角色工具白名单与人工确认、Qdrant 1.20.0 检索、Mem0 账号隔离记忆、Higress 隔离 Fetch MCP、离线规则 Eval | `ai-agent-development`、`prompt-engineering-patterns`、`agent-evaluation` | Agent 能力整合代码、Prompt/工具契约、Eval 用例与基线 |
| **6** | **代码与流程符合度审查智能体** | 审查模块边界、RBAC 与数据范围隔离、SQL/Redis/Kafka 事务安全、`AGENTS.md` 开发顺序合规、Spring Boot 构建与验证清单把关 | `code-review-skill`、`springboot-verification`、`requesting-code-review` | 代码审查报告、合规放行意见、统一验收问题汇总 |
| **7** | **性能测试与瓶颈分析智能体（Apifox）** | 基于 Apifox 编排核心读接口（QPS）与核心写链路（TPS）压测套件，采集基线、定位 JVM/MySQL/Redis/Kafka/Qdrant 瓶颈并驱动闭环优化 | `performance-profiling`、`benchmark`、`benchmark-optimization-loop` | Apifox 压测套件、实测基线与调优对比报告 |

---

## 3. 四阶段协作编排

### Phase 1：基线摸底与评审（只读，不改业务代码）
- **主导**：智能体 2（截图打分）+ 智能体 1（流程去繁与风控）。
- **动作**：访问本机运行中的 8080/8081 站点，采集核心页面桌面与窄屏截图，按 `.agents/rules/scoring-rubric-90plus.md` 完成现状逐页打分与繁琐点清单，明确从现状提升至 **≥ 90 分**的改造项。
- **出口**：用户确认本轮改造范围。

### Phase 2：集中开发整合（禁止提前运行测试）
- **主导**：智能体 3（后端单体）+ 智能体 4（双前端）+ 智能体 5（AI Agent）。
- **动作**：按确认清单完成全部业务代码、UI 视觉升级、交互精简、数据库迁移、Redis/Kafka/Qdrant 配置、前后端接线与测试夹具更新；统一执行跳测试构建：
  - 后端：`mvn -DskipTests=true clean package`
  - 前端：`frontend/` 与 `frontend-agent/` 分别执行 `npm ci --ignore-scripts && npm run build`
- **出口**：全部约定改动就位且跳测试构建全部通过。

### Phase 3：代码与流程符合度审查
- **主导**：智能体 6。
- **动作**：核对 diff、`doorhandle-contracts` 边界、权限与数据隔离、未提交垃圾文件、构建产物与迁移一致性。
- **出口**：审查通过，形成本轮固定候选提交。

### Phase 4：本机 Ubuntu Docker 统一验收、复评与 Apifox 压测
- **主导**：智能体 6（统一验收汇总）+ 智能体 2（整改后截图复评打分）+ 智能体 7（Apifox QPS/TPS 压测与瓶颈分析）+ 智能体 5（离线规则 Eval）。
- **动作**：基于同一固定候选提交部署至个人 Ubuntu Docker 栈，集中执行功能验收、离线 Eval、截图复评打分与 Apifox 压测。
- **闭环规则**：若任一维度或任一核心页面低于 **90 分**，汇总全部问题退回 Phase 2 集中修复后再统一复测，直至全部指标达成 90+ 目标。
