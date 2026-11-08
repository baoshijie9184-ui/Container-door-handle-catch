# ECS 隔离验收的资源预算

本文定义单体数据库重构验收的资源准入，不代表迁移、项目测试或部署已通过。本地只编辑与构建；实测、依赖准备、测试和数据均在原单体 ECS `172.29.146.74`。原应用保持运行。本地 Jenkins 调度固定提交，ECS 启停仍在流水线外完成。

## 容量事实与判断边界

### 2026-11-08 分批回收实绩与 SQL45 下一阶段预算

`8898fae3` 的维护 #125/#126 已实际成功，两批无重叠目标，合计回收 `1,027,674,112` 字节分配量（约 980 MiB）；第二批可用 `4,465,586,176` 字节。#127 的完整源码及新 pytest 清理通过，旧源独立恢复成功，SQL45 复用随后因报告权限规则不兼容而在恢复前拒绝。补充只读窗口实测可用 `3,978,686,464` 字节；未查询或打开数据库，已实际节省停机。

SQL 双恢复的现有准入要求是原 2.25 GiB 保底，加 1.5 GiB 临时上界和 6 倍实际 SQL 原件 `11,123,119` 字节，合计 `4,093,270,554` 字节。这是下一阶段尚待满足的空间条件，不是本轮实际首先触发的权限拒绝原因。重跑源码和旧源复制还会产生本轮缓存及资料，下一窗口须先继续有界回收、再读取现场余量；不降低门限，不直接把两批维护成功记为全部峰值够用。

### 2026-11-08 历史测试输出的分批回收

维护 #124 已真实返回 `OUTPUT_EXCEEDS_BOUNDED_PLAN`，未生成计划、未尝试删除。32 MiB 是控制计划的硬上限，与云盘容量不是同一门槛；不通过扩盘或提高上限绕过。独立盘点 #120/#122 两份 pytest 清单的约 13.77 MB 只是样本，实际准入包含其他历史 source 构建，完整计划更大。

新实现继续复用既有证据、静止检查、锁、精确计划及 FD 删除协议。所有候选共用 16 MiB 目标序列化预算，先选择编译输出、依赖目录和 npm 缓存，再选择剩余额度内的 pytest 直系 case；选择顺序固定。pytest 在内容哈希前按真实元数据、路径和固定长度 SHA 占位计算清单大小，超额跳过；完整清单生成后再精确核账。每个候选最多输出 64 条跳过详情，所有跳过项仍保留总数和完整有序标签/原因摘要。每一批继续核原 32 MiB 输出硬上限，下一批只重新处理尚存目标，不重放旧计划。该修改尚待新固定提交的 ECS 实测。

### 2026-11-08 #121/#122 的实际回收与剩余门槛

60 GiB 云盘没有再次扩容。维护 #121 只回收原始证据、静止检查及精确计划共同证明的旧构建输出，计划分配量 `1,708,077,056` 字节；可用空间现场由 `2,272,301,056` 增至 `3,980,546,048` 字节。没有清业务库、备份、源码、原始报告、发布制品或共享 Maven 缓存。该维护成功不代表测试通过。

完整源码 #122 随后通过 Java、Python 和双前端验证，两套依赖目录已确认停止后删除；旧源复制恢复仍未开始。只读重算为 5,599 文件、1,315 目录、4,096 字节块：原保底 `2,415,919,104`，副本上界 `87,961,600`、独立恢复上界 `1,350,099,486`、元数据 `10,309,632`，合计要求 `3,864,289,822` 字节；实际只有 `3,447,980,032`，差 `416,309,790` 字节。原 helper 仅返回泛化 `ValueError`，这是确定未满足的空间条件，尚不能证明它就是原先首先触发的 guard。旧 #110 原始归档全 SHA、manifest SHA、私有权限都正确，未创建本轮副本或改变原件。

