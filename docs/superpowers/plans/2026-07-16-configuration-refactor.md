# 配置体系精简实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目配置收敛为单一 YAML、官方 Spring Boot 3 MyBatis-Plus 自动配置和默认控制台日志，并删除重复或失效的 Java 配置。

**Architecture:** 环境变量和本地 `.env` 覆盖 `application.yml` 的安全默认值；MyBatis-Plus 使用官方 Boot 3 Starter 与单一分页配置；数据库字符集由 Hikari 统一初始化；Web 编码由 Spring Boot 管理；日志默认只输出标准输出。

**Tech Stack:** Java 17、Spring Boot 3.2.4、MyBatis-Plus 3.5.4、Maven 3.9.6、JUnit 5、AssertJ

---

## 文件结构

- `pom.xml`：只声明 Spring Boot 3 对应的 MyBatis-Plus Starter，移除重复测试依赖。
- `src/main/resources/application.yml`：唯一 Spring Boot 配置文件。
- `src/main/java/com/ruanzhu/doorhandlecatch/config/MybatisPlusConfig.java`：唯一 MyBatis-Plus Java 配置。
- `src/main/java/com/ruanzhu/doorhandlecatch/config/DotenvEnvironmentPostProcessor.java`：以低于系统环境变量的优先级加载本地 `.env`。
- `src/test/java/com/ruanzhu/doorhandlecatch/config/ConfigurationTopologyContractTest.java`：约束配置拓扑，防止重复配置回归。
- `src/test/java/com/ruanzhu/doorhandlecatch/config/MybatisPlusContextTest.java`：验证自动配置和分页插件 Bean。
- `src/test/java/com/ruanzhu/doorhandlecatch/config/DotenvEnvironmentPostProcessorTest.java`：验证环境变量优先级。

### Task 1：建立配置拓扑失败测试

**Files:**
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/config/ConfigurationTopologyContractTest.java`

- [ ] **Step 1：创建配置拓扑契约测试**

```java
package com.ruanzhu.doorhandlecatch.config;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class ConfigurationTopologyContractTest {

    private static final Path ROOT = Path.of("");

    @Test
    void usesOneSpringBootConfigurationFile() throws Exception {
        assertThat(ROOT.resolve("src/main/resources/application.yml")).exists();
        assertThat(ROOT.resolve("src/main/resources/application.properties")).doesNotExist();
    }

    @Test
    void usesOnlySpringBoot3MybatisPlusStarter() throws Exception {
        String pom = read("pom.xml");
        assertThat(pom).contains("mybatis-plus-spring-boot3-starter");
        assertThat(pom).doesNotContain("<artifactId>mybatis-spring-boot-starter</artifactId>");
        assertThat(pom).doesNotContain("<artifactId>mybatis-plus-boot-starter</artifactId>");
    }

    @Test
    void doesNotMaskDuplicateBeansOrExcludeMybatisAutoConfiguration() throws Exception {
        String yaml = read("src/main/resources/application.yml");
        String application = read("src/main/java/com/ruanzhu/doorhandlecatch/DoorHandleCatchApplication.java");
        assertThat(yaml).doesNotContain("allow-bean-definition-overriding");
        assertThat(application)
                .doesNotContain("MybatisPlusAutoConfiguration")
                .doesNotContain("ddlApplicationRunner")
                .doesNotContain("enable-sql-runner");
    }

    @Test
    void removesLegacyConfigurationClasses() {
        assertThat(configFile("CustomMybatisConfig.java")).doesNotExist();
        assertThat(configFile("MybatisPlusRunnerConfig.java")).doesNotExist();
        assertThat(configFile("DatabaseConfig.java")).doesNotExist();
        assertThat(configFile("DatabaseInitConfig.java")).doesNotExist();
        assertThat(configFile("WebConfig.java")).doesNotExist();
    }

    @Test
    void defaultsToConsoleOnlyLogging() throws Exception {
        assertThat(ROOT.resolve("src/main/resources/logback-spring.xml")).doesNotExist();
        assertThat(read("src/main/resources/application.yml"))
                .doesNotContain("logging.file")
                .doesNotContain("name: logs/");
    }

    private Path configFile(String name) {
        return ROOT.resolve("src/main/java/com/ruanzhu/doorhandlecatch/config").resolve(name);
    }

    private String read(String relativePath) throws Exception {
        return Files.readString(ROOT.resolve(relativePath), StandardCharsets.UTF_8);
    }
}
```

- [ ] **Step 2：运行测试并确认按预期失败**

Run:

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q -Dtest=ConfigurationTopologyContractTest test
```

Expected: FAIL；失败项应指向现存的 `application.properties`、旧 Starter、旧配置类或文件日志，而不是编译错误。

