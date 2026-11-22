package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.ToolUseBlock;
import io.agentscope.core.middleware.ActingInput;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import reactor.core.publisher.Flux;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
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

    private void call(AgentToolAccess access, String tool, Map<String,Object> input) {
        var invocation = new ActingInput(List.of(new ToolUseBlock("call-1", tool, input)));
        access.onActing(agent, RuntimeContext.empty(), invocation, ignored -> {
            executed.set(true);
            return Flux.empty();
        }).blockLast();
    }
}