两轮普通 source pytest 临时目录实占分别 `245,583,872` 和 `252,342,272` 字节，#122 NPM 缓存实占 `167,960,576` 字节；它们只是候选，含负例链接或特殊文件的历史测试目录必须逐项跳过，真实可回收量仍以新计划及执行回执为准。不降低恢复预算或测试余量，也不以未执行的清理量宣称后续全部阶段够用。当前修改先处理可证明的临时积累，再测下一阶段峰值。#122 完结后实例已实际回读 `Stopped / StopCharging`；本地 Jenkins 保持运行。

### 2026-11-07 晚间实测与已授权的 60 GiB 扩容

Jenkins #80 结束后、云端停机前，只读取得根卷可用 `4,116,332,544` 字节，约 3.83 GiB；云盘仍为 40 GiB。随后从流水线外实际回读 `Stopped / StopCharging`，Jenkins 控制器及本地节点保持在线。

四份已完成的本地字节封存包合计压缩/归档 `1,140,028,586` 字节：原 5,599 文件、额外 36 文件、15,750 个历史存储文件，以及本次成功的 45 表逻辑导出。它们尚未上传，不能记为云端已恢复。若原盘不额外释放已有内容，保留这些归档后仅余 `2,976,303,958` 字节。已知运行验收阶段的 Kafka 512 MiB、受控写入 256 MiB、BGE 三份各 64 MiB，再加独立 2 GiB＋256 MiB 保底，至少要求 `3,422,552,064` 字节；这还不含实际业务库、日志及候选镜像的新层。由此已能确定当前空间不足以完成全部流程，不能只按这 446,248,106 字节的最低差额扩盘并宣称足够。

用户已明确授权将原实例 `i-2zeieuov2aum486jm1ek` 的现有 ESSD Entry 系统盘 `d-2zeieuov2aum486inund` 从 40 扩至 60 GiB，并创建一次扩容前快照；不新建实例或数据盘，不修改计算规格。扩容会增加保留云盘的存储费用，停止计算计费后仍有云盘费用。原机保持停机，已提交快照 `s-2ze024y1756m92x0yemc`，须确认云端状态完成后才扩盘；不能把创建请求成功当成快照制作完成。此处没有查询账单或优惠券。60 GiB 是给当前迁移与受控测量增加 20 GiB 余量的方案，不是已证明的完整峰值。

实际执行现已完成：快照回读 `accomplished / 100% / Available=true` 后，调用离线 `ResizeDisk`，回读同一系统盘 `Size=60`；启动原实例后核实 IMDS、机器 ID、UID、磁盘序列号及 `/dev/vda3` 的原分区标识和起点。`growpart -N` 只读预览通过，再执行 `growpart /dev/vda 3` 与 `resize2fs /dev/vda3`；两个退出码均为 0，前两分区和根分区起点/UUID 均保持一致。根 ext4 容量 `63,017,381,888` 字节（约 58.69 GiB），实际可用 `24,380,280,832` 字节（约 22.71 GiB）。私有完整 API、分区和文件系统回执保存在 `work/jenkins/data-residency-20261107/resize-60gib/`。当前原实例已启动供后续 Jenkins 验证，测试结束后仍须在流水线外节省停机；本次扩容不代表数据恢复或应用发布已通过。

实际执行顺序：回读实例和磁盘身份、盘容量、分区、ext4 文件系统及当前恢复点；在用户授权的范围内准备恢复点后调用 `ResizeDisk` 扩原盘；启动原实例，按只读检测结果扩 `/dev/vda` 的第 3 分区，再扩 ext4；分别核对云盘 60 GiB、分区、文件系统和真实可用量。现机已有 `/usr/bin/growpart`、`/usr/sbin/resize2fs`，无需安装新工具。具体在线/离线参数和恢复点费用须在执行前按当前云 API 能力确认，不能把本方案当成已授权的变更。失败时保留原始回执和数据，不格式化或重建文件系统。

扩容后仍由固定提交的 Jenkins 在每一阶段读取实际层字节、上下文分配、恢复临时量和 cgroup 峰值；超界明确失败，完成测试后在流水线外节省停机。历史存储按组串行恢复，最大约 246 MiB 的临时展开量按阶段计算，不将 12.55 GB 全部同时展开，也不拿清空未验收原件换空间。

