package com.ruanzhu.doorhandle.module.ai.persistence;

import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock.Scope;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactCoordinationFixture;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Business serialization and rollback contracts, also inherited by the admitted MySQL variant. */
@Timeout(30)
class JdbcOwnerLockTest {
    protected DataSource source;
    protected JdbcTemplate jdbc;
    protected long owner;

    protected DataSource dataSource() throws Exception {
        return new DriverManagerDataSource("jdbc:h2:mem:owner-" + UUID.randomUUID()
                + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000", "sa", "");
    }

    @BeforeEach void setup() throws Exception {
        source = dataSource();
        jdbc = new JdbcTemplate(source);
        owner = ThreadLocalRandom.current().nextLong(1_000_000_000L, Long.MAX_VALUE - 1);
        CompactCoordinationFixture.install(jdbc);
        JdbcOwnerLock.validateSchema(jdbc);
        jdbc.execute("CREATE TABLE IF NOT EXISTS compact_owner_effect (owner_id BIGINT PRIMARY KEY, value_count INT NOT NULL)");
        jdbc.update("INSERT INTO compact_owner_effect(owner_id,value_count) VALUES(?,0)", owner);
    }

    @AfterEach void cleanup() throws Exception {
        if (jdbc != null) {
            jdbc.update("DELETE FROM compact_owner_effect WHERE owner_id=?", owner);
            jdbc.update("DELETE FROM runtime_state WHERE owner_id=? AND scope_key=''", owner);
        }
        if (source instanceof AutoCloseable closeable) closeable.close();
        else if (source instanceof DriverManagerDataSource driver
                && driver.getUrl() != null && driver.getUrl().startsWith("jdbc:h2:")) jdbc.execute("SHUTDOWN");
    }

    TransactionTemplate transaction() {
        var transaction = new TransactionTemplate(new DataSourceTransactionManager(source));
        transaction.setTimeout(15);
        return transaction;
    }

    private void incrementBusinessValue() {
        int previous = jdbc.queryForObject("SELECT value_count FROM compact_owner_effect WHERE owner_id=?", Integer.class, owner);
        jdbc.update("UPDATE compact_owner_effect SET value_count=? WHERE owner_id=?", previous + 1, owner);
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("Timed out waiting for fixture coordination");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Fixture interrupted", error);
        }
    }

    @Test void lockWithoutAnActiveTransactionCannotLeaveAnAutocommittedRow() {
        assertThatThrownBy(() -> JdbcOwnerLock.lock(jdbc, Scope.WORKSPACE, owner))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("transaction");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE owner_id=?", Long.class, owner)).isZero();
    }

    @Test void anUnrelatedTransactionCannotProtectThisDataSource() {
        DataSource unrelated = mock(DataSource.class);
        JdbcTemplate otherJdbc = new JdbcTemplate(unrelated);
        transaction().executeWithoutResult(status ->
                assertThatThrownBy(() -> JdbcOwnerLock.lock(otherJdbc, Scope.WORKSPACE, owner))
                        .isInstanceOf(IllegalStateException.class).hasMessageContaining("data source"));
        verifyNoInteractions(unrelated);
    }

    @Test void synchronizedButAutocommittingSecondDataSourceCannotAcquireAnOwnerLock() {
        var secondSource = new DelegatingDataSource(source);
        var secondJdbc = new JdbcTemplate(secondSource);
        transaction().executeWithoutResult(status -> {
            // A real read binds B to Spring synchronization without enlisting it in A's JDBC transaction.
            assertThat(secondJdbc.queryForObject("SELECT 1", Integer.class)).isEqualTo(1);
            assertThat(TransactionSynchronizationManager.hasResource(secondSource)).isTrue();
            assertThat(secondJdbc.execute((ConnectionCallback<Boolean>) connection -> connection.getAutoCommit())).isTrue();
            assertThatThrownBy(() -> JdbcOwnerLock.lock(secondJdbc, Scope.WORKSPACE, owner))
                    .isInstanceOf(IllegalStateException.class).hasMessageContaining("non-autocommit");
        });
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE owner_id=?", Long.class, owner)).isZero();
    }

    @Test void anonymousAndNegativeOwnerIdsAreRejectedBeforeRowsAreCreated() {
        transaction().executeWithoutResult(status -> {
            assertThatThrownBy(() -> JdbcOwnerLock.lock(jdbc, Scope.WORKSPACE, 0)).isInstanceOf(IllegalArgumentException.class);
            assertThatThrownBy(() -> JdbcOwnerLock.lock(jdbc, Scope.WORKSPACE, -1)).isInstanceOf(IllegalArgumentException.class);
        });
    }

