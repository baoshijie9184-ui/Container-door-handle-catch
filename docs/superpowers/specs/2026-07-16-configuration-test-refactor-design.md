# 配置与测试结构精简设计

## 1. 背景

当前项目可以正常构建和测试，但配置体系经过多轮功能叠加后出现了明显的重复与补丁式兼容：

- `application.yml` 与 `application.properties` 同时声明 Spring Boot 基础配置；
- 原生 MyBatis Starter 与 MyBatis-Plus Starter 同时存在，并解析出不同版本的 `mybatis-spring`；
- `CustomMybatisConfig`、`MybatisPlusConfig`、`MybatisPlusRunnerConfig` 和主启动类共同定义 MyBatis 相关 Bean；
- `spring.main.allow-bean-definition-overriding=true` 掩盖了重复 Bean；
- `DatabaseConfig`、Hikari 连接初始化 SQL 和 JDBC URL 同时处理字符集；
- `DatabaseInitConfig` 引用了仓库中不存在的初始化脚本；
- `WebConfig` 与 Spring Boot 自带编码配置重复；
- `logback-spring.xml` 默认持续生成多个文件日志，与容器和终端日志采集重复；
- 部分在线联调脚本使用 `test_*.py` 命名，只能依靠 `collect_ignore` 排除；
- 前端契约测试反复实现文件读取和正则断言样板；
- `DetectionTaskServiceImplTest` 超过 1100 行，测试职责边界不清晰。

本次重构以“减少重复来源、保留行为和回归保障”为原则，不以单纯减少测试数量为目标。

## 2. 目标

1. 建立单一、可追踪的 Spring Boot 配置来源。
2. 消除 MyBatis 与 MyBatis-Plus 的依赖版本冲突和 Bean 覆盖。
3. 删除失效或重复的 Java 配置类。
4. 默认不生成本地文件日志，避免开发日志持续堆积。
5. 将自动化测试、在线联调脚本和调试脚本明确分层。
6. 减少测试样板和超大测试类，同时保留安全、租户、迁移、异步幂等和业务闭环覆盖。
7. 重构前后保持 API、数据库结构和业务行为兼容。

## 3. 非目标

- 不修改微服务分支或把单体应用拆成微服务。
- 不修改数据库表结构和现有迁移脚本。
- 不删除安全、租户隔离、Kafka 幂等、OSS 授权或质量闭环测试。
- 不更换 JUnit、pytest 或 Node Test Runner。
- 不把真实密钥写入仓库配置。
- 不重构与配置、测试结构无关的业务实现。

## 4. 配置架构设计

### 4.1 配置来源

配置优先级统一为：

```text
操作系统 / Docker 环境变量
        │
        ▼
本地 .env（仅开发机，不提交）
        │
        ▼
application.yml 中的安全默认值
```

- `src/main/resources/application.yml` 是唯一的 Spring Boot 文件配置源。
- 删除仅包含两个重复属性的 `application.properties`。
- `.env.example` 保留 Java、Python Worker、ASR 和本地开发共用变量，作为本地配置模板。
- `deploy/docker.env.example` 只保留容器部署差异和必须替换的凭据占位符。
- `DotenvEnvironmentPostProcessor` 继续负责本地 `.env` 加载，但系统环境变量必须拥有更高优先级，避免 `.env` 覆盖 Docker、CI 或生产环境注入值。

### 4.2 MyBatis-Plus

项目使用 Spring Boot 3.2.4，因此改用 MyBatis-Plus 官方 Spring Boot 3 Starter：

```xml
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-spring-boot3-starter</artifactId>
    <version>${mybatis-plus.version}</version>
</dependency>
```

保持 MyBatis-Plus 版本为 `3.5.4`，本次只修正 Starter 类型，不同时升级框架功能版本。删除 `org.mybatis.spring.boot:mybatis-spring-boot-starter`，避免重复引入 MyBatis 和 `mybatis-spring`。

恢复 MyBatis-Plus 自动配置，并执行以下精简：

- 主启动类不再排除 `MybatisPlusAutoConfiguration`；
- 删除 `CustomMybatisConfig`；
- 删除 `MybatisPlusRunnerConfig`；
- 删除主启动类中的空 `ddlApplicationRunner` 和相关系统属性；
- `MybatisPlusConfig` 仅保留 `@MapperScan` 与分页拦截器 Bean；
- `application.yml` 只保留 `mybatis-plus` 配置段，删除重复的 `mybatis` 配置段；
- 删除 `spring.main.allow-bean-definition-overriding`，重复 Bean 必须使启动或测试失败。

官方安装说明明确区分 Spring Boot 2 和 Spring Boot 3 Starter，并要求引入 MyBatis-Plus 后不要再次引入原生 MyBatis Starter，以避免版本差异问题：<https://baomidou.com/en/getting-started/install/>。

### 4.3 数据库初始化与字符集

