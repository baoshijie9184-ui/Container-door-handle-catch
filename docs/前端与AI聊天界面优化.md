# 前端与 AI 聊天界面优化

更新日期：2026-10-16。分支：`java-cloud`。

后续按用户要求细化 Harness 布局：主站增加右侧会话工作区及最近执行，独立聊天增加工作区页签和折叠快捷栏，见 [Agent 前端 Harness 布局设计](Agent前端Harness布局设计.md)。下文为原阶段记录。

## 设计与实现

主站继续使用 Vue、Element Plus；独立聊天入口继续使用 React、AgentScope Chat 与 Ant Design。后端沿用 AgentScope Java 的账号权限、会话、记忆、操作确认和业务卡片接口。

| 区域 | 调整 |
| --- | --- |
| 全站外观 | 白色面板、浅灰背景、蓝色重点，减弱网格、渐变与阴影；统一表格和输入框边界 |
| 主站导航 | 固定业务侧栏与内容滚动区，窄屏折叠为图标导航，通过原有菜单浮层访问子页面；头部增加 AI 工作助手入口 |
| 首页 | 先展示检测总览，再并排展示工作单元与重复图片复查摘要；保留原有统计接口与权限范围 |
| 登录页 | 图片介绍区与浅色登录面板分栏；说明员工、主管均可登录 |
| 主站聊天 | `/agent/chat` 内嵌完整工作区，保留业务导航；其他页面仍可打开可调宽侧边助手 |
| 对话阅读 | 限制正文最大宽度，浅色用户消息、清晰的助手正文；四张欢迎问题卡片与技能提示 |
| 独立聊天 | 可折叠历史侧栏、居中对话区、按需展开的模型与能力面板；手机保留会话选择入口 |
| 操作反馈 | 保留出现、收起和按钮反馈，支持 `prefers-reduced-motion`；独立聊天信息面板与手机历史支持 Escape 关闭并恢复触发按钮焦点 |
| 滚动 | 独立聊天避免空会话被自动滚出视野，读取历史时不强制追随新消息；正文由外层阅读区统一滚动 |

主站欢迎卡片保留点击即发送行为；独立聊天欢迎卡片先填写输入框，用户发送后调用模型。模型面板的“默认模型”表示配置优先级，实际调用以运行记录为准。主站移除了没有实时健康接口依据的“平台稳定运行”等固定提示。

## 开源参考与许可证

查阅了 DeepSeek 官方 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的以下文档及实现：

- [布局说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/README.md)
- [AppFrame.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/src/client/AppFrame.tsx)、[列宽计算](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/src/client/columns.ts)、[布局样式](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/src/client/AppFrame.module.css)
- [Conversation 设计](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-conversation/README.md)

该项目使用 [MIT License](https://github.com/deepseek-ai/deepseek-harness/blob/master/LICENSE)，版权属于 DeepSeek；仓库说明当前处于开发预览，快速迭代且可能破坏兼容性。本次参考侧栏、正文和信息面板的布局思路，在现有框架中自行实现，没有引入 Harness 运行时、插件体系或复制其源文件。

图标复用项目已安装的 `@element-plus/icons-vue`、`@ant-design/icons` 和 `lucide-react`，未增加依赖、外部字体请求或图像服务。保留依赖包已有许可证；Lucide 使用 ISC 许可证，其他许可随现有包分发。

## 验证与复现

- 主站 54 项检查、独立聊天 5 项检查通过。
- 两套前端生产构建通过；独立聊天仍有既有大包提示。
- Playwright 浏览器验收 30 项通过，JavaScript 错误为 0。

脚本：`script/diagnostics/frontend-ui-acceptance.py`。使用项目 `leetcode` Python 的 Playwright Chromium；先启动临时前端进程（主站 3011、独立聊天 5175），然后执行：

```powershell
& 'D:\ruanjian\anaconda3\envs\leetcode\python.exe' script/diagnostics/frontend-ui-acceptance.py
```

浏览器通过路由提供隔离 API 数据，覆盖登录、内嵌聊天与侧边助手、欢迎卡片、消息提交与历史恢复、折叠菜单、手机会话列表、模型面板、键盘关闭、减少动画及横向溢出。不会访问 ECS、真实业务数据或收费模型。

结果为 `work/ui-refresh/results.json`，截图在同一目录；日志为 `work/ui-vue-build.log`、`work/ui-react-build.log`、`work/ui-vue-tests.log`、`work/ui-react-tests.log` 和 `work/ui-browser.log`。

服务器保持停机，新界面尚未提交推送或由 Jenkins 发布。云端真实账号、模型流式输出及业务卡片联调需在下次启动后复核。
