package com.ruanzhu.doorhandle.module.ai.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.config.AgentJournalProperties;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.web.server.ResponseStatusException;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

class JdbcAgentJournalTest {
    protected AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    protected AgentActor bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
    protected JdbcTemplate jdbc; protected JdbcAgentJournal journal;
    @BeforeEach void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(source);
        // H2 执行同一迁移结构，移除仅 MySQL 支持的字符集/排序规则，JSON 使用文本模拟。
        String ddl=Files.readString(Path.of("src/main/resources/db/migration-V16-agentscope-run-journal.sql"))
                .replaceAll(" COLLATE utf8mb4_bin","").replaceAll(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replace("payload_json JSON","payload_json VARCHAR(8192)");
        for(String sql:ddl.split(";")) if(!sql.isBlank())jdbc.execute(sql);
        var settings=new AgentJournalProperties();settings.setEnabled(true);
        journal=new JdbcAgentJournal(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),settings);journal.verifySchema();
    }
    private AgentJournal.Run begin(String session,String request) {return journal.begin(alice,session,"employee-main","CHAT",request,"fixture-model");}
    @Test void dottedUsernameSessionCanRunAndReloadButPathAndQueryCharactersAreRejected() {
        String session="sess_inspector.demo_ab12cd34";var run=begin(session,"request-dot");run.finish("COMPLETED");
        assertThat(journal.list(alice,session,null,20)).extracting(AgentJournal.RunView::runId).containsExactly(run.id());
        assertThat(journal.list(bob,session,null,20)).isEmpty();
        for(String invalid:List.of("../secret","sess?user=2","sess/user"))assertThatThrownBy(()->begin(invalid,"request-invalid")).isInstanceOf(ResponseStatusException.class);
    }
    @Test void writesOrderedEventsAndKeepsOnlyOneTerminalAfterRepeatedFinish() {
        var run=begin("s1","request-1");
        run.event("TOOL_STARTED",Map.of("agent","detection-task","tool","get_my_detection_tasks","callId","call-1"));
        run.finish("COMPLETED");run.finish("CANCELLED");
        assertThat(journal.get(alice,run.id()).status()).isEqualTo("COMPLETED");
        assertThat(journal.events(alice,run.id(),0,100)).extracting(AgentJournal.EventView::sequence).containsExactly(1L,2L,3L);
        assertThat(journal.events(alice,run.id(),1,1)).singleElement().satisfies(e->assertThat(e.type()).isEqualTo("TOOL_STARTED"));
        assertThatThrownBy(()->run.event("TOOL_STARTED",Map.of())).isInstanceOf(IllegalStateException.class);
        var next=begin("s1","request-2");next.finish("COMPLETED");
        assertThat(journal.list(alice,"s1",next.id(),20)).extracting(AgentJournal.RunView::runId).containsExactly(run.id());
    }
    @Test void duplicateRequestAndConcurrentSessionCannotCreateAnotherRun() {
        var run=begin("s1","request-1");
        assertThatThrownBy(()->begin("s1","request-2")).isInstanceOf(ResponseStatusException.class).hasMessageContaining("409");
        run.finish("COMPLETED");
        assertThatThrownBy(()->begin("s1","request-1")).isInstanceOf(ResponseStatusException.class).hasMessageContaining("409");
        assertThat(journal.list(alice,"s1",null,100)).hasSize(1);
    }
    @Test void allReadsAndCancellationAreScopedToTheServerActor() {
        var run=begin("s1","request-1");
        assertThat(journal.list(bob,null,null,20)).isEmpty();
        assertThatThrownBy(()->journal.get(bob,run.id())).isInstanceOf(ResponseStatusException.class).hasMessageContaining("404");
        assertThatThrownBy(()->journal.events(bob,run.id(),0,100)).hasMessageContaining("404");
        assertThatThrownBy(()->journal.cancel(bob,run.id())).hasMessageContaining("404");
        assertThatThrownBy(()->journal.list(bob,null,run.id(),20)).hasMessageContaining("404");
        run.bindCancel(()->run.finish("CANCELLED"));
        assertThat(journal.cancel(alice,run.id()).status()).isEqualTo("CANCELLED");
        assertThat(journal.cancel(alice,run.id()).status()).isEqualTo("CANCELLED");
    }
    @Test void rejectsRawPayloadsAndBoundsPagination() {
        var run=begin("s1","request-1");
        assertThatThrownBy(()->run.event("TOOL_STARTED",Map.of("password","private"))).hasMessageContaining("400");
        assertThatThrownBy(()->run.event("TOOL_STARTED",Map.of("agent","PRIVATE secret body"))).hasMessageContaining("400");
        assertThatThrownBy(()->journal.events(alice,run.id(),-1,20)).hasMessageContaining("400");
        assertThatThrownBy(()->journal.events(alice,run.id(),0,101)).hasMessageContaining("400");
        assertThat(journal.events(alice,run.id(),0,100)).hasSize(1);
    }
    @Test void expiredLeaseIsInterruptedAndNeverReplaysTheTool() {
        var run=begin("s1","request-1");
        // 模拟重启后新实例：没有旧运行的本机取消句柄。
        var source=jdbc.getDataSource();var settings=new AgentJournalProperties();settings.setEnabled(true);
        var restarted=new JdbcAgentJournal(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),settings);
        jdbc.update("UPDATE agent_run SET lease_expires_at=? WHERE run_id=?",java.time.LocalDateTime.now().minusMinutes(2),run.id());
        restarted.maintainLeases();
        assertThat(restarted.get(alice,run.id()).status()).isEqualTo("INTERRUPTED");
        assertThatThrownBy(()->run.finish("COMPLETED")).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->run.event("TOOL_STARTED",Map.of())).isInstanceOf(IllegalStateException.class);
        assertThat(restarted.events(alice,run.id(),0,100)).extracting(AgentJournal.EventView::type).containsExactly("RUN_STARTED","RUN_INTERRUPTED");
        begin("s1","request-2").finish("COMPLETED");
    }
    @Test void concurrentEventProducersHaveUniqueStableSequenceNumbers() throws Exception {
        var run=begin("s1","request-1");var pool=Executors.newFixedThreadPool(4);
        try {
            var jobs=new ArrayList<Future<?>>();
            for(int i=0;i<20;i++)jobs.add(pool.submit(()->run.event("MODEL_STARTED",Map.of("agent","employee-main"))));
            for(var job:jobs)job.get(5,TimeUnit.SECONDS);
        } finally {pool.shutdownNow();}
        run.finish("COMPLETED");
        assertThat(journal.events(alice,run.id(),0,100)).extracting(AgentJournal.EventView::sequence).containsExactlyElementsOf(java.util.stream.LongStream.rangeClosed(1,22).boxed().toList());
    }
    @Test void activeLeaseRenewalDoesNotInterruptAHealthyRunAndOtherInstanceCannotCancelIt() {
        var run=begin("s1","request-1");run.bindCancel(()->run.finish("CANCELLED"));
        journal.maintainLeases();assertThat(journal.get(alice,run.id()).status()).isEqualTo("RUNNING");
        var settings=new AgentJournalProperties();settings.setEnabled(true);
        var other=new JdbcAgentJournal(jdbc,new DataSourceTransactionManager(jdbc.getDataSource()),new ObjectMapper(),settings);
        assertThatThrownBy(()->other.cancel(alice,run.id())).hasMessageContaining("409");
    }
    @Test void slashEventsRetainOnlyCommandAndVersionMetadataAndNeverRawQuestionOrGuidance(){
        var run=begin("slash-session","slash-request");
        run.event("COMMAND_RECEIVED",Map.of("command","skill","policyVersion","skill-command-v1"));
        run.event("SKILL_COMMAND_LOADED",Map.of("skillId","skill-00000000-0000-0000-0000-000000000000","version",1,"sha256","a".repeat(64)));
        assertThatThrownBy(()->run.event("SKILL_COMMAND_LOADED",Map.of("instructions","private"))).hasMessageContaining("400");
        assertThatThrownBy(()->run.event("COMMAND_RECEIVED",Map.of("command","/skill task-guide private-question"))).hasMessageContaining("400");
        run.finish("COMPLETED");assertThat(journal.events(alice,run.id(),0,100)).extracting(AgentJournal.EventView::type).contains("COMMAND_RECEIVED","SKILL_COMMAND_LOADED","RUN_COMPLETED");
        assertThat(journal.events(alice,run.id(),0,100).toString()).doesNotContain("private-question","instructions");
    }
}
