# 最近三轮失败应用制品的独立退役批次

`reclaim-build-outputs` 的版本库控制脚本现在明确选择 `CanonicalBatch Recent`。此批次只允许以下三个未发布的失败构建的 `inbox/<release>/application.jar`，不会沿用其他生成缓存或历史容器的删除 API。

| 构建 | 固定提交 | 原始 JAR 字节数 |
| --- | --- | --- |
| 187 | `8e90ba50c691d561bd26b23f037fec1600e5e9de` | 380,063,222 |
| 188 | `df1e1a54d48e5005185f53459068fbe9efffe333` | 380,063,222 |
| 189 | `410506ad7c82e302e623a2ac27b63dc345fcd131` | 380,063,222 |

已直接核对每轮 `build.xml`、`release.json`、`local-build.json` 和 `fixture-cleanup.json` 的 C/D 原件相等，且与各自保全清单摘要一致；实际终态均为 `FAILURE/completed/done`，原参数为 `verify/mysql`、生产开关为 false。还从 Jenkins 原始 `source.tar.gz` 核对了完整摘要、PAX 提交及两份发布控制源码的真实字节摘要；原流水线只有发布/回滚和首次切库动作能进入发布路径。

这三项逻辑大小合计 1,140,189,666 字节，约 1.062 GiB；尚未检查服务器上文件是否仍存在，未执行退役，不能计作已释放空间。服务器重新开机后仍需重新核实可用磁盘及全部当前、回滚、发布目录和双根进程/文件描述符引用。

新记录仅进入 `RECENT_CANONICAL_ONLY`。原16项 `APPROVED_OLD`、builder、公共层及生成缓存的许可集合保持；新记录不能进入这些 API。控制脚本默认 `CanonicalBatch Historical` 仍采用原16项行为，Recent 仅在明确的 Maintenance/source-only 动作可选。两个批次分别使用原来的16项请求上限，没有扩大成19项请求，也不接受目录发现或通配符。

Recent 使用独立的 capture→plan/apply canonical 路径，收集原始回执后提前返回。所有原始控制角色、原源码证明、停止夹具、原始 JAR 全字节摘要、发布锁、双根静止检查、持有 inode、私有隔离及删除后回读继续生效。SQL、数据库卷、源码、报告和其他生成缓存没有进入此批次；退役不保证重建得到相同字节。#190 在流水线编译前失败，没有应用制品，明确不在集合中。

新增6项 ECS 契约，模块最低数由122增至128；相对于 `6bed743a` 的20模块基线，总最低数由1,596增至1,602。当前仅进行 AST、PowerShell 解析和差异检查，没有本地执行测试、调用云 API 或删除文件。须先由固定提交在 ECS 通过控制预检，再通过同一提交的 Jenkins Maintenance 实测并检查实际回执。
