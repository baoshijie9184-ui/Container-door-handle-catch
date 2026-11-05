package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.nio.file.Files;
import java.nio.file.Path;

/** Explicit disposable ECS fixture; never reads .env or a business database. */
final class EcsMysqlFixture {
    private EcsMysqlFixture() {}

    static JsonNode configuration() {
        try {
            if (!System.getProperty("os.name").equals("Linux")) {
                throw new SecurityException("Tests must execute on ECS; local machines are edit/build only");
            }
            String configured = System.getProperty("doorhandle.ecs.mysql.config", "");
            if (configured.isBlank() || !Path.of(configured).isAbsolute()) {
                throw new SecurityException("An explicit absolute doorhandle.ecs.mysql.config is required");
            }
            Path path = Path.of(configured).toRealPath();
            Path work = Path.of("../work").toRealPath();
            if (!path.startsWith(work) || !Files.isRegularFile(path)) {
                throw new SecurityException("ECS fixture configuration must stay inside project work");
            }
            JsonNode config = new ObjectMapper().readTree(path.toFile());
            String machine = config.path("machineId").asText();
            String instance = config.path("instanceId").asText();
            if (!config.path("scope").asText().equals("ecs-disposable-mysql")
                    || !machine.matches("[a-f0-9]{32}")
                    || !instance.matches("i-[a-z0-9]+")
                    || !machine.equals(Files.readString(Path.of("/etc/machine-id")).strip())
                    || !instance.equals(System.getenv("DOORHANDLE_ECS_INSTANCE_ID"))
                    || !machine.equals(System.getenv("DOORHANDLE_ECS_MACHINE_ID"))) {
                throw new SecurityException("Fixture is not bound to the admitted ECS execution host");
            }
            Path data = Path.of(config.path("dataDirectory").asText()).toRealPath();
            if (!data.startsWith(path.getParent()) || !Files.isDirectory(data)) {
                throw new SecurityException("MySQL data directory must belong to this ECS attempt");
            }
            return config;
        } catch (java.io.IOException error) {
            throw new IllegalStateException("ECS fixture configuration is unavailable");
        }
    }

    static DataSource source() {
        var config = configuration();
        String database = config.path("database").asText();
        String account = config.path("username").asText();
        int port = config.path("port").asInt();
        String uuid = config.path("serverUuid").asText();
        String url = "jdbc:mysql://127.0.0.1:" + port + "/" + database
                + "?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai";
        if (!database.matches("doorhandle_ecsit_[a-f0-9]{10}")
                || !account.equals("ecsit_" + database.substring("doorhandle_ecsit_".length()))
                || port <= 1024 || port > 65535 || port == 3306
                || !uuid.matches("[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
                || !url.equals(config.path("url").asText()) || config.path("password").asText().isBlank()) {
            throw new SecurityException("Only the explicit isolated ECS schema/account/server is allowed");
        }
        var source = new DriverManagerDataSource(url + "&connectTimeout=8000&socketTimeout=15000",
                account, config.path("password").asText());
        var actual = new JdbcTemplate(source).queryForMap("SELECT DATABASE() AS db, CURRENT_USER() AS account, "
                + "@@server_uuid AS uuid, @@port AS port, @@datadir AS data_directory");
        if (!database.equals(actual.get("db")) || !String.valueOf(actual.get("account")).startsWith(account + "@")
                || !uuid.equals(actual.get("uuid")) || ((Number) actual.get("port")).intValue() != port
                || !Path.of(config.path("dataDirectory").asText()).normalize().equals(
                        Path.of(String.valueOf(actual.get("data_directory"))).normalize())) {
            throw new SecurityException("Connected MySQL identity differs from the ECS fixture");
        }
        return source;
    }

    static String value(String name) {
        String value = configuration().path(name).asText();
        if (value.isBlank()) throw new SecurityException("Missing explicit ECS fixture setting: " + name);
        return value;
    }

    static String httpBase() {
        String base = value("backendBaseUrl");
        if (!base.matches("http://127\\.0\\.0\\.1:[0-9]{4,5}")
                || java.net.URI.create(base).getPort() <= 1024 || java.net.URI.create(base).getPort() > 65535) {
            throw new SecurityException("Backend must be the isolated HTTP fixture on this ECS host");
        }
        return base;
    }

    static Path directory(String name) {
        try {
            Path path = Path.of(value(name)).toRealPath();
            Path config = Path.of(System.getProperty("doorhandle.ecs.mysql.config")).toRealPath();
            if (!path.startsWith(config.getParent()) || !Files.isDirectory(path)) {
                throw new SecurityException("Fixture files must stay inside this ECS attempt");
            }
            return path;
        } catch (java.io.IOException error) {
            throw new IllegalStateException("ECS fixture directory is unavailable");
        }
    }
}
