# 本地 Stdio MCP 接入

更新日期：2026-10-13。当前 `java` 模块化单体新增第一种本地 MCP：Fetch 网页抓取。入口“Agent智能系统 → MCP工具”，路径 `/agent/mcp`。

## 使用方法

1. 登录本人账号，在 MCP 页面点击“安装到我的 Agent 目录”，核对固定版本与 MIT 许可证后确认。也可以向助手明确说“安装 Fetch MCP”；助手保存私人待确认提议并引导到同一页面，提议不执行下载。
2. 后端异步下载固定 Fetch wheel 及依赖，创建本人 Python 虚拟环境，保留包、版本锁、摘要和版权文件，检查真实 MCP 握手及 fetch 工具发现。安装完成保持未启用。
3. 点击“测试 Stdio 连接”可单独验证握手，不请求模型或抓取网页。确认“启用本人 MCP”后，后续主 Agent 可以使用 `mcp__fetch__fetch` 读取明确提供的公开网页。
4. 停用关闭本人正在使用的连接，后续调用拒绝；文件、版本和审计保留。每次调用结束关闭 Stdio 进程，不常驻其他用户的进程。

不用上传 MCP ZIP。当前后台采用 `pip` 安装到专属虚拟环境，运行命令为该环境的 `python -I -m mcp_server_fetch`，协议仍为本地 Stdio。没有使用魔搭的远程 Hosted URL，也不修改 Codex/VS Code 的 MCP 配置。

## 文件存储

沿用 `agentscope.ai.workspace`，默认项目 `.agentscope/workspace`：

```text
users/{userId}/mcp/fetch/installs/{operationId}/
  .venv/                本人安装的 Python 环境
  packages/             下载的 wheel 原文件
  licenses/             包内许可证和版权文件
  requirements.lock     本次完整版本和 wheel SHA-256
  stdio.json            固定启动配置，无模型/数据库凭证
  manifest.json         原来源、摘要、受检文件及清单
  install.log           本人的安装诊断日志
  cache/ tmp/ home/     项目内缓存和临时目录
```

目录由服务端数字账号 ID 与生成的安装编号决定，用户不能指定执行文件、目录、包名或 shell 命令。拒绝路径穿越、符号链接和路径重定向；HTTP 入口只读本人状态、清单及审计。主管不会得到员工私人配置。前端开发服务器文件访问范围限定在前端代码及必要共享工具，不能经 `/@fs` 读取这些后端安装文件。

这是应用层账号隔离，不是不同 OS 用户、容器或 E2B 沙箱。MCP 程序依然以本机后端进程账号运行；本期只允许经过核对的固定 Fetch 包，未开放任意第三方命令或文件系统 MCP。

## 开源版本与安装

