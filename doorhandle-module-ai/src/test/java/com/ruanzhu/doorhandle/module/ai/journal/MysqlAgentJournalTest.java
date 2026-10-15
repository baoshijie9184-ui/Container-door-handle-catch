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
        String database=System.getProperty("agent.journal.mysql.database","");
        if(!database.matches("doorhandle_agent_verify_[a-f0-9]{10}"))throw new IllegalArgumentException("需要项目专属隔离验证库");
        Path root=Path.of(System.getProperty("agent.journal.project",".."));
        var env=new HashMap<String,String>();
        for(String line:Files.readAllLines(root.resolve(".env"))) {
            int split=line.indexOf('=');if(split>0&&!line.startsWith("#"))env.put(line.substring(0,split).trim(),line.substring(split+1).trim().replaceAll("^['\"]|['\"]$",""));
        }
        String original=env.get("DB_URL");int begin=original.indexOf("//")+2;int slash=original.indexOf('/',begin);int query=original.indexOf('?',slash);
        String url=original.substring(0,slash+1)+database+(query<0?"":original.substring(query));
        var source=new DriverManagerDataSource(url,env.get("DB_USERNAME"),env.get("DB_PASSWORD"));jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("src/main/resources/db/migration-V16-agentscope-run-journal.sql"));
        for(String statement:ddl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        long owner=java.util.concurrent.ThreadLocalRandom.current().nextLong(1000,1_000_000_000);
        alice=new AgentActor(owner,"fixture-alice",AgentActor.Role.INSPECTOR);bob=new AgentActor(owner+1,"fixture-bob",AgentActor.Role.SUPERVISOR);
        var props=new AgentJournalProperties();props.setEnabled(true);journal=new JdbcAgentJournal(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),props);journal.verifySchema();
    }
}
