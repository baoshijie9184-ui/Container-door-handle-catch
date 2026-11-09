package com.ruanzhu.doorhandle.module.ai.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.config.AgentJournalProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** 显式开启；只使用预先创建且指定前缀的隔离验证库，不建库/删库或连接业务库。 */
@EnabledIfSystemProperty(named="agent.journal.mysql",matches="true")
class MysqlAgentJournalTest extends JdbcAgentJournalTest {
    @Override @BeforeEach void setup() throws Exception {
        var source=com.ruanzhu.doorhandle.module.ai.EcsIsolatedMysql.open(
                System.getProperty("agent.journal.mysql-file"), "doorhandle_agent_verify_");
        jdbc=new JdbcTemplate(source);
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactAgentJournalFixture.install(jdbc);
        long owner=java.util.concurrent.ThreadLocalRandom.current().nextLong(1000,1_000_000_000);
        alice=new AgentActor(owner,"fixture-alice",AgentActor.Role.INSPECTOR);bob=new AgentActor(owner+1,"fixture-bob",AgentActor.Role.SUPERVISOR);
        var props=new AgentJournalProperties();props.setEnabled(true);journal=new JdbcAgentJournal(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),props);journal.verifySchema();
    }
    @Test void unresolvedLegacyLeaseRemainsRunningAndKeepsItsCapacity()throws Exception{
        long sourceId=java.util.concurrent.ThreadLocalRandom.current().nextLong(1_000_000_000_000L,2_000_000_000_000L);
        String run=UUID.randomUUID().toString();var wall=new LinkedHashMap<String,Object>();
        wall.put("started_at","2020-01-02 00:00:00");wall.put("ended_at",null);wall.put("heartbeat_at","2020-01-02 00:00:01");wall.put("lease_expires_at","2020-01-02 00:01:31");
        String evidence=new ObjectMapper().writeValueAsString(Map.of("protocol","doorhandle-legacy-clock-v1","status","UNRESOLVED","sourceTable","agent_run","sourceKey",Map.of("id",sourceId),"sourceSnapshotSha256","a".repeat(64),"sourceRowSha256","b".repeat(64),"sourceWallTimes",wall));
        jdbc.update("INSERT INTO agent_run(id,run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,policy_version,instance_id,active_slot,last_sequence,started_at,ended_at,heartbeat_at,lease_expires_at,legacy_clock_json) VALUES(?,?,?,?,'employee-main','CHAT',?,'RUNNING','fixture-model','role-readonly-v1',?,1,0,NULL,NULL,NULL,NULL,?)",sourceId,run,alice.userId(),"legacy-"+run,UUID.randomUUID().toString(),UUID.randomUUID().toString(),evidence);
        var read=journal.get(alice,run);assertThat(read.status()).isEqualTo("RUNNING");assertThat(read.startedAt()).isNull();assertThat(read.clockStatus()).isEqualTo("UNRESOLVED");assertThat(read.sourceWallTimes()).containsEntry("lease_expires_at","2020-01-02 00:01:31");
        journal.maintainLeases();assertThat(journal.get(alice,run).status()).isEqualTo("RUNNING");
        assertThat(jdbc.queryForObject("SELECT active_slot FROM agent_run WHERE run_id=?",Integer.class,run)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT lease_expires_at FROM agent_run WHERE run_id=?",java.time.LocalDateTime.class,run)).isNull();
    }
    @Test void legacySourceKeyGuardsAllowGeneratedIdsAndRollbackMismatchedInsertAndRekey()throws Exception{
        com.ruanzhu.doorhandle.module.ai.testsupport.CompactBaselineParts.installClockGuards(jdbc,"db/compact/008-agent-run-clock-guards.sql","agent_run");
        var normal=journal.begin(alice,UUID.randomUUID().toString(),"employee-main","CHAT",UUID.randomUUID().toString(),"fixture-model");
        assertThat(jdbc.queryForObject("SELECT id FROM agent_run WHERE run_id=?",Long.class,normal.id())).isPositive();
        normal.finish("COMPLETED");
        long sourceId=java.util.concurrent.ThreadLocalRandom.current().nextLong(2_000_000_000_000L,3_000_000_000_000L);
        var wall=new LinkedHashMap<String,Object>();wall.put("started_at","2020-01-02 00:00:00");wall.put("ended_at",null);
        wall.put("heartbeat_at","2020-01-02 00:00:01");wall.put("lease_expires_at","2020-01-02 00:01:31");
        String evidence=new ObjectMapper().writeValueAsString(Map.of("protocol","doorhandle-legacy-clock-v1","status","UNRESOLVED",
            "sourceTable","agent_run","sourceKey",Map.of("id",sourceId),"sourceSnapshotSha256","a".repeat(64),
            "sourceRowSha256","b".repeat(64),"sourceWallTimes",wall));
        String insert="INSERT INTO agent_run(id,run_id,user_id,session_id,main_agent,entry_point,request_key,status,default_model,policy_version,instance_id,started_at,heartbeat_at,lease_expires_at,legacy_clock_json) VALUES(?,?,?,?,'employee-main','CHAT',?,'COMPLETED','fixture-model','role-readonly-v1',?,NULL,NULL,NULL,?)";
        String valid=UUID.randomUUID().toString();
        jdbc.update(insert,sourceId,valid,alice.userId(),"valid-"+valid,valid,valid,evidence);
        String invalid=UUID.randomUUID().toString();
        assertThatThrownBy(()->jdbc.update(insert,sourceId+1,invalid,alice.userId(),"invalid-"+invalid,invalid,invalid,evidence))
            .isInstanceOf(org.springframework.dao.DataAccessException.class).hasStackTraceContaining("Original legacy source key does not match target row");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_run WHERE run_id=?",Integer.class,invalid)).isZero();
        assertThatThrownBy(()->jdbc.update("UPDATE agent_run SET id=? WHERE id=?",sourceId+1,sourceId))
            .isInstanceOf(org.springframework.dao.DataAccessException.class).hasStackTraceContaining("Original legacy source key does not match target row");
        assertThat(jdbc.queryForObject("SELECT id FROM agent_run WHERE run_id=?",Long.class,valid)).isEqualTo(sourceId);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_run WHERE id=?",Integer.class,sourceId+1)).isZero();
    }
}
