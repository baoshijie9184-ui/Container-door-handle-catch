# 固定旧原件清退开发说明

[`retire-local-fixed-originals.py`](../../script/jenkins/retire-local-fixed-originals.py) 仅接受原始字节 SHA 固定的闭合清单及单独显式选择的模型别名范围，不发现或自动加入新文件。复用已存在的 Windows 独占句柄、身份核验、审计和证明刷新机制；目录全部保留，不提供递归删除。

| Profile | 原封存范围 | 本地可选范围 |
| --- | --- | --- |
| `legacy-project-originals-v1` | 5,599 原件 | D 项目内 5,598 项；C 盘 `history.db` 明确保留且不访问 |
| `additional-originals-v1` | 36 原件 | 固定清单中的36项；不加入任何模型别名或运输包 |
| `pth-aliases-v1` | 同一36项清单中的精确 PTH 成员 | 仅下述两个已知重复模型路径，不包含在前两种 profile 中 |
| `residual-project-originals-v1` | 精确固定的后续残留字节清单 | 1,968 项、8,779,830 字节；排除其他已登记 Git worktree 的352项 |

残留 profile 只来自既有报告的已列文件，不扫描或自动加入新目录。原始2,320项中352项位于其他 Git worktree，保留在原处；实际封存1,554项 SQL相关文件（含351项 `.sql.gz`）和414个小模型。SQL、压缩备份和模型均按 opaque 字节保存，不解析、解压、执行或合入业务。默认36项 profile 的清单、命名、限额与未传 profile 时的命令行为保持原样。

残留 profile 使用独立 `residual-project-originals-snapshot` / `residual-project-originals-restore` 目录，以及 `residual-project-originals-owner.json` / `residual-project-originals-public-receipt.json`；制品回执为 `artifacts/residual-artifact-custody.json`。通过本地 Jenkins 的 `LOCAL_ARTIFACTS_PROFILE=residual-project-originals-v1` 和已有的本地或ECS snapshot互斥参数选择；复用原来的打包、上传、独立恢复和后续复用流程。归档上限32 MiB，清单及控制JSON仍不超过2 MiB。

本地字节封包已固定：catalog SHA `a9b6498c0f0e59b8821b0dbd9a8a4c1488bd300a67d92049f673e687fd49a00c`，`custody.json` 原始SHA `471dedbba39f7220f760797ba1827040dd1cef7ac51af76daa8d7613117a6025`，`originals.tar` 原始SHA `743e1bfdfd6f88d5684e7833a624ad4a7b8d8e3cbb55286c858afd29fefdf2b6`。打包不是ECS恢复验收。实际清退还需固定提交在ECS通过测试、服务器独立恢复成功、严格更早的custody与当次新鲜现场证明；源代码、在用文件和新出现的Git worktree/nested repository仍需拒绝。

模型别名 profile 必须显式选择，仅允许项目根 `best_stg2.pth` 与 `work/quality-platform-20261103/ecs-stage-04/model/best_stg2.pth`，各159,274,200字节、SHA `eb10caf9fe5fa41e1ce0cfe2bcfaaa728ff44c4fa56f3c6994d6fadb66da434b`。必须先绑定36包的 `work/cloud/pth-model/best_stg2.pth` 精确成员，再获得同次现场证明：服务器 `/srv/doorhandle/models/best_stg2.pth` 实物及 worker 只读挂载、实际允许的模型配置与固定 manifest 路径关联。旧别名审计和旧运行回读只作设计依据，不代替当次现场证明。

2026-11-08 实际零删除预检发现，36包的上述原模型与项目根别名属于同一 NTFS 文件，链接数恰为2；另一处 quality-platform 模型为独立单链接文件。原执行器按单链接规则拒绝，尚未生成可执行计划，也未删除原件。补充实现只允许 `additional-originals-v1` 的这一精确模型成员形成固定两名称组：两个不同且祖先无重解析点的路径须具有相同完整指纹、固定大小和摘要，且原生链接数恰为2。未知第三链接、名称替换、缺失、符号链接及其他 profile 的多链接文件仍拒绝。

