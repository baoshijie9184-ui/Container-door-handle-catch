# 单体 ECS 运行与测试

2026-11-08 Jenkins #90：固定提交 `5dec4a42ba4ffac9df75bbff1734715b3ce49c54` 本地跳过测试构建通过；准备工具期间 SSH 被重置、退出 255，流水线失败，尚未执行项目测试或五类资料恢复。随后直接回读同次 ECS 私有回执，九项依赖已真实准备完成（109.34 秒），准确归属的 pip 容器退出 0、PID 0、无 OOM。实例运行状态、启动时长和 CloudTrail 证明中断时没有云端关机或系统重启；不能将该事件归为依赖失败或 Node 堆修复失败。原始控制证据已保全，随后从流水线外回读 `Stopped / StopCharging`，Jenkins 保持运行。现有 SSH 已配置 30 秒保活；新增恢复只允许在首次 SSH 255 后有界、只读重验同次完整完成回执，禁止重新运行准备或仅凭 `PREPARED` 字段跳过证据验证。

2026-11-08 Jenkins #89：固定提交 `02644b8cabb0785c4302425892e85f168e253bac` 的 Java 为 797 通过、612 条件跳过，Python 为 1,166 通过、24 跳过，均零失败及报错；主前端 157 项和独立 Agent 前端 20 项测试均通过。主前端生产构建成功；Agent 前端虽打印 Vite 构建完成，随后 V8 在约 1.5 GiB 堆顶触发 `SIGABRT`，实际命令失败，流水线正确阻止后续五类资料恢复。npm 工具容器原限制为 3 GiB，继续在该限制内修正 Node 堆配置，不扩 ECS 或放宽容器边界。工具清理原始回执为 `STOPPED / remaining=[]`，已从流水线外回读实例 `Stopped / StopCharging`，Jenkins 保持运行。

独立原始回执核验还发现 collector 将 tar 内回执解析后写回文本，Windows 换行转换导致同值 JSON 的字节摘要改变，会触发资料恢复助手的严格摘要拒绝。改为保留已验证成员的原始字节，维持消费端 SHA、目录及恢复门禁；与 Node 堆修复一起等待下一固定提交实测。

2026-11-08 Jenkins #88：固定提交 `eee02f041accf375125c5957feede662b70017fd` 的本地跳过测试构建通过；ECS 使用阿里云镜像完成八项 Python 依赖真实安装、`pip check` 和版本回读，耗时 58.174 秒，峰值磁盘增长 261,865,472 字节，无 OOM。Java 共 211 个 XML、1,409 项，797 通过、612 条件跳过，零失败及报错；Python 1,168 项中 1,109 通过、24 跳过、10 失败、25 报错。失败分组及原始报告已独立保全，继续修复依赖、夹具和实际校验问题；双前端及五类资料恢复尚未执行。工具清理实际回执为 `STOPPED / remaining=[]`，已从流水线外回读 ECS `Stopped / StopCharging`，Jenkins 保持运行。