2026-11-07 只读核对实例和机器身份后，原机 40 GiB 系统盘的文件系统容量约 39.01 GiB，实际可用约 7.88 GiB。Docker、业务数据与 `/home/ecs-user/doorhandle-ci` 在同一文件系统。当前业务 MySQL 卷物理分配约 299.41 MiB；Kafka 卷物理约 26.24 MiB、逻辑约 1.10 GiB，后者包含稀疏文件。估算新增写入时必须区分实际分配和逻辑长度，恢复程序是否保留稀疏空洞也会影响容量。

现有 CI 目录约 2.0 GiB，包含历史源码、演练、回执和备份。原容器仍引用不同历史发布目录，停止的演练容器也仍引用镜像和数据卷。镜像显示“可回收”或文件较旧不能作为删除依据。此次审计未删除任何数据。

Maven 与 Node 工具镜像已经缓存，镜像唯一层分别约 759 MB 和 231 MB；这不能证明 Maven、npm 依赖缓存已经准备好。历史 13 个 SQL 压缩快照合计约 24.46 MiB、gzip 标称解压约 147.98 MiB，不能代替本轮源库快照的实际大小。Docker 图像大小不能逐标签相加，同一个共享层也不能重复计算回收量。

原 11 个常驻容器均健康，4 个初始化容器正常退出。一次快照中，常驻容器 working set 合计约 4091 MiB，cgroup 匿名页约 2.47 GiB、当前计费内存约 4.63 GiB，主机 MemAvailable 约 12.01 GiB。各容器历史峰值相加约 4.73 GiB，不是同一时刻的负载峰值。这些快照不能证明原应用与完整测试栈在测试峰值下必然容纳。运行阶段仍须核对各进程/容器的真实限额、监测内存和 OOM。

固定“约 14 GiB 可用空间”的旧门槛是保守策略，不是系统实际峰值。空闲低于该值不能直接推出物理容量必然不足，也不能据此改成另一个较小常量并宣布足够。新预算需要实际证据，分阶段准入，保留真实余量。

## 预算模型

实现位于 [`ecs-resource-budget.py`](../../script/jenkins/ecs-resource-budget.py)。模块只有 JSON 计算和输入文件读取，不连接 ECS、不执行命令、不删除文件、不停止容器。调用方负责获得真实探针、核验摘要、建立本轮所有权，并实际实施进程组、cgroup 和增长监测。

预算锚定完整的 Git 提交号、本轮唯一 `ownerToken`、源码归档与应用 Jar 的原始字节数和 SHA-256。源库的 `allocatedBytes` 来自本轮源库实际元数据，`dumpBytes` 来自本轮已完成的快照，而非历史备份。摘要应指向已归档的测量证据，包含命令、固定提交、执行时间、目标身份、测量对象、物理字节、退出码和必要的所有权信息，不包含环境文件原文或凭据。

每个组件记录：

| 字段 | 含义 |
|---|---|
| `peakBytes` | 本阶段所需的组件实际物理峰值，或明确实施的受控测量上界 |
| `baselineBytes` | 起算探针时该组件已经存在的实际分配；不得随阶段推进移动起算点 |
| `measurement` | `MEASURED`、`ENFORCED_BOUND` 或 `NOT_MEASURED` |
| `evidenceSha256` | 实测记录或上界实施方案的已核验归档摘要 |
| `retention` | `PROTECTED` 或允许在证据归档后处理的 `OWNED_BUILD_OUTPUT` |

所有组件的起算量必须以同一基线解释，互不重复归属。根目录中的文件、Docker 卷、镜像唯一层和可写层要分别计量，禁止遍历重叠目录后重复相加。镜像使用本轮新增唯一层/未共享层；存在的共享层已经反映在磁盘可用量内。

每个阶段列出当时并存的组件。阶段新增磁盘预算为 `sum(peakBytes - baselineBytes)`；完整计划峰值取各阶段预算的最大值。已有归档和 Jar 已包含于基线实际占用，若发生额外复制，则将其新增副本纳入 `extraction` 等组件。阶段内已经发生的本轮增长从剩余预算中扣除，避免与当前真实空闲重复计算。