- [ ] **Step 3：提交失败测试**

```powershell
git add src/test/java/com/ruanzhu/doorhandlecatch/config/ConfigurationTopologyContractTest.java
git commit -m "test: define streamlined configuration topology"
```

### Task 2：切换到官方 Spring Boot 3 MyBatis-Plus Starter

**Files:**
- Modify: `pom.xml`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/DoorHandleCatchApplication.java`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/config/MybatisPlusConfig.java`
- Delete: `src/main/java/com/ruanzhu/doorhandlecatch/config/CustomMybatisConfig.java`
- Delete: `src/main/java/com/ruanzhu/doorhandlecatch/config/MybatisPlusRunnerConfig.java`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/config/MybatisPlusContextTest.java`

- [ ] **Step 1：编写 MyBatis-Plus 自动配置上下文测试**

```java
package com.ruanzhu.doorhandlecatch.config;

import com.baomidou.mybatisplus.autoconfigure.MybatisPlusAutoConfiguration;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import javax.sql.DataSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class MybatisPlusContextTest {

    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(MybatisPlusAutoConfiguration.class))
            .withUserConfiguration(MybatisPlusConfig.class)
            .withBean(DataSource.class, () -> mock(DataSource.class))
            .withPropertyValues("mybatis-plus.mapper-locations=classpath:mapper/*.xml");

    @Test
    void autoConfigurationCreatesOneSessionFactoryAndOnePaginationInterceptor() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).hasSingleBean(SqlSessionFactory.class);
            assertThat(context).hasSingleBean(MybatisPlusInterceptor.class);
        });
    }
}
```

- [ ] **Step 2：运行上下文测试，确认旧依赖结构不能满足目标**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q -Dtest=MybatisPlusContextTest test
```

Expected: FAIL，或因旧 Starter/重复 Bean 导致上下文失败。

- [ ] **Step 3：替换 Maven 依赖**

删除以下两个依赖：

```xml
<dependency>
    <groupId>org.mybatis.spring.boot</groupId>
    <artifactId>mybatis-spring-boot-starter</artifactId>
    <version>3.0.3</version>
</dependency>
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-boot-starter</artifactId>
    <version>${mybatis-plus.version}</version>
</dependency>
```

替换为：

```xml
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-spring-boot3-starter</artifactId>
    <version>${mybatis-plus.version}</version>
</dependency>
```

- [ ] **Step 4：将 MyBatis-Plus Java 配置收敛为一个类**

`MybatisPlusConfig.java` 的完整内容：

```java
package com.ruanzhu.doorhandlecatch.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@MapperScan("com.ruanzhu.doorhandlecatch.mapper")
public class MybatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
```

删除 `CustomMybatisConfig.java` 与 `MybatisPlusRunnerConfig.java`。

- [ ] **Step 5：恢复自动配置并删除空 Runner 补丁**

在 `DoorHandleCatchApplication.java`：

```java
@SpringBootApplication
@EnableAsync
public class DoorHandleCatchApplication {
```

删除：

```java
System.setProperty("mybatis-plus.global-config.enable-sql-runner", "false");
```

以及整个空 Bean：

```java
@Bean
@Primary
public ApplicationRunner ddlApplicationRunner() {
    return args -> { };
}
```

同步删除不再使用的 `MybatisPlusAutoConfiguration`、`ApplicationRunner`、`ConditionalOnMissingBean` 和 `Primary` import。

- [ ] **Step 6：验证上下文、拓扑和依赖树**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q '-Dtest=MybatisPlusContextTest,ConfigurationTopologyContractTest' test
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' dependency:tree '-Dincludes=com.baomidou,org.mybatis'
```

Expected: MyBatis 上下文测试通过；拓扑测试仅剩其他任务尚未处理的失败；依赖树不再同时包含两个 Starter。

- [ ] **Step 7：提交 MyBatis 重构**

```powershell
git add pom.xml src/main/java/com/ruanzhu/doorhandlecatch/DoorHandleCatchApplication.java src/main/java/com/ruanzhu/doorhandlecatch/config src/test/java/com/ruanzhu/doorhandlecatch/config/MybatisPlusContextTest.java
git commit -m "refactor: use Spring Boot 3 MyBatis Plus auto configuration"
```

### Task 3：统一 YAML 与环境变量优先级

**Files:**
- Modify: `src/main/resources/application.yml`
- Delete: `src/main/resources/application.properties`
- Modify: `src/main/java/com/ruanzhu/doorhandlecatch/config/DotenvEnvironmentPostProcessor.java`
- Create: `src/test/java/com/ruanzhu/doorhandlecatch/config/DotenvEnvironmentPostProcessorTest.java`

- [ ] **Step 1：编写 `.env` 优先级失败测试**

```java
package com.ruanzhu.doorhandlecatch.config;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class DotenvEnvironmentPostProcessorTest {

    @Test
    void systemEnvironmentKeepsPriorityOverLocalDotenv() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("DB_USERNAME", "system-user");

        DotenvEnvironmentPostProcessor.addDotenvProperties(
                environment, Map.of("DB_USERNAME", "dotenv-user", "DB_PASSWORD", "local-secret"));

        assertThat(environment.getProperty("DB_USERNAME")).isEqualTo("system-user");
        assertThat(environment.getProperty("DB_PASSWORD")).isEqualTo("local-secret");
    }

    @Test
    void emptyDotenvDoesNotAddPropertySource() {
        MockEnvironment environment = new MockEnvironment();
        int before = environment.getPropertySources().size();

        DotenvEnvironmentPostProcessor.addDotenvProperties(environment, Map.of());

        assertThat(environment.getPropertySources()).hasSize(before);
    }
}
```

- [ ] **Step 2：运行测试并确认缺少辅助方法**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q -Dtest=DotenvEnvironmentPostProcessorTest test
```

