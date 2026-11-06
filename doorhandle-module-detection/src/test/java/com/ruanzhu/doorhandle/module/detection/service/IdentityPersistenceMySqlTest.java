package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.support.ReportMySqlFixture;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;

/** Full compact baseline, including MySQL-only identity guards; an admitted ECS schema is mandatory. */
@EnabledIfSystemProperty(named="doorhandle.report.mysql.config",matches=".+")
class IdentityPersistenceMySqlTest {
    ReportMySqlFixture fixture;
    JdbcTemplate jdbc;

    @BeforeEach void setup() {
        fixture=new ReportMySqlFixture();jdbc=new JdbcTemplate(fixture.source());
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(1,'identity-never-bound','fixture','INSPECTOR')");
        jdbc.update("INSERT INTO users(id,username,password,role,binding_history_present,binding_version) VALUES(2,'identity-history','fixture','INSPECTOR',TRUE,4)");
    }
    @AfterEach void close(){if(fixture!=null)fixture.close();}

    @Test void neverBoundAccountCanBeRemovedButUnboundHistoricalAccountRemainsProtected() {
        assertThat(jdbc.update("DELETE FROM users WHERE id=1")).isEqualTo(1);
        assertThatThrownBy(()->jdbc.update("DELETE FROM users WHERE id=2")).isInstanceOf(DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT binding_history_present FROM users WHERE id=2",Boolean.class)).isTrue();
        assertThat(jdbc.queryForObject("SELECT employee_id FROM users WHERE id=2",Long.class)).isNull();
    }

    @Test void historyCannotBeErasedByChangingItsFlagPrimaryKeyOrVersion() {
        assertThatThrownBy(()->jdbc.update("UPDATE users SET binding_history_present=FALSE,binding_version=0 WHERE id=2"))
                .isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE users SET id=99 WHERE id=2")).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE users SET binding_version=3 WHERE id=2")).isInstanceOf(DataAccessException.class);
        assertThat(jdbc.queryForObject("SELECT binding_version FROM users WHERE id=2",Integer.class)).isEqualTo(4);
    }

    @Test void profileChangesAndMonotonicBindingUpdatesRemainAvailable() {
        assertThat(jdbc.update("UPDATE users SET role='SUPERVISOR',email='fixture@example.test' WHERE id=2")).isEqualTo(1);
        assertThat(jdbc.update("UPDATE users SET binding_version=binding_version+1,updated_at=updated_at WHERE id=2 AND binding_version=4"))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT binding_version FROM users WHERE id=2",Integer.class)).isEqualTo(5);
        assertThat(jdbc.queryForObject("SELECT binding_history_present FROM users WHERE id=2",Boolean.class)).isTrue();
    }

    @Test void historicalEmptyAssociationAtVersionZeroAlsoRetainsItsOriginalRestrictBoundary() {
        jdbc.update("UPDATE users SET binding_history_present=TRUE WHERE id=1");
        assertThatThrownBy(()->jdbc.update("DELETE FROM users WHERE id=1")).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(()->jdbc.update("UPDATE users SET binding_history_present=FALSE WHERE id=1"))
                .isInstanceOf(DataAccessException.class);
    }
}
