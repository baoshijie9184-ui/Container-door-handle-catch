package com.ruanzhu.doorhandle.framework.persistence;

import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/** A synchronization-bound connection alone is not proof of a JDBC transaction. */
public final class JdbcTransactions {
    private JdbcTransactions() { }
    public static void requireActive(JdbcTemplate jdbc) {
        if (!TransactionSynchronizationManager.isActualTransactionActive() || jdbc.getDataSource() == null
                || !TransactionSynchronizationManager.hasResource(jdbc.getDataSource())
                || !Boolean.FALSE.equals(jdbc.execute((ConnectionCallback<Boolean>) c -> c.getAutoCommit()))) {
            throw new IllegalStateException("Persistence requires a non-autocommit transaction on its JDBC data source");
        }
    }
}
