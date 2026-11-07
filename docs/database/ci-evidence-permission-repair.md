# 已登记 CI 证据的权限修复

Jenkins #97 的完整源码验证通过，但 9 个 verifier 自身生成的日志/JSON 叶文件为 `0664`，12 个 Java 报告中间目录为 `0775`，阻止后续冷存储准入。223 份原报告的大小与 SHA 均正确。原 Python XML 为 `0644`，没有组写权限，维持原状。

后续 verifier CLI 用可恢复的 `0077` umask 创建其自身输出。此设置约束主机进程及其普通子进程，不宣称 Docker 容器继承主机 umask；所有消费端原有权限、归属和内容检查继续保留。

[`repair-ci-evidence-permissions.py`](../../script/jenkins/repair-ci-evidence-permissions.py) 只处理[精确登记](../../script/jenkins/ci-evidence-permission-repairs.json)的 #97 原始证据。默认生成计划；流水线在新固定提交实际验证通过后、已选旧 ECS 封存被消费之前，显式调用 `--apply`。没有旧 ECS 封存输入时不运行该阶段，未知且更早的构建不会获准修改。

修复核对实例、源码闭包、原始回执、223 报告、证据 tar、工具停止状态、活动引用及持有文件描述符。全部预检后，仅以同一描述符收紧 21 个登记路径；逐项 fsync 意图和结果。旧报告、回执及 tar 字节不改写，业务文件不处理。重复运行仍须完整核验，已经正确的权限返回 `NO_ACTION`。

完整审计、逐项日志及摘要写在当前构建的新私有目录。公开摘要绑定完整审计 SHA，stdout 另带公开摘要原始字节 SHA；Jenkins 采集原件并核对摘要及构建身份，不使用自包含哈希。

源码已完成静态检查及独立复核，51 例合成回归尚须由固定提交在 ECS 执行。Jenkinsfile 已通过现有控制器的 [Declarative linter](https://www.jenkins.io/doc/book/pipeline/development/)，该静态检查未触发构建，也不代表实际权限修复已完成。
