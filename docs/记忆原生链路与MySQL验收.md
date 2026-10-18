# 记忆原生链路与 MySQL 验收

2026-10-18，UTC+8，`java-cloud`。本轮继续补齐长期记忆的真实链路，不替换 AgentScope Java，不更换模型或密钥，不部署中间版本。

## 修正的问题

### 并发审计登记

真实 ECS MySQL 8.4 的六请求并发测试复现了 `INSERT IGNORE` 后 `SELECT ... FOR UPDATE` 的死锁。重复插入可能先取得共享锁，多个事务随后同时升级独占锁；此前 H2 替身没有复现。

现改为 `INSERT ... ON DUPLICATE KEY UPDATE id=id`，直接取得已存在审计行的独占锁，保留原动作、请求编号、正文指纹、状态和时间，再在同一事务内核对并领取。只首次请求进入 DISPATCHED；未决或失败请求仍拒绝重放，成功重复请求只读回执。本轮没有增加对未知远程写入的自动重试。该登记方法同时被编辑、删除、治理、审阅决定和自动提炼使用。

锁行为依据 [MySQL 8.4 InnoDB 官方说明](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html)。不把本次特定竞争验证推广为所有事务永不死锁。

### 生产 SDK 初始化和模型参数

开发配置的 Mem0 源码与 PyPI 固定 2.0.19 实现存在差异。生产版本不接受 `is_reasoning_model` 构造参数，过去只测试手工合成配置时未覆盖。现生成配置前核对实际 `OpenAIConfig` 构造签名，只在支持时传入，不以捕获 TypeError 后重新初始化存储的方式兜底。

