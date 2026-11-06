package com.ruanzhu.doorhandle.module.ai.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.regex.Pattern;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/** Rebuilds only an already admitted disposable fixture, using the actual compact DDL. */
public final class CompactModelConfigurationFixture {
    private CompactModelConfigurationFixture() { }

    public static void install(JdbcTemplate jdbc) throws Exception {
        boolean mysql;
        try (var connection = jdbc.getDataSource().getConnection()) {
            String product = connection.getMetaData().getDatabaseProductName();
            if (!List.of("H2", "MySQL").contains(product)) throw new IllegalArgumentException("Unsupported fixture database");
            mysql = "MySQL".equals(product);
            if (mysql && (connection.getCatalog() == null || !connection.getCatalog().matches("doorhandle_model_verify_[a-z0-9]+")))
                throw new IllegalArgumentException("Model fixture requires its admitted disposable MySQL schema");
        }
        for (String table : List.of("audit_event", "scheduled_plan", "workflow_instance", "runtime_state", "llm_configuration",
                "agent_model_config_command", "agent_model_json_probe", "agent_model_revoked_key", "agent_model_configuration", "agent_model_config_control"))
            jdbc.execute("DROP TABLE IF EXISTS " + table);
        CompactWorkflowFixture.install(jdbc);
        String source = Files.readString(sourceRoot().resolve("sql/mysql/compact/baseline/25-agent.sql"));
        var match = Pattern.compile("(?s)CREATE TABLE llm_configuration \\(.*?;(?=\\s*(?:--|CREATE|$))").matcher(source);
        if (!match.find()) throw new IllegalStateException("Actual llm_configuration baseline is missing");
        String ddl = match.group();
        if (!mysql) ddl = ddl.replaceAll(" COLLATE utf8mb4_[a-z0-9_]+", "")
                .replace("document_json JSON", "document_json LONGTEXT")
                .replaceAll(" ENGINE=InnoDB(?: ROW_FORMAT=DYNAMIC)? DEFAULT CHARSET=utf8mb4", "")
                .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3")
                .replaceAll("(?m)^\\s*KEY [^\\n]+\\n", "").replaceAll(",\\s*\\)", ")");
        new ResourceDatabasePopulator(new ByteArrayResource(ddl.getBytes(StandardCharsets.UTF_8))).execute(jdbc.getDataSource());
        if (mysql) {
            var guards = new ResourceDatabasePopulator(new ClassPathResource("db/compact/007-runtime-guards.sql"));
            guards.setSeparator("$$");
            guards.execute(jdbc.getDataSource());
        }
    }

    private static Path sourceRoot() {
        for (Path path = Path.of("").toAbsolutePath(); path != null; path = path.getParent())
            if (Files.isRegularFile(path.resolve("sql/mysql/compact/baseline/25-agent.sql"))) return path;
        throw new IllegalStateException("The isolated ECS checkout must contain the compact baseline sources");
    }
}