必须覆盖这些组件：

| 组件名 | 包含内容及保留规则 |
|---|---|
| `extraction` | 固定源码解压、副本、Jar/归档新增副本；保护源文件 |
| `maven-cache` | 本轮专属 Maven 仓库的冷缓存实际增长；本轮保留 |
| `java-output` | 一套 reactor 编译输出及当前 suite 的临时输出 |
| `suite-evidence` | 全部 suite 的原始 XML、stdout/stderr、摘要清单；保留 |
| `main-node-modules` | 主站依赖树，仅在主站阶段存在 |
| `main-frontend-output` | 主站测试报告和构建输出；保留 |
| `agent-node-modules` | 独立 Agent UI 依赖树，仅在对应阶段存在 |
| `agent-frontend-output` | Agent UI 测试报告和构建输出；保留 |
| `fixture-mysql` | 本轮 MySQL 引擎文件、schema、索引、日志及迁移数据；保留 |
| `double-restore` | 两个独立恢复目标和恢复过程中并存的临时数据；保留 |
| `runtime-images` | 当前候选应用和辅助镜像新增的唯一分配，不重复计工具共享层 |
| `runtime-writable` | 隔离业务栈的可写层、卷、Kafka/Redis/Chroma 等增长；保留 |
| `runtime-backups` | 实际源快照、恢复输入和运行栈备份；保留 |
| `logs-receipts` | 资源监测原始记录、业务证据、部署回执及失败诊断；保留 |

只有 `java-output`、`main-node-modules`、`agent-node-modules` 可以标记为 `OWNED_BUILD_OUTPUT`。保护组件一旦在某阶段出现，后续阶段必须继续列入，不能用后续预算“忘记”已存在的数据库、备份或证据。

## 串行执行与渐进实测

56 个 MySQL suite 全部执行。只保留一套所需 reactor 编译输出；每个 suite 结束，先将原始 XML 和日志逐字节复制、核对字节数/SHA-256、写入归档清单，再处理本轮拥有的可再生成编译输出。不得把 56 份完整编译结果视作同时常驻，也不得为了省空间跳过 suite 或只保留汇总数量。

主站与独立 Agent UI 分别执行依赖安装、测试、构建、报告归档。前一个项目的原始报告和输出核验归档后，才可清理它在本轮 checkout 中的 `node_modules`，随后处理另一个项目。预算校验拒绝一个阶段同时保留两套依赖树。Maven 使用本轮专属缓存，不能清理共享缓存或旧生产目录。

未知的后续阶段不要求在开始前伪造峰值。可先由 Jenkins 在本轮隔离目录中准备工具和冷缓存、跳过测试执行构建，得到真实增长，再补齐后续计划。数据库与运行镜像也按依赖顺序逐阶段测量。

首次受控测量使用 `ENFORCED_BOUND`，必须给出真实实施的阶段上界，且阶段 `enforcement` 明确：

```json
{
  "ownedProcessGroup": true,
  "growthMonitor": true,
  "memoryLimitEnforced": true,
  "maxProbeIntervalSeconds": 1,
  "diskOvershootBytes": 268435456
}
```

以上数值只是字段示例，不能作为本项目已证明的余量。`diskOvershootBytes` 需要覆盖探针间隔、写入速率、终止延迟和停止后待刷盘增长；它另加在真实 2 GiB 磁盘保底之上。布尔字段不能代替实施：调用方须校验目标进程组/容器归本轮所有，提前启动增长监测，应用实际内存限额，监测失联或终止失败立即失败，等待本轮子进程全部退出。无上界实施能力时不能将估计写为 `ENFORCED_BOUND`。

每个阶段准入只评估当前并存项，后续阶段未知不阻塞当前安全量测。当前组件缺少峰值、基线、证据或约束时，当前阶段仍失败关闭。测量完成后记录真实峰值和原始探针，将组件更新为 `MEASURED`，以同一基线生成新的计划；不得提高预算去掩盖已经发生的超界。未来阶段到达前重新准入。全部组件实测完成前，全量计划始终是 `NOT_MEASURED`，不能声称完整验收已容纳或已通过。

