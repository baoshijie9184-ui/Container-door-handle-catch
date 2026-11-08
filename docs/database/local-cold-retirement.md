# 本地固定冷存储清退开发说明

入口为 [`retire-local-cold-stores.py`](../../script/jenkins/retire-local-cold-stores.py)，服务器证明复用 [`preserve-cold-stores.py`](../../script/jenkins/preserve-cold-stores.py)。遵循 [ECS 运行约定](../ECS-only-runtime.md) 与 [本地 Jenkins CI/CD](../本地Jenkins-CICD.md)：本地编辑、构建，测试由 Jenkins 在 ECS 执行；Linux 合成后端测试不能替代 Windows 原生句柄行为验收。

2026-11-08 已实际执行：固定提交 `b756a578` 的 #109 必需源码 PASS、#107 更早全量恢复及当次新鲜 ECS 证明均已核对。v1 已清退 15,750 文件、624 空目录；v2 已清退 16,409 文件、11,377 空目录，按设计保留下面两个工具根的 8 文件/2 目录/117,235 字节，结果为 `PARTIAL_FIXED_PROFILE_PROTECTED_ROOTS_RETAINED`。原始计划、计划 SHA、逐文件同句柄意图/结果及最终回执存于 Git 忽略的 `work/jenkins/retirement-109-cold-v1-*`、`retirement-109-cold-v2-*`，不可重放已完成的执行。运输包仍供后续验收，未纳入本次删除。

## 固定范围

仅接受以下两种 profile 及其原始 inventory。inventory 按原始字节 SHA 固定，不能为清退重写清单或自动推断其他目录。

| Profile | 原始文件数 | 原始字节数 | 树根数 | inventory SHA-256 |
| --- | ---: | ---: | ---: | --- |
| `cold-store-originals-v1` | 15,750 | 12,547,814,103 | 70 | `d31a1359676053b4182a0e4a9d15d8647cf17f93b2bc26bd7e84ce01116e2f6d` |
| `cold-store-history-v2` | 16,417 | 486,493,287 | 4,041 | `61a9dddc73bbcd15be4dd6ad0cb11aed3ad805862eb99c4940ecf321df25f33a` |

v2 固定保留两个 `TOOL_RECEIPT_STORE_COMPLETE_TREE_OWNERSHIP_UNPROVED` 根：

| 根编号 | 项目内相对路径 |
| --- | --- |
| `tool-1675` | `work/llm-management-20261104/tools-docker-02` |
| `tool-1676` | `work/llm-management-20261104/tools-docker-03` |

两根共 8 项文件、2 个目录、117,235 字节，整根保留，包含的数据库文件不因已有云端字节保全而获得本地删除权限。其余 4,039 根为 v2 可选清退范围；结果须为 `PARTIAL_FIXED_PROFILE_PROTECTED_ROOTS_RETAINED`，通过 `rootsSkipped`、`retained` 和 `entireProfileRetired=false` 明确保留范围。服务器云端恢复证明仍核验 v2 全部 4,041 根。

范围不包含 C 盘共享 MySQL/Redis、既有 5,599 文件及额外 36 文件保全范围、PTH 模型，也不包含 Git、Jenkins、共享中间件和受保护 checkout。SQL 数据库 `DROP` 属于另一批独立操作，本执行器不提供该能力。

## 计划与执行

默认生成 `PLAN_ONLY`，不初始化 Windows 删除后端或 SSH 连接。执行必须显式传入 `--apply`、已核对计划及其原始文件 SHA，以及当前真实 PASS 和更早构建的同 profile 云端公开保全回执。计划绑定 inventory、执行器、冷存储 helper 和两份回执，任一变化均拒绝。

执行器没有默认 ECS 地址。`--apply` 必须通过 `--ssh-host` 显式提供本次启机后实际回读的地址，不能沿用上次停机前的公网 IP；固定主机密钥与实例、机器身份门禁仍须全部通过。

以下为 PowerShell 参数示例，所有尖括号内容均需替换；输出目录必须在项目 `work/jenkins` 内，每次使用不同且尚不存在的目录，父目录须已存在。

```powershell
python -I -B script/jenkins/retire-local-cold-stores.py `
  --profile cold-store-originals-v1 `
  --inventory "<该profile原始inventory绝对路径>" `
  --current-receipt "<当前PASS>" `
  --custody-receipt "<旧public>" `
  --output "D:\AI\lunwen1\DoorHandleCatch\work\jenkins\cold-plan-<唯一编号>"

python -I -B script/jenkins/retire-local-cold-stores.py `
  --profile cold-store-originals-v1 `
  --inventory "<同一原始inventory绝对路径>" `
  --current-receipt "<当前PASS>" `
  --custody-receipt "<旧public>" `
  --apply --plan "<计划目录>\plan.json" --plan-sha256 "<计划SHA>" `
  --ssh-host "<已准入ECS地址>" --ssh-user "<既有SSH用户>" `
  --ssh-key "<项目内SSH私钥路径>" --known-hosts "<项目内已核对主机密钥文件>" `
  --remote-root "<既有ECS CI根目录>" `
  --output "D:\AI\lunwen1\DoorHandleCatch\work\jenkins\cold-apply-<唯一编号>"
```

