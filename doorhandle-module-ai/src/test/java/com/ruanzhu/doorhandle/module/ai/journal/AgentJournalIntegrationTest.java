package com.ruanzhu.doorhandle.module.ai.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.api.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import reactor.core.publisher.Flux;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.mockito.Mockito.*;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentJournalIntegrationTest {
    @Test void actualHarnessUsesControlMiddlewareAndPersistsOnlyControlMetadata() throws Exception {
        var inbox=mock(AgentSteeringInboxApi.class);
        when(inbox.take(any(),anyString(),anyString())).thenReturn(List.of(new AgentSteeringInboxApi.Input("input-control-fixture","PRIVATE_STEERING")));
        var provider=mock(org.springframework.beans.factory.ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(inbox);
        var controls=new com.ruanzhu.doorhandle.module.ai.control.ConversationControlRegistry(journal,provider);
        var audit=journal.begin(actor,"controlled-session","employee-main","CHAT","control-fixture","fixture");
        var handle=controls.attach(actor,"controlled-session",audit);
        controls.command(actor,"controlled-session",audit.id(),"pause",0);
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(audit,actor),null,null,handle)){
            var answer=agent.call("PRIVATE_QUESTION").toFuture();
            org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(3)).until(()->"PAUSED".equals(handle.view().phase()));
            verify(model,never()).stream(anyList(),anyList(),any());controls.command(actor,"controlled-session",audit.id(),"resume",handle.view().revision());
            assertThat(answer.get(5,TimeUnit.SECONDS).getTextContent()).isEqualTo("PRIVATE_REPLY");audit.finish("COMPLETED");
            var events=journal.events(actor,audit.id(),0,100);
            assertThat(events).extracting(AgentJournal.EventView::type).contains("PAUSE_REQUESTED","RUN_PAUSED","RUN_RESUMED","STEERING_APPLIED");
            assertThat(events.toString()).contains("input-control-fixture").doesNotContain("PRIVATE_QUESTION","PRIVATE_STEERING","PRIVATE_REPLY");
        }finally{handle.close();}
    }
    @TempDir Path workspace;
    private final AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    private JdbcAgentJournal journal;private RoleAgentFactory factory;private AgentScopeProperties settings;private Model model;
    @BeforeEach void setup() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        var jdbc=new JdbcTemplate(source);
        String ddl=Files.readString(Path.of("src/main/resources/db/migration-V16-agentscope-run-journal.sql"))
            .replaceAll(" COLLATE utf8mb4_bin","").replaceAll(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replace("payload_json JSON","payload_json VARCHAR(8192)");
        for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        var props=new AgentJournalProperties();props.setEnabled(true);journal=new JdbcAgentJournal(jdbc,new DataSourceTransactionManager(source),new ObjectMapper(),props);
        settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
        model=mock(Model.class);when(model.getModelName()).thenReturn("fixture-model");
        when(model.stream(anyList(),anyList(),any())).thenReturn(Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("PRIVATE_REPLY").build())).finishReason("stop").build()));
        factory=new RoleAgentFactory(settings,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper()),id->model);
    }
    private UsernamePasswordAuthenticationToken auth() {
        var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
        return new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);
    }
    @Test void nativeCompactionUsesTheSameOwnedJournalWithoutPersistingSummaryOrHistory() throws Exception {
        var config=settings.getContextCompaction();config.setEnabled(true);config.setTriggerMessages(4);config.setKeepMessages(2);config.setTriggerTokens(1000000);
        when(model.stream(anyList(),isNull(),any())).thenReturn(Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("{\"intent\":\"PRIVATE_SUMMARY\",\"facts\":[],\"constraints\":[],\"pending\":[]}").build())).usage(ChatUsage.builder().inputTokens(80).outputTokens(20).build()).build()));
        var history=new ArrayList<AgentConversationApi.Message>();
        for(int i=0;i<3;i++){history.add(new AgentConversationApi.Message("user","PRIVATE_HISTORY "+"x".repeat(500)));history.add(new AgentConversationApi.Message("assistant","OLD_REPLY "+"x".repeat(500)));}
        history.add(new AgentConversationApi.Message("user","CURRENT_PRIVATE_QUESTION"));
        var connections=new AgentModelProperties();connections.getDeepseek().setModel("context-fixture");settings.setModel("deepseek:context-fixture");
        var models=new com.ruanzhu.doorhandle.module.ai.model.AgentModelService(connections,settings);
        @SuppressWarnings("unchecked") var modelCache=(Map<String,Model>)org.springframework.test.util.ReflectionTestUtils.getField(models,"models");modelCache.put("deepseek:context-fixture",model);
        var contextFactory=new RoleAgentFactory(settings,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper()),models::resolve);
        var service=new AgentScopeConversationService(contextFactory,new AgentRunRegistry(),settings,journal);
        var run=service.start(actor,"compaction-session",history,"",event->{});
        assertThat(run.result().get(15,TimeUnit.SECONDS)).isEqualTo("PRIVATE_REPLY");
        var events=journal.events(actor,run.runId(),0,100);
        assertThat(events).extracting(AgentJournal.EventView::type).contains("CONTEXT_STARTED","CONTEXT_COMPLETED");
        assertThat(events).anySatisfy(event->{assertThat(event.type()).isEqualTo("CONTEXT_COMPLETED");assertThat(event.payload()).containsEntry("beforeMessages",7).containsEntry("afterMessages",3);});
        assertThat(events).anySatisfy(event->{assertThat(event.type()).isEqualTo("MODEL_COMPLETED");assertThat(event.payload()).containsEntry("purpose","CONTEXT_COMPACTION").containsEntry("inputTokens",80);});
        assertThat(events).anySatisfy(event->{assertThat(event.type()).isEqualTo("MODEL_ATTEMPT_COMPLETED");assertThat(event.payload()).containsEntry("purpose","CONTEXT_COMPACTION").containsEntry("provider","deepseek");});
        assertThat(events.toString()).doesNotContain("PRIVATE_SUMMARY","PRIVATE_HISTORY","CURRENT_PRIVATE_QUESTION","PRIVATE_REPLY");
        assertThatThrownBy(()->journal.events(new AgentActor(2,"boss",AgentActor.Role.SUPERVISOR),run.runId(),0,100)).hasMessageContaining("404");
        try(var paths=Files.walk(workspace)){assertThat(paths.filter(Files::isRegularFile).toList()).isEmpty();}
    }
    @Test void sdkMainAndDelegatedModelAttemptsPersistWithSeparateRequestIdsAndTheSameOwner() throws Exception {
        var connections=new AgentModelProperties();connections.setFallbackEnabled(true);
        connections.getOpenai().setModel("primary");connections.getDeepseek().setModel("backup");
        connections.setFallbackModels(List.of("deepseek:backup"));settings.setModel("openai-official:primary");
        var primary=mock(Model.class);when(primary.getModelName()).thenReturn("primary");
        when(primary.stream(anyList(),anyList(),any())).thenReturn(Flux.error(new io.agentscope.core.model.transport.HttpTransportException("PRIVATE_SECRET",402,"PRIVATE_ERROR_BODY")));
        when(model.getModelName()).thenReturn("backup");var step=new java.util.concurrent.atomic.AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            io.agentscope.core.message.ContentBlock block=switch(step.getAndIncrement()) {
                case 0 -> io.agentscope.core.message.ToolUseBlock.builder().id("delegate-1").name("delegate_detection_task")
                        .input(Map.of("question","PRIVATE_QUESTION")).content("{\"question\":\"PRIVATE_QUESTION\"}").build();
                case 1 -> new io.agentscope.core.message.ToolUseBlock("query-1","get_my_detection_tasks",Map.of());
                default -> TextBlock.builder().text("PRIVATE_REPLY").build();
            };
            return Flux.just(ChatResponse.builder().content(List.of(block)).finishReason("stop").build());
        });
        var models=new com.ruanzhu.doorhandle.module.ai.model.AgentModelService(connections,settings);
        @SuppressWarnings("unchecked") var cache=(Map<String,Model>)org.springframework.test.util.ReflectionTestUtils.getField(models,"models");
        cache.put("openai-official:primary",primary);cache.put("deepseek:backup",model);
        var detection=mock(DetectionAgentReadApi.class);when(detection.tasks(actor,1,20,false)).thenReturn(new DetectionAgentReadApi.TaskPage(List.of(),0,1,20));
        var routedFactory=new RoleAgentFactory(settings,new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper()),models::resolve);
        var run=journal.begin(actor,"routed-session","employee-main","CHAT","routed-request",settings.getModel());
        try(var runtime=(io.agentscope.harness.agent.HarnessAgent)routedFactory.create(actor,null,new AgentJournalMiddleware(run,actor))) {
            assertThat(runtime.call("PRIVATE_QUESTION").block(java.time.Duration.ofSeconds(15)).getTextContent()).isEqualTo("PRIVATE_REPLY");
        } catch(RuntimeException error) {throw new AssertionError("Recorded events: "+journal.events(actor,run.id(),0,100),error);}
        run.finish("COMPLETED");
        var rows=journal.events(actor,run.id(),0,100);
        assertThat(rows).extracting(AgentJournal.EventView::type).contains("MODEL_ATTEMPT_ERROR","MODEL_FALLBACK_SELECTED","MODEL_CANDIDATE_SKIPPED","MODEL_ATTEMPT_COMPLETED");
        var starts=rows.stream().filter(e->e.type().equals("MODEL_STARTED")).toList();
        assertThat(starts).hasSize(4);assertThat(starts).extracting(e->e.payload().get("modelRequestId")).doesNotHaveDuplicates();
        for(var start:starts) {
            assertThat(rows.stream().filter(e->e.type().equals("MODEL_ATTEMPT_COMPLETED")&&Objects.equals(e.payload().get("modelRequestId"),start.payload().get("modelRequestId"))).toList())
                    .singleElement().satisfies(e->assertThat(e.payload()).containsEntry("provider","deepseek").containsEntry("model","backup").containsEntry("agent",start.payload().get("agent")));
        }
        assertThat(rows).anySatisfy(e->{assertThat(e.type()).isEqualTo("MODEL_ATTEMPT_COMPLETED");assertThat(e.payload()).containsEntry("agent","detection-task").containsEntry("parentCallId","delegate-1");});
        assertThat(rows.toString()).doesNotContain("PRIVATE_QUESTION","PRIVATE_REPLY","PRIVATE_SECRET","PRIVATE_ERROR_BODY");
        var bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
        assertThatThrownBy(()->journal.events(bob,run.id(),0,100)).hasMessageContaining("404");
        verify(detection).tasks(actor,1,20,false);
    }
    @Test void mainSiteReturnsTheDurableRunIdAndTheCompletedEventHistorySurvivesServiceRecreation() throws Exception {
        var service=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings,journal);
        var run=service.start(actor,"s1",List.of(new AgentConversationApi.Message("user","PRIVATE_QUESTION")),"",event->{});
        assertThat(run.result().get(10,TimeUnit.SECONDS)).isEqualTo("PRIVATE_REPLY");
        assertThat(journal.get(actor,run.runId()).status()).isEqualTo("COMPLETED");
        assertThat(journal.events(actor,run.runId(),0,100).toString()).doesNotContain("PRIVATE_QUESTION","PRIVATE_REPLY");
        assertThat(journal.events(actor,run.runId(),0,100)).extracting(AgentJournal.EventView::type).contains("AGENT_STARTED","AGENT_COMPLETED","RUN_COMPLETED");
        assertThat(journal.list(actor,"s1",null,20)).singleElement().satisfies(saved->assertThat(saved.runId()).isEqualTo(run.runId()));
    }
    @Test void cancellationUsesTheActualNativeRunAndReleasesBothDatabaseAndProcessLocks() throws Exception {
        when(model.stream(anyList(),anyList(),any())).thenReturn(Flux.never());
        var service=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings,journal);
        var run=service.start(actor,"s1",List.of(new AgentConversationApi.Message("user","PRIVATE_QUESTION")),"",event->{});
        assertThat(journal.cancel(actor,run.runId()).status()).isEqualTo("CANCELLED");
        assertThat(run.result().isCancelled()).isTrue();
        when(model.stream(anyList(),anyList(),any())).thenReturn(Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("PRIVATE_REPLY").build())).finishReason("stop").build()));
        var next=service.start(actor,"s1",List.of(new AgentConversationApi.Message("user","next")),"",event->{});
        assertThat(next.result().get(10,TimeUnit.SECONDS)).isEqualTo("PRIVATE_REPLY");
        assertThat(journal.get(actor,next.runId()).status()).isEqualTo("COMPLETED");
        assertThat(journal.list(actor,"s1",null,20)).hasSize(2);
    }
    @Test void aguiCompletesOneDurableRunAndDuplicateClientRunIdDoesNotGenerateAgain() throws Exception {
        var service=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings,journal);
        AgentChatSessionApi gateway=(user,session,requestId,question,events)->{
            var run=service.start(user,session,List.of(new AgentConversationApi.Message("user",question)),"",events,"AGUI",requestId);
            return new AgentChatSessionApi.Run(run.result().thenApply(text->new AgentChatSessionApi.Reply(text,run.runId(),run.cards().get())),run.cancel());
        };
        var mvc=MockMvcBuilders.standaloneSetup(new RoleAgentController(factory,gateway)).build();
        String body="{\"threadId\":\"s1\",\"runId\":\"request-1\",\"messages\":[{\"id\":\"m1\",\"role\":\"user\",\"content\":\"PRIVATE_QUESTION\"}]}";
        var response=mvc.perform(post("/agui/run").principal(auth()).contentType("application/json").content(body)).andExpect(request().asyncStarted()).andReturn();
        response.getAsyncResult(10000);
        mvc.perform(asyncDispatch(response)).andExpect(status().isOk()).andExpect(content().string(org.hamcrest.Matchers.containsString("RUN_FINISHED")));
        assertThat(journal.list(actor,"s1",null,20)).singleElement().satisfies(saved->{assertThat(saved.entryPoint()).isEqualTo("AGUI");assertThat(saved.status()).isEqualTo("COMPLETED");});
        mvc.perform(post("/agui/run").principal(auth()).contentType("application/json").content(body)).andExpect(status().isConflict());
        assertThat(journal.list(actor,"s1",null,20)).hasSize(1);
    }
    @Test void historyAndCursorApiAreReadOnlyAndCancellationRequiresTheActionHeader() throws Exception {
        var run=journal.begin(actor,"s1","employee-main","CHAT","request-1","fixture-model");run.bindCancel(()->run.finish("CANCELLED"));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentRunController(journal)).build();
        mvc.perform(get("/api/agent/runs").principal(auth())).andExpect(status().isOk()).andExpect(jsonPath("$[0].runId").value(run.id()));
        mvc.perform(get("/api/agent/runs/"+run.id()+"/events").param("after","0").principal(auth())).andExpect(status().isOk()).andExpect(jsonPath("$[0].sequence").value(1));
        mvc.perform(post("/api/agent/runs/"+run.id()+"/cancel").principal(auth())).andExpect(status().isBadRequest());
        assertThat(journal.get(actor,run.id()).status()).isEqualTo("RUNNING");
        mvc.perform(post("/api/agent/runs/"+run.id()+"/cancel").principal(auth()).header("X-Agent-Action","cancel")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("CANCELLED"));
    }
}
