# Agent 页面视觉优化

2026-10-21，`java-cloud` 未发布工作区。沿用现有 Vue/Element Plus 和独立 React/AgentScope Chat 入口，共用 `frontend/src/assets/agent-appearance.css`；仅作用于 Agent 页面。Element Plus 使用既有依赖，遵循其 [MIT 许可证](https://github.com/element-plus/element-plus)，本次未新增 UI 依赖。

调整会话侧栏、欢迎卡片、消息阅读宽度、浅色用户气泡、模型选择、输入框焦点及工作面板层次。空会话不再重复展示快捷指令栏，原快捷指令仍保留在已有消息的会话；修复手机空会话滚到底部的问题。保留队列、逐条引导、上传、模型选择与敏感操作确认，支持键盘和减少动态效果设置。

追加视觉调整：Agent 各页统一使用窄图标导航，返回业务系统时恢复原业务导航；对话页移除重复的业务标题栏。新增 `AgentSectionIcon.vue`，为技能、记忆、MCP、市场、模型配置及操作确认提供开源图标；蓝色为主，紫色区分记忆、青绿区分连接、琥珀色区分待确认操作。资源卡片、筛选按钮、空状态插图、技能下载区和记忆设置加入有层次的配色。`agent-section.css` 仅作用于主站 Agent 区域，独立 React 欢迎卡片同步使用对应配色。

本地预览 `http://127.0.0.1:3012/#/agent/chat` 由 Vite 连接既有 SSH 转发入口 `18088`，使用真实服务器 API，依赖两个连接进程存活。`DOORHANDLE_DEV_API_TARGET` 仅供 Vite 开发代理使用，不进入生产包，不修改服务器开放端口或默认部署方式。两入口原测试端口 3011/5175 继续保留。

## 验证

- `work/agent-appearance/results.json`：两入口桌面/手机 8 组隔离 API 浏览器检查，无页面异常，覆盖欢迎标题在视野内、空队列隐藏、上传及模型入口、消息阅读、工作面板、键盘焦点和横向溢出；截图已复核。
- `work/agent-appearance-composer-check.log`：24 项聊天交互回归通过，无页面异常，覆盖上传、模型保存/冲突核对、草稿与附件恢复、排队/引导/编辑及停止继续。
- `work/agent-appearance-node-tests.log`：132 项主站 Node 检查通过。
- `work/agent-section-browser.log`：真实 ECS 接口下的桌面/手机 20 项只读页面检查通过，覆盖八个 Agent 页面、页头图标、窄导航、账号菜单、业务导航返回、无横向溢出及全局渲染异常；截图在 `work/agent-section/`，已复核市场、聊天、技能和记忆页面。
- `work/agent-section-composer-check.log`：24 项原聊天操作回归通过，`work/agent-section-node-tests.log` 的 132 项检查通过；主站构建 `work/agent-section-vue-build.log` 通过。没有调用供应商或修改模型、记忆等业务配置。
- Vue 与 React 构建日志分别保存在 `work/agent-appearance-vue-build.log`、`work/agent-appearance-react-build.log`；最终统一发布仍须锁定提交并重新执行完整 CI。React 保留已有的大包体积警告。

## 模型管理异常修复

真实服务器尚未发布/启用新增模型管理接口，旧环境对缺失路由返回 HTTP 200、正文 `{code:404,message:...}`。原页面直接赋值 `data.versions`，导致后续 `.find()` 读取 undefined。

现对版本列表及嵌套配置进行校验，通过后才原子替换视图状态；失败时隐藏管理写操作、清除内存中的待写入 Key，并显示不可用提示。刷新只读取状态，不重放命令。`work/agent-model-unavailable-browser.log` 的 14 项检查通过，增加错误信封、空响应、缺失/损坏 DTO、HTML 正文及恢复场景；真实 ECS 响应也已在独立浏览器上下文确认不会触发全局异常或显示写操作，未执行配置更改和供应商调用。

新版页面和修复当前只在开发预览生效，生产应用未替换。主管配置管理的加密 Secret、后端开关与完整候选验收仍按五类功能计划推进，不能通过本次页面修复宣称已上线。