## 调用接口

`plan(spec)`、`validate(plan)`、`check(plan, actualProbe, phase, baselineProbe=None)` 都是纯函数。`plan` 返回包含原始 spec 的可序列化计划；`validate` 重新推导并拒绝被篡改的预算或保底。`check` 返回当前阶段准入和本轮增长检查，绝不执行删除或终止。

输入结构如下，`components` 中必须列出上表所有项；未测项保留名称、正确 retention，并使用 `peakBytes: null`、`baselineBytes: null`、`measurement: "NOT_MEASURED"` 和空证据，不填写虚构值。

```json
{
  "version": 1,
  "ownerToken": "ci-BUILD-attempt-random",
  "sourceCommit": "完整40位提交号",
  "artifacts": {
    "sourceArchive": {"bytes": 123, "sha256": "实际64位摘要"},
    "applicationJar": {"bytes": 456, "sha256": "实际64位摘要"}
  },
  "source": {"allocatedBytes": null, "dumpBytes": null, "evidenceSha256": null},
  "components": {
    "extraction": {
      "peakBytes": null,
      "baselineBytes": null,
      "measurement": "NOT_MEASURED",
      "evidenceSha256": null,
      "retention": "PROTECTED"
    }
  },
  "phases": [
    {"name": "prepare", "components": ["extraction"], "memoryLimitBytes": null}
  ],
  "baselineProbe": {
    "ownerToken": "ci-BUILD-attempt-random",
    "sourceCommit": "完整40位提交号",
    "capturedAtUtc": "2026-11-07T00:00:00Z",
    "diskTotalBytes": 0,
    "diskAvailableBytes": 0,
    "memoryAvailableBytes": 0,
    "ownedDiskBytes": 0,
    "ownedMemoryBytes": 0,
    "oomKills": 0
  }
}
```

上述是不可执行的占位示例。`actualProbe` 使用与 `baselineProbe` 相同结构，表示同一文件系统、本轮所有路径/卷/可写层的物理分配、本轮 cgroup 当前内存与累计 OOM kill 次数。必须记录真实探针时间，拒绝早于基线、容量变化、所有权或提交不符的探针。原应用不纳入本轮计数，不能通过重置基线“消除”本轮增长。节点挂载或容量改变时先重新审阅和规划。

| 返回状态 | 含义 |
|---|---|
| `INVALID` | 结构、保留规则、固定身份或计划完整性不符 |
| `NOT_MEASURED` | 全量计划仍缺实际数据；这不等于物理空间必然不足 |
| `MEASUREMENT_ADMITTED` | 当前受控测量阶段准入，完整计划仍未证明 |
| `PHASE_ADMITTED` | 当前阶段已测并可开始，未来仍有未测项 |
| `READY` | 计划全部资源项具有实际测量证据；不代表项目测试完成 |
| `PASS` | 当前已测阶段的实时资源检查通过；不代表业务验收通过 |
| `FAIL_CLOSED` | 当前阶段停止准入或终止本轮，保留失败证据 |

运行 CLI 时，`plan` 读 spec，`validate/check` 读已保存计划；`check` 额外需要探针文件和阶段名：

```text
python3 -B script/jenkins/ecs-resource-budget.py check --input resource-plan.json --actual-probe resource-probe.json --phase frontend-main
```

调用方应保存完整 JSON 和退出码，不能只读取 `action`。`READY/PASS/PHASE_ADMITTED/MEASUREMENT_ADMITTED` 返回 0，其他返回 2。只接受当前阶段合适的状态，不能把测量准入等同于最终全量证明。

## 持续检查与失败处置

