package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.function.Consumer;
import static org.assertj.core.api.Assertions.*;

@EnabledIfSystemProperty(named="ecs.fixture.mysql", matches="true")
class EcsMysqlFixtureTest {
    @Test void explicitEcsFixtureSupportsRealWrites() {
        var jdbc = new JdbcTemplate(EcsMysqlFixture.source());
        jdbc.execute("CREATE TABLE ecs_connection_guard (id INT PRIMARY KEY, value_text VARCHAR(32))");
        try {
            jdbc.update("INSERT INTO ecs_connection_guard VALUES (1, 'ecs-only')");
            assertThat(jdbc.queryForObject("SELECT value_text FROM ecs_connection_guard WHERE id=1", String.class))
                    .isEqualTo("ecs-only");
        } finally { jdbc.execute("DROP TABLE ecs_connection_guard"); }
    }

    @Test void differentMachineIsRejected() throws Exception {
        reject(config -> config.put("machineId", "00000000000000000000000000000000"), "execution host");
    }

    @Test void differentMysqlInstanceIsRejected() throws Exception {
        reject(config -> config.put("serverUuid", "00000000-0000-0000-0000-000000000000"), "identity differs");
    }

    @Test void businessDatabaseAndRootAreRejected() throws Exception {
        reject(config -> { config.put("database", "doorhandledb"); config.put("username", "root"); }, "isolated ECS");
    }

    @Test void missingConfigurationNeverFallsBackToDotenv() {
        String original = System.getProperty("doorhandle.ecs.mysql.config");
        try {
            System.clearProperty("doorhandle.ecs.mysql.config");
            assertThatThrownBy(EcsMysqlFixture::source).isInstanceOf(SecurityException.class)
                    .hasMessageContaining("explicit absolute");
        } finally { System.setProperty("doorhandle.ecs.mysql.config", original); }
    }

    private void reject(Consumer<ObjectNode> change, String message) throws Exception {
        String original = System.getProperty("doorhandle.ecs.mysql.config");
        Path source = Path.of(original);
        var mapper = new ObjectMapper();
        var config = (ObjectNode) mapper.readTree(source.toFile());
        change.accept(config);
        Path candidate = source.resolveSibling("rejected-" + UUID.randomUUID() + ".json");
        try {
            Files.writeString(candidate, mapper.writeValueAsString(config));
            System.setProperty("doorhandle.ecs.mysql.config", candidate.toString());
            assertThatThrownBy(EcsMysqlFixture::source).isInstanceOf(SecurityException.class).hasMessageContaining(message);
        } finally {
            System.setProperty("doorhandle.ecs.mysql.config", original);
            Files.deleteIfExists(candidate);
        }
    }
}
