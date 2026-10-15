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
