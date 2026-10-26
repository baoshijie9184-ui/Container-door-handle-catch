# Agent 检测模型指标与发布配置查询

更新：2026-10-16，分支 `java-cloud`。本轮补齐 P11 中检测模型评估登记与发布配置的只读查询，不涉及 LLM 供应商管理。

## 使用方式与范围

主管可向助手提出“查看模型主键 7 的登记指标与发布配置”“这个检测模型登记的 AP 是多少”“查看模型 7 配置的灰度比例”。不知道模型主键时先查询模型列表，不能把版本号、模型名称或 LLM 型号作为主键。

主 Agent 通过 `delegate_model_ops` 委派模型专业 Agent，专业 Agent 新增 `get_model_operations`，唯一参数 `modelId` 为规范正整数十进制字符串，最大 `2147483647`。拒绝零、前导零、数值类型、浮点、越界、路径字符和附加身份/写入参数。原 `list_models` 保持不变。

链路为 `AgentScope AgentTool → ModelAgentReadApi.operations → 模型模块 ModelInfoMapper → model_management`。AI 模块仅引用 contracts DTO，不直接读取模型实体或 Mapper；设备、报告、LLM 供应商的管理入口不改变。

## 返回信息

| 分组 | 字段 | 含义 |
| --- | --- | --- |
| `model` | modelId/name/version/status/defaultModel | 模型当前目录摘要 |
| 状态 | validationStatus/mlopsStatus | 已有校验与 MLOps 状态记录 |
| `evaluation` | dataset、precisionScore、recallScore、mapScore、f1Score、avgInferenceMs | 测试集标签及登记指标，来源是数据库现有字段 |
| `rollout` | strategy、configuredPercent、abGroup、rollbackFromModelId | 发布策略、配置比例、A/B 分组及回滚来源模型主键 |
| `usage` | count、lastUsedAt、publishedAt | 数据库登记的使用次数和相关时间 |
| 读取信息 | queriedAt、invalidFields | 本次读取时间与被隐藏的异常字段名 |

SQL 显式选择上述列，不读取或返回模型文件路径、创建人、更新说明、校验自由文案和兼容性备注。按主键等值读取，无额外扫描、聚合或新增索引。

Precision、Recall、mAP、F1 合法范围为 `[0,1]`，平均耗时和使用次数为非负整数，配置比例为 `[0,100]` 整数，回滚来源为正整数模型主键。非法登记数值隐藏为 null，同时在 `invalidFields` 中标记固定字段名；异常策略/校验/MLOps 枚举同样隐藏并标记，原始异常值不作为查询结果发送。

缺失值保持 null，不填入零、100% 或默认策略。`0`、`0 ms`、`0%` 都是有效登记值，不能按真假值判断是否缺失。查询不会更新模型、补录默认值、运行评估或递增使用次数。

## 展示和权限

成功业务工具结果生成 `MODEL_OPERATIONS` 引用，引用只保存工具名及模型主键；沿用版本 1 `AGENT_CARDS` 信封、原聊天表和当前每轮/每卡限制，没有新增迁移。模型回复中的虚构编号或布局不会形成引用。

2026-10-25 按用户确认，两套聊天界面以 AP 为主指标，读取兼容字段 `mapScore` 并使用两位小数的百分比格式；Precision、Recall、F1 如有历史登记或异常标记，仍可展开核对。接口字段不改名，不推定通用历史登记的 IoU 阈值或评估协议；AP50/AP75 不由 AP 推算。其余配置在“查看发布配置与登记信息”中展开；评估数据集和分组是纯文本，不能注入 HTML 或外链。异常数值显示“需核对”，缺失值显示“未记录”，不将未知状态渲染为正常结果。训练资料和兼容边界见 [AP 指标口径](检测模型AP指标口径.md)。

查看模型使用固定主站路由 `#/models?modelId=<id>`，进入已有详情抽屉。没有发布、回滚、修改比例、下载或删除按钮；展开与刷新不执行业务写入。界面沿用白蓝风格、已有卡片过渡和 `prefers-reduced-motion`。

模型读门面要求主管身份，员工工具目录不注册该查询。卡片刷新通过现有解析接口重读当前账号角色及模型状态；降权不访问模型门面，删除或拒绝隐藏对象，失败清空旧视图并显示通用错误，不返回文件路径或原始异常。

启用持久运行日志时复用授权、工具开始/完成/错误和父子调用元数据，不记录指标正文或参数；授权审计失败阻止执行。只读卡片刷新不重放模型或专业工具执行。

## 登记信息与真实执行的区别

现有 `recordEvaluation` 接口保存用户提交的指标，`configureRollout` 保存发布策略字段。检查当前 Java 与 Python 执行代码后，尚未看到消费 `CANARY/AB_TEST` 配置进行真实检测流量分配的实现。因此本工具和卡片明确描述“登记值”和“配置记录”，不能声称已完成灰度分流、线上 A/B 或实际回滚。

卡片固定说明“指标为登记值 发布策略为配置记录 实际分流尚未核验”。MLOps 为 `ROLLED_BACK` 也仅表示存在回滚登记，不能证明线上流量已改变；`defaultModel` 不能证明这一次检测实际用了该模型。

库中没有独立评估记录版本、指标采集时间、数据集指纹、完整评估协议或采样硬件信息。本轮不补造这些证据，不据此宣称两个模型可直接比较、某个模型更优或线上耗时达到登记值。查询时间与发布时间不能当作评估时间；登记使用次数不能直接当作吞吐或完整线上调用总数。

## 开源与兼容

开发前核对 [AgentScope Java v2.0.4 工具接口](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/docs/v2/en/docs/building-blocks/tool.md)、[该版本发布记录](https://github.com/agentscope-ai/agentscope-java/releases/tag/v2.0.4) 和 [Apache-2.0 许可证](https://github.com/agentscope-ai/agentscope-java/blob/v2.0.4/LICENSE)。保持现有 SDK 和前端依赖版本，复用固定自定义卡片入口，无新增运行依赖或复制第三方源码。

## 验证与剩余事项

新增测试覆盖白名单 SQL 列和主键参数、主管限制、零值及缺失值、异常数值和枚举隐藏、工具输入与异常脱敏、真实 SDK 委派调用/卡片收集、引用持久格式、账号降权和对象删除后隐藏、授权审计失败阻断。前端检查覆盖比例精度、类型拒绝、零值与缺失值以及受控路由。

完整 Maven `clean verify` 共 539 项：516 通过、23 项可选真实模型/数据库联调跳过，0 失败/错误，13 模块构建及后端打包成功；主站 Node 87 项与独立聊天 Node 5 项通过。两套生产构建成功，React 保留既有大包提示；日志为 `work/model-operations-full-verify.log` 和 `work/model-operations-{vue,react}-{tests,build}.log`。

浏览器验收使用隔离 API 样本，扩展 `script/diagnostics/agent-resource-cards-acceptance.py` 验证两套界面的历史恢复、指标、配置展开、缺失/异常记录、手机布局、减少动画、权限失效与恢复；累计设备/目录/告警/模型运营卡片 120 项通过，0 JavaScript 异常、0 模型或业务写请求。结果位于 `work/resource-cards/results.json`，日志 `work/model-operations-browser.log`，截图 `work/resource-cards/{vue,react}-model-operations-{desktop,mobile}.png` 已复核，测试临时前端进程已关闭。

本轮未向 ECS 发布，未连接真实数据库或调用付费模型。真实云端指标读取、MySQL 执行计划、供应商语义路由、评估证据与实际灰度分流仍待后续开发或验收；不能以固定响应的 SDK 测试替代真实模型效果评测。
