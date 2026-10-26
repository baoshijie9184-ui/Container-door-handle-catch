package com.ruanzhu.doorhandle.module.ai.research;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.config.AgentJournalProperties;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import io.agentscope.core.message.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

public class ResearchEvidenceServiceTest {
    @TempDir Path workspace;
    protected final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR), bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
    protected JdbcTemplate jdbc;
    protected JdbcAgentJournal journal;
    protected ResearchEvidenceService evidence;
    protected DataSourceTransactionManager transactions;
    protected final ObjectMapper json=new ObjectMapper();
    @BeforeEach protected void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        jdbc=new JdbcTemplate(source);transactions=new DataSourceTransactionManager(source);
        migrate(Path.of("src/main/resources/db/migration-V16-agentscope-run-journal.sql"));
        migrate(Path.of("src/main/resources/db/migration-V31-agent-research-evidence.sql"));
        var settings=new AgentJournalProperties();settings.setEnabled(true);
        journal=new JdbcAgentJournal(jdbc,transactions,json,settings);journal.verifySchema();
        evidence=new ResearchEvidenceService(jdbc,transactions,json,journal);evidence.schema();
    }
    protected void migrate(Path path) throws Exception {
        String ddl=Files.readString(path).replaceAll("(?m)^--.*$", "").replaceAll(" COLLATE utf8mb4_bin","").replaceAll(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4(?: COLLATE=utf8mb4_bin)?","")
                .replace(" JSON "," VARCHAR(16384) ")
                .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3")
                .replaceAll("(?m)^\\s*KEY .*\\n","");
        for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
    }
    protected AgentJournal.Run begin(AgentActor actor,String session) {return journal.begin(actor,session,actor.supervisor()?"supervisor-main":"employee-main","CHAT",UUID.randomUUID().toString(),"fixture");}
    protected Map<String,Object> args() {return Map.of("url","https://1.1.1.1/article?topic=private-query","max_length",5000,"start_index",0);}
    protected String capture(AgentJournal.Run run,String call,String body) {
        evidence.capture(alice,run.id(),call,args(),ToolResultBlock.text(body));
        return evidence.view(alice,run.id()).sources().stream().filter(s->s.callId().equals(call)).findFirst().orElseThrow().sourceId();
    }
    @Test void successfulFetchKeepsOnlyRedactedBoundedExcerptAndReturnsAServerCitationMarker() {
        var run=begin(alice,"session");String body="# Public title\nAPI_KEY=hidden-value Bearer secret-value sk-secret123456 alice@example.com https://public.example/?secret=hidden-value\n"+"x".repeat(2000);
        var result=evidence.capture(alice,run.id(),"fetch-1",args(),ToolResultBlock.text(body));
        var view=evidence.view(alice,run.id());assertThat(view.sources()).singleElement().satisfies(s->{
            assertThat(s.requestedUrl()).isEqualTo("https://1.1.1.1/article");assertThat(s.queryOmitted()).isTrue();assertThat(s.urlRedacted()).isTrue();
            assertThat(s.title()).isEqualTo("Public title");assertThat(s.excerpt()).hasSizeLessThanOrEqualTo(1000).doesNotContain("hidden-value","secret-value","sk-secret123456","alice@example.com");
            assertThat(s.contentSha256()).isEqualTo(ResearchEvidenceService.sha256(body));assertThat(s.textChars()).isEqualTo(body.length());
            assertThat(s.expiresAt()).isEqualTo(s.fetchedAt().plusDays(30));
        });
        assertThat(result.getOutput().toString()).contains("[source:"+view.sources().get(0).sourceId()+"]");
        assertThat(journal.events(alice,run.id(),0,100).toString()).doesNotContain("Public title","private-query","hidden-value");
    }
    @Test void errorsEmptyRepliesAndUntrustedRequestAddressesCannotCreateSources() {
        var run=begin(alice,"session");var error=ToolResultBlock.error("private error body");
        assertThat(evidence.capture(alice,run.id(),"fetch-1",args(),error)).isSameAs(error);
        evidence.capture(alice,run.id(),"fetch-2",args(),ToolResultBlock.text(""));
        assertThatThrownBy(()->evidence.capture(alice,run.id(),"fetch-3",Map.of("url","http://127.0.0.1/"),ToolResultBlock.text("data"))).isInstanceOf(IllegalArgumentException.class);
        assertThat(evidence.view(alice,run.id()).sources()).isEmpty();
    }
    @Test void userAndRunIsolationApplyToSourcesAndAnswerReferenceValidation() {
        var first=begin(alice,"first");String id=capture(first,"fetch-1","# fact\nPublic fact");
        assertThatThrownBy(()->evidence.view(bob,first.id())).hasMessageContaining("404");
        var second=begin(alice,"second");evidence.recordAnswer(alice,second.id(),"Claim [source:"+id+"] [source:invented]");
        var view=evidence.view(alice,second.id());assertThat(view.sources()).isEmpty();assertThat(view.citations()).isEmpty();assertThat(view.unresolvedCitationCount()).isEqualTo(2);
        assertThatThrownBy(()->evidence.capture(bob,first.id(),"fetch-2",args(),ToolResultBlock.text("data"))).hasMessageContaining("404");
    }
    @Test void referencesBindToExactAnswerHashAndUtf16OffsetsAndDoNotRetainAnswerText() {
        var run=begin(alice,"session");String id=capture(run,"fetch-1","Public source");String marker="[source:"+id+"]", answer="A supplementary character \uD83D\uDE80 followed by PRIVATE_ANSWER "+marker;
        evidence.recordAnswer(alice,run.id(),answer);evidence.recordAnswer(alice,run.id(),answer);
        var view=evidence.view(alice,run.id());assertThat(view.answerSha256()).isEqualTo(ResearchEvidenceService.sha256(answer));
        assertThat(view.citations()).containsExactly(new ResearchEvidenceDtos.Citation(id,answer.indexOf(marker),answer.length()));
        assertThat(jdbc.queryForMap("SELECT * FROM agent_research_answer").toString()).doesNotContain("PRIVATE_ANSWER");
        assertThatThrownBy(()->evidence.recordAnswer(alice,run.id(),"different")).hasMessageContaining("409");
    }
    @Test void duplicateCallsAreStableButChangedInputsAndContentCannotOverwriteEvidence() {
        var run=begin(alice,"session");String id=capture(run,"fetch-1","Public source");assertThat(capture(run,"fetch-1","Public source")).isEqualTo(id);
        assertThatThrownBy(()->capture(run,"fetch-1","Changed source")).hasMessageContaining("409");
        assertThatThrownBy(()->evidence.capture(alice,run.id(),"fetch-1",Map.of("url","https://1.1.1.1/other"),ToolResultBlock.text("Public source"))).hasMessageContaining("409");
        assertThat(evidence.view(alice,run.id()).sources()).hasSize(1);
    }
    @Test void terminalAndExpiredRunsCannotAppendSourcesOrCitationsButCanReadHistory() {
        var run=begin(alice,"session");capture(run,"fetch-1","Public source");run.finish("COMPLETED");
        assertThat(evidence.view(alice,run.id()).sources()).hasSize(1);
        assertThatThrownBy(()->capture(run,"fetch-2","Public source")).hasMessageContaining("409");
        assertThatThrownBy(()->evidence.recordAnswer(alice,run.id(),"answer")).hasMessageContaining("409");
        var expired=begin(alice,"expired");jdbc.update("UPDATE agent_run SET lease_expires_at=? WHERE run_id=?",LocalDateTime.now().minusMinutes(1),expired.id());
        assertThatThrownBy(()->capture(expired,"fetch-1","data")).hasMessageContaining("409");
    }
    @Test void expiredSourcesReturnNoStoredAddressOrExcerptAndCannotAuthorizeANewCitation() {
        var run=begin(alice,"session");String id=capture(run,"fetch-1","PRIVATE_EXPIRED_SNIPPET");
        jdbc.update("UPDATE agent_research_source SET expires_at=?",LocalDateTime.now().minusDays(1));
        evidence.recordAnswer(alice,run.id(),"[source:"+id+"]");var view=evidence.view(alice,run.id());
        assertThat(view.expiredSourceCount()).isEqualTo(1);assertThat(view.sources()).isEmpty();assertThat(view.citations()).isEmpty();assertThat(view.unresolvedCitationCount()).isEqualTo(1);
        assertThat(view.toString()).doesNotContain("PRIVATE_EXPIRED_SNIPPET","1.1.1.1");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_source",Long.class)).isEqualTo(1); // logical expiry, not physical deletion
    }
    @Test void concurrentCaptureCannotExceedThePerRunBudget() throws Exception {
        var run=begin(alice,"session");for(int i=0;i<19;i++)capture(run,"fetch-"+i,"public");
        var pool=Executors.newFixedThreadPool(2);var start=new CountDownLatch(1);
        try {
            var jobs=new ArrayList<Future<Boolean>>();for(int i=19;i<21;i++){String call="fetch-"+i;jobs.add(pool.submit(()->{start.await();try{capture(run,call,"public");return true;}catch(org.springframework.web.server.ResponseStatusException error){assertThat(error.getStatusCode().value()).isEqualTo(409);return false;}}));}
            start.countDown();assertThat(List.of(jobs.get(0).get(5,TimeUnit.SECONDS),jobs.get(1).get(5,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);
        } finally {pool.shutdownNow();}
        assertThat(evidence.view(alice,run.id()).sources()).hasSize(20);
    }
    @Test void rawAndClasspathMigrationsAreIdentical() throws Exception {
        assertThat(Files.readAllBytes(Path.of("../sql/mysql/migration-V31-agent-research-evidence.sql")))
                .isEqualTo(Files.readAllBytes(Path.of("src/main/resources/db/migration-V31-agent-research-evidence.sql")));
    }
    @Test void nativeSdkFetchAndSharedConversationServicePersistSourceAndAnswerMapping() throws Exception {
        migrate(Path.of("../sql/mysql/migration-V25-local-mcp.sql"));
        var users=org.mockito.Mockito.mock(com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.class);
        org.mockito.Mockito.when(users.current(alice.userId(),alice.username())).thenReturn(new com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity(alice.userId(),alice.username(),false));
        var runtime=org.mockito.Mockito.mock(com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.class);
        org.mockito.Mockito.when(runtime.writesAllowed()).thenReturn(true);
        org.mockito.Mockito.when(runtime.install(org.mockito.ArgumentMatchers.any())).thenReturn(Map.of("serverKey","fetch","version","fixture"));
        var session=org.mockito.Mockito.mock(com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.Session.class);
        org.mockito.Mockito.when(session.call(org.mockito.ArgumentMatchers.any())).thenReturn(reactor.core.publisher.Mono.just(ToolResultBlock.text("# Public fixture\nA fact from the captured segment")));
        org.mockito.Mockito.when(runtime.open(org.mockito.ArgumentMatchers.any(),org.mockito.ArgumentMatchers.any())).thenReturn(session);
        var properties=new com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties();properties.setWorkspace(workspace.toString());
        var mcp=new com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService(jdbc,transactions,json,users,properties,runtime,evidence);
        try {
            mcp.schema();mcp.install(alice,0,"research-install-request",true);
            org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(3)).until(()->"INSTALLED".equals(mcp.view(alice).get("status")));
            mcp.enabled(alice,((Number)mcp.view(alice).get("revision")).intValue(),true);
            var model=org.mockito.Mockito.mock(io.agentscope.core.model.Model.class);
            org.mockito.Mockito.when(model.getModelName()).thenReturn("fixture-model");var calls=new java.util.concurrent.atomic.AtomicInteger();
            org.mockito.Mockito.when(model.stream(org.mockito.ArgumentMatchers.anyList(),org.mockito.ArgumentMatchers.anyList(),org.mockito.ArgumentMatchers.any())).thenAnswer(inv->{
                ContentBlock block;
                if(calls.getAndIncrement()==0) block=ToolUseBlock.builder().id("fetch-live-1").name(com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime.TOOL)
                        .input(Map.of("url","https://1.1.1.1/article")).content("{\"url\":\"https://1.1.1.1/article\"}").build();
                else {
                    String id=jdbc.queryForObject("SELECT source_id FROM agent_research_source",String.class);
                    assertThat(json.writeValueAsString(inv.getArgument(0))).contains("[source:"+id+"]");
                    block=TextBlock.builder().text("Public fact [source:"+id+"]").build();
                }
                return reactor.core.publisher.Flux.just(io.agentscope.core.model.ChatResponse.builder().content(List.of(block)).finishReason("stop").build());
            });
            var tools=new com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory(
                    org.mockito.Mockito.mock(com.ruanzhu.doorhandle.contracts.agent.DetectionAgentReadApi.class),
                    org.mockito.Mockito.mock(com.ruanzhu.doorhandle.contracts.agent.ResourceAgentReadApi.class),
                    org.mockito.Mockito.mock(com.ruanzhu.doorhandle.contracts.agent.ModelAgentReadApi.class),json);
            var factory=new com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory(properties,tools,id->model,null,mcp);
            var service=new com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService(factory,new com.ruanzhu.doorhandle.module.ai.agent.AgentRunRegistry(),properties,journal,evidence);
            var run=service.start(alice,"sdk-research",List.of(new com.ruanzhu.doorhandle.contracts.agent.AgentConversationApi.Message("user","Read https://1.1.1.1/article")),"",event->{});
            String answer=run.result().get(15,TimeUnit.SECONDS);
            var view=evidence.view(alice,run.runId());assertThat(view.sources()).hasSize(1);assertThat(view.citations()).hasSize(1);
            assertThat(view.answerSha256()).isEqualTo(ResearchEvidenceService.sha256(answer));
            assertThat(journal.get(alice,run.runId()).status()).isEqualTo("COMPLETED");
            org.mockito.Mockito.verify(session).close();org.mockito.Mockito.verify(session).call(org.mockito.ArgumentMatchers.any());
        } finally {mcp.close();}
    }
}
