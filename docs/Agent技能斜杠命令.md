# Agent 技能斜杠命令

`java` 单体的主站聊天和独立 Agent 页面已接入 `/` 菜单与后端命令解析。当前可选择的是本项目经审核发布的业务经验 Skill，按当前账号角色提供。新增 `/skills install 公开链接` 打开本人页面确认下载；已审核的本人 LINK 技能进入命令目录，卸载在页面确认执行。脚本/附件运行仍未接入，ZIP 上传继续保持移除。见 [链接下载安装](外部Skill链接下载与受控安装.md)。

## 使用方式

在聊天输入框输入 `/`，选择命令或已发布技能，补全后再发送。主站支持上下方向键、Enter/Tab 补全及 Escape 关闭菜单；中文输入法确认不会发送消息。Agent 页面复用 Sender 原生建议菜单。

| 命令 | 行为 |
| --- | --- |
| `/help` | 查看命令帮助 |
| `/skills` 或 `/skills list` | 列出当前角色可用的已发布技能 |
| `/skills info 技能名或skill-id` | 查看对应技能的发布版本、适用工具和正文 |
| `/skills manage` | 显示技能演化管理入口 |
| `/skill 技能名或skill-id` | 明确读取对应技能，返回经验步骤 |
| `/skill 技能名或skill-id 你的问题` | 先核对并加载对应技能，再由 AgentScope 处理问题 |
| `/技能名 你的问题` | 上一命令的简写；同名技能必须使用唯一 skill-id |

例如，发布名为 `task-progress` 的经验技能后，可发送 `/task-progress 查询当前任务进度`。实际可用名称以 `/skills` 和输入框目录为准，未发布、已停用或其他角色的技能不能调用。

`/skills` 的文字列表最多显示前 15 个，输入框目录最多提供 100 个。名称与内置命令冲突或存在同名发布记录时，菜单补全 `/skill skill-id`。选择菜单项只填写输入框，发送前不调用模型或执行工具。

## 实现与权限

- 目录接口为 `GET /api/agent/commands`，需要登录并返回 `Cache-Control: no-store`。仅返回发布版本的名称、编号、描述、版本和适用工具，不返回来源账号、私有运行、草稿正文或版权历史。
- 只解析本轮最后一条用户消息。历史助手回答、RAG 和工具资料中的 `/` 文本不会被当作当前命令；AG-UI 不接受助手消息作为最后一条问题。
- 帮助、列表、管理入口、无效命令和无参数正文读取由服务端直接回复，不启动模型。主站命令也跳过 RAG、Mem0 检索及自动记忆提取。
- 明确加载按当前业务账号角色、发布状态、来源类型、内容摘要、证据和规则 Eval 重新核对。发布指针在事务中锁定，同名查询最多匹配两条，存在歧义就拒绝。私人草稿、历史上传版本、已停用记录和其他角色技能不可选。
- 带问题的调用将已核对的经验正文作为本轮参考加入原有 HarnessAgent 提示，问题继续走 AgentScope 原生流式执行和既有工具授权。经验不能新增工具权限、增加文件/脚本能力或替代人工确认及业务审批。
- 命令读取属于应用层明确加载，记录为 `COMMAND_LOAD`；原 SDK `load_skill_through_path` 加载仍单独记录为 `LOAD`，不把命令加载伪称为 SDK 自动工具调用。

运行日志新增 `COMMAND_RECEIVED`、`COMMAND_REJECTED`、`SKILL_COMMAND_LOADED`。仅保留归一化命令类别、拒绝状态、技能编号、版本及摘要，不保存问题参数、URL 或经验正文。Skill 加载审计绑定实际运行和调用编号，已结束、失败、取消或他人的运行不能新增加载记录；之后回答失败不会撤销已经发生的读取。加载次数只表示实际读取，不是任务成功率或模型遵循程度。

## 开源复用与界面

沿用项目固定的 AgentScope Java 2.0.4 和 `@agentscope-ai/chat` 1.1.72；已检查当前安装包的 Apache-2.0 许可证与 Sender `suggestions`、受控输入及选择行为。React 直接复用原生菜单，Vue 沿用现有 ChatComposer 并共享命令目录转换函数。没有引入其他 Agent 引擎。

主站窄抽屉默认收起会话列表，避免输入框被挤成零宽；仍可手动展开会话列表或拖宽面板。命令菜单带出现/消失过渡，支持减少动态效果，Escape 关闭菜单时保留聊天窗口。

## 验证

- `mvn -B verify -Dagent.skills.commands.mysql=true -Dagent.skills.commands.keep.fixture=true` 完成：428 项中 411 项通过、17 项显式集成检查跳过，0 失败/错误，日志 `work/skill-commands-full-verify.log`。
- 实际 MySQL 与 AgentScope Harness 的 `SkillCommandLocalMysqlTest` 通过：发布版本先加载再进入模型、角色拒绝、版本审计、私人运行记录和原生流式回答。使用脚本模型，不请求收费供应商；结果 `work/skill-command-local-mysql.json`。
- 主站 49 项检查、Agent 页面 3 项检查和两套生产构建通过。主站窄侧栏修复及 Escape 行为通过实际浏览器验收，保留现有构建大包提示。
- 带点号账号的操作确认列表改用与运行日志一致的会话编号校验，运行/操作编号校验与账号隔离保持原规则。最终技能、日志、确认与入口的 54 项定向回归及重新打包通过，日志 `work/skill-commands-final-package.log`。
- `scripts/diagnostics/skill_commands_browser_acceptance.py` 的 8 项实际浏览器/HTTP 验收通过，覆盖两套菜单、键盘补全、明确加载、角色拒绝、无模型的安装拒绝、脱敏日志、手机布局、加载审计及匿名保护。结果 `work/skill-commands-browser-acceptance.json`，验收样本已停用保留历史。

以上验证说明命令路由、加载、权限和传输正常，不代表真实模型对技能的理解或业务效果已经完成语义评测。不需要新增数据库迁移或环境开关；当前分支的运行方式见 [服务器运行说明](服务器运行说明.md)。
