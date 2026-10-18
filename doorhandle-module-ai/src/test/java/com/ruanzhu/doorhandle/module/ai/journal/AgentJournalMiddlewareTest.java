package com.ruanzhu.doorhandle.module.ai.journal;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentscope.core.agent.*;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.middleware.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.publisher.Flux;
import java.nio.file.Path;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.assertj.core.api.Assertions.*;

class AgentJournalMiddlewareTest {
    @TempDir Path workspace;
    private final AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    @Test void actualMainDelegateAndBusinessToolAllAppearInTheSameRunWithoutBodies() {
        var run=mock(AgentJournal.Run.class);var events=new ArrayList<Map<String,Object>>();var types=new ArrayList<String>();
        doAnswer(call->{types.add(call.getArgument(0));events.add(call.getArgument(1));return null;}).when(run).event(anyString(),anyMap());
        var model=mock(Model.class);when(model.getModelName()).thenReturn("fixture");var step=new java.util.concurrent.atomic.AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{int i=step.getAndIncrement();ContentBlock block=switch(i){
            case 0->ToolUseBlock.builder().id("delegate-1").name("delegate_detection_task").input(Map.of("question","PRIVATE_QUESTION")).content("{\"question\":\"PRIVATE_QUESTION\"}").build();
            case 1->new ToolUseBlock("query-1","get_my_detection_tasks",Map.of());
            default->TextBlock.builder().text("PRIVATE_ANSWER").build();};return Flux.just(ChatResponse.builder().content(List.of(block)).build());});
        var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
        var detection=mock(DetectionAgentReadApi.class);when(detection.tasks(actor,1,20,false)).thenReturn(new DetectionAgentReadApi.TaskPage(List.of(),0,1,20));
        var factory=new RoleAgentFactory(settings,new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper()),id->model);
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(run,actor))){
            try { assertThat(agent.call("PRIVATE_USER_INPUT").block(java.time.Duration.ofSeconds(10)).getTextContent()).isEqualTo("PRIVATE_ANSWER"); }
            catch (RuntimeException error) { throw new AssertionError("Metadata events: "+events,error); }
        }
        assertThat(types).contains("AGENT_STARTED","AGENT_COMPLETED","AUTHORIZATION_ALLOWED","TOOL_STARTED","TOOL_COMPLETED","MODEL_STARTED");
        assertThat(types).doesNotContain("AGENT_CANCELLED","AGENT_ERROR");
        assertThat(events.toString()).contains("employee-main","detection-task","delegate_detection_task","get_my_detection_tasks","query-1")
                .doesNotContain("PRIVATE_QUESTION","PRIVATE_ANSWER","PRIVATE_USER_INPUT");
        assertThat(events).anySatisfy(payload -> {
            assertThat(payload.get("tool")).isEqualTo("get_my_detection_tasks");
            assertThat(payload.get("parentCallId")).isEqualTo("delegate-1");
        });
        assertThat(events.stream().filter(payload -> payload.containsKey("scope")).toList())
                .isNotEmpty().allSatisfy(payload -> assertThat(payload.get("scope")).isEqualTo("OWNED_OR_ASSIGNED"));
        verify(detection).tasks(actor,1,20,false);
    }
    @Test void closeDuringCompletionCallbackDoesNotRecordASecondTerminalState() {
        var run=mock(AgentJournal.Run.class);var agent=mock(Agent.class);when(agent.getName()).thenReturn("employee-main");
        var subscription=new java.util.concurrent.atomic.AtomicReference<reactor.core.Disposable>();
        doAnswer(inv->{subscription.get().dispose();return null;}).when(run).event(eq("AGENT_COMPLETED"),anyMap());
        var upstream=reactor.core.publisher.Sinks.many().unicast().<io.agentscope.core.event.AgentEvent>onBackpressureBuffer();
        subscription.set(new AgentJournalMiddleware(run,actor).onAgent(agent,RuntimeContext.empty(),mock(AgentInput.class),input->upstream.asFlux()).subscribe());
        upstream.tryEmitComplete();
        verify(run).event(eq("AGENT_COMPLETED"),anyMap());verify(run,never()).event(eq("AGENT_CANCELLED"),anyMap());
    }
    @Test void persistedWorkbenchYieldIsWaitingRatherThanAnExecutionError() {
        var run=mock(AgentJournal.Run.class);var agent=mock(Agent.class);when(agent.getName()).thenReturn("employee-main");
        var middleware=new AgentJournalMiddleware(run,actor);
        assertThatThrownBy(()->middleware.onAgent(agent,RuntimeContext.empty(),mock(AgentInput.class),input->Flux.error(new com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService.Yield())).blockLast()).isInstanceOf(com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService.Yield.class);
        assertThatThrownBy(()->middleware.onModelCall(agent,RuntimeContext.empty(),mock(io.agentscope.core.middleware.ModelCallInput.class),input->Flux.error(new com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService.Yield())).blockLast()).isInstanceOf(com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService.Yield.class);
        verify(run).event(eq("AGENT_YIELDED"),anyMap());verify(run).event(eq("MODEL_YIELDED"),anyMap());
        verify(run,never()).event(eq("AGENT_ERROR"),anyMap());verify(run,never()).event(eq("MODEL_ERROR"),anyMap());
        verify(run,never()).event(eq("AGENT_COMPLETED"),anyMap());verify(run,never()).event(eq("AGENT_CANCELLED"),anyMap());
    }
    @Test void genuineCancellationAndFailureRetainTheirOwnTerminalEvidence() {
        var run=mock(AgentJournal.Run.class);var agent=mock(Agent.class);when(agent.getName()).thenReturn("employee-main");
        var middleware=new AgentJournalMiddleware(run,actor);
        var subscription=middleware.onAgent(agent,RuntimeContext.empty(),mock(AgentInput.class),input->Flux.never()).subscribe();
        subscription.dispose();subscription.dispose();
        verify(run).event(eq("AGENT_CANCELLED"),anyMap());verify(run,never()).event(eq("AGENT_COMPLETED"),anyMap());
        reset(run);
        assertThatThrownBy(()->middleware.onAgent(agent,RuntimeContext.empty(),mock(AgentInput.class),input->Flux.error(new IllegalStateException("fixture"))).blockLast()).isInstanceOf(IllegalStateException.class);
        verify(run).event(eq("AGENT_ERROR"),anyMap());verify(run,never()).event(eq("AGENT_CANCELLED"),anyMap());
    }
    @Test void anEmployeeCannotUseASupervisorToolAndDeniedCallNeverReachesTheNextHandler() {
        var run=mock(AgentJournal.Run.class);var agent=mock(Agent.class);when(agent.getName()).thenReturn("resource-management");
        var called=new java.util.concurrent.atomic.AtomicBoolean();
        var middleware=new AgentJournalMiddleware(run,actor);
        assertThatThrownBy(()->middleware.onActing(agent,RuntimeContext.empty(),new ActingInput(List.of(new ToolUseBlock("call-1","list_devices",Map.of()))),input->{called.set(true);return Flux.empty();}).blockLast())
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        assertThat(called.get()).isFalse();verify(run).event(eq("AUTHORIZATION_DENIED"),argThat(payload->"DENY".equals(payload.get("decision"))));
    }
    @Test void auditWriteFailureStopsAuthorizedToolBeforeExecution() {
        var run=mock(AgentJournal.Run.class);doThrow(new IllegalStateException("database unavailable")).when(run).event(anyString(),anyMap());
        var agent=mock(Agent.class);when(agent.getName()).thenReturn("detection-task");var called=new java.util.concurrent.atomic.AtomicBoolean();
        assertThatThrownBy(()->new AgentJournalMiddleware(run,actor).onActing(agent,RuntimeContext.empty(),new ActingInput(List.of(new ToolUseBlock("c1","get_my_detection_tasks",Map.of()))),input->{called.set(true);return Flux.empty();}).blockLast())
                .isInstanceOf(IllegalStateException.class);
        assertThat(called.get()).isFalse();
    }
    @Test void alertToolsRequireSupervisorAndSuccessfulAuthorizationAuditBeforeDispatch() {
        for(String name:List.of("list_device_alerts","get_device_alert","get_model_operations","get_system_health")) {
            var run=mock(AgentJournal.Run.class);var agent=mock(Agent.class);when(agent.getName()).thenReturn(name.equals("get_model_operations")?"model-ops":"resource-management");
            var called=new java.util.concurrent.atomic.AtomicBoolean();
            var input=new ActingInput(List.of(new ToolUseBlock("alert-call",name,Map.of(name.equals("get_model_operations")?"modelId":"alertId","PRIVATE_PARAMETER"))));
            assertThatThrownBy(()->new AgentJournalMiddleware(run,actor).onActing(agent,RuntimeContext.empty(),input,i->{called.set(true);return Flux.empty();}).blockLast())
                    .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
            assertThat(called.get()).isFalse();
            var boss=new AgentActor(2,"boss",AgentActor.Role.SUPERVISOR);reset(run);
            new AgentJournalMiddleware(run,boss).onActing(agent,RuntimeContext.empty(),input,i->{called.set(true);return Flux.empty();}).blockLast();
            assertThat(called.get()).isTrue();
            verify(run).event(eq("AUTHORIZATION_ALLOWED"),argThat(p->name.equals(p.get("tool"))&&"SINGLE_ENTERPRISE".equals(p.get("scope"))&&!p.toString().contains("PRIVATE_PARAMETER")));
            reset(run);called.set(false);doThrow(new IllegalStateException("audit unavailable")).when(run).event(anyString(),anyMap());
            assertThatThrownBy(()->new AgentJournalMiddleware(run,boss).onActing(agent,RuntimeContext.empty(),input,i->{called.set(true);return Flux.empty();}).blockLast()).isInstanceOf(IllegalStateException.class);
            assertThat(called.get()).isFalse();
        }
    }
}