每个阶段开始前、命令执行中和结束后采样真实可用空间、本轮增长和 OOM。准入要求当前真实磁盘可用量至少覆盖当前阶段尚未发生的增长、2 GiB 保底和受控测量的额外 overshoot。内存按当前阶段本轮进程/容器的合计实际限额计算，扣除已发生的本轮用量后仍保留 1 GiB 主机余量。峰值接近或超过预算、外部空间挤占、OOM、监测故障、报告归档失败都阻止后续阶段。

任何容量失败都只返回 `STOP_OWNED_ATTEMPT / OWNED_ATTEMPT_ONLY`。执行方只能终止已核验属于本轮的进程组和测试容器，保护原运行应用和其他任务，不能调用全局 `docker prune`、停止原服务或删除无归属卷。数据库、快照、双恢复、迁移结果、业务证据、回执、源文件一律保留；失败时仍先收集已有原始报告、探针和诊断。获准清理编译物/依赖树也必须先证明路径在本轮 checkout 内、非符号链接跳转，且原始报告已核验归档；预算模块不会授权或执行清理。

本模块的测试源码见 [`test_jenkins_resource_budget.py`](../../tests_python/test_jenkins_resource_budget.py)，覆盖串行峰值、未知阶段、受控测量、真实保底、超界、OOM、原始所有权及篡改拒绝。应由 Jenkins 在已准入的 ECS 上运行。本地只做源码与 AST 检查，不能把静态检查记录为测试通过。

## 夹具准备阶段的实际执行约束

[`prepare-compact-fixtures.py`](../../script/jenkins/prepare-compact-fixtures.py) 使用 `plan_phase(spec)` 与 `check_phase(plan, actualProbe)`；这两个纯函数只描述当前准备阶段，不要求尚未执行的 Maven、前端或运行栈先给出峰值。`MEASUREMENT_ADMITTED` 只允许实施当前受控量测，返回始终保留 `fullAcceptanceStatus: NOT_MEASURED`、`allAcceptanceResourcesMeasured: false`。它没有把旧约 13.9 GiB 门槛替换成新的全程固定门槛。

阶段按如下顺序串行执行，均保留同一个起始探针、固定提交、源码/Jar 摘要和前阶段回执摘要：

| 阶段 | 准入的实际输入与边界 |
|---|---|
| `extraction` | 核验 PAX 提交、归档 SHA、自身源码；读取每个 tar 成员实际声明长度，按目标文件系统分配单元向上取整并计目录，另计 Jar 新副本与 32 MiB 元数据余量。最多 50,000 个成员、512 MiB 声明内容，拒绝链接、重复和越界路径 |
| `source-inspection` | 在不写源库的前提下读取源版本、表结构、事件/存储例程和实际 DATA_LENGTH+INDEX_LENGTH；本阶段以 64 MiB 增长界限受控量测 |
| `source-export` | 根据本轮实际源 ALLOC 设置 `min(2 GiB, max(512 MiB, 4×ALLOC+64 MiB))` 的可终止量测界限；完整保留源结构、typed 数据快照、前后逐表摘要及 SQL dump；该公式不是 SQL 大小预测或全程容量证明 |
| `fixture-clone` | 必须先有本轮已完成 dump 的实际字节、SHA-256、backup manifest SHA 和源 snapshot SHA；增长界限为 `max(768 MiB, 3×ALLOC+2×dumpBytes+128 MiB+suiteCount×2 MiB)`。仅在当前实际空闲满足剩余界限及保底后创建本轮 MySQL，复制源库及准备全部 suite |

上界是可停止的测量预算；发生超界就失败并保留已有数据，不能扩大上界掩盖超界，也不能声称在给定磁盘中完整测试必然成功。真实 SQL 若超过量测界限，应根据失败证据另行设计下一轮，不跳过数据或测试。未来 Maven 冷缓存、双恢复和完整运行栈仍需独立准入和实测。

准备器在 Linux 自身及其后代应用 3 GiB `RLIMIT_AS`，不修改原业务进程限额。Docker Go CLI 继承这一地址空间边界；另对本轮控制进程树 RSS 监测 2 GiB 上限。只读源客户端在原 MySQL 容器内部使用单独 512 MiB `ulimit -v`；原 mysqld 不被改动。夹具 MySQL 的 memory 与 memory-swap 都为 1.5 GiB，不允许交换突破该 cgroup。准入计入当前阶段控制器、源客户端或 Java 工具与夹具的并存限额，另保留 1 GiB 主机 MemAvailable。

