package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.control.ConversationControlRegistry;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.app.service.impl.*;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.task.SyncTaskExecutor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import reactor.core.publisher.*;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;
import static org.mockito.Mockito.*;

/** 两模块真实门面 + JDBC 队列/日志 + 原生 Harness，模型与外部业务使用隔离替身。 */
@Timeout(25)
class ConversationControlIntegrationTest {
    @TempDir Path workspace;
    final AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    @Test void queuedConversationPausesAcceptsSteeringResumesAndThenRunsTheNextTurn()throws Exception{
        var source=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");var jdbc=new JdbcTemplate(source);var manager=new DataSourceTransactionManager(source);
        for(String filename:List.of("migration-V16-agentscope-run-journal.sql","migration-V36-conversation-inbox.sql")){
            String ddl=Files.readString(Path.of("../sql/mysql",filename)).replaceAll("(?m)^--.*$", "").replaceAll(" COLLATE utf8mb4_bin","").replaceAll(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replace(" COLLATE=utf8mb4_bin","").replace("payload_json JSON","payload_json VARCHAR(8192)")
                    .replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3").replaceAll("(?m)^\\s*KEY .*\\n","").replaceAll(",\\s*\\)",")");
            for(String sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        }
        var journalProperties=new AgentJournalProperties();journalProperties.setEnabled(true);var json=new ObjectMapper();var journal=new JdbcAgentJournal(jdbc,manager,json,journalProperties);journal.verifySchema();
        var inputRef=new AtomicReference<AgentSteeringInboxApi>();var inputProvider=mock(ObjectProvider.class);when(inputProvider.getIfAvailable()).thenAnswer(inv->inputRef.get());
        var controls=new ConversationControlRegistry(journal,inputProvider);
        var model=mock(Model.class);when(model.getModelName()).thenReturn("fixture");var firstResponse=Sinks.<ChatResponse>one();var requests=new AtomicInteger();var received=new CopyOnWriteArrayList<List<Msg>>();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{received.add(List.copyOf(inv.getArgument(0)));int index=requests.incrementAndGet();if(index==1)return firstResponse.asMono().flux();return Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text(index==2?"专业结果":index==3?"第一轮完成":"第二轮完成").build())).finishReason("stop").build());});
        var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
        var factory=new RoleAgentFactory(settings,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json),id->model);
        var api=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings,journal,null,controls);
        var apiProvider=mock(ObjectProvider.class);when(apiProvider.getIfAvailable()).thenReturn(api);
        var messages=new CopyOnWriteArrayList<ChatMessageResponse>();var nextId=new AtomicLong();var sessions=mock(ChatSessionService.class);
        when(sessions.resolveTenantForSystemCallback("s1")).thenReturn(new TenantContext(1L,"alice"));when(sessions.listMessages("alice","s1")).thenAnswer(inv->List.copyOf(messages));
        when(sessions.appendUserMessage(any(TenantContext.class),eq("s1"),anyString())).thenAnswer(inv->append(messages,nextId,"user",inv.getArgument(2),"TEXT"));
        when(sessions.appendAssistantMessage(any(TenantContext.class),eq("s1"),anyString(),anyString(),anyString(),isNull())).thenAnswer(inv->append(messages,nextId,"assistant",inv.getArgument(2),inv.getArgument(3)));
        var chatProperties=new ChatAssistantProperties();chatProperties.setEnabled(true);
        var chat=new AgentScopeChatServiceImpl(sessions,apiProvider,mock(RagKnowledgeService.class),mock(Mem0Client.class),new SyncTaskExecutor(),chatProperties,json);
        var users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        var controlProvider=mock(ObjectProvider.class);when(controlProvider.getIfAvailable()).thenReturn(controls);when(controlProvider.getObject()).thenReturn(controls);
        var inbox=new ConversationInboxService(jdbc,manager,sessions,chat,users,controlProvider);inputRef.set(inbox);inbox.schema();
        try{
            var first=inbox.enqueue(actor,"s1",UUID.randomUUID().toString(),"NEXT_TURN","先查询检测任务");inbox.dispatch();
            await().atMost(Duration.ofSeconds(5)).until(()->requests.get()==1);
            var view=controls.inspect(actor,"s1");String run=view.runId();assertThat(run).isNotBlank();controls.command(actor,"s1",run,"pause",view.revision());
            var second=inbox.enqueue(actor,"s1",UUID.randomUUID().toString(),"NEXT_TURN","下一轮核对报告","AGUI");
            var steering=inbox.enqueue(actor,"s1",UUID.randomUUID().toString(),"NEXT_STEP","FOCUS_ON_SOURCES");
            firstResponse.tryEmitValue(ChatResponse.builder().content(List.of(new ToolUseBlock("delegate-1","delegate_detection_task",Map.of("question","查询检测任务")))).finishReason("tool_calls").build());
            await().atMost(Duration.ofSeconds(5)).until(()->"PAUSED".equals(controls.inspect(actor,"s1").phase()));assertThat(requests.get()).isEqualTo(1);
            inbox.dispatch();assertThat(jdbc.queryForObject("SELECT status FROM agent_conversation_input WHERE input_id=?",String.class,second.id())).isEqualTo("QUEUED");
            controls.command(actor,"s1",run,"resume",controls.inspect(actor,"s1").revision());
            await().atMost(Duration.ofSeconds(8)).until(()->"COMPLETED".equals(jdbc.queryForObject("SELECT status FROM agent_conversation_input WHERE input_id=?",String.class,first.id())));
            assertThat(jdbc.queryForObject("SELECT status FROM agent_conversation_input WHERE input_id=?",String.class,steering.id())).isEqualTo("APPLIED");
            inbox.dispatch();await().atMost(Duration.ofSeconds(5)).until(()->"COMPLETED".equals(jdbc.queryForObject("SELECT status FROM agent_conversation_input WHERE input_id=?",String.class,second.id())));
            assertThat(journal.list(actor,"s1",null,20)).hasSize(2).allSatisfy(item->assertThat(item.status()).isEqualTo("COMPLETED"));
            assertThat(journal.list(actor,"s1",null,20)).extracting(AgentJournal.RunView::entryPoint).containsExactlyInAnyOrder("CHAT","AGUI");
            assertThat(messages.stream().filter(item->"user".equals(item.getRole())).map(ChatMessageResponse::getContent).toList()).containsExactly("先查询检测任务","FOCUS_ON_SOURCES","下一轮核对报告");
            assertThat(received.get(2).stream().filter(item->item.getTextContent()!=null&&item.getTextContent().contains("FOCUS_ON_SOURCES")).count()).isEqualTo(1);
            assertThat(journal.events(actor,run,0,100)).extracting(AgentJournal.EventView::type).contains("PAUSE_REQUESTED","RUN_PAUSED","RUN_RESUMED","STEERING_APPLIED");
        }finally{inbox.close();}
    }
    private ChatMessageResponse append(List<ChatMessageResponse> messages,AtomicLong next,String role,String content,String type){var item=new ChatMessageResponse();item.setId(next.incrementAndGet());item.setSessionId("s1");item.setRole(role);item.setContent(content);item.setMessageType(type);messages.add(item);return item;}
}