该组写入计划并绑定计划原始 SHA。删除仍仅持有36项原成员的既有独占句柄，不为根别名另开数据句柄，也不把别名加入本轮删除成员；持锁后、完整哈希后及原名称删除意图落盘后均重核该组和有效现场证明。Windows 的共享规则作用于整个文件，既有句柄的删除 disposition 标记其打开的链接，依据微软的[硬链接共享规则](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createhardlinkw)和[文件删除规范](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/386d9ec5-e0f6-4853-b175-c05be01419e0)。删除后必须确认根别名仍保有原身份和字节长度，链接数变为1，并单独记入审计；不能把删除一个名称的逻辑字节数当成已释放的物理空间。

顺序为先完成36项 profile，再为两处模型别名分别取得独立 profile 的完整计划与新鲜服务器实物证明。先执行别名 profile 时若仍有多链接，会明确拒绝。新组处理仍须固定提交在 ECS 回归通过，之后先作真实 Windows 只读计划核查；独占期间若无法取得元数据，在首次删除前拒绝，不通过复制替换或先删除名称来满足单链接条件。

服务器模型与配置文件的只读规则仅接受此次实际观测的 owner UID 0 或1000、无链接、单硬链接、不可组/其他用户写；执行身份仍为1000，不提权、不修改云端原件。证明只确认磁盘字节和配置关联，不执行或反序列化模型，不声称 worker 已将模型加载到内存。配置、挂载或精确文件无法证实时，别名 profile 拒绝且本地两份保留。

配置关联遵循现有 worker：`DETECTION_MODEL_MANIFEST` 指向单份 manifest，`modelFile` 指向固定模型文件；`DETECTION_MODEL_ID` 是 Kafka 任务的正整数模型编号守卫。固定六类 `classNames` 沿用现有 PTH 引擎契约，不表示按编号在 manifest 中选择多条模型。

默认计划先只读观察全部文件的 FileID、大小和时间，再持有全部文件与祖先目录句柄，计算完整 SHA；每项必须等于已封存成员才产生 `PLAN_ONLY`。清单原本没有完整 FileID，因此不能伪造旧身份记录。计划保存本次实际身份，执行时必须重新精确符合该身份和全部字节摘要。

执行另需显式 `--apply --plan <计划原件> --plan-sha256 <原始SHA>`，以及 `--profile`、`--manifest`、`--output`、`--current-receipt`、`--custody-receipt`、本次实际回读地址 `--ssh-host` 和已配置的 SSH 凭据路径。计划和执行输出均为项目 `work/jenkins` 下新建私有目录。任一源码、清单、计划或回执摘要变化均拒绝；不会用新观察覆盖已核对计划。

本地执行器及依赖须与对应 CI 归档原始字节一致；换行不同直接拒绝，不放宽 SHA 门禁。

服务器 [`attest-fixed-originals.py`](../../script/jenkins/attest-fixed-originals.py) 通过固定源码闭包、同一 ECS 当前实际 PASS、严格更早的保全与完整独立恢复链取得只读证明。旧源复用遵守现有 `reuse-legacy-source.py` 准入：当前 inbox 中必须已有版本库流水线正常准备的固定 helper；缺失时拒绝，不由证明器创建。后续构建应通过现有 `LEGACY_SOURCE_ECS_SNAPSHOT` / `LOCAL_ARTIFACTS_ECS_SNAPSHOT` 阶段复用已成功的旧封存。归档、清单及原始回执在每次 nonce 现场重新完整核对 SHA。

执行始终持有全部剩余文件句柄；每次证明 TTL 不超过300秒，120秒或 UTC 剩余不超过60秒时重新取得同一证据绑定的新 nonce 证明。每条意图先 fsync，再次验证有效证明及同一原始句柄身份后，才逐文件 disposition 并关闭。刷新、权限、身份或关闭结果不确定时停止，保留未删文件和逐条审计，不自动续跑或重放。

禁止范围包括 C 盘、共享 MySQL/Redis、Jenkins、Git、跟踪源码和受保护 checkout；仅固定旧源的 Chroma/Kafka 路径可进入严格 resolver。固定清单之外的未知候选与运输包均不在本轮执行范围。两处 PTH 别名只接受独立 profile 的完整证明，不能凭历史别名 JSON 删除。

本页属于开发说明。仅完成源码静态检查和合成用例编写，不表示这些原件已经清退；测试只由固定提交在 ECS 执行，不在本地运行测试或真实 Windows 删除 API。

新增证明与执行器模块的最终登记及实际通过数量，以同提交的验收清单和 ECS 原始报告为准。
