package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Pattern;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Adds the real connector table to a workflow fixture that already owns audit_event. */
public final class CompactMcpFixture {
    private CompactMcpFixture() { }

    public static void installConnector(JdbcTemplate jdbc) throws Exception {
        Path baseline = null;
        for (Path path = Path.of("").toAbsolutePath(); path != null; path = path.getParent()) {
            Path candidate = path.resolve("sql/mysql/compact/baseline/25-agent.sql");
            if (Files.isRegularFile(candidate)) { baseline = candidate; break; }
        }
        if (baseline == null) throw new IllegalStateException("The isolated ECS checkout must contain the compact baseline sources");
        var match = Pattern.compile("(?ms)^CREATE TABLE agent_connector \\(.*?^\\) ENGINE=[^;]+;")
                .matcher(Files.readString(baseline));
        if (!match.find()) throw new IllegalStateException("The reviewed compact connector table is absent");
        String ddl = match.group();
        if (match.find()) throw new IllegalStateException("Duplicate compact connector table");
        try (var connection = jdbc.getDataSource().getConnection()) {
            if ("H2".equals(connection.getMetaData().getDatabaseProductName())) {
                CompactH2Functions.install(jdbc);
                ddl = CompactH2Functions.adaptDdl(ddl);
            }
        }
        var script = new ResourceDatabasePopulator(new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8)));
        script.setSqlScriptEncoding("UTF-8");
        script.execute(jdbc.getDataSource());
        CompactBaselineParts.installClockGuards(jdbc,"db/compact/009-agent-connector-clock-guards.sql","agent_connector");
    }
}