    @Test void sameScopeAndOwnerSerializesTransactionsIncludingFirstLockCreation() throws Exception {
        var firstHeld = new CountDownLatch(1);
        var releaseFirst = new CountDownLatch(1);
        var secondStarted = new CountDownLatch(1);
        var secondAcquired = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2);
        Future<?> first = null, second = null;
        try {
            first = pool.submit(() -> transaction().executeWithoutResult(status -> {
                JdbcOwnerLock.lock(jdbc, Scope.WORKSPACE, owner);
                firstHeld.countDown();
                await(releaseFirst);
                incrementBusinessValue();
            }));
            assertThat(firstHeld.await(5, TimeUnit.SECONDS)).isTrue();
            second = pool.submit(() -> transaction().executeWithoutResult(status -> {
                secondStarted.countDown();
                JdbcOwnerLock.lock(jdbc, Scope.WORKSPACE, owner);
                secondAcquired.countDown();
                incrementBusinessValue();
            }));
            assertThat(secondStarted.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(secondAcquired.await(500, TimeUnit.MILLISECONDS)).isFalse();
            releaseFirst.countDown();
            first.get(10, TimeUnit.SECONDS);
            second.get(10, TimeUnit.SECONDS);
            assertThat(jdbc.queryForObject("SELECT value_count FROM compact_owner_effect WHERE owner_id=?", Integer.class, owner)).isEqualTo(2);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE namespace='WORKSPACE' AND owner_id=? AND scope_key=''", Long.class, owner)).isEqualTo(1);
        } finally {
            releaseFirst.countDown();
            pool.shutdown();
            if (!pool.awaitTermination(15, TimeUnit.SECONDS)) pool.shutdownNow();
        }
    }

    @Test void differentScopesForTheSameOwnerDoNotWaitForEachOther() throws Exception {
        var firstHeld = new CountDownLatch(1);
        var releaseFirst = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2);
        try {
            var first = pool.submit(() -> transaction().executeWithoutResult(status -> {
                JdbcOwnerLock.lock(jdbc, Scope.WORKBENCH, owner);
                firstHeld.countDown();
                await(releaseFirst);
            }));
            assertThat(firstHeld.await(5, TimeUnit.SECONDS)).isTrue();
            var independent = pool.submit(() -> transaction().executeWithoutResult(status -> {
                JdbcOwnerLock.lock(jdbc, Scope.SKILL_DOWNLOAD, owner);
                incrementBusinessValue();
            }));
            independent.get(5, TimeUnit.SECONDS);
            assertThat(jdbc.queryForObject("SELECT value_count FROM compact_owner_effect WHERE owner_id=?", Integer.class, owner)).isEqualTo(1);
            releaseFirst.countDown();
            first.get(10, TimeUnit.SECONDS);
            assertThat(jdbc.queryForList("SELECT namespace FROM runtime_state WHERE owner_id=? ORDER BY namespace", String.class, owner))
                    .containsExactly("SKILL_DOWNLOAD", "WORKBENCH");
        } finally {
            releaseFirst.countDown();
            pool.shutdown();
            if (!pool.awaitTermination(15, TimeUnit.SECONDS)) pool.shutdownNow();
        }
    }

    @Test void rollbackRemovesNewLockStateAndBusinessWritesAndReleasesTheOwner() {
        assertThatThrownBy(() -> transaction().executeWithoutResult(status -> {
            JdbcOwnerLock.lock(jdbc, Scope.KNOWLEDGE, owner);
            incrementBusinessValue();
            throw new ExpectedRollback();
        })).isInstanceOf(ExpectedRollback.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM runtime_state WHERE owner_id=?", Long.class, owner)).isZero();
        assertThat(jdbc.queryForObject("SELECT value_count FROM compact_owner_effect WHERE owner_id=?", Integer.class, owner)).isZero();
        transaction().executeWithoutResult(status -> {
            JdbcOwnerLock.lock(jdbc, Scope.KNOWLEDGE, owner);
            incrementBusinessValue();
        });
        assertThat(jdbc.queryForObject("SELECT value_count FROM compact_owner_effect WHERE owner_id=?", Integer.class, owner)).isEqualTo(1);
    }

    private static final class ExpectedRollback extends RuntimeException { }
}
