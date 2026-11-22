package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournalMiddleware;
import com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime;
import com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.message.ToolUseBlock;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.model.ChatResponse;
import io.agentscope.core.model.Model;
import io.agentscope.core.tool.AgentTool;
import io.agentscope.core.tool.ToolCallParam;
import io.agentscope.core.tool.Toolkit;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.security.access.AccessDeniedException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.same;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AgentToolAccessTest {
    private final AgentActor employee = new AgentActor(28, "DET-0001", AgentActor.Role.INSPECTOR);
    private final BusinessUserDirectory users = mock(BusinessUserDirectory.class);
    private final Agent agent = mock(Agent.class);
    private final AtomicBoolean executed = new AtomicBoolean();

    @Test void authorizedReadExecutesWithoutAnApprovalOrJournal() {
        when(users.current(employee.userId(), employee.username()))
                .thenReturn(new BusinessUserDirectory.Identity(employee.userId(), employee.username(), false));
        var access = new AgentToolAccess(employee, users, Set.of("get_task_detail"), "", null);
        call(access, "get_task_detail", Map.of("taskId", "owned-task"));
        assertThat(executed).isTrue();
    }

    @Test void expiredRoleAndUnlistedToolsNeverReachExecution() {
        var supervisor = new AgentActor(19, "SUP-0001", AgentActor.Role.SUPERVISOR);
        when(users.current(supervisor.userId(), supervisor.username()))
                .thenReturn(new BusinessUserDirectory.Identity(supervisor.userId(), supervisor.username(), false));
        var access = new AgentToolAccess(supervisor, users, Set.of("propose_quality_assignment"), "", null);
        assertThatThrownBy(() -> call(access, "propose_quality_assignment", Map.of()))
                .isInstanceOf(AccessDeniedException.class);
        assertThatThrownBy(() -> call(access, "read_password", Map.of("confirmed", true)))
                .isInstanceOf(AccessDeniedException.class);
        assertThat(executed).isFalse();
    }

    @Test void fetchOnlyExecutesForAnExplicitCurrentUserUrl() {
        when(users.current(employee.userId(), employee.username()))
                .thenReturn(new BusinessUserDirectory.Identity(employee.userId(), employee.username(), false));
        var access = new AgentToolAccess(employee, users, Set.of(FetchMcpRuntime.TOOL),
                "请读取 https://example.com 的标题", null);
        assertThatThrownBy(() -> call(access, FetchMcpRuntime.TOOL, Map.of("url", "https://example.com/?data=extra")))
                .isInstanceOf(AccessDeniedException.class);
        assertThat(executed).isFalse();
        call(access, FetchMcpRuntime.TOOL, Map.of("url", "https://example.com/"));
        assertThat(executed).isTrue();
    }

    @ParameterizedTest @ValueSource(booleans={true,false})
    void actualSdkDoesNotAuditOrExecuteAnUnapprovedTool(boolean approved) throws Exception {
        when(users.current(employee.userId(),employee.username()))
                .thenReturn(new BusinessUserDirectory.Identity(employee.userId(),employee.username(),false));
        var events=new CopyOnWriteArrayList<String>();
        var run=mock(AgentJournal.Run.class);
        doAnswer(invocation->{events.add(invocation.getArgument(0));return null;}).when(run).event(anyString(),anyMap());
        var journal=new AgentJournalMiddleware(run,employee).withWorkbench(Set.of("lookup_record"));
        var workbench=mock(AgentWorkbenchService.Scope.class);
        var reached=new CountDownLatch(1);
        Sinks.One<Boolean> decision=Sinks.one();
        when(workbench.awaitToolApproval(any(),any(),same(journal),any(Runnable.class))).thenAnswer(invocation->{
            events.add("WAITING_FOR_APPROVAL");
            reached.countDown();
            return decision.asMono().flatMap(allow->{
                if(!allow)return Mono.error(new AccessDeniedException("工具调用已拒绝"));
                invocation.getArgument(3,Runnable.class).run();
                events.add("APPROVED_BY_USER");
                return Mono.empty();
            });
        });
        var toolkit=new Toolkit();
        toolkit.registerAgentTool(new AgentTool(){
            public String getName(){return "lookup_record";}
            public String getDescription(){return "Lookup a record";}
            public boolean isReadOnly(){return true;}
            public Map<String,Object> getParameters(){return Map.of("type","object","properties",Map.of());}
            public Mono<ToolResultBlock> callAsync(ToolCallParam param){
                executed.set(true);
                return Mono.just(ToolResultBlock.text("read complete"));
            }
        });
        var model=mock(Model.class);
        when(model.getModelName()).thenReturn("fixture-model");
        var rounds=new AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(invocation->{
            if(rounds.getAndIncrement()==0)return Flux.just(ChatResponse.builder()
                    .content(List.of(new ToolUseBlock("call-1","lookup_record",Map.of()))).finishReason("tool_calls").build());
            return Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("finished").build())).finishReason("stop").build());
        });
        var access=new AgentToolAccess(employee,users,Set.of("lookup_record"),"",journal,workbench);
        try(var nativeAgent=ReActAgent.builder().name("employee-main").model(model).toolkit(toolkit).maxIters(3)
                .middlewares(List.of(journal,access)).enableMetaTool(false).enableTaskList(false).build()){
            var done=nativeAgent.call("Read the record").toFuture();
            assertThat(reached.await(5,TimeUnit.SECONDS)).isTrue();
            assertThat(events).doesNotContain("TOOL_STARTED");
            assertThat(executed).isFalse();
            decision.tryEmitValue(approved);
            done.handle((result,error)->null).get(10,TimeUnit.SECONDS);
            if(approved){
                assertThat(executed).isTrue();
                assertThat(events).containsSubsequence("WAITING_FOR_APPROVAL","APPROVED_BY_USER","TOOL_STARTED","TOOL_COMPLETED");
            }else{
                assertThat(executed).isFalse();
                assertThat(events).contains("AUTHORIZATION_DENIED").doesNotContain("TOOL_STARTED","TOOL_COMPLETED");
            }
        }
    }

    private void call(AgentToolAccess access, String tool, Map<String,Object> input) {
        var invocation = new ActingInput(List.of(new ToolUseBlock("call-1", tool, input)));
        access.onActing(agent, RuntimeContext.empty(), invocation, ignored -> {
            executed.set(true);
            return Flux.empty();
        }).blockLast();
    }
}
