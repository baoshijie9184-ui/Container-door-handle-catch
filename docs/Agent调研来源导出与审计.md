# Agent 调研来源导出与审计

后续增加可选账号固定窗口限流，需 V35，默认关闭；额度与审计同事务提交，见 [导出限流](Agent调研来源导出限流.md)。下文验证表保留 D35 阶段记录。

更新日期：2026-10-16。分支：`java-cloud`。对应 D35 / P04 / P15。

## 操作方式

进入“Agent智能系统 → Agent执行追溯 → 调研来源”，点击“导出来源”，核对文件范围后点击“确认并保存 JSON”。取消或仅打开弹窗不会发送导出请求。独立 Agent 入口通过已有执行追溯链接进入同一页面。

导出包含本次重新读取时仍可查看的来源编号、脱敏请求地址、标题、摘录、片段范围、返回文本哈希、抓取/到期时间，以及最终回答哈希与来源标记位置。文件也标明版本、导出编号、生成时间和局限说明。已过期来源不导出内容，保留过期数量及既有回答中的历史引用标记；不包含聊天正文、完整网页、未脱敏请求查询参数、模型凭据或其他账号数据。

来源摘录仍是未受信任文本，文件格式为 JSON，不作为 HTML 或脚本执行。导出不重新抓取网页，不调用模型，也不恢复已结束运行。原“导出轨迹”仍只导出原有事件数据，与本来源文件分开。

文件下载后由用户自行保管，服务端来源过期、清理或关闭开关不能撤回已下载副本。页面显示“已发起文件保存”和文件 SHA-256，不能据此确认用户已经成功保存到磁盘。

## 权限与审计

接口为 `POST /api/agent/runs/{runId}/sources/export`，只接受 `{"confirmed":true}`，要求 `X-Agent-Action: export`，拒绝 `Sec-Fetch-Site: cross-site`。认证与现有 CORS 策略继续生效，不接受客户端传入账号、来源列表或正文。

授权使用登录账号的稳定 userId，再次检查本人运行；主管也不能导出其他账号的私人来源。不存在和其他账号的运行均返回 404。关闭导出功能时也先校验运行所有权，再返回功能未启用。

服务端读取现有来源视图并序列化文件，对实际 UTF-8 文件字节计算 SHA-256，在事务内保存审计，提交成功后才返回文件。审计表只含导出编号、账号/运行编号、格式版本、有效/过期来源数量、字节数、摘要和时间，不保存网址、摘录或回答正文。审计失败返回固定错误，不交付附件，不暴露 SQL 或异常原文。

成功响应包含 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、JSON 类型、以服务端 UUID 生成的附件名、`X-Export-Id` 和 `X-Content-SHA256`。文件上限为 512 KiB；单次来源和引用数量沿用 V31 限制，不批量导出全账号历史。

前端在保存前检查文件大小、格式版本、导出编号、运行归属、来源结构和实际字节哈希。失败或结果未确认时不自动重试，需重新确认；切换运行或离开组件后，旧请求完成也不触发下载。完整性检查需要 Web Crypto，请使用 HTTPS 或当前本机 SSH 隧道的 localhost/127.0.0.1 访问方式。

每次明确提交生成独立导出编号和审计，不承诺网络失败后重复提交仍使用同一个编号。审计成功证明服务端已生成并允许交付该文件，不能证明浏览器已收到或用户已落盘。文件哈希用于核对字节，不是数字签名，也不能证明网页结论真实。

## 迁移、配置与回退

在目标 MySQL 8 库备份并确认已有 V16、V31 后，手动执行：

```sql
SOURCE /path/to/sql/mysql/migration-V33-agent-research-export.sql;
```

该脚本只新增 `agent_research_export_audit`，不修改或清空已有来源。相同脚本打包在 AI 模块 `classpath:db/migration-V33-agent-research-export.sql`，应用不自动迁移。

配置示例：

