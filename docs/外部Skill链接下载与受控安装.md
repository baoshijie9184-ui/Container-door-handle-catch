# 外部 Skill 链接下载与受控安装

2026-10-14，`java` 模块化单体已接入第一版公开链接下载。入口为「Agent智能系统 → Agent技能演化 → 从链接安装 Skill」。ZIP 上传接口保持 HTTP 410。

## 当前支持

- 公开 GitHub 目录：`https://github.com/组织/仓库/tree/分支或提交/技能目录`，目录必须含 `SKILL.md`。分支或标签名称目前限单个路径段。
- 魔搭 `https://modelscope.cn/skills/@anthropics/skill-creator`：按应用已核对的映射定位至 `anthropics/skills` 的 `skills/skill-creator`，不是任意魔搭页面的通用下载解析器。
- 将分支解析为固定 40 位提交，只读取该提交的 Git tree 和原始文件。逐文件核对 Git blob SHA-1，再记录本地 SHA-256；保存目录内及继承的 LICENSE、NOTICE。
- 单包最多 96 文件、4 MiB 总量、单文件 1 MiB。拒绝链接、子模块、路径穿越、Windows 保留名、大小写重复路径、重定向、非公开地址和未经许可识别的包。
- 当前许可识别为 Apache-2.0、MIT、BSD 文本模式；这只是受支持格式检查，主管仍须阅读保留的许可及适用条件，不能代替法律判断。

## 下载、审核与使用

1. 用户填写来源与目标角色，页面二次确认后下载。员工只能选择员工角色。账号由认证上下文决定，不接受客户端指定存储账号。
2. 下载状态持久化为 `DOWNLOADING → DRAFT_CREATED`，失败为 `ERROR`。请求编号与参数摘要绑定，重放同一请求读取原记录，不重复安装；失败后重新下载使用新编号。
3. 固定包保存在项目工作区 `users/<userId>/skill-downloads/<downloadId>/`，此目录不参与 SDK 自动发现。下载完成后创建 `source_type=LINK` 私人草稿，证据与成功业务运行来源分开。
4. 本人运行规则 Eval、提交独立审核；另一名主管核对原文、固定提交、许可、适用性与权限后发布。草稿、规则通过版本均不能加载。
5. 发布后仅安装账号在匹配角色下可读取该 Skill，仍经 AgentScope Java 原生 `load_skill_through_path`。每次加载重新核对发布指针、评测、来源证据和本地文件摘要，文件被改动则拒绝加载。
6. `/skills` 目录包含本人已审核且角色匹配的链接 Skill；`/skill 名称或skill-id 问题` 复用现有明确加载与审计。同名时须使用 skill-id。
7. 本人可确认卸载，清空发布指针、撤回尚未审核的提交，并保存卸载审计。下载包、许可、版本和审核历史保留；卸载是停止后续加载，不删除当前轮已经读取的上下文。

聊天支持 `/skills install 公开链接`，也提供只读工具 `propose_linked_skill_install` 生成预填来源的确认入口。两者都不直接下载、不代用户确认或启用。聊天正文、外部网页或包内指令不能替代页面确认。

## 原生能力和边界

开发前核对 [AgentScope Java 2.0.4 Skill 仓库及账号目录设计](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/harness/skill.md) 和 [Apache-2.0 许可](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。本项目复用现有只读 `SkillSnapshotRepository`、审核事务、SDK 原生加载和工具权限；没有添加另一套 Agent 引擎。

外部文件属于数据，不把其指令作为开发或系统授权。下载器使用已有 requests、PyYAML 环境；不运行包内安装、构建脚本或依赖命令。包内 allowed-tools 不授予权限。

**脚本、references、assets 当前只下载存档，SDK 只允许读取正文。** 所以 skill-creator 可以下载、核验并进入审核，但涉及脚本生成、打包和附件的完整工作流仍属于 N02，不能称为完整可执行安装。

新下载当前生成独立私人草稿，不覆盖旧发布版本；同一原技能内的固定来源升级、自动版本比较、更多市场适配、物理文件清理和配额仍未完成。链接来源采用结构/权限规则检查，未验证语义效果或任意提示注入防御。

## 配置与迁移

需要已有 V16、V23、V24 与运行日志、技能演化开关。V27 只新增 `agent_skill_download`，根 SQL 和 App 资源副本一致；启动不自动执行 DDL。

```powershell
& 'D:/ruanjian/anaconda3/envs/leetcode/python.exe' script/shell/migrate-local-skill-links.py --apply
```

本地 `.env` 配置 `AGENT_SKILL_LINK_ENABLED=true`、`AGENT_SKILL_LINK_PYTHON` 指向已有 Python；示例默认关闭。回退先关闭链接下载开关，保留表、包和旧版本；关闭后 LINK 版本不会进入运行仓库，RUN 经验流程继续使用。

下载进程最多两个、等待队列最多八个，每个账号同时最多两项。进程超时 180 秒，5 分钟未结束记录标为失败；重启不自动重放下载。私有下载接口使用 no-store，失败不返回远端正文、环境变量或原始异常。

## 验证

- 全量 Maven verify：455 项，435 通过、20 项可选联调跳过，0 失败/错误；`work/skill-links-full-verify.log`。
- 新增 Python 下载边界 5 项，以及 H2/原生 SDK 链接来源生命周期 7 项，覆盖固定版本、许可存档、路径/链接/摘要拒绝、私人草稿、独立审核、本人角色加载、卸载与审计事务失败。旧 Skill 演化检查继续通过。
- Vue 52 项检查和生产构建通过；`work/skill-links-vue-tests.log`、`work/skill-links-vue-build.log`。
- 浏览器真实下载验收与截图结果见 `work/skill-links-browser-acceptance.json`、`work/skill-links-desktop.png`、`work/skill-links-mobile.png`。第三方脚本不执行，不调用收费模型；审核发布与篡改拒绝使用隔离 H2 样本，不自动启用真实下载包。

全量检查不代表真实模型语义收益、所有市场链接或生产并发容量已经验收；详见开发进展 P14、N02。

后续定向回归 26 项通过，包含实际原生 Harness 加载 LINK 正文、加载审计与无 shell/文件写工具检查；模型脚本化。React 5 项与生产构建通过。浏览器真实下载/页面 7 项通过，两套聊天确认导航 2 项通过；验收下载包均保留并停用。证据 `work/skill-links-final-target-tests.log`、`work/skill-links-navigation-acceptance.json`。
