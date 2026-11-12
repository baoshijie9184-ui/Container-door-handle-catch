# 原生 MySQL 验收批次优化

## 当前755项矩阵的分组结果（2026-11-12）

当前profile为64类、最低755项，首项Workbench保持独立。#260控制测试实际生成14个调用；此前752项矩阵为13个调用。新增MCP回归改变了既有算法的最低数权重和贪心分配，调用数随profile和property冲突动态确定，原设计没有固定13次的要求。

本轮将两处旧13组快照断言同步为当前profile的14组，分组算法不变。完整64类、逐类最低数、独立schema/账号/原始私有输入、最多6类/组、property无冲突、全部XML及授权检查保留；不降低测试量、截止时间、磁盘或内存门。14个调用不是性能SLO或压测结果。

#260的另外一处失败是源码契约检查未识别unknown时钟编译器添加的完整括号；相关检查修复后仍须同一固定提交在ECS验证。#260没有执行原生或整库验收，原件已保全，ECS已实际Stopped/StopCharging。

## 原56类批次优化的实施背景

原验收以 56 个独立 Maven 调用执行 56 个 MySQL 测试类，重复启动受控工具容器、Maven reactor 和报告检查。新实现保留全部测试类及逐类最低 **584 项**，先按原方式为每个类创建独立私有配置、schema、账号和原有迁移读取授权，再将没有重复 JVM property 名称的类合并到较少 Maven 调用。

固定版本 profile 的第一项保持第一个独立调用，由 profile 决定先验收的类，不在分组器中固定业务类名。#189以 `ConfirmationMigrationMySqlTest` 为首项，其35项已经真实全通过；下一提交将完整的 `OperationsAuditServiceTest` 条目移至首项，优先核查新修复的6项审计回归，其他55类的相对顺序及全部对象字段保持。Confirmation和Chat仍在完整矩阵内。其余类在兼容组中优先选择类数较少、最低测试数较少的组，每组最多6类；#189源码分析结果为12次调用，调用数随profile排序和property冲突动态确定。原类、配置路径和schema不合并，组内及跨组的私有输入路径与数据库身份均必须唯一。碰撞时增加调用数，不覆盖property或舍弃测试。

仅原生 MySQL 多类调用添加 `-DforkCount=1 -DreuseForks=false -Djunit.jupiter.execution.parallel.enabled=false`。现有 [Surefire 3.1.2](https://maven.apache.org/surefire-archives/surefire-3.1.2/maven-surefire-plugin/test-mojo.html#reuseForks) 支持每个类启动独立 JVM；不使用 Maven 并行 reactor，普通源码回归的原命令保持。只减少外层 Maven 调用，类自身的 JVM、测试内容和权限边界保留。

完整验收按原 profile 独立核对每个类的 XML、最低数、零失败/零跳过、实际计数和全局唯一覆盖；每个调用的 property 列表必须等于所选类的无冲突并集，报告不得被复用，也不能混入未选择类的用例。源码、编译产物复用和报告保全仍由原代码执行。MySQL provision/clone 的容量预算继续使用原 56 类数量，不按较少调用数缩减；单调用 3,600 秒、工具内存及磁盘余量门均保持。

新增控制回归覆盖真实 profile 分组、生产 provision 接线、原路径和授权保留、组内输入/schema 共享拒绝、实际 Maven 隔离参数及完整逐类 XML 验收的正负例；顶层报告清单不可重复，顶层每类计数也须与各组实际 XML 一致。现有 fixture admission 最低数从 30 增至 40，suite evidence 从 43 增至 63；合并旧45表投影接线后，控制预检增加分类模块130项，合计19模块、最低1,564项。旧 cutover 合成回执补上实际生产回执已有的顶层每类计数字段，不修改旧测试断言。Java 源码及 56 类的 profile 对象不改，父 POM 不改，不因此改变现有 Maven 依赖缓存输入。

当前只完成源码开发和静态检查，尚未执行这些新增测试或测得真实耗时、峰值与提速比例。后续须由已提交推送的固定提交，经本地 Jenkins 在 ECS 先运行控制预检，再完成整套 MySQL、整库迁移、Python 与双前端验收；本地不运行测试或应用。
