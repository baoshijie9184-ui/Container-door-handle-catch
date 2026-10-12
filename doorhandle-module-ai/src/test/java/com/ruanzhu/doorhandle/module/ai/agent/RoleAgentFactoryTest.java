package com.ruanzhu.doorhandle.module.ai.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.model.Model;
import io.agentscope.core.model.ModelRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.security.access.AccessDeniedException;
import java.nio.file.Path;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RoleAgentFactoryTest {
    @TempDir Path workspace;
    private final AgentActor employee = new AgentActor(1, "alice", AgentActor.Role.INSPECTOR);
    private final AgentActor supervisor = new AgentActor(2, "boss", AgentActor.Role.SUPERVISOR);

    @Test void mainActuallyDelegatesThroughSpecialistToolkitToBusinessFacade() {
        var model = mock(Model.class);
        when(model.getModelName()).thenReturn("role-toolkit-test");
        var responses = new java.util.concurrent.atomic.AtomicInteger();
        when(model.stream(anyList(), anyList(), any())).thenAnswer(invocation -> {
            int step = responses.getAndIncrement();
            io.agentscope.core.message.ContentBlock content = switch (step) {
                case 0 -> io.agentscope.core.message.ToolUseBlock.builder().id("delegate-1")
                        .name("delegate_detection_task").input(java.util.Map.of("question", "查询本人检测任务"))
                        .content("{\"question\":\"查询本人检测任务\"}").build();
                case 1 -> io.agentscope.core.message.ToolUseBlock.builder().id("query-1")
                        .name("get_my_detection_tasks").input(java.util.Map.of()).build();
                default -> io.agentscope.core.message.TextBlock.builder().text("本人暂无检测任务").build();
            };
            return reactor.core.publisher.Flux.just(io.agentscope.core.model.ChatResponse.builder()
                    .id("response-" + step).content(java.util.List.of(content)).build());
        });
        ModelRegistry.register("role-toolkit-test", model);
        var properties = new AgentScopeProperties();
        properties.setModel("role-toolkit-test");
        properties.setWorkspace(workspace.toString());
        var detection = mock(DetectionAgentReadApi.class);
        when(detection.tasks(employee, 1, 20, false)).thenReturn(new DetectionAgentReadApi.TaskPage(java.util.List.of(), 0, 1, 20));
        var factory = new RoleAgentFactory(properties, new BusinessToolkitFactory(detection,
                mock(ResourceAgentReadApi.class), mock(ModelAgentReadApi.class), new ObjectMapper()));
        var result = factory.create(employee, null).call("查询本人任务").block(java.time.Duration.ofSeconds(15));
        assertThat(result.getTextContent()).contains("暂无检测任务");
        verify(detection).tasks(employee, 1, 20, false);
        assertThat(responses.get()).isEqualTo(4);
    }

    private RoleAgentFactory factory() {
        var properties = new AgentScopeProperties();
        properties.setWorkspace(workspace.toString());
        return new RoleAgentFactory(properties, new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),
                mock(ResourceAgentReadApi.class), mock(ModelAgentReadApi.class), new ObjectMapper()));
    }
    @Test void roleAndInternalAgentRequestsAreCheckedBeforeModelCreation() {
        var factory = factory();
        assertThat(factory.resolveMainId(employee, "doorhandle-assistant")).isEqualTo("employee-main");
        assertThat(factory.resolveMainId(supervisor, "supervisor-assistant")).isEqualTo("supervisor-main");
        assertThatThrownBy(() -> factory.create(employee, "supervisor-main")).isInstanceOf(AccessDeniedException.class);
        assertThatThrownBy(() -> factory.create(employee, "model-ops")).isInstanceOf(AccessDeniedException.class);
    }
    @Test void mainAgentsHaveOnlyFourExplicitDelegatesAndNeverShareInstances() {
        try (var models = mockStatic(ModelRegistry.class)) {
            models.when(() -> ModelRegistry.resolve(anyString())).thenReturn(mock(Model.class));
            var factory = factory();
            for (var actor : new AgentActor[]{employee, supervisor}) {
                var first = factory.create(actor, null);
                var second = factory.create(actor, null);
                assertThat(first).isNotSameAs(second);
                assertThat(first.getToolkit()).isNotSameAs(second.getToolkit());
                assertThat(first.getToolkit().getToolNames()).containsExactlyInAnyOrderElementsOf(
                        RoleAgentCatalog.specialists(actor).stream().map(d -> "delegate_" + d.id().replace('-', '_')).toList());
            }
        }
    }
}