开发前核对 [魔搭 Fetch 页面](https://modelscope.cn/mcp/servers/@modelcontextprotocol/fetch)、[官方 README](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md) 和 [PyPI 2026.10.10 发布](https://pypi.org/project/mcp-server-fetch/2026.10.10/)。该包要求 Python >=3.10、MCP Python SDK 1.x；实际安装保留 MIT 和各依赖的许可证/版权文件。

固定顶层 `mcp-server-fetch==2026.10.10`，wheel SHA-256：

```text
d722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77
```

依赖从 PyPI 以 binary wheel 下载，本次解析的完整版本和摘要写入锁文件，再用 `--no-index --require-hashes` 离线安装，不执行 sdist 构建脚本。不同时间的新安装可能解析到不同兼容依赖版本，各自保留完整锁定清单。顶层源码摘要固定，不跟随市场上的“latest”自动升级。

安装脚本 `script/shell/install-local-fetch-mcp.py` 的基础 Python 只负责下载和创建环境，不向已有全局环境安装包。缓存、日志及临时目录位于用户安装目录。单次安装设超时、固定包/来源及文件数量/大小约束；失败保持未启用。重试生成新安装编号，不覆盖旧文件。当前未实现自动更新、卸载或任意包安装。

实际 SDK Jar 核对后使用 `McpClientBuilder.create("fetch").stdioTransport(...).buildAsync()` 和 `Toolkit.registration().mcpClient(...).mcpToolNamePrefix("mcp__fetch__").enableTools(["fetch"])`。与[官方 SDK MCP 设计](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/tool.md)一致使用原生协议、发现及结果转换；没有增加另一套 Agent 引擎。不同资料示例中的 builder 写法不替代项目实际 Jar API。

## 权限、生命周期与审计

- 系统仅有固定 `fetch` 服务器。员工和主管分别安装、启用自己的副本。浏览市场、安装成功、主动启用和实际调用分别检查，不能靠 `readOnlyHint` 或包内声明扩大权限。
- 模型安装工具 `propose_fetch_mcp_install` 绑定本人实际运行、mainAgent、租约及 callId，只保存待确认状态。安装必须由人工接口核对来源和许可证。已安装返回现状，不重复下载。
- 安装为有容量限制的后台作业，数据库保存状态、操作编号与租约；过期标记失败并审计，迟到作业不能覆盖新状态。原运行状态不被“提议成功”误写为安装成功。
- 状态操作使用行锁及 expectedRevision；安装请求编号去重。同账号最多两个并发网页调用。停用重查状态并关闭活动连接，取消/异常/超时清理客户端。
- 运行前复查本人启用状态、固定配置摘要、解释器/Fetch 模块、启动配置、锁文件和许可证文件摘要。并非整个虚拟环境的所有文件都逐一校验，也不宣称操作审计为不可篡改日志。
- 仅公开 HTTP/HTTPS 地址，拒绝凭证、常见秘密查询参数、内网/回环/元数据地址及非标准端口，限制返回字符与读取偏移；官方服务继续检查重定向。DNS 校验与网络连接之间仍有重绑定窗口，尚未实现独立网络出口隔离。
- Stdio 子进程不继承模型、数据库、OSS 等非白名单环境值；不自动传播 SDK 运行上下文。系统提示要求只抓取用户明确提供的公开网页，不将业务私密内容或网页中的指令用于外部工具调用。任意提示注入防御和模型遵循程度未经过完整对抗验收。
- MCP 审计关联本人、固定包、操作编号、原 runId/callId、开始/结果/取消；不持久保存 URL 明文、参数、网页正文。网络读取的 URL 保存摘要。网页抓取及 MCP 安装提议不计作成功业务工具经验来源，不能冒充检测/报告操作证据。

## 配置与迁移

功能默认关闭。先显式执行 V25 两表迁移，再配置：

```dotenv
AGENT_LOCAL_MCP_ENABLED=true
AGENT_LOCAL_MCP_PYTHON=已有Python解释器绝对路径
```

AI 聊天工具还需开启 AgentScope 和持久运行日志；主站管理页面和手动握手检查不调用生成模型。沿用 workspace，不额外安装到 C 盘。

```powershell
./scripts/run-python.ps1 script/shell/migrate-local-mcp.py --apply
./scripts/run-python.ps1 script/shell/migrate-local-mcp.py
```

本地入口仅允许已配置的本机 doorhandledb，核对根 SQL 与 App classpath 副本，可重复运行。应用启动只检查表，不自动迁移；关闭功能保留文件、状态与审计。

接口 `/api/agent/mcp/fetch`：GET 本人状态；POST `/install` 为固定安装、`/enabled` 为启停、`/probe` 为握手。写请求需 `X-MCP-Action: update`，响应不缓存。没有公开 shell、包名、用户目录或远程 URL 的修改接口。

## 验证

完整回归 425 项：409 通过、16 个可选集成检查跳过，0 失败/错误，见 `work/local-mcp-full-verify.log`。最后关于已安装提示、启停必填字段及排除 MCP 经验来源的回归 27 项通过，见 `work/local-mcp-final-targeted.log`。

真实安装验收完成：测试员工 inspector.demo（账号 18）保留 46 个包与 65 份版权文件，初次安装和显式启停/握手、另一个账号不可复用、手机布局、冲突及匿名拒绝的八项浏览器检查通过，无 JavaScript 异常。证据 `work/local-mcp-browser-acceptance.json`，截图已复核。测试主管保持未安装，不为所有用户预装。

单独启用 `LocalMcpMysqlTest` 通过真实 MySQL、主 Harness、原生 Stdio、公开 example.com 网页返回及 TOOL_COMPLETED 轨迹；模型响应脚本化，没有调用付费生成模型，见 `work/local-mcp-sdk-mysql.json`。验收后测试员工保留安装但停用，可在页面主动启用。SDK 关闭连接时出现一次进程退出 code 1 警告，握手、网页抓取及客户端清理检查通过，未屏蔽日志。

远程 MCP、其他服务器的通用注册、凭证管理、OS 沙箱、完整语义/对抗 Eval 和可靠跨实例后台队列仍待开发。

最终应用已重新打包并启动，六项本地健康检查通过，见 `work/local-mcp-final-start.log`。主站 47 项检查及两套前端生产构建通过；独立 Agent UI 登录后加载无 JavaScript 异常，共享卡片工具模块保持可读，见 `work/local-mcp-agent-ui-check.json`。两端开发服务器对本人 Stdio 文件的匿名访问及大小写变体共四项均返回 403，见 `work/local-mcp-files-private.json`。实际 SDK/网页及浏览器验收结束后未发现遗留的 mcp_server_fetch Python 进程。改动仍在 java 分支，未提交。
