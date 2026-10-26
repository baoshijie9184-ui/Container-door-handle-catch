# 系统与 Agent 演示数据预览

> 后续更新：用户已授权并完成真实 ECS 入库。本文记录此前虚构预览阶段，不代表当前数据状态。原入口现已切换真实服务；此前入口保存在 work/demo-data-20261025/index-preview-archived.html，虚构数据仍只作为历史页面样例。参见 [真实资料入库记录](真实资料入库记录-20261025.md)。

2026-10-25（UTC+8），`java-cloud`。用户要求先添加一批系统与 Agent 数据，当前 IDE 打开截图图集。用户已确认选择“当前页面预览”，本地只读演示数据已接入；未向 ECS 导入数据。

## 数据范围

同一套确定性演示资料包含 12 个任务、4 份报告、4 个模型、6 台设备、6 位人员、6 个会话/48 条消息、8 个工作项及 3 个文件元数据。任务关联批次、工单、采集设备、人员、模型和报告，覆盖正常放行、待复核、待返工、待复检、暂挂、部分失败、失败、排队及执行中。

Agent 资料包括计划、任务清单、待回答/已回答问题、已完成的专业任务场景、文件产物、后台任务和中断待核对场景。用量保持未知，不伪造供应商消耗、真实 SDK 状态、权限确认或工具回执。文件包含 Markdown、CSV 和 JSON 预置正文。所有名称/正文明确标为演示，模型指标为虚构值，图片是 SVG 示意图，不能用于论文真实性能论证。

## 查看入口

- [本地入口页](../work/demo-data-20261025/index.html)
- 系统：`http://127.0.0.1:3002/#/home`
- 主站 Agent：`http://127.0.0.1:3002/#/agent/chat`
- 独立 Agent：`http://127.0.0.1:5175/`
- [同批数据 JSON](../work/demo-data-20261025/batch.json)

原 3001/5174 页面与 ECS、MySQL、OSS 都没有改动。新端口仅绑定本机；演示 API 是标准库编写的进程，不连接真实服务，不安装依赖。数据保存在代码和导出 JSON 中，重启可重建，不是数据库业务记录。普通查询、筛选、翻页及查看详情可使用；发送、保存、审批、上传和安装会被拒绝，业务卡片解析 POST 仅为读取演示资料。

脚本：[数据定义](../script/fixtures/system_agent_preview.py)、[只读 API](../script/fixtures/serve_system_agent_preview.py)。启动前先核对端口空闲：

```powershell
python script/fixtures/serve_system_agent_preview.py --port 18089 --export work/demo-data-20261025/batch.json
```

在独立终端分别启动现有前端（工作目录对应 `frontend` 与 `frontend-agent`），只给这两个进程设置代理目标：

```powershell
$env:DOORHANDLE_DEV_OPEN_BROWSER='false'
$env:DOORHANDLE_DEV_API_TARGET='http://127.0.0.1:18089'
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3002 --strictPort
```

```powershell
$env:DOORHANDLE_API_TARGET='http://127.0.0.1:18089'
$env:VITE_BUSINESS_LOGIN_URL='http://127.0.0.1:3002/#/login'
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5175 --strictPort
```

API 使用独占监听，避免 Windows 上重复进程共用端口而读到旧数据。关闭时只停止本轮预览进程，不停止原服务。

## 验证边界

已通过现有浏览器助手读取主站首页、检测记录、报告、模型、设备、人员和两套 Agent；另从 3002/5175 经 Vite 读取 18089 演示 API，复核实际页面接线。截图属于本地演示，不是 ECS 验收。未运行测试套件、构建、迁移或部署，没有模型请求和真实业务写入。

本批不提供全部功能的后端模拟；个人记忆、MCP、真实执行轨迹等未覆盖接口仍可显示未配置/不可用，不代表真实服务异常。不宣称本预览证明多用户隔离、审批、执行恢复或长期记忆有效。若后续选择服务器演示数据，需要重新核对服务器、备份和当前接口，只新增可识别记录，不能直接把虚构审批/检测成绩或旧种子 SQL 覆盖到现有业务库。