两个独立线程负责物理分配与快速压力检查。分配线程使用经核验的 `sudo -n timeout --kill-after=0.2s 1.2s du -B1 -x -s -- <本轮attempt>`，只遍历本轮隔离目录；root du 子进程由原生 timeout 约束。物理分配量不由主机空闲差推算，其他任务释放空间不能掩盖本轮超界。另一线程每 0.5 秒读取真实磁盘空闲和 MemAvailable；任一线程延迟超过 2 秒、采样失败、OOM、超界或主机真实剩余低于 2 GiB+256 MiB，均立即向自身主线程发送 SIGUSR1 使操作失败。256 MiB 是独立停止余量，不能借用真实 2 GiB 保底。主机可用量下降只记录为 `HOST_DISK_LOSS_UPPER_BOUND`，不冒充资源归属证据。

每次执行宿主命令前，先在 0700 私有目录持久化唯一 command claim，再创建独立 session，命令继承本轮 owner 与 claim 标记；启动后追加 PID、startticks、参数摘要。失败时以 exact owner+claim 静默匹配 `/proc`，复核 startticks，再终止该 session。即使启动后 PID 回执尚未写成、或 group leader 已退出，也能识别本轮残留；无匹配 capability 的 PID 不被终止。不会输出或归档进程环境。

源库只读客户端另有本轮 export token。准备开始前先核验容器内 token 读取、startticks、kill 与地址空间限制能力；失败清理时重新核对原 source 容器完整 ID、镜像和 Compose 身份，在其 `/proc` 中静默精确匹配 token，仅 TERM/KILL 对应 `mysql`、`mysqldump` 或导出包装 `sh`，并复核 startticks。回执只含 PID、startticks、comm；绝不输出 MYSQL_PWD 等环境内容，不停止、重建或替换原 source 容器。源备份结束后同样确认本轮源客户端已退出。

本轮证据位于 `verification/<tag>/checkout/work/compact-fixtures/`：

| 文件 | 含义 |
|---|---|
| `resource-enforcement.json` | 实际 rlimit 回读、限额、固定源码与所有权、监测方案 |
| `resource-probes.jsonl` | 连续原始时间、主机余量、本轮物理分配、RSS/cgroup 与 OOM 探针 |
| `resource-phase-<序号>-<阶段>-plan.json`、`-admission.json` | 该阶段的固定输入、真实准入及剩余预算 |
| `resource-phase-<序号>-measured.json` | 结束探针、采样实际峰值/最低余量、前阶段回执摘要；只声明当前阶段已测 |
| `owned-command-claims/`、`owned-process-groups.jsonl` | 启动前 capability 与启动后 session 身份，不保存原始 argv 或环境 |
| `source-export-cleanup-*.json`、`cleanup-receipt.json` | 本轮源客户端、夹具/进程退出的确认；源数据与失败证据全部保留 |
| `resource-failure.json` | 监督失败；缺失终止确认时不能发布 PREPARED |

只有所有阶段完成、独立监测线程结束、探针与进程回执 fsync 成功后，才写 `.fixtures-ready.json`。失败清理逐项尝试本轮宿主进程、本轮源客户端、Java 探针和本轮 MySQL；一项失败不会跳过其他项，但任一退出状态未知都保留 `FAILED_OR_UNKNOWN`，阻止后续使用。整个过程不删除 dump、源数据、MySQL 目录或证据，不调用全局 Docker 清理。

新增的 ECS 测试源码包含实际 Linux 进程组与 watchdog 信号验证：非本轮 session 保持存活、leader 退出后的子进程仍可清理、仅有启动前 claim 时仍可找到本轮命令、监测迟采真实通知自身并留下失败回执。这些测试必须通过 Jenkins 在 ECS 执行；本次源码检查不能替代其实际结果。
