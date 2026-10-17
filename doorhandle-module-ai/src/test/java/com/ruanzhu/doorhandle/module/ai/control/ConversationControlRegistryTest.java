package com.ruanzhu.doorhandle.module.ai.control;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.ObjectProvider;
import reactor.core.publisher.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;
import static org.mockito.Mockito.*;

@Timeout(15)
class ConversationControlRegistryTest {
    final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.SUPERVISOR);
    AgentJournal journal;AgentJournal.Run audit;AgentSteeringInboxApi inbox;ConversationControlRegistry controls;
    ConversationControlRegistry.Handle handle;Model model;ReActAgent agent;
    @BeforeEach void setup(){
        journal=mock(AgentJournal.class);audit=mock(AgentJournal.Run.class);inbox=mock(AgentSteeringInboxApi.class);when(journal.enabled()).thenReturn(true);when(audit.id()).thenReturn("run-1");
        var provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(inbox);controls=new ConversationControlRegistry(journal,provider);controls.validate();handle=controls.attach(alice,"s1",audit);
        model=mock(Model.class);when(model.getModelName()).thenReturn("fixture");when(model.stream(anyList(),anyList(),any())).thenReturn(Flux.just(answer("完成")));
    }
    @AfterEach void close(){handle.close();if(agent!=null)agent.close();}
    ChatResponse answer(String text){return ChatResponse.builder().content(List.of(TextBlock.builder().text(text).build())).finishReason("stop").build();}
    ReActAgent build(Toolkit tools){agent=ReActAgent.builder().name("employee-main").sysPrompt("IMMUTABLE_SYSTEM_RULE").model(model).toolkit(tools).middlewares(List.of(handle)).maxIters(3)
            .stateStore(new io.agentscope.core.state.InMemoryAgentStateStore()).defaultSessionId("fixture").enableMetaTool(false).enableTaskList(false).build();return agent;}
    @Test void realSdkPausesBeforeModelRequestAndContinuesTheSameExecution()throws Exception{
        controls.command(alice,"s1","run-1","pause",0);var result=build(new Toolkit()).call("query").toFuture();
        await().atMost(Duration.ofSeconds(3)).until(()->"PAUSED".equals(handle.view().phase()));verify(model,never()).stream(anyList(),anyList(),any());assertThat(result).isNotDone();
        controls.command(alice,"s1","run-1","resume",handle.view().revision());assertThat(result.get(3,TimeUnit.SECONDS).getTextContent()).isEqualTo("完成");
        verify(audit).event(eq("PAUSE_REQUESTED"),anyMap());verify(audit).event(eq("RUN_PAUSED"),anyMap());verify(audit).event(eq("RUN_RESUMED"),anyMap());
    }
    @Test void aRunningToolFinishesBeforeTheNextModelBoundaryActuallyPauses()throws Exception{
        var pending=Sinks.<ToolResultBlock>one();var entered=new CountDownLatch(1);var tools=new Toolkit();
        tools.registerAgentTool(new AgentTool(){public String getName(){return "lookup";}public String getDescription(){return "read";}public boolean isReadOnly(){return true;}public Map<String,Object>getParameters(){return Map.of("type","object","properties",Map.of());}public Mono<ToolResultBlock>callAsync(ToolCallParam p){entered.countDown();return pending.asMono();}});
        var calls=new java.util.concurrent.atomic.AtomicInteger();when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->calls.getAndIncrement()==0?Flux.just(ChatResponse.builder().content(List.of(new ToolUseBlock("tool-1","lookup",Map.of()))).finishReason("tool_calls").build()):Flux.just(answer("完成")));
        var result=build(tools).call("query").toFuture();assertThat(entered.await(3,TimeUnit.SECONDS)).isTrue();controls.command(alice,"s1","run-1","pause",0);
        assertThat(handle.view().phase()).isEqualTo("PAUSE_REQUESTED");assertThat(calls.get()).isEqualTo(1);
        pending.tryEmitValue(ToolResultBlock.text("fact"));await().atMost(Duration.ofSeconds(3)).until(()->"PAUSED".equals(handle.view().phase()));assertThat(calls.get()).isEqualTo(1);
        controls.command(alice,"s1","run-1","resume",handle.view().revision());assertThat(result.get(3,TimeUnit.SECONDS).getTextContent()).isEqualTo("完成");
    }
    @Test void steeringIsUserInputAndRemainsPresentOnceInEveryLaterModelRequest()throws Exception{
        when(inbox.take(alice,"s1","run-1")).thenReturn(List.of(new AgentSteeringInboxApi.Input("input-one","FOCUS_ON_TESTS")),List.of());
        var requests=new CopyOnWriteArrayList<List<Msg>>();var calls=new java.util.concurrent.atomic.AtomicInteger();var tools=new Toolkit();
        tools.registerAgentTool(new AgentTool(){public String getName(){return "lookup";}public String getDescription(){return "read";}public boolean isReadOnly(){return true;}public Map<String,Object>getParameters(){return Map.of("type","object","properties",Map.of());}public Mono<ToolResultBlock>callAsync(ToolCallParam p){return Mono.just(ToolResultBlock.text("fact"));}});
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{requests.add(List.copyOf(inv.getArgument(0)));return calls.getAndIncrement()==0?Flux.just(ChatResponse.builder().content(List.of(new ToolUseBlock("tool-1","lookup",Map.of()))).finishReason("tool_calls").build()):Flux.just(answer("完成"));});
        assertThat(build(tools).call("query").block(Duration.ofSeconds(4)).getTextContent()).isEqualTo("完成");
        assertThat(requests).hasSize(2);for(var messages:requests){assertThat(messages.stream().filter(msg->msg.getTextContent()!=null&&msg.getTextContent().contains("FOCUS_ON_TESTS")).toList()).singleElement().satisfies(msg->assertThat(msg).isInstanceOf(UserMessage.class));}
        verify(audit).event(eq("STEERING_APPLIED"),eq(Map.of("agent","employee-main","inputId","input-one")));
    }
    @Test void oldRevisionCannotResumeAPauseOrDuplicateItsAudit(){
        controls.command(alice,"s1","run-1","pause",0);
        assertThatThrownBy(()->controls.command(alice,"s1","run-1","resume",0)).hasMessageContaining("409");verify(audit,times(1)).event(eq("PAUSE_REQUESTED"),anyMap());assertThat(handle.view().phase()).isEqualTo("PAUSE_REQUESTED");
    }
    @Test void foreignUserCannotControlOrReadALocalPrivateHandle(){
        when(journal.get(bob,"run-1")).thenThrow(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.NOT_FOUND));
        assertThatThrownBy(()->controls.command(bob,"s1","run-1","pause",0)).hasMessageContaining("404");assertThat(controls.inspect(bob,"s1").phase()).isEqualTo("IDLE");verify(audit,never()).event(anyString(),anyMap());
    }
    @Test void closingWhilePausedUnblocksTheSdkAndDoesNotResumeOrCallTheModel(){
        controls.command(alice,"s1","run-1","pause",0);var result=build(new Toolkit()).call("query").toFuture();await().atMost(Duration.ofSeconds(3)).until(()->"PAUSED".equals(handle.view().phase()));
        handle.close();await().atMost(Duration.ofSeconds(3)).until(result::isDone);verify(model,never()).stream(anyList(),anyList(),any());assertThat(controls.inspect(alice,"s1").phase()).isEqualTo("IDLE");
    }
    @Test void partialTextIsBoundedAndRemovedWhenTheHandleCloses(){handle.text("x".repeat(80000));assertThat(handle.view().text()).hasSize(64000);handle.close();assertThat(handle.view().text()).isEmpty();}
    @Test void controlRequiresDurableRunJournal(){when(journal.enabled()).thenReturn(false);assertThatThrownBy(controls::validate).hasMessageContaining("运行日志");}
    @Test void roleChangesWhilePausedAreRecheckedBeforeResumingTheModel(){
        handle.close();var users=mock(com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.class);
        when(users.current(1,"alice")).thenReturn(new com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity(1,"alice",false));
        var provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(inbox);controls=new ConversationControlRegistry(journal,provider,users);handle=controls.attach(alice,"s1",audit);
        controls.command(alice,"s1","run-1","pause",0);var result=build(new Toolkit()).call("query").toFuture();
        await().atMost(Duration.ofSeconds(3)).until(()->"PAUSED".equals(handle.view().phase()));when(users.current(1,"alice")).thenReturn(new com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity(1,"alice",true));
        controls.command(alice,"s1","run-1","resume",handle.view().revision());await().atMost(Duration.ofSeconds(3)).until(result::isDone);
        assertThat(result).isCompletedExceptionally();verify(model,never()).stream(anyList(),anyList(),any());verify(audit).event(eq("AUTHORIZATION_DENIED"),anyMap());
    }
}