v2 使用 `--profile cold-store-history-v2` 及该 profile 对应的原 inventory、旧 public，其他门禁相同。凭据和运行环境不进入计划、审计或版本库。

## 预检、现场证明与删除

执行先排除受保护根及跟踪源码，检查活动引用，再持有全部目标目录和全部文件句柄。文件使用 Windows `READ | DELETE`、`ShareMode=0` 的同一独占句柄；全部文件的身份、原始 SHA、字节数和目录成员均通过预检后，才允许第一次删除，所有剩余目标的句柄持续持有。

现场证明通过固定主机密钥文件认证的 SSH 获取，隔离外部 SSH 配置，并先核对服务器 helper 原始 SHA。`fresh-retirement-attest` 复核当前固定源码真实 PASS、实际 ECS 身份、严格更早的保全构建、全部逐根恢复与临时恢复清理证据，以及当下 inventory、manifest、archive 三份原始输入 SHA；只读验证，不创建恢复资源或改写服务器证据。`proofDigest` 是完整性摘要，真实性来自本次已认证 SSH，离线自报 JSON 不获准入。

首次及后续刷新均使用新 64hex nonce，固定同一 `current` / `custody` 绑定，每次证明 TTL 最大 300 秒。执行按单调时钟距上次请求 120 秒，或 UTC 有效期剩余不超过 60 秒时刷新现场证明；每次刷新仍完整核验所有根和当前归档 SHA。刷新或校验失败，在下一项删除前停止。每条删除意图先审计、flush、fsync，再次确认 TTL 后才调用删除 API。刷新本身的审计落盘若耗尽新证明时效，同样停止，不延长旧证明或自动回退使用旧响应。

每个文件仅由已验证的原句柄执行 disposition 并关闭确认，保留意图与完成记录；不先释放独占句柄再按路径 unlink。目录仅处理 inventory 中的目录，自深向浅复核原目录身份并确认当前为空，交给内核执行空目录 disposition；未知剩余成员阻止该目录删除，不使用递归删除或 `DELETE_ON_CLOSE`。

## 已验证的只读文件

共享句柄后端也供固定旧原件清退器使用。仅当已核对的文件 `fingerprint[7]` 含 `FILE_ATTRIBUTE_READONLY` 时，删除用的初始独占句柄额外申请 `FILE_WRITE_ATTRIBUTES=0x100`。这是取得权限，不是改写属性；字节打包的只读句柄、普通文件以及目录的权限保持原样。微软的 [FileDispositionInformationEx 规范](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4c26c8cb-5a8f-4339-a372-b315c4974131) 要求只读删除同时具备忽略只读标志与该访问权限。

含只读文件时，`WindowsBackend.hold` 在首次原生句柄调用前检查 `sys.getwindowsversion().platform_version`：必须是三个非负整数且不低于 Windows 10 1809（10.0.17763）；版本缺失、未知或过旧均拒绝。普通文件不增加该检查。该版本门只核对已公开的系统支持边界，不声称已实际执行过删除 API。

只读文件由同一已持有、全量摘要与身份均通过预检的句柄执行 `FileDispositionInfoEx=21`，缓冲区为固定4字节 `Flags=0x11`（`DELETE | IGNORE_READONLY_ATTRIBUTE`）。不使用 POSIX 或 ON_CLOSE 标志。普通文件与空目录继续使用 `FileDispositionInfo=4`、1字节 BOOLEAN。结构和标志参见微软 [扩展删除结构说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddk/ns-ntddk-_file_disposition_information_ex) 与 [句柄信息类枚举](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ne-minwinbase-file_info_by_handle_class)。

属性或FileID漂移在预检时拒绝，不借扩展标志覆盖变化。接口失败不改属性、不按路径强制删除、不重开句柄、不降级重试；原句柄留待所属持锁上下文释放。关闭失败时不移除持有记录、不记为已确认删除，按未确认 disposition 保留审计并停止。版本支持边界也可交叉核对微软 [STL 文件系统实现](https://github.com/microsoft/STL/blob/main/stl/src/filesystem.cpp) 中的 Windows 10 1809 注释；这里不采用该实现的旧系统降级或改属性分支。

## 失败与证据

计划、审计和结果写入新建私有输出目录。审计记录已确认删除量、disposition 尝试量及未确认量。删除后回读失败、关闭结果不确定、刷新失败或后续成员漂移均保留已有证据与剩余数据，结果按拒绝或局部完成处理，`automaticResumeAllowed=false`。必须逐条核对本轮意图和实际文件身份后再决定后续操作，禁止自动续跑、回放或扩大清退范围。

本轮新增源码与合成测试仍需按固定提交由 Jenkins 在 ECS 验证；文档、静态检查、合成后端结果均不表示本地数据已经清退。

[`compact-acceptance.json`](../../script/jenkins/compact-acceptance.json) 约定这两个模块均不允许跳过；最小数量以同提交的登记为准。合成用例覆盖定期刷新、同一证据绑定、新 nonce、刷新失败、审计延迟跨过时效、保留根边界、执行时显式提供当前地址，以及只读权限位、扩展ABI和失败审计。Linux 合成 API 测试不调用真实 Windows 删除接口；实际通过情况以对应固定提交的 ECS 原始报告为准。