Expected: compilation FAIL，提示 `addDotenvProperties` 不存在。

- [ ] **Step 3：实现低优先级 `.env` 属性源**

在 `DotenvEnvironmentPostProcessor` 中让 `postProcessEnvironment` 调用：

```java
addDotenvProperties(environment, envMap);
```

新增包级静态方法：

```java
static void addDotenvProperties(ConfigurableEnvironment environment, Map<String, Object> values) {
    if (values.isEmpty()) {
        return;
    }
    environment.getPropertySources()
            .addLast(new MapPropertySource("dotenvProperties", values));
}
```

- [ ] **Step 4：删除重复配置并精简 YAML**

删除 `application.properties`。在 `application.yml` 中：

```yaml
spring:
  main:
    banner-mode: console
```

不得再出现 `allow-bean-definition-overriding`。

只保留：

```yaml
mybatis-plus:
  mapper-locations: classpath:mapper/*.xml
  type-aliases-package: com.ruanzhu.doorhandlecatch.entity
  global-config:
    banner: false
  configuration:
    map-underscore-to-camel-case: true
    call-setters-on-nulls: true
    log-impl: ${MYBATIS_LOG_IMPL:org.apache.ibatis.logging.slf4j.Slf4jImpl}
```

删除整个重复的 `mybatis:` 段；删除 `spring.sql.init` 下 `mode: never` 对应的失效 schema/data 路径列表。

- [ ] **Step 5：运行定向测试**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q '-Dtest=DotenvEnvironmentPostProcessorTest,ConfigurationTopologyContractTest,MybatisPlusContextTest' test
```

Expected: `.env` 测试通过；配置拓扑只剩数据库/Web/日志任务尚未处理的失败。

- [ ] **Step 6：提交单一配置来源**

```powershell
git add src/main/resources/application.yml src/main/resources/application.properties src/main/java/com/ruanzhu/doorhandlecatch/config/DotenvEnvironmentPostProcessor.java src/test/java/com/ruanzhu/doorhandlecatch/config
git commit -m "refactor: consolidate application configuration"
```

### Task 4：删除重复数据库、Web 与文件日志配置

**Files:**
- Delete: `src/main/java/com/ruanzhu/doorhandlecatch/config/DatabaseConfig.java`
- Delete: `src/main/java/com/ruanzhu/doorhandlecatch/config/DatabaseInitConfig.java`
- Delete: `src/main/java/com/ruanzhu/doorhandlecatch/config/WebConfig.java`
- Delete: `src/main/resources/logback-spring.xml`
- Modify: `src/main/resources/application.yml`
- Modify: `src/test/java/com/ruanzhu/doorhandlecatch/config/SqlPopulatorEncodingContractTest.java`

- [ ] **Step 1：更新 SQL 初始化契约，明确唯一入口**

`SqlPopulatorEncodingContractTest.java` 的完整内容：

```java
package com.ruanzhu.doorhandlecatch.config;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class SqlPopulatorEncodingContractTest {

    @Test
    void businessSeedIsTheOnlyCustomSqlPopulatorAndUsesUtf8() throws Exception {
        Path configDir = Path.of("src/main/java/com/ruanzhu/doorhandlecatch/config");
        String source = Files.readString(configDir.resolve("BusinessSeedDataConfig.java"), StandardCharsets.UTF_8);

        assertThat(source)
                .contains("populator.setSqlScriptEncoding(StandardCharsets.UTF_8.name());");
        assertThat(configDir.resolve("DatabaseInitConfig.java")).doesNotExist();
    }
}
```

- [ ] **Step 2：运行测试并确认旧初始化类导致失败**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q -Dtest=SqlPopulatorEncodingContractTest test
```