- 删除 `DatabaseConfig`。连接池已经通过 `connection-init-sql: SET NAMES utf8mb4` 为每个新连接设置字符集，启动时只对单个连接执行 `SET NAMES utf8` 不完整且可能降级为三字节 UTF-8。
- 删除 `DatabaseInitConfig`。其 `init` Profile 引用的 `db/init/schema-init.sql` 不存在，属于失效入口。
- 删除 `spring.sql.init` 中 `mode: never` 下仍保留的失效脚本列表。
- 保留 `BusinessSeedDataConfig` 作为唯一的可选业务预置数据入口，由 `APP_BUSINESS_SEED_ENABLED` 显式启用。
- 数据库迁移 SQL 和 `db/schema.sql` 不改动。

### 4.4 Web 与安全配置

- 删除 `WebConfig`。
- 使用 `server.servlet.encoding` 处理 UTF-8 请求与响应，不再手工注册 `CharacterEncodingFilter` 和额外的 `StringHttpMessageConverter`。
- 保留 `WebMvcConfig`，只负责操作审计拦截器、静态资源和前端路由回退。
- CORS 继续只由 `SecurityConfig` 和 `AppCorsProperties` 管理。
- 不改变 JWT、Cookie、CSRF 和接口授权规则。

### 4.5 日志

- 删除 `logback-spring.xml`。
- 删除 `logging.file.name`，默认只输出控制台日志。
- 日志级别通过环境变量控制，应用包默认 `INFO`，需要排查时临时设为 `DEBUG`。
- Docker 使用标准输出采集日志；本地开发由终端查看日志。
- 不再为模型上传服务单独维护滚动文件 Appender。

## 5. 测试结构设计

### 5.1 测试分层

```text
src/test/java              Java 单元测试与配置契约测试
tests_python               Python 单元测试
frontend/tests             前端行为与必要源码契约测试
scripts/diagnostics        需要已启动服务或浏览器的人工诊断脚本
```

在线 Agent、登录浏览器调试和页面状态检查不属于默认自动化测试。以下脚本移至 `scripts/diagnostics/` 并改为诊断名称：

- `tests_python/test_agent.py`
- `tests_python/test_login_debug.py`
- `tests_python/test_login_debug2.py`
- `tests_python/test_usage_status_filter.py`

移动后删除 `conftest.py` 中对应的 `collect_ignore`，并删除只用于验证排除列表的 `test_python_collection_config.py`。在线 Agent 脚本继续支持手工执行，但不再伪装为 pytest 测试。

### 5.2 Java 测试

- 保留全部安全、租户、迁移、Kafka 事件、OSS 授权和质量闭环断言。
- 将 `DetectionTaskServiceImplTest` 按任务创建与上传、异步事件、质量处置、追溯查询四个职责拆分。
- 提取包内测试 Fixture，集中创建 Service、Mapper Mock、任务实体和事件对象。
- 对相同业务规则的多种非法状态使用 JUnit 参数化测试，删除重复 setup 和重复 verify 代码。
- 仅在多个测试确实共享时提取 Fixture，避免形成难以理解的通用测试框架。
- 删除未被测试使用的 H2 依赖。
- 删除显式 `mockito-core` 依赖，统一使用 `spring-boot-starter-test` 提供的 Mockito。

### 5.3 前端测试

- 新建一个测试辅助模块，统一仓库路径解析、UTF-8 文件读取和源码契约断言。
- 将 24 个零散契约文件按助手、质检、检测、部署与认证五个领域合并。
- 对已有纯函数的功能直接测试输入输出，不再只用正则判断源码文本。
- 组件集成暂时继续使用少量源码契约，因为项目尚未引入 Vue 组件测试运行时；不为本次重构额外引入 Vitest 或浏览器测试框架。
- 删除被 `npm run build`、路由配置或其他测试重复覆盖的低价值断言。

## 6. 错误处理与回滚

- MyBatis 自动配置失败时，以应用上下文测试和 Maven 测试失败作为阻断，不通过重新开启 Bean 覆盖规避。
- 配置属性缺失时保留当前安全默认值；JWT、OSS、数据库和外部模型凭据仍由环境变量注入。
- 每一类配置精简独立提交，发生问题时可以按提交回滚，而不回滚测试结构优化。
- 不删除迁移脚本或生产数据，因此回滚不涉及数据库逆向迁移。

## 7. 验证标准

实施完成必须同时满足：

1. `mvn test` 全部通过；
2. 新增应用上下文测试，确认 MyBatis-Plus 自动配置、分页拦截器、Mapper 扫描和无重复 Bean；
3. `pytest tests_python -q` 全部通过且不依赖在线后端；
4. `node --test tests/*.test.cjs` 全部通过；
5. `npm run build` 成功；
6. Maven 依赖树中只存在 Spring Boot 3 对应的 MyBatis-Plus Starter，不再同时出现原生 Starter；
7. 仓库中只保留一个 Spring Boot `application` 配置文件；
8. 默认启动不创建 `logs/*.log`；
9. `git diff --check` 通过，工作区没有测试输出或运行产物。

## 8. 预期结果

重构后，配置行为从“多份配置互相覆盖”变为“环境变量覆盖单一 YAML 默认值”；MyBatis 从手工排除和空 Bean 补丁恢复为官方 Spring Boot 3 自动配置；默认日志不再落盘。测试总覆盖不主动降低，但在线脚本与自动化测试分离，超大测试和前端样板得到收敛，后续新增功能可以明确选择对应测试层级。
