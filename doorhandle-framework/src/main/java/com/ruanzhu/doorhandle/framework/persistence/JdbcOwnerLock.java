package com.ruanzhu.doorhandle.framework.persistence;

import java.util.Objects;
import java.util.List;
import java.util.Map;
import java.util.HashMap;
import java.util.TreeMap;
import java.sql.DatabaseMetaData;
import java.sql.Types;
import org.springframework.dao.InvalidDataAccessResourceUsageException;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Serializes mutations of one owner's resource within the caller's transaction.
 * The namespace is part of the key: locking downloads must not lock that owner's
 * conversation queue, while two application instances share the same SQL lock.
 */
public final class JdbcOwnerLock {
    public enum Scope {
        CONVERSATION_INPUT, WORKBENCH, WORKSPACE,
        RESEARCH_STORAGE, SKILL_DOWNLOAD, KNOWLEDGE, MEMORY_MUTATION
    }

    private JdbcOwnerLock() { }

    public static void validateSchema(JdbcTemplate jdbc) {
        Objects.requireNonNull(jdbc, "jdbc");
        jdbc.queryForList("SELECT namespace,owner_id,scope_key,revision,created_at FROM runtime_state WHERE 1=0");
        Boolean verified = jdbc.execute((ConnectionCallback<Boolean>) connection -> {
            var metadata = connection.getMetaData();
            String product = metadata.getDatabaseProductName();
            if (!"MySQL".equals(product) && !"H2".equals(product)) {
                throw schemaFailure("unsupported database engine");
            }
            String catalog = connection.getCatalog();
            String schema = "H2".equals(product) ? connection.getSchema() : null;
            var primaryKey = new TreeMap<Short, String>();
            try (var keys = metadata.getPrimaryKeys(catalog, schema, "runtime_state")) {
                while (keys.next()) primaryKey.put(keys.getShort("KEY_SEQ"), keys.getString("COLUMN_NAME"));
            }
            if (!List.copyOf(primaryKey.values()).equals(List.of("namespace", "owner_id", "scope_key"))) {
                throw schemaFailure("primary key must be (namespace,owner_id,scope_key)");
            }
            Map<String, Integer> expectedTypes = Map.of("namespace", Types.VARCHAR, "owner_id", Types.BIGINT,
                    "scope_key", Types.VARCHAR, "revision", Types.BIGINT, "created_at", Types.TIMESTAMP);
            var columns = new HashMap<String, Integer>();
            try (var rows = metadata.getColumns(catalog, schema, "runtime_state", null)) {
                while (rows.next()) {
                    String name = rows.getString("COLUMN_NAME");
                    if (!expectedTypes.containsKey(name)) continue;
                    if (!"created_at".equals(name) && rows.getInt("NULLABLE") != DatabaseMetaData.columnNoNulls
                            || rows.getInt("DATA_TYPE") != expectedTypes.get(name)
                            || "namespace".equals(name) && rows.getInt("COLUMN_SIZE") != 64
                            || "scope_key".equals(name) && rows.getInt("COLUMN_SIZE") != 160) {
                        throw schemaFailure("coordination key/revision column definition differs");
                    }
                    columns.put(name, rows.getInt("DATA_TYPE"));
                }
            }
            if (!columns.equals(expectedTypes)) throw schemaFailure("coordination key/revision columns are incomplete");
            if ("MySQL".equals(product)) {
                try (var statement = connection.prepareStatement("SELECT ENGINE,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='runtime_state'");
                     var rows = statement.executeQuery()) {
                    if (!rows.next() || !"InnoDB".equals(rows.getString("ENGINE"))
                            || !"BASE TABLE".equals(rows.getString("TABLE_TYPE")) || rows.next()) {
                        throw schemaFailure("runtime_state must be one InnoDB base table");
                    }
                }
                try (var statement = connection.prepareStatement("SELECT COLUMN_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='runtime_state' AND COLUMN_NAME IN ('namespace','scope_key')");
                     var rows = statement.executeQuery()) {
                    int found = 0;
                    while (rows.next()) {
                        if (!"utf8mb4_bin".equals(rows.getString("COLLATION_NAME"))) {
                            throw schemaFailure("coordination key collation must be utf8mb4_bin");
                        }
                        found++;
                    }
                    if (found != 2) throw schemaFailure("coordination key collation metadata is incomplete");
                }
            }
            // H2 is used only by disposable test fixtures; it cannot attest MySQL's storage engine/collation.
            return Boolean.TRUE;
        });
        if (!Boolean.TRUE.equals(verified)) throw schemaFailure("coordination schema verification returned no evidence");
    }

    private static InvalidDataAccessResourceUsageException schemaFailure(String detail) {
        return new InvalidDataAccessResourceUsageException("Invalid compact coordination schema: " + detail);
    }

    public static void lock(JdbcTemplate jdbc, Scope scope, long ownerId) {
        Objects.requireNonNull(jdbc, "jdbc");
        Objects.requireNonNull(scope, "scope");
        if (ownerId <= 0) {
            throw new IllegalArgumentException("Owner lock requires a positive account ID");
        }
        if (!TransactionSynchronizationManager.isActualTransactionActive()
                || jdbc.getDataSource() == null
                || !TransactionSynchronizationManager.hasResource(jdbc.getDataSource())) {
            throw new IllegalStateException("Owner lock requires a transaction on its JDBC data source");
        }
        // Synchronization can bind a second data source to an unrelated transaction.
        // Such a connection may still auto-commit, which would release FOR UPDATE
        // immediately. Check the actual bound connection before touching the lock row.
        if (!Boolean.FALSE.equals(jdbc.execute(
                (ConnectionCallback<Boolean>) connection -> connection.getAutoCommit()))) {
            throw new IllegalStateException("Owner lock requires a non-autocommit JDBC transaction");
        }
        // The unique key also serializes two concurrent attempts to create a lock row.
        // Do not delete lock rows at release: transaction completion releases the lock.
        jdbc.update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,created_at)
                VALUES(?,?,'',UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)
                """, scope.name(), ownerId);
        jdbc.queryForObject("""
                SELECT owner_id FROM runtime_state
                WHERE namespace=? AND owner_id=? AND scope_key='' FOR UPDATE
                """, Long.class, scope.name(), ownerId);
    }
}
