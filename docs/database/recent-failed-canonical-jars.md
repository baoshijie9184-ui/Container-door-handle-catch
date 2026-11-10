# 最近三轮失败应用制品的独立退役批次

`reclaim-build-outputs` 的版本库控制脚本明确选择 `CanonicalBatch Recent`。此批次只允许以下三个未发布的失败构建的 `inbox/<release>/application.jar`；其前置步骤只可移除同三轮已严格认证的停止 MySQL 夹具容器对象，保留全部数据目录和卷，不扩展 builder 或生成缓存的许可集合。

| 构建 | 固定提交 | 原始 JAR 字节数 |
| --- | --- | --- |
| 187 | `8e90ba50c691d561bd26b23f037fec1600e5e9de` | 380,063,222 |
| 188 | `df1e1a54d48e5005185f53459068fbe9efffe333` | 380,063,222 |
| 189 | `410506ad7c82e302e623a2ac27b63dc345fcd131` | 380,063,222 |

已直接核对每轮 `build.xml`、`release.json`、`local-build.json` 和 `fixture-cleanup.json` 的 C/D 原件相等，且与各自保全清单摘要一致；实际终态均为 `FAILURE/completed/done`，原参数为 `verify/mysql`、生产开关为 false。还从 Jenkins 原始 `source.tar.gz` 核对了完整摘要、PAX 提交及两份发布控制源码的真实字节摘要；原流水线只有发布/回滚和首次切库动作能进入发布路径。

这三项逻辑大小合计 1,140,189,666 字节，约 1.062 GiB；尚未检查服务器上文件是否仍存在，未执行退役，不能计作已释放空间。服务器重新开机后仍需重新核实可用磁盘及全部当前、回滚、发布目录和双根进程/文件描述符引用。

新记录仅进入 `RECENT_CANONICAL_ONLY`。原16项 `APPROVED_OLD`、builder、公共层及生成缓存的许可集合保持；新记录不能进入这些 API。控制脚本默认 `CanonicalBatch Historical` 仍采用原16项行为，Recent 仅在明确的 Maintenance/source-only 动作可选。两个批次分别使用原来的16项请求上限，没有扩大成19项请求，也不接受目录发现或通配符。

Recent 使用独立的 capture→plan/apply fixture objects→原 plan/apply canonical 路径，收集原始回执后提前返回。所有原始控制角色、原源码证明、原始 JAR 全字节摘要、发布锁、双根静止检查、持有 inode、私有隔离及删除后回读继续生效。SQL、数据库卷、源码、报告和其他生成缓存没有进入删除范围；退役不保证重建得到相同字节。#190 在流水线编译前失败，没有应用制品，明确不在集合中。

#191 已实际通过20模块1,602项控制；随后 #192 Maintenance 为 SUCCESS，但原 canonical 计划因三个已退出的 MySQL 夹具对象仍存在而全部跳过，实际删除为0。原完整 `quiescent` 门禁保持，后续修复增加了前述对象前置步骤。

对象步骤复用原 `historical_mysql_fixture_descriptor/remove` 的严格主体，另以独立 Recent3 源许可绑定原 prepare recipe 和两份 helper SHA。原 owner/cleanup、完整容器ID、停止状态、binlog关闭及精确命令、资源/端口、唯一 bind 与 tmpfs 模型、UID999/0700数据目录 inode 均须重新核对。只对该次完整准入的真实 CID/Name 做引用过滤，其他容器/namespace/Links/VolumesFrom、残余cgroup和checkout/inbox进程引用继续阻断。普通 `docker rm <完整ID>` 不带 `-f/-v`；移除前后均核数据目录元数据，之后仍执行原未过滤的 canonical 静止检查。

前置失败、原件变化或回执状态未知会先收集原始计划、回执及journal，再阻止 JAR 阶段；只传公共投影和完整inspect摘要，不传 owner密码或完整Config.Env。新证据使用既有 `native-jar-duplicate-fixture-object-*` 前缀，沿原Jenkins归档规则保全。已不存在的对象单独报告 `alreadyAbsent`，不会伪造本轮移除成功。

对象修复新增22项 ECS 契约：JAR控制模块128→133、MySQL对象模块44→61，控制总最低数20模块1,602→1,624。当前只做AST、PowerShell解析和差异检查，没有本地执行测试、调用云 API 或删除文件。须先由固定提交在 ECS 通过新控制，再通过同一提交的 Jenkins Maintenance 实测并检查实际回执。
