package com.ruanzhu.doorhandle.module.infra;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.nio.file.Files;
import java.nio.file.Path;

/** Optional MySQL variants must use a fresh schema on the admitted ECS fixture. */
public final class EcsIsolatedMysql {
    private EcsIsolatedMysql() {}

    public static DriverManagerDataSource open(String file, String prefix) throws Exception {
        return open(file, prefix, "ecsit_");
    }

    public static DriverManagerDataSource open(String file, String prefix, String accountPrefix) throws Exception {
        if (!System.getProperty("os.name").equals("Linux") || (file == null || file.isBlank() || !Path.of(file).isAbsolute())) {
            throw new SecurityException("MySQL tests require an absolute ECS fixture configuration");
        }
        Path path = Path.of(file).toRealPath();
        if (!path.startsWith(Path.of("../work").toRealPath())) throw new SecurityException("Fixture must be under project work");
        var config = new ObjectMapper().readTree(path.toFile());
        String machine = config.path("machineId").asText(), instance = config.path("instanceId").asText();
        if (!config.path("scope").asText().equals("ecs-disposable-mysql") || !machine.matches("[a-f0-9]{32}")
                || !instance.matches("i-[a-z0-9]+") || !machine.equals(System.getenv("DOORHANDLE_ECS_MACHINE_ID"))
                || !instance.equals(System.getenv("DOORHANDLE_ECS_INSTANCE_ID"))
                || !machine.equals(Files.readString(Path.of("/etc/machine-id")).strip())) {
            throw new SecurityException("MySQL fixture is not bound to this ECS execution host");
        }
        String database = config.path("database").asText(), url = config.path("url").asText();
        String account = config.path("username").asText(), uuid = config.path("serverUuid").asText();
        int port = config.path("port").asInt();
        Path data = Path.of(config.path("dataDirectory").asText()).toRealPath();
        String expected = "jdbc:mysql://127.0.0.1:" + port + "/" + database
                + "?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai";
        if (!java.util.Set.of("doorhandle_agent_verify_", "doorhandle_model_verify_", "doorhandle_skill_verify_", "doorhandle_detection_verify_", "doorhandle_wb_verify_", "doorhandle_wb_live_", "doorhandle_feature_").contains(prefix)
                || !database.matches(prefix + (prefix.equals("doorhandle_feature_") ? "[a-f0-9]{12}" : "[a-f0-9]{10}")) || !java.util.Set.of("ecsit_", "wb_verify_").contains(accountPrefix) || !account.equals(accountPrefix + database.substring(prefix.length()))
                || config.path("password").asText().isBlank() || port <= 1024 || port > 65535 || port == 3306 || !expected.equals(url)
                || !data.startsWith(path.getParent()) || !Files.isDirectory(data)
                || !uuid.matches("[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")) {
            throw new SecurityException("Explicit isolated schema/account/server identity is required");
        }
        var source = new DriverManagerDataSource(url + "&connectTimeout=8000&socketTimeout=15000", account, config.path("password").asText());
        var actual = new JdbcTemplate(source).queryForMap("SELECT DATABASE() AS db, CURRENT_USER() AS account, "
                + "@@server_uuid AS uuid, @@port AS port, @@datadir AS data_directory");
        if (!database.equals(actual.get("db")) || !String.valueOf(actual.get("account")).startsWith(account + "@")
                || !uuid.equals(actual.get("uuid")) || ((Number)actual.get("port")).intValue() != port
                || !data.equals(Path.of(String.valueOf(actual.get("data_directory"))).toRealPath())) {
            throw new SecurityException("Connected MySQL differs from the owned ECS fixture");
        }
        return source;
    }
    public static com.zaxxer.hikari.HikariDataSource pool(String file, String prefix, String accountPrefix, int size) throws Exception {
        var verified = open(file, prefix, accountPrefix);
        var pool = new com.zaxxer.hikari.HikariDataSource();
        pool.setJdbcUrl(verified.getUrl()); pool.setUsername(verified.getUsername()); pool.setPassword(verified.getPassword());
        pool.setConnectionInitSql("SET time_zone = '+08:00'"); pool.setMaximumPoolSize(size); pool.setMinimumIdle(1);
        return pool;
    }
}
