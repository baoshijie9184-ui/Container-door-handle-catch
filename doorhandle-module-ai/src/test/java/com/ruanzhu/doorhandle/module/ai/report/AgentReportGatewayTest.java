package com.ruanzhu.doorhandle.module.ai.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentReportGatewayTest {
    final AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    final Map<String,Object> args=Map.of("taskId","task-1","title","标题","narrative","意见");
    JdbcTemplate jdbc;AgentJournal journal;QualityReportAgentApi api;AgentReportGateway gateway;
    @BeforeEach void setup(){
        var source=new DriverManagerDataSource("jdbc:h2:mem:gateway"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");jdbc=new JdbcTemplate(source);
        jdbc.execute("CREATE TABLE agent_run(run_id VARCHAR(128) PRIMARY KEY,user_id BIGINT,main_agent VARCHAR(64),status VARCHAR(20),lease_expires_at TIMESTAMP)");
        jdbc.update("INSERT INTO agent_run VALUES('run-1',1,'employee-main','RUNNING',DATEADD('MINUTE',10,CURRENT_TIMESTAMP))");
        journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);api=mock(QualityReportAgentApi.class);
        gateway=new AgentReportGateway(api,journal,jdbc,new DataSourceTransactionManager(source),new ObjectMapper());
    }
    @Test void actorStatusRoleAndLeaseAreRecheckedBeforeBusinessCall(){
        for(var mutation:List.of("user_id=2","status='CANCELLED'","main_agent='supervisor-main'","lease_expires_at=DATEADD('MINUTE',-1,CURRENT_TIMESTAMP)")){
            jdbc.update("UPDATE agent_run SET user_id=1,status='RUNNING',main_agent='employee-main',lease_expires_at=DATEADD('MINUTE',10,CURRENT_TIMESTAMP)");jdbc.update("UPDATE agent_run SET "+mutation);
            assertThatThrownBy(()->gateway.write(actor,"run-1","call-1","create_report_draft",args)).isInstanceOf(SecurityException.class);
        }
        verifyNoInteractions(api);
    }
    @Test void missingCallUnknownOperationAndDisabledJournalFailClosed(){
        assertThatThrownBy(()->gateway.write(actor,"run-1",null,"create_report_draft",args)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->gateway.write(actor,"run-1","call-1","approve_report",args)).isInstanceOf(SecurityException.class);
        when(journal.enabled()).thenReturn(false);assertThatThrownBy(()->gateway.write(actor,"run-1","call-1","create_report_draft",args)).isInstanceOf(SecurityException.class);verifyNoInteractions(api);
    }
    @Test void sameRunParametersGenerateStableServerIdIndependentOfModelCallIds(){
        gateway.write(actor,"run-1","call-1","create_report_draft",args);gateway.write(actor,"run-1","call-2","create_report_draft",new LinkedHashMap<>(args));
        var captor=org.mockito.ArgumentCaptor.forClass(QualityReportAgentApi.Origin.class);verify(api,times(2)).createDraft(eq(actor),any(),captor.capture());
        assertThat(captor.getAllValues().get(0).requestId()).hasSize(64).isEqualTo(captor.getAllValues().get(1).requestId());
        assertThat(captor.getAllValues().get(0).callId()).isEqualTo("call-1");
    }
    @Test void businessFailureRollsBackTheEntireGatewayTransaction(){
        jdbc.execute("CREATE TABLE fixture_write(id INT)");
        when(api.createDraft(any(),any(),any())).thenAnswer(inv->{jdbc.update("INSERT INTO fixture_write VALUES(1)");throw new IllegalStateException("origin failure");});
        assertThatThrownBy(()->gateway.write(actor,"run-1","call-1","create_report_draft",args)).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM fixture_write",Long.class)).isZero();
    }
}