本次修复补齐 worker 已使用的 `scipy==1.15.3`；五处归档恢复在 PAX 解码前通过 `_proc_member` 检查原始头，保留原有类型和 64 KiB 等限制，覆盖 [CPython 3.12 的 `_frombuf` 调用路径](https://github.com/python/cpython/blob/3.12/Lib/tarfile.py)。通用证据读取器完整读取缓冲及 gzip 尾部，拒绝非零尾随内容、CRC/截断和解压越界；构建及证据校验允许已有 `mem0` 服务名中的数字。其余修复针对合成夹具重复目录、实际未改变摘要的负例和过时部署断言，不降低门禁；上述变更等待下一固定提交在 ECS 验证。

2026-11-08 最新回执：Jenkins #87 的八项依赖安装在北京时间 00:01 被云端 OOS 关机中断。CloudTrail 确认调用方为 `OOSDoorHandleMidnightStopRole:automation-service`，当时安装运行约 24 分钟，未达到 1,800 秒期限；不能记为安装超时或依赖校验失败。已保全原计划、模板及事件，取消仅针对原单体实例的旧每日零点计划 `exec-d8e4d9bfb21640ccaeb7`，实际回读 `Cancelled`，随后从流水线外重新启动实例。后续继续遵守测试结束、证据收集及资源清理后再由流水线外执行 `StopCharging`，不在 CI/CD 中安排定时关机。

#87 已终态失败，未进入项目测试或五类资料恢复。新依赖安装配方改用项目已有阿里云 HTTPS PyPI 镜像；固定版本、原始下载摘要、TLS、无缓存、实际版本校验及资源限制保持不变，等待新固定提交在 ECS 验证。60 GiB 系统盘和文件系统扩容已完成，不能据此宣称数据迁移或 29 表重构已验收。

2026-11-07 Jenkins #85/#86：固定提交 `c4f49502e4bddd9535c973fa3ee72c7ba2d2faaa` 在准备新八项依赖镜像时被初始容量准入拦下，未创建 pip 容器、未执行项目测试或五包恢复。原代码在写入元数据后，重复预留完整 2 GiB，又要求“已有增长＋完整预留≤2 GiB”，因此任意正增长都会拒绝。现改为从同一次真实可用空间探针扣除已发生增长，再预留剩余预算；2 GiB 总包络、磁盘保底及内存限制均不变，并记录原始准入数值。新增精确边界、少一字节、预算耗尽及保底回归，工具准备最低测试数为 15，仍待 ECS 验证。两轮源码及控制器原始日志已独立保全，现场确认相关拥有容器数均为 0；已有元数据的文件分配不是原程序未记录的实际主机增长，不能混为实测峰值。

2026-11-07 Jenkins #84：固定提交 `2470a7f3156748d034cefd17a581913b13566b96` 的完整 Java 阶段实际 `BUILD SUCCESS`，211 份 XML 共 1,409 项：797 通过、612 条件跳过、无错误或断言失败。服务端新 compact 夹具已通过。随后 Python 收集因 CI 工具镜像缺少 mcp SDK 停止，尚未执行前端或五份封存恢复；该轮整体仍为 FAILURE。已将项目网关既有的 `mcp==1.29.0` 加入 CI 依赖，旧七项缓存的事实和校验不变，新清单将由固定源码的受控准备流程实际安装、pip check、版本核验并生成新镜像，未手工修改服务器测试环境或跳过用例。旧缓存负例同步使用完整旧清单以核对坏命令拒绝行为，实际复验待下一固定提交。

2026-11-07 Jenkins #83：固定提交 `f65fbb307b39ade987760142ebb022ef7370021b` 已推进到最后的 server 模块，完整 211 份 Java XML 为 1,409 项：796 通过、1 项错误、612 条件跳过、无断言失败。原记忆审计夹具 24 项已全部通过；唯一错误是服务端会话控制集成测试仍装旧 V16/V36 DDL。现已使用同一 AI 测试作用域适配器安装真实 compact 协调、工作流、运行日志表，保留全部 CHECK 及两条审计外键，状态断言改查 workflow_instance；原暂停、引导、恢复及后续消息行为断言均保留。13 模块本地跳过测试打包通过（1 分 23 秒），实际 ECS 复验仍待下一固定提交。#83 的五份原始回执和 215 项报告目录摘要已独立保全，工具实际 `STOPPED / remaining=[]`，并在流水线外回读 `Stopped / StopCharging`。

历史测试存储已补第二个固定字节清单：4,041 个目录根、16,417 文件、11,379 目录、486,493,287 原件字节，压缩包 17,367,264 字节；独立逐成员摘要、目录和 gzip 校验已通过。浏览器/SSH 工具缓存及已在首包内的 Chroma 来源不重复纳入。新增 `COLD_HISTORY_SNAPSHOT` / `COLD_HISTORY_ECS_SNAPSHOT` 与原 cold profile 使用独立目的地及回执，同一源码验证成功后可顺序处理全部五类保全包。52 项冷存储回归源码已登记，尚未在 ECS 执行；字节封包不等于服务器恢复或业务合入，本地原件继续保留。

2026-11-07 Jenkins #81：固定提交 `1f00ee6816b4ad82d7fe4d69fc66dc0774190655` 的 196 份 Java XML 共 1,384 项，789 通过、1 项断言失败、594 条件跳过、0 项错误。此前九项错误已消除，H2 函数 14 项、会话收件箱 30 项、工作流 fencing 3 项均通过；唯一失败是旧记忆夹具替换业务 ID 时遗漏既有 DISPATCHED 审计引用，造成两条可见操作。现已同步完整审计链，并明确验证原派发历史仍保留，没有放宽生产约束或删除历史。原始回执和报告已从 Jenkins #81 的独立归档逐文件校验保全，后续 Python、前端和四份封存恢复仍未执行；紧随的 SCM #82 为 `NOT_BUILT`，没有执行测试。

2026-11-07 Jenkins #80：固定提交 `273f2042903b9f222f162f908c62f1faa08a24d7` 实际产生 196 份 Java XML，780 项通过、9 项错误、0 项断言失败、594 项基础设施条件跳过。余下错误为 H2 将 MySQL 无长度 `CAST(... AS CHAR)` 截为 CHAR(1)，以及工作流/旧记忆变更夹具不符合真实 payload、时钟绑定约束。测试适配器现使用动态 VARCHAR 保留完整字符，显式长度仍保留；夹具改用真实 DIGEST_RUN 三字段和精确旧业务标识，全部生产 CHECK 保留。新增完整 ID、长文本、NULL 及错误单字符仍拒绝的回归；13 模块跳过测试打包通过（2 分 18 秒），后续仍须固定提交在 ECS 运行。原始回执和证据归档已独立校验保留，工具清理 `STOPPED / remaining=[]`，随后从流水线外实际确认 `Stopped / StopCharging`。

本轮另已完成 15,750 个历史存储文件及本次成功的 45 表 SQL 导出的字节封包，独立校验覆盖全部成员、目录和摘要；尚未上传或在 ECS 恢复，原件未删除。新增版本库流水线接线在完整源码验证通过后分别执行冷存储逐组恢复和 45 表双独立 MySQL 恢复；取消时按同一提交、实例及本轮所有权清理，仅在恢复原证完整时移除新建派生卷。候选四镜像及两个验收镜像的受控 BuildKit 构建代码也已补齐，实际路径尚未运行，不能将代码或静态检查记为迁移、容量或运行验收通过。生产门禁继续关闭。

2026-11-07 Jenkins #79：固定提交 `eca75a3133ee2c01cc6700e1dfef029730bd5508` 已通过 AI 模块（651 项、395 通过、256 基础设施条件跳过、无错误/失败），首次推进到 APP 模块。全轮 196 份 Java XML 为 727 通过、58 错误、3 断言失败、594 条件跳过；其中 57 错误是 APP 旧夹具缺少 JSON_UNQUOTE，另有 PDF 测试硬编码 target 目录及三项已退役种子导入断言。APP 现通过仅测试作用域的附加 JAR 复用同一 H2 适配器，保留全部 CHECK；PDF 使用本轮临时目录，种子导入回归验证默认关闭且显式启用仍拒绝旧脚本。13 模块本地跳过测试打包通过，附加 JAR 仅含三个适配器类，正式 Boot JAR 未包含测试 JAR；实际 ECS 验证尚待继续。原始回执和报告已独立保留，工具清理 `STOPPED`、`remaining=[]`，随后实际回读 ECS `Stopped / StopCharging`。用户之后重新启动了同一 ECS，本地 Jenkins 及节点继续在线。

已授权的一次本机旧库只读导出现已成功：45 张表，原 SQL 11,123,119 字节、gzip 1,890,654 字节；实际连接的 UUID/数据目录/端口/版本已与本机服务配置闭合，前后独立观察共 4,208 行。完整 11 个清单成员摘要已核验，所有临时凭据已清理。该结果仍为 `LOCAL_EXPORT_COMPLETE_RESTORE_PENDING`，原库未删除，也未宣称 ECS 双恢复或 131→29 迁移通过。

共享测试制品使用现有 Maven JAR Plugin 的 [test-jar 机制](https://maven.apache.org/plugins/maven-jar-plugin/examples/create-test-jar.html)，在 process-test-classes 阶段生成，APP 仅以 test 作用域引用；MySQL 原始 DDL、生产依赖边界及发布门禁保持原要求。

2026-11-07 Jenkins #76：固定提交 `ab8e8c9b8ffbe12b374c4836f8d830b2f23eb8b2` 的 154 份 Java XML 汇总为 581 项通过、2 项错误、0 项断言失败、471 项基础设施条件跳过。仅余两个调度用例被持久安装队列 enqueue 的派生表无类型参数拦截；已改为保留原 16 列、UTC、请求摘要及全部状态的直接 VALUES，并在真实调度回归内核对任务身份、所有者、摘要及 JSON 版本。13 模块本地跳过测试打包通过，后续 Python、前端、封存上传仍待 ECS 验证。原始回执及报告归档已独立保留，临时工具实际 `STOPPED`、`remaining=[]`，随后从流水线外回读 ECS `Stopped / StopCharging`。

本机端口误拦的进一步只读诊断：CIM 与 IPHelper 原始表都把已可访问的 Jenkins 和 MySQL 绑定端点状态返回为 `0`，不能将此称为 Listen 或断言 MySQL 未启动。导出脚本继续保留 UNKNOWN 原证，发送凭据前核对唯一端点所有者、固定服务/直接子进程、命令行、my.ini 及 auto.cnf；只有用户已授权的实际只读身份查询与本机 UUID、数据目录、版本、库名和端口全部吻合才允许导出。此次修复尚未执行新的导出，不能将端点归属证明当成已连接或已恢复。

2026-11-07 Jenkins #73：固定提交 `c340d69ecc703c0d4a2f4b8700a2e92139bc4923` 的 154 份 Java XML 汇总为 576 项通过、4 项错误、1 项断言失败、471 项基础设施条件跳过。UTC、重复建表、缺 connector 及多 ADD 外键问题已消除；新问题集中于 MCP 审计派生表参数类型推断和限流测试纳秒预期与 DATETIME(6) 存储精度差异。后续 Python、前端、旧数据上传未执行。报告已归档，工具清理 `STOPPED`、`remaining=[]`，随后从流水线外实际确认 ECS `Stopped / StopCharging`。

用户已单独授权一次管理员只读导出本机 `doorhandledb`，例外仅用于保全旧项目库。[专用脚本](../script/jenkins/export-legacy-local-mysql.ps1) 固定已有 MySQL83、回环端口及该 schema，使用单事务逻辑导出，生成私有摘要；前后 DDL/计数属于独立观察，不冒充同一事务的行级对账。脚本不启停共享服务、不执行本机恢复或测试、不删源数据。导出成功仅表示 `LOCAL_EXPORT_COMPLETE_RESTORE_PENDING`，后续上传、独立恢复与业务差异核验仍由固定提交的 Jenkins 流水线在 ECS 完成；没有恢复证据不能清退本机库。授权及执行回执保存在项目 Git 忽略目录。

本次已授权导出实际被 `LOCAL_SOURCE_METADATA_GATE / NO_REVIEWED_TCP_LISTENER` 拦截：服务显示 Running，但未取得固定 3306 监听证明，尚未执行 SQL、创建 dump 或启动/重启数据库。两类临时凭据已清理，原配置、库和共享服务均保留。不能将该失败尝试记为导出或迁移成功。#73 两个根因的源码已修复：MCP 审计用直接 VALUES 保留全部字段及 JSON 类型，限流失败前后精确比较数据库实际存储时间；新增审计写入及回滚回归，13 模块本地跳过测试打包通过，仍须 ECS 验证。

2026-11-07 Jenkins #72：固定提交 `687bc7a44c058312f36a460543ef803300db1570` 实际生成 154 份 Java XML，531 项通过、46 项错误、471 项基础设施条件跳过、0 项断言失败。生成列依赖适配及 12 项函数回归已通过；继续暴露的错误为 38 项无括号 UTC 函数调用在 H2 中解析为列、5 项 MCP 夹具重复建 audit_event、2 项旧 MCP 夹具缺 agent_connector，以及 1 项 H2 不支持同条 ALTER 中多个 ADD 外键。后续 Python、前端及两类封存上传仍未执行，不能据此宣称迁移已完成。168 份产物已归档，工具清理回执 `STOPPED`、`remaining=[]`；随后从流水线外实际回读 ECS `Stopped / StopCharging`，Jenkins 保持运行并清空默认目标地址。

对应修复统一采用 `UTC_TIMESTAMP(6)` 保留 UTC 语义；MCP 夹具只装真实 compact connector，保留原 audit_event；H2 夹具拆分多 ADD 并保留全部外键动作。新增非 UTC 会话、真实聊天关系和 connector 约束回归源码，13 模块本地跳过测试打包已通过，仍待下轮固定提交在 ECS 实际运行。

同日经用户授权的一次管理员只读目录核查，确认本机共享 MySQL83、Redis 仍在运行，MySQL 数据目录共 645,827,338 字节，其中 doorhandledb 目录为 46,284,800 字节；其余含其他项目数据。未执行本机 SQL、测试、启停或删除。目录元数据不是一致备份，历史计数回执也不足以证明当前本机库已完成迁移；本项目库仍须取得一次性只读导出例外授权，再由 Jenkins 在 ECS 独立恢复核验。其他项目库、共享服务和归属未明的 Redis 持久化文件不能据此清退。

2026-11-07 Jenkins #71：固定提交 `6a1baa2f2dad4a492eacaafc36bde06306c88769` 的 Java 源码验证实际为 443 项通过、133 项错误、469 项基础设施条件跳过、0 项断言失败。原始 XML 的新错误集中为 132 项 H2 不支持生成列引用另一生成列，以及 1 项测试 DDL 缺少分号；此前布尔类型错误已消除。已补齐仅用于 H2 夹具的同表前置生成表达式展开，保留无符号 64 位类型、真实生成列及约束，并增加实际 audit_event 表达式回归；这些修改仍待固定提交的 ECS 验证。后续 Python、前端及两类旧数据服务器封存阶段均未执行，原业务容器及 131 张源表未切换。本轮报告已归档，工具清理实际为 `STOPPED`、`remaining=[]`，随后从流水线外回读 ECS `Stopped / StopCharging`；Jenkins 保持运行。

2026-11-07 新一轮 Jenkins #68：固定提交 `754465e15a613ddc07c5266cb5e5b3abbcf798d9` 的 Java 源码验证实际为 441 项通过、132 项错误、469 项基础设施条件跳过，154 份原始 XML 已归档。旧 `UNSIGNED` 问题已消除；本轮错误为 131 项 JSON 文本与布尔值比较、1 项布尔列与数值比较的 H2 方言兼容问题。后续 Python、前端和旧数据上传阶段均未执行，不据此宣称迁移通过。测试工具清理回执为 `STOPPED`、`remaining=[]`，随后从流水线外回读 ECS `Stopped / StopCharging`，Jenkins 保持运行。两类适配及真实 DDL 约束回归已补齐，13 模块本地跳过测试打包通过，仍须由新的固定提交在 ECS 验证。原业务容器及 131 张源表未切换。

2026-11-07 13:35（北京时间）最新窗口：Jenkins #59 对固定提交 `68ee188164e8cd86dd2f32a45bb67977a5fa2971` 完成部分 Java 源码验证，430 项通过、136 项报错、469 项条件跳过。原始 XML 指向测试夹具中生成列 `VIRTUAL` 的 H2 方言兼容问题，未进入 Python、前端、整库迁移及运行验收。157 份报告已逐项核对摘要并独立留存；工具清理实际回执为 `STOPPED`、`remaining=[]`。随后在流水线外停止 ECS，并回读确认 `Stopped / StopCharging`；本地 Jenkins HTTP 200。原运行版本及 131 张源表未切换，29 张表仍是待验收目标结构。

2026-11-07 12:24（北京时间）测试窗口记录：Jenkins #57 在原 ECS 完成了部分源码验证，结果为 389 通过、137 失败、460 条基础设施条件跳过；失败集中于 AI 模块测试夹具的 MySQL JSON/H2 兼容及旧表名，未执行后续 Python、前端或迁移验收。原始 XML、日志和摘要已收集，本轮工具清理回执为 `STOPPED`、`remaining=[]`。随后从流水线外停止原实例并实际回读 `Stopped / StopCharging`，Jenkins HTTP 200。下一轮应先完成源码修复和构建，再按下方顺序开机验证，不能把本次失败写为重构验收通过。

2026-11-07 恢复执行：原单体实例已启动并通过实例、机器和 SSH 主机密钥核验，公网地址以本轮云端回执为准。此前 `InstanceExpired` / financial 锁记录仅为历史失败。29 表源码编译和本地全模块跳过测试打包通过，实际迁移、恢复及业务验收仍未通过；原线上库继续保留，生产发布及旧库演练门禁关闭。Jenkins #56 完成工具准备后被旧验证目录权限拦下；目录初始化修复已提交推送，由后续固定提交流水线重新验证。

本分支为 `java-cloud`，继续使用 Spring Boot 3.2.4 / Java 17。所有业务运行、开发预览和测试都在北京 ECS `i-2zeieuov2aum486jm1ek` 上执行，私网地址为 `172.29.146.74`。本地仅编辑、编译和打包，不启动数据库、应用、浏览器验收或测试。单元/集成测试全部在 ECS 执行。

2026-11-06 固定 CI/CD 控制器：后续统一使用本地 Jenkins <http://127.0.0.1:8080/>，本地专用节点 `doorhandle-local-ci` 通过已有 SSH/SCP 连接调度已启动的 ECS、收集报告，不新增常驻 ECS Jenkins agent 或为此安装额外 JRE。Jenkins 保持运行，ECS 开机与测试后的节省停机均在流水线外操作，不在 Jenkins 中配置开关机或限时停止阶段。登录信息保存在 Git 忽略的 [私有文档](../work/jenkins/local-access.md)，启动和流水线约定见 [本地 Jenkins CI/CD](本地Jenkins-CICD.md)。这一约定不允许恢复本地应用运行或测试。

## 数据库及环境文件

单体入口必须显式设置 `DB_URL`、`DB_USERNAME`、`DB_PASSWORD`，没有本机库和 root 回退。Java 不再自动读取工作目录 `.env`。Compose 部署继续使用 `DOORHANDLE_ENV_FILE` 指定主机上的私有环境文件；Java 若需要读取容器内的文件，使用独立的 `DOORHANDLE_JAVA_ENV_FILE`，且必须是容器内存在的绝对路径。两者不能混用。

`compose.cloud.yml` 中 `mysql`、`redis` 等容器 DNS 指向服务器内部服务，应继续保留。ECS 上的健康检查回环地址也有效。不要把容器内 `mysql:3306` 改成开发机地址，或将服务器数据库暴露到公网。仓库 `.env.example` 与 `deploy/docker.env.example` 中需要明确填写的连接项已留空。

## 执行入口

- 本地构建必须加 `-DskipTests=true`；可以编译测试源码，但不能执行测试。隔离构建输出可用 `-Ddoorhandle.isolated-verification=true -Ddoorhandle.verification-root=<项目内新目录>`。
- 旧 Windows Jenkinsfile 和本机应用启动/测试脚本已退役；历史文档中的本机应用运行命令失效。本地 Jenkins 控制器启动脚本继续使用。Git 历史保留旧实现。
- ECS 上使用 `script/jenkins/verify-ecs.py`。运行前配置 `DOORHANDLE_ECS_INSTANCE_ID=i-2zeieuov2aum486jm1ek`、事先核验的 `DOORHANDLE_ECS_MACHINE_ID`，以及已有 Java/Maven/Python/Node 工具路径。入口通过 IMDSv2 和 `/etc/machine-id` 核验实际实例后才运行测试。
- Jenkins 统一入口为 `Jenkinsfile.ecs-monolith`，本地节点标签 `doorhandle-local-ci`。入口固定受信任的 `java-cloud` 完整提交，本地执行控制和源码打包步骤，再通过 SSH 在 ECS 独立 checkout 调用 `verify-ecs.py`；原先依赖常驻 Linux Jenkins agent 的入口已替换。ECS 离线或连接资料缺失时预检明确失败，不自动开机、无限等待或转为本地测试。启用项目任务前须确认 CI 文件已推送到 SCM 分支；生产发布和旧库演练的机器环境门禁默认关闭，真实迁移验收前不启用。
- Jenkins 为每次构建生成独立的 `work/ecs-ci-<构建号>-<UUID>` 目录，显式传给验证入口；JUnit 和归档步骤只读取本次目录，避免旧失败或旧用例混入当前结果。历史证据和 Maven 缓存保留。
- 前端开发预览也在 ECS 上执行，须显式设置 `DOORHANDLE_DEV_API_TARGET` / `DOORHANDLE_API_TARGET`。构建静态资源仍可在本地完成。

测试使用单独工作目录与隔离数据库，不读取生产 `deploy/cloud.env`，不迁移或重建业务数据。显式真实 MySQL 用例仍需由专用夹具提供隔离连接和账号；普通源码验证不等于生产数据库验收。

`verify-ecs.py` 默认运行普通源码测试，记录真实通过、失败和条件跳过数量。`--java-only` 仅要求现有 Maven/Java，不要求 Node/npm。需要真实 MySQL 用例时，控制器先准备独立数据库及绑定 ECS 身份的私有 JSON，再传显式类名和清单，例如 `--java-only --java-tests EcsMysqlFixtureTest --fixture-property doorhandle.ecs.mysql.config=/absolute/checkout/work/attempt/private-server.json`。工作台使用 `workbench.mysql.config`，模型、技能和检测分别使用 `agent.model-config.mysql-file`、`agent.skill.mysql-file`、`detection.command.mysql-file`。脚本不会自动读取生产连接、创建数据库或清空业务库；启用夹具的用例若仍被跳过，将判为失败。

Feature MySQL 套件使用显式 `doorhandle.feature.mysql.config`，库名为 `doorhandle_feature_<12位随机十六进制>`，账号为 `ecsit_<同一后缀>`；不再使用固定 13363 端口、root 或空密码。其他旧集成用例也复用 ECS 隔离校验，必须核对机器身份、MySQL UUID、端口和本轮数据目录后才执行迁移或测试数据清理。

Python worker 的真实 MySQL 测试由控制器单独启用 `DOORHANDLE_WORKER_MYSQL_TESTS=1` 和绝对路径 `DOORHANDLE_WORKER_MYSQL_CONFIG`；普通验证不会隐式启用它。清单须位于独立 checkout 的 `work` 内，使用 `scope=ecs-disposable-mysql`、已核实的 `instanceId` / `machineId`、`serverUuid`、非 3306 的 `port`、本轮 `dataDirectory`、`database=doorhandle_worker_verify_<10位随机十六进制>`、`username=ecsit_<同一后缀>` 和非空密码。`url` 为该 ECS 回环端口及数据库的显式 JDBC URL，参数固定为 `?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai`。控制器预先创建空数据库和限定账号；测试核对真实服务身份后迁移 V42，不读取 `.env`，不创建或删除数据库，清理由拥有该隔离实例的控制器负责。

`script/shell/install-local-fetch-mcp.py` 是被 Docker 构建和 ECS 受控安装器复用的依赖构建工具，保留原来的制品校验与许可证收集逻辑；它本身不启动 Fetch 服务，不属于应退役的工作站运行入口。

Journal 的真实 MySQL 用例通过 `--java-tests MysqlAgentJournalTest --fixture-property agent.journal.mysql-file=/absolute/checkout/work/attempt/private-journal.json` 启用，清单使用 `doorhandle_agent_verify_<10位随机十六进制>` 与 `ecsit_<同一后缀>`。ModelFacts 使用 `--java-tests ModelFactsMySqlTest --fixture-property doorhandle.ecs.mysql.config=/absolute/checkout/work/attempt/private-server.json`，复用 `doorhandle_ecsit_<10位随机十六进制>`；入口分别设置 `agent.journal.mysql=true` 与 `model.facts.mysql=true`，不再读取根 `.env` 或回退到 root/空密码。

## 流水线之外的 ECS 启停顺序

1. 先完成代码修改与本地构建。在 Jenkins 流水线之外，通过云 API 或控制台核对实例 ID 与私网地址，保留实际状态回执。
2. 测试前从流水线外启动 ECS，等待系统、网络和执行环境就绪；流水线不调用开机、关机 API，也不安排限时停止任务。
3. 启动后重新查询公网 IP，通过既有 SSH 主机密钥验证连接；不能沿用历史公网 IP。需要 TLS 时，同时验证 `doorhandle-ssh.local` 证书。
4. 由 Jenkins 核对已启动目标的连通性与执行身份，在服务器隔离目录运行测试，保存源码/构建摘要、原始报告及清理回执。目标未就绪时明确失败，不自动开机，也不改为本地执行。
5. 测试结束关闭本轮拥有的测试进程并收回证据，再在流水线之外调用 ECS `StopInstance`，指定 `StoppedMode=StopCharging`。随后实际回读 `Status=Stopped` 和 `StoppedMode=StopCharging`；本地 Jenkins 控制器保持运行。

单纯执行操作系统 shutdown 不满足该要求。实例和云盘保留；StopCharging 停止计算资源计费，保留存储按原规则计费。不查询账单或卡券，不在此流程中发布生产、迁移数据或切流。