真实请求还确认 `kimi-k3` 拒绝 SDK 通用路径默认的 temperature=0.1。现在仅对 `kimi-k3`、`kimi-k2.7-code` 配置 temperature=1.0、top_p=0.95；其他模型保留原参数。取值参照 [百炼 Kimi 默认参数](https://help.aliyun.com/zh/model-studio/kimi-api)，并经真实请求核验。开发 SDK 可显式选择思考参数路径，PyPI SDK 继续走其原生兼容路径；未修改任何项目外 SDK 源码。

### 自动提炼等待预算

真实三会话提炼有一轮在 15 秒内完成；再次验证时出现两次 15 秒超时，均保留 NEEDS_REVIEW，没有自动重放。现将提炼模型与 Embedding 的等待配置分开：

| 配置 | 当前默认 | 边界 |
| --- | --- | --- |
| `MEM0_PROVIDER_TIMEOUT_SECONDS` | 15 秒 | Embedding 单次 SDK 请求，0.1–120 秒 |
| `MEM0_EXTRACTION_TIMEOUT_SECONDS` | 30 秒 | 自动提炼模型单次 SDK 请求，0.1–120 秒 |
| `MEM0_DUPLICATE_REVIEW_TIMEOUT_SECONDS` | 30 秒 | 手动语义审阅单次模型请求，1–60 秒 |

均关闭 SDK 自动重试。自动提炼仍只等待约 3 秒就可返回处理中，后台线程持有写槽直至真实结束；超过等待时间不等于供应商停止计算，也不保证费用停止。持久回执、过期标记与未知写操作不重放语义保持原样。这个配置不表示将聊天主模型超时一同延长。

## 真实 MySQL 与原生记忆 HTTP 联调

新增可选 `MemoryReviewMysqlIntegrationTest`。在原 ECS MySQL 引擎创建随机独立数据库，名称严格限制为 `doorhandle_wb_verify_` 前缀；只在这个库执行 V26 DDL。原生产业务库、用户、聊天和记忆不写入。

Java `PersonalMemoryService`、`MemoryPreferenceService` 和 `Mem0Client` 通过真实 HTTP 调用独立 FastAPI 桥接。桥接使用生产 PyPI SDK、真实 Chroma、原生历史和私有 SQLite 回执；所有目录位于本项目忽略的 `work/`，Embedding 和 LLM 在这组联调中使用固定替身，不调用收费模型。

五项全部通过：

1. 本人读取与跨账号拒绝，两个来源会话保留；一次确认产生一条审计、一次停用，相同请求只读原回执。
2. 转发代理让原生停用真实完成后丢失 HTTP 完成回包，MySQL 标为 UNKNOWN；重复提交拒绝，读取匹配 SQLite 决定后收敛为 SUCCEEDED，再次操作不重发。代理明确使用 HTTP/1.1，避免将测试协议升级错误误认为应用副作用丢失。
3. 原生正文编辑后旧建议失效，不能按旧版本停用；关闭读取设置后禁止新 AI 对比。
4. 六个相同请求同时进入真实 MySQL，最终仅一条审计、一条原生决定，生命周期只递增一次；允许其他竞争者收到明确 409，没有本次共享锁升级死锁。
5. 临时将独立库审计表改名以模拟不可用，禁止原生治理写入；随后恢复原表，审计仅保存摘要。

证据：`work/memory-review-mysql-fixed.log`、`work/memory-review-mysql-result.json`。包含 22 项原 H2 回归在内，共 27 项定向测试通过。两次独立 MySQL 测试库已按专属名称核验后清理，私人 SSH 测试隧道与桥接进程已关闭。本机业务访问隧道继续保留。

这是 ECS 引擎上的隔离联调，不是已经将新版部署到生产。最终生产账号、会话、重启和审计验收仍须在统一发布后执行。

可复验入口：先运行 `script/diagnostics/workbench-mysql-environment.py prepare`，启动 `script/diagnostics/memory-review-test-bridge.py --directory work/新的独立目录 --port 18091`，在项目私有配置中组合测试库连接与桥接元数据，再以 `agent.memory.review.mysql=true` 运行上述测试类。配置路径通过 `agent.memory.review.config` 指定，项目路径通过 `agent.memory.review.project` 指定。测试拒绝非项目 work 配置、非回环数据库地址、非指定前缀和非空数据库。连接密码不得放入 Maven 参数、日志或仓库；结束后运行原环境助手 cleanup，仅清理该独立测试库。

## 真实模型与 Embedding 的三会话验证

`script/diagnostics/memory-longitudinal-eval.py` 需要显式 `--live`，使用生产 PyPI SDK、当前真实模型/Embedding 和全新 Chroma/SQLite 目录；仅使用两个合成账号，不读写已有私人记忆。单次最多 3 个模型调用和 18 个 Embedding 操作，SDK 不重试。示例：

```powershell
D:/ruanjian/anaconda3/envs/leetcode/python.exe script/diagnostics/memory-longitudinal-eval.py --live --directory work/新的真实评测目录
```

固定顺序为第一会话记录默认 PDF、第二会话重述 PDF、第三会话增加蓝色标题，然后明确人工改为 CSV，再查询、跨账号访问、停用和到期。最后一轮 17/17 项通过：三个提炼回执成功，重复偏好没有新增记录，独立偏好单独保存；原请求重放没有新增模型调用；编辑保留来源，后续账号范围检索获得纠正内容；其他账号看不到记忆；停用或到期停止返回，未同意删除的条目仍实际保存。

最后一轮三个提炼约 9.8、7.6、15.9 秒，模型调用部分约 8.5、7.4、15.3 秒；供应商报告模型总 Token 为 24273，另有 10 次真实 Embedding 操作，其计费没有伪装为已知。这是一组固定合成样本的实测，不是延迟分位数、账单总额或容量基准。

保留之前的失败记录：首次 SDK 构造失败、参数 400、15 秒超时，以及评测脚本最初错误使用旧 `search` 参数的记录。脚本现按生产 SDK 的 filters/top_k 调用；提炼可能使用英文，蓝色语义检查接纳 blue 等价词，固定业务预期没有改为无条件通过。最终结果 `work/memory-longitudinal-live-20261018-e/result.json`、日志 `work/memory-longitudinal-live-e.log`；较早 a–d 目录不覆盖。

这组短序列不替代数周运行中的记忆稳定性、复杂冲突判断、完整业务授权或生产容器重启。前一轮语义关系评测仍为 15/16；此处的 17/17 是不同验证范围，不能相互替代。

## 其他检查与剩余门槛

ECS 现有受信镜像在离线、只读根目录、临时 `/tmp`、无生产卷的容器中通过 6 项验证，新增使用真实桥接生成配置来初始化 SDK，补上了之前的覆盖缺口。日志 `work/memory-native-governance-linux.log`。生产镜像与版本未改变。

完整 Maven `clean verify`：797 项，765 通过、32 项默认可选联调跳过，0 失败或错误。上面的 5 项新增 MySQL 联调已另以显式开关全部实跑；默认跳过不算同一次通过。日志 `work/memory-native-governance-maven.log`。前端源码本轮未改，沿用前一轮对应测试和构建；不重复收费调用或浏览器回归来增加数量。

最终 Python 全量 202 项及 6 subtest 通过，生产 PyPI SDK 的全部记忆测试 103 项通过；日志分别为 `work/memory-native-governance-verified.log`、`work/memory-native-governance-stock-verified.log`。新增检查覆盖配置构造、Kimi 参数选择、供应商预算分离及实际超时不重试。没有升级测试环境或外部 SDK。

另已运行 ECS 运维检查：磁盘约 60.87% 使用、可用约 13.46 GiB，私有配置权限及必需凭据配置符合检查；尚无新版工具的有效备份完成回执，所以整体检查仍为异常，不能声称备份恢复验收通过。凭据存在不证明已轮换或所有供应商有效。记录 `work/operations-cloud-preflight-20261018.log`。

真实备份/恢复、定时单元、完整质检正向闭环、多账号执行及最终 Jenkins 统一发布仍按 [总任务清单](系统完善任务实施.md) 继续推进。
