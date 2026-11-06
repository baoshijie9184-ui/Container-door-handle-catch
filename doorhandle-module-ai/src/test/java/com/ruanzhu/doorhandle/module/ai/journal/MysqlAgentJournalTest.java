package com.ruanzhu.doorhandle.module.ai.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.config.AgentJournalProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.util.*;

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
}
