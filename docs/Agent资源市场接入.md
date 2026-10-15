# Agent 资源市场目录与接入边界

核实与更新日期：2026-10-13。当前 `java` 分支的模块化单体新增“Agent智能系统 → 资源市场”，路径 `/agent/markets`。

## 已实现

后端 AI 模块维护版本化目录，`GET /api/agent/markets` 返回核实日期、目录版本、平台与三类能力。身份沿用项目的 Spring Security / `AgentIdentity`；员工和主管可以浏览，匿名及不具备检测助手角色的账号拒绝访问。响应不缓存。目录只包含公开资料，浏览不增加业务权限。

主站 Vue 页面支持 Agent、MCP、Skill 分类、关键词搜索、国内/国际筛选、详情说明及官方入口跳转；链接在新窗口打开，限制 HTTPS、不携带登录身份和业务参数、不向外站发送来源页面。页面及弹窗支持减少动态效果。

能力状态区分：`AVAILABLE` 已核实；`INTERFACE_ONLY` 仅接口；`UNVERIFIED` 未核实独立市场；`OUT_OF_SCOPE` 不在该目录范围。未核实不能解释为平台没有能力。默认 MCP 分类仅显示已核实市场，勾选“包含仅提供 MCP 接口的平台”后加入 SkillsMP。能力说明及核实来源可查看。

## 已收录的平台

| 平台 | Agent | MCP | Skill | 核实入口 |
| --- | --- | --- | --- | --- |
| 魔搭智能工坊 | 有入口 | 有广场 | 有技能中心 | [首页智能工坊菜单](https://modelscope.cn/home)、[Skills](https://modelscope.cn/skills)、[MCPs](https://modelscope.cn/mcp)、[Agents](https://modelscope.cn/agents) |
| 阿里云百炼 | 创建、发布、API 调用 | 官方与自定义服务 | 官方与自定义技能 | [Agent 2.0](https://docs.agent.bailian.aliyun.com/en/flow-agent/applications/agent-app)、[MCP 广场](https://docs.agent.bailian.aliyun.com/zh/mcp/official-services)、[Skill](https://docs.agent.bailian.aliyun.com/en/skill) |
| 阿里云 Skills 门户 | 未核实 | 未核实 | 已核实 | [门户](https://skills.aliyun.com/) |
| 阿里云 Agent 服务目录 | 未核实 | 未核实 | 已核实分类 | [Skills 目录](https://agentcatalog.aliyun.com/skills?orderBy=install) |
| MCP.so | 产品与模板目录 | 服务器目录 | 技能目录 | [首页](https://mcp.so/)、[Agents](https://mcp.so/agents)、[Skills](https://mcp.so/skills) |
| Skills.sh | 未核实 | 未核实 | 搜索与 CLI 安装生态 | [目录](https://skills.sh/)、[Vercel CLI 仓库](https://github.com/vercel-labs/skills) |
| 腾讯 SkillHub | 未核实 | 未核实 | 中文广场与开放 API | [平台](https://www.skillhub.cn/)、[腾讯官方仓库](https://github.com/Tencent/skillhub) |
| SkillsMP | 未核实 | 仅技能搜索 MCP 接口 | 聚合目录 | [开发文档](https://skillsmp.com/developers) |
| ClawHub | 未核实独立市场 | 未核实独立市场 | 技能与 OpenClaw 插件 | [官方仓库](https://github.com/openclaw/clawhub) |
| Smithery | 未核实 | 服务发现与连接 | 未核实 | [平台](https://smithery.ai/) |
| MCP 官方 Registry | 不在目录范围 | 官方元数据注册目录 | 不在目录范围 | [目录](https://registry.modelcontextprotocol.io/)、[官方仓库](https://github.com/modelcontextprotocol/registry) |

魔搭首页的动态导航已实际展开核实三个入口。阿里云服务目录的名称不能作为 Agent 市场已核实的证据，本期只标记已确认的 Skills 分类。阿里云百炼属于托管应用平台，其 Agent 功能不等同于可下载的 AgentScope Java 模板。

平台、CLI 或目录项目的许可证不等于其中每份资源的许可证。下载或复制前需要核对资源自己的许可及版权声明。本期仅新增手工整理的公开目录与项目自己的页面，没有复制外部资源源码、安装新依赖或部署外部服务。

## 运行接入进度

目录 API 的 `integrationStatus=DIRECTORY_ONLY`。页面的“前往平台”是导航，刷新只读取本项目目录，不后台扫描平台、执行 CLI 或调用收费服务。Skill ZIP 上传已移除，技能页面仅管理从业务运行提炼的经验技能。本地 Fetch MCP 已接入独立的按账号安装/启用页面，见 [本地 Stdio MCP 接入](本地StdioMCP接入.md)。Skill 自动下载、脚本附件、远程 Agent/MCP 及凭证配置尚未接入。

外部 Skill 与运行经验提炼采用不同来源：市场来源记录 `sourceType`、原项目、固定版本或提交、下载摘要、许可、资源文件与所需工具。不能伪造本人成功运行来使用现有演化提议入口。自学习来源仍要求本人明确授权与真实已完成运行。

三类能力分别实施：

1. **Skill 下载接入**：ZIP 上传及外部来源创建已移除。SkillHub/Git/市场链接自动下载、远端版本核验与脚本运行仍待实现；当前原生读取只提供审核后的业务经验技能。
2. **MCP 连接**：本地固定 Fetch 已接入按账号安装、人工启用、原生 Stdio、白名单与审计；通用服务器/工具/凭证引用注册仍待实施。工具名称沿用 SDK `mcp__{server_name}__{tool_name}`，按身份、角色、对象范围与风险授权。服务方的只读声明、平台登录和 API Key 不替代项目权限。后续写工具需具体人工确认、幂等与审计；云服务开通及收费需明确范围。
3. **Agent 接入**：区分可适配的配置/源码模板和远程已部署 Agent。模板映射到本项目的角色、委派与工具白名单；远程调用限制可传数据、服务身份、超时、计费与审计。共享平台资源不能获得员工私人会话或直接接管生产工具。

统一权限目标：资源导航、下载、启用和调用分别管理。业务经验技能采用私人来源、独立审核、版本与加载审计；资源能力、角色权限、业务对象授权和人工确认分别检查。动态权限管理、脚本包安装审批和外部 MCP/Agent 验收仍待开发。

## 验证

新增 HTTP 检查覆盖员工/主管读取、匿名与无权限账号拒绝、响应不缓存，以及禁止把目录 POST 当安装入口。主站运行现有检查与生产构建；浏览器检查实际登录、分类数量、MCP 接口区别、搜索与地区交集、详情、外链属性、失败后清空旧目录、手机弹窗及登录保护。实际结果见 `work/agent-market-*`，不宣称外部 API、下载或运行接入已经验收。

实际结果：两项后端 HTTP 流程测试通过，主站既有 47 项检查通过，前后端打包成功。九项实际浏览器/HTTP 检查全部通过，未出现页面 JavaScript 异常，见 `work/agent-market-browser-acceptance.json`。桌面与手机截图已复核；验收不调用外部市场服务，不下载、不安装资源，不请求模型供应商。首次浏览器脚本遇到 Element Plus 选择器覆盖和登录提示产生的多重 alert 定位问题，改用键盘选择和页面内定位后完成复验，未修改业务数据。

本地应用已通过统一启动脚本更新并运行，MySQL、Redis、Kafka、Chroma、Mem0、后端六项健康检查通过，见 `work/agent-market-local-start.log`。未新增数据库表、修改模型配置或安装环境；当前仍在 `java` 分支，改动未提交。