Expected: FAIL，因为 `DatabaseInitConfig.java` 仍存在。

- [ ] **Step 3：删除重复配置文件**

删除：

```text
src/main/java/com/ruanzhu/doorhandlecatch/config/DatabaseConfig.java
src/main/java/com/ruanzhu/doorhandlecatch/config/DatabaseInitConfig.java
src/main/java/com/ruanzhu/doorhandlecatch/config/WebConfig.java
src/main/resources/logback-spring.xml
```

- [ ] **Step 4：将日志改为控制台默认输出**

`application.yml` 的日志段替换为：

```yaml
logging:
  level:
    root: ${LOG_LEVEL_ROOT:INFO}
    com.ruanzhu.doorhandlecatch: ${LOG_LEVEL_APP:INFO}
    org.springframework.security: ${LOG_LEVEL_SECURITY:INFO}
    org.springframework.web: ${LOG_LEVEL_WEB:INFO}
    org.springframework.jdbc: ${LOG_LEVEL_JDBC:INFO}
  charset:
    console: UTF-8
  pattern:
    console: "%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n"
```

不得保留 `logging.file`、RollingFileAppender 或模型上传专用日志文件。

- [ ] **Step 5：验证全部配置契约**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q '-Dtest=ConfigurationTopologyContractTest,SqlPopulatorEncodingContractTest,MybatisPlusContextTest,DotenvEnvironmentPostProcessorTest' test
```

Expected: PASS。

- [ ] **Step 6：提交数据库、Web 与日志精简**

```powershell
git add src/main/java/com/ruanzhu/doorhandlecatch/config src/main/resources src/test/java/com/ruanzhu/doorhandlecatch/config
git commit -m "refactor: remove redundant runtime configuration"
```

### Task 5：精简依赖与配置模板

**Files:**
- Modify: `pom.xml`
- Modify: `.env.example`
- Modify: `deploy/docker.env.example`
- Modify: `docs/nginx-compose-deployment.md`
- Modify: `README.md`

- [ ] **Step 1：确认 H2 未被使用**

```powershell
rg -n 'jdbc:h2|org\.h2|H2' src/main src/test
```

Expected: no matches。

- [ ] **Step 2：删除重复测试依赖**

从 `pom.xml` 删除：

```xml
<dependency>
    <groupId>com.h2database</groupId>
    <artifactId>h2</artifactId>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-core</artifactId>
    <scope>test</scope>
</dependency>
```

Mockito 继续由 `spring-boot-starter-test` 提供。

- [ ] **Step 3：收敛环境变量模板**

在 `.env.example` 增加：

```dotenv
# -------------------- 日志（默认仅控制台） --------------------
LOG_LEVEL_ROOT=INFO
LOG_LEVEL_APP=INFO
LOG_LEVEL_JDBC=INFO
```

`deploy/docker.env.example` 只保留容器部署必须覆盖的数据库、Redis、Kafka、外部服务、凭据和 JVM 参数；公共默认值不重复复制。同步更新 README 与部署文档，说明本地使用 `.env`，Docker 使用 `DOORHANDLE_ENV_FILE` 指定部署文件。

- [ ] **Step 4：运行完整 Maven 测试**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q test
```

Expected: PASS，零失败。

- [ ] **Step 5：提交模板与依赖精简**

```powershell
git add pom.xml .env.example deploy/docker.env.example README.md docs/nginx-compose-deployment.md
git commit -m "chore: streamline dependencies and environment templates"
```

### Task 6：配置重构最终验收

**Files:**
- Verify only

- [ ] **Step 1：验证 Java 测试和打包**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' -q clean test package -DskipTests=false
```

Expected: BUILD SUCCESS，并生成可执行 JAR。

- [ ] **Step 2：验证依赖唯一性**

```powershell
& 'D:\ruanjian\apache-maven-3.9.6\bin\mvn.cmd' dependency:tree '-Dincludes=com.baomidou,org.mybatis'
```

Expected: 只出现 `mybatis-plus-spring-boot3-starter` 这一条 Starter 路径，不出现原生 `mybatis-spring-boot-starter` 或 Boot 2 Starter。

- [ ] **Step 3：验证不产生默认文件日志**

```powershell
rg -n 'logging\.file|RollingFileAppender|logs/doorhandlecatch' src/main/resources
```

Expected: no matches。

- [ ] **Step 4：验证仓库状态**

```powershell
git diff --check
git status -sb
```

Expected: 无未提交代码和测试产物。

