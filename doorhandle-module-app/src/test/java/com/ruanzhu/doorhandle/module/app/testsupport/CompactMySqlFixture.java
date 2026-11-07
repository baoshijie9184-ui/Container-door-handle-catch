package com.ruanzhu.doorhandle.module.app.testsupport;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;

/** Actual target DDL, exclusively after EcsIsolatedMysql admits an empty disposable schema. */
public final class CompactMySqlFixture implements AutoCloseable {
    private final DataSource source;
    private final Set<String> ownedTables = new HashSet<>();
    private boolean ownsEmptySchema;

    public CompactMySqlFixture(DataSource admittedSource) throws Exception {
        source = admittedSource;
        try (var connection = source.getConnection()) {
            if (!"MySQL".equals(connection.getMetaData().getDatabaseProductName()))
                throw new IllegalArgumentException("Native compact fixture requires admitted ECS MySQL");
        }
        if (!tables().isEmpty()) throw new IllegalStateException("Compact fixture requires its own empty ECS schema");
        ownsEmptySchema = true;
        try {
            for (String file : List.of("10-core.sql", "20-content.sql", "25-agent.sql", "30-operations.sql",
                    "35-runtime-guards.sql", "36-identity-guards.sql", "37-audit-guards.sql","38-quota-guards.sql","39-workflow-guards.sql", "40-relations.sql")) {
                install(Path.of("../sql/mysql/compact/baseline", file), file.endsWith("-guards.sql") ? "$$" : ";");
            }
            FixtureSourceSnapshot.installLegacyClockGuards(new JdbcTemplate(source),Path.of("../sql/mysql/compact/baseline"));
        } catch (Exception error) {
            try { close(); } catch (RuntimeException cleanup) { error.addSuppressed(cleanup); }
            throw error;
        }
    }

    private void install(Path path, String separator) throws Exception {
        var names = Pattern.compile("(?im)^CREATE TABLE(?: IF NOT EXISTS)?\\s+([a-z_][a-z0-9_]*)\\s*\\(")
                .matcher(Files.readString(path));
        while (names.find()) ownedTables.add(names.group(1));
        try (var connection = source.getConnection()) {
            ScriptUtils.executeSqlScript(connection, new EncodedResource(new FileSystemResource(path), StandardCharsets.UTF_8),
                    false, false, ScriptUtils.DEFAULT_COMMENT_PREFIX, separator,
                    ScriptUtils.DEFAULT_BLOCK_COMMENT_START_DELIMITER, ScriptUtils.DEFAULT_BLOCK_COMMENT_END_DELIMITER);
        }
    }

    private Set<String> tables() {
        return new HashSet<>(new JdbcTemplate(source).queryForList(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()", String.class));
    }

    @Override public void close() {
        if (!ownsEmptySchema) return;
        Set<String> present = tables();
        if (!ownedTables.containsAll(present))
            throw new IllegalStateException("Unowned table found in compact fixture; refusing cleanup");
        try (var connection = source.getConnection(); var statement = connection.createStatement()) {
            statement.execute("SET FOREIGN_KEY_CHECKS=0");
            try {
                for (String table : present.stream().sorted().toList()) statement.execute("DROP TABLE `" + table + "`");
            } finally { statement.execute("SET FOREIGN_KEY_CHECKS=1"); }
            ownsEmptySchema = false;
        } catch (Exception error) { throw new IllegalStateException("Cannot clean owned compact fixture tables", error); }
    }
}
