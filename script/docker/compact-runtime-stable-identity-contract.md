# 候选 runtime 稳定身份准入

状态：源码及静态编译。本轮没有启动 ECS、容器、后端、数据库或测试；下述 hook 必须由维护 `compact-runtime-acceptance.py` 的主代理集成到同一固定提交，再交原 Jenkins 完整 verify-runtime 执行。没有生产迁移、人工 SQL 激活或减少原 9 场景的旁路。

## 核心 runtime 的具体 hook

`Runtime.__init__` 与其他固定源码 module 一起加载：

```python
self.stable_identity = module('runtime_stable_identity', source / 'script/docker/compact-runtime-stable-identity.py')
```

`Runtime.build_config` 在原各服务配置完成之后、写出/校验 compose 之前，把返回配置接回；该函数深拷贝，不修改生产 env 文件：

```python
config = self.stable_identity.enable_required_environment(config)
```

必须保持该设置通过现有 `bounded_config`、配置校验和最终 `dc up`，不能只是记录一个未使用的配置副本。候选 backend 强制五个开关为 true：`DETECTION_STABLE_IDENTITY_ENABLED`、`DETECTION_ASSIGNMENT_BINDING_ENABLED`、`DETECTION_IDENTITY_REVIEW_ENABLED`、`DETECTION_IDENTITY_EVIDENCE_ENABLED`、`DETECTION_IDENTITY_MISSING_NAME_REVIEW_ENABLED`。最后一个用于兼容读取已经存在的明确缺失名称证明，不会据此创建证明或自动回填。

`Runtime.start` 在原 owned target DB 已准备好、启动候选服务之前调用只读 preflight，确保缺失 control 等启动前置失败也留下有界回执：

```python
self.stable_identity.preflight(self)
```

原服务健康、现有内部网络/worker 端点/原 native 数据核对全部通过后，且进入 9 个业务场景之前调用：

```python
self.stable_identity.admit(self)
```

原 9 场景全部完成、原 worker 的真实 `report_task_id` 及 restart/restore 验证已存在之后，浏览器验收之前调用：

```python
self.stable_identity.prove_current_task(self, self.report_task_id)
stable_identity = self.stable_identity.require_receipts(self)
browser = self.browser.run(self)
```

`require_receipts` 必须在 `ASSERTIONS_PASSED`、清理和最终 PASS 之前执行；不能捕获其错误继续通过。在最终同 build 的公开 runtime proof 增加：

```python
'stableIdentity': stable_identity,
```

`stableIdentity` 是额外的必需准入证明；不要添加到 `owner['scenarios']`，不要改小原 required 场景集合。缺少任何 hook、缺少两个 PASS 文件或证据与 build/context/hash 不一致，最终门应失败。现有失败保全/原件归档和清理策略由原 runtime/CI 维护者处理，helper 不创建容器、不删数据、不改迁移状态，也不操作云生命周期。

## 准入与阻断

`preflight(ctx)` 只 SELECT 已迁移的 owned target：DATABASE、server UUID、29 表、两条原 control 与任务计数。必须沿用原 migrationReceiptSha256 和 initialTargetSnapshotSha256。它的状态是 `PREFLIGHT_ONLY`，没有授权通过含义；缺失或不一致时为 BLOCKED。原数据及 task 数量没有因为准入不便被删除或换为空库。

`admit(ctx)` 从实际 backend 容器元数据取五个开关的布尔读回；不公布其他 env。经原 Python Cookie 客户端访问真实 Nginx/后端。登录主管后调用原 `GET /api/detection/identity/preview`，`includeAligned=true`，每页 100 个任务，上限 20,000 个任务。必须完整覆盖 preflight 的已迁移任务数，分页 revision/mode 保持一致，cursor 不重复。

授权关键角色仍是原实现的 created/assignee。每条必须已有稳定用户 ID、原名与来源绑定一致、来源为 SOURCE_RECORDED，状态为 ALREADY_ALIGNED 或已有明确证明的 MISSING_NAME_CONFIRMED。CANDIDATE_ONLY、同名 suggestedUserId、账号已不存在、来源未验证或历史名称缺失均不当成可用归属。其他历史操作者角色的未知项单列数量，既不伪造，也不擅自改变原 created/assignee 授权激活门。

只有零关键缺口时才调用原 `POST /api/detection/identity/activate`，携带刚读取的 revision、`sourceProtection=true` 与保存的单次 requestId。永不调用 `/apply`，永不写 ACTIVE SQL。既有映射来源不完整时必须保留真正阻断，交原人工 review/apply 流程处理；不能生成虚构的资料编号或确认依据。激活响应、HTTP 再预览、真实 DB 的 ACTIVE/ACTIVE、版本和来源激活 revision 全部读回一致才 PASS。旧的未知激活结果保留 pending request，不自动换号重发。

目前没有就地修复或生产激活授权。即使迁移目标控制模式已经 ACTIVE，仍通过原 activate 重新核对当前映射/账号/来源条件；没有合法来源激活 revision 也不据 ACTIVE 字样声称来源保护通过。

## 真实运行证明

`prove_current_task` 使用原九场景中由真实 worker 完成的 report_task_id，不新建简化或合成成功任务。本轮四账号功能验收由 supervisor 通过真实 HTTP 创建主任务，使 inspector、peer 均可作为非创建者竞争领取；主管随后真实分派给 inspector，继续报告和 SDK 场景。必须仍在同一迁移 target/server/build、保留原任务计数并新增至少一条真实任务；实际 DB 创建者 ID/身份原名与 supervisor 对应，当前稳定受派人为 inspector，原预览返回 NEW_CREATION 来源证书，当前模式 ACTIVE/ACTIVE。

四个原有账号分别实际读回 auth ID/role、任务 progress、trace、资源历史：inspector、两主管为 HTTP 200 且任务版本相同，peer 对 progress/trace 为真实 HTTP 403/404，历史过滤列表为空。HTTP 500、业务错误包装、页面未执行或 legacy off 不能充当拒绝。报告只保留账号 alias、稳定 ID、role、状态码、版本和任务 ID 哈希；trace 中的地址、正文和签名 URL 均不归档。

三个固定公开文件：`stable-identity-preflight.json`、`stable-identity-admission.json`、`stable-identity-authorization.json`，位于原 `ctx.directory`，引用保存到 owner。错误不打印原响应/异常文本；报告最多 32 条 taskId 哈希、角色与固定原因码，数量不能冒充完整细节。`require_receipts` 重新核对实际文件 SHA、固定提交/来源/build/profile、模式、开关、四账号权限和 NEW_CREATION 稳定绑定，禁止只检查 owner 中的 PASS 字样。

## 回归登记与检查

新增 `tests_python/test_compact_runtime_stable_identity.py`，22 条 ECS CI 源码合同用例，已在固定 profile 登记且不允许 skip。覆盖未知历史、同名候选、缺来源、实际开关关闭、假激活响应、源任务数变化、数据库身份不符、旧未知请求、真实 Client 请求头绑定、500 不冒充拒绝、有限缺口、重复 cursor、来源激活版本缺失和同 build 证明防篡改。

这些 adapter 夹具只验证准入策略，不是实际 HTTP/MySQL 运行证据。真正同 build 的授权结论必须来自上述 runtime hook 的真实目标/真实接口，不把用例构造出的结果文件当验收回执。本轮只执行 Python AST/编译与 JSON/补丁检查，没有执行这些测试；没有 Java 代码变动。
