package com.ruanzhu.doorhandle.module.ai.workbench;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLNonTransientConnectionException;
import java.sql.Statement;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class WorkbenchMigrationStatisticsSessionTest {
    private DataSource data;
    private Connection connection;
    private Statement statement;
    private ResultSet rows;
    private JdbcTemplate jdbc;

    @BeforeEach void setup() throws Exception {
        data=mock(DataSource.class);connection=mock(Connection.class);
        statement=mock(Statement.class);rows=mock(ResultSet.class);
        when(data.getConnection()).thenReturn(connection);
        when(connection.createStatement()).thenReturn(statement);
        when(connection.getCatalog()).thenReturn("verified-physical-session");
        when(statement.executeQuery("SELECT @@SESSION.information_schema_stats_expiry")).thenReturn(rows);
        when(rows.next()).thenReturn(true,false);
        jdbc=new JdbcTemplate(data);
    }

    @Test void observationUsesTheVerifiedPhysicalConnectionWithoutOpeningAnother() throws Exception {
        String observed=WorkbenchLegacyMigration.withFreshStatistics(jdbc,
                scoped->scoped.execute((ConnectionCallback<String>)Connection::getCatalog));
        assertEquals("verified-physical-session",observed);
        verify(data,times(1)).getConnection();
        verify(statement).execute("SET SESSION information_schema_stats_expiry=0");
        verify(connection,times(1)).close();
        verify(rows).close();verify(statement).close();
    }

    private void rejectedBeforeObservation() {
        var observed=new AtomicBoolean();
        assertThrows(IllegalStateException.class,()->WorkbenchLegacyMigration.withFreshStatistics(jdbc,
                scoped->{observed.set(true);return null;}));
        assertFalse(observed.get());
    }

    @Test void cachedExpiryCannotAuthorizeAnObservation() throws Exception {
        when(rows.getLong(1)).thenReturn(86400L);rejectedBeforeObservation();
        verify(connection).close();
    }

    @Test void missingReadbackCannotAuthorizeAnObservation() throws Exception {
        when(rows.next()).thenReturn(false);rejectedBeforeObservation();
        verify(connection).close();
    }

    @Test void nullReadbackCannotMasqueradeAsZero() throws Exception {
        when(rows.wasNull()).thenReturn(true);rejectedBeforeObservation();
        verify(connection).close();
    }

    @Test void multipleReadbackRowsCannotAuthorizeAnObservation() throws Exception {
        when(rows.next()).thenReturn(true,true);rejectedBeforeObservation();
        verify(connection).close();
    }

    @Test void failedSessionSettingDoesNotRunAnObserver() throws Exception {
        when(statement.execute("SET SESSION information_schema_stats_expiry=0"))
                .thenThrow(new SQLNonTransientConnectionException("fixture unavailable"));
        var observed=new AtomicBoolean();
        assertThrows(DataAccessException.class,()->WorkbenchLegacyMigration.withFreshStatistics(jdbc,
                scoped->{observed.set(true);return null;}));
        assertFalse(observed.get());verify(connection).close();
    }

    @Test void failedReadbackDoesNotRunAnObserver() throws Exception {
        when(statement.executeQuery("SELECT @@SESSION.information_schema_stats_expiry"))
                .thenThrow(new SQLNonTransientConnectionException("fixture unavailable"));
        var observed=new AtomicBoolean();
        assertThrows(DataAccessException.class,()->WorkbenchLegacyMigration.withFreshStatistics(jdbc,
                scoped->{observed.set(true);return null;}));
        assertFalse(observed.get());verify(connection).close();
    }
}