```dotenv
AGENT_RUN_JOURNAL_ENABLED=true
AGENT_RESEARCH_EVIDENCE_ENABLED=true
AGENT_RESEARCH_EXPORT_ENABLED=true
```

`AGENT_RESEARCH_EXPORT_ENABLED` 默认 false。只有来源登记和导出同时开启时才装配导出服务；缺少 V33 则提示迁移要求并停止启动。已有 V31 部署在关闭导出时仍可正常读取，不要求 V32 或 V33。账号配额/过期内容清理另见 [存储治理](Agent调研证据存储治理.md)，不是启用导出的前提。

后端和前端应成套发布。旧来源接口没有 `exportEnabled` 时，新前端不会显示导出入口；旧前端忽略新增字段。当前同源部署直接读取校验响应头；跨域部署沿用已授权 Origin，默认已暴露两个校验头，若自行覆盖 `APP_CORS_EXPOSED_HEADERS`，需保留 `X-Export-Id,X-Content-SHA256`。

回退设置 `AGENT_RESEARCH_EXPORT_ENABLED=false` 并重启后端，按钮隐藏、接口拒绝新导出，已有来源、下载文件和审计保留。本轮不写入私有环境文件，不执行真实库迁移或云端发布。

## 开源参考与兼容性

实现前检索了 [Langfuse](https://github.com/langfuse/langfuse) 的观测数据导出方案，并通过 [仓库元数据](https://api.github.com/repos/langfuse/langfuse) 核对项目未归档且仍有维护。[许可证](https://github.com/langfuse/langfuse/blob/main/LICENSE) 区分 MIT 核心与单独授权的企业目录，因此本轮只参考导出时保留稳定编号与数据边界的思路，不复制其审计实现或引入平台依赖。

实现复用当前 Java 17、Spring Boot 3.2.4、Jackson、MySQL 和 Vue/Element Plus。附件响应沿用 [Spring MVC 的 ResponseEntity 方式](https://spring.io/guides/gs/uploading-files/)，文件名只使用服务端生成的 UUID。

## 验证及后续

后端隔离测试覆盖私有运行授权、主管越权拒绝、过期时重新过滤、保留历史引用、正文/凭据不进入审计、精确字节摘要、确认/动作头/跨站请求、审计失败不返回文件、独立导出记录以及 Spring 条件装配。

前端 Node 检查覆盖旧接口降级、格式/运行/来源约束、大小和哈希校验；隔离 API 浏览器验收覆盖取消不请求、确认下载、失败不重试、坏哈希拒绝、切换运行丢弃迟到响应和手机弹窗。验证结果见 [开发进展](../开发进展.md) 与 `work/research-export-*`。

| 检查 | 本轮结果 |
| --- | --- |
| 完整 Maven `clean verify` | 585 项：562 通过、23 个可选联调跳过、0 失败/错误；13 个模块构建成功 |
| 主站 / 独立聊天 Node | 90 / 5 项通过 |
| 隔离 API 追溯浏览器 | 75 项通过，页面 JavaScript 错误为 0 |
| 主站生产构建 | 通过 |
| V33 副本 SHA-256 | 两份均为 `85CA255B96115304DAAA46A262FF31C24853A282C6D501F786275ECB6BAB89F1` |
| `git diff --check` | 通过 |

桌面和手机确认弹窗截图为 `work/agent-trace/research-export-confirm-{desktop,mobile}.png`，已查看复核；实际浏览器生成的隔离样本文件为 `work/agent-trace/research-export.json`。结果为 `work/agent-trace/results.json`，构建与检查日志为 `work/research-export-*.log`。临时前端预览进程已停止。

尚未进行真实 MySQL 的 V33 迁移、执行计划和云端端到端验收。下载频率限制已在后续 D41 增加可选实现，见 [导出限流](Agent调研来源导出限流.md)；审计记录保留期、审计查询页面、完整物理归档和备份恢复仍待补齐，P04/P15 保持部分完成。
